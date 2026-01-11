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
from utils import utils_disclaimer
from utils import utils_report_css

# ==========================================
# USER CONFIGURATION
# ==========================================
SPREADSHEET_ID = "13RfATfhAOOp_RCr3a_clcwXjrVdaFRib0_JTxUj729Q"
INPUT_TAB_NAME = "stock_shortlist"

LOOKBACK = 150
MULTIPLIER = 1
TIMESPAN = "day"

TARGET_CATEGORIES = ["Semicon", "Software", "Comm Svc", "Healthcare", "Finance", 
                    "Consumer Discretionary", "Alternative Energy", "Alternative Investments"]

REF_DAYS = [5, 10, 20, 40, 65]


# ==========================================
# CALCULATION LOGIC
# ==========================================

def calculate_aligned_returns(df_ohlc, ticker, category, is_etf, ref_days):
    df = df_ohlc.sort_values("t", ascending=False).head(100).copy()
    df['day_seq'] = range(len(df))

    results = []
    for ref_val in ref_days:
        if ref_val >= len(df): continue
        ref_price = df.iloc[ref_val]['close']
        path_df = df[df['day_seq'] <= ref_val].copy()

        for _, row in path_df.iterrows():
            results.append({
                'ticker': ticker,
                'category': category,
                'is_etf': is_etf,
                'ref_day': ref_val,
                'day_seq': row['day_seq'],
                'pct_diff': (row['close'] / ref_price) - 1
            })
    return results


# ==========================================
# VISUALIZATION
# ==========================================

