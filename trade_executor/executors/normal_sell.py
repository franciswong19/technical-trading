"""
normal_sell.py

Executor for NORMAL SELL request type.
- Place midprice or trailing stop orders
- Monitor every 10 min for fills
- At exchange cutoff: escalate to market
"""

import argparse
import sys
import os
import json
from datetime import datetime

import pytz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from trade_executor.config import (
    BASE_CLIENT_ID, EXCHANGES, RESULTS_DIR, STATUS_DIR,
    NORMAL_CHECK_INTERVAL, DURATION_BEFORE_CLOSE,
)
from trade_executor.models.request import TradeRequest
from trade_executor.models.execution_result import ExecutionResult, AccountResult, TickerResult, stamp_ticker_fill, stamp_ticker_completion
from trade_executor.ibkr_client import IBKRClient, IBKRConnectionError, OrderRejectedError
from trade_executor.quantity_calculator import calculate_sell_qty
from trade_executor.order_monitor import OrderMonitor


def execute(request: TradeRequest, client_id_offset: int = 0) -> ExecutionResult:
    """Execute NORMAL SELL."""
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
                if tp.initial_order_type == 'trailing_stop_threshold':
                    # ----------------------------------------------------------------
                    # TRAILING STOP WITH THRESHOLD PRICE
                    # Poll price every 10 min. Only place an order when price > threshold.
                    # At the last check window (15 min before close):
                    #   - condition met  → market order
                    #   - condition not met → no order, exit
                    # ----------------------------------------------------------------
                    threshold_price = tp.initial_threshold_price
                    monitor = OrderMonitor(
                        client, NORMAL_CHECK_INTERVAL, DURATION_BEFORE_CLOSE,
                        request.exchange,
                    )

                    print(f"[NormalSell] Waiting for price > {threshold_price:.2f} before placing trailing stop for {ticker}...")
                    threshold_result = monitor.wait_for_threshold_or_deadline(
                        lambda: client.get_current_price(ticker, request.exchange),
                        lambda p: p > threshold_price,
                    )
                    current_price = threshold_result['price']

                    if threshold_result['near_deadline']:
                        if threshold_result['condition_met']:
                            # Last check, condition met → market sell
                            print(f"[NormalSell] Last check: price={current_price:.2f} > threshold={threshold_price:.2f}, placing market order for {ticker}")
                            holdings = client.get_position_qty(ticker)
                            qty = calculate_sell_qty(holdings, tp.fulfillment_pct, ticker)
                            ticker_result.target_qty = qty
                            if qty > 0:
                                client.cancel_orders_for_ticker(ticker)
                                market_trade = client.place_market_order(ticker, 'SELL', qty, request.exchange)
                                ticker_result.order_type_used = 'market'
                                ticker_result.escalated_to_market = True
                                filled = client.wait_for_fill(market_trade, timeout_seconds=60)
                                if filled:
                                    fill_price = client.get_fill_price(market_trade)
                                    filled_qty = client.get_filled_qty(market_trade)
                                    ticker_result.filled_qty = filled_qty
                                    ticker_result.avg_fill_price = fill_price
                                    stamp_ticker_fill(ticker_result, tz)
                                    print(f"[NormalSell] ORDER FILLED (threshold market): {ticker} - {filled_qty} @ {fill_price:.4f}")
                                else:
                                    ticker_result.error = "Market order did not fill within 60s"
                                    result.errors.append(f"{account_id}/{ticker}: Market order timeout")
                            else:
                                ticker_result.error = f"No shares to sell at threshold trigger (holdings={holdings}, pct={tp.fulfillment_pct})"
                        else:
                            # Last check, condition not met → no order placed
                            print(f"[NormalSell] Threshold not met at deadline for {ticker} (price={current_price:.2f} <= threshold={threshold_price:.2f}), no order placed")
                            ticker_result.error = f"Threshold not met at deadline (price={current_price:.2f} <= threshold={threshold_price:.2f})"
                    else:
                        # Condition met before deadline → place trailing stop and monitor normally
                        print(f"[NormalSell] Threshold met: price={current_price:.2f} > {threshold_price:.2f}, placing trailing stop for {ticker}")
                        holdings = client.get_position_qty(ticker)
                        qty = calculate_sell_qty(holdings, tp.fulfillment_pct, ticker)
                        ticker_result.target_qty = qty
                        if qty > 0:
                            client.cancel_orders_for_ticker(ticker)
                            trade = client.place_trailing_stop_order(
                                ticker, 'SELL', qty, tp.initial_trailing_pct, request.exchange
                            )
                            ticker_result.order_type_used = 'trailing_stop'

                            mon_result = monitor.monitor_until_fill_or_deadline(trade, ticker)

                            if mon_result['filled']:
                                fill_price = client.get_fill_price(mon_result['trade'])
                                filled_qty = client.get_filled_qty(mon_result['trade'])
                                ticker_result.filled_qty = filled_qty
                                ticker_result.avg_fill_price = fill_price
                                stamp_ticker_fill(ticker_result, tz)
                                print(f"[NormalSell] {ticker} sold: {filled_qty} @ ${fill_price:.4f}")

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
                                    stamp_ticker_fill(ticker_result, tz)
                                else:
                                    ticker_result.error = "Market order did not fill within 60s"
                                    result.errors.append(f"{account_id}/{ticker}: Market order timeout")
                        else:
                            ticker_result.error = f"No shares to sell at threshold trigger (holdings={holdings}, pct={tp.fulfillment_pct})"

                    account_result.ticker_results.append(ticker_result)

                else:
                    # ----------------------------------------------------------------
                    # STANDARD ORDER TYPES: midprice / trailing_stop / market
                    # ----------------------------------------------------------------
                    # Get current holdings
                    holdings = client.get_position_qty(ticker)
                    qty = calculate_sell_qty(holdings, tp.fulfillment_pct, ticker)
                    ticker_result.target_qty = qty

                    if qty <= 0:
                        ticker_result.error = f"No shares to sell (holdings={holdings}, pct={tp.fulfillment_pct})"
                        account_result.ticker_results.append(ticker_result)
                    else:
                        # Cancel any open orders for this ticker (e.g. stop-loss) before selling
                        # to prevent IBKR from treating the combined sell orders as a short sale
                        client.cancel_orders_for_ticker(ticker)

                        # Place initial order
                        if tp.initial_order_type == 'midprice':
                            trade = client.place_midprice_order(ticker, 'SELL', qty, request.exchange)
                            ticker_result.order_type_used = 'midprice'
                        elif tp.initial_order_type == 'trailing_stop':
                            trade = client.place_trailing_stop_order(
                                ticker, 'SELL', qty, tp.initial_trailing_pct, request.exchange
                            )
                            ticker_result.order_type_used = 'trailing_stop'
                        else:
                            trade = client.place_market_order(ticker, 'SELL', qty, request.exchange)
                            ticker_result.order_type_used = 'market'

                        # Set up monitor
                        monitor = OrderMonitor(
                            client, NORMAL_CHECK_INTERVAL, DURATION_BEFORE_CLOSE,
                            request.exchange,
                        )

                        # Monitor until fill or deadline
                        mon_result = monitor.monitor_until_fill_or_deadline(trade, ticker)

                        if mon_result['filled']:
                            fill_price = client.get_fill_price(mon_result['trade'])
                            filled_qty = client.get_filled_qty(mon_result['trade'])
                            ticker_result.filled_qty = filled_qty
                            ticker_result.avg_fill_price = fill_price
                            print(f"[NormalSell] {ticker} sold: {filled_qty} @ ${fill_price:.2f}")

                        elif mon_result['deadline_reached']:
                            # Escalate to market
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
    parser = argparse.ArgumentParser(description='NORMAL SELL executor')
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

    ticker = request.ticker_params[0].ticker
    clientids = {
        account['account_id']: BASE_CLIENT_ID + args.client_id_offset + i
        for i, account in enumerate(request.accounts)
    }
    clientids_path = os.path.join(STATUS_DIR, f"{request.request_id}-{ticker}.clientids.json")
    with open(clientids_path, 'w') as f:
        json.dump(clientids, f)

    result = execute(request, client_id_offset=args.client_id_offset)
    result.to_json(result_path)
    print(f"\n[NormalSell] Result written to {result_path}")
    print(f"[NormalSell] Status: {result.status}")


if __name__ == '__main__':
    main()
