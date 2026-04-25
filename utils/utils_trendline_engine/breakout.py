"""
breakout.py

Breakout and breakdown detection and confirmation (Section 8 of methodology).
Uses multi-filter confirmation: close filter, ATR filter, volume filter.
Requires at least 2-of-3 filters to confirm a break.
"""

import numpy as np
import pandas as pd

from .types import PivotPoint, BreakInfo, SRZone
from .config import get_tier_param, CONFIG


def check_break(pivot_highs: list[PivotPoint], pivot_lows: list[PivotPoint],
                ohlc_df: pd.DataFrame, atr_value: float, tier: str,
                config: dict = None, prior_channel=None) -> BreakInfo | None:
    """Check if a breakout or breakdown is in progress (Section 4.3 / Section 8).

    Identifies a reference structure and confirms the break via multi-filter.

    Returns:
        BreakInfo if a break is detected (may or may not be confirmed), else None.
    """
    cfg = config or CONFIG

    if ohlc_df.empty or len(ohlc_df) < 10:
        return None

    closes = ohlc_df['close'].values
    highs = ohlc_df['high'].values
    lows = ohlc_df['low'].values
    volumes = ohlc_df['volume'].values
    current_price = closes[-1]

    # Step 1: Identify reference structure
    break_level, ref_structure, break_direction = _identify_reference_structure(
        pivot_highs, pivot_lows, current_price, atr_value, prior_channel
    )

    if break_level is None:
        return None

    # Step 2: Confirm the break
    return _confirm_break(
        closes, highs, lows, volumes, break_level, break_direction,
        ref_structure, atr_value, tier, cfg
    )


def _identify_reference_structure(pivot_highs, pivot_lows, current_price,
                                  atr_value, prior_channel):
    """Identify the reference structure for break detection (Section 8.1).

    Priority: prior trend channel > S/R zone > consolidation boundary.

    Returns:
        (break_level, reference_structure, break_direction) or (None, None, None).
    """
    # Priority 1: Prior trend channel
    if prior_channel is not None:
        upper = prior_channel.opposite_line.price_at(
            prior_channel.primary_line.anchor_points[-1].bar_index
        ) if prior_channel.opposite_line else None
        lower = prior_channel.primary_line.price_at(
            prior_channel.primary_line.anchor_points[-1].bar_index
        )

        if upper and current_price > upper + 0.5 * atr_value:
            return upper, 'PRIOR_CHANNEL', 'BREAKOUT'
        if current_price < lower - 0.5 * atr_value:
            return lower, 'PRIOR_CHANNEL', 'BREAKDOWN'

    # Priority 2/3: Use pivot extremes as consolidation boundaries
    if pivot_highs and pivot_lows:
        # Recent resistance = max of recent pivot highs
        recent_highs = sorted(pivot_highs, key=lambda p: p.bar_index)[-3:]
        recent_lows = sorted(pivot_lows, key=lambda p: p.bar_index)[-3:]

        resistance = max(p.price for p in recent_highs)
        support = min(p.price for p in recent_lows)

        if current_price > resistance + 0.5 * atr_value:
            return resistance, 'CONSOLIDATION', 'BREAKOUT'
        if current_price < support - 0.5 * atr_value:
            return support, 'CONSOLIDATION', 'BREAKDOWN'

    return None, None, None


def _confirm_break(closes, highs, lows, volumes, break_level, break_direction,
                   ref_structure, atr_value, tier, config):
    """Confirm a break using the multi-filter approach (Section 8.2).

    Requires at least 2 of 3 filters to pass.
    """
    atr_mult = config['ATR_BREAKOUT_MULTIPLIER']
    vol_mult = config['VOLUME_BREAKOUT_MULTIPLIER']
    confirm_bars = get_tier_param('BREAKOUT_CONFIRM_BARS', tier, config)

    n = len(closes)
    if n < 2:
        return None

    # Find the break bar (most recent bar that crossed the level)
    break_bar = None
    for i in range(n - 1, max(n - 20, 0) - 1, -1):
        if break_direction == 'BREAKOUT' and closes[i] > break_level:
            break_bar = i
            break
        elif break_direction == 'BREAKDOWN' and closes[i] < break_level:
            break_bar = i
            break

    if break_bar is None:
        return None

    # Filter 1: Close filter — bar closes beyond breakout level
    # For added confidence, check for 2 consecutive closes
    close_filter = False
    if break_bar > 0:
        if break_direction == 'BREAKOUT':
            close_filter = closes[break_bar] > break_level
            if break_bar + 1 < n:
                close_filter = close_filter and closes[break_bar + 1] > break_level
        else:
            close_filter = closes[break_bar] < break_level
            if break_bar + 1 < n:
                close_filter = close_filter and closes[break_bar + 1] < break_level

    # Filter 2: ATR filter — close beyond level by at least ATR_BREAKOUT_MULTIPLIER × ATR
    atr_filter = False
    if break_direction == 'BREAKOUT':
        atr_filter = closes[break_bar] > break_level + atr_mult * atr_value
    else:
        atr_filter = closes[break_bar] < break_level - atr_mult * atr_value

    # Filter 3: Volume filter — volume >= VOLUME_BREAKOUT_MULTIPLIER × avg_volume(20)
    volume_filter = False
    vol_start = max(0, break_bar - 20)
    avg_vol = np.mean(volumes[vol_start:break_bar]) if break_bar > vol_start else 0
    if avg_vol > 0:
        volume_filter = volumes[break_bar] >= vol_mult * avg_vol

    filters_passed = sum([close_filter, atr_filter, volume_filter])
    confirmed = filters_passed >= 2

    # Time confirmation: check if price stayed beyond level for confirm_bars
    if confirmed and break_bar + confirm_bars < n:
        # Check if price returned inside — false break
        for i in range(break_bar + 1, min(break_bar + confirm_bars + 1, n)):
            if break_direction == 'BREAKOUT' and closes[i] < break_level:
                confirmed = False
                break
            elif break_direction == 'BREAKDOWN' and closes[i] > break_level:
                confirmed = False
                break

    return BreakInfo(
        break_type=break_direction,
        break_level=break_level,
        reference_structure=ref_structure,
        confirmed=confirmed,
        filters_passed=filters_passed,
        close_filter=close_filter,
        atr_filter=atr_filter,
        volume_filter=volume_filter,
        break_bar_index=break_bar,
    )
