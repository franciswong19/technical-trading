"""
abort.py

Abort in-flight trade requests by cancelling entry-side IBKR orders and writing
ABORTED result files. Stop-loss orders protecting already-filled positions are
intentionally preserved.

SELL_EVERYTHING_NOW requests cannot be aborted — tell the user to manage manually.

Usage:
    python -m trade_executor.abort --request-ids 20260307-001 20260307-002
    python -m trade_executor.abort --all
"""

import argparse
import glob
import json
import os
import sys
from datetime import datetime

from trade_executor.config import REQUESTS_DIR, RESULTS_DIR, STATUS_DIR, LIVE_PORT
from trade_executor.ibkr_client import IBKRClient, IBKRConnectionError
from trade_executor.models.request import TradeRequest
from trade_executor.models.execution_result import ExecutionResult

SNAPSHOT_CLIENT_ID = 599  # Used only for the final remaining-orders snapshot


def get_base_request_id(filepath: str) -> str:
    """Extract base request_id (YYYYMMDD-XXX) from a request file path."""
    stem = os.path.splitext(os.path.basename(filepath))[0]
    parts = stem.split('-')
    return '-'.join(parts[:2])


def find_request_files_for_ids(request_ids: list) -> list:
    """Find all request JSON files matching the given request IDs."""
    files = []
    for req_id in request_ids:
        pattern = os.path.join(REQUESTS_DIR, f'{req_id}*.json')
        matched = glob.glob(pattern)
        if not matched:
            print(f"[ABORT] No request files found for ID: {req_id}")
        files.extend(matched)
    return files


def find_all_inflight_request_files() -> list:
    """Find all request files that have no corresponding result file."""
    all_files = glob.glob(os.path.join(REQUESTS_DIR, '*.json'))
    inflight = []
    for f in all_files:
        base_id = get_base_request_id(f)
        result_path = os.path.join(RESULTS_DIR, f'{base_id}.json')
        if not os.path.exists(result_path):
            inflight.append(f)
    return inflight


def load_clientids_for_request_file(request_file: str) -> dict:
    """Load the {account_id: client_id} map written by the executor at startup.

    Returns {} if the file doesn't exist (executor hadn't started yet or crashed
    before writing it — caller must handle as MANUAL ACTION REQUIRED).
    """
    basename = os.path.splitext(os.path.basename(request_file))[0]
    clientids_path = os.path.join(STATUS_DIR, f'{basename}.clientids.json')
    if not os.path.exists(clientids_path):
        return {}
    with open(clientids_path) as f:
        return json.load(f)


def build_today_ticker_map() -> dict:
    """Build a map of ticker -> [request_ids] from today's request files.

    Used to annotate remaining active orders with the request ID they belong to.
    """
    today_prefix = datetime.now().strftime('%Y%m%d')
    pattern = os.path.join(REQUESTS_DIR, f'{today_prefix}-*.json')
    today_files = glob.glob(pattern)

    ticker_map = {}  # ticker -> [request_id, ...]
    for f in today_files:
        try:
            req = TradeRequest.from_json(f)
            for tp in req.ticker_params:
                ticker_map.setdefault(tp.ticker, [])
                if req.request_id not in ticker_map[tp.ticker]:
                    ticker_map[tp.ticker].append(req.request_id)
        except Exception:
            pass
    return ticker_map


def should_cancel_order(trade, request_type: str) -> bool:
    """Return True if this order is an entry order (should be cancelled).

    Entry orders: PEG MID, TRAIL, MKT (never STP)
    Stop-loss orders: STP (always, regardless of action direction)

    For NORMAL_SELL / FAST_SELL: entry orders are SELL PEG MID / SELL TRAIL / SELL MKT.
    A SELL STP on the same ticker is a stop-loss from a prior BUY fill — must be preserved.
    Filtering by action == 'SELL' alone is not enough; must also exclude STP order type.
    """
    action = trade.order.action      # 'BUY' or 'SELL'
    order_type = trade.order.orderType  # 'PEG MID', 'TRAIL', 'MKT', 'STP', etc.

    if request_type == 'HOT_POTATO':
        return True  # Cancel all — no traditional stop-loss structure
    elif request_type in ('NORMAL_BUY', 'FAST_BUY'):
        # Cancel BUY entry orders; preserve SELL STP stop-losses
        return action == 'BUY' and order_type != 'STP'
    elif request_type in ('NORMAL_SELL', 'FAST_SELL'):
        # Cancel SELL entry orders (PEG MID / TRAIL / MKT);
        # preserve SELL STP stop-losses from prior BUY fills
        return action == 'SELL' and order_type != 'STP'
    return True


