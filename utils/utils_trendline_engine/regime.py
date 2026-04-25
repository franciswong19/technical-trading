"""
regime.py

Market regime classification (Section 4 of methodology).
Evaluates in strict priority order: TREND → BREAK → OTHERS.
"""

import numpy as np

from .types import PivotPoint, RegimeResult
from .config import get_tier_param, CONFIG


def check_trend(pivot_highs: list[PivotPoint], pivot_lows: list[PivotPoint],
                atr_value: float, tier: str,
                config: dict = None) -> RegimeResult | None:
    """Check if a directional TREND regime exists (Section 4.2).

    Steps:
    1. Pivot sequence (Dow Theory) — higher highs + higher lows OR lower lows + lower highs
    2. Pivot spacing validation (already applied in pivots.py)
    3. Quantitative confirmation via linear regression (R² >= 0.50)
    4. Trend start point identification

    Returns:
        RegimeResult with state='TREND' if confirmed, else None.
    """
    cfg = config or CONFIG
    min_r_squared = cfg['MIN_R_SQUARED']
    min_slope = get_tier_param('MIN_SLOPE', tier, cfg)

    # Need at least 2 of each for Dow Theory check
    if len(pivot_highs) < 2 or len(pivot_lows) < 2:
        return None

    # Step 1: Check for higher highs + higher lows (uptrend)
    uptrend = _check_consecutive_pattern(pivot_highs, 'higher') and \
              _check_consecutive_pattern(pivot_lows, 'higher')

    # Check for lower highs + lower lows (downtrend)
    downtrend = _check_consecutive_pattern(pivot_highs, 'lower') and \
                _check_consecutive_pattern(pivot_lows, 'lower')

    if not uptrend and not downtrend:
        return None

    # Step 3: Linear regression confirmation
    if uptrend:
        direction = 'UPTREND'
        primary_pivots = pivot_lows  # demand line
    else:
        direction = 'DOWNTREND'
        primary_pivots = pivot_highs  # supply line

    if len(primary_pivots) < 2:
        return None

    indices = np.array([p.bar_index for p in primary_pivots], dtype=float)
    prices = np.array([p.price for p in primary_pivots], dtype=float)

    slope, intercept, r_squared = _fit_regression(indices, prices)

    # Check slope threshold
    slope_pct = abs(slope) / np.mean(prices) if np.mean(prices) > 0 else 0
    if slope_pct < min_slope:
        return None

    # Check R² threshold
    if r_squared < min_r_squared:
        return None

    # Step 4: Trend start point — use the earliest primary pivot in the sequence
    trend_start = _find_trend_start(primary_pivots, direction)

    return RegimeResult(
        state='TREND',
        trend_direction=direction,
        confidence=r_squared,
        r_squared=r_squared,
        trend_start_bar_index=trend_start.bar_index,
        trend_start_timestamp=trend_start.timestamp,
    )


def _check_consecutive_pattern(pivots: list[PivotPoint], pattern: str) -> bool:
    """Check if at least 2 consecutive pivots follow a 'higher' or 'lower' pattern.

    Args:
        pivots: List of same-type pivots sorted by bar_index.
        pattern: 'higher' (each > prev) or 'lower' (each < prev).

    Returns:
        True if at least 2 consecutive pivots match the pattern.
    """
    if len(pivots) < 2:
        return False

    # Check the last N pivots (most recent trend matters most)
    # Need at least 2 consecutive matches
    consecutive = 0
    for i in range(len(pivots) - 1, 0, -1):
        if pattern == 'higher' and pivots[i].price > pivots[i - 1].price:
            consecutive += 1
        elif pattern == 'lower' and pivots[i].price < pivots[i - 1].price:
            consecutive += 1
        else:
            break

    return consecutive >= 1  # 2 pivots → 1 comparison → at least 2 consecutive higher/lower


def _find_trend_start(primary_pivots: list[PivotPoint],
                      direction: str) -> PivotPoint:
    """Find the trend start point — the most recent reversal pivot.

    For uptrend: the lowest pivot low before the higher-lows sequence began.
    For downtrend: the highest pivot high before the lower-highs sequence began.
    """
    # Walk backwards to find where the sequence breaks
    for i in range(len(primary_pivots) - 1, 0, -1):
        if direction == 'UPTREND' and primary_pivots[i].price <= primary_pivots[i - 1].price:
            return primary_pivots[i]
        elif direction == 'DOWNTREND' and primary_pivots[i].price >= primary_pivots[i - 1].price:
            return primary_pivots[i]

    return primary_pivots[0]


