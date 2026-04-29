"""
chart_builder.py

Builds Plotly OHLC charts with trendlines, S/R zones, and fan lines overlaid.
One chart per tier per ticker.
"""

import sys
from pathlib import Path
from datetime import timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pandas_market_calendars as mcal

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from utils.utils_trendline_engine.types import (
    TickerAnalysis, TierResult, Trendline, SRZone, Channel
)

# Color constants
TIER_COLORS = {
    'short_term': '#d62728',   # red
    'medium_term': '#1f77b4',  # blue
    'long_term': '#2ca02c',    # green
}
SUPPORT_FILL_COLOR = 'rgba(128, 128, 128, 0.15)'
RESISTANCE_FILL_COLOR = 'rgba(255, 165, 0, 0.15)'
SUPPORT_LINE_COLOR = '#808080'
RESISTANCE_LINE_COLOR = '#FFA500'
CANDLE_UP_COLOR = '#26a69a'
CANDLE_DOWN_COLOR = '#ef5350'

# Volume annotation colors
DIVERGENCE_COLOR = '#dc3545'           # red flag for bearish divergence
CLIMAX_COLOR = '#FFC107'               # yellow flag for volume climax caution


def build_ticker_charts(ohlc_data: dict[str, pd.DataFrame],
                        analysis: TickerAnalysis,
                        reference_date: str = '') -> dict[str, str]:
    """Build charts for all three tiers of a ticker.

    Args:
        ohlc_data: Dict of tier -> OHLCV DataFrame.
        analysis: TickerAnalysis result.
        reference_date: For computing next trading day extension.

    Returns:
        Dict mapping tier name to Plotly HTML fragment string.
    """
    charts = {}
    first_chart = True

    for tier_name in ['short_term', 'medium_term', 'long_term']:
        tier_result = getattr(analysis, tier_name, None)
        df = ohlc_data.get(tier_name)

        if tier_result is None or df is None or df.empty:
            charts[tier_name] = '<p>No data available for this tier.</p>'
            continue

        fig = _build_tier_chart(df, tier_result, tier_name, analysis.ticker,
                                reference_date)

        # Include plotly.js only on first chart
        charts[tier_name] = fig.to_html(
            full_html=False,
            include_plotlyjs='cdn' if first_chart else False
        )
        first_chart = False

    return charts


