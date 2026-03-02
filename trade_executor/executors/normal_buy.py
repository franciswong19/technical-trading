"""
normal_buy.py

Executor for NORMAL BUY request type.
- Place midprice or trailing stop orders
- Monitor every 10 min for fills
- On fill: 15-min timer then stop loss
- Recalculate qty if not filled
- At exchange cutoff: escalate to market
"""

import argparse
import sys
import os
import time
import json
from datetime import datetime

import pytz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from trade_executor.config import (
    BASE_CLIENT_ID, EXCHANGES, RESULTS_DIR, STATUS_DIR,
    NORMAL_CHECK_INTERVAL, DURATION_BEFORE_CLOSE, STOP_LOSS_DELAY,
)
from trade_executor.models.request import TradeRequest
from trade_executor.models.execution_result import ExecutionResult, AccountResult, TickerResult, stamp_ticker_fill, stamp_ticker_completion
from trade_executor.ibkr_client import IBKRClient, IBKRConnectionError, OrderRejectedError
from trade_executor.quantity_calculator import calculate_buy_qty, InsufficientCashError
from trade_executor.order_monitor import OrderMonitor
from trade_executor.stop_loss_manager import StopLossManager


def _write_fill_notification(request_id: str, ticker_result, status_dir: str) -> None:
    """Write a fill notification file to STATUS_DIR so the agent can report the fill immediately."""
    path = os.path.join(status_dir, f"{request_id}-{ticker_result.ticker}.filled.json")
    data = {
        'ticker': ticker_result.ticker,
        'action': ticker_result.action,
        'filled_qty': ticker_result.filled_qty,
        'avg_fill_price': ticker_result.avg_fill_price,
        'filled_at_local': ticker_result.filled_at_local,
        'filled_at_sgt': ticker_result.filled_at_sgt,
    }
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"[NormalBuy] Fill notification written: {path}")


