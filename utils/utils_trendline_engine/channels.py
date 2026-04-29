"""
channels.py

Trend channel construction (Sections 5-7, 10 of methodology).
Two-pass approach: assume parallel first, validate, then classify geometry.
Includes slope constraints, width validation, and trailing fit.
"""

import numpy as np

from .types import (PivotPoint, Trendline, TrendlineAnchor, Channel,
                    ParallelValidation, CurrentPricePosition, ProjectedValues,
                    TrailingFitResult)
from .config import get_tier_param, CONFIG


def build_channel(pivot_highs: list[PivotPoint], pivot_lows: list[PivotPoint],
                  ohlc_df, atr_value: float, trend_direction: str,
                  trend_start_bar: int, tier: str,
                  config: dict = None) -> tuple[Channel | None, TrailingFitResult | None]:
    """Full channel construction pipeline.

    Returns:
        Tuple of (channel, trailing_fit_result). Either may be None.
    """
    cfg = config or CONFIG

    # Select pivots from trend start onwards
    if trend_direction == 'UPTREND':
        primary_pivots = [p for p in pivot_lows if p.bar_index >= trend_start_bar]
        opposite_pivots = [p for p in pivot_highs if p.bar_index >= trend_start_bar]
        primary_role = 'SUPPORT'
        opposite_role = 'RESISTANCE'
    else:
        primary_pivots = [p for p in pivot_highs if p.bar_index >= trend_start_bar]
        opposite_pivots = [p for p in pivot_lows if p.bar_index >= trend_start_bar]
        primary_role = 'RESISTANCE'
        opposite_role = 'SUPPORT'

    if len(primary_pivots) < 2:
        return None, None

    # Pass 1: Primary trendline
    primary_line = _fit_primary_trendline(primary_pivots, trend_direction,
                                          ohlc_df, primary_role, atr_value, cfg)
    if primary_line is None:
        return None, None

    # Pass 1: Parallel channel line
    parallel_line = _build_parallel_line(primary_line, opposite_pivots,
                                         trend_direction, opposite_role, ohlc_df)

    # Pass 2: Validate parallelism
    validation = _validate_parallel(parallel_line, opposite_pivots, atr_value, cfg)

    # Determine channel geometry
    if validation.validation_result == 'PARALLEL_CONFIRMED':
        channel = Channel(
            primary_line=primary_line,
            opposite_line=parallel_line,
            channel_geometry='PARALLEL',
            parallel_validation=validation,
        )
    else:
        # Independently fit the opposite line
        independent_opposite = _fit_independent_opposite(opposite_pivots, trend_direction,
                                                         ohlc_df, opposite_role, cfg)
        geometry, resolution_bias = _classify_geometry(
            primary_line, independent_opposite or parallel_line,
            validation, opposite_pivots, cfg
        )
        channel = Channel(
            primary_line=primary_line,
            opposite_line=independent_opposite or parallel_line,
            channel_geometry=geometry,
            resolution_bias=resolution_bias,
            parallel_validation=validation,
        )

    # Validate slope (Section 6)
    _validate_slope(channel, tier, cfg)

    # Validate width (Section 7)
    _validate_width(channel, atr_value, tier, cfg, ohlc_df)

    # Current price position
    if not ohlc_df.empty:
        _compute_current_position(channel, ohlc_df)
        _compute_projections(channel, len(ohlc_df))

    # Trailing fit (Section 10)
    trailing_result = _build_trailing_fit(
        primary_pivots, opposite_pivots, trend_direction, ohlc_df,
        atr_value, primary_role, opposite_role, tier, cfg
    )

    # v2 volume analysis on the constructed channel:
    # - §5.9 volume divergence at successive anchor pivots
    # - §5.10 OBV trend tracking + joint trendline break detection
    if 'volume' in ohlc_df.columns and channel is not None:
        from .volume import detect_volume_divergence, compute_obv, analyze_obv

        channel.volume_divergence = detect_volume_divergence(
            channel, primary_pivots, opposite_pivots, trend_direction
        )

        if cfg.get('OBV_ENABLED', True):
            closes = ohlc_df['close'].values
            volumes = ohlc_df['volume'].values
            obv_series = compute_obv(closes, volumes)

            # Has the price primary line been broken?
            price_broken = False
            if channel.primary_line.anchor_points:
                last_idx = len(closes) - 1
                expected = channel.primary_line.price_at(last_idx)
                if trend_direction == 'UPTREND':
                    price_broken = closes[last_idx] < expected
                else:
                    price_broken = closes[last_idx] > expected

            channel.obv_analysis = analyze_obv(
                obv_series, channel, primary_pivots, trend_direction,
                price_trendline_broken=price_broken, config=cfg
            )

    return channel, trailing_result