def _build_tier_chart(ohlc_df: pd.DataFrame, tier_result: TierResult,
                      tier_name: str, ticker: str,
                      reference_date: str) -> go.Figure:
    """Build a Plotly chart with price candles + trendlines + S/R."""
    # Normalize timestamps to tz-naive US/Eastern so Plotly treats them as datetime
    ohlc_df = _normalize_timestamps(ohlc_df)

    tier_label = tier_name.replace('_', ' ').title()

    fig = go.Figure()

    # 1. OHLC candlestick bars
    fig.add_trace(go.Candlestick(
        x=ohlc_df['t'],
        open=ohlc_df['open'],
        high=ohlc_df['high'],
        low=ohlc_df['low'],
        close=ohlc_df['close'],
        increasing_line_color=CANDLE_UP_COLOR,
        decreasing_line_color=CANDLE_DOWN_COLOR,
        increasing_fillcolor=CANDLE_UP_COLOR,
        decreasing_fillcolor=CANDLE_DOWN_COLOR,
        name='OHLC',
        showlegend=False,
    ))

    # Compute next trading day for line extension
    next_td = _get_next_trading_day_ts(ohlc_df, reference_date)

    # 2. Trend channel lines
    if tier_result.trend_channel is not None:
        _add_channel_traces(fig, tier_result.trend_channel, ohlc_df,
                           tier_label, next_td, tier_result)

    # 3. Fan lines
    if tier_result.fan_lines:
        scale_mode = tier_result.scale_mode if tier_result else 'arithmetic'
        for i, fan_line in enumerate(tier_result.fan_lines):
            _add_trendline_trace(fig, fan_line, ohlc_df,
                                f'{tier_label} Fan {i+1}', next_td,
                                dash='dash', scale_mode=scale_mode)

    # 4. Horizontal range (SIDEWAYS regime)
    if tier_result.horizontal_range is not None:
        hr = tier_result.horizontal_range
        _add_horizontal_range(fig, hr.upper_boundary, hr.lower_boundary, ohlc_df)

    # 5. S/R zones
    for zone in tier_result.support_resistance_zones:
        _add_sr_zone_trace(fig, zone, ohlc_df, next_td)

    # 6. Pivot markers
    _add_pivot_markers(fig, tier_result.pivot_highs, tier_result.pivot_lows, ohlc_df)

    # 7. Volume divergence annotations at divergent pivots
    if tier_result.trend_channel is not None:
        _add_divergence_annotations(fig, tier_result, ohlc_df)

    # 8. Volume climax annotation at breakout bar
    if tier_result.break_info is not None:
        _add_climax_annotation(fig, tier_result.break_info, ohlc_df)

    # Layout
    regime_text = ''
    if tier_result.regime:
        regime_text = f" | {tier_result.regime.state}"
        if tier_result.regime.trend_direction:
            regime_text += f" ({tier_result.regime.trend_direction})"
        elif tier_result.regime.sub_type:
            regime_text += f" ({tier_result.regime.sub_type})"

    channel_text = ''
    if tier_result.trend_channel:
        channel_text = f" | {tier_result.trend_channel.channel_geometry}"

    fig.update_layout(
        title=f'{ticker} — {tier_label}{regime_text}{channel_text}',
        height=500,
        width=1000,
        margin=dict(t=50, b=40, l=60, r=20),
        template='plotly_white',
        hovermode='x unified',
        showlegend=False,
    )

    is_intraday = tier_result.interval in ('15min', '1hour')
    rangebreaks = _build_rangebreaks(ohlc_df, tier_result.interval)
    tickfmt = '%b %d\n%Y' if is_intraday else '%Y-%m-%d'

    fig.update_layout(
        xaxis=dict(
            rangeslider_visible=False,
            rangebreaks=rangebreaks,
            tickformat=tickfmt,
            tickangle=-45,
            tickfont=dict(size=9),
            title=tier_result.interval + ' bars',
        ),
        yaxis=dict(title='Price', side='right'),
    )

    return fig


def _add_trace(fig, trace, row=None):
    """Helper that adds a trace to the right subplot row (or single-row fig)."""
    if row is not None:
        fig.add_trace(trace, row=row, col=1)
    else:
        fig.add_trace(trace)


def _ts_ms(ts) -> np.datetime64:
    """Convert any datetime-like scalar to numpy datetime64[ms].

    Pivot/annotation timestamps come from the analysis engine, which ran on the
    original (non-normalized) ohlc data. Without this conversion, datetime64[ns]
    scalars in a Python list are misread by Plotly as millisecond integers,
    placing markers billions of years in the future.

    Must mirror _normalize_timestamps: convert to Eastern first, then strip tz,
    so pivot markers align with the OHLC bars on the chart x-axis.
    """
    pt = pd.Timestamp(ts)
    if pt.tzinfo is not None:
        pt = pt.tz_convert('America/New_York').tz_localize(None)
    return np.datetime64(pt, 'ms')


def _add_channel_traces(fig, channel: Channel, ohlc_df,
                        label, next_td, tier_result: TierResult, row=None):
    """Add primary and opposite channel lines to the figure."""
    break_bar = None
    if tier_result.break_info and tier_result.break_info.break_bar_index is not None:
        break_bar = tier_result.break_info.break_bar_index

    scale_mode = tier_result.scale_mode if tier_result else 'arithmetic'

    for line, line_label in [(channel.primary_line, f'{label} Primary'),
                              (channel.opposite_line, f'{label} Opposite')]:
        if line is None:
            continue
        _add_trendline_trace(fig, line, ohlc_df, line_label,
                            next_td, dash='solid', break_bar=break_bar, row=row,
                            scale_mode=scale_mode)


