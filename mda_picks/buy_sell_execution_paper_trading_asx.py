"""
Minimal-change automated trading script (paper trading) for IBKR.

Key points:
- Fixed $25,000 per buy (ASX testing)
- TP/SL placed on Day 1 immediately after BUY fill (same as Day 2)
- Daily TP/SL update at TP_SL_UPDATE_TIME — cancels only existing SELL orders (TP/SL) per symbol
- Forced sales (market sell) on Day 6 during FORCED_SALE window
- Daily buys during BUY window using POTD from Google Sheets (first column)
- Script can be started earlier than windows; scheduler will wait
"""
import asyncio
import math
import time
from datetime import datetime
import pytz
import gspread
from apscheduler.schedulers.background import BackgroundScheduler
from ib_insync import IB, Stock, LimitOrder, MarketOrder, ExecutionFilter
import pandas as pd
import pandas_market_calendars as mcal

asx = mcal.get_calendar('ASX')

# -------------------------
# CONFIGURATION (easy to change)
# -------------------------
HOST = '127.0.0.1'
PORT = 7497
CLIENT_ID = 1
TARGET_ACCOUNT = 'DUO713598'

SPREADSHEET_ID = '1gEHjNEI-0Zr-_cMzHsOnEurcA0q2rGtdDgEyRKFgY38'
TAB_NAME = 'selected_MDA'
GSHEETS_CREDS = 'service_account_key.json'  # service account JSON

TIMEZONE = 'Australia/Sydney'

# Times
TP_SL_UPDATE_TIME = (12, 31)      # TP/SL daily update
FORCED_SALE_START = (12, 32)     # forced sale window start
FORCED_SALE_END   = (12, 33)     # forced sale window end
DAILY_BUY_START   = (12, 34)     # buy window start
DAILY_BUY_END     = (12, 35)     # buy window end

# Trading params
FIXED_TRADE_AMOUNT = 25000       # $25k per ticker (ASX testing)
SLEEP_INTERVAL = 15              # polling delay (seconds)
AGGRESSIVE_ADJ = 1.001           # multiply last price by this for aggressive limit buys
# -------------------------

# ---------- IB / Sheets helpers ----------
def connect_ibkr():
    """Connect and return IB instance."""
    ib = IB()
    ib.connect(HOST, PORT, clientId=CLIENT_ID, timeout=5)
    print(f"[{datetime.now()}] Connected to IBKR (clientId={CLIENT_ID})")
    return ib