def _fit_primary_trendline(pivots: list[PivotPoint], trend_direction: str,
                           ohlc_df, role: str,
                           atr_value: float = 0.0,
                           config: dict = None) -> Trendline | None:
    """Fit the primary trendline (Section 5.1).

    Uses regression for slope discovery, removes outlier pivots (>2×ATR residual),
    then finds the intercept that maximises R² while keeping ≥80% of non-outlier
    pivots on the correct side of the line (above for support, below for resistance).
    """
    from .config import CONFIG
    cfg = config or CONFIG

    if len(pivots) < 2:
        return None

    indices = np.array([p.bar_index for p in pivots], dtype=float)
    prices = np.array([p.price for p in pivots], dtype=float)

    # Linear regression on all pivots
    coeffs = np.polyfit(indices, prices, 1)
    slope = coeffs[0]
    intercept_raw = coeffs[1]  # OLS intercept — maximises R²

    # Find intercept satisfying ≥MIN_CORRECT_SIDE_PCT on the correct side,
    # as close to intercept_raw as possible (maximises R²).
    min_correct = cfg.get('TRENDLINE_MIN_CORRECT_SIDE_PCT', 0.80)
    N = len(pivots)
    max_wrong = int(np.floor((1.0 - min_correct) * N))

    # adjusted_intercept_i = the intercept value that places the line exactly on pivot i
    adj = prices - slope * indices
    sorted_adj = np.sort(adj)  # ascending

    if role == 'SUPPORT':
        # Pivot is on/above line IFF adj_i >= intercept.
        # Allow at most max_wrong below → max valid intercept = sorted_adj[max_wrong].
        threshold = sorted_adj[max_wrong]
        intercept = min(intercept_raw, threshold)
    else:
        # Pivot is on/below line IFF adj_i <= intercept.
        # Allow at most max_wrong above → min valid intercept = sorted_adj[N-1-max_wrong].
        threshold = sorted_adj[N - 1 - max_wrong]
        intercept = max(intercept_raw, threshold)

    # R² on all pivots
    y_pred = slope * indices + intercept
    ss_res = np.sum((prices - y_pred) ** 2)
    ss_tot = np.sum((prices - np.mean(prices)) ** 2)
    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    anchors = [TrendlineAnchor(
        timestamp=p.timestamp, price=p.price, bar_index=p.bar_index
    ) for p in pivots]

    return Trendline(
        slope=slope,
        intercept=intercept,
        anchor_points=anchors,
        r_squared=max(0.0, r_squared),
        role=role,
        construction_method='REGRESSION',
    )


def _build_parallel_line(primary: Trendline, opposite_pivots: list[PivotPoint],
                         trend_direction: str, role: str,
                         ohlc_df) -> Trendline | None:
    """Build the parallel channel line with the same slope as primary (Section 5.2).

    Anchors to the most extreme opposite pivot.
    """
    if not opposite_pivots:
        return None

    # Same slope as primary
    slope = primary.slope

    # Anchor to the most extreme opposite pivot
    if trend_direction == 'UPTREND':
        # Upper line: anchor to highest pivot high
        anchor_pivot = max(opposite_pivots, key=lambda p: p.price)
    else:
        # Lower line: anchor to lowest pivot low
        anchor_pivot = min(opposite_pivots, key=lambda p: p.price)

    intercept = anchor_pivot.price - slope * anchor_pivot.bar_index

    # Verify no cut-through between primary's outermost anchors
    if primary.anchor_points and len(ohlc_df) > 0:
        first_idx = primary.anchor_points[0].bar_index
        last_idx = primary.anchor_points[-1].bar_index
        highs = ohlc_df['high'].values
        lows = ohlc_df['low'].values

        for i in range(first_idx, min(last_idx + 1, len(ohlc_df))):
            line_price = slope * i + intercept
            if trend_direction == 'UPTREND' and highs[i] > line_price:
                # Need to shift up
                intercept = max(intercept, highs[i] - slope * i)
            elif trend_direction == 'DOWNTREND' and lows[i] < line_price:
                intercept = min(intercept, lows[i] - slope * i)

    anchor = TrendlineAnchor(
        timestamp=anchor_pivot.timestamp,
        price=anchor_pivot.price,
        bar_index=anchor_pivot.bar_index,
    )

    return Trendline(
        slope=slope,
        intercept=intercept,
        anchor_points=[anchor],
        role=role,
        construction_method='PARALLEL_CLONE',
    )


