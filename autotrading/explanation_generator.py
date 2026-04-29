"""
explanation_generator.py

Generates a comprehensive step-by-step HTML explanation for each 15-min chart.
The output is a self-contained HTML file (Plotly embedded via CDN) containing:
  - 6 progressive charts that build up the analysis layer by layer
  - Bullet-point explanations for every signal and trendline decision
  - Plain-English reasoning tied directly to the actual numbers in the analysis

The goal: the reader should be able to open this file and fully understand *why*
the chart looks the way it does, with enough detail to verify the logic themselves.
"""

import sys
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from utils.utils_trendline_engine.types import TierResult
from utils.utils_trendline_engine.config import CONFIG

# Scoring weights (from config)
W_TOUCH = CONFIG['W_TOUCH']
W_RECENCY = CONFIG['W_RECENCY']
W_VOLUME = CONFIG['W_VOLUME']
W_REVERSAL = CONFIG['W_REVERSAL']


# ============================================================================
# Public API
# ============================================================================

def generate_explanation(df: pd.DataFrame,
                         tier_result: TierResult,
                         ticker: str,
                         reference_date: str,
                         progressive_charts: list[tuple[str, str]]) -> str:
    """Generate a self-contained HTML explanation document.

    Args:
        df: OHLCV DataFrame for the 15-min tier.
        tier_result: Completed TierResult for the short_term tier.
        ticker: Ticker symbol.
        reference_date: Analysis reference date string.
        progressive_charts: List of (title, html_fragment) from build_explanation_charts().

    Returns:
        Complete HTML string (self-contained, no external dependencies except Plotly CDN).
    """
    if tier_result is None:
        return _error_html(ticker, reference_date, "No short-term analysis data available.")

    # Pull progressive chart HTML by stage index
    def chart_at(i):
        if i < len(progressive_charts):
            return progressive_charts[i][1]
        return '<p><em>Chart not available.</em></p>'

    sections = []
    sections.append(_section_data_overview(df, tier_result, ticker, reference_date,
                                           chart_html=chart_at(0)))
    sections.append(_section_pivot_detection(df, tier_result, chart_html=chart_at(1)))
    sections.append(_section_regime_classification(df, tier_result))
    sections.append(_section_channel_construction(df, tier_result,
                                                  chart_primary=chart_at(2),
                                                  chart_full=chart_at(3)))
    sections.append(_section_sr_zones(df, tier_result, chart_html=chart_at(4)))
    sections.append(_section_volume_analysis(df, tier_result))

    if tier_result.break_info is not None:
        sections.append(_section_breakout(df, tier_result, chart_html=chart_at(5)))

    if tier_result.fan_lines:
        sections.append(_section_fan_lines(tier_result))

    sections.append(_section_final_verdict(df, tier_result, chart_html=chart_at(5)))

    return _wrap_html(ticker, reference_date, '\n'.join(sections))


def save_explanation(html_content: str, ticker: str, reference_date: str) -> Path:
    """Save the explanation HTML to the autotrading/reports/ folder.

    Returns:
        Path to the saved file.
    """
    output_folder = Path(__file__).resolve().parent / 'reports'
    output_folder.mkdir(parents=True, exist_ok=True)

    date_str = reference_date.replace('-', '') if reference_date else \
        datetime.now().strftime('%Y%m%d')
    file_path = output_folder / f'explanation_{ticker}_{date_str}.html'

    with open(str(file_path), 'w', encoding='utf-8') as f:
        f.write(html_content)

    print(f"  Explanation saved to: {file_path}")
    return file_path


# ============================================================================
# Section builders
# ============================================================================

def _section_data_overview(df, tier_result, ticker, reference_date,
                            chart_html='') -> str:
    n_bars = len(df)
    if not df.empty:
        t_col = pd.to_datetime(df['t'])
        start_dt = t_col.iloc[0].strftime('%Y-%m-%d %H:%M')
        end_dt = t_col.iloc[-1].strftime('%Y-%m-%d %H:%M')
        price_high = df['high'].max()
        price_low = df['low'].min()
        price_range_pct = (price_high - price_low) / price_low * 100
        latest_close = df['close'].iloc[-1]
    else:
        start_dt = end_dt = 'N/A'
        price_high = price_low = price_range_pct = latest_close = 0

    scale_reason = (
        "Log scale was selected because the price range spans more than 20% — "
        "log scale keeps percentage moves visually proportional at both price extremes."
        if tier_result.scale_mode == 'log'
        else "Arithmetic scale was used — price range is within 20% so linear spacing is appropriate."
    )

    atr_pct = (tier_result.atr_14 / latest_close * 100) if latest_close > 0 else 0

    html = _section_start('sec-1', '1. Data Overview')
    html += f'''
<p>This chart covers the last <strong>20 trading days</strong> of 15-minute bars
(approximately 520 bars). The analysis anchors all percentage thresholds to
<strong>ATR(14)</strong> so they scale automatically with recent volatility.</p>

<ul>
  <li><strong>Ticker:</strong> {ticker}</li>
  <li><strong>Reference date:</strong> {reference_date}</li>
  <li><strong>Bar count:</strong> {n_bars:,} bars (15-min intervals)</li>
  <li><strong>Date range:</strong> {start_dt} → {end_dt}</li>
  <li><strong>Price range:</strong> ${price_low:.2f} – ${price_high:.2f}
      ({price_range_pct:.1f}% span)</li>
  <li><strong>Latest close:</strong> ${latest_close:.2f}</li>
  <li><strong>ATR(14):</strong> ${tier_result.atr_14:.3f} per bar
      ({atr_pct:.2f}% of price) — used throughout as the volatility yardstick</li>
  <li><strong>Scale mode:</strong> {tier_result.scale_mode.upper()} — {scale_reason}</li>
</ul>

<p><em>The chart below shows the raw price bars before any analysis overlays are added.</em></p>
{chart_html}
'''
    html += _section_end()
    return html