def format_order_info(trade, ticker_to_request_ids: dict = None) -> str:
    """Format a trade for display, optionally annotating with today's request IDs."""
    order = trade.order
    contract = trade.contract
    price_info = ''
    if order.auxPrice and order.auxPrice > 0:
        price_info = f' @ ${order.auxPrice:.2f}'
    elif order.lmtPrice and order.lmtPrice > 0:
        price_info = f' @ ${order.lmtPrice:.2f}'

    annotation = ''
    if ticker_to_request_ids:
        req_ids = ticker_to_request_ids.get(contract.symbol)
        if req_ids:
            annotation = f' [today: {", ".join(sorted(req_ids))}]'

    return (
        f"{contract.symbol} — {order.action} {order.orderType}{price_info}"
        f" (order ID: {order.orderId}){annotation}"
    )


def abort_requests(request_files: list) -> None:
    """Cancel entry orders for the given request files and write ABORTED result files."""
    if not request_files:
        print("[ABORT] No request files to process.")
        return

    # Load all request objects; skip SELL_EVERYTHING_NOW
    requests_by_file = {}
    for f in request_files:
        try:
            req = TradeRequest.from_json(f)
        except Exception as e:
            print(f"[ABORT] ERROR loading {f}: {e}")
            continue

        if req.request_type in ('SELL_EVERYTHING_NOW', 'SELECTIVE_SELL_NOW'):
            print(
                f"[ABORT] SKIPPED {os.path.basename(f)}: {req.request_type} cannot be "
                f"aborted via this script — manage manually in IB Gateway."
            )
            continue

        requests_by_file[f] = req

    if not requests_by_file:
        print("[ABORT] No abortable request files found.")
        return

    today_ticker_map = build_today_ticker_map()

    # Build per-(client_id, account_id) work list
    # Key: (client_id, account_id) -> {'port': int, 'items': [(req, ticker_param)]}
    clientid_map = {}
    # Track accounts that have no clientId file (manual action required)
    missing_clientid = []  # [(account_id, request_file)]
    # Track all unique accounts for the final snapshot
    snapshot_accounts = {}  # account_id -> port

    for f, req in requests_by_file.items():
        clientids = load_clientids_for_request_file(f)
        for account in req.accounts:
            acct_id = account['account_id']
            port = account.get('port', LIVE_PORT)
            snapshot_accounts[acct_id] = port

            client_id = clientids.get(acct_id)
            if client_id is None:
                missing_clientid.append((acct_id, os.path.basename(f)))
                continue

            key = (client_id, acct_id)
            if key not in clientid_map:
                clientid_map[key] = {'port': port, 'items': []}
            for tp in req.ticker_params:
                clientid_map[key]['items'].append((req, tp))

    # Report any missing clientId files upfront
    for acct_id, fname in missing_clientid:
        print(
            f"[ABORT] MANUAL ACTION REQUIRED: No clientId file found for "
            f"{acct_id} / {fname} — executor may not have started yet. "
            f"Cancel entry orders manually via IB Gateway."
        )

    # Cancel entry orders — one IBKR connection per (client_id, account_id)
    cancelled_summary = {}   # account_id -> [formatted order strings]
    cancelling_statuses = {'PendingCancel', 'Cancelled', 'Inactive', 'ApiCancelled'}

    for (client_id, account_id), acct_data in clientid_map.items():
        port = acct_data['port']
        items = acct_data['items']
        client = IBKRClient(account_id=account_id, port=port, client_id=client_id)

        try:
            client.connect()
        except IBKRConnectionError as e:
            print(f"[ABORT] ERROR connecting to IBKR as clientId={client_id} "
                  f"for account {account_id}: {e}")
            continue

        try:
            cancelled_summary.setdefault(account_id, [])

            for req, tp in items:
                ticker = tp.ticker
                open_trades = client.ib.openTrades()
                ticker_trades = [t for t in open_trades if t.contract.symbol == ticker]
                to_cancel = [t for t in ticker_trades if should_cancel_order(t, req.request_type)]

                for trade in to_cancel:
                    try:
                        client.ib.cancelOrder(trade.order)
                        client.ib.sleep(0.5)
                        desc = format_order_info(trade)
                        cancelled_summary[account_id].append(desc)
                        print(f"[ABORT] Cancelled [{account_id}]: {desc}")
                    except Exception as e:
                        print(f"[ABORT] ERROR cancelling order for {ticker} "
                              f"({account_id}, clientId={client_id}): {e}")

                if to_cancel:
                    client.ib.sleep(2)
                    still_open = [
                        t for t in to_cancel
                        if t.orderStatus.status not in cancelling_statuses
                    ]
                    if still_open:
                        for t in still_open:
                            print(
                                f"[ABORT] MANUAL ACTION REQUIRED: Could not cancel "
                                f"{format_order_info(t)} for account {account_id} — "
                                f"cancel manually via IB Gateway"
                            )

        finally:
            client.disconnect()

    # Snapshot remaining open orders per account (using SNAPSHOT_CLIENT_ID=99)
    remaining_summary = {}   # account_id -> [formatted order strings]
    active_statuses = {'PreSubmitted', 'Submitted', 'PendingSubmit'}

    for account_id, port in snapshot_accounts.items():
        client = IBKRClient(account_id=account_id, port=port, client_id=SNAPSHOT_CLIENT_ID)
        try:
            client.connect()
        except IBKRConnectionError as e:
            print(f"[ABORT] ERROR connecting for snapshot (account {account_id}): {e}")
            continue
        try:
            remaining_summary[account_id] = [
                format_order_info(t, today_ticker_map)
                for t in client.ib.openTrades()
                if t.orderStatus.status in active_statuses
            ]
        finally:
            client.disconnect()

    # Write ABORTED result files
    aborted_request_ids = set()
    written_ids = set()
    for f, req in requests_by_file.items():
        req_id = req.request_id
        if req_id in written_ids:
            continue
        result_path = os.path.join(RESULTS_DIR, f'{req_id}.json')
        if os.path.exists(result_path):
            print(f"[ABORT] Result file already exists for {req_id} — skipping write.")
            written_ids.add(req_id)
            aborted_request_ids.add(req_id)
            continue
        try:
            result = ExecutionResult(
                request_id=req_id,
                status='ABORTED',
                completed_at=datetime.now().isoformat(),
                exchange=req.exchange,
                request_type=req.request_type,
                errors=['Aborted by user'],
            )
            result.to_json(result_path)
            print(f"[ABORT] Written ABORTED result: {result_path}")
            written_ids.add(req_id)
            aborted_request_ids.add(req_id)
        except Exception as e:
            print(f"[ABORT] ERROR writing result for {req_id}: {e}")

    # Print summary
    print("\n" + "=" * 60)
    print("ABORT SUMMARY")
    print("=" * 60)

    if aborted_request_ids:
        print(f"\nAborted request IDs: {', '.join(sorted(aborted_request_ids))}")

    for account_id in sorted(cancelled_summary.keys()):
        cancelled = cancelled_summary[account_id]
        if cancelled:
            print(f"\n[Account {account_id}] Entry orders cancelled ({len(cancelled)}):")
            for desc in cancelled:
                print(f"  - {desc}")
        else:
            print(f"\n[Account {account_id}] No entry orders found to cancel.")

    for account_id in sorted(remaining_summary.keys()):
        remaining = remaining_summary[account_id]
        if remaining:
            print(f"\n[Account {account_id}] Active orders still on IBKR ({len(remaining)}):")
            for desc in remaining:
                print(f"  - {desc}")
        else:
            print(f"\n[Account {account_id}] No active orders remaining on IBKR.")

    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description='Abort in-flight trade requests and cancel entry orders on IBKR'
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        '--request-ids', nargs='+', metavar='ID',
        help='Request ID(s) to abort (e.g. 20260307-001 20260307-002)'
    )
    group.add_argument(
        '--all', action='store_true',
        help='Abort all in-flight requests (those with no result file)'
    )
    args = parser.parse_args()

    if args.all:
        request_files = find_all_inflight_request_files()
        if not request_files:
            print("[ABORT] No in-flight requests found.")
            sys.exit(0)
        print(f"[ABORT] Found {len(request_files)} in-flight request file(s): "
              f"{[os.path.basename(f) for f in request_files]}")
    else:
        request_files = find_request_files_for_ids(args.request_ids)
        if not request_files:
            print("[ABORT] No request files found for the specified ID(s).")
            sys.exit(0)

    abort_requests(request_files)


if __name__ == '__main__':
    main()
