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
INPUT_TAB_NAME = "etf_shortlist"

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
# VISUALIZATION
# ==========================================

def generate_visual_report(df_all):
    # Standardize categories and fetch unique reference days
    categories = [c for c in TARGET_CATEGORIES if c in df_all['category'].unique()]
    ref_days = sorted(df_all['ref_day'].unique())
    report_date = datetime.now().strftime('%Y-%m-%d')

    # 1. Fixed Color Map for Ticker Consistency
    all_tickers = sorted(df_all['ticker'].unique())
    colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']
    color_map = {ticker: colors[i % len(colors)] for i, ticker in enumerate(all_tickers)}

    cat_summary = {
        'General Market': ", ".join(sorted(df_all[df_all['category'] == 'General ETF']['ticker'].unique())),
        'Sectors': ", ".join(sorted(df_all[df_all['category'] == 'Sector ETF']['ticker'].unique())),
        'Sub-sectors': ", ".join(sorted(df_all[df_all['category'] == 'Sub-sector ETF']['ticker'].unique())),
        'Commodities': ", ".join(sorted(df_all[df_all['category'] == 'Commodities']['ticker'].unique()))
    }
    
    sections_html = ""
    for rd in ref_days:
        for cat in categories:
            display_cat = cat.replace("General ETF", "General Market ETFs")\
                             .replace("Sector ETF", "Sector ETFs")\
                             .replace("Sub-sector ETF", "Sub-sector ETFs")\
                             .replace("Commodities", "Commodity ETFs")
            
            mask = (df_all['ref_day'] == rd) & (df_all['category'] == cat)
            sub_df = df_all[mask]
            tickers = sorted(sub_df['ticker'].unique())

            fig = go.Figure()
            latest_stats = []

            for tkr in tickers:
                tkr_df = sub_df[sub_df['ticker'] == tkr].sort_values('day_seq', ascending=False)
                perf_val = tkr_df[tkr_df['day_seq'] == 0]['pct_diff'].values[0] if not tkr_df.empty else 0
                latest_stats.append({'Ticker': tkr, 'Perf': f"{perf_val:+.2%}"})

                fig.add_trace(go.Scatter(
                    x=tkr_df['day_seq'], y=tkr_df['pct_diff'],
                    mode='lines', name=tkr,
                    line=dict(width=2, color=color_map[tkr]),
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
                <tr><td colspan="2" class="title-cell">{display_cat} (since {rd} trading days ago)</td></tr>
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
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 0; padding: 40px; color: #333; line-height: 1.8; }}
            
            /* Navy Blue Ribbon Headers */
            .header-ribbon {{ background-color: #002366; color: white; padding: 30px 40px; margin: -40px -40px 30px -40px; position: relative; }}
            .header-ribbon h1 {{ margin: 0; font-size: 28px; font-weight: bold; }}
            .header-ribbon h2 {{ margin: 5px 0 0 0; font-size: 20px; border: none; padding: 0; opacity: 0.9; color: white; }}
            .confidential-tag {{ position: absolute; top: 15px; right: 20px; font-size: 11px; font-weight: bold; color: rgba(255,255,255,0.8); }}
            
            .notice-box {{ border-left: 4px solid #002366; padding: 15px 20px; background: #f0f4fa; margin-bottom: 30px; font-size: 14px; line-height: 1.5; }}
            .legal-footer {{ margin-top: 60px; padding-top: 20px; border-top: 1px solid #ddd; font-size: 11px; color: #666; line-height: 1.5; text-align: justify; }}
            
            .category-block {{ border-collapse: collapse; width: 1100px; table-layout: fixed; border: none; }}
            .title-cell {{ font-size: 20px; font-weight: bold; color: #2c3e50; padding-bottom: 10px; white-space: nowrap; border: none; }}
            .table-cell {{ width: 350px; vertical-align: top; border: none; padding-top: 5px; }}
            .chart-cell {{ width: 800px; vertical-align: top; border: none; }}
            .perf-table {{ width: 320px; border-collapse: collapse; font-size: 13px; line-height: 1.4; }}
            .perf-table th, .perf-table td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            .perf-table th {{ background: #f8f9fa; }}
            
            h2 {{ font-size: 22px; border-bottom: 2px solid #eee; padding-bottom: 5px; margin-top: 40px; }}
            p, ul {{ margin-bottom: 15px; }}
        </style>
    </head>
    <body>
        <div class="header-ribbon">
            <div class="confidential-tag">Private and Confidential. Not for circulation.</div>
            <h1>Macro-Technical Momentum (MTM) Trading</h1>
            <h2>ETF Trend Analysis {report_date}</h2>
        </div>

        <div class="notice-box">
            <strong>NOTICE TO RECIPIENT:</strong> This proprietary document is provided on a confidential basis for informational purposes only. The sender is not liable for any actions or financial decisions taken based on this data. 
            <br><br> <strong>Please refer to the LEGAL DISCLOSURE at the bottom of this article first before proceeding with the rest of the report.</strong> Reproduction or redistribution of this report in any form is strictly prohibited.
        </div>

        <h2>Report Description</h2>
        <p>This ETF Trend Analysis report shows the % performance of each ETF in last 5, 10, 20, 40, 65 trading days, excluding weekends and US market holidays, but including half trading days. The report is an important component of the MTM trading process (see more details in <a href="https://docs.google.com/spreadsheets/d/1zirkorAxJs5_y9oV-Q6e-3c4Kr-iO8UsfA3CQwQy6OE">GSheet</a>), and it highlights which ETFs are over or under performing and for how long.</p>
        <p>The ETFs are carefully curated based on the author's investment scope and focus. They are consolidated accordingly to each of the 4 groups, General Market, Sectors, Sub-sectors and Commodities, so that they can be compared against one another within each group.</p>
        <ul>
            <li><strong>General Market:</strong> {cat_summary['General Market']}</li>
            <li><strong>Sectors:</strong> {cat_summary['Sectors']}</li>
            <li><strong>Sub-sectors:</strong> {cat_summary['Sub-sectors']}</li>
            <li><strong>Commodities:</strong> {cat_summary['Commodities']}</li>
        </ul>
        <p>The report is generated every Tue-Sat afternoons (Singapore time).</p>
        <p>Data source: polygon.io</p>

        <h2>Data Visualisation</h2>
        {sections_html}

        <div class="legal-footer">
            <strong>I. Confidentiality and Non-Disclosure</strong><br>
            This report is strictly confidential. It is intended solely for the person or entity to whom it was originally addressed. The contents of this document may not be reproduced, redistributed, or circulated, in whole or in part, to any other person or published on any website or social media platform without the express written consent of the author. Any unauthorized use or disclosure of this information is strictly prohibited.
            <br><br>
            
            <strong>II. Not Financial Advice</strong><br>
            This report is provided for informational and educational purposes only and does not constitute a "buy" or "sell" recommendation, nor does it represent an offer to provide investment advisory services. The analysis contained herein is "top-down" and "macro-tactical" in nature and does not take into account the specific investment objectives, financial situation, or particular needs of any individual recipient. No part of this report should be construed as legal, tax, or investment advice.
            <br><br>
            
            <strong>III. Risk Disclosure</strong><br>
            Investing in securities—including ETFs and individual stocks—involves significant risk of loss. Market conditions can change rapidly based on Federal Reserve policy, economic data, and shifting sector momentum. Past performance is not indicative of future results. No representation or warranty, express or implied, is made as to the accuracy or completeness of the information contained herein, and the author shall not be held liable for any investment losses or damages resulting from the use of this data.
            <br><br>
            
            <strong>IV. Independent Verification</strong><br>
            Recipients are urged to conduct their own independent research and consult with a licensed financial professional or investment advisor before making any financial decisions. The author may hold positions in the securities or sectors mentioned in this report and is under no obligation to update this information as market conditions evolve.
            <br><br>
            
            <em>Data provided via Polygon.io. Generated in Singapore Standard Time (SGT).</em>
        </div>
    </body>
    </html>
    """

    # --- File Saving & Email ---
    output_folder = current_dir / "mg_picks_trend_analysis"
    output_folder.mkdir(parents=True, exist_ok=True)
    today_str = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
    file_path = output_folder / f"data_viz_mg_picks_etf_trend_analysis_daily_{today_str}.html"

    with open(str(file_path), "w", encoding="utf-8") as f:
        f.write(html_template)
    
    RECIPIENTS = utils_email_handler.get_receiver_emails()
    if RECIPIENTS:
        utils_email_handler.send_report_email(
            receiver_list=RECIPIENTS,
            file_path=str(file_path),
            sender_email="francis.lunkai.wong@gmail.com",
            subject=f"ETF trend analysis report {report_date}",
            body=f"Hello. Please find the attached report on ETF trend analysis, generated on {report_date}."
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