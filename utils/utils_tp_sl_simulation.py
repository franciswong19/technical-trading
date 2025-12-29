# utils/utils_tp_sl_simulation.py
import time
import pandas as pd
from .utils_technical_indicators import get_ohlc_data


def run_simulation(ticker, pick_date, calendar_days, tp_sl_list, trading_days_limit=10, ts_pct=0.08):
    """
    Part 2 & 3: Consolidated function to fetch data and simulate TP/SL/TS performance.
    """
    # --- PART 2: Fetch OHLC Data ---
    pick_dt = pd.to_datetime(pick_date)
    end_dt = pick_dt + pd.Timedelta(days=calendar_days)

    # Reusing existing utility to fetch 5-min intervals
    df_ohlc = get_ohlc_data(
        ticker=ticker,
        end_date=end_dt.strftime('%Y-%m-%d'),
        lookback_days=calendar_days,
        multiplier=5,
        timespan="minute"
    )

    if df_ohlc is None or df_ohlc.empty:
        return {"error": "No OHLC data returned from Polygon"}

    # Exclude the 'Date' specified in the input
    df_ohlc['date_only'] = pd.to_datetime(df_ohlc['t']).dt.date
    df_ohlc = df_ohlc[df_ohlc['date_only'] > pick_dt.date()].copy()
    df_ohlc = df_ohlc.sort_values('t').reset_index(drop=True)

    if df_ohlc.empty:
        return {"error": "No data available after the pick date"}

    # --- PART 3: Simulate TP, SL & Trailing Stop ---
    try:
        # 1. Identify valid trading days
        unique_days = sorted(df_ohlc['date_only'].unique())
        target_days = unique_days[:trading_days_limit]
        df = df_ohlc[df_ohlc['date_only'].isin(target_days)].copy()

        # 2. Exclude first 10 mins (9:30-9:39) of the first trading day
        first_day = target_days[0]
        mask_mkt_open = (df['date_only'] == first_day) & (
                    pd.to_datetime(df['t']).dt.time < pd.to_datetime("09:40:00").time())
        df = df[~mask_mkt_open].copy()

        if df.empty:
            return {"error": "Insufficient data after morning exclusion"}

        # 3. Create Sequences
        df['trading_timestamp_sequence'] = range(len(df))
        df['trading_day_sequence'] = df['date_only'].map({d: i for i, d in enumerate(target_days)})
        df['trading_interval_sequence'] = df.groupby('date_only').cumcount()

        # 4. Define Buy Price (9:40 AM open of the first day)
        buy_row = df.iloc[0]
        buy_price = buy_row['open']
        buy_timestamp = buy_row['t']

        # 5. Iterative Loop for Trailing Stop and Existing TP/SL Breaches
        maxima = 0
        ts_breach_row = None
        
        # We also need to calculate TP/SL breaches
        df['is_tp_breached'] = 0
        df['is_sl_breached'] = 0
        for tp_mult, sl_mult, start_seq, end_seq in tp_sl_list:
            mask = (df['trading_day_sequence'] >= start_seq) & (df['trading_day_sequence'] <= end_seq)
            df.loc[mask & (df['high'] >= buy_price * tp_mult), 'is_tp_breached'] = 1
            df.loc[mask & (df['low'] <= buy_price * sl_mult), 'is_sl_breached'] = 1

        # Calculate Trailing Stop iteratively
        for idx, row in df.iterrows():
            # Update Maxima
            if row['trading_timestamp_sequence'] == 0:
                maxima = row['high']
            else:
                maxima = max(maxima, row['high'])
            
            # Check for TS Breach
            trigger_sell_price = maxima * (1 - ts_pct)
            if row['low'] <= trigger_sell_price:
                ts_breach_row = row.copy()
                ts_breach_row['ts_sell_price'] = trigger_sell_price
                break # Stop loop once TS is breached

        # 6. Find earliest breach of all three strategies
        tp_hits = df[df['is_tp_breached'] == 1]
        sl_hits = df[df['is_sl_breached'] == 1]

        earliest_tp = tp_hits['trading_timestamp_sequence'].min() if not tp_hits.empty else float('inf')
        earliest_sl = sl_hits['trading_timestamp_sequence'].min() if not sl_hits.empty else float('inf')
        earliest_ts = ts_breach_row['trading_timestamp_sequence'] if ts_breach_row is not None else float('inf')

        # 7. Determine Final Outcome based on what happened first
        first_event = min(earliest_tp, earliest_sl, earliest_ts)

        if first_event == float('inf'):
            # No breach: End of Holding (10th day at 9:40 AM)
            exit_cand = df[(df['trading_day_sequence'] == trading_days_limit - 1) & (df['trading_interval_sequence'] == 0)]
            exit_row = exit_cand.iloc[0] if not exit_cand.empty else df.iloc[-1]
            sell_price, trigger = exit_row['open'], "End of Holding Period"
        elif first_event == earliest_tp:
            exit_row = df[df['trading_timestamp_sequence'] == earliest_tp].iloc[0]
            sell_price, trigger = exit_row['high'], "Take Profit"
        elif first_event == earliest_sl:
            exit_row = df[df['trading_timestamp_sequence'] == earliest_sl].iloc[0]
            sell_price, trigger = exit_row['low'], "Stop Loss"
        else: # Trailing Stop was first
            exit_row = ts_breach_row
            sell_price, trigger = ts_breach_row['ts_sell_price'], "Trailing Stop"

        return {
            "buy price": buy_price, "sell price": sell_price,
            "returns_percentage": (sell_price / buy_price - 1) * 100,
            "buy_timestamp": buy_timestamp, "sell_timestamp": exit_row['t'],
            "trading_timestamp_sequence": exit_row['trading_timestamp_sequence'],
            "trading_day_sequence": exit_row['trading_day_sequence'],
            "trading_interval_sequence": exit_row['trading_interval_sequence'],
            "trigger": trigger, "error": None
        }
    except Exception as e:
        return {"error": f"Logic error: {str(e)}"}