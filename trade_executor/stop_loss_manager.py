"""
stop_loss_manager.py

Manages stop loss placement including the 15-minute delay after fill.
Supports NORMAL (8%), HEIGHTENED (3%), FIXED PRICE, and ADHOC trailing stops.
"""

import threading
from datetime import datetime

import pytz

from trade_executor.ibkr_client import IBKRClient
from trade_executor.config import (
    STOP_NORMAL_PCT,
    STOP_HEIGHTENED_PCT,
    STOP_LOSS_DELAY,
)


class StopLossManager:
    """Manages stop loss placement and lifecycle for a single IBKR client."""

    def __init__(self, client: IBKRClient, exchange: str):
        self.client = client
        self.exchange = exchange
        self._timers: list[threading.Timer] = []
        self._placed_stops: list[dict] = []  # Track placed stop orders

    def calculate_stop_price(self, buy_price: float, stop_type: str,
                             fixed_price: float = None) -> float:
        """Calculate the stop loss price.

        Args:
            buy_price: Average fill price
            stop_type: 'NORMAL', 'HEIGHTENED', or 'FIXED_PRICE'
            fixed_price: User-specified price (required if stop_type == 'FIXED_PRICE')

        Returns:
            float: Stop loss price (rounded to 2 decimals)
        """
        if stop_type == 'NORMAL':
            return round(buy_price * (1 - STOP_NORMAL_PCT), 2)
        elif stop_type == 'HEIGHTENED':
            return round(buy_price * (1 - STOP_HEIGHTENED_PCT), 2)
        elif stop_type == 'FIXED_PRICE':
            if fixed_price is None:
                raise ValueError("fixed_price is required for FIXED_PRICE stop type")
            return round(fixed_price, 2)
        else:
            raise ValueError(f"Unknown stop type: {stop_type}")

    def schedule_stop_loss(self, ticker: str, qty: int, buy_price: float,
                           stop_type: str, fixed_price: float = None,
                           delay_seconds: int = STOP_LOSS_DELAY) -> None:
        """Schedule a stop loss to be placed after a delay (default 15 minutes).

        Args:
            ticker: Stock symbol
            qty: Number of shares to protect
            buy_price: Average fill price
            stop_type: 'NORMAL', 'HEIGHTENED', or 'FIXED_PRICE'
            fixed_price: User-specified price (if FIXED_PRICE)
            delay_seconds: Delay before placing stop (default 900 = 15 min)
        """
        print(
            f"[StopLoss] Scheduling {stop_type} stop for {ticker} "
            f"({delay_seconds}s delay, buy_price={buy_price:.2f})"
        )

        timer = threading.Timer(
            delay_seconds,
            self._place_stop_callback,
            args=(ticker, qty, buy_price, stop_type, fixed_price),
        )
        timer.daemon = True
        timer.start()
        self._timers.append(timer)

    def place_stop_loss_now(self, ticker: str, qty: int, buy_price: float,
                            stop_type: str, fixed_price: float = None) -> dict:
        """Place a stop loss immediately.

        Args:
            ticker: Stock symbol
            qty: Number of shares
            buy_price: Average fill price
            stop_type: 'NORMAL', 'HEIGHTENED', or 'FIXED_PRICE'
            fixed_price: User-specified price (if FIXED_PRICE)

        Returns:
            dict: {trade, stop_price, success}
        """
        stop_price = self.calculate_stop_price(buy_price, stop_type, fixed_price)
        try:
            trade = self.client.place_stop_loss(ticker, qty, stop_price, self.exchange)
            result = {
                'trade': trade,
                'stop_price': stop_price,
                'ticker': ticker,
                'success': True,
            }
            self._placed_stops.append(result)
            print(f"[StopLoss] Placed {stop_type} stop for {ticker} at ${stop_price:.2f}")
            return result
        except Exception as e:
            print(f"[StopLoss] FAILED to place stop for {ticker}: {e}")
            return {
                'trade': None,
                'stop_price': stop_price,
                'ticker': ticker,
                'success': False,
                'error': str(e),
            }

    def place_trailing_and_fixed_stops(self, ticker: str, qty: int,
                                       fill_price: float,
                                       trailing_pct: float,
                                       stop_type1_pct: float,
                                       transaction_type: str) -> dict:
        """Place BOTH a fixed stop AND a trailing stop.
        Used for HOT POTATO request type.

        Args:
            ticker: Stock symbol
            qty: Number of shares
            fill_price: Average fill price
            trailing_pct: Trailing stop percentage (Stop type 2)
            stop_type1_pct: Fixed stop percentage offset from fill price (Stop type 1)
            transaction_type: 'BUY' or 'SELL' — direction of the fill

        Returns:
            dict: {fixed_stop_trade, trailing_stop_trade, success}
        """
        result = {
            'fixed_stop_trade': None,
            'trailing_stop_trade': None,
            'success': True,
        }

        # Fixed stop at X.X% offset from fill price (Stop type 1)
        if transaction_type == 'BUY':
            fixed_stop_price = round(fill_price * (1 - stop_type1_pct / 100), 2)
            stop_action = 'SELL'
        else:
            fixed_stop_price = round(fill_price * (1 + stop_type1_pct / 100), 2)
            stop_action = 'BUY'

        try:
            fixed_trade = self.client.place_stop_loss(
                ticker, qty, fixed_stop_price, self.exchange, action=stop_action
            )
            result['fixed_stop_trade'] = fixed_trade
            print(f"[StopLoss] HOT POTATO fixed stop for {ticker} at ${fixed_stop_price:.2f} ({stop_action})")
        except Exception as e:
            print(f"[StopLoss] FAILED fixed stop for {ticker}: {e}")
            result['success'] = False

        # Trailing stop (Stop type 2)
        trailing_action = 'SELL' if transaction_type == 'BUY' else 'BUY'
        try:
            trailing_trade = self.client.place_trailing_stop_order(
                ticker, trailing_action, qty, trailing_pct, self.exchange, tif='GTC'
            )
            result['trailing_stop_trade'] = trailing_trade
            print(f"[StopLoss] HOT POTATO trailing stop for {ticker} at {trailing_pct}%")
        except Exception as e:
            print(f"[StopLoss] FAILED trailing stop for {ticker}: {e}")
            result['success'] = False

        return result

    def cancel_all_stops_for_ticker(self, ticker: str) -> int:
        """Cancel all placed stop orders for a specific ticker.

        Returns:
            int: Number of stops cancelled
        """
        cancelled = 0
        for stop_info in self._placed_stops:
            if stop_info['ticker'] == ticker and stop_info.get('trade'):
                try:
                    self.client.cancel_order(stop_info['trade'])
                    cancelled += 1
                except Exception:
                    pass  # Order may already be filled/cancelled
        return cancelled

    def get_placed_stops(self) -> list:
        """Return list of all placed stop orders."""
        return self._placed_stops.copy()

    def cleanup(self) -> None:
        """Cancel all pending timers. Call this on shutdown."""
        for timer in self._timers:
            timer.cancel()
        self._timers.clear()
        print("[StopLoss] Cleaned up all pending timers")

    def _place_stop_callback(self, ticker: str, qty: int, buy_price: float,
                             stop_type: str, fixed_price: float = None) -> None:
        """Timer callback to place the stop loss after delay."""
        print(f"[StopLoss] Timer expired, placing {stop_type} stop for {ticker}")
        self.place_stop_loss_now(ticker, qty, buy_price, stop_type, fixed_price)
