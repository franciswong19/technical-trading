"""
fan_principle.py

Fan principle detection and trend redrawing (Section 12 of methodology).
When a trendline is broken, redraw at a shallower angle. Maximum 3 fan lines
before a reversal is expected.
"""

import numpy as np

from .types import PivotPoint, Trendline, TrendlineAnchor
from .config import CONFIG


def detect_fan_lines(primary_line: Trendline, ohlc_df,
                     primary_pivots: list[PivotPoint],
                     trend_direction: str,
                     config: dict = None) -> tuple[list[Trendline], bool]:
    """Detect fan lines by iteratively redrawing broken trendlines (Section 12.2).

    Args:
        primary_line: The current primary trendline.
        ohlc_df: OHLCV DataFrame.
        primary_pivots: Primary-side pivots (lows for uptrend, highs for downtrend).
        trend_direction: 'UPTREND' or 'DOWNTREND'.
        config: Optional config override.

    Returns:
        Tuple of (fan_lines, fan_exhausted).
        fan_lines: list of up to 3 Trendline objects.
        fan_exhausted: True if 3 fan lines have been broken (reversal signal).
    """
    cfg = config or CONFIG
    max_fan = cfg['MAX_FAN_LINES']

    if ohlc_df.empty or len(primary_pivots) < 2:
        return [], False

    closes = ohlc_df['close'].values
    lows = ohlc_df['low'].values
    highs = ohlc_df['high'].values

    fan_lines = []
    current_line = primary_line
    remaining_pivots = list(primary_pivots)

    for _ in range(max_fan):
        fan_lines.append(current_line)

        # Check if current line is broken
        break_index = _find_break_point(current_line, closes, lows, highs,
                                        trend_direction)

        if break_index is None:
            # Line not broken — done
            break

        if len(fan_lines) >= max_fan:
            # 3rd fan line broken → exhausted
            return fan_lines, True

        # Redraw using pivots after the break point
        remaining_pivots = [p for p in remaining_pivots if p.bar_index > break_index]
        if len(remaining_pivots) < 2:
            break

        new_line = _fit_fan_line(remaining_pivots, trend_direction)
        if new_line is None:
            break

        current_line = new_line

    return fan_lines, len(fan_lines) >= max_fan


def _find_break_point(line: Trendline, closes: np.ndarray,
                      lows: np.ndarray, highs: np.ndarray,
                      trend_direction: str) -> int | None:
    """Find the bar index where the trendline is broken.

    For uptrend: close below the demand line.
    For downtrend: close above the supply line.
    """
    start = 0
    if line.anchor_points:
        start = line.anchor_points[-1].bar_index + 1

    for i in range(start, len(closes)):
        line_price = line.price_at(i)
        if trend_direction == 'UPTREND' and closes[i] < line_price:
            return i
        elif trend_direction == 'DOWNTREND' and closes[i] > line_price:
            return i

    return None


def _fit_fan_line(pivots: list[PivotPoint],
                  trend_direction: str) -> Trendline | None:
    """Fit a new fan line from remaining pivots."""
    if len(pivots) < 2:
        return None

    indices = np.array([p.bar_index for p in pivots], dtype=float)
    prices = np.array([p.price for p in pivots], dtype=float)

    coeffs = np.polyfit(indices, prices, 1)
    slope = coeffs[0]

    if trend_direction == 'UPTREND':
        adjusted_intercepts = prices - slope * indices
        intercept = np.min(adjusted_intercepts)
    else:
        adjusted_intercepts = prices - slope * indices
        intercept = np.max(adjusted_intercepts)

    role = 'SUPPORT' if trend_direction == 'UPTREND' else 'RESISTANCE'

    anchors = [TrendlineAnchor(
        timestamp=p.timestamp, price=p.price, bar_index=p.bar_index
    ) for p in pivots]

    return Trendline(
        slope=slope,
        intercept=intercept,
        anchor_points=anchors,
        role=role,
        construction_method='REGRESSION',
    )
