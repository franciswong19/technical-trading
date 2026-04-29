"""
data_fetcher.py

Fetches three-tier OHLCV data from IB Gateway for trendline analysis.
Uses utils/utils_ibkr_historical.py for the actual IB API calls.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd
import pandas_market_calendars as mcal

# Path setup
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from utils.utils_ibkr_historical import fetch_tier_data
from utils.utils_trendline_engine.config import CONFIG


def resolve_reference_date(reference_date: str = '') -> str:
    """Resolve the reference date. If blank, use yesterday.

    The reference date might not be a trading day. That's OK — IB will
    return data up to the last available bar on or before the date.

    Args:
        reference_date: Date string 'YYYY-MM-DD' or empty.

    Returns:
        Resolved date string 'YYYY-MM-DD'.
    """
    if not reference_date or reference_date.strip() == '':
        yesterday = datetime.now() - timedelta(days=1)
        return yesterday.strftime('%Y-%m-%d')
    return reference_date.strip()


def fetch_all_tiers(ib, ticker: str, reference_date: str = '',
                    exchange: str = 'SMART', currency: str = 'USD',
                    config: dict = None,
                    tiers: list = None) -> dict[str, pd.DataFrame]:
    """Fetch OHLCV data for the requested analysis tiers from IB Gateway.

    Args:
        ib: Connected IB instance.
        ticker: Stock symbol (e.g. 'QQQ').
        reference_date: Reference date 'YYYY-MM-DD' or empty for yesterday.
        exchange: IBKR exchange (default 'SMART').
        currency: Currency (default 'USD').
        config: Optional config override.
        tiers: List of tier names to fetch (default: all three tiers).

    Returns:
        Dict with keys for each requested tier, each containing a DataFrame
        with columns: t, open, high, low, close, volume.
    """
    if tiers is None:
        tiers = ['short_term', 'medium_term', 'long_term']

    ref_date = resolve_reference_date(reference_date)
    print(f"  Fetching data for {ticker}, reference date: {ref_date}")

    result = {}
    for tier in tiers:
        print(f"    [{tier}] ", end='')
        df = fetch_tier_data(
            ib=ib,
            ticker=ticker,
            tier=tier,
            reference_date=ref_date,
            exchange=exchange,
            currency=currency,
        )
        print(f"{len(df)} bars fetched.")
        result[tier] = df

        # Respect IB pacing limits
        ib.sleep(1)

    return result


def get_next_trading_day(reference_date: str, calendar_name: str = 'NYSE') -> datetime:
    """Get the next trading day after the reference date.

    Used for extending trendlines into the future on charts.

    Args:
        reference_date: Date string 'YYYY-MM-DD'.
        calendar_name: Market calendar name (default 'NYSE').

    Returns:
        datetime of the next trading day.
    """
    cal = mcal.get_calendar(calendar_name)
    ref_dt = pd.Timestamp(reference_date)

    # Look ahead up to 10 days to find the next trading day
    end_dt = ref_dt + timedelta(days=10)
    schedule = cal.schedule(start_date=ref_dt + timedelta(days=1), end_date=end_dt)

    if not schedule.empty:
        return schedule.index[0].to_pydatetime()

    # Fallback: just add 1 day
    return ref_dt.to_pydatetime() + timedelta(days=1)
