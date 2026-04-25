"""
config.py

Configuration defaults for the trendline analysis engine.
Transcribed from agent_docs/trendline_methodology.md Section 16.
All parameters are in one place for easy tuning.
"""

CONFIG = {
    # ═══════════════════════════════════════
    # TIER DEFINITIONS
    # ═══════════════════════════════════════
    "TIERS": {
        "short_term": {
            "interval": "15min",
            "lookback_trading_days": 20,
            "bars_per_day": 26,
            # → lookback_bars = 20 × 26 = 520
        },
        "medium_term": {
            "interval": "1hour",
            "lookback_trading_days": 60,
            "bars_per_day": 7,
            # → lookback_bars = 60 × 7 = 420
        },
        "long_term": {
            "interval": "daily",
            "lookback_trading_days": 260,
            "bars_per_day": 1,
            # → lookback_bars = 260
        },
    },

    # ═══════════════════════════════════════
    # PIVOT DETECTION (per tier)
    # ═══════════════════════════════════════
    "PIVOT_WINDOW": {
        "short_term": 3,           # bars on each side
        "medium_term": 4,
        "long_term": 5,
    },
    "ATR_PERIOD": 14,              # same across all tiers
    "ATR_SWING_MULTIPLIER": {
        "short_term": 0.75,
        "medium_term": 1.0,
        "long_term": 1.5,
    },
    "MIN_PIVOTS_PRIMARY": 3,       # same across all tiers
    "MIN_PIVOTS_OPPOSITE": 1,

    # ═══════════════════════════════════════
    # PIVOT SPACING (per tier)
    # ═══════════════════════════════════════
    "MIN_PIVOT_SEPARATION": {
        "short_term": 20,          # bars between same-side pivots
        "medium_term": 10,
        "long_term": 15,
    },
    "SWING_ATR_MULTIPLE": {
        "short_term": 1.0,         # intervening swing >= this × ATR
        "medium_term": 1.0,
        "long_term": 1.5,
    },
    "MIN_CHANNEL_SPAN": {
        "short_term": 80,          # bars from first to last anchor
        "medium_term": 30,
        "long_term": 40,
    },

    # ═══════════════════════════════════════
    # MARKET REGIME CLASSIFICATION
    # ═══════════════════════════════════════
    "MIN_R_SQUARED": 0.50,
    "CHOPPY_R_SQUARED_CEILING": 0.30,

    # ═══════════════════════════════════════
    # SLOPE CONSTRAINTS (% per bar, per tier)
    # ═══════════════════════════════════════
    "MIN_SLOPE": {
        "short_term": 0.00005,     # 0.005% per bar
        "medium_term": 0.00007,    # 0.007% per bar
        "long_term": 0.0001,       # 0.01% per bar
    },
    "MAX_SLOPE": {
        "short_term": 0.0015,      # 0.15% per bar
        "medium_term": 0.003,      # 0.30% per bar
        "long_term": 0.005,        # 0.50% per bar
    },

    # ═══════════════════════════════════════
    # CHANNEL WIDTH (% of midpoint price)
    # ═══════════════════════════════════════
    "MIN_WIDTH_PCT": {
        "short_term": 1.0,
        "medium_term": 1.5,
        "long_term": 2.0,
    },
    "MAX_WIDTH_PCT": {
        "short_term": 15.0,
        "medium_term": 20.0,
        "long_term": 30.0,
    },
    "MIN_WIDTH_ATR_MULTIPLE": 2.0,  # same across all tiers
    "MAX_WIDTH_ATR_MULTIPLE": 8.0,

    # ═══════════════════════════════════════
    # PARALLEL VALIDATION
    # ═══════════════════════════════════════
    "PARALLEL_RESIDUAL_ATR_THRESHOLD": 0.5,
    "PARALLEL_SLOPE_TOLERANCE": 0.15,
    "MIN_TOUCHES_FOR_WEDGE_TRIANGLE": 5,

    # ═══════════════════════════════════════
    # RECENT DATA HANDLING (per tier)
    # ═══════════════════════════════════════
    "RECENT_EXCLUDE": {
        "short_term": 26,          # bars excluded for trailing fit
        "medium_term": 7,
        "long_term": 10,
    },
    "RECENT_DIVERGENCE_THRESHOLD": 0.20,

    # ═══════════════════════════════════════
    # S/R ZONE CONSTRUCTION (per tier)
    # ═══════════════════════════════════════
    "ZONE_TOLERANCE_PCT": {
        "short_term": 0.3,
        "medium_term": 0.4,
        "long_term": 0.5,
    },
    "ZONE_TOLERANCE_ATR_MULTIPLE": 0.5,
    "MIN_ZONE_TOUCHES": 2,
    "MIN_ZONE_AGE_BARS": 5,
    "MIN_ZONE_SCORE": 4.0,
    "ZONE_WEAKENING_BASE": 0.90,
    "ZONE_DECAY_WINDOW": {
        "short_term": 400,         # bars
        "medium_term": 200,
        "long_term": 120,
    },

    # ═══════════════════════════════════════
    # S/R SCORING WEIGHTS (same across tiers)
    # ═══════════════════════════════════════
    "W_TOUCH": 2.0,
    "W_RECENCY": 1.5,
    "W_VOLUME": 1.0,
    "W_REVERSAL": 3.0,

    # ═══════════════════════════════════════
    # BREAKOUT CONFIRMATION (per tier)
    # ═══════════════════════════════════════
    "ATR_BREAKOUT_MULTIPLIER": 0.5,
    "VOLUME_BREAKOUT_MULTIPLIER": 1.25,
    "BREAKOUT_CONFIRM_BARS": {
        "short_term": 4,
        "medium_term": 3,
        "long_term": 3,
    },

    # ═══════════════════════════════════════
    # FAN PRINCIPLE (same across tiers)
    # ═══════════════════════════════════════
    "MAX_FAN_LINES": 3,

    # ═══════════════════════════════════════
    # LOG SCALE (same across tiers)
    # ═══════════════════════════════════════
    "LOG_SCALE_THRESHOLD": 0.20,

    # ═══════════════════════════════════════
    # EDGE CASES (same across tiers)
    # ═══════════════════════════════════════
    "GAP_THRESHOLD_ATR_MULTIPLE": 2.0,
    "LOW_LIQUIDITY_VOLUME": 100_000,
    "ELEVATED_VOL_RATIO": 2.0,
}


def get_tier_param(param_name: str, tier: str, config: dict = None) -> object:
    """Get a tier-specific parameter value, falling back to the global value if not per-tier.

    Args:
        param_name: The parameter name (e.g. 'PIVOT_WINDOW', 'MIN_R_SQUARED')
        tier: The tier name ('short_term', 'medium_term', 'long_term')
        config: Optional config dict override (defaults to CONFIG)

    Returns:
        The parameter value for the given tier.
    """
    cfg = config or CONFIG
    value = cfg[param_name]
    if isinstance(value, dict):
        return value[tier]
    return value


def get_tier_def(tier: str, config: dict = None) -> dict:
    """Get the tier definition (interval, lookback, bars_per_day)."""
    cfg = config or CONFIG
    return cfg["TIERS"][tier]


def get_lookback_bars(tier: str, config: dict = None) -> int:
    """Calculate total lookback bars for a tier."""
    tier_def = get_tier_def(tier, config)
    return tier_def["lookback_trading_days"] * tier_def["bars_per_day"]