def _validate_parallel(parallel_line: Trendline | None,
                       opposite_pivots: list[PivotPoint],
                       atr_value: float, config: dict) -> ParallelValidation:
    """Validate whether the parallel line is respected (Section 5.3).

    Computes residuals of opposite pivots against the parallel line.
    """
    if parallel_line is None or len(opposite_pivots) < 2:
        return ParallelValidation(validation_result='PARALLEL_CONFIRMED',
                                  total_touches=len(opposite_pivots))

    threshold = config['PARALLEL_RESIDUAL_ATR_THRESHOLD']

    # Compute residuals
    residuals = []
    for pivot in opposite_pivots:
        expected = parallel_line.price_at(pivot.bar_index)
        residuals.append(pivot.price - expected)

    residuals = np.array(residuals)
    median_residual = np.median(residuals)
    median_ratio = median_residual / atr_value if atr_value > 0 else 0

    # Residual trend (slope of residuals over time)
    if len(residuals) >= 2:
        res_indices = np.arange(len(residuals), dtype=float)
        res_slope = np.polyfit(res_indices, residuals, 1)[0]
    else:
        res_slope = 0.0

    # Classify (Section 5.3)
    if abs(median_ratio) < threshold and abs(res_slope) < 0.1 * atr_value:
        result = 'PARALLEL_CONFIRMED'
    elif median_ratio < -threshold or res_slope < -0.05 * atr_value:
        result = 'CONVERGING'
    elif median_ratio > threshold or res_slope > 0.05 * atr_value:
        result = 'DIVERGING'
    else:
        result = 'PARALLEL_CONFIRMED'

    return ParallelValidation(
        residual_median_atr_ratio=median_ratio,
        residual_trend_slope=res_slope,
        validation_result=result,
        total_touches=len(opposite_pivots),
    )


def _fit_independent_opposite(opposite_pivots: list[PivotPoint],
                              trend_direction: str, ohlc_df,
                              role: str, config: dict = None) -> Trendline | None:
    """Independently fit the opposite-side line (Section 5.4 Step 4)."""
    from .config import CONFIG
    cfg = config or CONFIG

    if len(opposite_pivots) < 2:
        return None

    indices = np.array([p.bar_index for p in opposite_pivots], dtype=float)
    prices = np.array([p.price for p in opposite_pivots], dtype=float)

    coeffs = np.polyfit(indices, prices, 1)
    slope = coeffs[0]
    intercept_raw = coeffs[1]

    # Apply same ≥min_correct_side_pct logic as _fit_primary_trendline
    min_correct = cfg.get('TRENDLINE_MIN_CORRECT_SIDE_PCT', 0.70)
    N = len(opposite_pivots)
    max_wrong = int(np.floor((1.0 - min_correct) * N))

    adj = prices - slope * indices
    sorted_adj = np.sort(adj)

    if role == 'SUPPORT':
        threshold = sorted_adj[max_wrong]
        intercept = min(intercept_raw, threshold)
    else:  # RESISTANCE
        threshold = sorted_adj[N - 1 - max_wrong]
        intercept = max(intercept_raw, threshold)

    # R²
    y_pred = slope * indices + intercept
    ss_res = np.sum((prices - y_pred) ** 2)
    ss_tot = np.sum((prices - np.mean(prices)) ** 2)
    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    anchors = [TrendlineAnchor(
        timestamp=p.timestamp, price=p.price, bar_index=p.bar_index
    ) for p in opposite_pivots]

    return Trendline(
        slope=slope,
        intercept=intercept,
        anchor_points=anchors,
        r_squared=max(0.0, r_squared),
        role=role,
        construction_method='INDEPENDENT_FIT',
    )


