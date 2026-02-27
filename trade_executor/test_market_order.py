"""
Quick test: place a live market BUY order on EURONEXT via SMART routing.
Parameters: account=U6674415, ticker=PHIA, qty=4, currency=EUR
"""

from ib_insync import IB, Stock, MarketOrder

ACCOUNT_ID = 'U6674415'
PORT = 4001
CLIENT_ID = 99
TICKER = 'PHIA'
QTY = 4
CURRENCY = 'EUR'
EXCHANGE = 'SMART'

ib = IB()
ib.connect('127.0.0.1', PORT, clientId=CLIENT_ID)
print(f"Connected: {ib.isConnected()}")

contract = Stock(TICKER, EXCHANGE, CURRENCY)

order = MarketOrder('BUY', QTY)
order.account = ACCOUNT_ID
print(f"Order: {order}")

trade = ib.placeOrder(contract, order)
ib.sleep(3)

print(f"Order status: {trade.orderStatus.status}")
print(f"Filled qty:   {trade.orderStatus.filled}")
print(f"Avg price:    {trade.orderStatus.avgFillPrice}")
if trade.log:
    for entry in trade.log:
        print(f"  Log: {entry.message}")

ib.disconnect()
