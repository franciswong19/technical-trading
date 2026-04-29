"""
volume.py

Volume-based analysis for the trendline engine (v2 methodology).
Implements Sections 3.7, 4.2 Step 5, 5.9, 5.10, 8.2.1, 9.1, and 11.2-11.3
of agent_docs/trendline_methodology v2.

All volume analytics are centralised here so other engine modules stay focused
on their core algorithm (pivots, regime, channels, breakout, S/R).
"""

import numpy as np
import pandas as pd

from .types import (PivotPoint, Trendline, TrendlineAnchor, Channel,
                    PivotVolumeDivergence, OBVAnalysis)
from .config import CONFIG


# ============================================================================
# Section 3.7 — Pivot volume recording
# ============================================================================

def compute_volume_ma(volumes: np.ndarray, period: int = 20) -> np.ndarray:
    """Compute simple moving average of volume.

    Returns an array same length as `volumes`, NaN for the first `period-1` bars.
    """
    n = len(volumes)
    ma = np.full(n, np.nan)
    if n < period:
        return ma
    cumsum = np.cumsum(np.insert(volumes, 0, 0))
    ma[period - 1:] = (cumsum[period:] - cumsum[:-period]) / period
    return ma


def record_pivot_volumes(pivots: list[PivotPoint], volumes: np.ndarray,
                         config: dict = None) -> list[PivotPoint]:
    """Populate volume context fields on each pivot (Section 3.7).

    Computes:
      - volume_at_pivot: 3-bar centred avg around the pivot bar
      - volume_ratio: pivot volume / 20-bar SMA volume at that bar
      - volume_change_vs_prior: % change vs prior same-side pivot

    Args:
        pivots: List of PivotPoint objects (sorted by bar_index).
        volumes: Full volume array for the tier.
        config: Optional config override.

    Returns:
        Same list, with volume fields populated in-place.
    """
    cfg = config or CONFIG
    neighborhood = cfg['PIVOT_VOLUME_NEIGHBORHOOD']
    ma_period = cfg['VOLUME_MA_PERIOD']
    n = len(volumes)

    if n == 0 or not pivots:
        return pivots

    volume_ma = compute_volume_ma(volumes, ma_period)

    # Pass 1: per-pivot volume_at_pivot and volume_ratio
    for pivot in pivots:
        idx = pivot.bar_index
        if idx < 0 or idx >= n:
            continue

        # 3-bar centred avg (bar i-1, i, i+1 by default)
        start = max(0, idx - (neighborhood - 1) // 2)
        end = min(n, idx + (neighborhood - 1) // 2 + 1)
        # If neighborhood is odd, this gives a centred window of size = neighborhood
        # (e.g. neighborhood=3 → bars [i-1, i, i+1])
        # For even neighborhood, bias toward earlier bars
        if neighborhood == 3:
            start = max(0, idx - 1)
            end = min(n, idx + 2)
        pivot.volume_at_pivot = float(np.mean(volumes[start:end]))

        # Ratio vs 20-bar SMA at this bar
        if idx < len(volume_ma) and not np.isnan(volume_ma[idx]) and volume_ma[idx] > 0:
            pivot.volume_ratio = pivot.volume_at_pivot / float(volume_ma[idx])
        else:
            pivot.volume_ratio = 1.0  # no baseline available — treat as neutral

    # Pass 2: per-pivot volume_change_vs_prior (same-side pivot)
    pivot_highs = sorted([p for p in pivots if p.pivot_type == 'HIGH'],
                         key=lambda p: p.bar_index)
    pivot_lows = sorted([p for p in pivots if p.pivot_type == 'LOW'],
                        key=lambda p: p.bar_index)

    for same_side in (pivot_highs, pivot_lows):
        for i in range(1, len(same_side)):
            prev = same_side[i - 1]
            curr = same_side[i]
            if prev.volume_at_pivot > 0:
                curr.volume_change_vs_prior = (
                    (curr.volume_at_pivot - prev.volume_at_pivot)
                    / prev.volume_at_pivot * 100.0
                )

    return pivots


# ============================================================================
# Section 4.2 Step 5 — Volume trend confirmation (non-blocking)
# ============================================================================

def check_volume_trend(pivot_highs: list[PivotPoint], pivot_lows: list[PivotPoint],
                       ohlc_df: pd.DataFrame, trend_direction: str,
                       config: dict = None
                       ) -> tuple[bool | None, float, str]:
    """Assess whether volume supports the trend (Section 4.2 Step 5).

    Splits bars into with-trend and counter-trend legs based on alternating
    pivots. Compares mean volume per leg type against threshold.

    Args:
        pivot_highs: Sorted pivot highs.
        pivot_lows: Sorted pivot lows.
        ohlc_df: OHLCV DataFrame.
        trend_direction: 'UPTREND' or 'DOWNTREND'.
        config: Optional config override.

    Returns:
        Tuple of (volume_confirmed, volume_trend_ratio, interpretation).
        volume_confirmed: True if healthy, False if divergent, None if inconclusive.
    """
    cfg = config or CONFIG
    threshold = cfg['VOLUME_TREND_RATIO_THRESHOLD']

    if 'volume' not in ohlc_df.columns or ohlc_df.empty:
        return None, 0.0, 'No volume data'

    volumes = ohlc_df['volume'].values

    # Merge and sort all pivots by bar index — they should already alternate
    all_pivots = sorted(pivot_highs + pivot_lows, key=lambda p: p.bar_index)
    if len(all_pivots) < 2:
        return None, 0.0, 'Insufficient pivots for leg analysis'

    with_trend_volumes = []
    counter_trend_volumes = []

    # Walk consecutive pivots; each segment is one leg
    for i in range(1, len(all_pivots)):
        prev = all_pivots[i - 1]
        curr = all_pivots[i]
        if prev.pivot_type == curr.pivot_type:
            # Skip duplicates (alternation should have removed these but be safe)
            continue

        start = prev.bar_index + 1
        end = curr.bar_index + 1
        if start >= end or start >= len(volumes):
            continue
        leg_volumes = volumes[start:min(end, len(volumes))]
        if len(leg_volumes) == 0:
            continue

        # Determine leg direction: if curr is HIGH and prev is LOW, leg is up
        leg_is_up = (curr.pivot_type == 'HIGH' and prev.pivot_type == 'LOW')

        if trend_direction == 'UPTREND':
            if leg_is_up:
                with_trend_volumes.extend(leg_volumes.tolist())
            else:
                counter_trend_volumes.extend(leg_volumes.tolist())
        else:  # DOWNTREND
            if not leg_is_up:
                with_trend_volumes.extend(leg_volumes.tolist())
            else:
                counter_trend_volumes.extend(leg_volumes.tolist())

    if not with_trend_volumes or not counter_trend_volumes:
        return None, 0.0, 'Insufficient leg data'

    with_trend_avg = float(np.mean(with_trend_volumes))
    counter_trend_avg = float(np.mean(counter_trend_volumes))

    if counter_trend_avg <= 0:
        return None, 0.0, 'Counter-trend volume zero'

    ratio = with_trend_avg / counter_trend_avg

    if ratio >= threshold:
        confirmed = True
        interp = (f'Volume expanding on with-trend legs '
                  f'(ratio={ratio:.2f}) — healthy {trend_direction.lower()}')
    elif ratio <= (1.0 / threshold):
        confirmed = False
        interp = (f'Volume expanding AGAINST trend '
                  f'(ratio={ratio:.2f}) — bearish divergence')
    else:
        confirmed = None
        interp = f'Volume trend inconclusive (ratio={ratio:.2f})'

    return confirmed, ratio, interp


# ============================================================================
# Section 5.9 — Volume divergence at anchor points
# ============================================================================

def detect_volume_divergence(channel: Channel,
                             primary_pivots: list[PivotPoint],
                             opposite_pivots: list[PivotPoint],
                             trend_direction: str) -> PivotVolumeDivergence:
    """Detect bearish/bullish volume divergences at successive pivots (§5.9).

    For an uptrend:
      - Bearish divergence at highs: PH_n+1.price > PH_n.price AND
                                     PH_n+1.volume_at_pivot < PH_n.volume_at_pivot
      - Bullish confirmation at lows: PL_n+1.price > PL_n.price AND
                                      PL_n+1.volume_at_pivot < PL_n.volume_at_pivot

    For a downtrend (mirror):
      - Bullish divergence at lows: PL_n+1.price < PL_n.price AND
                                    PL_n+1.volume_at_pivot < PL_n.volume_at_pivot
      - Bearish confirmation at highs: PH_n+1.price < PH_n.price AND
                                       PH_n+1.volume_at_pivot < PH_n.volume_at_pivot

    Returns:
        PivotVolumeDivergence with warning level and per-pivot details.
    """
    result = PivotVolumeDivergence()

    # We focus on the divergence (bearish for uptrend at highs; bullish for downtrend at lows)
    # because those are the actionable warnings. Confirmations are recorded as info.
    if trend_direction == 'UPTREND':
        check_pivots = sorted(opposite_pivots, key=lambda p: p.bar_index)
        higher_price_check = lambda a, b: a.price > b.price
    else:
        check_pivots = sorted(primary_pivots, key=lambda p: p.bar_index)
        higher_price_check = lambda a, b: a.price < b.price

    if len(check_pivots) < 2:
        result.divergence_warning = 'NONE'
        return result

    consecutive = 0
    max_consecutive = 0
    details = []

    for i in range(1, len(check_pivots)):
        prev = check_pivots[i - 1]
        curr = check_pivots[i]
        is_divergent = (
            higher_price_check(curr, prev)
            and curr.volume_at_pivot > 0
            and prev.volume_at_pivot > 0
            and curr.volume_at_pivot < prev.volume_at_pivot
        )

        details.append({
            'pivot': f'{curr.pivot_type}{i+1} at {curr.timestamp}',
            'price': float(curr.price),
            'volume_at_pivot': float(curr.volume_at_pivot),
            'volume_ratio': float(curr.volume_ratio),
            'prior_pivot_volume': float(prev.volume_at_pivot),
            'divergence': bool(is_divergent),
        })

        if is_divergent:
            consecutive += 1
            max_consecutive = max(max_consecutive, consecutive)
        else:
            consecutive = 0

    if max_consecutive >= 2:
        result.divergence_warning = 'SIGNIFICANT'
    elif max_consecutive == 1:
        result.divergence_warning = 'MILD'
    else:
        result.divergence_warning = 'NONE'

    result.divergence_count = max_consecutive
    result.details = details
    return result


# ============================================================================
# Section 5.10 — On-Balance Volume (OBV)
# ============================================================================

def compute_obv(closes: np.ndarray, volumes: np.ndarray) -> np.ndarray:
    """Cumulative On-Balance Volume series.

    OBV[0] = 0
    OBV[i] = OBV[i-1] + volume[i] if close[i] > close[i-1]
             OBV[i-1] - volume[i] if close[i] < close[i-1]
             OBV[i-1]              otherwise
    """
    n = len(closes)
    obv = np.zeros(n)
    for i in range(1, n):
        if closes[i] > closes[i - 1]:
            obv[i] = obv[i - 1] + volumes[i]
        elif closes[i] < closes[i - 1]:
            obv[i] = obv[i - 1] - volumes[i]
        else:
            obv[i] = obv[i - 1]
    return obv


def analyze_obv(obv_series: np.ndarray, channel: Channel,
                primary_pivots: list[PivotPoint], trend_direction: str,
                price_trendline_broken: bool = False,
                config: dict = None) -> OBVAnalysis:
    """Analyse OBV trend over the channel span (Section 5.10).

    Fits a regression to OBV across the channel's span and classifies
    confirmation/divergence vs the price trend. Optionally detects joint
    trendline breaks.

    Args:
        obv_series: Full OBV array.
        channel: Constructed price channel.
        primary_pivots: Primary-side pivots (lows for uptrend, highs for downtrend).
        trend_direction: 'UPTREND' or 'DOWNTREND'.
        price_trendline_broken: Whether the price primary line is broken.
        config: Optional config override.

    Returns:
        OBVAnalysis populated with slope, confirmation, joint break flags.
    """
    result = OBVAnalysis()
    result.obv_series = obv_series.tolist()

    if not channel or not channel.primary_line or not channel.primary_line.anchor_points:
        return result

    first_bar = channel.primary_line.anchor_points[0].bar_index
    last_bar = channel.primary_line.anchor_points[-1].bar_index

    if last_bar <= first_bar or last_bar >= len(obv_series):
        return result

    # Fit regression to OBV over channel span
    indices = np.arange(first_bar, last_bar + 1, dtype=float)
    obv_segment = obv_series[first_bar:last_bar + 1]
    if len(obv_segment) < 2:
        return result

    coeffs = np.polyfit(indices, obv_segment, 1)
    slope = float(coeffs[0])
    intercept = float(coeffs[1])

    # R²
    y_pred = slope * indices + intercept
    ss_res = float(np.sum((obv_segment - y_pred) ** 2))
    ss_tot = float(np.sum((obv_segment - np.mean(obv_segment)) ** 2))
    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    result.obv_slope = slope
    result.obv_r_squared = max(0.0, r_squared)

    # Slope direction (use a small epsilon relative to OBV magnitude)
    obv_range = float(np.max(np.abs(obv_segment))) if np.any(obv_segment) else 1.0
    epsilon = obv_range * 0.001
    if slope > epsilon:
        result.obv_slope_direction = 'POSITIVE'
    elif slope < -epsilon:
        result.obv_slope_direction = 'NEGATIVE'
    else:
        result.obv_slope_direction = 'FLAT'

    # Confirmation vs price trend
    if trend_direction == 'UPTREND':
        if slope > 0:
            result.obv_confirmation = 'CONFIRMED'
        else:
            result.obv_confirmation = 'DIVERGENT'
    elif trend_direction == 'DOWNTREND':
        if slope < 0:
            result.obv_confirmation = 'CONFIRMED'
        else:
            result.obv_confirmation = 'DIVERGENT'

    # Build OBV trendline anchored at the last OBV value within range
    role = 'OBV'
    obv_anchor_bar = first_bar
    obv_anchor_value = float(obv_segment[0])
    obv_intercept = obv_anchor_value - slope * obv_anchor_bar
    result.obv_trendline = Trendline(
        slope=slope,
        intercept=obv_intercept,
        anchor_points=[
            TrendlineAnchor(
                timestamp=primary_pivots[0].timestamp if primary_pivots else None,
                price=obv_anchor_value,
                bar_index=obv_anchor_bar,
            ),
        ],
        r_squared=result.obv_r_squared,
        role=role,
        construction_method='OBV_REGRESSION',
    )

    # Detect OBV trendline break — does the most recent OBV value cross below/above the line?
    last_obv = float(obv_series[-1])
    last_idx = len(obv_series) - 1
    expected_obv = slope * last_idx + obv_intercept
    if trend_direction == 'UPTREND':
        result.obv_trendline_broken = last_obv < expected_obv
    elif trend_direction == 'DOWNTREND':
        result.obv_trendline_broken = last_obv > expected_obv

    result.price_trendline_broken = price_trendline_broken

    if result.obv_trendline_broken and price_trendline_broken:
        result.joint_break = 'CONFIRMED'
    elif result.obv_trendline_broken and not price_trendline_broken:
        result.joint_break = 'OBV_LEADING'
    else:
        result.joint_break = 'NONE'

    return result


# ============================================================================
# Section 8.2.1 — Volume climax caution
# ============================================================================

def check_volume_climax(breakout_volume: float, avg_volume_20: float,
                        config: dict = None) -> bool:
    """Flag a volume climax on a breakout bar (Section 8.2.1).

    Per Bulkowski (Ch. 41): heavy breakout volume (>3× average) actually triples
    failure rates. This is a CAUTION flag, not a confirmation gate.

    Returns:
        True if breakout_volume > climax multiplier × avg_volume.
    """
    cfg = config or CONFIG
    multiplier = cfg['VOLUME_CLIMAX_MULTIPLIER']
    if avg_volume_20 <= 0:
        return False
    return breakout_volume > multiplier * avg_volume_20


# ============================================================================
# Section 9.1 — Sideways range volume analysis
# ============================================================================

def analyze_range_volume(ohlc_df: pd.DataFrame, upper: float, lower: float
                         ) -> tuple[str, str]:
    """Analyse volume behaviour within a horizontal range (Section 9.1).

    Returns (range_volume_bias, range_volume_trend):
      - range_volume_bias: BULLISH (rally vol > decline vol × 1.15), BEARISH, NEUTRAL
      - range_volume_trend: DECLINING (coiling — normal), FLAT, EXPANDING (anomaly)
    """
    if 'volume' not in ohlc_df.columns or ohlc_df.empty:
        return 'NEUTRAL', 'FLAT'

    closes = ohlc_df['close'].values
    volumes = ohlc_df['volume'].values
    n = len(closes)

    if n < 3:
        return 'NEUTRAL', 'FLAT'

    # Split bars into rising vs falling
    rally_volumes = []
    decline_volumes = []
    for i in range(1, n):
        if closes[i] > closes[i - 1]:
            rally_volumes.append(volumes[i])
        elif closes[i] < closes[i - 1]:
            decline_volumes.append(volumes[i])

    if not rally_volumes or not decline_volumes:
        bias = 'NEUTRAL'
    else:
        rally_avg = float(np.mean(rally_volumes))
        decline_avg = float(np.mean(decline_volumes))
        if rally_avg > decline_avg * 1.15:
            bias = 'BULLISH'
        elif decline_avg > rally_avg * 1.15:
            bias = 'BEARISH'
        else:
            bias = 'NEUTRAL'

    # Volume trend (slope of volume series)
    indices = np.arange(n, dtype=float)
    slope = float(np.polyfit(indices, volumes, 1)[0])
    avg_vol = float(np.mean(volumes))
    epsilon = avg_vol * 0.005  # 0.5% per bar threshold

    if slope < -epsilon:
        trend = 'DECLINING'
    elif slope > epsilon:
        trend = 'EXPANDING'
    else:
        trend = 'FLAT'

    return bias, trend


# ============================================================================
# Helper used by support_resistance.py for Section 11.2-11.3 zone scoring
# ============================================================================

def avg_volume_ratio_for_pivots(pivots: list[PivotPoint]) -> float:
    """Average volume_ratio across a set of pivots that touched a zone.

    Used by the S/R zone scorer to compute `avg_volume_ratio_at_touches`.
    Returns 1.0 (neutral) if no valid ratios available.
    """
    valid = [p.volume_ratio for p in pivots
             if p.volume_ratio and p.volume_ratio > 0]
    if not valid:
        return 1.0
    return float(np.mean(valid))
