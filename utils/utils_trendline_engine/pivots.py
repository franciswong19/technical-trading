"""
pivots.py

Pivot point identification following Grimes's three-order hierarchy.
Implements Section 3 of the trendline methodology:
- First/second/third-order pivot detection
- ATR-based swing confirmation
- Zigzag alternation enforcement
- Pivot spacing constraints (bar separation, intervening swing, no overlap)
"""

import numpy as np
import pandas as pd
from datetime import datetime

from .types import PivotPoint
from .config import get_tier_param, get_lookback_bars, CONFIG


def compute_atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
                period: int = 14) -> np.ndarray:
    """Compute Average True Range (ATR) using pure numpy.

    Args:
        highs: Array of high prices.
        lows: Array of low prices.
        closes: Array of close prices.
        period: ATR lookback period (default 14).

    Returns:
        Array of ATR values (same length as input, NaN-padded at start).
    """
    n = len(highs)
    if n < 2:
        return np.full(n, np.nan)

    # True Range = max(H-L, |H-prev_C|, |L-prev_C|)
    tr = np.empty(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        tr[i] = max(hl, hc, lc)

    # Wilder's smoothed ATR
    atr = np.full(n, np.nan)
    if n < period:
        return atr

    atr[period - 1] = np.mean(tr[:period])
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

    return atr


def find_first_order_pivots(highs: np.ndarray, lows: np.ndarray,
                            timestamps: np.ndarray, window_n: int,
                            strict: bool = True) -> list[PivotPoint]:
    """Find first-order pivot highs and lows.

    A first-order pivot high at index i requires:
        high[i] > max(high[i-N:i]) AND high[i] > max(high[i+1:i+N+1])
    (strict inequality; non-strict >= on one side if strict=False)

    Args:
        highs: Array of high prices.
        lows: Array of low prices.
        timestamps: Array of timestamps.
        window_n: Number of bars on each side to check.
        strict: If True, use strict inequality. If False, use >= on left side.

    Returns:
        List of PivotPoint objects, sorted by bar_index.
    """
    n = len(highs)
    pivots = []

    for i in range(window_n, n - window_n):
        # Check pivot high
        left_max_h = np.max(highs[i - window_n:i])
        right_max_h = np.max(highs[i + 1:i + window_n + 1])

        if strict:
            is_pivot_high = highs[i] > left_max_h and highs[i] > right_max_h
        else:
            is_pivot_high = highs[i] >= left_max_h and highs[i] > right_max_h

        if is_pivot_high:
            pivots.append(PivotPoint(
                bar_index=i,
                timestamp=timestamps[i],
                price=highs[i],
                pivot_type='HIGH',
                order=1,
            ))

        # Check pivot low
        left_min_l = np.min(lows[i - window_n:i])
        right_min_l = np.min(lows[i + 1:i + window_n + 1])

        if strict:
            is_pivot_low = lows[i] < left_min_l and lows[i] < right_min_l
        else:
            is_pivot_low = lows[i] <= left_min_l and lows[i] < right_min_l

        if is_pivot_low:
            pivots.append(PivotPoint(
                bar_index=i,
                timestamp=timestamps[i],
                price=lows[i],
                pivot_type='LOW',
                order=1,
            ))

    pivots.sort(key=lambda p: p.bar_index)
    return pivots


def find_higher_order_pivots(first_order: list[PivotPoint],
                             target_order: int = 2) -> list[PivotPoint]:
    """Find second-order and third-order pivots from first-order pivots.

    Second-order pivot high: a first-order pivot high preceded AND followed
    by a lower first-order pivot high.
    Second-order pivot low: a first-order pivot low preceded AND followed
    by a higher first-order pivot low.

    Third-order: same logic applied to second-order pivots.

    Args:
        first_order: List of first-order PivotPoint objects.
        target_order: Maximum order to compute (2 or 3).

    Returns:
        List of all pivots up to target_order, with order field set.
    """
    # Separate by type
    all_pivots = list(first_order)

    for order in range(2, target_order + 1):
        prev_order = order - 1
        highs = [p for p in all_pivots if p.pivot_type == 'HIGH' and p.order == prev_order]
        lows = [p for p in all_pivots if p.pivot_type == 'LOW' and p.order == prev_order]

        # Find higher-order highs
        for i in range(1, len(highs) - 1):
            if highs[i].price > highs[i - 1].price and highs[i].price > highs[i + 1].price:
                all_pivots.append(PivotPoint(
                    bar_index=highs[i].bar_index,
                    timestamp=highs[i].timestamp,
                    price=highs[i].price,
                    pivot_type='HIGH',
                    order=order,
                ))

        # Find higher-order lows
        for i in range(1, len(lows) - 1):
            if lows[i].price < lows[i - 1].price and lows[i].price < lows[i + 1].price:
                all_pivots.append(PivotPoint(
                    bar_index=lows[i].bar_index,
                    timestamp=lows[i].timestamp,
                    price=lows[i].price,
                    pivot_type='LOW',
                    order=order,
                ))

    return all_pivots


def filter_by_atr_swing(pivots: list[PivotPoint], atr_value: float,
                        multiplier: float) -> list[PivotPoint]:
    """Filter pivots by ATR-based swing confirmation.

    A pivot is confirmed only if the swing from the preceding opposite pivot
    is >= multiplier × ATR.

    Args:
        pivots: List of PivotPoint objects, sorted by bar_index.
        atr_value: Current ATR(14) value.
        multiplier: ATR_SWING_MULTIPLIER for the tier.

    Returns:
        Filtered list of confirmed pivots.
    """
    if not pivots or np.isnan(atr_value):
        return pivots

    threshold = multiplier * atr_value
    confirmed = []
    last_opposite = None  # Track last opposite-type pivot for swing measurement

    for pivot in sorted(pivots, key=lambda p: p.bar_index):
        if last_opposite is None:
            # First pivot — keep it, we can't measure swing yet
            confirmed.append(pivot)
            last_opposite = pivot
            continue

        if pivot.pivot_type != last_opposite.pivot_type:
            # Opposite type — measure swing
            swing = abs(pivot.price - last_opposite.price)
            if swing >= threshold:
                confirmed.append(pivot)
                last_opposite = pivot
            # If swing too small, skip this pivot but keep tracking
        else:
            # Same type — keep (will be resolved by alternation later)
            confirmed.append(pivot)

    return confirmed


def enforce_zigzag_alternation(pivots: list[PivotPoint]) -> list[PivotPoint]:
    """Enforce strict alternation between pivot highs and lows.

    If two consecutive pivot highs occur, keep only the higher one.
    If two consecutive pivot lows occur, keep only the lower one.

    Args:
        pivots: List of PivotPoint objects, sorted by bar_index.

    Returns:
        List with strict high-low alternation enforced.
    """
    if len(pivots) < 2:
        return pivots

    sorted_pivots = sorted(pivots, key=lambda p: p.bar_index)
    result = [sorted_pivots[0]]

    for pivot in sorted_pivots[1:]:
        if pivot.pivot_type == result[-1].pivot_type:
            # Same type — keep the more extreme one
            if pivot.pivot_type == 'HIGH':
                if pivot.price > result[-1].price:
                    result[-1] = pivot
            else:
                if pivot.price < result[-1].price:
                    result[-1] = pivot
        else:
            result.append(pivot)

    return result


def enforce_spacing_constraints(pivots: list[PivotPoint], highs: np.ndarray,
                                lows: np.ndarray, atr_value: float,
                                tier: str, config: dict = None) -> list[PivotPoint]:
    """Enforce pivot spacing constraints (Section 3.6).

    Three conditions between adjacent same-side anchor pivots:
    A) Minimum bar separation
    B) Minimum intervening swing (open water)
    C) No overlap (open water visual test)

    Args:
        pivots: List of PivotPoint objects with alternation already enforced.
        highs: Full array of high prices.
        lows: Full array of low prices.
        atr_value: Current ATR(14) value.
        tier: Tier name for parameter lookup.
        config: Optional config override.

    Returns:
        List of pivots satisfying all spacing constraints.
    """
    cfg = config or CONFIG
    min_sep = get_tier_param('MIN_PIVOT_SEPARATION', tier, cfg)
    swing_atr_mult = get_tier_param('SWING_ATR_MULTIPLE', tier, cfg)
    swing_threshold = swing_atr_mult * atr_value

    # Process highs and lows separately for spacing
    pivot_highs = [p for p in pivots if p.pivot_type == 'HIGH']
    pivot_lows = [p for p in pivots if p.pivot_type == 'LOW']

    filtered_highs = _filter_same_side_spacing(pivot_highs, highs, lows, min_sep,
                                                swing_threshold, 'HIGH')
    filtered_lows = _filter_same_side_spacing(pivot_lows, highs, lows, min_sep,
                                               swing_threshold, 'LOW')

    # Merge and re-sort
    result = filtered_highs + filtered_lows
    result.sort(key=lambda p: p.bar_index)
    return result


def _filter_same_side_spacing(same_side_pivots: list[PivotPoint],
                               highs: np.ndarray, lows: np.ndarray,
                               min_sep: int, swing_threshold: float,
                               pivot_type: str) -> list[PivotPoint]:
    """Filter same-side pivots for spacing constraints A, B, C."""
    if len(same_side_pivots) < 2:
        return same_side_pivots

    result = [same_side_pivots[0]]

    for pivot in same_side_pivots[1:]:
        prev = result[-1]
        passes = True

        # Condition A: minimum bar separation
        if pivot.bar_index - prev.bar_index < min_sep:
            passes = False

        # Condition B: minimum intervening swing
        if passes:
            start = prev.bar_index + 1
            end = pivot.bar_index
            if start < end:
                if pivot_type == 'LOW':
                    # For two lows, the rally between them must be large enough
                    max_high_between = np.max(highs[start:end])
                    swing = max_high_between - max(prev.price, pivot.price)
                else:
                    # For two highs, the dip between them must be large enough
                    min_low_between = np.min(lows[start:end])
                    swing = min(prev.price, pivot.price) - min_low_between
                if swing < swing_threshold:
                    passes = False

        # Condition C: no overlap (open water visual test)
        if passes and start < end:
            if pivot_type == 'LOW':
                # Highest price near each pivot low must be below the intervening high
                max_high_between = np.max(highs[start:end])
                # Check 3-bar neighborhood of each pivot
                prev_hood_start = max(0, prev.bar_index - 1)
                prev_hood_end = min(len(highs), prev.bar_index + 2)
                pivot_hood_start = max(0, pivot.bar_index - 1)
                pivot_hood_end = min(len(highs), pivot.bar_index + 2)
                prev_hood_max = np.max(highs[prev_hood_start:prev_hood_end])
                pivot_hood_max = np.max(highs[pivot_hood_start:pivot_hood_end])
                if prev_hood_max >= max_high_between or pivot_hood_max >= max_high_between:
                    passes = False
            else:
                # For two highs, lowest near each must be above the intervening low
                min_low_between = np.min(lows[start:end])
                prev_hood_start = max(0, prev.bar_index - 1)
                prev_hood_end = min(len(lows), prev.bar_index + 2)
                pivot_hood_start = max(0, pivot.bar_index - 1)
                pivot_hood_end = min(len(lows), pivot.bar_index + 2)
                prev_hood_min = np.min(lows[prev_hood_start:prev_hood_end])
                pivot_hood_min = np.min(lows[pivot_hood_start:pivot_hood_end])
                if prev_hood_min <= min_low_between or pivot_hood_min <= min_low_between:
                    passes = False

        if passes:
            result.append(pivot)
        else:
            # Keep the more extreme pivot
            if pivot_type == 'HIGH' and pivot.price > prev.price:
                result[-1] = pivot
            elif pivot_type == 'LOW' and pivot.price < prev.price:
                result[-1] = pivot

    return result


def identify_pivots(ohlc_df: pd.DataFrame, tier: str,
                    config: dict = None) -> tuple[list[PivotPoint], list[PivotPoint], float]:
    """Full pivot identification pipeline for a single tier.

    Runs: first-order detection → higher-order detection → ATR filter →
    zigzag alternation → spacing constraints.

    Includes retry-with-relaxed-ATR if too few pivots found (Section 15.1).

    Args:
        ohlc_df: DataFrame with columns: t, open, high, low, close, volume.
        tier: 'short_term', 'medium_term', or 'long_term'.
        config: Optional config override.

    Returns:
        Tuple of (pivot_highs, pivot_lows, atr_value).
        pivot_highs: list of confirmed HIGH pivots.
        pivot_lows: list of confirmed LOW pivots.
        atr_value: median ATR(14) value over the lookback.
    """
    cfg = config or CONFIG

    highs = ohlc_df['high'].values
    lows = ohlc_df['low'].values
    closes = ohlc_df['close'].values
    timestamps = ohlc_df['t'].values

    window_n = get_tier_param('PIVOT_WINDOW', tier, cfg)
    atr_mult = get_tier_param('ATR_SWING_MULTIPLIER', tier, cfg)
    min_primary = cfg['MIN_PIVOTS_PRIMARY']

    # Compute ATR
    atr_array = compute_atr(highs, lows, closes, cfg['ATR_PERIOD'])
    valid_atr = atr_array[~np.isnan(atr_array)]
    atr_value = float(np.median(valid_atr)) if len(valid_atr) > 0 else 0.0

    # Step 1: Find first-order pivots (strict)
    first_order = find_first_order_pivots(highs, lows, timestamps, window_n, strict=True)

    # Fallback to non-strict if no pivots found
    if len(first_order) < 4:
        first_order = find_first_order_pivots(highs, lows, timestamps, window_n, strict=False)

    # Step 2: Find higher-order pivots
    all_pivots = find_higher_order_pivots(first_order, target_order=3)

    # Use the highest available order for analysis, falling back to lower orders
    for use_order in [3, 2, 1]:
        candidate_pivots = [p for p in all_pivots if p.order >= use_order]
        # Also include first-order as the base set
        if use_order > 1:
            # Use higher-order pivots for regime classification,
            # but keep all first-order for channel construction
            candidate_pivots = [p for p in all_pivots if p.order == 1]
        break

    # Use first-order pivots for the main pipeline
    working_pivots = [p for p in all_pivots if p.order == 1]

    # Step 3: ATR swing filter
    filtered = filter_by_atr_swing(working_pivots, atr_value, atr_mult)

    # Retry with relaxed ATR if too few pivots (Section 15.1)
    if len([p for p in filtered if p.pivot_type == 'HIGH']) + \
       len([p for p in filtered if p.pivot_type == 'LOW']) < 4:
        relaxed_mult = max(0.0, atr_mult - 0.25)
        filtered = filter_by_atr_swing(working_pivots, atr_value, relaxed_mult)

    # Step 4: Zigzag alternation
    alternated = enforce_zigzag_alternation(filtered)

    # Step 5: Spacing constraints
    spaced = enforce_spacing_constraints(alternated, highs, lows, atr_value, tier, cfg)

    # Separate into highs and lows
    pivot_highs = [p for p in spaced if p.pivot_type == 'HIGH']
    pivot_lows = [p for p in spaced if p.pivot_type == 'LOW']

    return pivot_highs, pivot_lows, atr_value


def get_second_order_pivots(all_pivots: list[PivotPoint]) -> tuple[list[PivotPoint], list[PivotPoint]]:
    """Extract second-order (or higher) pivots for regime classification.

    Falls back to first-order if insufficient second-order pivots exist.

    Returns:
        Tuple of (second_order_highs, second_order_lows).
    """
    second_highs = [p for p in all_pivots if p.pivot_type == 'HIGH' and p.order >= 2]
    second_lows = [p for p in all_pivots if p.pivot_type == 'LOW' and p.order >= 2]

    # Fall back to first-order if insufficient
    if len(second_highs) < 2:
        second_highs = [p for p in all_pivots if p.pivot_type == 'HIGH' and p.order >= 1]
    if len(second_lows) < 2:
        second_lows = [p for p in all_pivots if p.pivot_type == 'LOW' and p.order >= 1]

    second_highs.sort(key=lambda p: p.bar_index)
    second_lows.sort(key=lambda p: p.bar_index)

    return second_highs, second_lows
