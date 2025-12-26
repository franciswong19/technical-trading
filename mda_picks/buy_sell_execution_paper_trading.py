"""
Paper Trading Script: Daily Buy/Sell with TP/SL and Forced Sales

Features:
- Executes TP/SL update at 09:30 EST
- Executes forced sales within configurable window (default 09:40–09:50 EST)
- Executes daily buys within configurable window (default 10:00–10:10 EST)
- TP/SL logic varies by day held, also set on day 1
- Buy max fixed at $5,000 per symbol
- All IBKR calls run in main thread to avoid asyncio issues
- Reads POTD from Google Sheet
"""

from ib_insync import IB, Stock, LimitOrder, ExecutionFilter
from datetime import datetime, timedelta
import pytz
import gspread
from math import floor
import time

# ==========================
# CONFIGURATION PARAMETERS
# ==========================
HOST = '127.0.0.1'          # TWS/IB Gateway host
PORT = 7497                 # 7497 for Paper, 7496 for Live
CLIENT_ID = 1               # Unique client ID
TARGET_ACCOUNT = 'DUO713598'

MAX_BUY_AMOUNT = 5000       # $5000 per symbol
TIMEZONE = 'US/Eastern'

# Time windows (EST)
TP_SL_UPDATE_HOUR = 12
TP_SL_UPDATE_MIN = 46

FORCED_SALE_START_HOUR = 12
FORCED_SALE_START_MIN = 47
FORCED_SALE_END_HOUR = 12
FORCED_SALE_END_MIN = 48

DAILY_BUY_START_HOUR = 12
DAILY_BUY_START_MIN = 49
DAILY_BUY_END_HOUR = 12
DAILY_BUY_END_MIN = 50

# TP/SL percentages by holding day
TP_SL_RULES = {
    1: {'TP': 0.20, 'SL': -0.15},  # Day 1 = same as day 2
    2: {'TP': 0.20, 'SL': -0.15},
    3: {'TP': 0.15, 'SL': -0.10},
    4: {'TP': 0.10, 'SL': -0.10},
    5: {'TP': 0.10, 'SL': -0.10},
}

# Google Sheet config
SPREADSHEET_ID = '1gEHjNEI-0Zr-_cMzHsOnEurcA0q2rGtdDgEyRKFgY38'
SHEET_NAME = 'selected_MDA'

# ==========================
# HELPER FUNCTIONS
# ==========================

def connect_gsheet():
    """Connect to Google Sheet and return the worksheet"""
    gc = gspread.service_account()  # assumes you have credentials json configured
    sh = gc.open_by_key(SPREADSHEET_ID)
    ws = sh.worksheet(SHEET_NAME)
    return ws

def get_potd():
    """Retrieve POTD symbols from Google Sheet"""
    ws = connect_gsheet()
    data = ws.col_values(1)
    potd = [s.strip().upper() for s in data if s.strip()]
    print(f"POTD today: {potd}")
    return potd

def get_positions_with_buy_dates(ib):
    """
    Fetch current positions and map symbol to buy date.
    Only considers BOT (buy) executions.
    """
    ex_filter = ExecutionFilter()
    executions = ib.reqExecutions(ex_filter)
    executions = [ex for ex in executions if ex.execution.acctNumber == TARGET_ACCOUNT]

    buy_dates = {}
    for ex in executions:
        if ex.execution.side == 'BOT':
            symbol = ex.contract.symbol if hasattr(ex, 'contract') else ex.execution.symbol
            buy_date = datetime.strptime(ex.execution.time, "%Y%m%d  %H:%M:%S")
            # Take the earliest buy date for this symbol
            if symbol not in buy_dates or buy_date < buy_dates[symbol]:
                buy_dates[symbol] = buy_date
    return buy_dates

def cancel_sell_orders_for_symbol(ib, symbol):
    """Cancel all open sell orders (TP/SL) for a given symbol"""
    open_orders = ib.openOrders()
    canceled = 0
    for trade in open_orders:
        order = trade.order
        contract = trade.contract
        if contract.symbol == symbol and order.action.upper() == 'SELL':
            ib.cancelOrder(order)
            canceled += 1
    if canceled == 0:
        print(f"No SELL orders to cancel for {symbol}")
    else:
        print(f"Canceled {canceled} SELL orders for {symbol}")

