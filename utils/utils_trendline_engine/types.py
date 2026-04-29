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
    # v2 volume fields (Section 3.7)
    volume_at_pivot: float = 0.0       # 3-bar centred avg
    volume_ratio: float = 0.0          # vs 20-bar SMA
    volume_change_vs_prior: float = 0.0  # % change vs prior same-side pivot


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
    outlier_pivots: list[PivotPoint] = None        # Pivots excluded from fit as statistical outliers

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
    # v2 volume fields
    volume_divergence: Optional['PivotVolumeDivergence'] = None  # Section 5.9
    obv_analysis: Optional['OBVAnalysis'] = None                  # Section 5.10


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
    # v2 volume fields (Section 11.2-11.3)
    avg_volume_ratio_at_touches: float = 1.0


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
    # v2 volume fields (Section 8.2 + 8.2.1)
    volume_climax_caution: bool = False              # >3x avg volume on breakout (Bulkowski empirical)
    breakdown_volume_elevated: bool = False          # diagnostic for downside breaks


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
    # v2 volume fields (Section 4.2 Step 5)
    volume_confirmed: Optional[bool] = None          # None=inconclusive, True=healthy, False=divergent
    volume_trend_ratio: float = 0.0


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
    # v2 volume fields (Section 9.1)
    range_volume_bias: str = 'NEUTRAL'      # BULLISH, BEARISH, NEUTRAL (rally vs decline volume)
    range_volume_trend: str = 'FLAT'        # DECLINING (coiling), FLAT, EXPANDING (anomaly)


@dataclass
class PivotVolumeDivergence:
    """Volume divergence detection at successive pivot anchors (Section 5.9)."""
    divergence_warning: str = 'NONE'              # SIGNIFICANT (>=2 consecutive), MILD (1), NONE
    divergence_count: int = 0
    details: list[dict] = field(default_factory=list)  # per-pivot divergence details


@dataclass
class OBVAnalysis:
    """On-Balance Volume trend analysis (Section 5.10)."""
    obv_slope: float = 0.0                        # slope of OBV over channel span
    obv_r_squared: float = 0.0
    obv_slope_direction: str = 'FLAT'             # POSITIVE, NEGATIVE, FLAT
    obv_confirmation: str = ''                    # CONFIRMED, DIVERGENT
    obv_trendline: Optional[Trendline] = None     # trendline fitted to OBV series
    obv_trendline_broken: bool = False
    price_trendline_broken: bool = False
    joint_break: str = 'NONE'                     # CONFIRMED, OBV_LEADING, NONE
    obv_series: list[float] = field(default_factory=list)  # full OBV series for charting


@dataclass
class VolumeAnalysis:
    """Aggregated volume analysis output for a tier (matches v2 §14 schema)."""
    volume_confirmed: Optional[bool] = None
    volume_trend_ratio: float = 0.0
    volume_trend_interpretation: str = ''
    pivot_volume_divergence: Optional[PivotVolumeDivergence] = None
    obv_analysis: Optional[OBVAnalysis] = None
    anchor_point_volumes: list[dict] = field(default_factory=list)


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

    # v2 aggregated volume analysis (Section 14)
    volume_analysis: Optional[VolumeAnalysis] = None


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
