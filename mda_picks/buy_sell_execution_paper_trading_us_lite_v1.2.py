import time
import math
from datetime import datetime
import pytz
import gspread
from apscheduler.schedulers.background import BackgroundScheduler
import pandas as pd
import pandas_market_calendars as mcal
from ib_insync import IB, Stock, MarketOrder, LimitOrder, StopOrder
import asyncio

# ------------------------- CONFIG -------------------------
HOST = '127.0.0.1'
PORT = 7497
CLIENT_ID = 2
TARGET_ACCOUNT = 'DUO713598'

SPREADSHEET_ID = 'YOUR_SPREADSHEET_ID'
TAB_NAME = 'selected_MDA'
GSHEETS_CREDS = 'service_account_key.json'

TIMEZONE = 'US/Eastern'
BUY_HOUR, BUY_MINUTE = 14, 27  # buy window start
SLEEP_INTERVAL = 5
FIXED_TRADE_AMOUNT = 5000  # $25k per ticker

# ------------------------- IBKR / Calendar -------------------------
ib = IB()
tz = pytz.timezone(TIMEZONE)
nyse = mcal.get_calendar('NYSE')


# ------------------------- Helpers -------------------------



def ensure_event_loop():
    """Ensure there is an asyncio loop in this thread (needed for APScheduler jobs)."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop

def get_potd_from_gsheet():
    """Return list of tickers from Google Sheets (first column)."""
    gc = gspread.service_account(filename=GSHEETS_CREDS)
    sh = gc.open_by_key(SPREADSHEET_ID)
    ws = sh.worksheet(TAB_NAME)
    data = ws.col_values(1)
    tickers = [d.strip() for d in data if d.strip()]
    print(f"[{datetime.now()}] POTD tickers: {tickers}")
    return tickers


def calculate_qty(price):
    qty = math.floor(FIXED_TRADE_AMOUNT / price)
    return max(qty, 1)


def get_delayed_price(contract):
    ib.reqMarketDataType(3)  # delayed
    ticker = ib.reqMktData(contract, snapshot=True)
    ib.sleep(2)
    price = None
    if ticker.last and not math.isnan(ticker.last):
        price = ticker.last
    elif ticker.close and not math.isnan(ticker.close):
        price = ticker.close
    return price


def place_tp_sl_for_symbol(symbol, qty, ref_price, buy_date):
    """Place TP/SL valid for 5 trading days using NYSE calendar."""
    schedule = nyse.schedule(start_date=buy_date, end_date=buy_date + pd.Timedelta(days=15))
    trading_days = schedule.index
    if len(trading_days) < 5:
        raise ValueError("Not enough trading days for 5-day TP/SL.")

    expiry_day = trading_days[4]  # 5th trading day
    expiry_dt = datetime.combine(expiry_day.date(), datetime.max.time())
    expiry_dt = tz.localize(expiry_dt)
    expiry_str = expiry_dt.strftime('%Y%m%d %H:%M:%S %Z')

    tp_price = ref_price * 1.2  # +20% target
    sl_price = ref_price * 0.85  # -15% stop

    contract = Stock(symbol, 'SMART', 'USD')
    tp_order = LimitOrder('SELL', qty, round(tp_price, 2), tif='GTD', goodTillDate=expiry_str)
    sl_order = StopOrder('SELL', qty, round(sl_price, 2), tif='GTD', goodTillDate=expiry_str)
    ib.placeOrder(contract, tp_order)
    ib.placeOrder(contract, sl_order)
    print(f"[{datetime.now()}] TP/SL placed for {symbol} | TP={tp_price:.2f}, SL={sl_price:.2f} expires {expiry_str}")


# ------------------------- Main Execution -------------------------
def execute_daily_buys():
    try:
        # Ensure event loop exists
        loop = ensure_event_loop()

        if not ib.isConnected():
            ib.connect(HOST, PORT, clientId=CLIENT_ID, timeout=5)
            print(f"[{datetime.now()}] Connected to IBKR")

        tickers = get_potd_from_gsheet()
        positions = {p.contract.symbol for p in ib.positions() if p.account == TARGET_ACCOUNT}

        for symbol in tickers:
            if symbol in positions:
                print(f"[{datetime.now()}] Already have {symbol}, skipping buy.")
                continue

            contract = Stock(symbol, 'SMART', 'USD')
            price = get_delayed_price(contract)
            if not price:
                print(f"[{datetime.now()}] No valid market price for {symbol}, skipping.")
                continue

            qty = calculate_qty(price)
            if qty <= 0:
                print(f"[{datetime.now()}] Qty computed 0 for {symbol}, skipping.")
                continue

            order = MarketOrder('BUY', qty)
            trade = ib.placeOrder(contract, order)
            ib.sleep(2)
            print(f"[{datetime.now()}] Market BUY {symbol} qty={qty} at approx {price:.2f}")

            # TP/SL for 5 trading days
            place_tp_sl_for_symbol(symbol, qty, price, datetime.now())

    except Exception as e:
        print(f"[{datetime.now()}] Error in daily buys: {e}")


# ------------------------- Scheduler -------------------------
def main():
    scheduler = BackgroundScheduler(timezone=TIMEZONE)
    scheduler.add_job(execute_daily_buys, 'cron', hour=BUY_HOUR, minute=BUY_MINUTE)
    scheduler.start()
    print(f"[{datetime.now()}] Scheduler started. Waiting for buy window {BUY_HOUR}:{BUY_MINUTE} {TIMEZONE}.")

    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        print(f"[{datetime.now()}] Shutting down scheduler and IBKR...")
        scheduler.shutdown()
        if ib.isConnected():
            ib.disconnect()
        print("Shutdown complete.")


if __name__ == "__main__":
    main()
