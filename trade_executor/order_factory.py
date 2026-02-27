"""
order_factory.py

Creates IBKR Order objects. Executors should use these factory functions
rather than constructing orders directly, ensuring consistency.
"""

from ib_insync import MarketOrder, StopOrder, Order


def create_midprice_order(action: str, qty: int) -> Order:
    """Create a Pegged-to-Midpoint order.

    Args:
        action: 'BUY' or 'SELL'
        qty: Number of shares

    Returns:
        Order object with PEG MID type
    """
    return Order(action=action, totalQuantity=qty, orderType='PEG MID')


def create_market_order(action: str, qty: int) -> MarketOrder:
    """Create a standard market order.

    Args:
        action: 'BUY' or 'SELL'
        qty: Number of shares

    Returns:
        MarketOrder object
    """
    return MarketOrder(action, qty)


def create_trailing_stop_order(action: str, qty: int, trail_pct: float) -> Order:
    """Create a trailing stop order with percentage-based trail.

    Args:
        action: 'BUY' or 'SELL'
        qty: Number of shares
        trail_pct: Trailing percentage (e.g. 1.5 for 1.5%)

    Returns:
        Order object with TRAIL type
    """
    return Order(
        action=action,
        totalQuantity=qty,
        orderType='TRAIL',
        trailingPercent=trail_pct,
    )


def create_stop_loss_order(qty: int, stop_price: float) -> StopOrder:
    """Create a protective stop loss (sell stop).

    Args:
        qty: Number of shares
        stop_price: Stop trigger price

    Returns:
        StopOrder object
    """
    return StopOrder('SELL', qty, round(stop_price, 2))