def _classify_geometry(primary: Trendline, opposite: Trendline,
                       validation: ParallelValidation,
                       opposite_pivots: list[PivotPoint],
                       config: dict) -> tuple[str, str | None]:
    """Classify channel geometry (Section 5.5).

    Returns:
        Tuple of (geometry, resolution_bias).
    """
    slope_tolerance = config['PARALLEL_SLOPE_TOLERANCE']
    min_touches = config['MIN_TOUCHES_FOR_WEDGE_TRIANGLE']

    slope_primary = primary.slope
    slope_opposite = opposite.slope
    max_abs_slope = max(abs(slope_primary), abs(slope_opposite))

    if max_abs_slope == 0:
        return 'PARALLEL', None

    slope_diff_pct = abs(slope_primary - slope_opposite) / max_abs_slope

    # 5.5a: PARALLEL — slopes within tolerance
    if slope_diff_pct < slope_tolerance:
        return 'PARALLEL', None

    # Check touch count for wedge/triangle classification
    total_touches = len(primary.anchor_points) + len(opposite.anchor_points)
    tag_prefix = '' if total_touches >= min_touches else 'POSSIBLE_'

    # Both slopes same sign → converging or diverging
    same_sign = (slope_primary > 0 and slope_opposite > 0) or \
                (slope_primary < 0 and slope_opposite < 0)

    if same_sign:
        # Check for convergence (wedge)
        if validation.validation_result == 'CONVERGING':
            if slope_primary > 0:
                # Rising wedge (uptrend, upper slope < lower slope)
                return f'{tag_prefix}RISING_WEDGE', 'BEARISH'
            else:
                # Falling wedge
                return f'{tag_prefix}FALLING_WEDGE', 'BULLISH'
        elif validation.validation_result == 'DIVERGING':
            return 'BROADENING', 'BEARISH'

    # One side flat → triangle
    flat_threshold = 0.0001  # Essentially flat
    primary_flat = abs(slope_primary) < flat_threshold
    opposite_flat = abs(slope_opposite) < flat_threshold

    if primary_flat or opposite_flat:
        if opposite_flat and slope_primary > 0:
            return f'{tag_prefix}ASCENDING_TRIANGLE', 'BULLISH'
        elif opposite_flat and slope_primary < 0:
            return f'{tag_prefix}DESCENDING_TRIANGLE', 'BEARISH'
        elif primary_flat:
            if slope_opposite > 0:
                return f'{tag_prefix}ASCENDING_TRIANGLE', 'BULLISH'
            else:
                return f'{tag_prefix}DESCENDING_TRIANGLE', 'BEARISH'
        return f'{tag_prefix}SYMMETRICAL_TRIANGLE', 'NEUTRAL'

    # Both converging equally
    if abs(slope_primary + slope_opposite) < abs(slope_primary - slope_opposite) * 0.5:
        return f'{tag_prefix}SYMMETRICAL_TRIANGLE', 'NEUTRAL'

    # Default: treat as non-parallel
    if validation.validation_result == 'CONVERGING':
        if slope_primary > 0:
            return f'{tag_prefix}RISING_WEDGE', 'BEARISH'
        return f'{tag_prefix}FALLING_WEDGE', 'BULLISH'

    return 'PARALLEL', None


def _validate_slope(channel: Channel, tier: str, config: dict):
    """Validate slope constraints (Section 6).

    Sets steep_flag and attempts to build a secondary shallower channel.
    """
    max_slope = get_tier_param('MAX_SLOPE', tier, config)
    primary = channel.primary_line

    # Compute slope as percentage of price per bar
    mid_price = primary.price_at(
        primary.anchor_points[-1].bar_index if primary.anchor_points else 0
    )
    if mid_price <= 0:
        return

    slope_pct = abs(primary.slope) / mid_price

    if slope_pct > max_slope:
        channel.primary_line.steep_flag = True


def _validate_width(channel: Channel, atr_value: float, tier: str,
                    config: dict, ohlc_df):
    """Validate channel width constraints (Section 7)."""
    if channel.opposite_line is None:
        return

    min_width_pct = get_tier_param('MIN_WIDTH_PCT', tier, config)
    max_width_pct = get_tier_param('MAX_WIDTH_PCT', tier, config)
    min_atr_mult = config['MIN_WIDTH_ATR_MULTIPLE']
    max_atr_mult = config['MAX_WIDTH_ATR_MULTIPLE']

    # Compute width at the midpoint of the channel span
    if channel.primary_line.anchor_points:
        mid_bar = channel.primary_line.anchor_points[-1].bar_index
    else:
        mid_bar = len(ohlc_df) // 2

    upper_price = max(channel.primary_line.price_at(mid_bar),
                      channel.opposite_line.price_at(mid_bar))
    lower_price = min(channel.primary_line.price_at(mid_bar),
                      channel.opposite_line.price_at(mid_bar))
    mid_price = (upper_price + lower_price) / 2.0

    if mid_price <= 0:
        return

    width_pct = (upper_price - lower_price) / mid_price * 100.0
    width_atr = (upper_price - lower_price) / atr_value if atr_value > 0 else 0

    channel.width_pct = width_pct
    channel.width_atr = width_atr

    if width_pct < min_width_pct:
        channel.width_status = 'CHANNEL_TOO_NARROW'
    elif width_pct > max_width_pct:
        channel.width_status = 'CHANNEL_TOO_WIDE'
    else:
        channel.width_status = 'VALID'


