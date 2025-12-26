"""
Automated US stock trading script (paper trading, IBKR).

Key points:
- Fixed $25,000 per buy
- TP/SL placed on Day 1 immediately after BUY fill (same as Day 2)
- Daily TP/SL update at TP_SL_UPDATE_TIME — cancels only existing SELL orders (TP/SL)
- Forced sales (market sell) on Day 6 during FORCED_SALE window
- Daily buys during BUY window using POTD from Google Sheets (first column)
- Uses snapshot mode for delayed US prices
- Buys/sells executed as MARKET orders
"""

import asyncio
import math
import time
from datetime import datetime
import pytz
import gspread
from apscheduler.schedulers.background import BackgroundScheduler
from ib_insync import IB, Stock, MarketOrder, ExecutionFilter
import pandas as pd
import pandas_market_calendars as mcal

# ---------- Configuration ----------
HOST = '127.0.0.1'
PORT = 7497
CLIENT_ID = 1
TARGET_ACCOUNT = 'DUO713598'

SPREADSHEET_ID = '1gEHjNEI-0Zr-_cMzHsOnEurcA0q2rGtdDgEyRKFgY38'
TAB_NAME = 'selected_MDA'
GSHEETS_CREDS = 'service_account_key.json'

TIMEZONE = 'US/Eastern'

TP_SL_UPDATE_TIME = (13, 51)
FORCED_SALE_START = (13, 51)
FORCED_SALE_END   = (13, 52)
DAILY_BUY_START   = (13, 51)
DAILY_BUY_END     = (13, 52)

FIXED_TRADE_AMOUNT = 25000
SLEEP_INTERVAL = 15

usa = mcal.get_calendar('NYSE')

# ---------- IB / Sheets helpers ----------
def connect_ibkr():
    ib = IB()
    ib.connect(HOST, PORT, clientId=CLIENT_ID, timeout=5)
    print(f"[{datetime.now()}] Connected to IBKR (clientId={CLIENT_ID})")
    # Force delayed US data (snapshot will always work)
    ib.reqMarketDataType(3)
    return ib

def ensure_event_loop():
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
    positions = ib.positions()
    filtered = [p for p in positions if p.account == TARGET_ACCOUNT]
    syms = [p.contract.symbol for p in filtered]
    print(f"[{datetime.now()}] Current positions: {syms}")
    return filtered

def get_positions_with_buy_dates(ib):
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
    gc = gspread.service_account(filename=GSHEETS_CREDS)
    sh = gc.open_by_key(SPREADSHEET_ID)
    ws = sh.worksheet(TAB_NAME)
    data = ws.col_values(1)
    potd = [d.strip() for d in data if d.strip()]
    print(f"[{datetime.now()}] POTD: {potd}")
    # Return as list of dicts for snapshot function
    return [{"symbol": s, "exchange": "SMART", "currency": "USD"} for s in potd]

def trading_days_since(buy_date, today):
    schedule = usa.schedule(start_date=buy_date, end_date=today)
    return len(schedule.index) - 1

# ---------- Order helpers ----------
def cancel_sell_orders_for_symbol(ib, symbol):
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

def place_market_order(ib, symbol, qty, action):
    contract = Stock(symbol, 'SMART', 'USD')
    order = MarketOrder(action, qty)
    trade = ib.placeOrder(contract, order)
    print(f"[{datetime.now()}] Placed {action} MARKET order for {symbol} qty={qty} (orderId={order.orderId})")
    return trade

# ---------- TP/SL ----------
def tp_sl_prices_from_ref(ref_price, day_number):
    if day_number in (1, 2):
        tp = ref_price * 1.2
        sl = ref_price * 0.85
    elif day_number == 3:
        tp = ref_price * 1.15
        sl = ref_price * 0.9
    else:
        tp = ref_price * 1.10
        sl = ref_price * 0.9
    return tp, sl

def place_tp_sl_for_symbol(ib, symbol, qty, ref_price, day_number):
    cancel_sell_orders_for_symbol(ib, symbol)
    tp, sl = tp_sl_prices_from_ref(ref_price, day_number)
    contract = Stock(symbol, 'SMART', 'USD')
    tp_order = MarketOrder('SELL', qty)  # Market order for TP
    sl_order = MarketOrder('SELL', qty)  # Market order for SL
    ib.placeOrder(contract, tp_order)
    ib.placeOrder(contract, sl_order)
    print(f"[{datetime.now()}] Placed TP/SL MARKET orders for {symbol} qty={qty}")

