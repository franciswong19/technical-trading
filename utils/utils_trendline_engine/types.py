"""
types.py

Dataclasses for the trendline analysis engine output structures.
All modules in the engine produce and consume these types.
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass
class PivotPoint:
    """A detected pivot point (local extremum)."""
    bar_index: int
    timestamp: datetime
    price: float
    pivot_type: str          # 'HIGH' or 'LOW'
    order: int = 1           # 1=first-order, 2=second-order, 3=third-order


@dataclass
class TrendlineAnchor:
    """A single anchor point on a trendline."""
    timestamp: datetime
    price: float
    bar_index: int


@dataclass
class Trendline:
    """A fitted trendline with slope, intercept, and anchor points."""
    slope: float                                    # price change per bar (or log-price if log scale)
    intercept: float                                # price at bar_index=0
    anchor_points: list[TrendlineAnchor]
    r_squared: float = 0.0
    role: str = ''                                  # 'SUPPORT' or 'RESISTANCE'
    steep_flag: bool = False
    construction_method: str = 'REGRESSION'         # 'REGRESSION', 'PARALLEL_CLONE', 'INDEPENDENT_FIT'

    def price_at(self, bar_index: float) -> float:
        """Return the trendline price at a given bar index."""
        return self.slope * bar_index + self.intercept


@dataclass
class ParallelValidation:
    """Result of Pass 2 parallel validation (residual analysis)."""
    residual_median_atr_ratio: float = 0.0
    residual_trend_slope: float = 0.0
    validation_result: str = 'PARALLEL_CONFIRMED'   # PARALLEL_CONFIRMED, CONVERGING, DIVERGING, ACCELERATING, TRIANGLE
    total_touches: int = 0


@dataclass
class CurrentPricePosition:
    """Where the current price sits within the channel."""
    price: float = 0.0
    pct_within_channel: float = 0.0                 # 0=at lower line, 100=at upper line
    zone: str = ''                                   # LOWER_QUARTER, LOWER_HALF, MID_UPPER, UPPER_QUARTER


@dataclass
class ProjectedValues:
    """Projected trendline prices for the next bar."""
    primary_line_price: float = 0.0
    opposite_line_price: float = 0.0


@dataclass
class Channel:
    """A trend channel defined by primary and opposite trendlines."""
    primary_line: Trendline
    opposite_line: Optional[Trendline] = None
    channel_geometry: str = 'PARALLEL'               # PARALLEL, RISING_WEDGE, FALLING_WEDGE, BROADENING,
                                                     # ASCENDING_TRIANGLE, DESCENDING_TRIANGLE, SYMMETRICAL_TRIANGLE
    resolution_bias: Optional[str] = None            # BULLISH, BEARISH, NEUTRAL, CAUTION_ACCELERATION
    width_pct: float = 0.0
    width_atr: float = 0.0
    width_status: str = 'VALID'                      # VALID, CHANNEL_TOO_NARROW, CHANNEL_TOO_WIDE
    parallel_validation: Optional[ParallelValidation] = None
    current_price_position: Optional[CurrentPricePosition] = None
    projected_values: Optional[ProjectedValues] = None
    # For steep trendlines: a secondary shallower channel
    secondary_channel: Optional['Channel'] = None


@dataclass
class SRZone:
    """A support or resistance zone."""
    zone_type: str                                   # 'SUPPORT' or 'RESISTANCE'
    midpoint: float
    upper: float
    lower: float
    touch_count: int = 0
    zone_score: float = 0.0
    role_reversal: bool = False
    age_bars: int = 0
    weakened: bool = False


@dataclass
class BreakInfo:
    """Information about a breakout or breakdown."""
    break_type: str                                  # 'BREAKOUT' or 'BREAKDOWN'
    break_level: float = 0.0
    reference_structure: str = ''                    # 'PRIOR_CHANNEL', 'SR_ZONE', 'CONSOLIDATION'
    confirmed: bool = False
    filters_passed: int = 0                          # how many of 3 filters passed (need 2)
    close_filter: bool = False
    atr_filter: bool = False
    volume_filter: bool = False
    break_bar_index: Optional[int] = None
    break_timestamp: Optional[datetime] = None
    pullback_expected: bool = True


@dataclass
class RegimeResult:
    """Result of market regime classification."""
    state: str                                       # 'TREND', 'BREAK', 'OTHERS'
    sub_type: Optional[str] = None                   # For OTHERS: 'SIDEWAYS', 'CHOPPY', 'TRANSITIONAL', 'INSUFFICIENT_DATA'
                                                     # For TREND: None
                                                     # For BREAK: None (see break_info)
    trend_direction: Optional[str] = None            # 'UPTREND' or 'DOWNTREND' (TREND regime only)
    confidence: float = 0.0
    r_squared: float = 0.0
    trend_start_bar_index: Optional[int] = None
    trend_start_timestamp: Optional[datetime] = None


@dataclass
class TrailingFitResult:
    """Result of the dual-fit (trailing fit) approach for recent data handling."""
    recent_divergence: bool = False
    slope_difference_pct: float = 0.0
    trailing_channel: Optional[Channel] = None


@dataclass
class HorizontalRange:
    """Horizontal trading range for SIDEWAYS regime."""
    upper_boundary: float
    lower_boundary: float
    width_pct: float


@dataclass
class TierResult:
    """Complete analysis result for a single tier (short/medium/long-term)."""
    tier: str                                        # 'short_term', 'medium_term', 'long_term'
    interval: str                                    # '15min', '1hour', 'daily'
    lookback_trading_days: int
    lookback_bars: int
    scale_mode: str = 'arithmetic'                   # 'arithmetic' or 'log'
    atr_14: float = 0.0

    regime: Optional[RegimeResult] = None
    trend_channel: Optional[Channel] = None
    trailing_fit: Optional[TrailingFitResult] = None
    fan_lines: list[Trendline] = field(default_factory=list)
    fan_exhausted: bool = False
    break_info: Optional[BreakInfo] = None
    horizontal_range: Optional[HorizontalRange] = None
    support_resistance_zones: list[SRZone] = field(default_factory=list)

    # All pivots found (for charting)
    pivot_highs: list[PivotPoint] = field(default_factory=list)
    pivot_lows: list[PivotPoint] = field(default_factory=list)


@dataclass
class TierConflict:
    """A conflict between two tiers."""
    tiers: list[str]                                 # e.g. ['long_term', 'short_term']
    conflict_type: str                               # 'DIRECTION_CONFLICT', 'REGIME_CONFLICT'
    interpretation: str = ''


@dataclass
class MultiTierInteraction:
    """Cross-tier analysis: confluence, conflict, and actionable guidance."""
    confluence: str = ''                             # FULL_BULLISH, FULL_BEARISH, PARTIAL_BULLISH, PARTIAL_BEARISH, NEUTRAL
    conviction: str = ''                             # HIGH, MEDIUM, LOW
    description: str = ''
    dominant_bias: str = ''                           # BULLISH, BEARISH, NEUTRAL
    conflicts: list[TierConflict] = field(default_factory=list)
    suggested_stop_tier: str = ''                     # 'short_term', 'medium_term', 'long_term'


@dataclass
class TickerAnalysis:
    """Top-level analysis output for a single ticker across all three tiers."""
    ticker: str
    analysis_timestamp: datetime
    short_term: Optional[TierResult] = None
    medium_term: Optional[TierResult] = None
    long_term: Optional[TierResult] = None
    multi_tier_interaction: Optional[MultiTierInteraction] = None
    status: str = 'SUCCESS'                          # SUCCESS, PARTIAL, FAILED
    errors: list[str] = field(default_factory=list)
