import time
import math
import asyncio
from datetime import datetime
import pytz
import gspread
from apscheduler.schedulers.background import BackgroundScheduler
from ib_insync import IB, Stock, MarketOrder, LimitOrder, StopOrder

# -------------------------
# CONFIG
HOST = '127.0.0.1'
PORT = 7497
CLIENT_ID = 2
TARGET_ACCOUNT = 'DUO713598'
TIMEZONE = 'US/Eastern'
FIXED_TRADE_AMOUNT = 25000  # $25k per ticker
SLEEP_INTERVAL = 1  # seconds
SPREADSHEET_ID = '1gEHjNEI-0Zr-_cMzHsOnEurcA0q2rGtdDgEyRKFgY38'
TAB_NAME = 'selected_MDA'
GSHEETS_CREDS = 'service_account_key.json'
TP_MULT = 1.2
SL_MULT = 0.85
DAILY_BUY_START = (14, 29)  # 2:00 PM EST
DAILY_BUY_END = (14, 30)    # 2:05 PM EST
# -------------------------

def ensure_event_loop():
    """Ensure an asyncio event loop exists in current thread."""
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
    """Fetch tickers from Google Sheets (first column)."""
    gc = gspread.service_account(filename=GSHEETS_CREDS)
    sh = gc.open_by_key(SPREADSHEET_ID)
    ws = sh.worksheet(TAB_NAME)
    data = ws.col_values(1)
    potd = [d.strip() for d in data if d.strip()]
    print(f"[{datetime.now()}] POTD: {potd}")
    return potd

def execute_daily_buys():
    ensure_event_loop()  # important for APScheduler threads

    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    start_h, start_m = DAILY_BUY_START
    end_h, end_m = DAILY_BUY_END

    # Only run during buy window
    if not ((now.hour > start_h or (now.hour == start_h and now.minute >= start_m)) and
            (now.hour < end_h or (now.hour == end_h and now.minute <= end_m))):
        print(f"[{datetime.now()}] Not in buy window. Exiting.")
        return

    ib = IB()
    ib.connect(HOST, PORT, clientId=CLIENT_ID, timeout=5)
    ib.reqMarketDataType(3)  # delayed prices

    tickers = get_potd_from_gsheet()

    for symbol in tickers:
        contract = Stock(symbol, 'SMART', 'USD')
        ticker = ib.reqMktData(contract, snapshot=True)
        ib.sleep(2)  # wait for snapshot

        price = None
        if ticker.last and not math.isnan(ticker.last):
            price = ticker.last
        elif ticker.close and not math.isnan(ticker.close):
            price = ticker.close

        if not price:
            print(f"[{datetime.now()}] No valid market price for {symbol} — skipping.")
            continue

        qty = math.floor(FIXED_TRADE_AMOUNT / price)
        if qty <= 0:
            print(f"[{datetime.now()}] Qty 0 for {symbol} (@{price}) — skipping.")
            continue

        # Place market buy
        order = MarketOrder('BUY', qty)
        ib.placeOrder(contract, order)
        print(f"[{datetime.now()}] Market BUY placed for {symbol} qty={qty} @ {price}")

        # Place TP/SL immediately (Day 1)
        tp_price = round(price * TP_MULT, 2)
        sl_price = round(price * SL_MULT, 2)

        # TP (Limit Sell above buy price)
        tp_order = LimitOrder('SELL', qty, tp_price)
        ib.placeOrder(contract, tp_order)

        # SL (Stop Sell below buy price)
        sl_order = StopOrder('SELL', qty, sl_price)
        ib.placeOrder(contract, sl_order)
        print(f"[{datetime.now()}] TP/SL placed for {symbol} | TP~{tp_price}, SL~{sl_price}")

        time.sleep(SLEEP_INTERVAL)

    ib.disconnect()
    print(f"[{datetime.now()}] Daily buy routine complete.")

# -------------------------
# Scheduler
# -------------------------
scheduler = BackgroundScheduler(timezone=TIMEZONE)
scheduler.add_job(execute_daily_buys, 'cron', hour=DAILY_BUY_START[0], minute=DAILY_BUY_START[1])
scheduler.start()
print(f"[{datetime.now()}] Scheduler started. Waiting for buy window...")

try:
    while True:
        time.sleep(60)
except (KeyboardInterrupt, SystemExit):
    print(f"[{datetime.now()}] Shutting down scheduler...")
    scheduler.shutdown()
