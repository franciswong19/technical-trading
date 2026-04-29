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

from .types import (TierResult, TickerAnalysis, HorizontalRange, VolumeAnalysis)
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
    """Analyze a single ticker for whichever tiers have data in ohlc_data.

    Follows the execution flow in Appendix A of the methodology:
    Phase 1: Analyze each tier independently
    Phase 2: Multi-tier interaction
    Phase 3: Assemble final output

    Args:
        ticker: Stock symbol (e.g. 'QQQ').
        ohlc_data: Dict with keys for the requested tiers ('short_term',
                   'medium_term', 'long_term'), each containing a DataFrame
                   with columns: t, open, high, low, close, volume.
                   Only keys present in the dict are analysed; omitted tiers
                   are silently skipped (not counted as errors).
        config: Optional config override (defaults to CONFIG).

    Returns:
        TickerAnalysis with results for each provided tier.
    """
    cfg = config or CONFIG
    results = {}
    errors = []

    # Phase 1: Analyze each tier that was provided
    requested_tiers = [t for t in ['short_term', 'medium_term', 'long_term']
                       if t in ohlc_data]
    all_tiers = ['short_term', 'medium_term', 'long_term']

    for tier_name in all_tiers:
        df = ohlc_data.get(tier_name)
        if df is None:
            # Tier not requested — build empty placeholder silently
            results[tier_name] = _empty_tier_result(tier_name, cfg)
            continue
        try:
            if df.empty:
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

    # Phase 3: Assemble output — status reflects only requested tiers
    n_requested = len(requested_tiers)
    n_errors = sum(1 for e in errors
                   if any(e.startswith(t) for t in requested_tiers))
    status = 'SUCCESS'
    if n_requested == 0 or n_errors == n_requested:
        status = 'FAILED'
    elif n_errors > 0:
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

            # v2 §9.1: range volume bias + trend
            if 'volume' in ohlc_df.columns:
                from .volume import analyze_range_volume
                bias, vtrend = analyze_range_volume(ohlc_df, upper, lower)
                result.horizontal_range.range_volume_bias = bias
                result.horizontal_range.range_volume_trend = vtrend

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

    # v2 §14: assemble aggregated VolumeAnalysis from collected fields
    result.volume_analysis = _build_volume_analysis(result)

    return result


def _build_volume_analysis(tier_result: TierResult) -> VolumeAnalysis:
    """Assemble the aggregated VolumeAnalysis output block (v2 §14)."""
    va = VolumeAnalysis()

    if tier_result.regime is not None:
        va.volume_confirmed = tier_result.regime.volume_confirmed
        va.volume_trend_ratio = tier_result.regime.volume_trend_ratio

        if va.volume_confirmed is True:
            va.volume_trend_interpretation = (
                f'Volume expanding on with-trend legs '
                f'(ratio={va.volume_trend_ratio:.2f}) — healthy'
            )
        elif va.volume_confirmed is False:
            va.volume_trend_interpretation = (
                f'Volume expanding AGAINST trend '
                f'(ratio={va.volume_trend_ratio:.2f}) — bearish divergence'
            )
        else:
            va.volume_trend_interpretation = 'Inconclusive or no trend'

    if tier_result.trend_channel is not None:
        va.pivot_volume_divergence = tier_result.trend_channel.volume_divergence
        va.obv_analysis = tier_result.trend_channel.obv_analysis

        # Anchor point volumes from the primary line
        primary = tier_result.trend_channel.primary_line
        if primary and primary.anchor_points:
            # Match anchors to source pivots to get volume context
            primary_pivots = (tier_result.pivot_lows
                              if tier_result.regime
                              and tier_result.regime.trend_direction == 'UPTREND'
                              else tier_result.pivot_highs)
            for anchor in primary.anchor_points:
                source_pivot = next(
                    (p for p in primary_pivots if p.bar_index == anchor.bar_index),
                    None,
                )
                volume_ratio = source_pivot.volume_ratio if source_pivot else 0.0
                va.anchor_point_volumes.append({
                    'date': str(anchor.timestamp),
                    'price': float(anchor.price),
                    'volume_ratio': float(volume_ratio),
                    'type': 'pivot_low' if (
                        tier_result.regime
                        and tier_result.regime.trend_direction == 'UPTREND'
                    ) else 'pivot_high',
                })

    return va


def _inverse_transform_channel(channel, inverse_fn):
    """Convert channel anchor prices back from log space to price space.

    Keep slope and intercept in log space: the trendline is fitted to log-transformed
    data, so price_at() returns log prices which the chart then inverts for display.
    Only anchor prices (used for display) are inverted.
    """
    for line in [channel.primary_line, channel.opposite_line]:
        if line is None:
            continue
        # Keep intercept in log space so price_at() returns consistent log values
        # Don't convert: line.intercept stays in log space to match slope
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
