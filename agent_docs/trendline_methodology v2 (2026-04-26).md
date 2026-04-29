# Deterministic Methodology: Trend Channels, Support Lines & Resistance Lines

## Purpose

This document defines a fully deterministic, procedural algorithm for programmatically drawing long-term and short-term trend channels, support lines, and resistance lines for a given US equity ticker. It is designed to be implemented in Python, connected to a market data API (e.g., Interactive Brokers, Yahoo Finance, or similar), and executed without human judgment.

For each ticker, the algorithm produces **three independent analyses** — short-term, medium-term, and long-term — each with its own trend channel, S/R zones, and regime classification. A multi-tier interaction layer then identifies confluence and conflict between the tiers.

Every decision point has explicit numeric thresholds and fallback logic. Where the literature offers ranges, we pick a single default with configurable override.

---

## Table of Contents

1. [Three-Tier Timeframe Structure](#1-three-tier-timeframe-structure)
2. [Chart Scaling](#2-chart-scaling)
3. [Pivot Point Identification](#3-pivot-point-identification)
4. [Market Regime Classification (TREND / BREAK / OTHERS)](#4-market-regime-classification-trend--break--others)
5. [Trend Channel Construction (Two-Pass Approach)](#5-trend-channel-construction-two-pass-approach)
6. [Slope Constraints](#6-slope-constraints)
7. [Channel Width Constraints](#7-channel-width-constraints)
8. [Break Regime: Breakout & Breakdown](#8-break-regime-breakout--breakdown)
9. [Others Regime: Sideways, Choppy & Transitional](#9-others-regime-sideways-choppy--transitional)
10. [Handling Recent Price Data](#10-handling-recent-price-data)
11. [Support & Resistance Line Construction](#11-support--resistance-line-construction)
12. [Fan Principle & Trend Redrawing](#12-fan-principle--trend-redrawing)
13. [Multi-Tier Interaction](#13-multi-tier-interaction)
14. [Output Schema](#14-output-schema)
15. [Edge Cases & Fallbacks](#15-edge-cases--fallbacks)
16. [Configuration Defaults Summary](#16-configuration-defaults-summary)

**Volume analysis is integrated throughout** — not as a separate section but embedded in the sections where it applies: pivot volume recording (§3.7), volume trend confirmation (§4.2 Step 5), volume divergence at channel anchors (§5.9), OBV trend tracking (§5.10), directional breakout volume filters (§8.2), volume within ranges (§9.1), and S/R zone volume scoring (§11.2–11.3).

---

## 1. Three-Tier Timeframe Structure

### 1.1 Overview

Each ticker is analyzed independently across three timeframes. Each tier runs the full pipeline (pivot identification → regime classification → channel/S/R construction) with its own parameters. The three tiers are related by a factor of approximately 4–7×, following Grimes's guideline that time frames should be related by a factor of 3 to 5 for each to provide new information without loss of resolution or unnecessary repetition.

```
SHORT-TERM ──(4×)──▶ MEDIUM-TERM ──(~7×)──▶ LONG-TERM
  15-min                  1-hour                   Daily
```

### 1.2 Tier Definitions

| | Short-Term | Medium-Term | Long-Term |
|---|---|---|---|
| **Bar interval** | 15 minutes | 1 hour (60 minutes) | 1 trading day |
| **Lookback** | 20 trading days | 60 trading days | 260 trading days (~1 year) |
| **Bars in lookback** | ~520 bars (20 × 26) | ~420 bars (60 × 7) | 260 bars |
| **Factor from tier below** | — | 4× (15-min → 60-min) | ~7× (60-min → daily) |
| **What it captures** | Intraday swings, precise entries/exits, next-day stop targets | Multi-day swings, short-term trend channels, swing-trade management | Intermediate trend, multi-week/month channels, position-level context |
| **Typical holding period served** | Intraday to a few days | A few days to a few weeks | A few weeks to a few months |

### 1.3 Bars Per Day Calculation

- **15-minute bars**: US equities regular session 09:30–16:00 ET = 6.5 hours = **26 bars per day**.
- **1-hour bars**: US equities regular session = 7 bars per day (09:30–10:30, 10:30–11:30, 11:30–12:30, 12:30–13:30, 13:30–14:30, 14:30–15:30, 15:30–16:00). Note: the last bar covers only 30 minutes. Data providers may handle this differently; the algorithm should accept whatever the provider returns. Default assumption: **7 bars per day**.
- **Daily bars**: **1 bar per day**.

### 1.4 Data Fields Required Per Bar

```
timestamp, open, high, low, close, volume
```

All pivot calculations use **high** and **low** (wicks), not close, unless explicitly stated otherwise for specific S/R calculations (see Section 11).

### 1.5 Independence of Tiers

Each tier is analyzed **independently** — it has its own pivots, its own regime classification, and its own channel. It is entirely normal (and common) for tiers to show different regimes. For example:

- Long-term: TREND (uptrend) / Medium-term: OTHERS (sideways pullback) / Short-term: TREND (downtrend within pullback)
- Long-term: OTHERS (range) / Medium-term: BREAK (breakout from range) / Short-term: TREND (new uptrend)

The multi-tier interaction layer (Section 13) identifies these confluences and conflicts after all three tiers have been analyzed independently.

---

## 2. Chart Scaling

### 2.1 When to Use Log Scale

- If `(max_price - min_price) / min_price > 0.20` over the lookback window, use **semi-logarithmic (log) scaling** for all price-axis calculations.
- In log scale, all regression, slope, and distance calculations operate on `ln(price)` rather than raw price.
- For short-term and medium-term (15-min and 1-hour), log scale is almost never needed. Default to arithmetic scale.
- For long-term daily analysis (260 days), always check and apply log scale if the threshold is met.

### 2.2 Implementation

```
if (max(highs) - min(lows)) / min(lows) > 0.20:
    prices = ln(prices)  # all subsequent calculations use log prices
    scale_mode = "log"
else:
    scale_mode = "arithmetic"
```

After all line calculations are complete, convert coordinates back to price space via `exp()` if log scale was used.

---

## 3. Pivot Point Identification

### 3.1 Definitions (Grimes's Hierarchy)

Pivots are the foundation of all subsequent analysis. We use Grimes's three-order hierarchy:

- **First-order pivot high**: A bar whose high is higher than the high of the N bars immediately before AND after it.
- **First-order pivot low**: A bar whose low is lower than the low of the N bars immediately before AND after it.
- **Second-order pivot high**: A first-order pivot high that is preceded AND followed by a lower first-order pivot high.
- **Second-order pivot low**: A first-order pivot low that is preceded AND followed by a higher first-order pivot low.
- **Third-order pivot high**: A second-order pivot high that is preceded AND followed by a lower second-order pivot high.
- **Third-order pivot low**: A second-order pivot low that is preceded AND followed by a higher second-order pivot low.

### 3.2 Lookback/Lookahead Window for First-Order Pivots

Use a configurable window `N` on each side:

| Tier | Pivot Window N | Rationale |
|------|---------------|-----------|
| Short-term (15-min) | 3 bars (45 min) | Captures intraday swing points |
| Medium-term (1-hour) | 4 bars (4 hours, ~half a trading day) | Captures multi-hour swing points |
| Long-term (daily) | 5 bars (1 trading week) | Captures multi-day swing points |

A **strict** first-order pivot high at index `i` requires: `high[i] > max(high[i-N:i])` AND `high[i] > max(high[i+1:i+N+1])`

Use **non-strict** inequality (`>=`) for one side only if no pivots are found with strict inequality in a given segment. This prevents the "no pivots found" edge case in flat/choppy markets.

### 3.3 ATR-Based Swing Confirmation

To filter out noise pivots (insignificant wiggles):

1. Compute ATR(14) — 14-bar Average True Range (calculated on the tier's own bar interval).
2. A pivot is **confirmed** only if the swing from the preceding opposite pivot is >= `ATR_SWING_MULTIPLIER × ATR(14)`.

| Tier | ATR_SWING_MULTIPLIER | Rationale |
|------|---------------------|-----------|
| Short-term (15-min) | 0.75 | Intraday swings are naturally smaller relative to ATR |
| Medium-term (1-hour) | 1.0 | Standard threshold |
| Long-term (daily) | 1.5 | Only significant multi-day swings qualify |

3. Pivots that fail this filter are discarded.

### 3.4 Zigzag Alternation Enforcement

After filtering, enforce strict alternation: pivot highs and pivot lows must alternate. If two consecutive pivot highs occur, keep only the higher one. If two consecutive pivot lows occur, keep only the lower one.

### 3.5 Minimum Pivot Count

- To proceed with any trend channel construction, require **at least 3 pivots** on the primary side (lows for uptrend, highs for downtrend) and **at least 1 pivot** on the opposite side.
- If fewer pivots exist after filtering, widen the lookback window by 50% and re-run. If still insufficient, output `status: "INSUFFICIENT_DATA"` and skip channel construction.

### 3.6 Pivot Spacing Constraints

Two pivots close together in time produce unreliable trendlines. Edwards & Magee state: "If your trendline is drawn from two original Bottoms which are very close together in time — say, less than a week apart — it is subject to error." The trendline is only correct if anchor points "have developed as independent wave components of the trend you are trying to define, with a good rally and 'open water' between them."

This requires enforcing three conditions between any two adjacent anchor pivots on the same side:

**Condition A — Minimum Bar Separation:**

| Tier | Min Bars Between Same-Side Pivots | Equivalent Time |
|------|----------------------------------|-----------------|
| Short-term (15-min) | 20 bars | ~5 hours |
| Medium-term (1-hour) | 10 bars | ~1.5 trading days |
| Long-term (daily) | 15 bars | ~3 weeks |

**Condition B — Minimum Intervening Swing ("Open Water"):**

The swing between two same-side pivots must be large enough to constitute a genuine wave. For two pivot lows PL1 and PL2, the rally between them must satisfy:

```
max_high_between(PL1, PL2) - max(PL1.price, PL2.price) >= SWING_ATR_MULTIPLE × ATR(14)
```

| Tier | SWING_ATR_MULTIPLE |
|------|-------------------|
| Short-term (15-min) | 1.0 |
| Medium-term (1-hour) | 1.0 |
| Long-term (daily) | 1.5 |

**Condition C — No Overlap (Open Water Visual Test):**

The bar ranges around each pivot must not directly overlap with the intervening opposite pivot. Specifically, for two pivot lows with an intervening pivot high between them: the highest price in the 3-bar neighborhood of each pivot low must be lower than the pivot high's price. This ensures there was a genuine peak between the lows, not just choppy flat action.

**Minimum Total Channel Span:**

The distance from the first anchor pivot to the last anchor pivot must also meet a minimum span:

| Tier | Min Total Channel Span | Equivalent Time |
|------|----------------------|-----------------|
| Short-term (15-min) | 80 bars | ~3 trading days |
| Medium-term (1-hour) | 30 bars | ~4 trading days |
| Long-term (daily) | 40 bars | ~2 months |

**Practical Data Requirements to Find Pivots:**

| Pivots Needed | Short-Term (15-min) | Medium-Term (1-hour) | Long-Term (Daily) |
|---------------|---------------------|----------------------|-------------------|
| 2+2 (minimum to draw channel) | ~100–200 bars | ~60–120 bars | ~60–100 bars |
| 3+3 (minimum to validate/classify) | ~250–400 bars | ~150–250 bars | ~120–200 bars |

**Note on pivot count vs. classification**: 2+2 pivots (2 lows + 2 highs) is the geometric minimum to draw a channel. 3+3 is the practical minimum to validate the channel and to classify whether it is parallel, converging, or diverging. Bulkowski requires 5 total touches (3 on one side + 2 on the other) for wedge and triangle classification.

### 3.7 Volume Recording at Each Pivot

Every confirmed pivot must record its volume context. This is the foundation for all volume-based analysis in subsequent sections.

For each confirmed pivot, compute and store:

```
pivot.volume_at_pivot = mean(volume[i-1], volume[i], volume[i+1])  # 3-bar average centered on pivot bar
pivot.volume_ratio = pivot.volume_at_pivot / SMA(volume, 20)       # ratio vs 20-bar average volume
```

The 3-bar average smooths single-bar spikes; the ratio normalizes across stocks and time periods.

**Volume change between consecutive same-side pivots:**

For each pair of consecutive pivot highs (PH_n, PH_n+1) or pivot lows (PL_n, PL_n+1):

```
volume_change_pct = (PH_n+1.volume_at_pivot - PH_n.volume_at_pivot) / PH_n.volume_at_pivot × 100
```

Store this as `pivot.volume_change_vs_prior` on each pivot. This powers the volume divergence detection in Section 5.

---

## 4. Market Regime Classification (TREND / BREAK / OTHERS)

### 4.1 Three-State Overview

Before drawing any channels or lines, the algorithm must first classify the current market regime into one of three mutually exclusive states. **Each tier runs this classification independently.**

```
                    ┌─────────────────────┐
                    │  Identify Pivots     │
                    │  (Section 3)         │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │  Check for TREND     │
                    │  (Section 4.2)       │
                    └──────────┬──────────┘
                          ┌────┴────┐
                       YES│         │NO
                    ┌─────▼───┐ ┌───▼─────────┐
                    │ TREND   │ │ Check for    │
                    │ regime  │ │ BREAK        │
                    │ → §5–7  │ │ (Section 4.3)│
                    └─────────┘ └───┬─────────┘
                               ┌────┴────┐
                            YES│         │NO
                         ┌─────▼───┐ ┌───▼─────────┐
                         │ BREAK   │ │ OTHERS      │
                         │ regime  │ │ regime      │
                         │ → §8    │ │ → §9        │
                         └─────────┘ └─────────────┘
```

**TREND**: A directional trend exists — draw trend channels (Sections 5–7).

**BREAK**: No established trend currently holds, but a breakout or breakdown from a prior structure has occurred or is in progress — detect and confirm the break (Section 8).

**OTHERS**: Neither a directional trend nor a break is present — the market is sideways, choppy, or in an ambiguous transitional state — draw horizontal S/R ranges only (Section 9).

The classification is evaluated **in this strict order**: TREND first, then BREAK, then OTHERS. OTHERS is the default fallback.

### 4.2 TREND Detection

A directional trend is confirmed when ALL of the following are true:

**Step 1 — Pivot Sequence (Dow Theory):**

Examine second-order pivots (or third-order if available):

- **Uptrend**: At least 2 consecutive higher pivot lows AND at least 2 consecutive higher pivot highs.
- **Downtrend**: At least 2 consecutive lower pivot highs AND at least 2 consecutive lower pivot lows.

If neither pattern is present → not a TREND, proceed to BREAK check.

**Step 2 — Pivot Spacing (Section 3.6):**

The pivot sequence from Step 1 must satisfy all three spacing constraints (bar separation, intervening swing, no overlap). If the pivots that form the "higher-highs / higher-lows" pattern are too close together or lack open water between them, the pattern is unreliable → not a TREND, proceed to BREAK check.

**Step 3 — Quantitative Confirmation via Linear Regression:**

1. Fit a linear regression to the primary-side pivots (pivot lows for uptrend, pivot highs for downtrend).
2. Compute slope and R².
3. Trend is confirmed if:
   - `|slope|` > `MIN_SLOPE_THRESHOLD` (see Section 6)
   - `R² >= 0.50` (at least 50% of variance explained by a linear relationship)
4. If `R² < 0.50` → not a TREND, proceed to BREAK check.

**Step 4 — Trend Start Point:**

The trend channel starts from the **most recent significant trend change point**:

- The most recent third-order pivot that represents a reversal (e.g., a third-order pivot low after a downtrend marks the start of a potential uptrend).
- If no clear third-order reversal exists, use the most recent second-order pivot where the pivot sequence changes character (from lower-lows to higher-lows, or vice versa).

**Output if TREND:**

```
regime = "TREND"
trend_direction = "UPTREND" | "DOWNTREND"
volume_confirmed = true | false
→ proceed to Section 5 (channel construction)
```

**Step 5 — Volume Trend Confirmation (Non-Blocking):**

After confirming TREND via Steps 1–4, assess whether volume supports the trend. This does NOT change the regime classification — it produces a `volume_confirmed` flag that affects confidence scoring.

Per Edwards & Magee (Ch. 3): "Volume tends to expand as prices move in the direction of the prevailing trend. In a Bull Market, volume increases when prices rise and dwindles as prices decline."

For each swing leg in the trend (alternating between with-trend and counter-trend legs):

```
# For an UPTREND:
with_trend_avg_volume = mean(volume) during up-legs (pivot low → pivot high)
counter_trend_avg_volume = mean(volume) during down-legs (pivot high → pivot low)

volume_trend_ratio = with_trend_avg_volume / counter_trend_avg_volume

if volume_trend_ratio >= 1.10:
    volume_confirmed = True   # Volume expands in trend direction — healthy
elif volume_trend_ratio <= 0.90:
    volume_confirmed = False  # Volume expands AGAINST trend — bearish divergence
else:
    volume_confirmed = null   # Inconclusive
```

For a DOWNTREND, invert: `with_trend_avg_volume` is during down-legs, `counter_trend_avg_volume` is during up-legs.

**Important caveat (Grimes)**: Volume is highly correlated with bar range and volatility. The `volume_confirmed` flag is a quality modifier on the trend, not a gate. A trend with `volume_confirmed: false` is still a TREND for channel-drawing purposes — but the confidence score should be reduced by 15%.

### 4.3 BREAK Detection (Breakout / Breakdown)

If no TREND is detected, check whether a breakout or breakdown is in progress. A BREAK means that price has decisively moved beyond a previously established structure (prior channel, S/R zone, or consolidation boundary).

**Step 1 — Identify the Reference Structure** (in priority order):

a. **Prior trend channel** that is now broken.
b. **Horizontal S/R zone** where price has recently traded and has now moved beyond.
c. **Consolidation boundaries** (range/rectangle formed by clustering pivot highs and lows).

If no reference structure can be identified → classify as OTHERS.

**Step 2 — Confirm the Break** via multi-filter confirmation (detailed in Section 8).

**Step 3 — Time Confirmation** — see Section 8.4 for tier-specific confirmation windows.

**Step 4 — Classify Break Direction:**

- **BREAKOUT**: Price breaks above resistance (upward).
- **BREAKDOWN**: Price breaks below support (downward).

**Output if BREAK:**

```
regime = "BREAK"
break_type = "BREAKOUT" | "BREAKDOWN"
→ proceed to Section 8
```

### 4.4 OTHERS Classification

If neither TREND nor BREAK is detected:

- **SIDEWAYS**: Pivots oscillate within a contained horizontal band. Both regression slopes below `MIN_SLOPE_THRESHOLD`, range below `MAX_WIDTH_PCT`.
- **CHOPPY**: Pivots exist but show no consistent pattern. R² < 0.30 on both sides.
- **TRANSITIONAL**: Market has recently broken a trend (fan exhausted, or reversal confirmed) but has not established a new trend or clear range.
- **INSUFFICIENT_DATA**: Not enough bars or pivots to classify.

**Output if OTHERS:**

```
regime = "OTHERS"
sub_type = "SIDEWAYS" | "CHOPPY" | "TRANSITIONAL" | "INSUFFICIENT_DATA"
→ proceed to Section 9
```

---

## 5. Trend Channel Construction (Two-Pass Approach)

This section applies only when `regime = "TREND"`. The process is identical across all three tiers; only the numeric parameters differ (see Section 16 for tier-specific values).

The core insight: **always start by assuming the channel is parallel, then let the data tell you whether it isn't.** The deviation from parallelism is itself a diagnostic signal.

### 5.1 Pass 1: Primary Trendline (Standard Trend Line)

**For an uptrend** (demand line):

1. Collect all confirmed pivot lows from the trend start point (Section 4.2, Step 4) to present that satisfy spacing constraints (Section 3.6).
2. Require minimum **3 pivot lows** for a valid trendline.
3. Fit a linear regression line through these pivot lows (using bar index as X, price as Y).
4. This regression gives the **slope** and **intercept** as initial estimates.
5. **Anchor adjustment**: Shift the regression line downward so that it passes through (or just touches) the lowest pivot low that is not an outlier. The line must not cut through any price bars between the two outermost anchor points.
   - Specifically: `adjusted_intercept = min(pivot_low_prices - slope * pivot_low_indices)`
   - Then verify: for all bars between the first and last anchor pivot, `low[i] >= slope * i + adjusted_intercept`. If any bar violates this, that bar's low becomes the new anchor and the intercept is recalculated.
6. The regression is used for **slope discovery only**. The final line is anchored to actual pivot points.
7. **Record volume at each anchor point** (Section 3.7). These volume readings power the divergence detection in Section 5.9.

**For a downtrend** (supply line):

1. Collect all confirmed pivot highs from the trend start point.
2. Require minimum **3 pivot highs**.
3. Fit regression, then shift the line **upward** to pass through the highest valid pivot high.
4. `adjusted_intercept = max(pivot_high_prices - slope * pivot_high_indices)`
5. Verify no price bar highs exceed the line between anchor points.

### 5.2 Pass 1: Parallel Channel Line (Assume Parallel)

Following Grimes's three-step method:

1. Take the primary trendline from Step 5.1.
2. Create a parallel line with the **same slope**.
3. Anchor the parallel line to the **single most extreme opposite pivot** between the two outermost anchor points of the primary trendline:
   - For uptrend: anchor to the **highest pivot high** between the first and last anchor pivot lows.
   - For downtrend: anchor to the **lowest pivot low** between the first and last anchor pivot highs.
4. **Critical constraint**: The parallel line must NOT cut through any prices between the two initial anchor points of the primary trendline. If it does, use the next-most-extreme pivot as the anchor.

### 5.3 Pass 2: Parallel Validation (Residual Analysis)

Test whether the parallel line is respected by subsequent opposite-side pivots.

**Step 1 — Compute Residuals:**

```
residual[i] = actual_pivot_price[i] - parallel_line_price_at(pivot_bar_index[i])
```

**Step 2 — Evaluate Residual Pattern:**

```
median_residual = median(residuals)
residual_trend = linear_regression_slope(residuals over time)
```

**Step 3 — Classify:**

```
IF |median_residual| < 0.5 × ATR(14) AND |residual_trend| is small:
    → channel_geometry = "PARALLEL"
    → DONE

ELSE IF median_residual < -0.5 × ATR(14) OR residual_trend is significantly negative:
    → Candidate: CONVERGING (wedge) → Proceed to Step 4

ELSE IF median_residual > 0.5 × ATR(14) OR residual_trend is significantly positive:
    → Check: are pivot lows ALSO breaking below the primary trendline?
        → If YES (both sides expanding): Candidate: DIVERGING (broadening)
        → If NO (only highs expanding, lows hold): Candidate: ACCELERATING
    → Proceed to Step 4

ELSE IF one set of pivots is flat (range < ZONE_TOLERANCE_PCT):
    → Candidate: TRIANGLE → Proceed to Step 4
```

### 5.4 Pass 2: Non-Parallel Channel Construction (When Parallel Fails)

**Step 4 — Independently Fit the Opposite-Side Line:**

1. Collect all opposite-side pivots.
2. Fit a separate linear regression, anchor to the most extreme opposite-side pivot.
3. Compute `slope_primary` and `slope_opposite`.

**Step 5 — Classify Channel Geometry:**

```
slope_diff_pct = abs(slope_primary - slope_opposite) / max(abs(slope_primary), abs(slope_opposite))
```

**5.5a — PARALLEL**: `slope_diff_pct < 0.15` → use parallel line from Pass 1.

**5.5b — CONVERGING (Wedge)**: Both slopes same sign, lines converge.

- Uptrend + upper slope < lower slope → `RISING_WEDGE`, resolution bias `BEARISH` (69% break downside per Bulkowski)
- Downtrend + |upper slope| < |lower slope| → `FALLING_WEDGE`, resolution bias `BULLISH` (92% break upside)
- Compute projected apex: `apex_bar_index = (intercept_opposite - intercept_primary) / (slope_primary - slope_opposite)`
- Validation: Bulkowski requires at least **5 trendline touches** (3 on one side, 2 on the other). With fewer, tag as `POSSIBLE_WEDGE`.

**5.5c — DIVERGING (Broadening)**: Both sides expanding — highs overshoot AND lows break below primary trendline.

- `channel_geometry = "BROADENING"`, resolution bias `BEARISH`
- Volume should be high and irregular throughout (unlike triangles).

**5.5d — ACCELERATION**: Only opposite side expands, primary holds.

- This is NOT a non-parallel channel. Redraw a steeper parallel channel from recent pivots.
- Tag `resolution_bias = "CAUTION_ACCELERATION"`.
- Retain original shallower channel as secondary reference.

**5.5e — TRIANGLE**: One side flat, one side sloped.

- `ASCENDING_TRIANGLE`: Flat resistance + rising support → bullish bias
- `DESCENDING_TRIANGLE`: Flat support + falling resistance → bearish bias
- `SYMMETRICAL_TRIANGLE`: Both sides converging equally → neutral until breakout
- Validation: 5 trendline touches minimum. Breakout typically at 60–75% of distance to apex.

### 5.6 Channel Geometry Decision Table

| Observation | Residual Pattern | Geometry | Resolution Bias |
|------------|-----------------|----------|----------------|
| Pivot highs respect parallel line | \|median\| < 0.5 ATR, no trend | **PARALLEL** | Trend continues |
| Pivot highs falling short, progressively | Negative, worsening residuals | **RISING_WEDGE** / **FALLING_WEDGE** | Counter-trend break expected |
| Pivot highs overshoot, lows hold | Positive residuals, primary intact | **ACCELERATION** | Redraw steeper parallel; caution |
| Both sides expanding | Highs overshoot AND lows break | **BROADENING** | Bearish / instability |
| One side flat, other sloped | One set clusters horizontally | **TRIANGLE** | Depends on which side is flat |

### 5.7 Which Line Matters More

- **Uptrend**: The lower channel line (demand line) is the structurally important line — it defines where buyers defend.
- **Downtrend**: The upper channel line (supply line) is the structurally important line — it defines where sellers cap rallies.

### 5.8 Minimum Data Points Summary

| Purpose | Pivot Lows | Pivot Highs | Total Touches |
|---------|-----------|-------------|---------------|
| Draw a single trendline | 2 | — | 2 |
| Draw a parallel channel | 2 | 1 | 3 |
| Validate parallelism | 2 | 2 | 4 |
| Classify channel type reliably | 3 | 3 | 6 |
| Bulkowski's minimum for wedge/triangle | 3 | 2 (or 2+3) | 5 |

### 5.9 Volume Divergence at Anchor Points

After the channel is constructed, evaluate whether volume at successive anchor points confirms or contradicts the trend. This is one of the most reliable volume signals in the literature (Pring Principle 5, Edwards & Magee Ch. 6).

**For an uptrend channel:**

At each successive pivot high anchor (PH1 → PH2 → PH3), compare volume:

```
# Bearish volume divergence at highs:
# Price makes a higher high, but volume at the high is LOWER than the previous high
if PH_n+1.price > PH_n.price AND PH_n+1.volume_at_pivot < PH_n.volume_at_pivot:
    volume_divergence_highs = True
    # Per E&M: "tab the chart with a red signal" when volume disparity is conspicuous

# Bullish volume confirmation at lows:
# Price makes a higher low on DECLINING volume (sellers exhausting)
if PL_n+1.price > PL_n.price AND PL_n+1.volume_at_pivot < PL_n.volume_at_pivot:
    volume_confirmation_lows = True  # Per Pring Principle 9: "Never short a dull market"
```

**For a downtrend channel** (mirror logic):

```
# Bullish volume divergence at lows:
if PL_n+1.price < PL_n.price AND PL_n+1.volume_at_pivot < PL_n.volume_at_pivot:
    volume_divergence_lows = True  # Selling pressure declining — potential bottom

# Bearish volume confirmation at highs:
if PH_n+1.price < PH_n.price AND PH_n+1.volume_at_pivot < PH_n.volume_at_pivot:
    volume_confirmation_highs = True  # Less buying on rallies — trend is healthy
```

**Counting divergences:**

```
divergence_count = number of consecutive anchor points showing volume divergence
if divergence_count >= 2:
    volume_divergence_warning = "SIGNIFICANT"
    # Multiple divergences compound the signal — per Pring: "the greater the number
    # of divergences, the weaker the technical position"
elif divergence_count == 1:
    volume_divergence_warning = "MILD"
else:
    volume_divergence_warning = "NONE"
```

**Output**: These volume readings are embedded in each anchor point in the JSON output (Section 14) and summarized in the `volume_analysis` block.

### 5.10 On-Balance Volume (OBV) Trend Tracking

OBV provides a cumulative volume-flow indicator that can confirm or diverge from the price trend. Per Pring (Ch. 23): requiring joint trendline breaks in BOTH OBV and price is "probably the best way to interpret OBV."

**OBV Computation:**

```
OBV[0] = 0
for each bar i from 1 to N:
    if close[i] > close[i-1]:
        OBV[i] = OBV[i-1] + volume[i]
    elif close[i] < close[i-1]:
        OBV[i] = OBV[i-1] - volume[i]
    else:
        OBV[i] = OBV[i-1]
```

**OBV Trend Analysis:**

1. Fit a linear regression to OBV over the channel span (same bar range as the price channel).
2. Compute `obv_slope` and `obv_r_squared`.
3. Compare OBV slope direction to price trend direction:

```
if trend_direction == "UPTREND" and obv_slope > 0:
    obv_confirmation = "CONFIRMED"      # OBV rising with price — accumulation
elif trend_direction == "UPTREND" and obv_slope <= 0:
    obv_confirmation = "DIVERGENT"      # OBV flat or falling while price rises — distribution
elif trend_direction == "DOWNTREND" and obv_slope < 0:
    obv_confirmation = "CONFIRMED"      # OBV falling with price — distribution
elif trend_direction == "DOWNTREND" and obv_slope >= 0:
    obv_confirmation = "DIVERGENT"      # OBV rising while price falls — accumulation
```

**OBV Trendline Break Detection:**

Optionally, draw a trendline on OBV itself (same regression + anchor method as price trendlines, Section 5.1, but applied to the OBV series). When the OBV trendline breaks before the price trendline, it is an early warning of trend change. When both break simultaneously, conviction is highest.

```
obv_trendline_broken = True | False
price_trendline_broken = True | False

if obv_trendline_broken and price_trendline_broken:
    joint_break = "CONFIRMED"   # Highest conviction reversal signal (Pring)
elif obv_trendline_broken and not price_trendline_broken:
    joint_break = "OBV_LEADING" # Early warning — watch for price to follow
else:
    joint_break = "NONE"
```

---

## 6. Slope Constraints

### 6.1 Why Constrain Slope

Edwards & Magee: "A very steep line can easily be broken by a brief sideways consolidation." Pring: "The violation of a particularly steep trend is not as significant as that of a more gradual one." Grimes: "It is important to avoid attaching too much significance to a break of a nearly vertical trend line."

### 6.2 Slope Thresholds

All slopes are expressed as **percentage price change per bar**.

| Parameter | Short-Term (15-min) | Medium-Term (1-hour) | Long-Term (Daily) |
|-----------|---------------------|----------------------|-------------------|
| MIN_SLOPE (below = sideways) | 0.005% per bar | 0.007% per bar | 0.01% per bar |
| MAX_SLOPE (above = steep flag) | 0.15% per bar | 0.30% per bar | 0.50% per bar |
| IDEAL_RANGE | 0.01%–0.08% | 0.015%–0.15% | 0.02%–0.20% |

These thresholds are calibrated so that `MIN_SLOPE × lookback_bars ≈ 2.5–3%` across all tiers — i.e., the minimum total price movement to qualify as a trend is roughly consistent regardless of timeframe.

### 6.3 Handling Steep Trendlines

When `slope > MAX_SLOPE`:

1. Still draw the trendline (it defines the current rate of trend).
2. Tag with `steep_flag: true` and `sustainability_warning`.
3. Attempt to draw a secondary, shallower trendline using only the earlier pivot points (excluding the most recent 1–2 pivots that caused the steepening).
4. A break of a steep trendline is expected and should be classified as a **rate-of-trend change**, not necessarily a reversal.

### 6.4 Log-Scale Slope Adjustment

If using log scale (long-term tier only in most cases):

```
log_slope = slope_in_log_space
pct_slope = exp(log_slope) - 1  # convert to percentage for threshold comparison
```

---

## 7. Channel Width Constraints

### 7.1 Why Constrain Width

A channel too wide is meaningless; too narrow will be broken by normal volatility. Grimes: "The purpose of the parallel trend line is to create a trend channel that shows the range of fluctuations that the market has accepted as normal."

### 7.2 Width Measurement

```
width_pct = (upper_line_price - lower_line_price) / ((upper_line_price + lower_line_price) / 2) × 100
```

### 7.3 Width Thresholds

| Parameter | Short-Term (15-min) | Medium-Term (1-hour) | Long-Term (Daily) |
|-----------|---------------------|----------------------|-------------------|
| MIN_WIDTH_PCT | 1.0% | 1.5% | 2.0% |
| MAX_WIDTH_PCT | 15.0% | 20.0% | 30.0% |
| PREFERRED_RANGE | 1.5%–8% | 2%–12% | 3%–15% |

### 7.4 Width Validation Logic

```
if width_pct < MIN_WIDTH_PCT:
    status = "CHANNEL_TOO_NARROW"
elif width_pct > MAX_WIDTH_PCT:
    status = "CHANNEL_TOO_WIDE"
else:
    status = "VALID"
```

### 7.5 ATR-Based Width Cross-Check

Channel width should be between **2× ATR(14)** and **8× ATR(14)** (using each tier's own ATR):

```
if channel_width_price < 2 * atr:
    # Channel too narrow relative to volatility
elif channel_width_price > 8 * atr:
    # Channel too wide relative to volatility
```

---

## 8. Break Regime: Breakout & Breakdown

This section applies when `regime = "BREAK"`.

### 8.1 Break Reference Structures

The break is defined relative to a prior structure, identified in this priority order:

1. **Prior trend channel**: The primary trendline of the most recent valid channel.
2. **Horizontal S/R zone**: The nearest S/R zone in the direction of the break.
3. **Consolidation boundary**: Upper or lower boundary of a recent range.

### 8.2 Multi-Filter Breakout Confirmation (Directional)

A break is confirmed when **at least 2 of the following 3 filters** are satisfied. **Critical asymmetric rule** (Edwards & Magee, Ch. 17): "It takes buying to put prices up, but prices can fall of their own weight." Volume confirmation is required for upside breakouts but NOT for downside breakdowns.

**Filter 1 — Close Filter**: Bar must close beyond the breakout level. For added confidence, 2 consecutive closes.

**Filter 2 — ATR Filter**: Close must be beyond the level by at least `ATR_BREAKOUT_MULTIPLIER × ATR(14)`.

**Filter 3 — Volume Filter (DIRECTIONAL):**

For **BREAKOUT (upward)**: Volume on breakout bar must be >= `VOLUME_BREAKOUT_MULTIPLIER × average_volume(20)`. This filter is **required** — an upside breakout on low volume is suspect.

For **BREAKDOWN (downward)**: Volume is **not required** for confirmation. Downside breaks are valid on normal or even declining volume. However, if volume IS elevated on a breakdown, it adds conviction.

```
if break_type == "BREAKOUT":
    # Volume filter is one of the 3 required filters
    volume_filter_passed = breakout_volume >= VOLUME_BREAKOUT_MULTIPLIER × avg_volume_20
    
elif break_type == "BREAKDOWN":
    # Volume filter is automatically passed — downside breaks don't need volume
    volume_filter_passed = True
    # But record volume for diagnostic purposes
    breakdown_volume_elevated = breakout_volume >= VOLUME_BREAKOUT_MULTIPLIER × avg_volume_20
```

| Parameter | Short-Term | Medium-Term | Long-Term |
|-----------|-----------|-------------|-----------|
| ATR_BREAKOUT_MULTIPLIER | 0.5 | 0.5 | 0.5 |
| VOLUME_BREAKOUT_MULTIPLIER | 1.25 | 1.25 | 1.25 |

### 8.2.1 Volume Climax Caution Flag

**Empirical caveat (Bulkowski, Ch. 41)**: Heavy breakout-day volume (>3× average) actually triples failure rates — 14% failure after above-average volume vs 5% after below-average volume for upward breakouts. This directly contradicts the classical rule that heavy volume confirms breakouts.

Resolution: when breakout volume is extremely high, flag a potential climax rather than treating it as pure confirmation:

```
if breakout_volume > 3.0 × avg_volume_20:
    volume_climax_caution = True
    # Possible exhaustion/climax rather than genuine follow-through
    # Watch for throwback/pullback with extra vigilance
    # Consider this a SHORT-TERM blow-off rather than start of sustained move
elif breakout_volume > VOLUME_BREAKOUT_MULTIPLIER × avg_volume_20:
    volume_climax_caution = False
    # Normal elevated volume — standard confirmation
else:
    volume_climax_caution = False
```

This flag does NOT prevent the breakout from being confirmed — it adds a warning to the output. Per Bulkowski, performance after heavy-volume breakouts averages only 1.8 percentage points better than after light-volume breakouts, while failure rates triple. The algorithm should record this as a risk factor.

### 8.3 Time Confirmation Window

| Tier | Confirmation Window |
|------|-------------------|
| Short-term (15-min) | 4 bars (1 hour) |
| Medium-term (1-hour) | 3 bars (3 hours) |
| Long-term (daily) | 3 bars (3 trading days) |

If price returns inside the prior structure within this window → **false break**, reclassify as OTHERS.

### 8.4 Pullback / Throwback Expectation

After a confirmed break, price commonly retests the broken level (~60% of the time per K&D). The broken level becomes an S/R level with `role_reversal: true`.

### 8.5 What Happens After a Break

A confirmed break triggers re-evaluation on the next analysis run:

- If price establishes a new trend → reclassify as TREND.
- If price consolidates → reclassify as OTHERS.
- If the break was false → reclassify as OTHERS.

---

## 9. Others Regime: Sideways, Choppy & Transitional

This section applies when `regime = "OTHERS"`. Do NOT force a directional trend channel.

### 9.1 SIDEWAYS

Draw a horizontal trading range: upper boundary = highest resistance zone, lower boundary = lowest support zone. Tag as `channel_type: "HORIZONTAL_RANGE"`.

**Volume behavior within ranges** (Pring, Ch. 5; Murphy, Ch. 6):

In a SIDEWAYS regime, monitor volume for breakout buildup signals:

```
# Compute average volume during the SIDEWAYS period
range_avg_volume = mean(volume) over the range duration

# Split volume into rally-leg volume vs decline-leg volume within the range
rally_volume = mean(volume) during bars where price is rising toward resistance
decline_volume = mean(volume) during bars where price is falling toward support

# Directional tell within range (Murphy):
if rally_volume > decline_volume × 1.15:
    range_volume_bias = "BULLISH"  # Eventual breakout more likely upward
elif decline_volume > rally_volume × 1.15:
    range_volume_bias = "BEARISH"  # Eventual breakdown more likely downward
else:
    range_volume_bias = "NEUTRAL"

# Volume trend within range:
volume_slope = linear_regression_slope(volume series over range duration)
if volume_slope < 0:
    range_volume_trend = "DECLINING"  # Normal for consolidation — coiling
elif volume_slope > 0:
    range_volume_trend = "EXPANDING"  # Unusual — breakout may be imminent
else:
    range_volume_trend = "FLAT"
```

Per Pring (Ch. 5): volume "almost dries up" as a rectangle nears completion, then "picks up noticeably" on the breakout. Expanding volume within an ongoing range is an anomaly worth flagging.

### 9.2 CHOPPY

Only draw individual S/R levels, not ranges or channels. R² < 0.30 on both sides.

### 9.3 TRANSITIONAL

Fan principle exhausted or reversal confirmed, but new trend not yet established. Draw S/R from prior trend's key levels plus any new levels forming.

### 9.4 INSUFFICIENT_DATA

Total bars < minimum lookback or fewer than 4 confirmed pivots.

---

## 10. Handling Recent Price Data

### 10.1 Dual-Fit Approach

1. **Full fit**: Fit trendline using ALL pivots.
2. **Trailing fit**: Fit excluding the most recent N bars:

| Tier | Bars Excluded for Trailing Fit |
|------|-------------------------------|
| Short-term (15-min) | 26 bars (1 trading day) |
| Medium-term (1-hour) | 7 bars (1 trading day) |
| Long-term (daily) | 10 bars (2 weeks) |

3. If the two fits produce >20% slope difference → flag `recent_divergence: true` and report both.
4. For live trading, use the **trailing fit** as primary reference.

### 10.2 When To Redraw

- A new confirmed pivot forms (enough lookahead bars have passed)
- Price closes beyond the channel by > 1 × ATR(14) for 2+ consecutive bars
- The fan principle triggers (Section 12)

---

## 11. Support & Resistance Line Construction

S/R lines are constructed **independently within each tier** using that tier's own pivots, ATR, and parameters.

### 11.1 Horizontal S/R Lines

For the purposes of this algorithm, "Support and Resistance Lines" refers specifically to **horizontal** lines. Sloped support/resistance is captured by the trend channel lines.

### 11.2 How To Identify Horizontal S/R Levels

1. Collect all significant reversal points (pivot highs and pivot lows) from the lookback window.
2. For resistance: use the `high` of the pivot high bar. For support: use the `low` of the pivot low bar.
3. **Record the volume context at each reversal point** using the `volume_at_pivot` and `volume_ratio` from Section 3.7. Per Edwards & Magee (Ch. 13): the potency of an S/R level is proportional to the volume that originally created it. Heavy-volume reversals create strong, persistent zones; light-volume reversals create weak zones.
4. **Cluster nearby levels into zones**:

| Tier | ZONE_TOLERANCE_PCT | Alternative: ATR Multiple |
|------|-------------------|--------------------------|
| Short-term (15-min) | 0.3% | 0.5 × ATR(14) |
| Medium-term (1-hour) | 0.4% | 0.5 × ATR(14) |
| Long-term (daily) | 0.5% | 0.5 × ATR(14) |

4. **Score each zone** by touch count, recency, volume, and role reversal.

### 11.3 Zone Scoring Formula

```
zone_score = (touch_count × W_TOUCH) + (recency_score × W_RECENCY) + (volume_score × W_VOLUME) + (role_reversal_bonus × W_REVERSAL)
```

Default weights: `W_TOUCH = 2.0`, `W_RECENCY = 1.5`, `W_VOLUME = 1.0`, `W_REVERSAL = 3.0`

Where:
- `recency_score` = sum of `exp(-decay_rate × bars_since_touch)` for each touch
- `volume_score` = average `volume_ratio` (Section 3.7) across all touches in the zone. A zone where reversals consistently occurred on above-average volume (ratio > 1.0) scores higher. Per Edwards & Magee: heavy-volume tops/bottoms create powerful S/R; light-volume tops/bottoms create weak S/R.
- `role_reversal_bonus` = 1 if zone has acted as both S and R, else 0

### 11.4 Zone Boundary Definition

```
zone_upper = max(prices in cluster) + 0.25 × ATR(14)
zone_lower = min(prices in cluster) - 0.25 × ATR(14)
zone_midpoint = (zone_upper + zone_lower) / 2
```

### 11.5 Minimum Requirements

- At least 2 reversal points (touches) within the zone.
- Zone must be at least 5 bars old.
- `zone_score >= 4.0`.

### 11.6 S/R Weakening Rule

Repeated tests weaken levels:

```
if touch_count >= 3:
    weakening_factor = 0.90 ^ (touch_count - 2)
    zone_score *= weakening_factor
```

### 11.7 S/R Level Decay Over Time

For levels not retested in the last `DECAY_WINDOW` bars:

| Tier | DECAY_WINDOW | Equivalent Time |
|------|-------------|-----------------|
| Short-term (15-min) | 400 bars | ~15 trading days |
| Medium-term (1-hour) | 200 bars | ~29 trading days |
| Long-term (daily) | 120 bars | ~6 months |

Reduce score by 50% if not retested within this window.

---

## 12. Fan Principle & Trend Redrawing

### 12.1 The Fan Principle

When a trendline is broken but the broader trend has not reversed, redraw at a shallower angle. Maximum 3 fan lines before a reversal is expected (per Pring and K&D).

### 12.2 Fan Line Algorithm

```
fan_lines = []
current_pivots = all_primary_pivots

while True:
    trendline = fit_and_anchor(current_pivots)
    fan_lines.append(trendline)
    
    if len(fan_lines) >= 3:
        status = "FAN_EXHAUSTED"
        trend_reversal_signal = True
        break
    
    if not is_broken(trendline, current_price):
        break
    
    current_pivots = pivots_after_break_point
    if len(current_pivots) < 2:
        break
```

### 12.3 When To Completely Redraw

1. Fan principle exhausted (3 fan lines broken) → reclassify regime.
2. Third-order pivot reversal confirmed.
3. New trend in opposite direction established.

---

## 13. Multi-Tier Interaction

### 13.1 Purpose

After all three tiers are analyzed independently, this layer compares the regimes across tiers to identify confluence (agreement) and conflict (disagreement). This informs position sizing, stop selection, and trade conviction.

### 13.2 Confluence Detection

**All tiers agree on direction**: Highest conviction. All three show TREND in the same direction, or higher tiers show TREND while lower tier shows early BREAK in the same direction.

```
if all tiers show UPTREND (or BREAKOUT upward):
    confluence = "FULL_BULLISH"
    conviction = "HIGH"

if all tiers show DOWNTREND (or BREAKDOWN):
    confluence = "FULL_BEARISH"
    conviction = "HIGH"
```

### 13.3 Conflict Detection

**Common conflict patterns:**

| Long-Term | Medium-Term | Short-Term | Interpretation |
|-----------|-------------|------------|----------------|
| UPTREND | UPTREND | DOWNTREND | Pullback within uptrend — potential buy setup once short-term downtrend exhausts |
| UPTREND | OTHERS (sideways) | DOWNTREND | Consolidation within uptrend — wait for medium-term to resolve |
| UPTREND | BREAK (breakdown) | DOWNTREND | Trend may be changing — watch for long-term trendline break |
| OTHERS | BREAK (breakout) | UPTREND | Potential new trend emerging from range — confirmation pending |
| DOWNTREND | UPTREND | UPTREND | Counter-trend rally — long-term bias still bearish |

### 13.4 Tier Dominance Rule

When tiers conflict, **the higher tier provides the bias, the lower tier provides the timing**:

- **Long-term determines overall bias** (bullish/bearish/neutral).
- **Medium-term determines swing direction** (which side of the channel to trade).
- **Short-term determines entry/exit precision** (exactly when to act).

A short-term signal that conflicts with the long-term bias should be treated with lower conviction and tighter stops. A short-term signal that aligns with the long-term bias gets higher conviction and wider stops.

### 13.5 Stop Selection by Tier

| Hold Period | Primary Stop Source | Context Source |
|-------------|-------------------|----------------|
| Intraday to a few days | Short-term (15-min) channel line | Medium-term direction |
| A few days to a few weeks | Medium-term (1-hour) channel line | Long-term direction |
| A few weeks to a few months | Long-term (daily) channel line or major S/R zone | — |

### 13.6 Multi-Tier Output Fields

```json
{
  "multi_tier_interaction": {
    "confluence": "PARTIAL_BULLISH",
    "conviction": "MEDIUM",
    "description": "Long-term uptrend, medium-term sideways (pullback), short-term downtrend — classic pullback-within-uptrend setup",
    "dominant_bias": "BULLISH",
    "conflicts": [
      {
        "tiers": ["long_term", "short_term"],
        "type": "DIRECTION_CONFLICT",
        "interpretation": "Short-term counter-trend move within long-term uptrend"
      }
    ],
    "suggested_stop_tier": "medium_term"
  }
}
```

---

## 14. Output Schema

The algorithm outputs one JSON per ticker, containing all three tier analyses plus the multi-tier interaction layer:

```json
{
  "ticker": "AAPL",
  "analysis_timestamp": "2026-04-22T12:00:00Z",
  
  "short_term": {
    "tier": "short_term",
    "interval": "15min",
    "lookback_trading_days": 20,
    "lookback_bars": 520,
    "scale_mode": "arithmetic",
    "atr_14": 1.25,
    
    "regime": {
      "state": "TREND",
      "sub_type": null,
      "trend_direction": "DOWNTREND",
      "confidence": 0.71,
      "r_squared": 0.58,
      "trend_start_date": "2026-04-18T11:30:00",
      "trend_start_bar_index": 480
    },
    
    "trend_channel": {
      "channel_geometry": "PARALLEL",
      "resolution_bias": null,
      "steep_flag": false,
      "primary_line": {
        "role": "RESISTANCE",
        "slope_pct_per_bar": -0.025,
        "intercept_price": 195.80,
        "anchor_points": [
          {"timestamp": "2026-04-18T14:30:00", "price": 195.80, "bar_index": 488},
          {"timestamp": "2026-04-19T10:30:00", "price": 195.20, "bar_index": 501},
          {"timestamp": "2026-04-21T13:30:00", "price": 194.10, "bar_index": 516}
        ],
        "r_squared": 0.88
      },
      "opposite_line": {
        "role": "SUPPORT",
        "slope_pct_per_bar": -0.025,
        "intercept_price": 192.40,
        "construction_method": "PARALLEL_CLONE",
        "anchor_points": [
          {"timestamp": "2026-04-19T15:30:00", "price": 192.10, "bar_index": 508}
        ]
      },
      "parallel_validation": {
        "residual_median_atr_ratio": 0.12,
        "validation_result": "PARALLEL_CONFIRMED",
        "total_touches": 5
      },
      "channel_width_pct": 1.8,
      "channel_width_atr": 2.7,
      "width_status": "VALID",
      "current_price_position": {
        "price": 193.50,
        "pct_within_channel": 32.4,
        "zone": "LOWER_HALF"
      },
      "projected_values": {
        "next_bar": {
          "primary_line_price": 194.05,
          "opposite_line_price": 192.35
        }
      }
    },
    
    "trailing_fit_channel": {
      "recent_divergence": false
    },
    
    "fan_lines": [],
    "break_info": null,
    
    "support_resistance_zones": [
      {
        "type": "SUPPORT",
        "zone_midpoint": 191.80,
        "zone_upper": 192.10,
        "zone_lower": 191.50,
        "touch_count": 3,
        "zone_score": 7.2,
        "role_reversal": false
      }
    ]
  },
  
  "medium_term": {
    "tier": "medium_term",
    "interval": "1hour",
    "lookback_trading_days": 60,
    "lookback_bars": 420,
    "scale_mode": "arithmetic",
    "atr_14": 2.10,
    
    "regime": {
      "state": "OTHERS",
      "sub_type": "SIDEWAYS",
      "trend_direction": null
    },
    
    "trend_channel": null,
    
    "horizontal_range": {
      "upper_boundary": 198.50,
      "lower_boundary": 190.20,
      "width_pct": 4.3
    },
    
    "support_resistance_zones": [
      {
        "type": "RESISTANCE",
        "zone_midpoint": 198.50,
        "zone_upper": 199.00,
        "zone_lower": 198.00,
        "touch_count": 4,
        "zone_score": 9.8,
        "role_reversal": true
      },
      {
        "type": "SUPPORT",
        "zone_midpoint": 190.20,
        "zone_upper": 190.80,
        "zone_lower": 189.60,
        "touch_count": 3,
        "zone_score": 7.5,
        "role_reversal": false
      }
    ]
  },
  
  "long_term": {
    "tier": "long_term",
    "interval": "daily",
    "lookback_trading_days": 260,
    "lookback_bars": 260,
    "scale_mode": "arithmetic",
    "atr_14": 3.45,
    
    "regime": {
      "state": "TREND",
      "sub_type": null,
      "trend_direction": "UPTREND",
      "confidence": 0.85,
      "r_squared": 0.72,
      "trend_start_date": "2025-08-12",
      "trend_start_bar_index": 78
    },
    
    "trend_channel": {
      "channel_geometry": "PARALLEL",
      "resolution_bias": null,
      "steep_flag": false,
      "primary_line": {
        "role": "SUPPORT",
        "slope_pct_per_bar": 0.045,
        "intercept_price": 172.30,
        "anchor_points": [
          {"date": "2025-08-12", "price": 172.30, "bar_index": 78},
          {"date": "2025-10-28", "price": 176.50, "bar_index": 133},
          {"date": "2026-01-15", "price": 182.40, "bar_index": 190}
        ],
        "r_squared": 0.91
      },
      "opposite_line": {
        "role": "RESISTANCE",
        "slope_pct_per_bar": 0.045,
        "intercept_price": 185.60,
        "construction_method": "PARALLEL_CLONE",
        "anchor_points": [
          {"date": "2025-09-22", "price": 185.60, "bar_index": 108}
        ]
      },
      "parallel_validation": {
        "residual_median_atr_ratio": 0.15,
        "validation_result": "PARALLEL_CONFIRMED",
        "total_touches": 7
      },
      "channel_width_pct": 6.8,
      "channel_width_atr": 3.9,
      "width_status": "VALID",
      "current_price_position": {
        "price": 193.50,
        "pct_within_channel": 62.1,
        "zone": "MID_UPPER"
      },
      "projected_values": {
        "next_bar": {
          "primary_line_price": 189.20,
          "opposite_line_price": 202.50
        }
      }
    },
    
    "trailing_fit_channel": {
      "recent_divergence": false
    },
    
    "fan_lines": [],
    "break_info": null,
    
    "support_resistance_zones": [
      {
        "type": "SUPPORT",
        "zone_midpoint": 175.00,
        "zone_upper": 175.80,
        "zone_lower": 174.20,
        "touch_count": 4,
        "zone_score": 11.2,
        "role_reversal": true,
        "avg_volume_ratio_at_touches": 1.45
      }
    ],
    
    "volume_analysis": {
      "volume_confirmed": true,
      "volume_trend_ratio": 1.28,
      "volume_trend_interpretation": "Volume expanding on up-legs, contracting on down-legs — healthy",
      
      "pivot_volume_divergence": {
        "divergence_warning": "MILD",
        "divergence_count": 1,
        "details": [
          {"pivot": "PH3 at 2026-03-15", "price": 199.20, "volume_ratio": 0.95, "prior_pivot_volume_ratio": 1.35, "divergence": true}
        ]
      },
      
      "obv_analysis": {
        "obv_slope_direction": "POSITIVE",
        "obv_confirmation": "CONFIRMED",
        "obv_trendline_broken": false,
        "joint_break": "NONE"
      },
      
      "anchor_point_volumes": [
        {"date": "2025-08-12", "price": 172.30, "volume_ratio": 0.82, "type": "pivot_low"},
        {"date": "2025-10-28", "price": 176.50, "volume_ratio": 0.65, "type": "pivot_low"},
        {"date": "2026-01-15", "price": 182.40, "volume_ratio": 0.58, "type": "pivot_low"}
      ]
    }
  },
  
  "multi_tier_interaction": {
    "confluence": "PARTIAL_BULLISH",
    "conviction": "MEDIUM",
    "description": "Long-term uptrend, medium-term sideways (pullback within range), short-term downtrend — classic pullback-within-uptrend. Watch for short-term reversal to confirm next up-leg.",
    "dominant_bias": "BULLISH",
    "conflicts": [
      {
        "tiers": ["long_term", "short_term"],
        "type": "DIRECTION_CONFLICT",
        "interpretation": "Short-term counter-trend move within long-term uptrend"
      }
    ],
    "suggested_stop_tier": "medium_term"
  },
  
  "status": "SUCCESS"
}
```

---

## 15. Edge Cases & Fallbacks

### 15.1 Not Enough Data

- If total bars < minimum lookback for a tier: that tier outputs `regime: OTHERS, sub_type: INSUFFICIENT_DATA`.
- If no pivots found after filtering: relax `ATR_SWING_MULTIPLIER` by 0.25 and retry once. If still none: `status: "NO_PIVOTS_FOUND"`.

### 15.2 IPO / Recently Listed Stock

- If data history < 60 trading days: long-term tier outputs INSUFFICIENT_DATA, medium-term may have limited data. Short-term tier can still function.
- If data history < 20 trading days: only short-term tier may function.

### 15.3 Gaps (Overnight, Earnings, Ex-Div)

- Large gaps (> 2× ATR): not a pivot point. Draw S/R at gap boundaries. Use post-gap prices for trendline fitting unless pre-gap trend is clearly continuing.
- **Special note for 1-hour and 15-min tiers**: Overnight gaps appear as large gaps between the last bar of one day and the first bar of the next. These are normal and should NOT trigger gap-handling logic unless the gap size exceeds `2 × ATR(14)` for that tier.

### 15.4 Stock Splits / Dividends

- All price data must be **split-adjusted and dividend-adjusted** before analysis.

### 15.5 Very Low-Volume / Illiquid Stocks

- If average daily volume < 100,000 shares: flag `low_liquidity: true`.
- Increase `ZONE_TOLERANCE_PCT` by 50%. Increase `ATR_BREAKOUT_MULTIPLIER` to 0.75.

### 15.6 Extreme Volatility (Earnings Season, etc.)

- If current ATR(14) > 2× ATR(60): flag `elevated_volatility: true`.
- Widen all tolerances by 50%. Consider excluding spike bars from pivot calculations.

### 15.7 Regime Transitions

When the regime changes between analysis runs:

- TREND → BREAK: The broken trendline becomes an S/R level with `role_reversal: true`.
- OTHERS → TREND: The horizontal range boundaries become initial S/R context for the new channel.
- BREAK → TREND: The break level and any pullback/throwback level become key S/R for the new channel.

### 15.8 Flat Market With Occasional Spikes

Draw horizontal S/R only. Spikes form outlier pivots excluded from S/R clustering via ATR filter. Tag `regime: "OTHERS"`, `sub_type: "SIDEWAYS"`.

---

## 16. Configuration Defaults Summary

All parameters in one place for easy tuning. Tier-specific values are listed side by side.

```python
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
    "VOLUME_CLIMAX_MULTIPLIER": 3.0,      # above this × avg_vol = climax caution flag
    "BREAKOUT_CONFIRM_BARS": {
        "short_term": 4,
        "medium_term": 3,
        "long_term": 3,
    },
    
    # ═══════════════════════════════════════
    # VOLUME ANALYSIS
    # ═══════════════════════════════════════
    "VOLUME_MA_PERIOD": 20,                # period for average volume baseline
    "PIVOT_VOLUME_NEIGHBORHOOD": 3,        # bars on each side for pivot volume averaging
    "VOLUME_TREND_RATIO_THRESHOLD": 1.10,  # with-trend/counter-trend vol ratio for confirmation
    "VOLUME_CONFIDENCE_PENALTY": 0.15,     # reduce confidence by 15% if volume not confirmed
    "OBV_ENABLED": True,                   # compute OBV and OBV trendline analysis
    
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
```

---

## Appendix A: Algorithm Execution Flow (Pseudocode)

```
function analyze_ticker(ticker, config):
    
    results = {}
    
    # ═══════════════════════════════════════════
    # PHASE 1: ANALYZE EACH TIER INDEPENDENTLY
    # ═══════════════════════════════════════════
    
    for tier in ["short_term", "medium_term", "long_term"]:
        
        tier_config = config.TIERS[tier]
        
        # Step 1: Fetch data
        data = fetch_ohlcv(ticker, tier_config.interval, tier_config.lookback_trading_days)
        
        # Step 2: Determine scale
        scale = determine_scale(data, config.LOG_SCALE_THRESHOLD)
        if scale == "log":
            data.prices = ln(data.prices)
        
        # Step 3: Compute ATR
        atr = compute_atr(data, config.ATR_PERIOD)
        
        # Step 4: Identify pivots (Section 3)
        pivots = identify_pivots(data, config.PIVOT_WINDOW[tier], 
                                 config.ATR_SWING_MULTIPLIER[tier], atr)
        pivots = enforce_alternation(pivots)
        pivots = enforce_spacing(pivots, config, tier)
        pivots = record_pivot_volumes(pivots, data.volume, config)  # NEW: Section 3.7
        
        if len(pivots.lows) + len(pivots.highs) < 4:
            results[tier] = {"regime": {"state": "OTHERS", "sub_type": "INSUFFICIENT_DATA"}}
            continue
        
        # Step 5: Classify regime (Section 4) — TREND → BREAK → OTHERS
        trend = check_trend(pivots, config, tier)
        volume_confirmed = check_volume_trend(pivots, data.volume, trend, config)  # NEW: §4.2 Step 5
        
        if trend.detected:
            # TREND regime → Build channel (Section 5)
            primary_line = fit_primary_trendline(pivots, trend, config, tier)
            parallel_line = build_parallel_line(primary_line, pivots, trend)
            validation = validate_parallel(parallel_line, pivots, atr, config)
            
            if validation.result == "PARALLEL_CONFIRMED":
                channel = ParallelChannel(primary_line, parallel_line)
            elif validation.result in ("CONVERGING", "DIVERGING", "TRIANGLE"):
                opposite_line = fit_independent_opposite(pivots, trend, config, tier)
                channel = NonParallelChannel(primary_line, opposite_line, validation)
            elif validation.result == "ACCELERATING":
                channel = rebuild_steeper_parallel(pivots, trend, config, tier)
            
            validate_slope(channel, config, tier)
            validate_width(channel, atr, config, tier)
            trailing_channel = build_channel(pivots, trend, config, tier, exclude_recent=True)
            fan_lines = detect_fan_lines(channel, data, pivots, config)
            
            # NEW: Volume analysis (Sections 5.9, 5.10)
            vol_divergence = detect_volume_divergence(channel.anchor_points, pivots)
            obv_analysis = compute_obv_analysis(data, channel, trend, config)
            
            break_info = None
        
        else:
            break_result = check_break(pivots, data, atr, config, tier)
            if break_result.detected:
                channel = None
                trailing_channel = None
                fan_lines = []
                break_info = break_result
            else:
                sub_type = classify_others(pivots, config, tier)
                channel = None
                trailing_channel = None
                fan_lines = []
                break_info = None
        
        # Step 6: S/R zones (always, regardless of regime)
        sr_zones = identify_sr_zones(pivots, data.volume, atr, config, tier)
        sr_zones = score_and_filter_zones(sr_zones, config, tier)
        
        # Step 7: Convert back from log scale
        if scale == "log":
            channel = exp_transform(channel)
            sr_zones = exp_transform(sr_zones)
        
        # Step 8: Projections
        projections = compute_projections(channel, next_n_bars=1) if channel else None
        
        # Store tier result
        results[tier] = build_tier_output(tier, data, atr, channel, 
                                          trailing_channel, fan_lines,
                                          break_info, sr_zones, projections)
    
    # ═══════════════════════════════════════════
    # PHASE 2: MULTI-TIER INTERACTION (Section 13)
    # ═══════════════════════════════════════════
    
    interaction = analyze_tier_interaction(
        results["short_term"],
        results["medium_term"],
        results["long_term"]
    )
    
    # ═══════════════════════════════════════════
    # PHASE 3: ASSEMBLE FINAL OUTPUT
    # ═══════════════════════════════════════════
    
    return {
        "ticker": ticker,
        "analysis_timestamp": now(),
        "short_term": results["short_term"],
        "medium_term": results["medium_term"],
        "long_term": results["long_term"],
        "multi_tier_interaction": interaction,
        "status": "SUCCESS"
    }
```

---

## Appendix B: Key Sources & Their Contributions

| Concept | Primary Source | Section |
|---------|--------------|---------|
| Pivot hierarchy (1st/2nd/3rd order) | Grimes, Ch. 1 | §3 |
| Pivot spacing ("independent wave components") | Edwards & Magee, Ch. 14 | §3.6 |
| Timeframe factor of 3–5× | Grimes, Ch. 1 | §1.1 |
| Standard trendline construction | Grimes, Ch. 3; Edwards & Magee, Ch. 14 | §5.1 |
| Parallel channel line (3-step method) | Grimes, Ch. 3; Kirkpatrick & Dahlquist, Ch. 12 | §5.2 |
| Non-parallel channels (wedges, triangles, broadening) | Kirkpatrick & Dahlquist, Ch. 15; Bulkowski | §5.4–5.5 |
| 5-touch minimum for wedge/triangle | Bulkowski (Encyclopedia of Chart Patterns) | §5.4 |
| Steep trendlines / acceleration | Edwards & Magee, Ch. 14; Pring, Ch. 8 | §6 |
| Fan principle | Pring, Ch. 8; Edwards & Magee, Ch. 14 | §12 |
| S/R as zones, not lines | Grimes, Ch. 4; Kirkpatrick & Dahlquist, Ch. 12 | §11 |
| S/R weakening with repeated tests | Grimes, Ch. 4; Edwards & Magee, Ch. 13 | §11.6 |
| Breakout confirmation (close, ATR, volume) | Kirkpatrick & Dahlquist, Ch. 13 | §8.2 |
| Pullbacks and throwbacks | Kirkpatrick & Dahlquist, Ch. 13 | §8.4 |
| Log vs. arithmetic scaling | Grimes, Ch. 1; Edwards & Magee, Ch. 2; K&D, Ch. 11 | §2 |
| Multi-timeframe interaction | Grimes, Ch. 7 | §13 |
| Intermediate cycle duration | Pring, Ch. 4 | §1.2 |
| Regression for slope discovery | Prior design (validated) | §5.1 |
| Channel width via ATR | Grimes, Ch. 8 (stops/ATR logic) | §7.5 |
| Volume divergence at pivots | Pring, Ch. 22 (Principle 5); Edwards & Magee, Ch. 6 | §5.9 |
| Volume expands in trend direction | Edwards & Magee, Ch. 3, Ch. 17; Murphy, Ch. 7 | §4.2 |
| Asymmetric breakout volume rule | Edwards & Magee, Ch. 14, Ch. 17; Pring, Ch. 22 | §8.2 |
| Heavy breakout volume triples failures | Bulkowski, Ch. 41 (empirical) | §8.2.1 |
| On-Balance Volume (OBV) | Pring, Ch. 23; Murphy, Ch. 7; K&D, Ch. 18 | §5.10 |
| OBV joint trendline breaks | Pring, Ch. 23 | §5.10 |
| S/R potency proportional to volume | Edwards & Magee, Ch. 13 | §11.2 |
| Volume declines in consolidation patterns | Pring, Ch. 5; Murphy, Ch. 6 | §9.1 |
| Volume directional tell in ranges | Murphy, Ch. 6 | §9.1 |
| Grimes skepticism on volume predictive power | Grimes, Ch. 3–5 | §4.2, §5.9 |

---

## Appendix C: What This Document Does NOT Cover (Future Work)

- **Volume profile / Volume-at-Price analysis** at S/R zones (Market Profile, VPOC) — only aggregate volume metrics are covered, not price-level distribution
- **Advanced volume indicators** beyond OBV (Chaikin Money Flow, MFI, Force Index, TRIN/Arms Index) — OBV was selected as the single deterministic volume indicator for simplicity
- **Moving average confluence** with trendlines (e.g., 50/200 SMA interaction with channels)
- **Pattern recognition** (head-and-shoulders, flags, pennants, etc.) — only channel geometry and S/R are covered
- **Trend exhaustion / health scoring** (swing length deterioration, climax detection, momentum divergence)
- **Multi-ticker relative strength** or sector rotation
- **Options-derived support/resistance** (max pain, gamma exposure levels)
- **Order flow / Level 2 data** integration
- **Live alerting logic** (zone-based alerts, trailing stops) — covered in separate workflow notes
- **Backtesting framework** for validating parameter choices
