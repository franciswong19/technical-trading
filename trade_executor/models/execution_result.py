"""
execution_result.py

Data models for trade execution results.
Written by executor scripts, read by Claude (main agent) for verification.
"""

import json
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional

import pytz

SGT = pytz.timezone('Asia/Singapore')


def stamp_ticker_completion(ticker_result: 'TickerResult', exchange_tz: pytz.BaseTzInfo) -> None:
    """Set completed_at_local and completed_at_sgt on a TickerResult."""
    now = datetime.now(exchange_tz)
    ticker_result.completed_at_local = now.isoformat()
    ticker_result.completed_at_sgt = now.astimezone(SGT).isoformat()


@dataclass
class TickerResult:
    """Result for a single ticker execution."""
    ticker: str
    action: str                            # 'BUY' / 'SELL'
    seq_num: int = 1                       # Sequence number (>1 for HOT POTATO cycles)
    target_qty: int = 0
    filled_qty: int = 0
    avg_fill_price: float = 0.0
    order_type_used: str = ''              # 'midprice' / 'market' / 'trailing_stop'
    escalated_to_market: bool = False
    stop_loss_placed: bool = False
    stop_loss_price: Optional[float] = None
    stop_loss_order_id: Optional[int] = None
    completed_at_local: str = ''           # ISO timestamp in exchange local time
    completed_at_sgt: str = ''             # ISO timestamp in Singapore Time (SGT)
    error: Optional[str] = None


@dataclass
class AccountResult:
    """Result for a single account within a request."""
    account_id: str
    ticker_results: list = field(default_factory=list)  # List of TickerResult dicts


@dataclass
class ExecutionResult:
    """Complete execution result for a trade request."""
    request_id: str
    status: str = 'PENDING'                # 'COMPLETED' / 'PARTIAL' / 'FAILED'
    started_at: str = ''                   # ISO timestamp
    completed_at: str = ''                 # ISO timestamp
    exchange: str = ''
    request_type: str = ''
    account_results: list = field(default_factory=list)  # List of AccountResult dicts
    errors: list = field(default_factory=list)            # List of error strings

    def to_json(self, path: str) -> None:
        """Write result to a JSON file."""
        data = asdict(self)
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)

    @classmethod
    def from_json(cls, path: str) -> 'ExecutionResult':
        """Load result from a JSON file."""
        with open(path, 'r') as f:
            data = json.load(f)

        # Reconstruct nested objects
        account_results = []
        for ar in data.pop('account_results', []):
            ticker_results = [TickerResult(**tr) for tr in ar.pop('ticker_results', [])]
            account_results.append(AccountResult(ticker_results=ticker_results, **ar))

        return cls(account_results=account_results, **data)

    def to_dict(self) -> dict:
        """Convert to a plain dictionary."""
        return asdict(self)
