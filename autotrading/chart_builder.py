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
    """Build a single Plotly OHLC chart with overlaid analysis."""
    fig = go.Figure()
    tier_color = TIER_COLORS[tier_name]
    tier_label = tier_name.replace('_', ' ').title()

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
                           tier_color, tier_label, next_td, tier_result)

    # 3. Fan lines
    if tier_result.fan_lines:
        for i, fan_line in enumerate(tier_result.fan_lines):
            _add_trendline_trace(fig, fan_line, ohlc_df, tier_color,
                                f'{tier_label} Fan {i+1}', next_td,
                                dash='dash')

    # 4. Horizontal range (SIDEWAYS regime)
    if tier_result.horizontal_range is not None:
        hr = tier_result.horizontal_range
        _add_horizontal_range(fig, hr.upper_boundary, hr.lower_boundary,
                              ohlc_df, tier_color)

    # 5. S/R zones
    for zone in tier_result.support_resistance_zones:
        _add_sr_zone_trace(fig, zone, ohlc_df, next_td)

    # 6. Pivot markers
    _add_pivot_markers(fig, tier_result.pivot_highs, tier_result.pivot_lows)

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
        margin=dict(t=40, b=40, l=60, r=20),
        template='plotly_white',
        hovermode='x unified',
        xaxis=dict(
            title=tier_result.interval + ' bars',
            rangeslider_visible=False,
        ),
        yaxis=dict(
            title='Price',
            side='right',
        ),
        legend=dict(
            orientation='h',
            yanchor='bottom',
            y=1.02,
            xanchor='right',
            x=1,
            font=dict(size=9),
        ),
    )

    return fig


def _add_channel_traces(fig, channel: Channel, ohlc_df, color, label,
                        next_td, tier_result: TierResult):
    """Add primary and opposite channel lines to the figure."""
    # Determine if there's a breakout (trendlines become dotted after)
    break_bar = None
    if tier_result.break_info and tier_result.break_info.break_bar_index is not None:
        break_bar = tier_result.break_info.break_bar_index

    for line, line_label in [(channel.primary_line, f'{label} Primary'),
                              (channel.opposite_line, f'{label} Opposite')]:
        if line is None:
            continue
        _add_trendline_trace(fig, line, ohlc_df, color, line_label,
                            next_td, dash='solid', break_bar=break_bar)


def _add_trendline_trace(fig, line: Trendline, ohlc_df, color, name,
                         next_td, dash='solid', break_bar=None):
    """Add a trendline trace, extending to the next trading day.

    If break_bar is set, line becomes dotted from that bar onwards.
    """
    if not line.anchor_points:
        return

    first_bar = line.anchor_points[0].bar_index
    last_bar = len(ohlc_df) - 1
    timestamps = ohlc_df['t'].values

    if break_bar is not None and first_bar <= break_bar <= last_bar:
        # Solid portion: first_bar to break_bar
        solid_ts = []
        solid_prices = []
        for i in range(first_bar, min(break_bar + 1, len(timestamps))):
            solid_ts.append(timestamps[i])
            solid_prices.append(line.price_at(i))

        fig.add_trace(go.Scatter(
            x=solid_ts, y=solid_prices,
            mode='lines', name=name,
            line=dict(color=color, width=1.5, dash='solid'),
            showlegend=True,
        ))

        # Dotted portion: break_bar to extension
        dotted_ts = []
        dotted_prices = []
        for i in range(break_bar, len(timestamps)):
            dotted_ts.append(timestamps[i])
            dotted_prices.append(line.price_at(i))
        # Extend to next trading day
        if next_td is not None:
            ext_bar = last_bar + 1
            dotted_ts.append(next_td)
            dotted_prices.append(line.price_at(ext_bar))

        fig.add_trace(go.Scatter(
            x=dotted_ts, y=dotted_prices,
            mode='lines', name=f'{name} (broken)',
            line=dict(color=color, width=1.5, dash='dot'),
            showlegend=False,
        ))
    else:
        # No breakout — draw full line solid + extension
        ts_list = []
        price_list = []
        for i in range(first_bar, len(timestamps)):
            ts_list.append(timestamps[i])
            price_list.append(line.price_at(i))
        # Extend to next trading day
        if next_td is not None:
            ext_bar = last_bar + 1
            ts_list.append(next_td)
            price_list.append(line.price_at(ext_bar))

        fig.add_trace(go.Scatter(
            x=ts_list, y=price_list,
            mode='lines', name=name,
            line=dict(color=color, width=1.5, dash=dash),
            showlegend=True,
        ))


