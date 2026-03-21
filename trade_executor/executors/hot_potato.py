"""
hot_potato.py

Executor for HOT POTATO request type.
Most complex executor - single ticker with cycle-based repetition.

Lifecycle:
1. Place initial order (midprice or trailing stop)
2. Monitor for fill (1 min interval, escalate to market 1 min before deadline)
3. On fill: 15-min timer -> place BOTH stop at buy price AND trailing stop
4. Monitor which stop triggers first (5 min interval)
5. On trigger: cancel other stop, increment counter, repeat with subsequent order type
6. Stop when counter >= threshold or at exchange cutoff (end-of-day handling)
"""

import argparse
import sys
import os
import time
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import pytz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from trade_executor.config import (
    BASE_CLIENT_ID, EXCHANGES, RESULTS_DIR, STATUS_DIR,
    FAST_CHECK_INTERVAL, NORMAL_CHECK_INTERVAL, THRESHOLD_CHECK_INTERVAL, HOT_POTATO_STOP_CHECK_INTERVAL,
    DURATION_BEFORE_CLOSE, DEFAULT_CYCLE_THRESHOLD, STOP_LOSS_DELAY,
)
from trade_executor.models.request import TradeRequest
from trade_executor.models.execution_result import ExecutionResult, AccountResult, TickerResult, stamp_ticker_fill, stamp_ticker_completion
from trade_executor.ibkr_client import IBKRClient, IBKRConnectionError, OrderRejectedError
from trade_executor.quantity_calculator import calculate_buy_qty, calculate_sell_qty, InsufficientCashError
from trade_executor.order_monitor import OrderMonitor
from trade_executor.stop_loss_manager import StopLossManager


def _write_fill_notification(request_id: str, ticker_result, seq_num: int, status_dir: str) -> None:
    """Write a per-cycle fill notification file to STATUS_DIR."""
    path = os.path.join(status_dir, f"{request_id}-{ticker_result.ticker}-cycle{seq_num}.filled.json")
    data = {
        'ticker': ticker_result.ticker,
        'action': ticker_result.action,
        'seq_num': seq_num,
        'filled_qty': ticker_result.filled_qty,
        'avg_fill_price': ticker_result.avg_fill_price,
        'filled_at_local': ticker_result.filled_at_local,
        'filled_at_sgt': ticker_result.filled_at_sgt,
    }
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"[HotPotato] Fill notification written: {path}")


