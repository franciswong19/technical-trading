import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import talib
# Import the API_KEY from your new connection utility
from .utils_polygon_connection import API_KEY



# ==========================================
# CORE FUNCTIONS
# ==========================================

def get_ohlc_data(ticker, end_date, lookback_days, multiplier, timespan, api_key=API_KEY):
    """
    Fetches OHLC data from Polygon.io ending at 'end_date' with flexible aggregation.

    Parameters:
    - ticker (str): Stock symbol (e.g., 'AAPL').
    - end_date (str/datetime): The end date/time for the data query.
    - lookback_days (int): The number of calendar days of history to fetch.
    - multiplier (int): The number of timespans to aggregate (e.g., 1, 5, 10).
    - timespan (str): The unit of time (e.g., 'minute', 'hour', 'day', 'week', 'month', 'quarter', 'year').

    Returns:
    - pandas.DataFrame: OHLC data, or None on failure.
    """

    end_dt = pd.to_datetime(end_date)
    # Calculate start date based on the lookback days (calendar days)
    start_dt = end_dt - pd.Timedelta(days=lookback_days)

    # Use ISO format for dates to satisfy Polygon API
    start_str = start_dt.isoformat()[:10]
    end_str = end_dt.isoformat()[:10]

    url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{start_str}/{end_str}"

    # Polygon API max limit is 50000 bars per call
    params = {"apiKey": api_key, "limit": 50000, "sort": "asc", "adjusted": "true"}

    print(f"  -> Fetching {multiplier} {timespan} data...")

    try:
        resp = requests.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException as e:
        print(f"Request failed for {ticker}: {e}")
        return None

    if "results" not in data:
        print(f"  -> No results found for {ticker} in range.")
        return None

    df = pd.DataFrame(data["results"])

    # 't' is the timestamp. Convert to date for daily/weekly or datetime for minute/hour data.
    df["t"] = pd.to_datetime(df["t"], unit="ms")

    # Apply market hours filter to ALL data
    if timespan in ["minute", "hour"]:
        df = df.set_index("t").between_time("09:30", "16:00").reset_index()

    # If the aggregation is 'day' or larger, we usually only care about the date part.
    if timespan in ["day", "week", "month", "quarter", "year"]:
        df["t"] = df["t"].dt.date

    df = df.rename(columns={"c": "close", "o": "open", "h": "high", "l": "low", "v": "volume"})

    # Ensure data is sorted by time/date
    return df.sort_values("t").reset_index(drop=True)


def get_technical_indicators(df):
    """
    Computes EMA, ADX, Bollinger Bands, and RSI using TA-Lib.
    Prerequisite: get_ohlc_data()
    """
    if df is None or df.empty:
        return None

    # Arrays for TA-Lib
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values

    # 1. EMAs
    df["EMA30"] = talib.EMA(close, timeperiod=30)
    df["EMA150"] = talib.EMA(close, timeperiod=150)

    # 2. ADX / DI
    df["PLUS_DI"] = talib.PLUS_DI(high, low, close, timeperiod=14)
    df["MINUS_DI"] = talib.MINUS_DI(high, low, close, timeperiod=14)
    df["DI_diff"] = df["PLUS_DI"] - df["MINUS_DI"]

    # 3. Bollinger Bands (Using 100 period as per your snippet)
    upper, middle, lower = talib.BBANDS(close, timeperiod=100, nbdevup=2, nbdevdn=2, matype=0)
    df["BB_Upper"] = upper
    df["BB_Lower"] = lower

    # 4. RSI (14)
    df["RSI"] = talib.RSI(close, timeperiod=14)

    return df


def calculate_crossovers(df):
    """
    Calculates the numerical difference (crossover value) for various indicators.
    A positive result indicates the 'condition' is met.

    Prerequisite: This function calls get_technical_indicators(df) internally.
    """

    if df is None or df.empty:
        return None

    # 2. Calculate Crossover columns (Numerical differences)
    # Price > EMA 30
    df["close_ema30_crossover"] = df["close"] - df["EMA30"]

    # EMA 30 > EMA 150
    df["ema30_ema150_crossover"] = df["EMA30"] - df["EMA150"]

    # +DI > -DI
    df["adx_crossover"] = df["DI_diff"]

    # Price > Upper Bollinger Band
    df["close_bbupper_crossover"] = df["close"] - df["BB_Upper"]

    # Price < Lower Bollinger Band (Met if result is positive)
    df["bblower_close_crossover"] = df["BB_Lower"] - df["close"]

    # RSI < 30 (Met if result is positive)
    df["rsi_30_crossover"] = 30 - df["RSI"]

    # RSI > 70 (Met if result is positive)
    df["rsi_70_crossover"] = df["RSI"] - 70

    return df


