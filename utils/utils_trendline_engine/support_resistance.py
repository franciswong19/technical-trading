"""
support_resistance.py

Support and resistance zone construction (Section 11 of methodology).
Clusters reversal points into horizontal zones, scores them by touch count,
recency, volume, and role reversal, then applies weakening and decay.
"""

import numpy as np
import pandas as pd

from .types import PivotPoint, SRZone
from .config import get_tier_param, CONFIG


def build_sr_zones(pivot_highs: list[PivotPoint], pivot_lows: list[PivotPoint],
                   ohlc_df: pd.DataFrame, atr_value: float, tier: str,
                   config: dict = None) -> list[SRZone]:
    """Full S/R zone construction pipeline.

    Steps: cluster → score → filter.

    Args:
        pivot_highs: Confirmed pivot highs.
        pivot_lows: Confirmed pivot lows.
        ohlc_df: OHLCV DataFrame.
        atr_value: ATR(14) value.
        tier: Tier name.
        config: Optional config override.

    Returns:
        List of scored and filtered SRZone objects.
    """
    cfg = config or CONFIG
    total_bars = len(ohlc_df)
    volumes = ohlc_df['volume'].values if 'volume' in ohlc_df.columns else None
    avg_volume = float(np.mean(volumes)) if volumes is not None and len(volumes) > 0 else 1.0

    # Cluster resistance zones from pivot highs
    resistance_zones = _cluster_pivots_into_zones(
        pivot_highs, 'RESISTANCE', atr_value, tier, cfg
    )

    # Cluster support zones from pivot lows
    support_zones = _cluster_pivots_into_zones(
        pivot_lows, 'SUPPORT', atr_value, tier, cfg
    )

    all_zones = resistance_zones + support_zones

    # Check for role reversal (zone acted as both S and R)
    _detect_role_reversal(all_zones, pivot_highs, pivot_lows, atr_value, tier, cfg)

    # Score zones
    for zone in all_zones:
        zone.zone_score = _score_zone(zone, total_bars, volumes, avg_volume, tier, cfg)

    # Apply weakening (3+ touches)
    _apply_weakening(all_zones, cfg)

    # Apply time decay
    _apply_time_decay(all_zones, total_bars, tier, cfg)

    # Filter by minimum requirements
    all_zones = _filter_zones(all_zones, cfg)

    # Sort by score descending
    all_zones.sort(key=lambda z: z.zone_score, reverse=True)

    return all_zones


def _cluster_pivots_into_zones(pivots: list[PivotPoint], zone_type: str,
                                atr_value: float, tier: str,
                                config: dict) -> list[SRZone]:
    """Cluster nearby pivot prices into zones (Section 11.2-11.4).

    Uses ZONE_TOLERANCE_PCT or ZONE_TOLERANCE_ATR_MULTIPLE to group nearby levels.
    """
    if not pivots:
        return []

    tolerance_pct = get_tier_param('ZONE_TOLERANCE_PCT', tier, config) / 100.0
    tolerance_atr = config['ZONE_TOLERANCE_ATR_MULTIPLE'] * atr_value

    # Sort by price
    sorted_pivots = sorted(pivots, key=lambda p: p.price)

    zones = []
    current_cluster = [sorted_pivots[0]]

    for pivot in sorted_pivots[1:]:
        cluster_mid = np.mean([p.price for p in current_cluster])
        # Use the larger of percentage and ATR tolerance
        tol = max(cluster_mid * tolerance_pct, tolerance_atr)

        if abs(pivot.price - cluster_mid) <= tol:
            current_cluster.append(pivot)
        else:
            zones.append(_cluster_to_zone(current_cluster, zone_type, atr_value))
            current_cluster = [pivot]

    # Don't forget the last cluster
    zones.append(_cluster_to_zone(current_cluster, zone_type, atr_value))

    return zones