def _execute_account(i: int, account: dict, request: TradeRequest, tz, client_id_offset: int) -> tuple:
    asyncio.set_event_loop(asyncio.new_event_loop())
    account_id = account['account_id']
    port = account['port']
    client_id = BASE_CLIENT_ID + client_id_offset + i

    account_result = AccountResult(account_id=account_id)
    errors = []
    client = IBKRClient(account_id, port, client_id)
    stop_mgr = StopLossManager(client, request.exchange)

    # HOT POTATO: single ticker only
    tp = request.ticker_params[0]
    ticker = tp.ticker
    cycle_threshold = tp.cycle_threshold or DEFAULT_CYCLE_THRESHOLD

    try:
        client.connect()
        trading_currency = EXCHANGES[request.exchange]['currency']
        portfolio_value = client.get_portfolio_value(trading_currency)
        cash_value = client.get_cash_value(trading_currency)
        pending_buy_value = client.get_pending_buy_value(request.exchange)
        available_cash = cash_value - pending_buy_value

        cycle_count = 0
        all_ticker_results = []

        # If entering SELL cycles, clear any pre-existing stops on the ticker first.
        # Prevents IBKR treating the combined sell orders as a short sale.
        if request.transaction_type == 'SELL':
            client.cancel_orders_for_ticker(ticker)
            print(f"[HotPotato] Cancelled existing orders for {ticker} before SELL cycles")

        # Compute the exchange cutoff time
        cutoff_monitor = OrderMonitor(
            client, FAST_CHECK_INTERVAL, DURATION_BEFORE_CLOSE,
            request.exchange,
        )
        deadline = cutoff_monitor.get_deadline()

        while cycle_count < cycle_threshold:
            seq_num = cycle_count + 1
            ticker_result = TickerResult(
                ticker=ticker,
                action=request.transaction_type,
                seq_num=seq_num,
            )

            # Check if we're past the exchange cutoff
            now = datetime.now(tz)
            if now >= deadline:
                print(f"[HotPotato] Deadline reached, stopping cycles at count={cycle_count}")
                break

            try:
                # Calculate qty
                price = client.get_current_price(ticker, request.exchange)

                if request.transaction_type == 'BUY':
                    qty = calculate_buy_qty(
                        portfolio_value, available_cash, tp.fulfillment_pct, price, ticker
                    )
                else:
                    holdings = client.get_position_qty(ticker)
                    qty = calculate_sell_qty(holdings, tp.fulfillment_pct, ticker)

                ticker_result.target_qty = qty

                if qty <= 0:
                    ticker_result.error = f"Calculated qty is 0 at cycle {seq_num}"
                    stamp_ticker_completion(ticker_result, tz)
                    all_ticker_results.append(ticker_result)
                    break

                # Place order: initial for first cycle, subsequent for later cycles
                if cycle_count == 0 and tp.initial_order_type == 'trailing_stop_threshold':
                    # ----------------------------------------------------------------
                    # TRAILING STOP WITH THRESHOLD PRICE (cycle 0 only)
                    # Poll price every 10 min until condition met or near deadline.
                    # BUY: price < threshold → place trailing stop
                    # SELL: price > threshold → place trailing stop
                    # At last check window: condition met → market order, else break
                    # ----------------------------------------------------------------
                    threshold_price = tp.initial_threshold_price
                    is_buy = request.transaction_type == 'BUY'
                    condition = (lambda p: p < threshold_price) if is_buy else (lambda p: p > threshold_price)
                    direction_desc = f"< {threshold_price:.2f}" if is_buy else f"> {threshold_price:.2f}"

                    threshold_monitor = OrderMonitor(
                        client, THRESHOLD_CHECK_INTERVAL, DURATION_BEFORE_CLOSE,
                        request.exchange,
                    )

                    print(f"[HotPotato] Cycle {seq_num}: waiting for price {direction_desc} before placing trailing stop for {ticker}...")
                    threshold_result = threshold_monitor.wait_for_threshold_or_deadline(
                        lambda: client.get_current_price(ticker, request.exchange),
                        condition,
                    )
                    current_price = threshold_result['price']

                    if threshold_result['near_deadline']:
                        if threshold_result['condition_met']:
                            # Last check, condition met → market order
                            print(f"[HotPotato] Cycle {seq_num}: last check condition met at price={current_price:.2f}, placing market order for {ticker}")
                            if is_buy:
                                qty = calculate_buy_qty(portfolio_value, available_cash, tp.fulfillment_pct, current_price, ticker)
                            else:
                                holdings = client.get_position_qty(ticker)
                                qty = calculate_sell_qty(holdings, tp.fulfillment_pct, ticker)
                            ticker_result.target_qty = qty
                            if qty <= 0:
                                ticker_result.error = f"Calculated qty is 0 at threshold trigger (cycle {seq_num})"
                                stamp_ticker_completion(ticker_result, tz)
                                all_ticker_results.append(ticker_result)
                                break
                            trade = client.place_market_order(ticker, request.transaction_type, qty, request.exchange)
                            ticker_result.order_type_used = 'market'
                            ticker_result.escalated_to_market = True
                            filled = client.wait_for_fill(trade, timeout_seconds=60)
                            mon_result = {'filled': filled, 'trade': trade, 'deadline_reached': False}
                            if not filled:
                                ticker_result.error = "Market escalation failed (threshold last check)"
                                stamp_ticker_completion(ticker_result, tz)
                                all_ticker_results.append(ticker_result)
                                break
                        else:
                            # Threshold not met at deadline → abort cycle loop
                            print(f"[HotPotato] Cycle {seq_num}: threshold not met at deadline for {ticker} (price={current_price:.2f}), stopping")
                            ticker_result.error = f"Threshold not met at deadline (price={current_price:.2f}), no order placed"
                            stamp_ticker_completion(ticker_result, tz)
                            all_ticker_results.append(ticker_result)
                            break
                    else:
                        # Condition met before deadline → place trailing stop, monitor with fast interval
                        print(f"[HotPotato] Cycle {seq_num}: threshold met at price={current_price:.2f}, placing trailing stop for {ticker}")
                        if is_buy:
                            qty = calculate_buy_qty(portfolio_value, available_cash, tp.fulfillment_pct, current_price, ticker)
                        else:
                            holdings = client.get_position_qty(ticker)
                            qty = calculate_sell_qty(holdings, tp.fulfillment_pct, ticker)
                        ticker_result.target_qty = qty
                        if qty <= 0:
                            ticker_result.error = f"Calculated qty is 0 at threshold trigger (cycle {seq_num})"
                            stamp_ticker_completion(ticker_result, tz)
                            all_ticker_results.append(ticker_result)
                            break
                        trade = client.place_trailing_stop_order(
                            ticker, request.transaction_type, qty, tp.initial_trailing_pct, request.exchange
                        )
                        ticker_result.order_type_used = 'trailing_stop'

                        fill_monitor = OrderMonitor(
                            client, FAST_CHECK_INTERVAL, DURATION_BEFORE_CLOSE,
                            request.exchange,
                        )
                        mon_result = fill_monitor.monitor_until_fill_or_deadline(trade, ticker)

                elif cycle_count == 0 and tp.initial_order_type == 'fixed_stop':
                    # ----------------------------------------------------------------
                    # FIXED STOP (cycle 0 only)
                    # Poll price every 5 min until condition met or near deadline.
                    # BUY: price >= threshold → place market order
                    # SELL: price <= threshold → place market order
                    # At last check window: condition met → market order, else break
                    # ----------------------------------------------------------------
                    threshold_price = tp.initial_threshold_price
                    is_buy = request.transaction_type == 'BUY'
                    condition = (lambda p: p >= threshold_price) if is_buy else (lambda p: p <= threshold_price)
                    direction_desc = f">= {threshold_price:.2f}" if is_buy else f"<= {threshold_price:.2f}"

                    threshold_monitor = OrderMonitor(
                        client, THRESHOLD_CHECK_INTERVAL, DURATION_BEFORE_CLOSE,
                        request.exchange,
                    )

                    print(f"[HotPotato] Cycle {seq_num}: waiting for price {direction_desc} to trigger fixed stop market order for {ticker}...")
                    threshold_result = threshold_monitor.wait_for_threshold_or_deadline(
                        lambda: client.get_current_price(ticker, request.exchange),
                        condition,
                    )
                    current_price = threshold_result['price']

                    if threshold_result['condition_met']:
                        # Condition met (early or at last check) → market order
                        print(f"[HotPotato] Cycle {seq_num}: fixed stop triggered at price={current_price:.2f}, placing market order for {ticker}")
                        if is_buy:
                            qty = calculate_buy_qty(portfolio_value, available_cash, tp.fulfillment_pct, current_price, ticker)
                        else:
                            holdings = client.get_position_qty(ticker)
                            qty = calculate_sell_qty(holdings, tp.fulfillment_pct, ticker)
                        ticker_result.target_qty = qty
                        if qty <= 0:
                            ticker_result.error = f"Calculated qty is 0 at fixed stop trigger (cycle {seq_num})"
                            stamp_ticker_completion(ticker_result, tz)
                            all_ticker_results.append(ticker_result)
                            break
                        trade = client.place_market_order(ticker, request.transaction_type, qty, request.exchange)
                        ticker_result.order_type_used = 'market'
                        filled = client.wait_for_fill(trade, timeout_seconds=60)
                        mon_result = {'filled': filled, 'trade': trade, 'deadline_reached': False}
                        if not filled:
                            ticker_result.error = "Market order failed at fixed stop trigger"
                            stamp_ticker_completion(ticker_result, tz)
                            all_ticker_results.append(ticker_result)
                            break
                    else:
                        # near_deadline + condition not met → abort cycle loop
                        print(f"[HotPotato] Cycle {seq_num}: fixed stop not triggered at deadline for {ticker} (price={current_price:.2f}), stopping")
                        ticker_result.error = f"Fixed stop not triggered at deadline (price={current_price:.2f}), no order placed"
                        stamp_ticker_completion(ticker_result, tz)
                        all_ticker_results.append(ticker_result)
                        break

                else:
                    # Standard order placement (midprice / trailing_stop / market)
                    # Also handles all subsequent cycles (cycle_count > 0)
                    if cycle_count == 0:
                        order_type = tp.initial_order_type
                        trail_pct = tp.initial_trailing_pct
                    else:
                        order_type = tp.subsequent_order_type or 'trailing_stop'
                        trail_pct = tp.subsequent_trailing_pct

                    if order_type == 'midprice':
                        trade = client.place_midprice_order(
                            ticker, request.transaction_type, qty, request.exchange
                        )
                        ticker_result.order_type_used = 'midprice'
                    elif order_type == 'trailing_stop':
                        trade = client.place_trailing_stop_order(
                            ticker, request.transaction_type, qty, trail_pct, request.exchange
                        )
                        ticker_result.order_type_used = 'trailing_stop'
                    else:
                        trade = client.place_market_order(
                            ticker, request.transaction_type, qty, request.exchange
                        )
                        ticker_result.order_type_used = 'market'

                    # Monitor for fill (1 min interval, escalate 1 min before deadline)
                    fill_monitor = OrderMonitor(
                        client, FAST_CHECK_INTERVAL, DURATION_BEFORE_CLOSE,
                        request.exchange,
                    )

                    mon_result = fill_monitor.monitor_until_fill_or_deadline(trade, ticker)

                if not mon_result['filled'] and mon_result['deadline_reached']:
                    # Escalate to market
                    new_price = client.get_current_price(ticker, request.exchange)
                    if request.transaction_type == 'BUY':
                        new_qty = calculate_buy_qty(
                            portfolio_value, available_cash, tp.fulfillment_pct, new_price, ticker
                        )
                    else:
                        holdings = client.get_position_qty(ticker)
                        new_qty = calculate_sell_qty(holdings, tp.fulfillment_pct, ticker)

                    if new_qty <= 0:
                        new_qty = qty

                    market_trade = fill_monitor.escalate_to_market(
                        mon_result['trade'], ticker, request.transaction_type, new_qty
                    )
                    ticker_result.escalated_to_market = True
                    ticker_result.target_qty = new_qty

                    filled = client.wait_for_fill(market_trade, timeout_seconds=60)
                    if filled:
                        mon_result['filled'] = True
                        mon_result['trade'] = market_trade
                    else:
                        ticker_result.error = "Market escalation failed"
                        stamp_ticker_completion(ticker_result, tz)
                        all_ticker_results.append(ticker_result)
                        break

                if not mon_result['filled']:
                    ticker_result.error = "Order not filled"
                    stamp_ticker_completion(ticker_result, tz)
                    all_ticker_results.append(ticker_result)
                    break

                # Order filled
                fill_price = client.get_fill_price(mon_result['trade'])
                filled_qty = client.get_filled_qty(mon_result['trade'])
                ticker_result.filled_qty = filled_qty
                ticker_result.avg_fill_price = fill_price
                stamp_ticker_fill(ticker_result, tz)
                _write_fill_notification(request.request_id, ticker_result, seq_num, STATUS_DIR)
                print(f"[HotPotato] Cycle {seq_num} filled: {ticker} {request.transaction_type} "
                      f"{filled_qty} @ {fill_price:.4f}. Waiting {STOP_LOSS_DELAY}s before stops...")
                client.ib.sleep(STOP_LOSS_DELAY)

                # Check deadline again after 15-min wait
                if datetime.now(tz) >= deadline:
                    ticker_result.stop_loss_placed = False
                    stamp_ticker_completion(ticker_result, tz)
                    all_ticker_results.append(ticker_result)
                    break

                # Place BOTH stops: fixed at X.X% offset (Stop type 1) AND trailing stop (Stop type 2)
                stop_result = stop_mgr.place_trailing_and_fixed_stops(
                    ticker, filled_qty, fill_price, tp.stop_adhoc_trailing_pct,
                    stop_type1_pct=tp.stop_type1_pct,
                    transaction_type=request.transaction_type,
                )
                ticker_result.stop_loss_placed = stop_result['success']
                if request.transaction_type == 'BUY':
                    ticker_result.stop_loss_price = round(fill_price * (1 - tp.stop_type1_pct / 100), 2)
                else:
                    ticker_result.stop_loss_price = round(fill_price * (1 + tp.stop_type1_pct / 100), 2)

                stamp_ticker_completion(ticker_result, tz)
                all_ticker_results.append(ticker_result)

                if not stop_result['success']:
                    errors.append(f"{account_id}/{ticker}: Stop placement failed at cycle {seq_num}")
                    break

                # Monitor which stop triggers first (5-min intervals)
                stop_trades = []
                if stop_result['fixed_stop_trade']:
                    stop_trades.append({'name': 'fixed', 'trade': stop_result['fixed_stop_trade']})
                if stop_result['trailing_stop_trade']:
                    stop_trades.append({'name': 'trailing', 'trade': stop_result['trailing_stop_trade']})

                stop_monitor = OrderMonitor(
                    client, HOT_POTATO_STOP_CHECK_INTERVAL, DURATION_BEFORE_CLOSE,
                    request.exchange,
                )

                trigger_result = stop_monitor.wait_for_stop_trigger(stop_trades)

                if trigger_result['triggered_name']:
                    # One stop triggered - cancel the other
                    for remaining in trigger_result['remaining']:
                        try:
                            client.cancel_order(remaining['trade'])
                        except Exception:
                            pass

                    cycle_count += 1
                    print(f"[HotPotato] Cycle {seq_num} {trigger_result['triggered_name']} stop triggered. Count: {cycle_count}/{cycle_threshold}")
                else:
                    # Deadline reached while monitoring stops
                    for st in stop_trades:
                        try:
                            client.cancel_order(st['trade'])
                        except Exception:
                            pass
                    break

            except InsufficientCashError as e:
                ticker_result.error = str(e)
                errors.append(f"{account_id}/{ticker}: {e}")
                stamp_ticker_completion(ticker_result, tz)
                all_ticker_results.append(ticker_result)
                break
            except OrderRejectedError as e:
                ticker_result.error = str(e)
                errors.append(f"{account_id}/{ticker}: {e}")
                stamp_ticker_completion(ticker_result, tz)
                all_ticker_results.append(ticker_result)
                break
            except Exception as e:
                ticker_result.error = str(e)
                errors.append(f"{account_id}/{ticker}: {e}")
                stamp_ticker_completion(ticker_result, tz)
                all_ticker_results.append(ticker_result)
                break

        # End-of-day handling
        # Use transaction_type_before_close if set, otherwise fall back to transaction_type.
        # transaction_type = direction of each cycle's entry order.
        # transaction_type_before_close = desired position state at end-of-day.
        eod_txn = request.transaction_type_before_close or request.transaction_type
        try:
            current_position = client.get_position_qty(ticker)
            print(f"[HotPotato] End-of-day: {ticker} position={current_position}, "
                  f"eod_txn={eod_txn}")

            if eod_txn == 'BUY' and current_position <= 0:
                # End-of-day target is to be holding — buy if not already holding
                price = client.get_current_price(ticker, request.exchange)
                qty = calculate_buy_qty(
                    portfolio_value, available_cash, tp.fulfillment_pct, price, ticker
                )
                if qty > 0:
                    eod_trade = client.place_market_order(ticker, 'BUY', qty, request.exchange)
                    client.wait_for_fill(eod_trade, timeout_seconds=60)
                    eod_result = TickerResult(
                        ticker=ticker, action='BUY',
                        seq_num=len(all_ticker_results) + 1,
                        target_qty=qty,
                        filled_qty=client.get_filled_qty(eod_trade),
                        avg_fill_price=client.get_fill_price(eod_trade),
                        order_type_used='market',
                    )
                    stamp_ticker_completion(eod_result, tz)
                    all_ticker_results.append(eod_result)

            elif eod_txn == 'SELL' and current_position > 0:
                # End-of-day target is to be flat — clear any remaining stops first,
                # then market sell to avoid IBKR treating combined sells as a short sale.
                client.cancel_orders_for_ticker(ticker)
                eod_trade = client.place_market_order(
                    ticker, 'SELL', current_position, request.exchange
                )
                client.wait_for_fill(eod_trade, timeout_seconds=60)
                eod_result = TickerResult(
                    ticker=ticker, action='SELL',
                    seq_num=len(all_ticker_results) + 1,
                    target_qty=current_position,
                    filled_qty=client.get_filled_qty(eod_trade),
                    avg_fill_price=client.get_fill_price(eod_trade),
                    order_type_used='market',
                )
                stamp_ticker_completion(eod_result, tz)
                all_ticker_results.append(eod_result)

            # BUY + holding -> do nothing (already in desired state)
            # SELL + not holding -> do nothing (already flat)

        except Exception as e:
            errors.append(f"{account_id}/{ticker}: End-of-day handling failed - {e}")

        account_result.ticker_results = all_ticker_results

    except IBKRConnectionError as e:
        errors.append(f"{account_id}: Connection failed - {e}")
    finally:
        stop_mgr.cleanup()
        client.disconnect()

    return account_result, errors


def execute(request: TradeRequest, client_id_offset: int = 0) -> ExecutionResult:
    """Execute HOT POTATO."""
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
            pool.submit(_execute_account, i, account, request, tz, client_id_offset): account
            for i, account in enumerate(request.accounts)
        }
        for f in as_completed(futures):
            account_result, errors = f.result()
            result.account_results.append(account_result)
            result.errors.extend(errors)

    result.completed_at = datetime.now(tz).isoformat()
    result.status = 'PARTIAL' if result.errors else 'COMPLETED'

    return result


def main():
    parser = argparse.ArgumentParser(description='HOT POTATO executor')
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

    clientids = {
        account['account_id']: BASE_CLIENT_ID + args.client_id_offset + i
        for i, account in enumerate(request.accounts)
    }
    clientids_path = os.path.join(STATUS_DIR, f"{request.request_id}.clientids.json")
    with open(clientids_path, 'w') as f:
        json.dump(clientids, f)

    result = execute(request, client_id_offset=args.client_id_offset)
    result.to_json(result_path)
    print(f"\n[HotPotato] Result written to {result_path}")
    print(f"[HotPotato] Status: {result.status}")


if __name__ == '__main__':
    main()