def _add_sr_zone_trace(fig, zone: SRZone, ohlc_df, next_td):
    """Add a semi-transparent S/R zone band."""
    if ohlc_df.empty:
        return

    timestamps = list(ohlc_df['t'].values)
    if next_td is not None:
        timestamps.append(next_td)

    is_support = zone.zone_type == 'SUPPORT'
    fill_color = SUPPORT_FILL_COLOR if is_support else RESISTANCE_FILL_COLOR
    line_color = SUPPORT_LINE_COLOR if is_support else RESISTANCE_LINE_COLOR
    label = f"S {zone.midpoint:.2f}" if is_support else f"R {zone.midpoint:.2f}"

    # Upper boundary
    fig.add_trace(go.Scatter(
        x=timestamps,
        y=[zone.upper] * len(timestamps),
        mode='lines',
        line=dict(color=line_color, width=0.5, dash='dot'),
        showlegend=False,
        hoverinfo='skip',
    ))

    # Lower boundary with fill to upper
    fig.add_trace(go.Scatter(
        x=timestamps,
        y=[zone.lower] * len(timestamps),
        mode='lines',
        fill='tonexty',
        fillcolor=fill_color,
        line=dict(color=line_color, width=0.5, dash='dot'),
        name=label,
        showlegend=True,
    ))


def _add_horizontal_range(fig, upper, lower, ohlc_df, color):
    """Add horizontal range boundaries for SIDEWAYS regime."""
    timestamps = list(ohlc_df['t'].values)
    fig.add_trace(go.Scatter(
        x=timestamps, y=[upper] * len(timestamps),
        mode='lines', name='Range High',
        line=dict(color=color, width=1, dash='dash'),
        showlegend=True,
    ))
    fig.add_trace(go.Scatter(
        x=timestamps, y=[lower] * len(timestamps),
        mode='lines', name='Range Low',
        line=dict(color=color, width=1, dash='dash'),
        showlegend=True,
    ))


def _add_pivot_markers(fig, pivot_highs, pivot_lows):
    """Add small triangle markers at pivot points."""
    if pivot_highs:
        fig.add_trace(go.Scatter(
            x=[p.timestamp for p in pivot_highs],
            y=[p.price for p in pivot_highs],
            mode='markers',
            marker=dict(symbol='triangle-down', size=6, color='red', opacity=0.6),
            name='Pivot High',
            showlegend=False,
            hovertemplate='Pivot High<br>Price: %{y:.2f}<extra></extra>',
        ))

    if pivot_lows:
        fig.add_trace(go.Scatter(
            x=[p.timestamp for p in pivot_lows],
            y=[p.price for p in pivot_lows],
            mode='markers',
            marker=dict(symbol='triangle-up', size=6, color='green', opacity=0.6),
            name='Pivot Low',
            showlegend=False,
            hovertemplate='Pivot Low<br>Price: %{y:.2f}<extra></extra>',
        ))


def _get_next_trading_day_ts(ohlc_df, reference_date):
    """Get the next trading day timestamp for line extension."""
    try:
        if reference_date:
            ref = pd.Timestamp(reference_date)
        elif not ohlc_df.empty:
            ref = pd.Timestamp(ohlc_df['t'].values[-1])
        else:
            return None

        cal = mcal.get_calendar('NYSE')
        end = ref + timedelta(days=10)
        schedule = cal.schedule(start_date=ref + timedelta(days=1), end_date=end)
        if not schedule.empty:
            return schedule.index[0]
    except Exception:
        pass
    return None