def _cluster_to_zone(cluster: list[PivotPoint], zone_type: str,
                     atr_value: float) -> SRZone:
    """Convert a cluster of pivots into an SRZone."""
    prices = [p.price for p in cluster]
    min_price = min(prices)
    max_price = max(prices)
    midpoint = (min_price + max_price) / 2.0

    # Zone boundaries with ATR padding (Section 11.4)
    zone_upper = max_price + 0.25 * atr_value
    zone_lower = min_price - 0.25 * atr_value

    # Age = bars since oldest pivot in cluster
    max_bar_index = max(p.bar_index for p in cluster)
    min_bar_index = min(p.bar_index for p in cluster)
    age_bars = max_bar_index - min_bar_index

    return SRZone(
        zone_type=zone_type,
        midpoint=midpoint,
        upper=zone_upper,
        lower=zone_lower,
        touch_count=len(cluster),
        zone_score=0.0,
        role_reversal=False,
        age_bars=age_bars,
    )


def _detect_role_reversal(zones: list[SRZone], pivot_highs: list[PivotPoint],
                          pivot_lows: list[PivotPoint], atr_value: float,
                          tier: str, config: dict):
    """Detect if any zone has acted as both support and resistance."""
    tolerance_pct = get_tier_param('ZONE_TOLERANCE_PCT', tier, config) / 100.0

    for zone in zones:
        tol = max(zone.midpoint * tolerance_pct, 0.5 * atr_value)
        opposite_pivots = pivot_lows if zone.zone_type == 'RESISTANCE' else pivot_highs

        for pivot in opposite_pivots:
            if abs(pivot.price - zone.midpoint) <= tol:
                zone.role_reversal = True
                break


def _score_zone(zone: SRZone, total_bars: int, volumes: np.ndarray | None,
                avg_volume: float, tier: str, config: dict) -> float:
    """Score a zone using the formula from Section 11.3.

    score = (touch_count × W_TOUCH) + (recency_score × W_RECENCY) +
            (volume_score × W_VOLUME) + (role_reversal_bonus × W_REVERSAL)
    """
    w_touch = config['W_TOUCH']
    w_recency = config['W_RECENCY']
    w_volume = config['W_VOLUME']
    w_reversal = config['W_REVERSAL']

    # Touch count component
    touch_score = zone.touch_count * w_touch

    # Recency: simple heuristic — newer zones score higher
    # Use age_bars relative to total bars
    recency_ratio = 1.0 - (zone.age_bars / max(total_bars, 1))
    recency_score = max(0.0, recency_ratio) * w_recency * zone.touch_count

    # Volume: normalized (using average as 1.0 baseline)
    volume_score = 1.0 * w_volume  # Default if no volume data

    # Role reversal bonus
    reversal_bonus = w_reversal if zone.role_reversal else 0.0

    return touch_score + recency_score + volume_score + reversal_bonus


def _apply_weakening(zones: list[SRZone], config: dict):
    """Apply weakening rule for zones with 3+ touches (Section 11.6).

    Repeated tests weaken levels:
        if touch_count >= 3: score *= 0.90 ^ (touch_count - 2)
    """
    base = config['ZONE_WEAKENING_BASE']
    for zone in zones:
        if zone.touch_count >= 3:
            zone.zone_score *= base ** (zone.touch_count - 2)
            zone.weakened = True


def _apply_time_decay(zones: list[SRZone], total_bars: int,
                      tier: str, config: dict):
    """Apply time decay for zones not recently tested (Section 11.7).

    If zone's most recent touch is older than DECAY_WINDOW, reduce score by 50%.
    """
    decay_window = get_tier_param('ZONE_DECAY_WINDOW', tier, config)
    for zone in zones:
        if zone.age_bars > decay_window:
            zone.zone_score *= 0.5


def _filter_zones(zones: list[SRZone], config: dict) -> list[SRZone]:
    """Filter zones by minimum requirements (Section 11.5).

    - At least 2 touches
    - At least 5 bars old
    - Score >= 4.0
    """
    min_touches = config['MIN_ZONE_TOUCHES']
    min_age = config['MIN_ZONE_AGE_BARS']
    min_score = config['MIN_ZONE_SCORE']

    return [z for z in zones
            if z.touch_count >= min_touches
            and z.age_bars >= min_age
            and z.zone_score >= min_score]