def _section_pivot_detection(df, tier_result, chart_html='') -> str:
    pivot_window = CONFIG['PIVOT_WINDOW']['short_term']
    atr_mult = CONFIG['ATR_SWING_MULTIPLIER']['short_term']
    min_sep = CONFIG['MIN_PIVOT_SEPARATION']['short_term']
    swing_atr = CONFIG['SWING_ATR_MULTIPLE']['short_term']
    min_span = CONFIG['MIN_CHANNEL_SPAN']['short_term']

    highs = sorted(tier_result.pivot_highs, key=lambda p: p.bar_index)
    lows = sorted(tier_result.pivot_lows, key=lambda p: p.bar_index)

    def pivot_rows(pivots, label):
        if not pivots:
            return f'<li><em>No {label} found.</em></li>'
        rows = []
        for i, p in enumerate(pivots):
            ts = pd.Timestamp(p.timestamp).strftime('%m/%d %H:%M') \
                if p.timestamp else f'bar {p.bar_index}'
            vol_str = (f', vol ratio {p.volume_ratio:.2f}×'
                       if p.volume_ratio > 0 else '')
            chg_str = ''
            if i > 0 and p.volume_change_vs_prior != 0:
                direction = '↑' if p.volume_change_vs_prior > 0 else '↓'
                chg_str = f' ({direction}{abs(p.volume_change_vs_prior):.0f}% vs prior)'
            rows.append(
                f'<li>Bar {p.bar_index} — {ts}: <strong>${p.price:.2f}</strong>'
                f'{vol_str}{chg_str}</li>'
            )
        return '\n'.join(rows)

    html = _section_start('sec-2', '2. Step 1: Pivot Detection')
    html += f'''
<p>Pivots are the local turning points the engine uses as anchors for trendlines and
support/resistance zones. The detection follows <strong>Grimes's three-order hierarchy</strong>
— only first-order pivots (the most significant local extremes) are used here.</p>

<h3>Detection Rules (15-min tier parameters)</h3>
<ul>
  <li><strong>Window:</strong> ±{pivot_window} bars — a high is a pivot only if it is
      strictly greater than all bars within {pivot_window} bars on each side
      (similarly for lows).</li>
  <li><strong>ATR confirmation:</strong> The price swing from the previous pivot of the
      opposite type must be ≥ {atr_mult}× ATR(14) = at least
      ${atr_mult * tier_result.atr_14:.3f}. This filters micro-wiggles that are not
      meaningful swings.</li>
  <li><strong>Alternation:</strong> Pivots must strictly alternate high → low → high →
      … The zigzag is enforced so consecutive same-side pivots are impossible.</li>
  <li><strong>Minimum separation:</strong> Same-side pivots must be ≥ {min_sep} bars
      apart to prevent clusters of nearby pivots being treated as distinct turning
      points.</li>
  <li><strong>Intervening swing:</strong> The counterswing between two same-side pivots
      must be ≥ {swing_atr}× ATR(14) ≈ ${swing_atr * tier_result.atr_14:.3f} — ensures
      "open water" between pivots, ruling out minor retracements.</li>
  <li><strong>Channel span:</strong> The full set of anchors must span ≥ {min_span} bars
      so the trendline is not based on a tiny, unrepresentative window.</li>
</ul>

<h3>Pivot Highs Found ({len(highs)})</h3>
<ul>
{pivot_rows(highs, 'pivot highs')}
</ul>

<h3>Pivot Lows Found ({len(lows)})</h3>
<ul>
{pivot_rows(lows, 'pivot lows')}
</ul>

<details>
  <summary>Why some candidates are rejected</summary>
  <ul>
    <li>A local peak that has a neighbour within {pivot_window} bars which is equally
        high or higher → fails the strict inequality window test.</li>
    <li>A peak where the preceding swing from the nearest low is smaller than
        ${atr_mult * tier_result.atr_14:.3f} (the ATR threshold) → rejected as noise.</li>
    <li>Two highs too close together (gap &lt; {min_sep} bars) → only the most extreme
        of the cluster is kept.</li>
  </ul>
</details>

<p><em>The chart below adds these pivot markers (▼ for highs in red, ▲ for lows in green)
on top of the raw bars.</em></p>
{chart_html}
'''
    html += _section_end()
    return html