def generate_visual_report(df_all):
    categories = [c for c in TARGET_CATEGORIES if c in df_all['category'].unique()]
    ref_days = sorted(df_all['ref_day'].unique())
    report_date = datetime.now().strftime('%Y-%m-%d')

    # Color mapping for tickers (Standard tickers get colors, ETFs are black)
    all_tickers = sorted(df_all['ticker'].unique())
    colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']
    color_map = {t: colors[i % len(colors)] for i, t in enumerate(all_tickers)}

    # Build dynamic documentation lists
    stock_list_html = ""
    etf_list_html = ""
    for cat in TARGET_CATEGORIES:
        cat_df = df_all[df_all['category'] == cat]
        stocks = sorted(cat_df[cat_df['is_etf'] != 1]['ticker'].unique())
        etfs = sorted(cat_df[cat_df['is_etf'] == 1]['ticker'].unique())
        
        stock_list_html += f"<li><strong>{cat}:</strong> {', '.join(stocks)}</li>"
        if etfs:
            etf_list_html += f"<li><strong>{cat}:</strong> {', '.join(etfs)}</li>"

    sections_html = ""
    for rd in ref_days:
        for cat in categories:
            mask = (df_all['ref_day'] == rd) & (df_all['category'] == cat)
            sub_df = df_all[mask]
            tickers = sorted(sub_df['ticker'].unique())

            fig = go.Figure()
            latest_stats = []

            for tkr in tickers:
                tkr_df = sub_df[sub_df['ticker'] == tkr].sort_values('day_seq', ascending=False)
                is_etf_flag = tkr_df['is_etf'].iloc[0]
                perf_val = tkr_df[tkr_df['day_seq'] == 0]['pct_diff'].values[0] if not tkr_df.empty else 0
                latest_stats.append({'Ticker': tkr, 'Perf': f"{perf_val:+.2%}"})

                # Formatting: Black for ETFs, Color for stocks
                line_color = 'black' if is_etf_flag == 1 else color_map[tkr]
                line_width = 3 if is_etf_flag == 1 else 2

                fig.add_trace(go.Scatter(
                    x=tkr_df['day_seq'], y=tkr_df['pct_diff'],
                    mode='lines', name=tkr,
                    line=dict(width=line_width, color=line_color),
                    showlegend=False,
                    hovertemplate=f"<b>{tkr}</b><br>Day: %{{x}}<br>Return: %{{y:.2%}}<extra></extra>"
                ))

            # Applied requested wide dimensions
            fig.update_layout(
                height=450, width=800, margin=dict(t=10, b=40, l=0, r=0),
                template="plotly_white", hovermode="closest",
                hoverlabel=dict(font_size=12, font_family="Arial", font_color="white"),
                xaxis=dict(autorange="reversed", title="Trading days ago", showgrid=True),
                yaxis=dict(tickformat=".1%", title="% performance", showgrid=True)
            )
            
            chart_html = fig.to_html(full_html=False, include_plotlyjs='cdn' if sections_html == "" else False)
            table_rows = "".join([f"<tr><td>{s['Ticker']}</td><td>{s['Perf']}</td></tr>" for s in latest_stats])

            sections_html += f"""
            <table class="category-block">
                <tr><td colspan="2" class="title-cell">{cat} (since {rd} trading days ago)</td></tr>
                <tr>
                    <td class="table-cell">
                        <table class="perf-table">
                            <thead><tr><th>Ticker</th><th>% performance</th></tr></thead>
                            <tbody>{table_rows}</tbody>
                        </table>
                    </td>
                    <td class="chart-cell">{chart_html}</td>
                </tr>
            </table>
            <div style="height: 40px;"></div>
            """

    html_template = f"""
    <html>
    <head>{utils_report_css.get_report_css()}</head>
    <body>
        {utils_report_css.get_header_ribbon_html("Macro-Technical Momentum (MTM) Trading", f"Stock Trend Analysis {report_date}")}
        {utils_disclaimer.get_notice_box_html()}

        <h2>Report Description</h2>
        <p>This Stock Trend Analysis report shows the % performance of each stock in last 5, 10, 20, 40, 65 trading days, excluding weekends and US market holidays, but including half trading days. The report is an important component of the MTM trading process (see more details in <a href="https://docs.google.com/spreadsheets/d/1zirkorAxJs5_y9oV-Q6e-3c4Kr-iO8UsfA3CQwQy6OE">GSheet</a>), and it highlights which stocks are over or under performing and for how long.</p>
        <p>The stocks are carefully curated based on the author's investment scope and focus. They are consolidated accordingly to each of the 8 groups so that they can be compared against one another within each group.</p>
        <ul>{stock_list_html}</ul>
        <p>The stocks are compared to the sectors' representative ETFs, some of which are leveraged.</p>
        <ul>{etf_list_html}</ul>
        <p>The report is generated every Tue-Sat afternoons (Singapore time).</p>
        <p>Data source: polygon.io</p>

        <h2>Data Visualisation</h2>
        {sections_html}
        {utils_disclaimer.get_legal_footer_html()}
    </body>
    </html>
    """
    
    output_folder = current_dir / "mg_picks_trend_analysis"
    output_folder.mkdir(parents=True, exist_ok=True)
    file_path = output_folder / f"stock_trend_analysis_daily_{datetime.now().strftime('%Y%m%d')}.html"
    with open(str(file_path), "w", encoding="utf-8") as f: f.write(html_template)
    
    RECIPIENTS = utils_email_handler.get_receiver_emails()
    if RECIPIENTS:
        utils_email_handler.send_report_email(
            receiver_list=RECIPIENTS,
            file_path=str(file_path),
            sender_email="francis.lunkai.wong@gmail.com",
            subject=f"Stock trend analysis report {report_date}",
            body=f"Hello. Please find the attached report on stock trend analysis, generated on {report_date}."
        )

# ==========================================
# MAIN EXECUTION
# ==========================================

def main():
    creds_path = project_root / 'creds' / 'service_account_key.json'
    client = utils_gsheet_handler.authenticate_gsheet(creds_path)
    df_raw = utils_gsheet_handler.extract_data(client, SPREADSHEET_ID, INPUT_TAB_NAME)
    if df_raw is None or df_raw.empty: return

    # Standardize is_etf column (handle strings vs numbers)
    df_raw['is_etf'] = pd.to_numeric(df_raw['is_etf'], errors='coerce').fillna(0)
    df_filtered = df_raw[df_raw['category'].isin(TARGET_CATEGORIES)].copy()
    all_results = []
    today = pd.Timestamp.now().strftime('%Y-%m-%d')

    for idx, row in df_filtered.iterrows():
        ticker, cat, is_etf = row['ticker'], row['category'], row['is_etf']
        df_ohlc = utils_technical_indicators.get_ohlc_data(ticker, today, LOOKBACK, MULTIPLIER, TIMESPAN)
        if df_ohlc is not None and not df_ohlc.empty:
            all_results.extend(calculate_aligned_returns(df_ohlc, ticker, cat, is_etf, REF_DAYS))
        time.sleep(12)

    if all_results: generate_visual_report(pd.DataFrame(all_results))

if __name__ == "__main__": main()