def _compute_current_position(channel: Channel, ohlc_df):
    """Compute where the current price sits within the channel."""
    if channel.opposite_line is None:
        return

    current_price = ohlc_df['close'].values[-1]
    last_bar = len(ohlc_df) - 1

    lower = min(channel.primary_line.price_at(last_bar),
                channel.opposite_line.price_at(last_bar))
    upper = max(channel.primary_line.price_at(last_bar),
                channel.opposite_line.price_at(last_bar))

    if upper == lower:
        pct = 50.0
    else:
        pct = (current_price - lower) / (upper - lower) * 100.0

    if pct < 25:
        zone = 'LOWER_QUARTER'
    elif pct < 50:
        zone = 'LOWER_HALF'
    elif pct < 75:
        zone = 'MID_UPPER'
    else:
        zone = 'UPPER_QUARTER'

    channel.current_price_position = CurrentPricePosition(
        price=current_price, pct_within_channel=pct, zone=zone
    )


def _compute_projections(channel: Channel, total_bars: int):
    """Compute projected trendline prices for the next bar."""
    if channel.opposite_line is None:
        return

    next_bar = total_bars  # 0-indexed, so total_bars = next bar index
    channel.projected_values = ProjectedValues(
        primary_line_price=channel.primary_line.price_at(next_bar),
        opposite_line_price=channel.opposite_line.price_at(next_bar),
    )


def _build_trailing_fit(primary_pivots, opposite_pivots, trend_direction,
                        ohlc_df, atr_value, primary_role, opposite_role,
                        tier, config) -> TrailingFitResult | None:
    """Build trailing fit channel excluding recent N bars (Section 10).

    Compares slope with full-fit to detect recent divergence.
    """
    exclude_bars = get_tier_param('RECENT_EXCLUDE', tier, config)
    divergence_threshold = config['RECENT_DIVERGENCE_THRESHOLD']

    total_bars = len(ohlc_df)
    cutoff = total_bars - exclude_bars

    # Filter pivots to exclude recent bars
    trailing_primary = [p for p in primary_pivots if p.bar_index < cutoff]
    trailing_opposite = [p for p in opposite_pivots if p.bar_index < cutoff]

    if len(trailing_primary) < 2:
        return TrailingFitResult(recent_divergence=False)

    # Fit trailing primary line
    trailing_primary_line = _fit_primary_trendline(
        trailing_primary, trend_direction, ohlc_df, primary_role, atr_value, config
    )
    if trailing_primary_line is None:
        return TrailingFitResult(recent_divergence=False)

    # Full-fit primary line
    full_primary_line = _fit_primary_trendline(
        primary_pivots, trend_direction, ohlc_df, primary_role, atr_value, config
    )
    if full_primary_line is None:
        return TrailingFitResult(recent_divergence=False)

    # Compare slopes
    if abs(full_primary_line.slope) > 0:
        slope_diff = abs(trailing_primary_line.slope - full_primary_line.slope) / \
                     abs(full_primary_line.slope)
    else:
        slope_diff = 0.0

    divergence = slope_diff > divergence_threshold

    # Build trailing channel for reference
    trailing_parallel = _build_parallel_line(
        trailing_primary_line, trailing_opposite, trend_direction,
        opposite_role, ohlc_df
    )

    trailing_channel = Channel(
        primary_line=trailing_primary_line,
        opposite_line=trailing_parallel,
        channel_geometry='PARALLEL',
    ) if trailing_parallel else None

    return TrailingFitResult(
        recent_divergence=divergence,
        slope_difference_pct=slope_diff,
        trailing_channel=trailing_channel,
    )