def _add_trendline_trace(fig, line: Trendline, ohlc_df, name,
                         next_td, dash='solid', break_bar=None, row=None,
                         scale_mode='arithmetic'):
    """Add a trendline trace (black), extending to the next trading day.

    If break_bar is set, line becomes dotted from that bar onwards.
    If scale_mode is 'log', prices are converted from log space to price space.
    """
    if not line.anchor_points:
        return

    inverse_fn = np.exp if scale_mode == 'log' else None

    def get_price(bar_idx):
        p = line.price_at(bar_idx)
        return inverse_fn(p) if inverse_fn is not None else p

    first_bar = line.anchor_points[0].bar_index
    last_bar = len(ohlc_df) - 1
    timestamps = ohlc_df['t'].values

    if break_bar is not None and first_bar <= break_bar <= last_bar:
        # Solid portion: first_bar to break_bar
        solid_ts = [timestamps[i] for i in range(first_bar, min(break_bar + 1, len(timestamps)))]
        solid_prices = [get_price(i) for i in range(first_bar, min(break_bar + 1, len(timestamps)))]

        _add_trace(fig, go.Scatter(
            x=solid_ts, y=solid_prices,
            mode='lines', name=name,
            line=dict(color='black', width=1.5, dash='solid'),
            showlegend=False,
        ), row=row)

        # Dotted portion: break_bar to extension
        dotted_ts = [timestamps[i] for i in range(break_bar, len(timestamps))]
        dotted_prices = [get_price(i) for i in range(break_bar, len(timestamps))]
        if next_td is not None:
            dotted_ts.append(next_td)
            dotted_prices.append(get_price(last_bar + 1))

        _add_trace(fig, go.Scatter(
            x=dotted_ts, y=dotted_prices,
            mode='lines', name=f'{name} (broken)',
            line=dict(color='black', width=1.5, dash='dot'),
            showlegend=False,
        ), row=row)
    else:
        # No breakout — draw full line solid + extension
        ts_list = [timestamps[i] for i in range(first_bar, len(timestamps))]
        price_list = [get_price(i) for i in range(first_bar, len(timestamps))]
        if next_td is not None:
            ts_list.append(next_td)
            price_list.append(get_price(last_bar + 1))

        _add_trace(fig, go.Scatter(
            x=ts_list, y=price_list,
            mode='lines', name=name,
            line=dict(color='black', width=1.5, dash=dash),
            showlegend=False,
        ), row=row)


def _add_sr_zone_trace(fig, zone: SRZone, ohlc_df, next_td, row=None):
    """Add a semi-transparent S/R zone band with score annotation."""
    if ohlc_df.empty:
        return

    timestamps = list(ohlc_df['t'].values)
    if next_td is not None:
        timestamps.append(next_td)

    is_support = zone.zone_type == 'SUPPORT'
    fill_color = SUPPORT_FILL_COLOR if is_support else RESISTANCE_FILL_COLOR
    line_color = SUPPORT_LINE_COLOR if is_support else RESISTANCE_LINE_COLOR

    # Upper boundary
    _add_trace(fig, go.Scatter(
        x=timestamps,
        y=[zone.upper] * len(timestamps),
        mode='lines',
        line=dict(color=line_color, width=0.5, dash='dot'),
        showlegend=False,
        hoverinfo='skip',
    ), row=row)

    # Lower boundary with fill to upper (no legend)
    _add_trace(fig, go.Scatter(
        x=timestamps,
        y=[zone.lower] * len(timestamps),
        mode='lines',
        fill='tonexty',
        fillcolor=fill_color,
        line=dict(color=line_color, width=0.5, dash='dot'),
        showlegend=False,
        hoverinfo='skip',
    ), row=row)

    # Score annotation just inside the left edge of the zone band
    if timestamps:
        first_x = timestamps[0]
        zone_y = zone.midpoint
        score_text = f"{zone.zone_score:.2f}"
        annotation_kwargs = dict(
            x=first_x,
            y=zone_y,
            text=score_text,
            showarrow=False,
            xanchor='left',
            yanchor='middle',
            font=dict(size=9, color=line_color),
            xshift=4,
        )
        if row is not None:
            annotation_kwargs['row'] = row
            annotation_kwargs['col'] = 1
        fig.add_annotation(**annotation_kwargs)


