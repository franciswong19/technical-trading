"""
scale.py

Chart scaling determination (Section 2 of methodology).
Decides whether to use arithmetic or logarithmic scale based on price range.
"""

import numpy as np


def determine_scale(highs: np.ndarray, lows: np.ndarray, threshold: float = 0.20):
    """Determine whether to use log or arithmetic scale.

    If (max_price - min_price) / min_price > threshold, use log scale.

    Args:
        highs: Array of high prices over the lookback window.
        lows: Array of low prices over the lookback window.
        threshold: Percentage threshold for switching to log scale (default 0.20 = 20%).

    Returns:
        Tuple of (scale_mode, transform_fn, inverse_fn):
            - scale_mode: 'log' or 'arithmetic'
            - transform_fn: function to apply to prices before calculations
            - inverse_fn: function to convert back to price space
    """
    max_price = np.max(highs)
    min_price = np.min(lows)

    if min_price <= 0:
        # Cannot use log scale with zero or negative prices
        return 'arithmetic', _identity, _identity

    price_range_pct = (max_price - min_price) / min_price

    if price_range_pct > threshold:
        return 'log', np.log, np.exp
    else:
        return 'arithmetic', _identity, _identity


def _identity(x):
    """Identity function (no transformation)."""
    return x
