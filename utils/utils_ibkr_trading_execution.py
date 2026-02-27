"""
utils_ibkr_trading_execution.py

Reusable IBKR trading execution functions extracted from
mda_picks/buy_sell_execution_paper_trading_us_lite_v1.2.py.

Provides importable utilities for order placement, price retrieval,
TP/SL management, and trading calendar operations.
"""

import math
import asyncio
from datetime import datetime

import pytz
import pandas as pd
import pandas_market_calendars as mcal
from ib_insync import IB, Stock, MarketOrder, LimitOrder, StopOrder, Order


# ==========================================
# EVENT LOOP HELPERS
# ==========================================

def ensure_event_loop():
    """Ensure there is an asyncio event loop in the current thread.
    Required when running IBKR operations from APScheduler or threads."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop


# ==========================================
# PRICE RETRIEVAL
# ==========================================

def get_live_price(ib, contract):
    """
    Get live market price for a contract.

    Args:
        ib: Connected IB instance
        contract: IBKR contract object

    Returns:
        float: Current market price, or None if unavailable
    """
    ib.reqMarketDataType(1)  # 1 = live data
    ticker = ib.reqMktData(contract, snapshot=True)
    ib.sleep(2)
    price = None
    if ticker.last and not math.isnan(ticker.last):
        price = ticker.last
    elif ticker.close and not math.isnan(ticker.close):
        price = ticker.close
    ib.cancelMktData(contract)
    return price


def get_delayed_price(ib, contract):
    """
    Get delayed market price for a contract (paper trading).

    Args:
        ib: Connected IB instance
        contract: IBKR contract object

    Returns:
        float: Delayed market price, or None if unavailable
    """
    ib.reqMarketDataType(3)  # 3 = delayed data
    ticker = ib.reqMktData(contract, snapshot=True)
    ib.sleep(2)
    price = None
    if ticker.last and not math.isnan(ticker.last):
        price = ticker.last
    elif ticker.close and not math.isnan(ticker.close):
        price = ticker.close
    ib.cancelMktData(contract)
    return price


# ==========================================
# CONTRACT CREATION
# ==========================================

def create_stock_contract(symbol, exchange='SMART', currency='USD'):
    """
    Create an IBKR Stock contract.

    Args:
        symbol: Ticker symbol (e.g. 'AAPL')
        exchange: IBKR exchange routing (e.g. 'SMART', 'IBIS', 'SBF')
        currency: Currency code (e.g. 'USD', 'EUR')

    Returns:
        Stock contract object
    """
    return Stock(symbol, exchange, currency)


# ==========================================
# ORDER CREATION
# ==========================================

def create_market_order(action, qty):
    """Create a market order.

    Args:
        action: 'BUY' or 'SELL'
        qty: Number of shares

    Returns:
        MarketOrder object
    """
    return MarketOrder(action, qty)


def create_limit_order(action, qty, limit_price, tif='GTC', good_till_date=None):
    """Create a limit order.

    Args:
        action: 'BUY' or 'SELL'
        qty: Number of shares
        limit_price: Limit price
        tif: Time in force ('GTC', 'GTD', 'DAY')
        good_till_date: Expiry datetime string for GTD orders

    Returns:
        LimitOrder object
    """
    order = LimitOrder(action, qty, round(limit_price, 2), tif=tif)
    if good_till_date and tif == 'GTD':
        order.goodTillDate = good_till_date
    return order


def create_stop_order(action, qty, stop_price, tif='GTC', good_till_date=None):
    """Create a stop order.

    Args:
        action: 'BUY' or 'SELL'
        qty: Number of shares
        stop_price: Stop trigger price
        tif: Time in force ('GTC', 'GTD', 'DAY')
        good_till_date: Expiry datetime string for GTD orders

    Returns:
        StopOrder object
    """
    order = StopOrder(action, qty, round(stop_price, 2), tif=tif)
    if good_till_date and tif == 'GTD':
        order.goodTillDate = good_till_date
    return order


def create_midprice_order(action, qty):
    """Create a Pegged-to-Midpoint order.

    Args:
        action: 'BUY' or 'SELL'
        qty: Number of shares

    Returns:
        Order object with PEG MID type
    """
    order = Order(
        action=action,
        totalQuantity=qty,
        orderType='PEG MID',
    )
    return order


def create_trailing_stop_order(action, qty, trailing_percent):
    """Create a trailing stop order with percentage-based trail.

    Args:
        action: 'BUY' or 'SELL'
        qty: Number of shares
        trailing_percent: Trailing stop percentage (e.g. 1.5 for 1.5%)

    Returns:
        Order object with TRAIL type
    """
    order = Order(
        action=action,
        totalQuantity=qty,
        orderType='TRAIL',
        trailingPercent=trailing_percent,
    )
    return order


# ==========================================
# ORDER PLACEMENT & MANAGEMENT
# ==========================================

def place_order(ib, contract, order):
    """Place an order and return the trade object.

    Args:
        ib: Connected IB instance
        contract: IBKR contract object
        order: IBKR order object

    Returns:
        Trade object
    """
    trade = ib.placeOrder(contract, order)
    ib.sleep(2)  # Allow order status to propagate
    return trade


def wait_for_fill(ib, trade, timeout_seconds=60):
    """Wait for an order to fill.

    Args:
        ib: Connected IB instance
        trade: Trade object to monitor
        timeout_seconds: Maximum wait time

    Returns:
        bool: True if filled, False if timed out
    """
    elapsed = 0
    while elapsed < timeout_seconds:
        ib.sleep(1)
        elapsed += 1
        if trade.isDone():
            return True
    return False


def cancel_order(ib, trade):
    """Cancel a specific order.

    Args:
        ib: Connected IB instance
        trade: Trade object to cancel
    """
    ib.cancelOrder(trade.order)
    ib.sleep(1)


def cancel_all_orders(ib):
    """Cancel all open orders.

    Args:
        ib: Connected IB instance

    Returns:
        int: Number of orders cancelled
    """
    open_orders = ib.openOrders()
    count = len(open_orders)
    if count > 0:
        ib.reqGlobalCancel()
        ib.sleep(2)
    return count


def get_fill_price(trade):
    """Get the average fill price from a completed trade.

    Args:
        trade: Completed Trade object

    Returns:
        float: Average fill price, or None if not filled
    """
    if trade.fills:
        total_value = sum(f.execution.price * f.execution.shares for f in trade.fills)
        total_shares = sum(f.execution.shares for f in trade.fills)
        if total_shares > 0:
            return total_value / total_shares
    return None


# ==========================================
# TRADING CALENDAR HELPERS
# ==========================================

def get_market_calendar(calendar_name='NYSE'):
    """Get a market calendar instance.

    Args:
        calendar_name: Calendar name ('NYSE', 'XETRA', 'EURONEXT')

    Returns:
        MarketCalendar instance
    """
    return mcal.get_calendar(calendar_name)


def is_market_open(calendar_name='NYSE', timezone_str='US/Eastern'):
    """Check if the market is currently open.

    Args:
        calendar_name: Calendar name
        timezone_str: Timezone string

    Returns:
        bool: True if market is open
    """
    tz = pytz.timezone(timezone_str)
    now = datetime.now(tz)
    calendar = get_market_calendar(calendar_name)
    schedule = calendar.schedule(start_date=now.date(), end_date=now.date())

    if schedule.empty:
        return False

    market_open = schedule.iloc[0]['market_open'].to_pydatetime()
    market_close = schedule.iloc[0]['market_close'].to_pydatetime()

    # Ensure timezone-aware comparison
    if market_open.tzinfo is None:
        market_open = pytz.utc.localize(market_open)
    if market_close.tzinfo is None:
        market_close = pytz.utc.localize(market_close)

    return market_open <= now <= market_close


def get_market_close_time(calendar_name='NYSE', timezone_str='US/Eastern', date=None):
    """Get the market close time for a given date.

    Args:
        calendar_name: Calendar name
        timezone_str: Timezone string
        date: Date to check (default: today)

    Returns:
        datetime: Market close time (timezone-aware), or None if market is closed
    """
    tz = pytz.timezone(timezone_str)
    if date is None:
        date = datetime.now(tz).date()

    calendar = get_market_calendar(calendar_name)
    schedule = calendar.schedule(start_date=date, end_date=date)

    if schedule.empty:
        return None

    market_close = schedule.iloc[0]['market_close'].to_pydatetime()
    if market_close.tzinfo is None:
        market_close = pytz.utc.localize(market_close)

    return market_close.astimezone(tz)


def get_trading_days_ahead(start_date, num_days, calendar_name='NYSE'):
    """Get the next N trading days from a start date.

    Args:
        start_date: Starting date
        num_days: Number of trading days
        calendar_name: Calendar name

    Returns:
        list of trading day dates
    """
    calendar = get_market_calendar(calendar_name)
    end_date = start_date + pd.Timedelta(days=num_days * 3)  # generous buffer
    schedule = calendar.schedule(start_date=start_date, end_date=end_date)
    return schedule.index[:num_days].tolist()


# ==========================================
# QUANTITY CALCULATION
# ==========================================

def calculate_qty_from_amount(amount, price):
    """Calculate number of shares from a dollar amount.

    Args:
        amount: Dollar amount to invest
        price: Price per share

    Returns:
        int: Number of shares (minimum 1 if amount > 0)
    """
    if price <= 0:
        return 0
    qty = math.floor(amount / price)
    return max(qty, 1) if amount > 0 else 0