# ---------- asyncio helper ----------
def ensure_event_loop():
    """Ensure there is an asyncio event loop in the current thread."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop

def get_positions(ib):
    """Return positions filtered for TARGET_ACCOUNT."""
    positions = ib.positions()
    filtered = [p for p in positions if p.account == TARGET_ACCOUNT]
    syms = [p.contract.symbol for p in filtered]
    print(f"[{datetime.now()}] Current positions: {syms}")
    return filtered

def get_positions_with_buy_dates(ib):
    """Return dict of conId -> buy datetime."""
    ex_filter = ExecutionFilter()
    loop = ensure_event_loop()
    executions = loop.run_until_complete(ib.reqExecutionsAsync(ex_filter))
    executions = [ex for ex in executions if ex.execution.acctNumber == TARGET_ACCOUNT]
    buy_dates = {}
    for ex in executions:
        if ex.execution.side == 'BOT':
            conId = ex.execution.conId
            buy_dates[conId] = pd.to_datetime(ex.execution.time).date()
    return buy_dates

def get_potd_from_gsheet():
    """Read POTD (first column) from Google Sheets tab."""
    gc = gspread.service_account(filename=GSHEETS_CREDS)
    sh = gc.open_by_key(SPREADSHEET_ID)
    ws = sh.worksheet(TAB_NAME)
    data = ws.col_values(1)
    potd = [d.strip() for d in data if d.strip()]
    print(f"[{datetime.now()}] POTD: {potd}")
    return potd

def trading_days_since(buy_date, today):
    schedule = asx.schedule(start_date=buy_date, end_date=today)
    return len(schedule.index) - 1

# ---------- Order helpers ----------
def cancel_sell_orders_for_symbol(ib, symbol):
    """Cancel only SELL orders for this symbol (TP/SL)."""
    open_orders = ib.openOrders()
    canceled = 0
    for trade in open_orders:
        order = trade.order
        contract = trade.contract
        try:
            if contract and contract.symbol == symbol and order.action.upper() == 'SELL':
                ib.cancelOrder(order)
                canceled += 1
                print(f"[{datetime.now()}] Canceled SELL order for {symbol} (orderId={order.orderId})")
        except Exception as e:
            print(f"[{datetime.now()}] Error cancelling order for {symbol}: {e}")
    if canceled == 0:
        print(f"[{datetime.now()}] No SELL orders to cancel for {symbol}")
    return canceled

def place_limit_order(ib, symbol, qty, action, limit_price):
    """Place a simple LMT order and return the trade object."""
    contract = Stock(symbol, 'ASX', 'AUD')
    order = LimitOrder(action, qty, limit_price)
    trade = ib.placeOrder(contract, order)
    print(f"[{datetime.now()}] Placed {action} LIMIT for {symbol} qty={qty} @ {limit_price:.2f} (orderId={order.orderId})")
    return trade

def wait_for_full_fill(ib, trade, qty, window_end_dt):
    """Wait until the trade is fully filled or window ends."""
    while True:
        if trade.isDone():
            status = trade.orderStatus.status
            filled = getattr(trade.orderStatus, 'filled', None)
            print(f"[{datetime.now()}] Order status: {status}, filled={filled}")
            if status and status.upper() == 'FILLED':
                return True
            if filled is not None and filled >= qty:
                return True
            return False
        now = datetime.now(pytz.timezone(TIMEZONE))
        if now >= window_end_dt:
            print(f"[{datetime.now()}] Window end reached; order not fully filled.")
            return False
        time.sleep(1)

# ---------- TP/SL logic ----------
def tp_sl_prices_from_ref(ref_price, day_number):
    if day_number in (1, 2):
        tp = ref_price * 1.2
        sl = ref_price * 0.85
    elif day_number == 3:
        tp = ref_price * 1.15
        sl = ref_price * 0.9
    else:  # day 4 & 5
        tp = ref_price * 1.10
        sl = ref_price * 0.9
    return tp, sl

def place_tp_sl_for_symbol(ib, symbol, qty, ref_price, day_number):
    cancel_sell_orders_for_symbol(ib, symbol)
    tp, sl = tp_sl_prices_from_ref(ref_price, day_number)
    contract = Stock(symbol, 'ASX', 'AUD')
    tp_order = LimitOrder('SELL', qty, round(tp, 2))
    sl_order = LimitOrder('SELL', qty, round(sl, 2))
    ib.placeOrder(contract, tp_order)
    ib.placeOrder(contract, sl_order)
    print(f"[{datetime.now()}] Placed TP/SL for {symbol} qty={qty} | TP={tp:.2f} SL={sl:.2f}")

# ---------- Scheduled tasks ----------
def update_tp_sl_daily(ib):
    ensure_event_loop()
    tz = pytz.timezone(TIMEZONE)
    today = datetime.now(tz).date()
    print(f"[{datetime.now()}] Running daily TP/SL update...")
    positions = get_positions(ib)
    buy_dates = get_positions_with_buy_dates(ib)
    for pos in positions:
        symbol = pos.contract.symbol
        buy_date = buy_dates.get(pos.contract.conId)
        if not buy_date:
            print(f"[{datetime.now()}] No buy date for {symbol} — skipping.")
            continue
        day_number = (today - buy_date).days + 1
        if day_number >= 6:
            print(f"[{datetime.now()}] {symbol} is day {day_number} (>=6) — handled by forced sale.")
            continue
        ref_price = pos.marketPrice if pos.marketPrice else None
        if not ref_price:
            ticker = ib.reqMktData(pos.contract)
            time.sleep(0.5)
            ref_price = getattr(ticker, 'last', float('nan'))
            if math.isnan(ref_price):
                print(f"[{datetime.now()}] No valid market price for {symbol} — skipping.")
                continue
        place_tp_sl_for_symbol(ib, symbol, int(pos.position), ref_price, day_number)

def execute_forced_sales_window(ib):
    ensure_event_loop()
    tz = pytz.timezone(TIMEZONE)
    start_h, start_m = FORCED_SALE_START
    end_h, end_m = FORCED_SALE_END
    print(f"[{datetime.now()}] Forced sale window starting ({FORCED_SALE_START} -> {FORCED_SALE_END})")
    while True:
        now = datetime.now(tz)
        in_window = ((now.hour > start_h or (now.hour == start_h and now.minute >= start_m)) and
                     (now.hour < end_h or (now.hour == end_h and now.minute <= end_m)))
        if in_window:
            positions = get_positions(ib)
            buy_dates = get_positions_with_buy_dates(ib)
            today = now.date()
            for pos in positions:
                symbol = pos.contract.symbol
                buy_date = buy_dates.get(pos.contract.conId)
                if buy_date:
                    tdays = trading_days_since(buy_date, today)
                    if tdays >= 5:  # 6th trading day
                        qty = int(pos.position)
                        if qty <= 0:
                            continue
                        order = MarketOrder('SELL', qty)
                        ib.placeOrder(pos.contract, order)
                        print(f"[{datetime.now()}] Forced MARKET SELL placed for {symbol} qty={qty}.")
            time.sleep(SLEEP_INTERVAL)
        else:
            print(f"[{datetime.now()}] Forced sale window ended/exited.")
            break

def execute_daily_buys_window(ib):
    """
    Repeatedly run during DAILY_BUY_START -> DAILY_BUY_END.
    For each POTD not already in account:
      - compute qty = floor(FIXED_TRADE_AMOUNT / last_price)
      - place LIMIT BUY at last * AGGRESSIVE_ADJ
      - wait for full fill until window end; if filled -> place TP/SL for day 1
      - if not filled by window end -> leave buy order (no TP/SL)
    """

    # Ensure event loop exists in this thread
    ensure_event_loop()

    tz = pytz.timezone(TIMEZONE)
    start_h, start_m = DAILY_BUY_START
    end_h, end_m = DAILY_BUY_END
    print(f"[{datetime.now()}] Daily buy window starting (window {DAILY_BUY_START} -> {DAILY_BUY_END})")

    while True:
        now = datetime.now(tz)
        in_window = ((now.hour > start_h or (now.hour == start_h and now.minute >= start_m)) and
                     (now.hour < end_h or (now.hour == end_h and now.minute <= end_m)))
        if in_window:
            potd = get_potd_from_gsheet()
            positions = get_positions(ib)
            existing = {p.contract.symbol for p in positions}
            to_buy = [s for s in potd if s not in existing]

            if not to_buy:
                print(f"[{datetime.now()}] No new symbols to buy this run.")
            else:
                window_end_dt = datetime(now.year, now.month, now.day, end_h, end_m, tzinfo=tz)
                for symbol in to_buy:
                    contract = Stock(symbol, 'ASX', 'AUD')
                    ticker = ib.reqMktData(contract, '', False, False)  # normal request
                    time.sleep(1)  # allow ticker to update

                    last_price = getattr(ticker, 'last', None)

                    # Fallback to delayed/close price if real-time last_price is unavailable
                    if last_price is None or math.isnan(last_price):
                        last_price = getattr(ticker, 'close', None)
                        if last_price is not None:
                            print(f"[{datetime.now()}] Using delayed/close price for {symbol}: {last_price}")
                        else:
                            print(f"[{datetime.now()}] No valid market price for {symbol} even in close — skipping.")
                            continue

                    qty = math.floor(FIXED_TRADE_AMOUNT / last_price)

                    # ASX minimum marketable parcel (~AUD 500)
                    if qty * last_price < 500:
                        qty = math.ceil(500 / last_price)

                    if qty <= 0:
                        print(f"[{datetime.now()}] Qty computed as 0 for {symbol} (@{last_price}) — skipping.")
                        continue

                    limit_price = round(last_price * AGGRESSIVE_ADJ, 2)
                    trade = place_limit_order(ib, symbol, qty, 'BUY', limit_price)
                    filled = wait_for_full_fill(ib, trade, qty, window_end_dt)

                    if filled:
                        # Place TP/SL for Day 1 immediately (same as Day 2)
                        place_tp_sl_for_symbol(ib, symbol, qty, last_price, day_number=1)
                        print(f"[{datetime.now()}] Buy filled & TP/SL placed for {symbol}.")
                    else:
                        print(f"[{datetime.now()}] Buy for {symbol} not fully filled in window — TP/SL NOT placed.")
            time.sleep(SLEEP_INTERVAL)
        else:
            print(f"[{datetime.now()}] Buy window ended/exited.")
            break


# ---------- Main / scheduler ----------
def main():
    ib = connect_ibkr()
    tz = pytz.timezone(TIMEZONE)
    scheduler = BackgroundScheduler(timezone=TIMEZONE)

    scheduler.add_job(lambda: update_tp_sl_daily(ib), 'cron',
                      hour=TP_SL_UPDATE_TIME[0], minute=TP_SL_UPDATE_TIME[1])
    print(f"[{datetime.now()}] Scheduled TP/SL daily update at {TP_SL_UPDATE_TIME} {TIMEZONE}")

    scheduler.add_job(lambda: execute_forced_sales_window(ib), 'cron',
                      hour=FORCED_SALE_START[0], minute=FORCED_SALE_START[1])
    print(f"[{datetime.now()}] Scheduled forced sale window start at {FORCED_SALE_START} {TIMEZONE}")

    scheduler.add_job(lambda: execute_daily_buys_window(ib), 'cron',
                      hour=DAILY_BUY_START[0], minute=DAILY_BUY_START[1])
    print(f"[{datetime.now()}] Scheduled daily buy window start at {DAILY_BUY_START} {TIMEZONE}")

    scheduler.start()
    print(f"[{datetime.now()}] Scheduler started. Script running and waiting for windows...")

    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        print(f"[{datetime.now()}] Stopping scheduler and disconnecting IB...")
        scheduler.shutdown()
        ib.disconnect()
        print(f"[{datetime.now()}] Shutdown complete.")

if __name__ == '__main__':
    main()
