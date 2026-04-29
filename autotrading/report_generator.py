"""
report_generator.py

HTML report assembly, file saving, and email distribution.
Follows the layout pattern of data_processing_mg_picks_etf_trend_analysis_daily.py.
"""

import sys
from pathlib import Path
from datetime import datetime

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from utils import utils_report_css
from utils import utils_disclaimer
from utils import utils_email_handler
from utils.utils_trendline_engine.types import TickerAnalysis


def build_html_report(all_results: list[TickerAnalysis],
                      all_charts: dict[str, dict[str, str]],
                      reference_date: str) -> str:
    """Assemble the full HTML report.

    Args:
        all_results: List of TickerAnalysis objects.
        all_charts: Dict of ticker -> dict of tier -> HTML fragment.
        reference_date: Reference date string for the report title.

    Returns:
        Complete HTML string.
    """
    report_date = reference_date or datetime.now().strftime('%Y-%m-%d')

    # Build ticker sections
    ticker_sections = ''
    for analysis in all_results:
        ticker = analysis.ticker
        charts = all_charts.get(ticker, {})
        ticker_sections += _build_ticker_section(analysis, charts)

    # Assemble full HTML
    html = f"""
    <html>
    <head>
        {utils_report_css.get_report_css()}
        <style>
            .tier-section {{
                margin-bottom: 30px;
            }}
            .ticker-header {{
                background-color: #002366;
                color: white;
                padding: 8px 15px;
                margin: 20px 0 10px 0;
                font-size: 18px;
                border-radius: 4px;
            }}
            .tier-title {{
                color: #333;
                font-size: 14px;
                margin: 10px 0 5px 0;
                padding: 5px 10px;
                background-color: #f0f0f0;
                border-left: 4px solid #002366;
            }}
            .summary-table {{
                border-collapse: collapse;
                margin: 10px 0;
                font-size: 12px;
            }}
            .summary-table td, .summary-table th {{
                border: 1px solid #ddd;
                padding: 4px 8px;
                text-align: left;
            }}
            .summary-table th {{
                background-color: #f5f5f5;
            }}
            .multi-tier-box {{
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 4px;
                padding: 10px 15px;
                margin: 15px 0;
                font-size: 13px;
            }}
            .status-success {{ color: #28a745; font-weight: bold; }}
            .status-partial {{ color: #ffc107; font-weight: bold; }}
            .status-failed {{ color: #dc3545; font-weight: bold; }}
        </style>
    </head>
    <body>
        {utils_report_css.get_header_ribbon_html(
            "Auto-Trading System",
            f"Trendline & S/R Analysis — {report_date}"
        )}
        {utils_disclaimer.get_notice_box_html()}

        <h2>Report Description</h2>
        <p>This report applies a deterministic trendline and support/resistance analysis
        on the <strong>15-minute timeframe</strong> (20 trading days, 520 bars) for each
        selected ticker. The methodology follows Grimes's pivot hierarchy,
        Edwards &amp; Magee's trendline construction, and Kirkpatrick &amp; Dahlquist's breakout
        confirmation framework, with Pring's volume divergence and Bulkowski's climax rules.</p>
        <p>
            <strong>S/R zones:</strong>
            <span style="color:#808080;">Support (gray)</span> |
            <span style="color:#FFA500;">Resistance (orange)</span>
        </p>
        <p>Dotted trendlines indicate a breakout has occurred from that point onwards.
        A separate per-ticker <em>explanation file</em> is saved alongside this report,
        walking through the step-by-step reasoning behind every trendline and signal.</p>
        <p>Data source: IB Gateway (regular trading hours)</p>

        <h2>Analysis</h2>
        {ticker_sections}

        {utils_disclaimer.get_legal_footer_html()}
    </body>
    </html>
    """
    return html


def _build_ticker_section(analysis: TickerAnalysis,
                          charts: dict[str, str]) -> str:
    """Build the HTML section for a single ticker."""
    status_class = {
        'SUCCESS': 'status-success',
        'PARTIAL': 'status-partial',
        'FAILED': 'status-failed',
    }.get(analysis.status, '')

    html = f'<div class="ticker-header">{analysis.ticker} '
    html += f'<span class="{status_class}">[{analysis.status}]</span></div>\n'

    # Per-tier charts and summaries (15-min only)
    for tier_name, tier_label in [('short_term', 'Short-Term (15-min)')]:
        tier_result = getattr(analysis, tier_name, None)
        chart_html = charts.get(tier_name, '<p>No chart available.</p>')

        html += f'<div class="tier-section">\n'
        html += f'<div class="tier-title">{tier_label}</div>\n'

        # Summary table
        if tier_result and tier_result.regime:
            html += _build_summary_table(tier_result)

        # Chart
        html += chart_html
        html += '\n</div>\n'

    # Errors
    if analysis.errors:
        html += '<div style="color:#dc3545;font-size:12px;margin:10px 0;">'
        html += '<strong>Errors:</strong> ' + '; '.join(analysis.errors)
        html += '</div>\n'

    html += '<hr style="margin:30px 0;">\n'
    return html


