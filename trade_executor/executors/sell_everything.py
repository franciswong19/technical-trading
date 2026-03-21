"""
sell_everything.py

Executor for SELL EVERYTHING NOW request type.
Cancels all open orders, then market sells all positions.
"""

import argparse
import sys
import os
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
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


def _execute_account(i: int, account: dict, request: TradeRequest, tz) -> tuple:
    asyncio.set_event_loop(asyncio.new_event_loop())
    account_id = account['account_id']
    port = account['port']
    client_id = BASE_CLIENT_ID + i

    account_result = AccountResult(account_id=account_id)
    errors = []

    client = IBKRClient(account_id, port, client_id)
    try:
        client.connect()

        # Cancel all open orders
        cancelled = client.cancel_all_orders()
        print(f"[SellAll] Cancelled {cancelled} open orders for {account_id}")

        # Get all positions
        positions = client.get_positions()
        if not positions:
            print(f"[SellAll] No positions to sell for {account_id}")

        # Phase 1: Place ALL market sell orders at once
        pending = []
        for pos in positions:
            symbol = pos['symbol']
            qty = pos['position']

            if qty <= 0:
                continue

            ticker_result = TickerResult(
                ticker=symbol,
                action='SELL',
                target_qty=qty,
                order_type_used='market',
            )

            try:
                trade = client.place_market_order(symbol, 'SELL', qty, request.exchange)
                pending.append((symbol, qty, trade, ticker_result))
                print(f"[SellAll] Placed market sell for {symbol}: {qty} shares")
            except Exception as e:
                ticker_result.error = str(e)
                errors.append(f"{account_id}/{symbol}: {e}")
                stamp_ticker_completion(ticker_result, tz)
                account_result.ticker_results.append(ticker_result)

        # Phase 2: Wait for all fills
        for symbol, qty, trade, ticker_result in pending:
            try:
                filled = client.wait_for_fill(trade, timeout_seconds=60)

                if filled:
                    ticker_result.filled_qty = client.get_filled_qty(trade)
                    ticker_result.avg_fill_price = client.get_fill_price(trade)
                    print(f"[SellAll] Sold {symbol}: {ticker_result.filled_qty} @ ${ticker_result.avg_fill_price:.2f}")
                else:
                    ticker_result.filled_qty = client.get_filled_qty(trade)
                    ticker_result.error = f"Fill timeout after 60s (partial: {ticker_result.filled_qty}/{qty})"
                    errors.append(f"{account_id}/{symbol}: {ticker_result.error}")

            except Exception as e:
                ticker_result.error = str(e)
                errors.append(f"{account_id}/{symbol}: {e}")

            stamp_ticker_completion(ticker_result, tz)
            account_result.ticker_results.append(ticker_result)

    except IBKRConnectionError as e:
        errors.append(f"{account_id}: Connection failed - {e}")
    finally:
        client.disconnect()

    return account_result, errors


def execute(request: TradeRequest) -> ExecutionResult:
    """Execute SELL EVERYTHING NOW.

    1. For each account (in parallel): connect
    2. Cancel all open orders
    3. Get all positions
    4. Place market sell for every position
    5. Wait for fills (max 60s each)
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

    with ThreadPoolExecutor(max_workers=len(request.accounts)) as pool:
        futures = {
            pool.submit(_execute_account, i, account, request, tz): account
            for i, account in enumerate(request.accounts)
        }
        for f in as_completed(futures):
            account_result, errors = f.result()
            result.account_results.append(account_result)
            result.errors.extend(errors)

    # Determine overall status
    result.completed_at = datetime.now(tz).isoformat()
    if result.errors:
        result.status = 'PARTIAL'
    else:
        result.status = 'COMPLETED'

    return result


def main():
    parser = argparse.ArgumentParser(description='SELL EVERYTHING NOW executor')
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
    print(f"\n[SellAll] Result written to {result_path}")
    print(f"[SellAll] Status: {result.status}")


if __name__ == '__main__':
    main()