def execute(request: TradeRequest, client_id_offset: int = 0) -> ExecutionResult:
    """Execute NORMAL BUY."""
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
        stop_mgr = StopLossManager(client, request.exchange)

        try:
            client.connect()
            trading_currency = EXCHANGES[request.exchange]['currency']
            portfolio_value = client.get_portfolio_value(trading_currency)
            cash_value = client.get_cash_value(trading_currency)
            pending_buy_value = client.get_pending_buy_value(request.exchange)
            available_cash = cash_value - pending_buy_value

            tp = request.ticker_params[0]
            ticker = tp.ticker
            ticker_result = TickerResult(ticker=ticker, action='BUY')

            try:
                # Get price and calculate qty
                price = client.get_current_price(ticker, request.exchange)
                qty = calculate_buy_qty(
                    portfolio_value, available_cash, tp.fulfillment_pct, price, ticker
                )
                ticker_result.target_qty = qty

                if qty <= 0:
                    ticker_result.error = f"Calculated qty is 0 (pv={portfolio_value:.2f}, pct={tp.fulfillment_pct}, price={price:.2f})"
                    account_result.ticker_results.append(ticker_result)
                else:
                    # Place initial order
                    if tp.initial_order_type == 'midprice':
                        trade = client.place_midprice_order(ticker, 'BUY', qty, request.exchange)
                        ticker_result.order_type_used = 'midprice'
                    elif tp.initial_order_type == 'trailing_stop':
                        trade = client.place_trailing_stop_order(
                            ticker, 'BUY', qty, tp.initial_trailing_pct, request.exchange
                        )
                        ticker_result.order_type_used = 'trailing_stop'
                    else:
                        trade = client.place_market_order(ticker, 'BUY', qty, request.exchange)
                        ticker_result.order_type_used = 'market'

                    # Set up monitor
                    monitor = OrderMonitor(
                        client, NORMAL_CHECK_INTERVAL, DURATION_BEFORE_CLOSE,
                        request.exchange,
                    )

                    # Define recalculation callback
                    def on_check(current_trade, current_ticker):
                        nonlocal qty
                        try:
                            new_price = client.get_current_price(current_ticker, request.exchange)
                            new_qty = calculate_buy_qty(
                                portfolio_value, available_cash, tp.fulfillment_pct, new_price, current_ticker
                            )
                            if new_qty != qty and new_qty > 0:
                                qty = new_qty
                                client.modify_order_qty(current_trade, new_qty)
                                ticker_result.target_qty = new_qty
                                print(f"[NormalBuy] Updated {current_ticker} qty to {new_qty} at ${new_price:.2f}")
                        except Exception as e:
                            print(f"[NormalBuy] Recalc error for {current_ticker}: {e}")
                        return None

                    # Monitor until fill or deadline
                    mon_result = monitor.monitor_until_fill_or_deadline(
                        trade, ticker, on_check_callback=on_check
                    )

                    if mon_result['filled']:
                        # Filled successfully
                        fill_price = client.get_fill_price(mon_result['trade'])
                        filled_qty = client.get_filled_qty(mon_result['trade'])
                        ticker_result.filled_qty = filled_qty
                        ticker_result.avg_fill_price = fill_price
                        stamp_ticker_fill(ticker_result, tz)
                        print(f"[NormalBuy] ORDER FILLED: {ticker} - {filled_qty} @ {fill_price:.4f}")
                        _write_fill_notification(request.request_id, ticker_result, STATUS_DIR)

                        # Wait 15 min then place stop loss. Use ib.sleep() (not time.sleep())
                        # so the asyncio event loop stays alive and the connection is maintained.
                        print(f"[NormalBuy] Waiting {STOP_LOSS_DELAY}s before placing stop loss for {ticker}...")
                        client.ib.sleep(STOP_LOSS_DELAY)
                        stop_result = stop_mgr.place_stop_loss_now(
                            ticker, filled_qty, fill_price,
                            tp.stop_type, tp.stop_fixed_price,
                        )
                        ticker_result.stop_loss_placed = stop_result['success']
                        ticker_result.stop_loss_price = stop_result['stop_price']

                    elif mon_result['deadline_reached']:
                        # Deadline: recalculate and escalate to market
                        try:
                            new_price = client.get_current_price(ticker, request.exchange)
                            new_qty = calculate_buy_qty(
                                portfolio_value, available_cash, tp.fulfillment_pct, new_price, ticker
                            )
                            if new_qty <= 0:
                                new_qty = qty

                            market_trade = monitor.escalate_to_market(
                                mon_result['trade'], ticker, 'BUY', new_qty
                            )
                            ticker_result.escalated_to_market = True
                            ticker_result.order_type_used = 'market'
                            ticker_result.target_qty = new_qty

                            filled = client.wait_for_fill(market_trade, timeout_seconds=60)
                            if filled:
                                fill_price = client.get_fill_price(market_trade)
                                filled_qty = client.get_filled_qty(market_trade)
                                ticker_result.filled_qty = filled_qty
                                ticker_result.avg_fill_price = fill_price
                                stamp_ticker_fill(ticker_result, tz)
                                print(f"[NormalBuy] ORDER FILLED (market escalation): {ticker} - {filled_qty} @ {fill_price:.4f}")
                                _write_fill_notification(request.request_id, ticker_result, STATUS_DIR)

                                print(f"[NormalBuy] Waiting {STOP_LOSS_DELAY}s before placing stop loss for {ticker}...")
                                client.ib.sleep(STOP_LOSS_DELAY)
                                stop_result = stop_mgr.place_stop_loss_now(
                                    ticker, filled_qty, fill_price,
                                    tp.stop_type, tp.stop_fixed_price,
                                )
                                ticker_result.stop_loss_placed = stop_result['success']
                                ticker_result.stop_loss_price = stop_result['stop_price']
                            else:
                                ticker_result.error = "Market order did not fill within 60s"
                                result.errors.append(f"{account_id}/{ticker}: Market order timeout")
                        except Exception as e:
                            ticker_result.error = f"Escalation failed: {e}"
                            result.errors.append(f"{account_id}/{ticker}: {e}")

                    account_result.ticker_results.append(ticker_result)

            except InsufficientCashError as e:
                ticker_result.error = str(e)
                result.errors.append(f"{account_id}/{ticker}: {e}")
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
            stop_mgr.cleanup()
            client.disconnect()

        result.account_results.append(account_result)

    # Determine overall status
    result.completed_at = datetime.now(tz).isoformat()
    if result.status != 'FAILED':
        if result.errors:
            result.status = 'PARTIAL'
        else:
            result.status = 'COMPLETED'

    return result


def main():
    parser = argparse.ArgumentParser(description='NORMAL BUY executor')
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
    print(f"\n[NormalBuy] Result written to {result_path}")
    print(f"[NormalBuy] Status: {result.status}")


if __name__ == '__main__':
    main()
