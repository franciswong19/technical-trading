import time
import math
from ib_insync import IB, Stock

# -------------------------
# CONFIG
HOST = '127.0.0.1'
PORT = 7497
CLIENT_ID = 2
TICKERS = ['AAPL', 'MSFT', 'GOOG', 'AMZN', 'TSLA']  # list of tickers
EXCHANGE = 'SMART'
CURRENCY = 'USD'
# -------------------------

ib = IB()
ib.connect(HOST, PORT, clientId=CLIENT_ID, timeout=5)
print("Connected to IBKR")

# 🔥 Force delayed data mode
ib.reqMarketDataType(3)

for SYMBOL in TICKERS:
    contract = Stock(SYMBOL, EXCHANGE, CURRENCY)
    print(f"\nRequesting price for {SYMBOL}: {contract}")

    # 🔥 Snapshot request — guaranteed to return delayed price
    ticker = ib.reqMktData(contract, snapshot=True)
    ib.sleep(2)  # allow IBKR to populate delayed data

    price = None
    if getattr(ticker, 'last', None) and not math.isnan(ticker.last):
        price = ticker.last
    elif getattr(ticker, 'close', None) and not math.isnan(ticker.close):
        price = ticker.close

    if price:
        print(f"Delayed price for {SYMBOL}: {price}")
    else:
        print(f"Still no price for {SYMBOL} — check market data subscription.")

    print("Ticker object:", ticker)

ib.disconnect()
print("Disconnected")
