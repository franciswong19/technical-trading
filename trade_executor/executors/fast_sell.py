"""
fast_sell.py

Executor for FAST SELL request type.
Same as NORMAL SELL but with:
- 1-min check interval
- Timed deadline
- Midprice only
- Escalate 1 min before deadline
"""

import argparse
import sys
import os
from datetime import datetime

import pytz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from trade_executor.config import (
    BASE_CLIENT_ID, EXCHANGES, RESULTS_DIR, STATUS_DIR,
    FAST_CHECK_INTERVAL, DURATION_TIMED,
)
from trade_executor.models.request import TradeRequest
from trade_executor.models.execution_result import ExecutionResult, AccountResult, TickerResult, stamp_ticker_completion
from trade_executor.ibkr_client import IBKRClient, IBKRConnectionError, OrderRejectedError
from trade_executor.quantity_calculator import calculate_sell_qty
from trade_executor.order_monitor import OrderMonitor


def execute(request: TradeRequest, client_id_offset: int = 0) -> ExecutionResult:
    """Execute FAST SELL."""
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

    for i, account in enumerate(request.accounts):
        account_id = account['account_id']
        port = account['port']
        client_id = BASE_CLIENT_ID + client_id_offset + i

        account_result = AccountResult(account_id=account_id)
        client = IBKRClient(account_id, port, client_id)

        try:
            client.connect()

            tp = request.ticker_params[0]
            ticker = tp.ticker
            ticker_result = TickerResult(ticker=ticker, action='SELL')

            try:
                holdings = client.get_position_qty(ticker)
                qty = calculate_sell_qty(holdings, tp.fulfillment_pct, ticker)
                ticker_result.target_qty = qty

                if qty <= 0:
                    ticker_result.error = f"No shares to sell (holdings={holdings})"
                    account_result.ticker_results.append(ticker_result)
                else:
                    # Cancel any open orders for this ticker (e.g. stop-loss) before selling
                    # to prevent IBKR from treating the combined sell orders as a short sale
                    client.cancel_orders_for_ticker(ticker)

                    # FAST SELL always uses midprice
                    trade = client.place_midprice_order(ticker, 'SELL', qty, request.exchange)
                    ticker_result.order_type_used = 'midprice'

                    monitor = OrderMonitor(
                        client, FAST_CHECK_INTERVAL, DURATION_TIMED,
                        request.exchange,
                        deadline_minutes=request.duration_minutes,
                    )

                    mon_result = monitor.monitor_until_fill_or_deadline(trade, ticker)

                    if mon_result['filled']:
                        fill_price = client.get_fill_price(mon_result['trade'])
                        filled_qty = client.get_filled_qty(mon_result['trade'])
                        ticker_result.filled_qty = filled_qty
                        ticker_result.avg_fill_price = fill_price

                    elif mon_result['deadline_reached']:
                        market_trade = monitor.escalate_to_market(
                            mon_result['trade'], ticker, 'SELL', qty
                        )
                        ticker_result.escalated_to_market = True
                        ticker_result.order_type_used = 'market'

                        filled = client.wait_for_fill(market_trade, timeout_seconds=60)
                        if filled:
                            fill_price = client.get_fill_price(market_trade)
                            filled_qty = client.get_filled_qty(market_trade)
                            ticker_result.filled_qty = filled_qty
                            ticker_result.avg_fill_price = fill_price
                        else:
                            ticker_result.error = "Market order did not fill within 60s"
                            result.errors.append(f"{account_id}/{ticker}: Market order timeout")

                    account_result.ticker_results.append(ticker_result)

            except OrderRejectedError as e:
                ticker_result.error = str(e)
                result.errors.append(f"{account_id}/{ticker}: {e}")
                account_result.ticker_results.append(ticker_result)
            except Exception as e:
                ticker_result.error = str(e)
                result.errors.append(f"{account_id}/{ticker}: {e}")
                account_result.ticker_results.append(ticker_result)

            stamp_ticker_completion(ticker_result, tz)

        except IBKRConnectionError as e:
            result.errors.append(f"{account_id}: Connection failed - {e}")
            result.status = 'FAILED'
        finally:
            client.disconnect()

        result.account_results.append(account_result)

    result.completed_at = datetime.now(tz).isoformat()
    if result.status != 'FAILED':
        result.status = 'PARTIAL' if result.errors else 'COMPLETED'

    return result


def main():
    parser = argparse.ArgumentParser(description='FAST SELL executor')
    parser.add_argument('--request', required=True, help='Path to request JSON file')
    parser.add_argument('--client-id-offset', type=int, default=0, help='Offset for IBKR client ID (for parallel execution)')
    args = parser.parse_args()

    request = TradeRequest.from_json(args.request)

    result_path = os.path.join(RESULTS_DIR, f"{request.request_id}.json")
    if os.path.exists(result_path):
        print(f"ERROR: Result already exists for {request.request_id}. Aborting.")
        sys.exit(1)

    os.makedirs(RESULTS_DIR, exist_ok=True)
    os.makedirs(STATUS_DIR, exist_ok=True)

    result = execute(request, client_id_offset=args.client_id_offset)
    result.to_json(result_path)
    print(f"\n[FastSell] Result written to {result_path}")
    print(f"[FastSell] Status: {result.status}")


if __name__ == '__main__':
    main()