def _add_horizontal_range(fig, upper, lower, ohlc_df, row=None):
    """Add horizontal range boundaries for SIDEWAYS regime."""
    timestamps = list(ohlc_df['t'].values)
    for level in [upper, lower]:
        _add_trace(fig, go.Scatter(
            x=timestamps, y=[level] * len(timestamps),
            mode='lines',
            line=dict(color='black', width=1, dash='dash'),
            showlegend=False,
        ), row=row)


def _add_pivot_markers(fig, pivot_highs, pivot_lows, ohlc_df, row=None):
    """Add small triangle markers at pivot points.

    Uses bar_index to look up timestamps directly from the normalized ohlc_df,
    guaranteeing alignment with the candlestick x-axis regardless of how the
    pivot timestamps were stored.
    """
    timestamps = ohlc_df['t'].values
    n = len(timestamps)

    if pivot_highs:
        valid = [p for p in pivot_highs if p.bar_index < n]
        _add_trace(fig, go.Scatter(
            x=[timestamps[p.bar_index] for p in valid],
            y=[p.price for p in valid],
            mode='markers',
            marker=dict(symbol='triangle-down', size=6, color='black', opacity=0.7),
            name='Pivot High',
            showlegend=False,
            hovertemplate='Pivot High<br>Price: %{y:.2f}<extra></extra>',
        ), row=row)

    if pivot_lows:
        valid = [p for p in pivot_lows if p.bar_index < n]
        _add_trace(fig, go.Scatter(
            x=[timestamps[p.bar_index] for p in valid],
            y=[p.price for p in valid],
            mode='markers',
            marker=dict(symbol='triangle-up', size=6, color='black', opacity=0.7),
            name='Pivot Low',
            showlegend=False,
            hovertemplate='Pivot Low<br>Price: %{y:.2f}<extra></extra>',
        ), row=row)


# ============================================================================
# v2 volume annotations (Section 5.9, 5.10, 8.2.1)
# ============================================================================

def _add_divergence_annotations(fig, tier_result: TierResult, ohlc_df, row=None):
    """Add red flag annotations at divergent pivot anchors (Section 5.9)."""
    channel = tier_result.trend_channel
    if channel is None or channel.volume_divergence is None:
        return
    if channel.volume_divergence.divergence_warning == 'NONE':
        return

    direction = (tier_result.regime.trend_direction
                 if tier_result.regime else None)
    if direction == 'UPTREND':
        check_pivots = sorted(tier_result.pivot_highs, key=lambda p: p.bar_index)
    elif direction == 'DOWNTREND':
        check_pivots = sorted(tier_result.pivot_lows, key=lambda p: p.bar_index)
    else:
        return

    for detail in channel.volume_divergence.details:
        if not detail.get('divergence'):
            continue

        # Find the matching pivot to position the annotation
        match = next(
            (p for p in check_pivots
             if abs(p.price - detail['price']) < 0.01),
            None,
        )
        if match is None:
            continue

        # Offset so the flag sits above (uptrend high) or below (downtrend low)
        offset_dir = 1 if direction == 'UPTREND' else -1
        if match.bar_index >= len(ohlc_df):
            continue
        _add_trace(fig, go.Scatter(
            x=[ohlc_df['t'].values[match.bar_index]],
            y=[match.price * (1.0 + 0.005 * offset_dir)],
            mode='markers+text',
            marker=dict(symbol='triangle-down' if offset_dir > 0 else 'triangle-up',
                        size=12, color=DIVERGENCE_COLOR),
            text=['VD'],
            textposition='top center' if offset_dir > 0 else 'bottom center',
            textfont=dict(size=9, color=DIVERGENCE_COLOR),
            hovertemplate=(
                f"Volume Divergence<br>"
                f"Price: {detail['price']:.2f}<br>"
                f"Volume ratio: {detail['volume_ratio']:.2f}<br>"
                f"Prior pivot vol: {detail['prior_pivot_volume']:.0f}<extra></extra>"
            ),
            showlegend=False,
        ), row=row)


