"""
utils_trendline_engine

Deterministic trendline analysis engine implementing the methodology
from agent_docs/trendline_methodology.md.

Public API:
    analyze_ticker(ticker, ohlc_data, config) -> TickerAnalysis

The engine is data-source agnostic — it accepts pre-fetched DataFrames
with columns: t, open, high, low, close, volume.
"""

import numpy as np
import pandas as pd
from datetime import datetime

from .types import (TierResult, TickerAnalysis, HorizontalRange)
from .config import CONFIG, get_tier_param, get_tier_def, get_lookback_bars
from .scale import determine_scale
from .pivots import identify_pivots
from .regime import classify_regime
from .channels import build_channel
from .breakout import check_break
from .support_resistance import build_sr_zones
from .fan_principle import detect_fan_lines
from .multi_tier import analyze_tier_interaction


def analyze_ticker(ticker: str, ohlc_data: dict[str, pd.DataFrame],
                   config: dict = None) -> TickerAnalysis:
    """Analyze a single ticker across all three tiers.

    Follows the execution flow in Appendix A of the methodology:
    Phase 1: Analyze each tier independently
    Phase 2: Multi-tier interaction
    Phase 3: Assemble final output

    Args:
        ticker: Stock symbol (e.g. 'QQQ').
        ohlc_data: Dict with keys 'short_term', 'medium_term', 'long_term',
                   each containing a DataFrame with columns: t, open, high, low, close, volume.
        config: Optional config override (defaults to CONFIG).

    Returns:
        TickerAnalysis with all three tier results and multi-tier interaction.
    """
    cfg = config or CONFIG
    results = {}
    errors = []

    # Phase 1: Analyze each tier independently
    for tier_name in ['short_term', 'medium_term', 'long_term']:
        try:
            df = ohlc_data.get(tier_name)
            if df is None or df.empty:
                results[tier_name] = _empty_tier_result(tier_name, cfg)
                errors.append(f"{tier_name}: no data available")
                continue

            results[tier_name] = _analyze_tier(df, tier_name, cfg)
        except Exception as e:
            results[tier_name] = _empty_tier_result(tier_name, cfg)
            errors.append(f"{tier_name}: {str(e)}")

    # Phase 2: Multi-tier interaction
    interaction = analyze_tier_interaction(
        results.get('short_term'),
        results.get('medium_term'),
        results.get('long_term'),
    )

    # Phase 3: Assemble output
    status = 'SUCCESS'
    if len(errors) == 3:
        status = 'FAILED'
    elif errors:
        status = 'PARTIAL'

    return TickerAnalysis(
        ticker=ticker,
        analysis_timestamp=datetime.now(),
        short_term=results.get('short_term'),
        medium_term=results.get('medium_term'),
        long_term=results.get('long_term'),
        multi_tier_interaction=interaction,
        status=status,
        errors=errors,
    )


