"""
ibkr_client.py

IBKR connection wrapper. Single point of contact with Interactive Brokers
for all executor scripts. Exchange-aware contract creation and order management.
"""

import math
from datetime import datetime

import pytz
from ib_insync import IB, Stock, MarketOrder, StopOrder, Order
from ib_insync.util import UNSET_DOUBLE

from trade_executor.config import IBKR_HOST, EXCHANGES


class IBKRConnectionError(Exception):
    """Raised when connection to IBKR fails."""
    pass


class OrderRejectedError(Exception):
    """Raised when IBKR rejects an order."""
    pass


class IBKRClient:
    """Wraps all IBKR interactions for a single account."""

    def __init__(self, account_id: str, port: int, client_id: int,
                 host: str = IBKR_HOST):
        self.ib = IB()
        self.account_id = account_id
        self.port = port
        self.client_id = client_id
        self.host = host

    # ==========================================
    # CONNECTION
    # ==========================================

    def connect(self) -> None:
        """Connect to IBKR TWS/IB Gateway.

        After connecting, immediately syncs all open orders from all sessions
        (TWS, mobile app, other API clients). This ensures cancel_orders_for_ticker()
        sees pre-existing stops and get_pending_buy_value() has an accurate picture
        of committed cash before any checks or cancellations are performed.

        Raises:
            IBKRConnectionError: If connection fails
        """
        try:
            self.ib.connect(self.host, self.port, clientId=self.client_id, timeout=5)
            print(f"[IBKR] Connected: account={self.account_id}, port={self.port}, clientId={self.client_id}")
            # Pull in orders from all sessions — without this, openTrades() only
            # reflects orders placed by this specific API client_id.
            self.ib.reqAllOpenOrders()
            self.ib.sleep(1)
            print(f"[IBKR] All open orders synced ({len(self.ib.openTrades())} open trades visible)")
        except Exception as e:
            raise IBKRConnectionError(
                f"Failed to connect to IBKR at {self.host}:{self.port} "
                f"(clientId={self.client_id}): {e}"
            )

    def disconnect(self) -> None:
        """Gracefully disconnect from IBKR."""
        if self.ib.isConnected():
            self.ib.disconnect()
            print(f"[IBKR] Disconnected: account={self.account_id}")

    def is_connected(self) -> bool:
        """Check if connected to IBKR."""
        return self.ib.isConnected()

    # ==========================================
    # ACCOUNT DATA
    # ==========================================

    def get_portfolio_value(self, currency: str = None) -> float:
        """Get NetLiquidation value for this account in a specific currency.

        Uses NetLiquidation-S from accountValues which provides per-currency
        breakdown. Falls back to accountSummary if currency not specified.

        Args:
            currency: Target currency (e.g. 'USD', 'EUR'). If None, returns
                      base currency value from accountSummary.

        Returns:
            float: Net liquidation value in the specified currency
        """
        if currency:
            values = self.ib.accountValues(account=self.account_id)
            by_currency = None
            for item in values:
                if item.tag == 'NetLiquidation-S' and item.currency == currency:
                    return float(item.value)
                if item.tag == 'NetLiquidationByCurrency' and item.currency == currency:
                    by_currency = float(item.value)
            if by_currency is not None:
                return by_currency
            raise ValueError(
                f"NetLiquidation not found for account {self.account_id} "
                f"in {currency}"
            )
        summary = self.ib.accountSummary(account=self.account_id)
        for item in summary:
            if item.tag == 'NetLiquidation':
                return float(item.value)
        raise ValueError(f"NetLiquidation not found for account {self.account_id}")

    def get_cash_value(self, currency: str = None) -> float:
        """Get cash balance for this account in a specific currency.

        Uses CashBalance from accountValues which provides per-currency
        breakdown (e.g. USD cash, EUR cash separately). Falls back to
        TotalCashValue from accountSummary if currency not specified.

        Args:
            currency: Target currency (e.g. 'USD', 'EUR'). If None, returns
                      base currency total from accountSummary.

        Returns:
            float: Cash value in the specified currency
        """
        if currency:
            values = self.ib.accountValues(account=self.account_id)
            for item in values:
                if item.tag == 'CashBalance' and item.currency == currency:
                    return float(item.value)
            # No cash in this currency
            return 0.0
        summary = self.ib.accountSummary(account=self.account_id)
        for item in summary:
            if item.tag == 'TotalCashValue':
                return float(item.value)
        raise ValueError(f"TotalCashValue not found for account {self.account_id}")

    def get_positions(self) -> list:
        """Get all positions for this account.

        Returns:
            list of dicts: [{symbol, position, market_price, contract}, ...]
        """
        all_positions = self.ib.positions()
        result = []
        for pos in all_positions:
            if pos.account == self.account_id:
                result.append({
                    'symbol': pos.contract.symbol,
                    'position': int(pos.position),
                    'contract': pos.contract,
                })
        return result

    def get_position_qty(self, ticker: str) -> int:
        """Get number of shares held for a specific ticker.

        Args:
            ticker: Stock symbol

        Returns:
            int: Number of shares (0 if not held)
        """
        positions = self.get_positions()
        for pos in positions:
            if pos['symbol'] == ticker:
                return pos['position']
        return 0

    # ==========================================
    # PRICE DATA
    # ==========================================

    def get_current_price(self, ticker: str, exchange: str) -> float:
        """Get live market price for a ticker.

        Args:
            ticker: Stock symbol
            exchange: Exchange key ('US', 'XETRA', 'EURONEXT')

        Returns:
            float: Current market price

        Raises:
            ValueError: If price unavailable
        """
        contract = self._create_contract(ticker, exchange)
        self.ib.reqMarketDataType(1)  # Live data
        mkt_data = self.ib.reqMktData(contract, snapshot=True)

        price = None
        for _ in range(3):  # Retry up to 3 times (some exchanges are slower to respond)
            self.ib.sleep(2)
            if mkt_data.last and not math.isnan(mkt_data.last):
                price = mkt_data.last
                break
            if mkt_data.close and not math.isnan(mkt_data.close):
                price = mkt_data.close
                break
            # Fallback: use midpoint of bid/ask if available
            bid_ok = mkt_data.bid and not math.isnan(mkt_data.bid) and mkt_data.bid > 0
            ask_ok = mkt_data.ask and not math.isnan(mkt_data.ask) and mkt_data.ask > 0
            if bid_ok and ask_ok:
                price = (mkt_data.bid + mkt_data.ask) / 2
                break

        self.ib.cancelMktData(contract)

        if price is None:
            raise ValueError(f"Unable to get market price for {ticker} on {exchange}")

        return price

    # ==========================================
    # ORDER PLACEMENT
    # ==========================================

    def place_midprice_order(self, ticker: str, action: str, qty: int,
                             exchange: str) -> 'Trade':
        """Place a Pegged-to-Midpoint order.

        On exchanges that support PEG MID (e.g. US/SMART), places a native
        midprice order. On exchanges that don't (e.g. EURONEXT/AEB), falls back
        to a limit order at the calculated (bid+ask)/2.

        Args:
            ticker: Stock symbol
            action: 'BUY' or 'SELL'
            qty: Number of shares
            exchange: Exchange key

        Returns:
            Trade object
        """
        if not EXCHANGES[exchange].get('native_midprice', True):
            print(f"[IBKR] PEG MID not supported on {exchange}, falling back to market order")
            return self.place_market_order(ticker, action, qty, exchange)
        contract = self._create_contract(ticker, exchange)
        order = Order(action=action, totalQuantity=qty, orderType='PEG MID')
        return self._place_and_verify(contract, order, ticker)

    def place_market_order(self, ticker: str, action: str, qty: int,
                           exchange: str) -> 'Trade':
        """Place a market order.

        Args:
            ticker: Stock symbol
            action: 'BUY' or 'SELL'
            qty: Number of shares
            exchange: Exchange key

        Returns:
            Trade object
        """
        contract = self._create_contract(ticker, exchange)
        order = MarketOrder(action, qty)
        return self._place_and_verify(contract, order, ticker)

    def place_trailing_stop_order(self, ticker: str, action: str, qty: int,
                                  trail_pct: float, exchange: str) -> 'Trade':
        """Place a trailing stop order with percentage-based trail.

        Args:
            ticker: Stock symbol
            action: 'BUY' or 'SELL'
            qty: Number of shares
            trail_pct: Trailing percentage (e.g. 1.5 for 1.5%)
            exchange: Exchange key

        Returns:
            Trade object
        """
        contract = self._create_contract(ticker, exchange)
        order = Order(
            action=action,
            totalQuantity=qty,
            orderType='TRAIL',
            trailingPercent=trail_pct,
        )
        return self._place_and_verify(contract, order, ticker)

    def place_stop_loss(self, ticker: str, qty: int, stop_price: float,
                        exchange: str) -> 'Trade':
        """Place a protective stop loss order.

        Args:
            ticker: Stock symbol
            qty: Number of shares
            stop_price: Stop trigger price
            exchange: Exchange key

        Returns:
            Trade object
        """
        contract = self._create_contract(ticker, exchange)
        order = StopOrder('SELL', qty, round(stop_price, 2))
        return self._place_and_verify(contract, order, ticker)

    # ==========================================
    # ORDER MANAGEMENT
    # ==========================================

    def modify_order_qty(self, trade, new_qty: int) -> None:
        """Modify the quantity of an existing order.

        Args:
            trade: Trade object to modify
            new_qty: New quantity
        """
        trade.order.totalQuantity = new_qty
        self.ib.placeOrder(trade.contract, trade.order)
        self.ib.sleep(1)

    def cancel_order(self, trade) -> None:
        """Cancel a specific order.

        Args:
            trade: Trade object to cancel
        """
        self.ib.cancelOrder(trade.order)
        self.ib.sleep(1)

    def cancel_all_orders(self) -> int:
        """Cancel all open orders.

        Returns:
            int: Number of orders cancelled
        """
        open_orders = self.ib.openOrders()
        count = len(open_orders)
        if count > 0:
            self.ib.reqGlobalCancel()
            self.ib.sleep(2)
            print(f"[IBKR] Cancelled {count} open orders for account {self.account_id}")
        return count

    def cancel_orders_for_ticker(self, ticker: str) -> int:
        """Cancel all open orders for a specific ticker across all sessions.

        Used before placing a sell order to avoid IBKR treating the combined
        open sell orders (e.g. existing stop-loss + new sell) as a short sale.

        Attempts per-order cancel first. If any orders remain after 2s (e.g. they
        belong to a different client session and Error 10147 was returned), falls back
        to reqGlobalCancel() which works across all sessions, then re-verifies.

        Args:
            ticker: Stock symbol

        Returns:
            int: Number of orders cancelled

        Raises:
            RuntimeError: If orders still remain after both cancel attempts.
        """
        open_trades = self.ib.openTrades()
        to_cancel = [t for t in open_trades if t.contract.symbol == ticker]
        if not to_cancel:
            return 0

        # Statuses that indicate a cancel is accepted/in-flight — safe to proceed
        cancelling_statuses = {'PendingCancel', 'Cancelled', 'Inactive', 'ApiCancelled'}

        for trade in to_cancel:
            self.ib.cancelOrder(trade.order)
        self.ib.sleep(2)

        still_open = [
            t for t in self.ib.openTrades()
            if t.contract.symbol == ticker
            and t.orderStatus.status not in cancelling_statuses
        ]
        if still_open:
            # Per-order cancel failed (likely cross-session orders); fall back to global cancel
            print(f"[IBKR] Per-order cancel incomplete for {ticker} ({len(still_open)} remaining) — using reqGlobalCancel()")
            self.ib.reqGlobalCancel()
            self.ib.sleep(2)
            still_open = [
                t for t in self.ib.openTrades()
                if t.contract.symbol == ticker
                and t.orderStatus.status not in cancelling_statuses
            ]
            if still_open:
                raise RuntimeError(
                    f"Failed to cancel {len(still_open)} open order(s) for {ticker} even after reqGlobalCancel()."
                )

        print(f"[IBKR] Cancelled {len(to_cancel)} open order(s) for {ticker} before selling")
        return len(to_cancel)

    def get_open_orders(self) -> list:
        """Get all open orders."""
        return self.ib.openOrders()

    def get_pending_buy_value(self, exchange: str) -> float:
        """Estimate cash committed to pending BUY orders from all sessions.

        Must be called after connect() so reqAllOpenOrders() has already synced
        orders from all sessions. Used to compute truly available cash before
        placing a new BUY order or performing a cash sufficiency check.

        Only counts orders with a determinable price (LMT via lmtPrice, or STP/TRAIL
        via auxPrice). Market (MKT) and pegged (PEG MID) orders are excluded because
        their execution price is not known in advance.

        Args:
            exchange: Exchange key — used only for log context

        Returns:
            float: Estimated cash reserved by pending BUY orders
        """
        active_statuses = {'PreSubmitted', 'Submitted', 'PendingSubmit'}
        total = 0.0
        for trade in self.ib.openTrades():
            if trade.order.action != 'BUY':
                continue
            if trade.orderStatus.status not in active_statuses:
                continue
            remaining_qty = trade.order.totalQuantity - (trade.orderStatus.filled or 0)
            if remaining_qty <= 0:
                continue
            # Determine price: prefer lmtPrice, fall back to auxPrice (stop/trail price).
            # Exclude ib_insync's UNSET_DOUBLE sentinel (~1.8e308) which compares > 0
            # but is not a real price.
            price = None
            if trade.order.lmtPrice and 0 < trade.order.lmtPrice < UNSET_DOUBLE:
                price = trade.order.lmtPrice
            elif trade.order.auxPrice and 0 < trade.order.auxPrice < UNSET_DOUBLE:
                price = trade.order.auxPrice
            if price:
                reserved = remaining_qty * price
                total += reserved
                print(f"[IBKR] Pending BUY [{exchange}]: {trade.contract.symbol} "
                      f"{remaining_qty} @ {price:.2f} = {reserved:.2f} reserved")
        if total > 0:
            print(f"[IBKR] Total pending BUY reserved cash [{exchange}]: {total:.2f}")
        return total

    # ==========================================
    # FILL DETECTION
    # ==========================================

    def is_filled(self, trade) -> bool:
        """Check if a trade is fully filled."""
        self.ib.sleep(0)  # Process pending events
        return trade.isDone() and trade.orderStatus.status == 'Filled'

    def is_done(self, trade) -> bool:
        """Check if a trade is done (filled, cancelled, or error)."""
        self.ib.sleep(0)
        return trade.isDone()

    def get_fill_price(self, trade) -> float:
        """Get the average fill price from a completed trade.

        Uses trade.orderStatus.avgFillPrice as the primary source — this is
        populated atomically with the 'Filled' status update. Falls back to
        trade.fills (execDetails) which can arrive slightly later.

        Returns:
            float: Average fill price, or 0.0 if not filled
        """
        # Primary: orderStatus fields arrive with the 'Filled' status update
        if trade.orderStatus.avgFillPrice:
            return float(trade.orderStatus.avgFillPrice)
        # Fallback: execDetails (may arrive after orderStatus)
        if trade.fills:
            total_value = sum(f.execution.price * f.execution.shares for f in trade.fills)
            total_shares = sum(f.execution.shares for f in trade.fills)
            if total_shares > 0:
                return total_value / total_shares
        return 0.0

    def get_filled_qty(self, trade) -> int:
        """Get the total filled quantity.

        Uses trade.orderStatus.filled as the primary source — this is
        populated atomically with the 'Filled' status update. Falls back to
        trade.fills (execDetails) which can arrive slightly later.

        Returns:
            int: Total filled shares
        """
        # Primary: orderStatus fields arrive with the 'Filled' status update
        if trade.orderStatus.filled:
            return int(trade.orderStatus.filled)
        # Fallback: execDetails (may arrive after orderStatus)
        if trade.fills:
            return int(sum(f.execution.shares for f in trade.fills))
        return 0

    def wait_for_fill(self, trade, timeout_seconds: int = 60) -> bool:
        """Block until a trade is filled or timeout.

        Args:
            trade: Trade object
            timeout_seconds: Maximum wait time

        Returns:
            bool: True if filled, False if timed out
        """
        elapsed = 0
        while elapsed < timeout_seconds:
            self.ib.sleep(1)
            elapsed += 1
            if trade.isDone():
                return True
        return False

    # ==========================================
    # INTERNAL HELPERS
    # ==========================================

    def _create_contract(self, ticker: str, exchange: str) -> Stock:
        """Create an exchange-aware stock contract.

        Args:
            ticker: Stock symbol
            exchange: Exchange key ('US', 'XETRA', 'EURONEXT')

        Returns:
            Stock contract object
        """
        cfg = EXCHANGES[exchange]
        return Stock(ticker, cfg['ibkr_exchange'], cfg['currency'])

    def _place_and_verify(self, contract, order, ticker: str) -> 'Trade':
        """Place an order and verify it wasn't immediately rejected.

        Args:
            contract: IBKR contract
            order: IBKR order
            ticker: Symbol for error messages

        Returns:
            Trade object

        Raises:
            OrderRejectedError: If order is rejected
        """
        order.account = self.account_id
        trade = self.ib.placeOrder(contract, order)
        self.ib.sleep(2)  # Allow status to propagate

        if trade.orderStatus.status == 'Inactive':
            log_msg = trade.log[-1].message if trade.log else 'unknown reason'
            raise OrderRejectedError(
                f"Order rejected for {ticker}: {order.action} {order.totalQuantity} "
                f"({order.orderType}) - {log_msg}"
            )

        print(
            f"[IBKR] Order placed: {order.action} {order.totalQuantity} {ticker} "
            f"({order.orderType}) - status: {trade.orderStatus.status}"
        )
        return trade