def _add_climax_annotation(fig, break_info, ohlc_df, row=None):
    """Add yellow CLIMAX annotation at breakout bar (Section 8.2.1)."""
    if not break_info.volume_climax_caution:
        return
    if break_info.break_bar_index is None:
        return
    if break_info.break_bar_index >= len(ohlc_df):
        return

    bar_ts = ohlc_df['t'].values[break_info.break_bar_index]
    bar_price = ohlc_df['high'].values[break_info.break_bar_index]
    _add_trace(fig, go.Scatter(
        x=[bar_ts],
        y=[bar_price * 1.01],
        mode='markers+text',
        marker=dict(symbol='star', size=14, color=CLIMAX_COLOR,
                    line=dict(color='black', width=1)),
        text=['CLIMAX'],
        textposition='top center',
        textfont=dict(size=10, color='#666'),
        hovertemplate=(
            "Volume Climax Caution<br>"
            "Heavy breakout volume (>3x avg)<br>"
            "Per Bulkowski: triples failure rates<extra></extra>"
        ),
        showlegend=False,
    ), row=row)



def build_explanation_charts(df: pd.DataFrame, tier_result: TierResult,
                             ticker: str,
                             reference_date: str = '') -> list[tuple[str, str]]:
    """Build 6 progressive charts for the explanation document.

    Each chart adds one more layer of overlay, letting the reader see exactly
    how each element is constructed on top of the raw price data.

    Returns:
        List of (stage_title, plotly_html_fragment) tuples.
        The first stage includes the Plotly CDN script; subsequent ones do not.
    """
    import copy

    def _strip(pivots=True, channel=True, sr=True, fan=True,
               vol_annot=True, primary_only=False):
        """Shallow-copy tier_result with selected features cleared."""
        tr = copy.copy(tier_result)

        if not pivots:
            tr.pivot_highs = []
            tr.pivot_lows = []

        if not channel:
            tr.trend_channel = None
            tr.trailing_fit = None
        else:
            if tr.trend_channel is not None:
                ch = copy.copy(tr.trend_channel)
                if primary_only:
                    ch.opposite_line = None
                if not vol_annot:
                    ch.volume_divergence = None
                    ch.obv_analysis = None
                tr.trend_channel = ch

        if not sr:
            tr.support_resistance_zones = []

        if not fan:
            tr.fan_lines = []
            tr.fan_exhausted = False

        if not vol_annot:
            tr.break_info = None

        return tr

    stages_config = [
        ('Stage 1: Raw OHLC (15-min bars)',
         _strip(pivots=False, channel=False, sr=False, fan=False, vol_annot=False)),
        ('Stage 2: + Pivot Points',
         _strip(pivots=True, channel=False, sr=False, fan=False, vol_annot=False)),
        ('Stage 3: + Primary Trendline',
         _strip(pivots=True, channel=True, sr=False, fan=False, vol_annot=False, primary_only=True)),
        ('Stage 4: + Full Channel',
         _strip(pivots=True, channel=True, sr=False, fan=False, vol_annot=False)),
        ('Stage 5: + Support & Resistance Zones',
         _strip(pivots=True, channel=True, sr=True, fan=False, vol_annot=False)),
        ('Stage 6: Final Chart (All Overlays)',
         tier_result),
    ]

    result = []
    for i, (title, tr) in enumerate(stages_config):
        if tr is None:
            result.append((title, '<p>No data for this stage.</p>'))
            continue
        fig = _build_tier_chart(df, tr, 'short_term', ticker, reference_date)
        fig.update_layout(title=f'{ticker} — {title}')
        include_js = 'cdn' if i == 0 else False
        html = fig.to_html(full_html=False, include_plotlyjs=include_js)
        result.append((title, html))

    return result


