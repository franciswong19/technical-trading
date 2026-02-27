from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
import threading, time

class App(EWrapper, EClient):
    def __init__(self):
        EClient.__init__(self, self)

    def nextValidId(self, orderId):
        contract = Contract()
        contract.symbol = "SHELL"
        contract.secType = "STK"
        contract.currency = "EUR"
        contract.exchange = "AEB"
        self.reqMarketDataType(1)  # 1 = live
        self.reqMktData(1, contract, "", False, False, [])

    def tickPrice(self, reqId, tickType, price, attrib):
        labels = {1: "BID", 2: "ASK", 4: "LAST"}
        if tickType in labels:
            print(f"{labels[tickType]}: {price}")

    def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=""):
        print(f"Error {errorCode}: {errorString}")

app = App()
app.connect("127.0.0.1", 4001, clientId=99)  # 4002 for Gateway, 7497 for TWS paper, 7496 for TWS live
threading.Thread(target=app.run, daemon=True).start()
time.sleep(5)
app.disconnect()