# ---------- Scheduled tasks ----------
def update_tp_sl_daily(ib):
    ensure_event_loop()
    tz = pytz.timezone(TIMEZONE)
    today = datetime.now(tz).date()
    positions = get_positions(ib)
    buy_dates = get_positions_with_buy_dates(ib)
    for pos in positions:
        symbol = pos.contract.symbol
        buy_date = buy_dates.get(pos.contract.conId)
        if not buy_date:
            continue
        day_number = (today - buy_date).days + 1
        if day_number >= 6:
            continue
        # Snapshot price
        ticker = ib.reqMktData(pos.contract, snapshot=True)
        ib.sleep(2)
        ref_price = ticker.last or ticker.close
        if not ref_price or math.isnan(ref_price):
            print(f"No valid market price for {symbol} — skipping TP/SL")
            continue
        place_tp_sl_for_symbol(ib, symbol, int(pos.position), ref_price, day_number)

def execute_forced_sales_window(ib):
    ensure_event_loop()
    tz = pytz.timezone(TIMEZONE)
    start_h, start_m = FORCED_SALE_START
    end_h, end_m = FORCED_SALE_END
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
                    if tdays >= 5:
                        qty = int(pos.position)
                        if qty <= 0:
                            continue
                        place_market_order(ib, symbol, qty, 'SELL')
            time.sleep(SLEEP_INTERVAL)
        else:
            break

def execute_daily_buys_window(ib):
    """
    Repeatedly run during DAILY_BUY_START -> DAILY_BUY_END.
    For each POTD not already in account:
      - compute qty = floor(FIXED_TRADE_AMOUNT / last_price)
      - place MARKET BUY immediately
      - place TP/SL for Day 1 immediately after fill
    """

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
            potd = get_potd_from_gsheet()  # list of dicts: [{"symbol":..., "exchange":..., "currency":...}]
            positions = get_positions(ib)
            existing = {p.contract.symbol for p in positions}
            to_buy = [s for s in potd if s["symbol"] not in existing]

            if not to_buy:
                print(f"[{datetime.now()}] No new symbols to buy this run.")
            else:
                window_end_dt = datetime(now.year, now.month, now.day, end_h, end_m, tzinfo=tz)
                for s in to_buy:
                    symbol = s["symbol"]
                    print(f"Running numbers for {symbol} right now.")

                    contract = Stock(symbol, s["exchange"], s["currency"])

                    print(f"{contract}")
                    # Request snapshot (delayed) price
                    ib.reqMarketDataType(3)  # delayed price
                    ticker = ib.reqMktData(contract, snapshot=True)
                    print(f"{ticker}")
                    ib.sleep(5)  # give IBKR a moment to populate data

                    last_price = None
                    if ticker.last and not math.isnan(ticker.last):
                        last_price = ticker.last
                    elif ticker.close and not math.isnan(ticker.close):
                        last_price = ticker.close

                    print(f"{symbol}, {last_price}, {ticker.last}, {ticker.close}")

                    if not last_price:
                        print(f"[{datetime.now()}] No valid market price for {symbol} (even delayed) — skipping.")
                        continue

                    qty = math.floor(FIXED_TRADE_AMOUNT / last_price)
                    if qty <= 0:
                        print(f"[{datetime.now()}] Qty computed as 0 for {symbol} (@{last_price}) — skipping.")
                        continue

                    # Use MARKET BUY to ensure execution
                    order = MarketOrder('BUY', qty)
                    trade = ib.placeOrder(contract, order)
                    print(f"[{datetime.now()}] MARKET BUY placed for {symbol} qty={qty}")

                    filled = wait_for_full_fill(ib, trade, qty, window_end_dt)
                    if filled:
                        place_tp_sl_for_symbol(ib, symbol, qty, last_price, day_number=1)
                        print(f"[{datetime.now()}] Buy filled & TP/SL placed for {symbol}.")
                    else:
                        print(f"[{datetime.now()}] Buy for {symbol} not fully filled in window — TP/SL NOT placed.")

            time.sleep(SLEEP_INTERVAL)
        else:
            print(f"[{datetime.now()}] Buy window ended/exited.")
            break




# ---------- Main ----------
def main():
    ib = connect_ibkr()
    tz = pytz.timezone(TIMEZONE)
    scheduler = BackgroundScheduler(timezone=TIMEZONE)

    # TP/SL daily update
    #scheduler.add_job(lambda: update_tp_sl_daily(ib), 'cron',
    #                  hour=TP_SL_UPDATE_TIME[0], minute=TP_SL_UPDATE_TIME[1])

    # Forced sale window
    #scheduler.add_job(lambda: execute_forced_sales_window(ib), 'cron',
    #                  hour=FORCED_SALE_START[0], minute=FORCED_SALE_START[1])

    # Daily buys
    scheduler.add_job(
        lambda: execute_daily_buys_window(ib),
        'cron',
        hour=DAILY_BUY_START[0],
        minute=DAILY_BUY_START[1]
    )

    scheduler.start()
    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        ib.disconnect()

if __name__ == '__main__':
    main()