def _normalize_timestamps(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize timestamps for Plotly: strip timezone, then convert to datetime64[ms].

    Plotly's Candlestick handles a pandas Series of datetime64[ns] correctly, but
    Scatter traces receive individual numpy scalars from .values[i]. A datetime64[ns]
    scalar is treated as an integer (ms) by Plotly, placing lines billions of years
    in the future. datetime64[ms] scalars are interpreted correctly.
    """
    df = df.copy()
    col = df['t']
    if pd.api.types.is_datetime64_any_dtype(col):
        if hasattr(col.dtype, 'tz') and col.dtype.tz is not None:
            col = col.dt.tz_convert('America/New_York').dt.tz_localize(None)
        df['t'] = col.astype('datetime64[ms]')
    return df


def _build_rangebreaks(df: pd.DataFrame, interval: str) -> list:
    """Build Plotly rangebreaks: weekends, overnight hours, and NYSE holidays."""
    breaks = [dict(bounds=['sat', 'mon'])]
    if interval not in ('15min', '1hour'):
        return breaks

    breaks.append(dict(bounds=[16, 9.5], pattern='hour'))

    try:
        start = pd.Timestamp(df['t'].min()).normalize()
        end = pd.Timestamp(df['t'].max()).normalize()
        cal = mcal.get_calendar('NYSE')
        schedule = cal.schedule(
            start_date=start.strftime('%Y-%m-%d'),
            end_date=end.strftime('%Y-%m-%d'),
        )
        trading_days = set(schedule.index.strftime('%Y-%m-%d'))
        all_weekdays = pd.bdate_range(
            start.strftime('%Y-%m-%d'),
            end.strftime('%Y-%m-%d'),
        )
        holidays = [
            d.strftime('%Y-%m-%d')
            for d in all_weekdays
            if d.strftime('%Y-%m-%d') not in trading_days
        ]
        if holidays:
            # Only remove trading hours (09:30–16:00) on holidays.
            # The overnight rangebreak already covers 16:00–09:30 on each side,
            # so a full-day values break (default dvalue=86400000ms) double-removes
            # 17.5h of overnight on both sides, causing Plotly to over-compress the
            # surrounding weeks (the Apr 3 / Apr 6 visual collision).
            breaks.append(dict(
                values=[f'{h}T09:30:00' for h in holidays],
                dvalue=23400000,  # 6.5 trading hours in ms
            ))
    except Exception:
        pass

    return breaks


def _get_next_trading_day_ts(ohlc_df, reference_date):
    """Get the next trading day timestamp for line extension (tz-naive)."""
    try:
        if reference_date:
            ref = pd.Timestamp(reference_date)
        elif not ohlc_df.empty:
            ref = pd.Timestamp(ohlc_df['t'].iloc[-1])
        else:
            return None

        cal = mcal.get_calendar('NYSE')
        end = ref + timedelta(days=10)
        schedule = cal.schedule(start_date=ref + timedelta(days=1), end_date=end)
        if not schedule.empty:
            ts = schedule.index[0]
            if ts.tzinfo is not None:
                ts = ts.tz_localize(None)
            # Return as datetime64[ms] to match normalized ohlc timestamps
            return np.datetime64(ts, 'ms')
    except Exception:
        pass
    return None