def _build_summary_table(tier_result) -> str:
    """Build a summary table for a tier result."""
    regime = tier_result.regime
    rows = [
        ('Regime', regime.state),
    ]

    if regime.trend_direction:
        rows.append(('Direction', regime.trend_direction))
    if regime.sub_type:
        rows.append(('Sub-type', regime.sub_type))
    if regime.r_squared > 0:
        rows.append(('R-squared', f'{regime.r_squared:.3f}'))

    if tier_result.trend_channel:
        ch = tier_result.trend_channel
        rows.append(('Channel', ch.channel_geometry))
        rows.append(('Width', f'{ch.width_pct:.1f}% ({ch.width_status})'))
        if ch.current_price_position:
            rows.append(('Position', f'{ch.current_price_position.zone} '
                        f'({ch.current_price_position.pct_within_channel:.0f}%)'))
        if ch.primary_line.steep_flag:
            rows.append(('Warning', 'STEEP TRENDLINE'))

    if tier_result.trailing_fit and tier_result.trailing_fit.recent_divergence:
        rows.append(('Divergence', 'Recent price diverging from trailing fit'))

    if tier_result.fan_exhausted:
        rows.append(('Fan', 'EXHAUSTED — reversal expected'))

    sr_count = len(tier_result.support_resistance_zones)
    if sr_count > 0:
        rows.append(('S/R Zones', str(sr_count)))

    # v2 volume analysis rows
    va = tier_result.volume_analysis
    if va is not None:
        if va.volume_confirmed is True:
            rows.append(('Volume Trend',
                         f'CONFIRMED ({va.volume_trend_ratio:.2f}x)'))
        elif va.volume_confirmed is False:
            rows.append(('Volume Trend',
                         f'<span style="color:#dc3545">DIVERGENT '
                         f'({va.volume_trend_ratio:.2f}x)</span>'))

        pvd = va.pivot_volume_divergence
        if pvd and pvd.divergence_warning != 'NONE':
            color = '#dc3545' if pvd.divergence_warning == 'SIGNIFICANT' else '#ffc107'
            rows.append(('Volume Divergence',
                         f'<span style="color:{color}">{pvd.divergence_warning} '
                         f'({pvd.divergence_count} consecutive)</span>'))

        obv = va.obv_analysis
        if obv:
            obv_text = obv.obv_confirmation or '—'
            if obv.joint_break == 'CONFIRMED':
                rows.append(('OBV',
                             f'<span style="color:#dc3545">JOINT BREAK CONFIRMED</span>'))
            elif obv.joint_break == 'OBV_LEADING':
                rows.append(('OBV',
                             f'<span style="color:#ffc107">OBV LEADING (early warning)</span>'))
            elif obv_text:
                color = '#28a745' if obv_text == 'CONFIRMED' else '#dc3545'
                rows.append(('OBV',
                             f'<span style="color:{color}">{obv_text} '
                             f'({obv.obv_slope_direction})</span>'))

    if tier_result.horizontal_range is not None:
        hr = tier_result.horizontal_range
        if hr.range_volume_bias != 'NEUTRAL' or hr.range_volume_trend != 'FLAT':
            rows.append(('Range Volume',
                         f'{hr.range_volume_bias} bias, {hr.range_volume_trend}'))

    if (tier_result.break_info is not None
            and tier_result.break_info.volume_climax_caution):
        rows.append(('Volume Climax',
                     '<span style="color:#ffc107">CAUTION (>3x avg vol)</span>'))

    row_html = ''.join(f'<tr><th>{k}</th><td>{v}</td></tr>' for k, v in rows)
    return f'<table class="summary-table">{row_html}</table>\n'


def save_report(html_content: str, reference_date: str) -> Path:
    """Save the HTML report to the autotrading/reports/ folder.

    Returns:
        Path to the saved file.
    """
    output_folder = Path(__file__).resolve().parent / 'reports'
    output_folder.mkdir(parents=True, exist_ok=True)

    date_str = reference_date.replace('-', '') if reference_date else \
               datetime.now().strftime('%Y%m%d')
    file_path = output_folder / f'trendline_report_{date_str}.html'

    with open(str(file_path), 'w', encoding='utf-8') as f:
        f.write(html_content)

    print(f"Report saved to: {file_path}")
    return file_path


def email_report(file_path: Path, reference_date: str):
    """Email the report using the existing email utility."""
    recipients = utils_email_handler.get_receiver_emails()
    if not recipients:
        print("No email recipients configured. Skipping email.")
        return

    report_date = reference_date or datetime.now().strftime('%Y-%m-%d')

    utils_email_handler.send_report_email(
        receiver_list=recipients,
        file_path=str(file_path),
        sender_email='francis.lunkai.wong@gmail.com',
        subject=f'Trendline & S/R Analysis Report {report_date}',
        body=(f'Hello. Please find the attached trendline and support/resistance '
              f'analysis report, generated on {report_date}.'),
    )
