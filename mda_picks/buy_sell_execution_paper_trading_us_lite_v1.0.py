import time
import math
from datetime import datetime
import gspread
from ib_insync import IB, Stock, MarketOrder, LimitOrder

# -------------------------
# CONFIG
HOST = '127.0.0.1'
PORT = 7497
CLIENT_ID = 2
TARGET_ACCOUNT = 'DUO713598'

SPREADSHEET_ID = '1gEHjNEI-0Zr-_cMzHsOnEurcA0q2rGtdDgEyRKFgY38'
TAB_NAME = 'selected_MDA'
GSHEETS_CREDS = 'service_account_key.json'

FIXED_TRADE_AMOUNT = 5000  # USD per ticker
EXCHANGE = 'SMART'
CURRENCY = 'USD'
AGGRESSIVE_ADJ = 1.0  # for market orders, can leave 1.0
# -------------------------

# ---------- Helpers ----------
def get_potd_from_gsheet():
    gc = gspread.service_account(filename=GSHEETS_CREDS)
    sh = gc.open_by_key(SPREADSHEET_ID)
    ws = sh.worksheet(TAB_NAME)
    data = ws.col_values(1)
    tickers = [d.strip() for d in data if d.strip()]
    print(f"[{datetime.now()}] POTD tickers: {tickers}")
    return tickers

def tp_sl_prices(ref_price):
    """Compute TP/SL for day 1"""
    tp = ref_price * 1.2  # 20% gain
    sl = ref_price * 0.85  # 15% loss
    return round(tp, 2), round(sl, 2)

# ---------- Main ----------
def main():
    ib = IB()
    ib.connect(HOST, PORT, clientId=CLIENT_ID, timeout=5)
    print(f"[{datetime.now()}] Connected to IBKR")

    # Use delayed data
    ib.reqMarketDataType(3)

    tickers = get_potd_from_gsheet()

    for symbol in tickers:
        contract = Stock(symbol, EXCHANGE, CURRENCY)
        print(f"\n[{datetime.now()}] Processing {symbol}")

        # Request snapshot price (guaranteed delayed price)
        ticker = ib.reqMktData(contract, snapshot=True)
        ib.sleep(2)  # give IBKR time to populate price

        price = None
        if getattr(ticker, 'last', None) and not math.isnan(ticker.last):
            price = ticker.last
        elif getattr(ticker, 'close', None) and not math.isnan(ticker.close):
            price = ticker.close

        if not price:
            print(f"[{datetime.now()}] No valid price for {symbol} — skipping")
            continue

        # Compute quantity
        qty = math.floor(FIXED_TRADE_AMOUNT / price)
        if qty <= 0:
            print(f"[{datetime.now()}] Qty computed as 0 for {symbol} (@{price}) — skipping")
            continue

        # Place market BUY order
        order = MarketOrder('BUY', qty)
        trade = ib.placeOrder(contract, order)
        print(f"[{datetime.now()}] BUY MARKET {symbol} x {qty} @ {price}")

        # Wait until filled
        while not trade.isDone():
            ib.sleep(1)
        print(f"[{datetime.now()}] Buy filled for {symbol}")

        # Place TP/SL using LIMIT SELL orders
        tp, sl = tp_sl_prices(price)
        tp_order = LimitOrder('SELL', qty, tp)
        sl_order = LimitOrder('SELL', qty, sl)
        ib.placeOrder(contract, tp_order)
        ib.placeOrder(contract, sl_order)
        print(f"[{datetime.now()}] TP/SL placed for {symbol} | TP={tp} SL={sl}")

    ib.disconnect()
    print(f"[{datetime.now()}] Disconnected")

if __name__ == "__main__":
    main()
