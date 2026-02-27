"""
quantity_calculator.py

Calculates the number of shares to buy or sell based on portfolio value,
fulfillment percentage, and current price. Includes cash validation for buys.
"""

import math


class InsufficientCashError(Exception):
    """Raised when account does not have enough cash for the requested buy."""

    def __init__(self, required: float, available: float, ticker: str = ''):
        self.required = required
        self.available = available
        self.ticker = ticker
        msg = (
            f"Insufficient cash for {ticker}: "
            f"required ${required:,.2f}, available ${available:,.2f} "
            f"(shortfall: ${required - available:,.2f})"
        )
        super().__init__(msg)


class InsufficientCashForRequestError(Exception):
    """Raised when total fulfillment across all tickers exceeds available cash."""

    def __init__(self, total_required: float, available: float,
                 total_fulfillment_pct: float):
        self.total_required = total_required
        self.available = available
        self.total_fulfillment_pct = total_fulfillment_pct
        msg = (
            f"Insufficient cash for request: "
            f"total fulfillment {total_fulfillment_pct * 100:.1f}% "
            f"requires ${total_required:,.2f}, "
            f"but only ${available:,.2f} cash available "
            f"(shortfall: ${total_required - available:,.2f}). "
            f"Revise fulfillment percentages to proceed."
        )
        super().__init__(msg)


def calculate_buy_qty(portfolio_value: float, cash_value: float,
                      fulfillment_pct: float, price: float,
                      ticker: str = '') -> int:
    """
    Calculate the number of shares to buy.

    Formula: qty = floor(portfolio_value * fulfillment_pct / price)

    Args:
        portfolio_value: Account NetLiquidation value
        cash_value: Account TotalCashValue (available cash)
        fulfillment_pct: Target percentage of portfolio (0.01 to 1.0)
        price: Current price per share
        ticker: Ticker symbol (for error messages)

    Returns:
        int: Number of shares to buy (>= 0)

    Raises:
        InsufficientCashError: If cash < portfolio_value * fulfillment_pct
        ValueError: If price <= 0 or fulfillment_pct out of range
    """
    if price <= 0:
        raise ValueError(f"Invalid price for {ticker}: {price}")

    if not (0 < fulfillment_pct <= 1.0):
        raise ValueError(f"Fulfillment percentage must be between 0 and 1.0, got {fulfillment_pct}")

    required_amount = portfolio_value * fulfillment_pct

    if cash_value < required_amount:
        raise InsufficientCashError(
            required=required_amount,
            available=cash_value,
            ticker=ticker,
        )

    qty = math.floor(required_amount / price)
    return max(qty, 0)


def calculate_sell_qty(current_holdings: int, fulfillment_pct: float,
                       ticker: str = '') -> int:
    """
    Calculate the number of shares to sell.

    Formula: qty = floor(current_holdings * fulfillment_pct)

    Args:
        current_holdings: Number of shares currently held
        fulfillment_pct: Target percentage to sell (0.01 to 1.0)
        ticker: Ticker symbol (for error messages)

    Returns:
        int: Number of shares to sell (>= 0)

    Raises:
        ValueError: If fulfillment_pct out of range or holdings negative
    """
    if not (0 < fulfillment_pct <= 1.0):
        raise ValueError(f"Fulfillment percentage must be between 0 and 1.0, got {fulfillment_pct}")

    if current_holdings <= 0:
        return 0

    qty = math.floor(current_holdings * fulfillment_pct)
    return max(qty, 0)


def validate_total_cash(portfolio_value: float, cash_value: float,
                        ticker_params: list) -> None:
    """Validate that total fulfillment across all tickers fits within cash.

    Sums fulfillment_pct from all ticker_params, computes the total required
    amount (portfolio_value * total_pct), and checks against cash_value.

    Args:
        portfolio_value: Account NetLiquidation value
        cash_value: Account available cash
        ticker_params: List of TickerParams (each has .fulfillment_pct)

    Raises:
        InsufficientCashForRequestError: If total required exceeds cash
    """
    total_pct = sum(tp.fulfillment_pct for tp in ticker_params)
    total_required = portfolio_value * total_pct

    if total_required > cash_value:
        raise InsufficientCashForRequestError(
            total_required=total_required,
            available=cash_value,
            total_fulfillment_pct=total_pct,
        )
