"""
multi_tier.py

Multi-tier interaction analysis (Section 13 of methodology).
Compares regimes across short/medium/long-term tiers to identify
confluence, conflict, and actionable guidance.
"""

from .types import TierResult, MultiTierInteraction, TierConflict


def analyze_tier_interaction(short: TierResult | None,
                             medium: TierResult | None,
                             long: TierResult | None) -> MultiTierInteraction:
    """Analyze confluence and conflict across three tiers (Section 13.2-13.6).

    Args:
        short: Short-term tier result.
        medium: Medium-term tier result.
        long: Long-term tier result.

    Returns:
        MultiTierInteraction with confluence, conviction, conflicts, and guidance.
    """
    result = MultiTierInteraction()

    tiers = {'short_term': short, 'medium_term': medium, 'long_term': long}
    directions = {}
    regimes = {}

    for name, tier in tiers.items():
        if tier is None or tier.regime is None:
            regimes[name] = 'UNKNOWN'
            directions[name] = None
            continue
        regimes[name] = tier.regime.state
        if tier.regime.state == 'TREND':
            directions[name] = tier.regime.trend_direction
        elif tier.regime.state == 'BREAK' and tier.break_info:
            directions[name] = 'UPTREND' if tier.break_info.break_type == 'BREAKOUT' else 'DOWNTREND'
        else:
            directions[name] = None

    # Confluence detection (Section 13.2)
    bullish_count = sum(1 for d in directions.values() if d == 'UPTREND')
    bearish_count = sum(1 for d in directions.values() if d == 'DOWNTREND')
    total_directional = bullish_count + bearish_count

    if bullish_count == 3:
        result.confluence = 'FULL_BULLISH'
        result.conviction = 'HIGH'
        result.dominant_bias = 'BULLISH'
    elif bearish_count == 3:
        result.confluence = 'FULL_BEARISH'
        result.conviction = 'HIGH'
        result.dominant_bias = 'BEARISH'
    elif bullish_count >= 2:
        result.confluence = 'PARTIAL_BULLISH'
        result.conviction = 'MEDIUM'
        result.dominant_bias = 'BULLISH'
    elif bearish_count >= 2:
        result.confluence = 'PARTIAL_BEARISH'
        result.conviction = 'MEDIUM'
        result.dominant_bias = 'BEARISH'
    else:
        result.confluence = 'NEUTRAL'
        result.conviction = 'LOW'
        result.dominant_bias = 'NEUTRAL'

    # Override with long-term bias (Section 13.4: tier dominance rule)
    if directions.get('long_term'):
        result.dominant_bias = 'BULLISH' if directions['long_term'] == 'UPTREND' else 'BEARISH'

    # Conflict detection (Section 13.3)
    conflicts = []

    # Long vs short conflict
    if directions.get('long_term') and directions.get('short_term'):
        if directions['long_term'] != directions['short_term']:
            interp = _interpret_conflict(
                regimes['long_term'], directions['long_term'],
                regimes['short_term'], directions['short_term'],
                regimes.get('medium_term', 'UNKNOWN'), directions.get('medium_term')
            )
            conflicts.append(TierConflict(
                tiers=['long_term', 'short_term'],
                conflict_type='DIRECTION_CONFLICT',
                interpretation=interp,
            ))

    # Long vs medium conflict
    if directions.get('long_term') and directions.get('medium_term'):
        if directions['long_term'] != directions['medium_term']:
            conflicts.append(TierConflict(
                tiers=['long_term', 'medium_term'],
                conflict_type='DIRECTION_CONFLICT',
                interpretation=_interpret_lt_mt_conflict(
                    directions['long_term'], directions['medium_term'],
                    regimes['medium_term']
                ),
            ))

    result.conflicts = conflicts

    # Description
    result.description = _build_description(regimes, directions)

    # Suggested stop tier (Section 13.5)
    result.suggested_stop_tier = _suggest_stop_tier(regimes)

    return result


def _interpret_conflict(lt_regime, lt_dir, st_regime, st_dir,
                        mt_regime, mt_dir) -> str:
    """Generate interpretation string for long-term vs short-term conflict."""
    if lt_dir == 'UPTREND' and st_dir == 'DOWNTREND':
        if mt_regime == 'OTHERS':
            return ("Consolidation within uptrend — short-term counter-trend move. "
                    "Wait for medium-term to resolve before acting.")
        return ("Pullback within uptrend — potential buy setup once short-term "
                "downtrend exhausts.")
    elif lt_dir == 'DOWNTREND' and st_dir == 'UPTREND':
        return ("Counter-trend rally within downtrend — long-term bias still bearish. "
                "Short-term signal should be treated with lower conviction.")
    return "Direction conflict between long-term and short-term tiers."


def _interpret_lt_mt_conflict(lt_dir, mt_dir, mt_regime) -> str:
    """Generate interpretation for long vs medium conflict."""
    if lt_dir == 'UPTREND' and mt_dir == 'DOWNTREND':
        if mt_regime == 'BREAK':
            return "Medium-term breakdown within long-term uptrend — watch for long-term trendline test."
        return "Medium-term pullback within long-term uptrend."
    elif lt_dir == 'DOWNTREND' and mt_dir == 'UPTREND':
        return "Medium-term rally within long-term downtrend — potential bear flag."
    return "Direction conflict between long-term and medium-term tiers."


def _build_description(regimes, directions) -> str:
    """Build a human-readable description of the multi-tier state."""
    parts = []
    for tier_name in ['long_term', 'medium_term', 'short_term']:
        regime = regimes.get(tier_name, 'UNKNOWN')
        direction = directions.get(tier_name)
        label = tier_name.replace('_', '-')
        if direction:
            parts.append(f"{label}: {direction.lower()}")
        elif regime == 'OTHERS':
            parts.append(f"{label}: sideways/choppy")
        elif regime == 'BREAK':
            parts.append(f"{label}: breakout/breakdown")
        else:
            parts.append(f"{label}: {regime.lower()}")

    return ', '.join(parts)


def _suggest_stop_tier(regimes) -> str:
    """Suggest which tier to use for stop placement (Section 13.5)."""
    # If trading on short-term signals, use medium-term for stops
    if regimes.get('short_term') == 'TREND':
        return 'medium_term'
    # If medium-term trend, use long-term for stops
    if regimes.get('medium_term') == 'TREND':
        return 'long_term'
    # Default
    return 'medium_term'