def _section_regime_classification(df, tier_result) -> str:
    regime = tier_result.regime
    if regime is None:
        return _section_start('sec-3', '3. Step 2: Regime Classification') + \
               '<p><em>No regime result available.</em></p>' + _section_end()

    min_r2 = CONFIG['MIN_R_SQUARED']
    choppy_ceil = CONFIG['CHOPPY_R_SQUARED_CEILING']
    min_slope_val = CONFIG['MIN_SLOPE']['short_term']
    max_slope_val = CONFIG['MAX_SLOPE']['short_term']
    vol_thresh = CONFIG['VOLUME_TREND_RATIO_THRESHOLD']
    vol_penalty = CONFIG['VOLUME_CONFIDENCE_PENALTY']

    highs = sorted(tier_result.pivot_highs, key=lambda p: p.bar_index)
    lows = sorted(tier_result.pivot_lows, key=lambda p: p.bar_index)

    # Build Dow Theory narrative
    trend_tolerance = CONFIG.get('TREND_TOLERANCE_PCT', 0.0)
    dow_lines = _dow_theory_narrative(highs, lows, regime.trend_direction, trend_tolerance)

    # Slope explanation
    ch = tier_result.trend_channel
    slope_pct_str = '—'
    slope_check = '—'
    steep_note = ''
    if ch and ch.primary_line:
        mid_price = df['close'].iloc[len(df) // 2] if not df.empty else 1
        slope_abs = ch.primary_line.slope
        slope_pct = abs(slope_abs / mid_price) * 100
        slope_pct_str = f'{slope_pct:.4f}% per bar'
        min_pct = min_slope_val * 100
        max_pct = max_slope_val * 100
        if slope_pct < min_pct:
            slope_check = (f'<span class="fail">FAIL</span> — {slope_pct:.4f}% &lt; '
                           f'min {min_pct:.3f}% — price is not moving meaningfully')
        elif slope_pct > max_pct:
            slope_check = (f'<span class="warn">STEEP</span> — {slope_pct:.4f}% &gt; '
                           f'max {max_pct:.2f}% — trendline is unsustainably steep '
                           f'(steep_flag = True)')
            steep_note = ('<li><span class="warn">Steep trendline warning:</span> Slopes '
                          f'above {max_pct:.2f}%/bar rarely persist. A secondary, shallower '
                          'channel may be drawn to show a more sustainable rate of ascent.</li>')
        else:
            slope_check = (f'<span class="pass">PASS</span> — {slope_pct:.4f}% is within '
                           f'[{min_pct:.3f}%, {max_pct:.2f}%]')

    # R² explanation
    r2_val = regime.r_squared
    r2_check = _badge(r2_val >= min_r2, f'{r2_val:.3f}')
    r2_note = ''
    if r2_val < choppy_ceil:
        r2_note = ('R² below 0.30 classifies the market as CHOPPY — pivots exist but '
                   'they do not follow a coherent linear trend.')
    elif r2_val < min_r2:
        r2_note = ('R² between 0.30 and 0.50 is TRANSITIONAL — some structure present '
                   'but not enough linearity to call a confident trend.')

    # Volume narrative
    vol_ratio = regime.volume_trend_ratio
    if regime.volume_confirmed is True:
        vol_verdict = (f'<span class="pass">CONFIRMED</span> — with-trend volume is '
                       f'{vol_ratio:.2f}× counter-trend volume (threshold ≥ {vol_thresh}×). '
                       'Buying/selling pressure aligns with the price direction.')
        vol_penalty_str = 'No confidence penalty applied.'
    elif regime.volume_confirmed is False:
        low_thresh = vol_thresh * (1 - vol_penalty * 2)
        vol_verdict = (f'<span class="fail">DIVERGENT</span> — with-trend volume is only '
                       f'{vol_ratio:.2f}× counter-trend (threshold ≥ {vol_thresh}×). '
                       f'Volume is not expanding on the dominant legs.')
        vol_penalty_str = (f'Confidence reduced by {vol_penalty * 100:.0f}% '
                           f'(from {regime.confidence + vol_penalty:.2f} → {regime.confidence:.2f}).')
    else:
        vol_verdict = (f'<span class="warn">INCONCLUSIVE</span> — with-trend volume ratio '
                       f'{vol_ratio:.2f}× (between the confirmation threshold {vol_thresh:.2f}× '
                       f'and the divergence floor).')
        vol_penalty_str = 'No confidence penalty; inconclusive volume is non-blocking.'

    html = _section_start('sec-3', '3. Step 2: Regime Classification')
    html += f'''
<p>Regime classification determines the overall market condition. The engine evaluates
in strict priority order: <strong>TREND → BREAK → OTHERS</strong>. A TREND is only
declared if all four criteria below pass simultaneously.</p>

<h3>Criterion 1: Dow Theory Pivot Sequence</h3>
<p>An uptrend requires higher highs <em>and</em> higher lows; a downtrend requires
lower lows and lower highs. A tolerance of {trend_tolerance * 100:.2f}% is applied —
a pivot may be up to {trend_tolerance * 100:.2f}% below the previous same-side pivot
and still count as "higher" (catches minor pullbacks without breaking the trend
classification).</p>
<ul>
{dow_lines}
</ul>

<h3>Criterion 2: Linear Regression Fit (R²)</h3>
<ul>
  <li>R² of primary-side pivots: {r2_check} (threshold: ≥ {min_r2})</li>
  {f'<li>{r2_note}</li>' if r2_note else ''}
  <li>R² measures how well the pivots cluster around a straight line. A low R² means
      the swings are erratic — the "trend" would just be connecting random noise.</li>
</ul>

<h3>Criterion 3: Slope Significance</h3>
<ul>
  <li>Primary trendline slope: {slope_pct_str}</li>
  <li>Slope check: {slope_check}</li>
  <li>The minimum slope (0.005%/bar) prevents a nearly horizontal line from being
      declared a trend. A flat channel is SIDEWAYS, not a trend.</li>
  {steep_note}
</ul>

<h3>Criterion 4: Volume Confirmation</h3>
<ul>
  <li>Volume verdict: {vol_verdict}</li>
  <li>{vol_penalty_str}</li>
  <li>Volume is <em>non-blocking</em> — it adjusts confidence but does not on its own
      flip the regime to OTHERS. This follows Pring's framework: volume divergence is
      a warning, not an immediate regime change signal.</li>
</ul>

<h3>Final Verdict</h3>
<ul>
  <li><strong>Regime:</strong> {regime.state}
      {f'({regime.trend_direction})' if regime.trend_direction else ''}
      {f'— sub-type: {regime.sub_type}' if regime.sub_type else ''}</li>
  <li><strong>Confidence:</strong> {regime.confidence:.2f}
      (1.0 = fully confirmed, ≥0.70 = high conviction)</li>
  <li><strong>R²:</strong> {r2_val:.3f}</li>
  {f'<li><strong>Trend starts at bar:</strong> {regime.trend_start_bar_index}</li>'
     if regime.trend_start_bar_index is not None else ''}
</ul>
'''
    html += _section_end()
    return html


def _section_channel_construction(df, tier_result,
                                   chart_primary='', chart_full='') -> str:
    ch = tier_result.trend_channel
    if ch is None:
        return (
            _section_start('sec-4', '4. Step 3: Trendline Channel') +
            '<p><em>No trend channel available (regime is OTHERS or INSUFFICIENT_DATA).</em></p>' +
            _section_end()
        )

    primary = ch.primary_line
    opposite = ch.opposite_line

    # Primary line anchor detail
    primary_anchors = _anchor_list(primary)

    # Opposite line anchor detail
    opp_anchors = _anchor_list(opposite) if opposite else '<em>Not available.</em>'

    # Slope sign
    direction_word = 'rising' if (primary.slope > 0) else 'falling'

    # Geometry explanation
    geom = ch.channel_geometry
    geom_expl = _geometry_explanation(geom)

    # Width
    width_pct = ch.width_pct
    min_w = CONFIG['MIN_WIDTH_PCT']['short_term']
    max_w = CONFIG['MAX_WIDTH_PCT']['short_term']
    min_atr = CONFIG['MIN_WIDTH_ATR_MULTIPLE']
    max_atr = CONFIG['MAX_WIDTH_ATR_MULTIPLE']
    width_atr = ch.width_atr
    width_status_badge = _badge(ch.width_status == 'VALID', ch.width_status)

    # Price position
    pos_html = ''
    if ch.current_price_position:
        pos = ch.current_price_position
        pos_html = (
            f'<li><strong>Current price position:</strong> {pos.zone} — '
            f'{pos.pct_within_channel:.0f}% of the way from the lower line to the '
            f'upper line (0% = at lower boundary, 100% = at upper boundary). '
            f'Current price: ${pos.price:.2f}.</li>'
        )

    # R² of primary line
    r2_primary = getattr(primary, 'r_squared', 0.0)

    html = _section_start('sec-4', '4. Step 3: Trendline Channel')
    html += f'''
<p>The channel is built using a <strong>two-pass approach</strong>:</p>
<ol>
  <li><strong>Pass 1a (primary line):</strong> Linear regression through the
      primary-side pivots (highs for uptrend, lows for downtrend), then the line is
      shifted so it passes through — but does not cut into — the most extreme pivot.</li>
  <li><strong>Pass 1b (opposite line):</strong> A parallel line at the same slope,
      anchored to the most extreme opposite-side pivot (low for uptrend,
      high for downtrend).</li>
  <li><strong>Pass 2 (geometry validation):</strong> The residual scatter between the
      two lines is examined to classify whether the channel is parallel, wedging,
      broadening, or triangular.</li>
</ol>

<h3>Primary Trendline</h3>
<ul>
  <li><strong>Role:</strong> {primary.role or 'SUPPORT (uptrend) / RESISTANCE (downtrend)'}</li>
  <li><strong>Direction:</strong> {direction_word.title()} — slope =
      {primary.slope:.4f} price units per bar</li>
  <li><strong>R² of regression fit:</strong> {r2_primary:.3f}
      (how tightly the pivots cluster around the line)</li>
  <li><strong>Construction method:</strong> {primary.construction_method}</li>
  <li><strong>Steep flag:</strong> {'⚠ YES — line slope exceeds max threshold' if primary.steep_flag else 'No'}</li>
  <li><strong>Anchor points used:</strong>
    <ul>
      {primary_anchors}
    </ul>
  </li>
</ul>

<p><em>The chart below shows the primary trendline only, without the opposite line.
This lets you see which pivots anchor the primary fit and how closely they align.</em></p>
{chart_primary}

<h3>Opposite (Parallel/Bounding) Line</h3>
<ul>
  <li><strong>Anchor point:</strong>
    <ul>
      {opp_anchors}
    </ul>
  </li>
  <li>The opposite line is placed at the same slope as the primary line and
      shifted to just touch — without being exceeded by — the most extreme
      opposite-side pivot. This defines the far boundary of the channel.</li>
</ul>

<h3>Channel Geometry</h3>
<ul>
  <li><strong>Detected geometry:</strong> <strong>{geom}</strong></li>
  <li>{geom_expl}</li>
  {f'<li><strong>Resolution bias:</strong> {ch.resolution_bias}</li>'
     if ch.resolution_bias else ''}
</ul>

<h3>Channel Width</h3>
<ul>
  <li><strong>Width:</strong> {width_pct:.1f}% of midpoint price</li>
  <li><strong>Width in ATR units:</strong> {width_atr:.1f}× ATR(14)</li>
  <li><strong>Valid range:</strong> {min_w:.1f}% – {max_w:.1f}% (percentage check) |
      {min_atr:.1f}× – {max_atr:.1f}× ATR (volatility cross-check)</li>
  <li><strong>Status:</strong> {width_status_badge}</li>
  <li>A channel that is too narrow (< {min_w}%) is likely fitting noise rather than
      meaningful structure. One that is too wide (> {max_w}%) may be catching
      multiple distinct trend phases.</li>
  {pos_html}
</ul>

<p><em>The chart below adds the opposite line, completing the full channel.</em></p>
{chart_full}
'''
    html += _section_end()
    return html


def _section_sr_zones(df, tier_result, chart_html='') -> str:
    zones = tier_result.support_resistance_zones
    min_score = CONFIG['MIN_ZONE_SCORE']
    min_touches = CONFIG['MIN_ZONE_TOUCHES']
    tol_pct = CONFIG['ZONE_TOLERANCE_PCT']['short_term']
    tol_atr = CONFIG['ZONE_TOLERANCE_ATR_MULTIPLE']
    decay_window = CONFIG['ZONE_DECAY_WINDOW']['short_term']

    zone_detail = ''
    if zones:
        zone_detail = '<h3>Active S/R Zones (sorted by score)</h3>'
        for z in sorted(zones, key=lambda x: -x.zone_score):
            badge = '🟦 Support' if z.zone_type == 'SUPPORT' else '🟧 Resistance'
            reversal_note = (' — <span class="warn">role reversal</span>: '
                             'this level previously acted as the opposite type' if z.role_reversal else '')
            weakened_note = ' — <span class="warn">weakened</span> (3+ touches reduce zone strength)' \
                if z.weakened else ''

            # Score breakdown: reconstruct approximate components
            touch_component = z.touch_count * W_TOUCH
            reversal_component = W_REVERSAL if z.role_reversal else 0
            remaining = z.zone_score - touch_component - reversal_component
            # remaining ≈ recency + volume (can't separate exactly without raw data)
            vol_note = (f' | avg volume at touches: {z.avg_volume_ratio_at_touches:.2f}× avg vol'
                        if z.avg_volume_ratio_at_touches != 1.0 else '')

            zone_detail += f'''
<div class="zone-card">
  <strong>{badge}: ${z.midpoint:.2f}</strong>
  (zone ${z.lower:.2f} – ${z.upper:.2f}, band width {(z.upper - z.lower) / z.midpoint * 100:.2f}%)
  {reversal_note}{weakened_note}
  <ul>
    <li>Touches: <strong>{z.touch_count}</strong>
        (minimum required: {min_touches})</li>
    <li>Zone age: {z.age_bars} bars since formation</li>
    <li>Score breakdown:
      <ul>
        <li>Touch component: {z.touch_count} × {W_TOUCH} = <strong>{touch_component:.1f}</strong></li>
        {'<li>Role reversal bonus: 1 × ' + str(W_REVERSAL) + ' = <strong>' + str(reversal_component) + '.0</strong></li>' if z.role_reversal else ''}
        <li>Recency + volume components: ≈ {remaining:.2f}
            (exact split not stored — depends on how recently the touches occurred
            and volume at each touch)</li>
        <li><strong>Total score: {z.zone_score:.2f}</strong>
            (threshold to appear: ≥ {min_score})</li>
      </ul>
    </li>
    {f'<li>Average volume at touches: {z.avg_volume_ratio_at_touches:.2f}× 20-bar average{vol_note}</li>' if z.avg_volume_ratio_at_touches != 1.0 else ''}
  </ul>
</div>
'''
    else:
        zone_detail = '<p><em>No S/R zones met the minimum score threshold.</em></p>'

    html = _section_start('sec-5', '5. Step 4: Support & Resistance Zones')
    html += f'''
<p>S/R zones are horizontal price bands where the market has repeatedly reversed.
The engine clusters nearby pivot prices and scores each cluster on four dimensions:</p>

<h3>Scoring Formula</h3>
<ul>
  <li><strong>Touch count</strong> × {W_TOUCH} — each time price tests the zone from
      above (resistance) or below (support) without decisively breaking through, the
      zone gains {W_TOUCH} points.</li>
  <li><strong>Recency</strong> × {W_RECENCY} — more recent touches score higher.
      Zones not retested within {decay_window} bars have their score halved
      (time decay, per Bulkowski).</li>
  <li><strong>Volume at touches</strong> × {W_VOLUME} — high-volume reversals at
      the zone confirm it is a meaningful level (not thin-market noise).</li>
  <li><strong>Role reversal bonus</strong> × {W_REVERSAL} — if the level previously
      acted as support and now acts as resistance (or vice versa), it scores an extra
      {W_REVERSAL} points. Former support becomes resistance after a breakdown,
      and vice versa — a well-established concept in technical analysis.</li>
</ul>

<h3>Acceptance Criteria</h3>
<ul>
  <li>Minimum score: ≥ {min_score}</li>
  <li>Minimum touches: ≥ {min_touches}</li>
  <li>Zone clustering tolerance: {tol_pct}% of price (or {tol_atr}× ATR,
      whichever is larger) — pivots within this band are grouped into one zone.</li>
  <li>Zones weaken by 10% per touch beyond the 3rd (0.90^(touches-2) multiplier)
      — repeated tests erode the zone's resistance to future breakouts.</li>
</ul>

{zone_detail}

<p><em>The chart below adds S/R zone bands to the full channel. Gray bands are support;
orange bands are resistance.</em></p>
{chart_html}
'''
    html += _section_end()
    return html


def _section_volume_analysis(df, tier_result) -> str:
    va = tier_result.volume_analysis
    regime = tier_result.regime
    ch = tier_result.trend_channel
    vol_thresh = CONFIG['VOLUME_TREND_RATIO_THRESHOLD']
    climax_mult = CONFIG['VOLUME_CLIMAX_MULTIPLIER']

    # Trend volume
    if va is not None:
        ratio = va.volume_trend_ratio
        confirmed = va.volume_confirmed
        interp = va.volume_trend_interpretation
    elif regime is not None:
        ratio = regime.volume_trend_ratio
        confirmed = regime.volume_confirmed
        interp = ''
    else:
        ratio = 0.0
        confirmed = None
        interp = ''

    if confirmed is True:
        vol_badge = '<span class="pass">CONFIRMED</span>'
    elif confirmed is False:
        vol_badge = '<span class="fail">DIVERGENT</span>'
    else:
        vol_badge = '<span class="warn">INCONCLUSIVE</span>'

    # Pivot-level divergence
    pvd_html = ''
    pvd = (va.pivot_volume_divergence if va else None) or \
          (ch.volume_divergence if ch else None)
    if pvd and pvd.divergence_warning != 'NONE':
        color = 'fail' if pvd.divergence_warning == 'SIGNIFICANT' else 'warn'
        pvd_html = f'''
<h3>Pivot-Level Volume Divergence</h3>
<p>Volume divergence occurs when successive pivots in the trend direction show
<em>decreasing</em> volume — price is still making new highs/lows but fewer
participants are driving those moves. This is a classic warning from Pring.</p>
<ul>
  <li><strong>Divergence warning:</strong>
      <span class="{color}">{pvd.divergence_warning}</span>
      ({pvd.divergence_count} consecutive divergent pivot pair(s))</li>
  <li>The "VD" red flags on the chart mark the specific pivots where volume
      was lower than the prior same-side pivot.</li>
  {''.join(f'<li>Pivot ${d.get("price", 0):.2f}: volume ratio {d.get("volume_ratio", 0):.2f}×, '
           f'prior pivot vol {d.get("prior_pivot_volume", 0):.0f} — '
           f'{"divergent ⚠" if d.get("divergence") else "OK"}</li>'
           for d in pvd.details) if pvd.details else ''}
</ul>
'''

    # OBV analysis
    obv_html = ''
    obv = (va.obv_analysis if va else None) or (ch.obv_analysis if ch else None)
    if obv and obv.obv_slope_direction:
        joint_txt = ''
        if obv.joint_break == 'CONFIRMED':
            joint_txt = ('<li><span class="fail">Joint break CONFIRMED:</span> both the '
                         'price trendline and the OBV trendline have been breached. '
                         'This is a strong signal — OBV confirms the price break is '
                         'backed by real money flow, not just a wick.</li>')
        elif obv.joint_break == 'OBV_LEADING':
            joint_txt = ('<li><span class="warn">OBV leading:</span> the OBV trendline '
                         'has broken before the price trendline. This is an early warning '
                         '— watch for the price trendline to follow.</li>')

        obv_html = f'''
<h3>On-Balance Volume (OBV)</h3>
<p>OBV accumulates volume on up-bars and subtracts it on down-bars. Its slope
direction tells us whether money is generally flowing <em>into</em> or <em>out of</em>
the stock over the trend period.</p>
<ul>
  <li><strong>OBV slope direction:</strong> {obv.obv_slope_direction}
      (slope = {obv.obv_slope:.4f} per bar, R² = {obv.obv_r_squared:.3f})</li>
  <li><strong>OBV vs price trend:</strong>
      <span class="{'pass' if obv.obv_confirmation == 'CONFIRMED' else 'fail'}">{obv.obv_confirmation}</span>
      — {"OBV direction matches the price trend direction (healthy confirmation)."
         if obv.obv_confirmation == "CONFIRMED"
         else "OBV direction opposes the price trend — selling pressure underneath rising prices, or buying beneath falling prices."}</li>
  {joint_txt}
  <li>The purple OBV line and its dashed trendline appear in the lower subplot
      of the final chart.</li>
</ul>
'''

    # Climax
    climax_html = ''
    if tier_result.break_info and tier_result.break_info.volume_climax_caution:
        climax_html = f'''
<h3>Volume Climax at Breakout</h3>
<p>The breakout bar had volume exceeding {climax_mult:.0f}× the 20-bar average.
Per Bulkowski's empirical study of thousands of chart patterns, very high breakout
volume <em>triples</em> the failure rate compared to normal-volume breakouts.
The "CLIMAX" star on the chart marks this bar.</p>
<ul>
  <li>Interpretation: exhaustion of buying/selling interest in one bar.
      The move may reverse quickly — treat the breakout with extra caution.</li>
</ul>
'''

    html = _section_start('sec-6', '6. Step 5: Volume Analysis')
    html += f'''
<p>Volume is examined at three levels: trend-wide, pivot-by-pivot, and on-balance
flow. None of these are binary pass/fail — they adjust the <em>confidence</em> in
the regime classification.</p>

<h3>Trend Volume Ratio</h3>
<p>The engine computes average volume on bars moving in the trend direction versus
bars moving against it. A healthy trend should attract more volume on its dominant legs.</p>
<ul>
  <li><strong>With-trend / counter-trend volume ratio:</strong>
      {ratio:.2f}× (threshold for confirmation: ≥ {vol_thresh}×)</li>
  <li><strong>Volume verdict:</strong> {vol_badge}</li>
  {f'<li>{interp}</li>' if interp else ''}
</ul>

{pvd_html}
{obv_html}
{climax_html}
'''
    html += _section_end()
    return html


def _section_breakout(df, tier_result, chart_html='') -> str:
    bi = tier_result.break_info
    if bi is None:
        return ''

    atr_mult = CONFIG['ATR_BREAKOUT_MULTIPLIER']
    vol_mult = CONFIG['VOLUME_BREAKOUT_MULTIPLIER']
    confirm_bars = CONFIG['BREAKOUT_CONFIRM_BARS']['short_term']

    close_badge = _badge(bi.close_filter, 'PASS' if bi.close_filter else 'FAIL')
    atr_badge = _badge(bi.atr_filter, 'PASS' if bi.atr_filter else 'FAIL')
    vol_badge = _badge(bi.volume_filter, 'PASS' if bi.volume_filter else 'FAIL')
    confirmed_badge = _badge(bi.confirmed, 'CONFIRMED' if bi.confirmed else 'NOT CONFIRMED')

    break_bar_note = ''
    if bi.break_bar_index is not None and bi.break_bar_index < len(df):
        ts = pd.Timestamp(df['t'].iloc[bi.break_bar_index]).strftime('%m/%d %H:%M')
        break_bar_note = f'(bar {bi.break_bar_index}, {ts})'

    # Volume filter explanation depends on direction
    if bi.break_type == 'BREAKDOWN':
        vol_filter_expl = (
            'Downside breaks <em>auto-pass</em> the volume filter. Edwards & Magee note '
            'that markets can fall under their own weight on light volume — panicked '
            'selling and low liquidity both cause breakdowns. A high-volume requirement '
            'would miss genuine breakdowns.'
        )
    else:
        vol_filter_expl = (
            f'Upside breakouts require ≥ {vol_mult}× average volume to confirm. '
            'A breakout that attracts normal or below-average volume is suspicious — '
            'there is insufficient conviction to push through overhead supply.'
        )

    html = _section_start('sec-7', '7. Step 6: Breakout / Breakdown Confirmation')
    html += f'''
<p>A regime of <strong>BREAK</strong> means the price has moved decisively beyond a
reference structure (prior channel boundary or key S/R zone). The engine requires
<strong>2 out of 3 filters</strong> to confirm the break.</p>

<h3>Break Details</h3>
<ul>
  <li><strong>Break type:</strong> {bi.break_type}</li>
  <li><strong>Break level:</strong> ${bi.break_level:.2f}</li>
  <li><strong>Reference structure:</strong> {bi.reference_structure}</li>
  <li><strong>Break bar:</strong> {break_bar_note or '—'}</li>
</ul>

<h3>Three-Filter Confirmation (need 2/3)</h3>
<ul>
  <li><strong>Filter 1 — Close filter:</strong> {close_badge}
    <ul>
      <li>The bar's closing price must land <em>beyond</em> the break level. A wick
          through the level without a close beyond it is not a confirmed break —
          sellers/buyers stepped in and forced the close back.</li>
    </ul>
  </li>
  <li><strong>Filter 2 — ATR filter:</strong> {atr_badge}
    <ul>
      <li>The close must exceed the break level by at least {atr_mult}× ATR(14) =
          ${atr_mult * tier_result.atr_14:.3f}. This buffer prevents noise from
          triggering breaks — just barely touching the line does not count.</li>
    </ul>
  </li>
  <li><strong>Filter 3 — Volume filter:</strong> {vol_badge}
    <ul>
      <li>{vol_filter_expl}</li>
    </ul>
  </li>
</ul>

<h3>Confirmation Status</h3>
<ul>
  <li><strong>Filters passed:</strong> {bi.filters_passed}/3</li>
  <li><strong>Confirmed:</strong> {confirmed_badge}</li>
  <li>After the break bar, price must remain beyond the broken level for
      ≥ {confirm_bars} bars to sustain BREAK status. If it retreats, the
      regime reverts to OTHERS.</li>
  <li>The broken level is then re-classified as S/R with the <em>role reversal</em>
      flag set — former support becomes resistance, and vice versa.</li>
</ul>

<p><em>The final chart (below) shows the breakout marker, dotted trendlines
beyond the break point, and the re-classified S/R zone.</em></p>
{chart_html}
'''
    html += _section_end()
    return html


def _section_fan_lines(tier_result) -> str:
    fans = tier_result.fan_lines
    if not fans:
        return ''

    max_fans = CONFIG['MAX_FAN_LINES']
    exhausted = tier_result.fan_exhausted

    fan_items = []
    for i, fan in enumerate(fans):
        anchors = _anchor_list(fan)
        fan_items.append(f'''
<li><strong>Fan line {i + 1}</strong> (slope: {fan.slope:.4f} price/bar)
  <ul>
    <li>Anchor points: <ul>{anchors}</ul></li>
    <li>Each successive fan is flatter than the previous one — the trend is
        decelerating, retesting at increasingly shallow angles.</li>
  </ul>
</li>
''')

    exhausted_note = ''
    if exhausted:
        exhausted_note = '''
<div class="warn-box">
  <strong>Fan Exhausted:</strong> All three fan lines have now been broken.
  Per the fan principle (Edwards &amp; Magee Chapter 14), exhaustion of three
  fans signals a probable trend reversal. The engine reclassifies the regime
  at this point.
</div>
'''

    html = _section_start('sec-8', '8. Fan Principle')
    html += f'''
<p>When the primary trendline breaks but the broader trend structure is still intact,
the engine redraws trendlines at <em>shallower</em> slopes using only the post-break
pivots. This is the <strong>fan principle</strong> — each successive redraw "fans out"
at a decreasing angle.</p>

<ul>
  <li>Maximum fans before exhaustion signal: {max_fans}</li>
  <li>When the third fan line breaks, the engine sets
      <code>fan_exhausted = True</code> and signals a likely trend reversal.</li>
</ul>

<h3>Fan Lines</h3>
<ul>
{''.join(fan_items)}
</ul>

{exhausted_note}
'''
    html += _section_end()
    return html


def _section_final_verdict(df, tier_result, chart_html='') -> str:
    regime = tier_result.regime
    ch = tier_result.trend_channel
    bi = tier_result.break_info
    zones = tier_result.support_resistance_zones

    # Nearest support and resistance
    if not df.empty:
        latest_price = df['close'].iloc[-1]
    else:
        latest_price = 0

    supports = [z for z in zones if z.zone_type == 'SUPPORT' and z.midpoint < latest_price]
    resistances = [z for z in zones if z.zone_type == 'RESISTANCE' and z.midpoint > latest_price]
    nearest_sup = max(supports, key=lambda z: z.midpoint).midpoint if supports else None
    nearest_res = min(resistances, key=lambda z: z.midpoint).midpoint if resistances else None

    # Verdict paragraph
    regime_str = 'unknown'
    dir_str = ''
    if regime:
        regime_str = regime.state
        if regime.trend_direction:
            dir_str = f', direction: {regime.trend_direction}'
        elif regime.sub_type:
            dir_str = f', sub-type: {regime.sub_type}'

    summary = f'The 15-min chart for this period is classified as <strong>{regime_str}{dir_str}</strong>'
    if regime:
        summary += f' with confidence {regime.confidence:.2f}'
    summary += '.'

    if ch and regime and regime.state == 'TREND':
        geom = ch.channel_geometry
        w = ch.width_pct
        pos = ch.current_price_position
        pos_str = f'{pos.zone} ({pos.pct_within_channel:.0f}% through channel)' \
            if pos else '—'
        summary += (f' Price is moving within a <strong>{geom}</strong> channel '
                    f'(width {w:.1f}%), currently in the <strong>{pos_str}</strong>.')

    va_note = ''
    if regime and regime.volume_confirmed is True:
        va_note = ' Volume is <strong>expanding on the dominant legs</strong> — a healthy sign.'
    elif regime and regime.volume_confirmed is False:
        va_note = ' <span class="warn">Volume is diverging</span> — the trend is moving on declining participation.'
    summary += va_note

    # Watch-for bullet
    watch_items = []
    if ch and regime and regime.state == 'TREND':
        lower_price = ch.primary_line.price_at(len(df) - 1) if df is not None else 0
        upper_price = ch.opposite_line.price_at(len(df) - 1) if ch.opposite_line else None

        if regime.trend_direction == 'UPTREND':
            watch_items.append(
                f'A close below the lower channel boundary (~${lower_price:.2f}) with '
                f'elevated volume would suggest the uptrend is breaking down.'
            )
            if nearest_res:
                watch_items.append(
                    f'Nearest resistance at ${nearest_res:.2f} — a decisive close above '
                    f'this level (with volume) would signal continuation strength.'
                )
        elif regime.trend_direction == 'DOWNTREND':
            if upper_price:
                watch_items.append(
                    f'A close above the upper channel boundary (~${upper_price:.2f}) '
                    f'with volume would challenge the downtrend.'
                )
            if nearest_sup:
                watch_items.append(
                    f'Nearest support at ${nearest_sup:.2f} — watch for a volume-backed '
                    f'bounce here, or a breakdown through it.'
                )

    if bi and bi.confirmed:
        watch_items.append(
            f'Post-breakout: the broken {bi.break_level:.2f} level is now '
            f'{"resistance" if bi.break_type == "BREAKDOWN" else "support"} '
            f'(role reversal). A retest of this level is typical before continuation.'
        )

    if tier_result.fan_exhausted:
        watch_items.append(
            'All three fan lines exhausted — high probability of trend reversal. '
            'Monitor for a new pivot structure forming in the opposite direction.'
        )

    watch_html = ''
    if watch_items:
        watch_html = '<h3>What to Watch</h3><ul>' + \
                     ''.join(f'<li>{w}</li>' for w in watch_items) + '</ul>'

    html = _section_start('sec-9', '9. Final Verdict & Key Takeaways')
    html += f'''
<p>{summary}</p>

<h3>Key Takeaways</h3>
<ul>
  <li><strong>Regime:</strong> {regime_str}{dir_str}
      {'— confidence ' + f'{regime.confidence:.2f}' if regime else ''}</li>
  {f'<li><strong>R²:</strong> {regime.r_squared:.3f}</li>' if regime else ''}
  {f'<li><strong>Channel:</strong> {ch.channel_geometry}, width {ch.width_pct:.1f}%, status {ch.width_status}</li>' if ch else ''}
  {f'<li><strong>Current position:</strong> {ch.current_price_position.zone} ({ch.current_price_position.pct_within_channel:.0f}% through channel)</li>' if ch and ch.current_price_position else ''}
  {f'<li><strong>Volume:</strong> {"Confirmed ✓" if regime and regime.volume_confirmed is True else ("Divergent ⚠" if regime and regime.volume_confirmed is False else "Inconclusive")}</li>' if regime else ''}
  {f'<li><strong>Nearest support:</strong> ${nearest_sup:.2f}</li>' if nearest_sup else ''}
  {f'<li><strong>Nearest resistance:</strong> ${nearest_res:.2f}</li>' if nearest_res else ''}
  {f'<li><strong>Breakout:</strong> {bi.break_type} at ${bi.break_level:.2f} — {"confirmed" if bi.confirmed else "not confirmed"}</li>' if bi else ''}
  {f'<li><span class="warn"><strong>Fan principle exhausted</strong> — reversal signal active</span></li>' if tier_result.fan_exhausted else ''}
</ul>

{watch_html}

<p><em>Final chart with all overlays:</em></p>
{chart_html}
'''
    html += _section_end()
    return html


# ============================================================================
# HTML helpers
# ============================================================================

def _section_start(anchor_id: str, title: str) -> str:
    return f'<section id="{anchor_id}">\n<h2>{title}</h2>\n'


def _section_end() -> str:
    return '\n</section>\n<hr>\n'


def _badge(passing: bool, text: str) -> str:
    cls = 'pass' if passing else 'fail'
    return f'<span class="{cls}">{text}</span>'


def _anchor_list(line) -> str:
    if line is None or not line.anchor_points:
        return '<li><em>No anchors recorded.</em></li>'
    items = []
    for ap in line.anchor_points:
        ts = pd.Timestamp(ap.timestamp).strftime('%m/%d %H:%M') \
            if ap.timestamp else f'bar {ap.bar_index}'
        items.append(f'<li>Bar {ap.bar_index} ({ts}): ${ap.price:.2f}</li>')
    return '\n'.join(items)


def _dow_theory_narrative(highs, lows, direction, tolerance: float = 0.0) -> str:
    """Build bullet-point Dow Theory sequence narrative."""
    lines = []

    if not highs and not lows:
        return '<li><em>No pivots available to assess Dow Theory sequence.</em></li>'

    tol_pct = tolerance * 100

    def _hl_pass(curr_price, prev_price):
        return curr_price >= prev_price * (1 - tolerance)

    def _ll_pass(curr_price, prev_price):
        return curr_price <= prev_price * (1 + tolerance)

    if direction == 'UPTREND':
        # Check highs for HH
        if len(highs) >= 2:
            lines.append('<li><strong>Higher Highs (HH) check:</strong>')
            lines.append('<ul>')
            for i in range(1, len(highs)):
                prev_h = highs[i - 1]
                curr_h = highs[i]
                passes = _hl_pass(curr_h.price, prev_h.price)
                if curr_h.price > prev_h.price:
                    arrow = '↑ higher ✓'
                elif passes:
                    pct = (prev_h.price - curr_h.price) / prev_h.price * 100
                    arrow = f'↓ {pct:.2f}% lower but within {tol_pct:.2f}% tolerance ✓'
                else:
                    arrow = '↓ lower ✗'
                lines.append(
                    f'<li>High {i}: ${prev_h.price:.2f} → High {i+1}: '
                    f'${curr_h.price:.2f} {arrow}</li>'
                )
            lines.append('</ul>')
            lines.append('</li>')
        # Check lows for HL
        if len(lows) >= 2:
            lines.append('<li><strong>Higher Lows (HL) check:</strong>')
            lines.append('<ul>')
            for i in range(1, len(lows)):
                prev_l = lows[i - 1]
                curr_l = lows[i]
                passes = _hl_pass(curr_l.price, prev_l.price)
                if curr_l.price > prev_l.price:
                    arrow = '↑ higher ✓'
                elif passes:
                    pct = (prev_l.price - curr_l.price) / prev_l.price * 100
                    arrow = f'↓ {pct:.2f}% lower but within {tol_pct:.2f}% tolerance ✓'
                else:
                    arrow = '↓ lower ✗'
                lines.append(
                    f'<li>Low {i}: ${prev_l.price:.2f} → Low {i+1}: '
                    f'${curr_l.price:.2f} {arrow}</li>'
                )
            lines.append('</ul>')
            lines.append('</li>')
    elif direction == 'DOWNTREND':
        if len(highs) >= 2:
            lines.append('<li><strong>Lower Highs (LH) check:</strong>')
            lines.append('<ul>')
            for i in range(1, len(highs)):
                prev_h = highs[i - 1]
                curr_h = highs[i]
                passes = _ll_pass(curr_h.price, prev_h.price)
                if curr_h.price < prev_h.price:
                    arrow = '↓ lower ✓'
                elif passes:
                    pct = (curr_h.price - prev_h.price) / prev_h.price * 100
                    arrow = f'↑ {pct:.2f}% higher but within {tol_pct:.2f}% tolerance ✓'
                else:
                    arrow = '↑ higher ✗'
                lines.append(
                    f'<li>High {i}: ${prev_h.price:.2f} → High {i+1}: '
                    f'${curr_h.price:.2f} {arrow}</li>'
                )
            lines.append('</ul>')
            lines.append('</li>')
        if len(lows) >= 2:
            lines.append('<li><strong>Lower Lows (LL) check:</strong>')
            lines.append('<ul>')
            for i in range(1, len(lows)):
                prev_l = lows[i - 1]
                curr_l = lows[i]
                passes = _ll_pass(curr_l.price, prev_l.price)
                if curr_l.price < prev_l.price:
                    arrow = '↓ lower ✓'
                elif passes:
                    pct = (curr_l.price - prev_l.price) / prev_l.price * 100
                    arrow = f'↑ {pct:.2f}% higher but within {tol_pct:.2f}% tolerance ✓'
                else:
                    arrow = '↑ higher ✗'
                lines.append(
                    f'<li>Low {i}: ${prev_l.price:.2f} → Low {i+1}: '
                    f'${curr_l.price:.2f} {arrow}</li>'
                )
            lines.append('</ul>')
            lines.append('</li>')
    else:
        lines.append('<li>Regime is not TREND — Dow Theory sequence was not satisfied '
                     '(no consistent HH+HL or LH+LL pattern detected).</li>')

    return '\n'.join(lines) if lines else \
        '<li><em>Insufficient pivots for Dow Theory check.</em></li>'


def _geometry_explanation(geom: str) -> str:
    explanations = {
        'PARALLEL': (
            'The two channel lines run at nearly identical slopes (slope difference &lt; 15%). '
            'Price oscillates between two parallel boundaries — the classic "trend channel". '
            'Breakouts from parallel channels are the most reliable pattern for continuation.'
        ),
        'RISING_WEDGE': (
            'Both lines slope upward but converge — support is rising faster than resistance. '
            'This is a <strong>bearish pattern</strong>: the rally is narrowing, suggesting '
            'buyers are running out of room. Resolution is typically downward.'
        ),
        'FALLING_WEDGE': (
            'Both lines slope downward but converge — resistance is falling faster than support. '
            'This is a <strong>bullish pattern</strong>: the decline is narrowing, suggesting '
            'sellers are losing momentum. Resolution is typically upward.'
        ),
        'BROADENING': (
            'The lines diverge — the channel is widening over time. This signals increasing '
            'volatility and instability. Broadening patterns are notoriously unpredictable; '
            'this is a caution signal.'
        ),
        'ASCENDING_TRIANGLE': (
            'Flat resistance line with a rising support line. This is a <strong>bullish '
            'continuation pattern</strong> — buyers are consistently stepping in at higher '
            'prices while sellers cluster at a fixed ceiling. Breakout above resistance '
            'is the expected resolution.'
        ),
        'DESCENDING_TRIANGLE': (
            'Falling resistance line with a flat support line. This is a <strong>bearish '
            'continuation pattern</strong> — sellers consistently cap rallies at lower '
            'prices while buyers defend a fixed floor. Breakdown below support '
            'is the expected resolution.'
        ),
        'SYMMETRICAL_TRIANGLE': (
            'Both lines converge toward a point — resistance falling, support rising. '
            'This is a <strong>neutral pattern</strong>: the market is coiling toward '
            'a decision. Resolution can be in either direction; wait for the breakout.'
        ),
    }
    return explanations.get(geom, f'Geometry type "{geom}" detected.')


def _wrap_html(ticker: str, reference_date: str, body: str) -> str:
    """Wrap all sections in a full HTML page."""
    nav_links = [
        ('#sec-1', '1. Data Overview'),
        ('#sec-2', '2. Pivot Detection'),
        ('#sec-3', '3. Regime Classification'),
        ('#sec-4', '4. Channel Construction'),
        ('#sec-5', '5. S/R Zones'),
        ('#sec-6', '6. Volume Analysis'),
        ('#sec-7', '7. Breakout (if applicable)'),
        ('#sec-8', '8. Fan Lines (if applicable)'),
        ('#sec-9', '9. Final Verdict'),
    ]
    nav_html = ' | '.join(
        f'<a href="{href}">{label}</a>' for href, label in nav_links
    )

    gen_time = datetime.now().strftime('%Y-%m-%d %H:%M')

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{ticker} 15-Min Chart Explanation — {reference_date}</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
      font-size: 14px;
      line-height: 1.6;
      color: #333;
      max-width: 1100px;
      margin: 0 auto;
      padding: 20px 30px;
    }}
    h1 {{
      background-color: #002366;
      color: white;
      padding: 12px 20px;
      border-radius: 4px;
      font-size: 20px;
    }}
    h2 {{
      color: #002366;
      border-bottom: 2px solid #002366;
      padding-bottom: 4px;
      margin-top: 30px;
    }}
    h3 {{
      color: #444;
      margin-top: 18px;
      font-size: 15px;
    }}
    nav {{
      background: #f0f4ff;
      padding: 10px 16px;
      border-radius: 4px;
      margin-bottom: 24px;
      font-size: 13px;
    }}
    section {{
      margin-bottom: 10px;
    }}
    ul, ol {{
      margin: 6px 0 10px 0;
      padding-left: 22px;
    }}
    li {{
      margin-bottom: 4px;
    }}
    .pass {{
      color: #28a745;
      font-weight: bold;
    }}
    .fail {{
      color: #dc3545;
      font-weight: bold;
    }}
    .warn {{
      color: #d09000;
      font-weight: bold;
    }}
    .warn-box {{
      background: #fff3cd;
      border-left: 4px solid #ffc107;
      padding: 10px 14px;
      margin: 14px 0;
      border-radius: 3px;
    }}
    .zone-card {{
      background: #fafafa;
      border: 1px solid #ddd;
      border-radius: 4px;
      padding: 10px 14px;
      margin: 10px 0;
    }}
    hr {{
      border: none;
      border-top: 1px solid #e0e0e0;
      margin: 30px 0;
    }}
    details summary {{
      cursor: pointer;
      color: #0056b3;
      font-size: 13px;
      margin: 8px 0;
    }}
    footer {{
      font-size: 12px;
      color: #999;
      margin-top: 40px;
      text-align: center;
    }}
  </style>
</head>
<body>

<h1>📈 {ticker} — 15-Min Chart Explanation</h1>
<p><strong>Reference date:</strong> {reference_date} &nbsp;|&nbsp;
   <strong>Generated:</strong> {gen_time}</p>

<nav>
  <strong>Jump to:</strong> {nav_html}
</nav>

<p>This document walks through the complete reasoning behind the trendline chart for
<strong>{ticker}</strong>. Each section explains one step of the analysis, shows which
data triggered each decision, and includes progressive charts so you can see exactly
how each overlay is built on top of the raw price data.</p>

{body}

<footer>
  Auto-generated by TechnicalTrading trendline engine — for internal use only.
  Past analysis does not constitute investment advice.
</footer>

</body>
</html>'''


def _error_html(ticker: str, reference_date: str, message: str) -> str:
    return f'''<!DOCTYPE html>
<html><head><title>{ticker} Explanation — Error</title></head>
<body>
  <h1>{ticker} — {reference_date}</h1>
  <p style="color:red;">{message}</p>
</body></html>'''
