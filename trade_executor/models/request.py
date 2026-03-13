"""
request.py

Data models for trade execution requests.
These dataclasses define the contract between Claude (main agent) and Python executors.
"""

import json
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class TickerParams:
    """Parameters for a single ticker within a trade request."""
    ticker: str
    fulfillment_pct: float                         # 0.01 to 1.0 (1% to 100%)
    initial_order_type: str                        # 'market' / 'midprice' / 'trailing_stop' / 'trailing_stop_threshold' / 'fixed_stop'
    initial_trailing_pct: Optional[float] = None   # If initial order is trailing stop (e.g. 1.5)
    initial_threshold_price: Optional[float] = None  # If initial_order_type='trailing_stop_threshold' or 'fixed_stop'
    subsequent_order_type: Optional[str] = None    # HOT POTATO only: 'trailing_stop'
    subsequent_trailing_pct: Optional[float] = None  # HOT POTATO only: trailing stop %
    stop_type: Optional[str] = None                # 'NORMAL' / 'HEIGHTENED' / 'FIXED_PRICE' / 'ADHOC'
    stop_fixed_price: Optional[float] = None       # If stop_type == 'FIXED_PRICE'
    stop_adhoc_trailing_pct: Optional[float] = None  # HOT POTATO Stop type 2: ADHOC trailing stop %
    stop_type1_pct: Optional[float] = None         # HOT POTATO Stop type 1: fixed stop % offset from fill price
    cycle_threshold: Optional[int] = None          # HOT POTATO only, default 3


@dataclass
class TradeRequest:
    """Complete trade execution request."""
    request_id: str
    accounts: list                # List of dicts: [{"alias": "LIVE-US", "account_id": "U13868670", "port": 7496}]
    exchange: str                 # 'US' / 'XETRA' / 'EURONEXT'
    ticker_params: list           # List of TickerParams (serialized as dicts in JSON)
    request_type: str             # SELL_EVERYTHING_NOW / NORMAL_BUY / NORMAL_SELL / FAST_BUY / FAST_SELL / HOT_POTATO
    transaction_type: str         # 'BUY' / 'SELL' — initial order direction
    duration_type: str            # 'IMMEDIATE' / 'BEFORE_CLOSE' / 'TIMED'
    duration_minutes: Optional[int] = None  # If duration_type == 'TIMED'
    transaction_type_before_close: Optional[str] = None  # HOT POTATO only: 'BUY' / 'SELL' — desired position at end-of-day

    def to_json(self, path: str) -> None:
        """Write request to a JSON file."""
        data = asdict(self)
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)

    @classmethod
    def from_json(cls, path: str) -> 'TradeRequest':
        """Load request from a JSON file."""
        with open(path, 'r') as f:
            data = json.load(f)

        # Reconstruct TickerParams objects from dicts
        ticker_params = [TickerParams(**tp) for tp in data.pop('ticker_params')]
        return cls(ticker_params=ticker_params, **data)

    def to_dict(self) -> dict:
        """Convert to a plain dictionary."""
        return asdict(self)
