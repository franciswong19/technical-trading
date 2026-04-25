"""
utils_ibkr_historical.py

Reusable utility for fetching historical OHLCV bars from IB Gateway via ib_insync.
Returns DataFrames in the same format as utils_technical_indicators.get_ohlc_data()
(columns: t, open, high, low, close, volume) for interoperability.
"""

import pandas as pd
from datetime import datetime
from ib_insync import IB, Stock


# IB bar size strings
BAR_SIZE_MAP = {
    '15min': '15 mins',
    '1hour': '1 hour',
    'daily': '1 day',
}

# IB duration strings per tier
DURATION_MAP = {
    'short_term': '25 D',     # 25 calendar days ≈ 20 trading days + buffer
    'medium_term': '90 D',    # 90 calendar days ≈ 60 trading days + buffer
    'long_term': '1 Y',       # 1 year ≈ 260 trading days
}


def fetch_historical_bars(
    ib: IB,
    ticker: str,
    end_date: str = '',
    bar_size: str = 'daily',
    duration: str = '1 Y',
    exchange: str = 'SMART',
    currency: str = 'USD',
    use_rth: bool = True,
    what_to_show: str = 'TRADES',
) -> pd.DataFrame:
    """Fetch historical OHLCV bars from IB Gateway.

    Args:
        ib: Connected IB instance.
        ticker: Stock symbol (e.g. 'QQQ').
        end_date: End date/time in IB format 'YYYYMMDD HH:MM:SS' or '' for now.
        bar_size: Bar size key: '15min', '1hour', 'daily' (mapped to IB strings).
        duration: IB duration string (e.g. '20 D', '1 Y').
        exchange: IBKR exchange (default 'SMART').
        currency: Currency (default 'USD').
        use_rth: If True, only return regular trading hours data.
        what_to_show: Data type ('TRADES', 'MIDPOINT', 'BID', 'ASK').

    Returns:
        DataFrame with columns: t (datetime), open, high, low, close, volume.
        Sorted ascending by timestamp. Empty DataFrame if no data.
    """
    ib_bar_size = BAR_SIZE_MAP.get(bar_size, bar_size)

    contract = Stock(ticker, exchange, currency)
    ib.qualifyContracts(contract)

    bars = ib.reqHistoricalData(
        contract,
        endDateTime=end_date,
        durationStr=duration,
        barSizeSetting=ib_bar_size,
        whatToShow=what_to_show,
        useRTH=use_rth,
        formatDate=1,
    )

    if not bars:
        print(f"[WARN] No historical data returned for {ticker} ({bar_size}, {duration})")
        return pd.DataFrame(columns=['t', 'open', 'high', 'low', 'close', 'volume'])

    records = []
    for bar in bars:
        records.append({
            't': pd.Timestamp(bar.date),
            'open': float(bar.open),
            'high': float(bar.high),
            'low': float(bar.low),
            'close': float(bar.close),
            'volume': int(bar.volume),
        })

    df = pd.DataFrame(records)
    df = df.sort_values('t', ascending=True).reset_index(drop=True)
    return df


def fetch_tier_data(
    ib: IB,
    ticker: str,
    tier: str,
    reference_date: str = '',
    exchange: str = 'SMART',
    currency: str = 'USD',
) -> pd.DataFrame:
    """Fetch historical data for a specific analysis tier.

    Args:
        ib: Connected IB instance.
        ticker: Stock symbol.
        tier: 'short_term', 'medium_term', or 'long_term'.
        reference_date: Reference date as 'YYYY-MM-DD' or '' for latest.
        exchange: IBKR exchange.
        currency: Currency.

    Returns:
        DataFrame with OHLCV data for the tier's lookback period.
    """
    tier_to_bar_size = {
        'short_term': '15min',
        'medium_term': '1hour',
        'long_term': 'daily',
    }

    bar_size = tier_to_bar_size[tier]
    duration = DURATION_MAP[tier]

    # Convert reference_date to IB endDateTime format
    end_date = ''
    if reference_date:
        dt = datetime.strptime(reference_date, '%Y-%m-%d')
        # For intraday bars, set end time to market close (16:00 ET)
        if bar_size in ('15min', '1hour'):
            end_date = dt.strftime('%Y%m%d') + ' 16:00:00 US/Eastern'
        else:
            end_date = dt.strftime('%Y%m%d') + ' 23:59:59'

    return fetch_historical_bars(
        ib=ib,
        ticker=ticker,
        end_date=end_date,
        bar_size=bar_size,
        duration=duration,
        exchange=exchange,
        currency=currency,
    )
