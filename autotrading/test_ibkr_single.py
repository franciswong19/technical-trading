"""
test_ibkr_single.py

Smoke test: fetch one ticker from IB Gateway, run analysis, generate HTML report.
Skips the Google Sheet step so you can isolate any IB-related issues.

Usage:
    python -m autotrading.test_ibkr_single QQQ
    python -m autotrading.test_ibkr_single AAPL 2026-04-25
"""

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from utils.utils_ibkr_portfolio import connect_ibkr, disconnect_ibkr
from utils.utils_trendline_engine import analyze_ticker
from autotrading.data_fetcher import fetch_all_tiers, resolve_reference_date
from autotrading.chart_builder import build_ticker_charts
from autotrading.report_generator import build_html_report, save_report

IB_HOST = '127.0.0.1'
IB_PORT = 4001
IB_CLIENT_ID = 21        # offset from main report (20)


def main():
    if len(sys.argv) < 2:
        print('Usage: python -m autotrading.test_ibkr_single TICKER [reference_date]')
        sys.exit(1)

    ticker = sys.argv[1].upper()
    reference_date = resolve_reference_date(sys.argv[2] if len(sys.argv) > 2 else '')

    print(f'Ticker: {ticker}')
    print(f'Reference date: {reference_date}')
    print()

    print(f'Connecting to IB Gateway at {IB_HOST}:{IB_PORT} (clientId={IB_CLIENT_ID})...')
    ib = connect_ibkr(host=IB_HOST, port=IB_PORT, client_id=IB_CLIENT_ID)

    try:
        print(f'\nFetching 3-tier data for {ticker}...')
        ohlc_data = fetch_all_tiers(ib, ticker, reference_date)

        print('\nRunning analysis...')
        result = analyze_ticker(ticker, ohlc_data)
        print(f'  Status: {result.status}')
        if result.errors:
            for err in result.errors:
                print(f'  WARN: {err}')

        for tier_name in ['short_term', 'medium_term', 'long_term']:
            tier = getattr(result, tier_name)
            print(f'\n  [{tier_name}]')
            print(f'    Bars:   {tier.lookback_bars}')
            print(f'    Regime: {tier.regime.state} {tier.regime.trend_direction or tier.regime.sub_type or ""}')
            if tier.trend_channel:
                print(f'    Channel: {tier.trend_channel.channel_geometry}, '
                      f'width={tier.trend_channel.width_pct:.1f}%')
            print(f'    Pivots: {len(tier.pivot_highs)} highs, {len(tier.pivot_lows)} lows')
            if tier.volume_analysis:
                va = tier.volume_analysis
                print(f'    Volume: confirmed={va.volume_confirmed}, '
                      f'ratio={va.volume_trend_ratio:.2f}')
                if va.obv_analysis:
                    print(f'    OBV:    {va.obv_analysis.obv_slope_direction}, '
                          f'{va.obv_analysis.obv_confirmation}, '
                          f'joint={va.obv_analysis.joint_break}')

        if result.multi_tier_interaction:
            mti = result.multi_tier_interaction
            print(f'\n  Multi-tier: {mti.confluence}, conviction={mti.conviction}')

        print('\nBuilding charts...')
        charts = build_ticker_charts(ohlc_data, result, reference_date)

        print('Generating report...')
        html = build_html_report([result], {ticker: charts}, reference_date)
        file_path = save_report(html, reference_date)

        print(f'\nSUCCESS — open this file in a browser to inspect:')
        print(f'  {file_path}')

    finally:
        disconnect_ibkr(ib)


if __name__ == '__main__':
    main()