def _analyze_tier(ohlc_df: pd.DataFrame, tier: str,
                  config: dict) -> TierResult:
    """Analyze a single tier: pivots → regime → channel/S/R → fan."""
    tier_def = get_tier_def(tier, config)
    lookback_bars = get_lookback_bars(tier, config)

    highs = ohlc_df['high'].values
    lows = ohlc_df['low'].values

    # Step 1: Determine scale (Section 2)
    scale_mode, transform, inverse = determine_scale(
        highs, lows, config['LOG_SCALE_THRESHOLD']
    )

    # Apply transform if log scale
    working_df = ohlc_df.copy()
    if scale_mode == 'log':
        for col in ['open', 'high', 'low', 'close']:
            working_df[col] = transform(working_df[col])

    # Step 2: Identify pivots (Section 3)
    pivot_highs, pivot_lows, atr_value = identify_pivots(working_df, tier, config)

    # Create tier result
    result = TierResult(
        tier=tier,
        interval=tier_def['interval'],
        lookback_trading_days=tier_def['lookback_trading_days'],
        lookback_bars=len(ohlc_df),
        scale_mode=scale_mode,
        atr_14=atr_value,
        pivot_highs=pivot_highs,
        pivot_lows=pivot_lows,
    )

    # Check for insufficient data
    if len(pivot_highs) + len(pivot_lows) < 4:
        from .types import RegimeResult
        result.regime = RegimeResult(state='OTHERS', sub_type='INSUFFICIENT_DATA')
        return result

    # Step 3: Classify regime (Section 4)
    regime = classify_regime(pivot_highs, pivot_lows, working_df, atr_value,
                            tier, config)
    result.regime = regime

    # Step 4: Build channel or handle other regimes
    if regime.state == 'TREND' and regime.trend_start_bar_index is not None:
        channel, trailing_fit = build_channel(
            pivot_highs, pivot_lows, working_df, atr_value,
            regime.trend_direction, regime.trend_start_bar_index,
            tier, config
        )

        # Convert back from log scale if needed
        if scale_mode == 'log' and channel is not None:
            _inverse_transform_channel(channel, inverse)

        result.trend_channel = channel
        result.trailing_fit = trailing_fit

        # Fan principle (Section 12)
        if channel and channel.primary_line:
            primary_pivots = pivot_lows if regime.trend_direction == 'UPTREND' else pivot_highs
            fan_lines, fan_exhausted = detect_fan_lines(
                channel.primary_line, working_df, primary_pivots,
                regime.trend_direction, config
            )
            result.fan_lines = fan_lines
            result.fan_exhausted = fan_exhausted

    elif regime.state == 'BREAK':
        break_info = check_break(pivot_highs, pivot_lows, working_df, atr_value,
                                 tier, config)
        result.break_info = break_info

    elif regime.state == 'OTHERS' and regime.sub_type == 'SIDEWAYS':
        # Draw horizontal range
        if pivot_highs and pivot_lows:
            upper = max(p.price for p in pivot_highs)
            lower = min(p.price for p in pivot_lows)
            if scale_mode == 'log':
                upper = inverse(upper)
                lower = inverse(lower)
            mid = (upper + lower) / 2
            width_pct = (upper - lower) / mid * 100 if mid > 0 else 0
            result.horizontal_range = HorizontalRange(
                upper_boundary=upper, lower_boundary=lower, width_pct=width_pct
            )

    # Step 5: S/R zones (always, regardless of regime)
    sr_zones = build_sr_zones(pivot_highs, pivot_lows, working_df, atr_value,
                              tier, config)
    # Convert S/R back from log scale
    if scale_mode == 'log':
        for zone in sr_zones:
            zone.midpoint = float(inverse(zone.midpoint))
            zone.upper = float(inverse(zone.upper))
            zone.lower = float(inverse(zone.lower))

    result.support_resistance_zones = sr_zones

    # Convert pivots back from log scale for charting
    if scale_mode == 'log':
        for p in result.pivot_highs:
            p.price = float(inverse(p.price))
        for p in result.pivot_lows:
            p.price = float(inverse(p.price))

    return result


def _inverse_transform_channel(channel, inverse_fn):
    """Convert channel prices back from log space to price space."""
    for line in [channel.primary_line, channel.opposite_line]:
        if line is None:
            continue
        line.intercept = float(inverse_fn(line.intercept))
        # Slope in log space → need to recompute in price space
        # For charting, we keep the line equation in log space and convert at render time
        for anchor in line.anchor_points:
            anchor.price = float(inverse_fn(anchor.price))

    if channel.current_price_position:
        channel.current_price_position.price = float(
            inverse_fn(channel.current_price_position.price)
        )
    if channel.projected_values:
        channel.projected_values.primary_line_price = float(
            inverse_fn(channel.projected_values.primary_line_price)
        )
        channel.projected_values.opposite_line_price = float(
            inverse_fn(channel.projected_values.opposite_line_price)
        )


def _empty_tier_result(tier: str, config: dict) -> TierResult:
    """Create an empty tier result for when no data is available."""
    tier_def = get_tier_def(tier, config)
    from .types import RegimeResult
    return TierResult(
        tier=tier,
        interval=tier_def['interval'],
        lookback_trading_days=tier_def['lookback_trading_days'],
        lookback_bars=0,
        regime=RegimeResult(state='OTHERS', sub_type='INSUFFICIENT_DATA'),
    )
