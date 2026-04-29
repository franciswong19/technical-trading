"""
run_trendline_report.py

Main entry point for generating the trendline & S/R analysis report.
Reads parameters from Google Sheet, fetches data from IB Gateway,
runs the analysis engine, and generates an HTML report with email delivery.

Usage:
    python -m autotrading.run_trendline_report
"""

import sys
import time
import argparse
from pathlib import Path
from datetime import datetime, timedelta

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from utils import utils_gsheet_handler
from utils.utils_ibkr_portfolio import connect_ibkr, disconnect_ibkr
from utils.utils_trendline_engine import analyze_ticker
from autotrading.data_fetcher import fetch_all_tiers, resolve_reference_date
from autotrading.chart_builder import build_ticker_charts, build_explanation_charts
from autotrading.report_generator import build_html_report, save_report, email_report
from autotrading.explanation_generator import generate_explanation, save_explanation

# ==========================================
# CONFIGURATION
# ==========================================
SPREADSHEET_ID = '13RfATfhAOOp_RCr3a_clcwXjrVdaFRib0_JTxUj729Q'
INPUT_TAB_NAME = 'autotrading_params'

# IB Gateway connection
IB_HOST = '127.0.0.1'
IB_PORT = 4001
IB_CLIENT_ID = 20       # Separate from trade executor range (10-19)

# Exchange defaults
DEFAULT_EXCHANGE = 'SMART'
DEFAULT_CURRENCY = 'USD'


def parse_params(df):
    """Parse tickers and reference_date from the GSheet DataFrame.

    Expected columns: ticker, reference_date (optional)

    Returns:
        Tuple of (tickers, reference_date).
    """
    if df is None or df.empty:
        raise ValueError("No data found in autotrading_params tab")

    tickers = []
    reference_date = ''

    # Extract tickers
    if 'ticker' in df.columns:
        tickers = [t.strip().upper() for t in df['ticker'].dropna().tolist()
                   if t.strip()]

    # Extract reference_date (use the first non-empty value)
    if 'reference_date' in df.columns:
        dates = df['reference_date'].dropna().tolist()
        if dates:
            ref = str(dates[0]).strip()
            if ref:
                reference_date = ref

    if not tickers:
        raise ValueError("No tickers found in autotrading_params tab")

    return tickers, reference_date


def main():
    parser = argparse.ArgumentParser(description='Trendline & S/R Analysis Report')
    parser.add_argument('--tickers', nargs='+', metavar='TICKER',
                        help='Override tickers (e.g. --tickers QQQ SPY)')
    parser.add_argument('--date', metavar='YYYY-MM-DD',
                        help='Override reference date (e.g. --date 2026-04-25)')
    args = parser.parse_args()

    print("=" * 60)
    print("TRENDLINE & S/R ANALYSIS REPORT GENERATOR")
    print("=" * 60)

    # Step 1: Read params (CLI overrides GSheet)
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers]
        reference_date = resolve_reference_date(args.date or '')
        print(f"\n[1/5] Using CLI params (skipping Google Sheet).")
    else:
        print("\n[1/5] Reading parameters from Google Sheet...")
        creds_path = project_root / 'creds' / 'service_account_key.json'
        client = utils_gsheet_handler.authenticate_gsheet(creds_path)
        df_params = utils_gsheet_handler.extract_data(client, SPREADSHEET_ID, INPUT_TAB_NAME)
        tickers, reference_date = parse_params(df_params)
        if args.date:
            reference_date = resolve_reference_date(args.date)
        else:
            reference_date = resolve_reference_date(reference_date)
    print(f"  Tickers: {', '.join(tickers)}")
    print(f"  Reference date: {reference_date}")

    # Step 2: Connect to IB Gateway
    print("\n[2/5] Connecting to IB Gateway...")
    ib = connect_ibkr(host=IB_HOST, port=IB_PORT, client_id=IB_CLIENT_ID)

    try:
        # Step 3: Fetch data and run analysis
        print(f"\n[3/5] Analyzing {len(tickers)} tickers...")
        all_results = []
        all_charts = {}

        for i, ticker in enumerate(tickers, 1):
            print(f"\n--- [{i}/{len(tickers)}] {ticker} ---")

            # Fetch 15-min data only
            ohlc_data = fetch_all_tiers(
                ib, ticker, reference_date,
                exchange=DEFAULT_EXCHANGE,
                currency=DEFAULT_CURRENCY,
                tiers=['short_term'],
            )

            # Run analysis
            print(f"  Analyzing...", end=' ')
            analysis = analyze_ticker(ticker, ohlc_data)
            print(f"Status: {analysis.status}")
            if analysis.errors:
                for err in analysis.errors:
                    print(f"    WARN: {err}")

            # Build main chart (short_term only)
            print(f"  Building chart...", end=' ')
            charts = build_ticker_charts(ohlc_data, analysis, reference_date)
            print("Done.")

            # Build progressive explanation charts + explanation document
            print(f"  Generating explanation...", end=' ')
            df_short = ohlc_data.get('short_term')
            if df_short is not None and not df_short.empty and analysis.short_term:
                prog_charts = build_explanation_charts(
                    df_short, analysis.short_term, ticker, reference_date
                )
                explanation_html = generate_explanation(
                    df=df_short,
                    tier_result=analysis.short_term,
                    ticker=ticker,
                    reference_date=reference_date,
                    progressive_charts=prog_charts,
                )
                save_explanation(explanation_html, ticker, reference_date)
            print("Done.")

            all_results.append(analysis)
            all_charts[ticker] = charts

            # Brief pause between tickers for IB pacing
            if i < len(tickers):
                time.sleep(2)

        # Step 4: Generate report
        print(f"\n[4/5] Generating HTML report...")
        html = build_html_report(all_results, all_charts, reference_date)
        file_path = save_report(html, reference_date)

        # Step 5: Email report
        print(f"\n[5/5] Sending email...")
        email_report(file_path, reference_date)

    finally:
        # Always disconnect
        disconnect_ibkr(ib)

    print("\n" + "=" * 60)
    print("REPORT GENERATION COMPLETE")
    print("=" * 60)


if __name__ == '__main__':
    main()