def calculate_crossover_periods(df, window_size=10):
    """
    Redone scoring logic based on Ranking.

    1. Filters for the last 'window_size' rows.
    2. Ranks rows: 0 is the latest timestamp.
    3. Identifies 'pos', 'neg', or the rank of the most recent positive crossover.
    """
    # Create a copy to avoid SettingWithCopy warnings
    temp_df = df.copy().sort_values("t", ascending=False).reset_index(drop=True)

    # 1. Select the last X bars (window_size)
    # Even if period_type is minutes, this selects the last X periods
    analysis_df = temp_df.head(window_size).copy()

    # 2. Rank the rows: 0 being the latest timestamp
    analysis_df["rank"] = range(len(analysis_df))

    # ADDED DEBUG PRINT
    print(f"\n--- Debug: Starting Crossover Calculation ---")
    # Filter columns that contain 'crossover' or are exactly 'rank'
    debug_cols = [col for col in analysis_df.columns if "crossover" in col or col == "rank"]
    # Print only those columns
    print(f"DataFrame received (Filtered):\n{analysis_df[debug_cols].to_string(index=False)}")
    # ---------------------------

    results = {}

    # Identify all crossover columns
    crossover_cols = [col for col in analysis_df.columns if "crossover" in col]

    for col in crossover_cols:
        new_col_name = f"{col}_period"
        series = analysis_df[col]

        # 1. If all values are positive or zero, then col = 'pos'
        if (series >= 0).all():
            results[new_col_name] = 'pos'

        # 2. If all values are negative, then col = 'neg'
        elif (series < 0).all():
            results[new_col_name] = 'neg'

        # 3. Otherwise, find the lowest rank of a positive value
        # that follows a negative value from the previous higher rank (older data)
        else:
            # We shift the series to compare each value with the one at the 'previous higher rank'
            # analysis_df is sorted by rank 0, 1, 2... (0 is newest, 9 is oldest)
            # series.shift(-1) brings the older data (rank i+1) up to compare with rank i
            is_positive = series >= 0
            was_negative = series.shift(-1) < 0

            # A 'flip' is where current is positive AND previous was negative
            flips = analysis_df[is_positive & was_negative]

            if not flips.empty:
                # The first row in 'flips' is the one with the lowest rank (most recent)
                results[new_col_name] = int(flips["rank"].iloc[0])
            else:
                # Fallback: if there are negatives but no - to + transition (e.g., currently negative)
                results[new_col_name] = 'neg'

    return results


def process_technical_indicators(ticker, end_date, lookback=365, multiplier=1, timespan="day", window=10):
    """
    Main orchestrator for a single ticker. Now parameterized for flexible calls.

    Parameters:
    - ticker (str): Stock symbol.
    - end_date (str): The cutoff date for analysis.
    - lookback (int): How many calendar days of history to fetch from API.
    - multiplier (int): The size of the timespan (e.g., 10 for 10 minute bars).
    - timespan (str): The unit of time (e.g., 'minute', 'day').
    - window (int): The number of periods to look back for the crossover scoring.
    """

    # 1. Fetch Data using the parameters
    df = get_ohlc_data(ticker, end_date, lookback, multiplier, timespan)
    if df is None:
        return None

    # 2. Calculate Technicals & Crossovers
    # Ensure these function names match your library
    df = get_technical_indicators(df)
    df = calculate_crossovers(df)

    # 3. Filter to the specific evaluation end point (The "Time-Travel Gatekeeper")
    end_date_dt = pd.to_datetime(end_date)

    if df.empty:
        return None

    # Check if 't' is date (Daily/Weekly) or datetime (Intraday) for proper masking
    if isinstance(df["t"].iloc[-1], pd.Timestamp):
        mask = df["t"] <= end_date_dt
    else:
        mask = df["t"] <= end_date_dt.date()

    df_filtered = df[mask]

    # Use the 'window' parameter to ensure we have enough data points
    if len(df_filtered) < window:
        print(f"Insufficient data for {ticker}. Needed {window}, got {len(df_filtered)}")
        return None

    # 4. Generate Results using the ranking-based logic
    # This returns a dictionary of all xxxxx_crossover_period results
    scoring_results = calculate_crossover_periods(df_filtered, window_size=window)

    return scoring_results