def classify_others(pivot_highs: list[PivotPoint], pivot_lows: list[PivotPoint],
                    atr_value: float, tier: str,
                    config: dict = None) -> RegimeResult:
    """Classify the OTHERS regime sub-type (Section 4.4 / Section 9).

    Sub-types: SIDEWAYS, CHOPPY, TRANSITIONAL, INSUFFICIENT_DATA.
    """
    cfg = config or CONFIG
    choppy_ceiling = cfg['CHOPPY_R_SQUARED_CEILING']
    min_slope = get_tier_param('MIN_SLOPE', tier, cfg)

    total_pivots = len(pivot_highs) + len(pivot_lows)
    if total_pivots < 4:
        return RegimeResult(state='OTHERS', sub_type='INSUFFICIENT_DATA')

    # Check if SIDEWAYS: both sides have low slope, contained range
    high_r2 = 0.0
    low_r2 = 0.0
    high_slope_pct = 0.0
    low_slope_pct = 0.0

    if len(pivot_highs) >= 2:
        h_idx = np.array([p.bar_index for p in pivot_highs], dtype=float)
        h_prices = np.array([p.price for p in pivot_highs], dtype=float)
        slope_h, _, high_r2 = _fit_regression(h_idx, h_prices)
        high_slope_pct = abs(slope_h) / np.mean(h_prices) if np.mean(h_prices) > 0 else 0

    if len(pivot_lows) >= 2:
        l_idx = np.array([p.bar_index for p in pivot_lows], dtype=float)
        l_prices = np.array([p.price for p in pivot_lows], dtype=float)
        slope_l, _, low_r2 = _fit_regression(l_idx, l_prices)
        low_slope_pct = abs(slope_l) / np.mean(l_prices) if np.mean(l_prices) > 0 else 0

    # SIDEWAYS: both slopes below MIN_SLOPE
    if high_slope_pct < min_slope and low_slope_pct < min_slope:
        return RegimeResult(state='OTHERS', sub_type='SIDEWAYS')

    # CHOPPY: R² < 0.30 on both sides
    if high_r2 < choppy_ceiling and low_r2 < choppy_ceiling:
        return RegimeResult(state='OTHERS', sub_type='CHOPPY')

    # Default: TRANSITIONAL
    return RegimeResult(state='OTHERS', sub_type='TRANSITIONAL')


def classify_regime(pivot_highs: list[PivotPoint], pivot_lows: list[PivotPoint],
                    ohlc_df, atr_value: float, tier: str,
                    config: dict = None,
                    prior_channel=None) -> RegimeResult:
    """Main regime classifier. Evaluates TREND → BREAK → OTHERS in strict order.

    Args:
        pivot_highs: Confirmed pivot highs.
        pivot_lows: Confirmed pivot lows.
        ohlc_df: DataFrame with OHLCV data.
        atr_value: ATR(14) value.
        tier: Tier name.
        config: Optional config override.
        prior_channel: Prior channel for break detection (optional).

    Returns:
        RegimeResult.
    """
    # Import here to avoid circular import
    from .breakout import check_break

    # Step 1: Check TREND
    trend_result = check_trend(pivot_highs, pivot_lows, atr_value, tier, config)
    if trend_result is not None:
        return trend_result

    # Step 2: Check BREAK
    break_info = check_break(pivot_highs, pivot_lows, ohlc_df, atr_value, tier,
                             config, prior_channel)
    if break_info is not None and break_info.confirmed:
        return RegimeResult(
            state='BREAK',
            sub_type=break_info.break_type,
        )

    # Step 3: OTHERS
    return classify_others(pivot_highs, pivot_lows, atr_value, tier, config)


def _fit_regression(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    """Fit a linear regression and return (slope, intercept, r_squared)."""
    if len(x) < 2:
        return 0.0, 0.0, 0.0

    # numpy polyfit for slope discovery
    coeffs = np.polyfit(x, y, 1)
    slope = coeffs[0]
    intercept = coeffs[1]

    # R² calculation
    y_pred = slope * x + intercept
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    return slope, intercept, max(0.0, r_squared)
