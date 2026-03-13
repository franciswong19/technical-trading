"""
selective_sell_now.py

Executor for SELECTIVE SELL NOW request type.
Cancels open orders for specified tickers, then market sells those positions.
Tickers not found in the portfolio are logged as non-fatal warnings and skipped.
"""

import argparse
import sys
import os
from datetime import datetime

import pytz

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from trade_executor.config import (
    BASE_CLIENT_ID, EXCHANGES, RESULTS_DIR, STATUS_DIR,
)
from trade_executor.models.request import TradeRequest
from trade_executor.models.execution_result import ExecutionResult, AccountResult, TickerResult, stamp_ticker_completion
from trade_executor.ibkr_client import IBKRClient, IBKRConnectionError


def execute(request: TradeRequest) -> ExecutionResult:
    """Execute SELECTIVE SELL NOW.

    1. For each account: connect
    2. Cancel open orders for each target ticker
    3. Get all positions
    4. Cross-reference: target tickers missing from positions → warn and skip
    5. Place market sell for every matched position
    6. Wait for fills (max 60s each)
    """
    exchange_cfg = EXCHANGES[request.exchange]
    tz = pytz.timezone(exchange_cfg['timezone'])
    started_at = datetime.now(tz).isoformat()

    result = ExecutionResult(
        request_id=request.request_id,
        status='PENDING',
        started_at=started_at,
        exchange=request.exchange,
        request_type=request.request_type,
    )

    target_tickers = [tp.ticker for tp in request.ticker_params]

    for i, account in enumerate(request.accounts):
        account_id = account['account_id']
        port = account['port']
        client_id = BASE_CLIENT_ID + i

        account_result = AccountResult(account_id=account_id)

        client = IBKRClient(account_id, port, client_id)
        try:
            client.connect()

            # Cancel open orders for each target ticker
            for symbol in target_tickers:
                cancelled = client.cancel_orders_for_ticker(symbol)
                print(f"[SelectiveSell] Cancelled {cancelled} open orders for {symbol} ({account_id})")

            # Get all positions
            positions = client.get_positions()
            positions_by_symbol = {pos['symbol']: pos for pos in positions}

            # Cross-reference: warn on missing tickers, build sell list
            pending = []
            for symbol in target_tickers:
                pos = positions_by_symbol.get(symbol)
                if pos is None or pos['position'] <= 0:
                    warning = f"{symbol}: not in portfolio — skipped"
                    result.errors.append(warning)
                    print(f"[SelectiveSell] WARNING: {warning}")
                    continue

                qty = pos['position']
                ticker_result = TickerResult(
                    ticker=symbol,
                    action='SELL',
                    target_qty=qty,
                    order_type_used='market',
                )

                try:
                    trade = client.place_market_order(symbol, 'SELL', qty, request.exchange)
                    pending.append((symbol, qty, trade, ticker_result))
                    print(f"[SelectiveSell] Placed market sell for {symbol}: {qty} shares")
                except Exception as e:
                    ticker_result.error = str(e)
                    result.errors.append(f"{account_id}/{symbol}: {e}")
                    stamp_ticker_completion(ticker_result, tz)
                    account_result.ticker_results.append(ticker_result)

            # Wait for all fills
            for symbol, qty, trade, ticker_result in pending:
                try:
                    filled = client.wait_for_fill(trade, timeout_seconds=60)

                    if filled:
                        ticker_result.filled_qty = client.get_filled_qty(trade)
                        ticker_result.avg_fill_price = client.get_fill_price(trade)
                        print(f"[SelectiveSell] Sold {symbol}: {ticker_result.filled_qty} @ ${ticker_result.avg_fill_price:.2f}")
                    else:
                        ticker_result.filled_qty = client.get_filled_qty(trade)
                        ticker_result.error = f"Fill timeout after 60s (partial: {ticker_result.filled_qty}/{qty})"
                        result.errors.append(f"{account_id}/{symbol}: {ticker_result.error}")

                except Exception as e:
                    ticker_result.error = str(e)
                    result.errors.append(f"{account_id}/{symbol}: {e}")

                stamp_ticker_completion(ticker_result, tz)
                account_result.ticker_results.append(ticker_result)

        except IBKRConnectionError as e:
            result.errors.append(f"{account_id}: Connection failed - {e}")
            result.status = 'FAILED'
        finally:
            client.disconnect()

        result.account_results.append(account_result)

    # Determine overall status
    completed_at = datetime.now(tz).isoformat()
    result.completed_at = completed_at

    if result.status != 'FAILED':
        # "not in portfolio" warnings are non-fatal; only order/fill errors cause PARTIAL
        non_warning_errors = [
            e for e in result.errors
            if 'not in portfolio' not in e
        ]
        if non_warning_errors:
            result.status = 'PARTIAL'
        else:
            result.status = 'COMPLETED'

    return result


def main():
    parser = argparse.ArgumentParser(description='SELECTIVE SELL NOW executor')
    parser.add_argument('--request', required=True, help='Path to request JSON file')
    args = parser.parse_args()

    request = TradeRequest.from_json(args.request)

    # Check for existing result (duplicate prevention)
    result_path = os.path.join(RESULTS_DIR, f"{request.request_id}.json")
    if os.path.exists(result_path):
        print(f"ERROR: Result already exists for {request.request_id}. Aborting.")
        sys.exit(1)

    # Ensure output directories exist
    os.makedirs(RESULTS_DIR, exist_ok=True)
    os.makedirs(STATUS_DIR, exist_ok=True)

    result = execute(request)
    result.to_json(result_path)
    print(f"\n[SelectiveSell] Result written to {result_path}")
    print(f"[SelectiveSell] Status: {result.status}")


if __name__ == '__main__':
    main()