def place_tp_sl_for_symbol(ib, contract, buy_price, holding_day):
    """Place TP/SL orders based on holding day"""
    rules = TP_SL_RULES.get(holding_day)
    if not rules:
        print(f"No TP/SL rules for holding day {holding_day}")
        return

    tp_price = round(buy_price * (1 + rules['TP']), 2)
    sl_price = round(buy_price * (1 + rules['SL']), 2)

    # Cancel existing TP/SL orders
    cancel_sell_orders_for_symbol(ib, contract.symbol)

    # Place TP order
    tp_order = LimitOrder('SELL', 1, tp_price)
    ib.placeOrder(contract, tp_order)
    print(f"Placed TP for {contract.symbol} at {tp_price}")

    # Place SL order
    sl_order = LimitOrder('SELL', 1, sl_price)
    ib.placeOrder(contract, sl_order)
    print(f"Placed SL for {contract.symbol} at {sl_price}")

# ==========================
# TRADING FUNCTIONS
# ==========================

def update_tp_sl_daily(ib):
    """Update TP/SL for all current positions"""
    print("=== Updating TP/SL ===")
    positions = ib.positions()
    buy_dates = get_positions_with_buy_dates(ib)
    today = datetime.now(pytz.timezone(TIMEZONE)).date()

    for pos in positions:
        if pos.account != TARGET_ACCOUNT or pos.position <= 0:
            continue
        symbol = pos.contract.symbol
        conId = pos.contract.conId
        buy_date = buy_dates.get(conId)
        if not buy_date:
            continue
        holding_day = (today - buy_date.date()).days + 1  # include day 1
        place_tp_sl_for_symbol(ib, pos.contract, pos.avgCost, holding_day)

def execute_forced_sales_window(ib):
    """Sell tickers on their 6th trading day"""
    print("=== Executing Forced Sales ===")
    positions = ib.positions()
    buy_dates = get_positions_with_buy_dates(ib)
    today = datetime.now(pytz.timezone(TIMEZONE)).date()

    for pos in positions:
        if pos.account != TARGET_ACCOUNT or pos.position <= 0:
            continue
        symbol = pos.contract.symbol
        conId = pos.contract.conId
        buy_date = buy_dates.get(conId)
        if not buy_date:
            continue
        holding_day = (today - buy_date.date()).days + 1
        if holding_day >= 6:
            qty = int(pos.position)
            order = LimitOrder('SELL', qty, pos.marketPrice * 0.99)  # aggressive limit
            ib.placeOrder(pos.contract, order)
            print(f"Forced sale: {symbol}, qty={qty}")

def execute_daily_buys_window(ib):
    """Execute daily POTD buys"""
    print("=== Executing Daily Buys ===")
    potd = get_potd()
    positions = ib.positions()
    existing_symbols = [pos.contract.symbol for pos in positions if pos.account == TARGET_ACCOUNT]

    to_buy = [s for s in potd if s not in existing_symbols]
    if not to_buy:
        print("No new symbols to buy today.")
        return

    for symbol in to_buy:
        contract = Stock(symbol, 'SMART', 'USD')
        last_price = ib.reqMktData(contract).last
        if last_price is None or last_price <= 0:
            print(f"Cannot get market price for {symbol}, skipping.")
            continue
        qty = floor(MAX_BUY_AMOUNT / last_price)
        if qty <= 0:
            print(f"Not enough cash to buy {symbol}")
            continue
        order = LimitOrder('BUY', qty, last_price * 1.01)  # aggressive
        ib.placeOrder(contract, order)
        print(f"Bought {symbol}, qty={qty}, price={order.lmtPrice}")

        # Set TP/SL immediately (day 1)
        place_tp_sl_for_symbol(ib, contract, last_price, 1)

# ==========================
# MAIN SCRIPT
# ==========================

def main():
    ib = IB()
    try:
        ib.connect(HOST, PORT, clientId=CLIENT_ID, timeout=5)
        print("Connected to IBKR Paper Trading")
    except Exception as e:
        print(f"Error connecting: {e}")
        return

    print("Waiting for scheduled windows...")
    tz = pytz.timezone(TIMEZONE)

    try:
        while True:
            now = datetime.now(tz)

            # TP/SL update
            if now.hour == TP_SL_UPDATE_HOUR and now.minute == TP_SL_UPDATE_MIN:
                update_tp_sl_daily(ib)

            # Forced sales
            elif (FORCED_SALE_START_HOUR <= now.hour <= FORCED_SALE_END_HOUR and
                  FORCED_SALE_START_MIN <= now.minute <= FORCED_SALE_END_MIN):
                execute_forced_sales_window(ib)

            # Daily buys
            elif (DAILY_BUY_START_HOUR <= now.hour <= DAILY_BUY_END_HOUR and
                  DAILY_BUY_START_MIN <= now.minute <= DAILY_BUY_END_MIN):
                execute_daily_buys_window(ib)

            time.sleep(5)  # check every 5 seconds

    except KeyboardInterrupt:
        print("Stopping script...")

    ib.disconnect()
    print("Disconnected from IBKR")

if __name__ == "__main__":
    main()
