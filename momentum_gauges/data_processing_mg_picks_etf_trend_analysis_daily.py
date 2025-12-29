import os
import sys
import time
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pathlib import Path
from datetime import datetime, timedelta

# --- PATH SETUP ---
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
sys.path.append(str(project_root))

from utils import utils_gsheet_handler
from utils import utils_technical_indicators
from utils import utils_email_handler

# ==========================================
# USER CONFIGURATION
# ==========================================
SPREADSHEET_ID = "13RfATfhAOOp_RCr3a_clcwXjrVdaFRib0_JTxUj729Q"
INPUT_TAB_NAME = "shortlist"

LOOKBACK = 150
MULTIPLIER = 1
TIMESPAN = "day"

TARGET_CATEGORIES = ["General ETF", "Sector ETF", "Sub-sector ETF", "Commodities"]
REF_DAYS = [5, 10, 20, 40, 65]


# ==========================================
# CALCULATION LOGIC
# ==========================================

def calculate_aligned_returns(df_ohlc, ticker, category, ref_days):
    """
    Ensures returns start at 0% at the Reference Day and only
    show the path from Ref Day (X) to Today (0).
    """
    # Head(70) to ensure we have enough for a 65-day lookback
    df = df_ohlc.sort_values("t", ascending=False).head(100).copy()
    df['day_seq'] = range(len(df))  # 0 is today, 10 is 10 days ago

    results = []
    for ref_val in ref_days:
        if ref_val >= len(df):
            continue

        # The price at the reference day (e.g., 10 days ago)
        ref_price = df.iloc[ref_val]['close']

        # Only take days from ref_val down to 0 (today)
        path_df = df[df['day_seq'] <= ref_val].copy()

        for _, row in path_df.iterrows():
            pct_diff = (row['close'] / ref_price) - 1
            results.append({
                'ticker': ticker,
                'price': round(row['close'], 2),
                'category': category,
                'ref_day': ref_val,
                'day_seq': row['day_seq'],
                'pct_diff': pct_diff
            })


    return results


# ==========================================
# VISUALIZATION (2-COLUMN GRID)
# ==========================================

def generate_visual_report(df_all):
    categories = [c for c in TARGET_CATEGORIES if c in df_all['category'].unique()]
    ref_days = sorted(df_all['ref_day'].unique())

    # Total subplots = Ref Days * Categories (e.g., 6 * 4 = 24)
    # With 2 columns, we need (Total / 2) rows
    total_plots = len(ref_days) * len(categories)
    num_cols = 2
    num_rows = (total_plots + 1) // num_cols

    # Generate sub-titles for each plot
    titles = []
    for rd in ref_days:
        for cat in categories:
            titles.append(f"Ref Day {rd} | {cat}")

    fig = make_subplots(
        rows=num_rows,
        cols=num_cols,
        subplot_titles=titles,
        vertical_spacing=0.02,
        # Increase this value (e.g., from 0.05 to 0.1 or 0.12) to add more horizontal gap
        horizontal_spacing=0.12,
        # Optional: Add specific column widths if you want to force more space in the middle
        column_widths=[0.45, 0.45]
    )

    plot_idx = 0
    for rd in ref_days:
        for cat in categories:
            curr_row = (plot_idx // num_cols) + 1
            curr_col = (plot_idx % num_cols) + 1

            mask = (df_all['ref_day'] == rd) & (df_all['category'] == cat)
            sub_df = df_all[mask]

            tickers = sub_df['ticker'].unique()
            for tkr in tickers:
                tkr_df = sub_df[sub_df['ticker'] == tkr].sort_values('day_seq', ascending=False)

                fig.add_trace(
                    go.Scatter(
                        x=tkr_df['day_seq'],
                        y=tkr_df['pct_diff'],
                        mode='lines',
                        name=tkr,
                        line=dict(width=1.5),
                        hovertemplate=f"<b>{tkr}</b><br>Day: %{{x}}<br>Return: %{{y:.2%}}<extra></extra>"
                    ),
                    row=curr_row, col=curr_col
                )

            # Label axes for every subplot
            fig.update_xaxes(title_text="Days Ago", row=curr_row, col=curr_col, autorange="reversed", showgrid=True)
            fig.update_yaxes(title_text="% Diff", row=curr_row, col=curr_col, tickformat=".1%", showgrid=True)

            plot_idx += 1

    fig.update_layout(
        height=num_rows * 350,
        width=1400,
        title_text="<b>ETF Trend Analysis</b>",
        template="plotly_white",
        showlegend=False,
        margin=dict(t=100, b=50, l=80, r=50)
    )

    # 1. Define and create the output directory
    output_folder = current_dir / "mg_picks_trend_analysis"
    output_folder.mkdir(parents=True, exist_ok=True)

    # 2. Save the file into that folder
    
    today_str = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
    file_path = output_folder / f"data_viz_mg_picks_etf_trend_analysis_daily_{today_str}.html"

    fig.write_html(str(file_path))
    print(f"Interactive report saved: {file_path}")
    # fig.show() is removed/commented out for automated runs

    # --- ADD THIS TO SEND EMAIL ---   
    report_date = datetime.now().strftime('%Y-%m-%d')

    EMAIL_SUBJECT = f"ETF trend analysis report {report_date}"
    EMAIL_CONTENT = f"This is the attached report on ETF trend analysis on {report_date}."
    TARGET_EMAIL = "francis.lunkai.wong@gmail.com"

    utils_email_handler.send_report_email(
        receiver_email=TARGET_EMAIL,
        file_path=str(file_path),
        sender_email=TARGET_EMAIL  # Usually same as receiver for personal reports
    )


# ==========================================
# MAIN EXECUTION
# ==========================================

def main():
    creds_path = project_root / 'creds' / 'service_account_key.json'
    client = utils_gsheet_handler.authenticate_gsheet(creds_path)

    df_raw = utils_gsheet_handler.extract_data(client, SPREADSHEET_ID, INPUT_TAB_NAME)
    if df_raw is None or df_raw.empty: return

    df_filtered = df_raw[df_raw['category'].isin(TARGET_CATEGORIES)].copy()
    all_results = []
    today = pd.Timestamp.now().strftime('%Y-%m-%d')

    print(f"Analyzing {len(df_filtered)} tickers...")
    for idx, row in df_filtered.iterrows():
        ticker, cat = row['ticker'], row['category']
        print(f"[{idx + 1}] {ticker}...", end=" ")

        df_ohlc = utils_technical_indicators.get_ohlc_data(ticker, today, LOOKBACK, MULTIPLIER, TIMESPAN)

        if df_ohlc is not None and not df_ohlc.empty:
            data = calculate_aligned_returns(df_ohlc, ticker, cat, REF_DAYS)
            all_results.extend(data)
            print("Done.")
        else:
            print("Failed.")
        time.sleep(12)

    if all_results:
        generate_visual_report(pd.DataFrame(all_results))


if __name__ == "__main__":
    main()