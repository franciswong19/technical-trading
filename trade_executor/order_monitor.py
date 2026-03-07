"""
order_monitor.py

Core monitoring loop engine. Handles fill detection, quantity recalculation,
and deadline-based escalation to market orders. Exchange-aware deadlines.
"""

from datetime import datetime, timedelta

import pytz
import pandas_market_calendars as mcal

from trade_executor.ibkr_client import IBKRClient
from trade_executor.config import EXCHANGES


class OrderMonitor:
    """
    Generic monitoring loop for active orders.
    Handles fill detection, escalation, and deadline enforcement.
    """

    def __init__(self, client: IBKRClient, check_interval_seconds: int,
                 deadline_type: str, exchange: str,
                 deadline_minutes: int = None):
        """
        Args:
            client: IBKRClient instance
            check_interval_seconds: How often to check (e.g. 60 or 600)
            deadline_type: 'BEFORE_CLOSE' or 'TIMED'
            exchange: Exchange key ('US', 'XETRA', 'EURONEXT')
            deadline_minutes: Only used when deadline_type == 'TIMED'
        """
        self.client = client
        self.check_interval = check_interval_seconds
        self.deadline_type = deadline_type
        self.exchange = exchange
        self.deadline_minutes = deadline_minutes
        self._deadline = self._compute_deadline()

    def get_deadline(self) -> datetime:
        """Return the computed deadline."""
        return self._deadline

    def monitor_until_fill_or_deadline(self, trade, ticker: str,
                                       on_check_callback=None) -> dict:
        """
        Monitor an order until it fills or the deadline approaches.

        Args:
            trade: IBKR Trade object to monitor
            ticker: Stock symbol
            on_check_callback: Optional callback(trade, ticker) called each interval.
                               Should return a new trade if the order was modified, or None.

        Returns:
            dict: {
                'filled': bool,
                'trade': trade object (may be updated),
                'escalated': bool,
                'deadline_reached': bool,
            }
        """
        result = {
            'filled': False,
            'trade': trade,
            'escalated': False,
            'deadline_reached': False,
        }

        while True:
            # Sleep for the check interval (in 1-second increments for responsiveness).
            # Use ib.sleep() instead of time.sleep() to keep the asyncio event loop running,
            # which prevents IB Gateway from disconnecting due to missed heartbeats.
            for _ in range(self.check_interval):
                self.client.ib.sleep(1)
                # Check fill during sleep
                if self.client.is_filled(trade):
                    result['filled'] = True
                    result['trade'] = trade
                    return result

            # Check if filled after full interval
            if self.client.is_filled(trade):
                result['filled'] = True
                result['trade'] = trade
                return result

            # Check deadline proximity
            if self._is_near_deadline(buffer_seconds=self.check_interval):
                result['deadline_reached'] = True
                return result

            # Call the on_check callback (e.g. for qty recalculation)
            if on_check_callback:
                new_trade = on_check_callback(trade, ticker)
                if new_trade is not None:
                    trade = new_trade
                    result['trade'] = trade

    def escalate_to_market(self, trade, ticker: str, action: str,
                           qty: int) -> 'Trade':
        """Cancel the current order and place a market order.

        Args:
            trade: Current trade to cancel
            ticker: Stock symbol
            action: 'BUY' or 'SELL'
            qty: Quantity for the market order

        Returns:
            New Trade object for the market order
        """
        print(f"[Monitor] Escalating {ticker} to market order ({action} {qty})")

        # Cancel existing order
        try:
            self.client.cancel_order(trade)
        except Exception:
            pass  # Order may already be done

        # Place market order
        new_trade = self.client.place_market_order(ticker, action, qty, self.exchange)
        return new_trade

    def wait_for_threshold_or_deadline(self, get_price_fn, condition_fn) -> dict:
        """
        Poll price at check_interval until condition is met or we are near the deadline.

        Used for 'trailing_stop_threshold' initial order type: waits for the price
        threshold condition to be satisfied before placing an order.

        Args:
            get_price_fn: Callable that returns the current price (float)
            condition_fn: Callable(price) -> bool, True when order should be placed

        Returns:
            dict: {
                'condition_met': bool,   -- True if condition_fn returned True
                'near_deadline': bool,   -- True if within check_interval of deadline
                'price': float,          -- Most recent price fetched
            }
        If both condition_met and near_deadline are True, treat as last-check → market order.
        """
        while True:
            price = get_price_fn()
            near_deadline = self._is_near_deadline(buffer_seconds=60)
            condition_met = condition_fn(price)

            if condition_met or near_deadline:
                return {
                    'condition_met': condition_met,
                    'near_deadline': near_deadline,
                    'price': price,
                }

            # Condition not met, not near deadline — sleep and retry
            for _ in range(self.check_interval):
                self.client.ib.sleep(1)

    def wait_for_stop_trigger(self, stop_trades: list,
                              check_interval: int = 300) -> dict:
        """Monitor multiple stop orders and detect which triggers first.
        Used for HOT POTATO dual-stop monitoring.

        Args:
            stop_trades: List of dicts with 'name' and 'trade' keys
            check_interval: Check interval in seconds (default 300 = 5 min)

        Returns:
            dict: {'triggered_name': str, 'triggered_trade': trade, 'remaining': list}
                  or {'triggered_name': None} if deadline reached
        """
        while True:
            for _ in range(check_interval):
                self.client.ib.sleep(1)

                # Check each stop
                for st in stop_trades:
                    if self.client.is_done(st['trade']):
                        triggered = st
                        remaining = [s for s in stop_trades if s['name'] != triggered['name']]
                        return {
                            'triggered_name': triggered['name'],
                            'triggered_trade': triggered['trade'],
                            'remaining': remaining,
                        }

            # Check deadline
            if self._is_near_deadline(buffer_seconds=check_interval):
                return {'triggered_name': None, 'remaining': stop_trades}

    # ==========================================
    # INTERNAL HELPERS
    # ==========================================

    def _compute_deadline(self) -> datetime:
        """Compute the deadline based on type and exchange.

        Returns:
            datetime: Timezone-aware deadline
        """
        exchange_cfg = EXCHANGES[self.exchange]
        tz = pytz.timezone(exchange_cfg['timezone'])
        now = datetime.now(tz)

        if self.deadline_type == 'TIMED':
            return now + timedelta(minutes=self.deadline_minutes)

        elif self.deadline_type == 'BEFORE_CLOSE':
            # Get market close time for today
            calendar = mcal.get_calendar(exchange_cfg['calendar'])
            schedule = calendar.schedule(start_date=now.date(), end_date=now.date())

            if schedule.empty:
                # Market not open today, use a far-future deadline
                print(f"[Monitor] WARNING: No market schedule found for {now.date()} on {self.exchange}")
                return now + timedelta(hours=8)

            market_close = schedule.iloc[0]['market_close'].to_pydatetime()
            if market_close.tzinfo is None:
                market_close = pytz.utc.localize(market_close)
            market_close = market_close.astimezone(tz)

            cutoff = market_close - timedelta(minutes=exchange_cfg['cutoff_minutes_before_close'])
            return cutoff

        elif self.deadline_type == 'IMMEDIATE':
            # No deadline for immediate orders
            return now + timedelta(minutes=2)

        else:
            raise ValueError(f"Unknown deadline type: {self.deadline_type}")

    def _is_near_deadline(self, buffer_seconds: int = 60) -> bool:
        """Check if we are within buffer_seconds of the deadline.

        Args:
            buffer_seconds: Buffer time in seconds

        Returns:
            bool: True if near or past deadline
        """
        exchange_cfg = EXCHANGES[self.exchange]
        tz = pytz.timezone(exchange_cfg['timezone'])
        now = datetime.now(tz)
        return now >= (self._deadline - timedelta(seconds=buffer_seconds))
