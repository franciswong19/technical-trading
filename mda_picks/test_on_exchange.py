import time
import math
from ib_insync import IB, Stock

# -------------------------
# CONFIG
HOST = '127.0.0.1'
PORT = 7497
CLIENT_ID = 2
SYMBOL = 'AAPL'
EXCHANGE = 'SMART'
CURRENCY = 'USD'
# -------------------------

ib = IB()
ib.connect(HOST, PORT, clientId=CLIENT_ID, timeout=5)
print("Connected to IBKR")

# 🔥 Force delayed data mode
ib.reqMarketDataType(3)

contract = Stock(SYMBOL, EXCHANGE, CURRENCY)
print(f"{contract}")
# -------------------------
# 🔥 Snapshot request — guaranteed to return delayed price
# -------------------------
ticker = ib.reqMktData(contract, snapshot=True)
print(f"{ticker}")
ib.sleep(2)

# IBKR puts delayed price into ticker.last or ticker.close
price = None

if ticker.last and not math.isnan(ticker.last):
    price = ticker.last
elif ticker.close and not math.isnan(ticker.close):
    price = ticker.close

if price:
    print(f"Delayed price for {SYMBOL}: {price}")
else:
    print("Still no price — your region might require ‘US Equity and Options Add-On’ market data (free).")

print("Ticker:", ticker)
ib.disconnect()
