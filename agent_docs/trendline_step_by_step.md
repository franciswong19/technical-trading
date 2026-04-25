# Trendline Methodology: Step-by-Step with Numeric Examples

## Overview

This document walks through the trendline algorithm step by step with concrete numeric examples. The audience is someone who wants to understand the algorithm in detail before coding it.

**What the report does**: For a given US equity ticker, the algorithm produces three independent analyses -- short-term, medium-term, and long-term -- each with its own trend channel, support/resistance zones, and regime classification. A multi-tier interaction layer then identifies confluence and conflict between the tiers.

**Three-tier structure**:

```
SHORT-TERM ──(4x)──> MEDIUM-TERM ──(~7x)──> LONG-TERM
  15-min                 1-hour                  Daily
```

Each tier runs the full pipeline independently: data fetching, pivot detection, regime classification, channel construction, S/R zones. The tiers are related by a factor of 4-7x so each provides new information without redundancy.

**Pipeline for each tier**:

```
Fetch Data --> Scale --> Detect Pivots --> Classify Regime --> Build Channel --> S/R Zones
                                               |
                                    TREND / BREAK / OTHERS
```

---

## Step 1: Data Fetching

### Three tiers, bar sizes, lookback periods

| Tier | Bar Interval | Lookback | Bars Per Day | Total Bars |
|------|-------------|----------|--------------|------------|
| Short-term | 15 minutes | 20 trading days | 26 | 520 |
| Medium-term | 1 hour | 60 trading days | 7 | 420 |
| Long-term | 1 day | 260 trading days (~1 year) | 1 | 260 |

Each bar contains: `timestamp, open, high, low, close, volume`.

### Numeric example

Suppose we are analyzing ticker AAPL on April 24, 2026.

**Short-term tier**: Fetch 15-minute bars going back 20 trading days. US equities trade 09:30-16:00 ET = 6.5 hours = 26 bars per day. Total: 20 x 26 = 520 bars.

**Medium-term tier**: Fetch 1-hour bars going back 60 trading days. The session produces 7 hourly bars per day (09:30-10:30, 10:30-11:30, ..., 15:30-16:00; the last bar is only 30 min). Total: 60 x 7 = 420 bars.

**Long-term tier**: Fetch daily bars going back 260 trading days (~1 calendar year). Total: 260 bars.

---

## Step 2: Chart Scaling

### When to use log vs. arithmetic

The algorithm checks whether the price range over the lookback window is large enough to warrant logarithmic scaling.

**Threshold**: If `(max_price - min_price) / min_price > 0.20` (i.e., more than 20% range), use log scale.

### Numeric example: arithmetic scale

```
Lookback data for AAPL (daily, 260 bars):
  max(highs) = $198.50
  min(lows)  = $172.30

Range check: (198.50 - 172.30) / 172.30 = 26.20 / 172.30 = 0.152

0.152 < 0.20 --> Use ARITHMETIC scale
```

All subsequent calculations use raw prices.

### Numeric example: log scale

```
Lookback data for SMCI (daily, 260 bars):
  max(highs) = $85.00
  min(lows)  = $18.50

Range check: (85.00 - 18.50) / 18.50 = 66.50 / 18.50 = 3.59

3.59 > 0.20 --> Use LOG scale
```

All prices are transformed via `ln(price)` before regression, pivot calculations, etc. After all line calculations are complete, coordinates are converted back to price space via `exp()`.

---

## Step 3: Pivot Detection

Pivots are the foundation of all subsequent analysis. The algorithm uses Grimes's three-order hierarchy.

### 3a. First-order pivot identification

A first-order pivot high at bar `i` requires: `high[i] > max(high[i-N:i])` AND `high[i] > max(high[i+1:i+N+1])`, where `N` is the pivot window:

| Tier | Pivot Window N |
|------|---------------|
| Short-term (15-min) | 3 bars (45 min each side) |
| Medium-term (1-hour) | 4 bars (4 hours each side) |
| Long-term (daily) | 5 bars (1 week each side) |

### Numeric example: pivot high detection (long-term, N=5)

Consider daily bars around bar index 45. We check whether bar 45's high is greater than the highs of the 5 bars before and the 5 bars after.

```
Bar index:  40     41     42     43     44    [45]    46     47     48     49     50
High:     $189.20 $190.10 $191.50 $191.80 $192.10 $192.30 $191.90 $191.60 $191.20 $190.50 $189.80

Bars 40-44 highs: [$189.20, $190.10, $191.50, $191.80, $192.10]
  max = $192.10
  $192.30 > $192.10?  YES

Bars 46-50 highs: [$191.90, $191.60, $191.20, $190.50, $189.80]
  max = $191.90
  $192.30 > $191.90?  YES

--> Bar 45 high = $192.30 is a FIRST-ORDER PIVOT HIGH
```

Similarly, a first-order pivot low at bar `i` requires the low to be less than all surrounding lows within the window.

### 3b. ATR swing confirmation

To filter out noise pivots (insignificant wiggles), each pivot must represent a meaningful swing from the preceding opposite pivot.

**Rule**: The swing from the previous opposite pivot must be >= `ATR_SWING_MULTIPLIER x ATR(14)`.

| Tier | ATR_SWING_MULTIPLIER |
|------|---------------------|
| Short-term | 0.75 |
| Medium-term | 1.0 |
| Long-term | 1.5 |

### Numeric example: ATR swing confirmation (long-term)

```
ATR(14) = $1.25

Previous pivot low was at bar 38, price = $189.50
Current candidate pivot high at bar 45, price = $192.30

Swing = $192.30 - $189.50 = $2.80

Required minimum = 1.5 x $1.25 = $1.875

$2.80 >= $1.875?  YES --> PIVOT HIGH CONFIRMED
```

If the swing had been only $1.00, it would fail: $1.00 < $1.875, and the pivot would be discarded as noise.

### 3c. Zigzag alternation enforcement

After filtering, pivots must strictly alternate: high, low, high, low, ... If two consecutive pivot highs occur, keep only the higher one. If two consecutive pivot lows occur, keep only the lower one.

```
Before alternation:
  PH $192.30, PH $193.10, PL $189.50, PH $194.80, PL $190.20, PL $188.60

After alternation:
  PH $193.10 (kept higher of $192.30 and $193.10)
  PL $189.50
  PH $194.80
  PL $188.60 (kept lower of $190.20 and $188.60)
```

### 3d. Pivot spacing constraints

Two pivots close together in time produce unreliable trendlines. Three conditions must hold between any two adjacent anchor pivots on the same side:

**Condition A -- Minimum bar separation**:

| Tier | Min Bars Between Same-Side Pivots |
|------|----------------------------------|
| Short-term | 20 bars (~5 hours) |
| Medium-term | 10 bars (~1.5 trading days) |
| Long-term | 15 bars (~3 weeks) |

**Condition B -- Minimum intervening swing ("open water")**:

For two pivot lows PL1 and PL2, the rally between them must be large enough:

```
max_high_between(PL1, PL2) - max(PL1.price, PL2.price) >= SWING_ATR_MULTIPLE x ATR(14)
```

| Tier | SWING_ATR_MULTIPLE |
|------|-------------------|
| Short-term | 1.0 |
| Medium-term | 1.0 |
| Long-term | 1.5 |

### Numeric example: Condition B (long-term)

```
PL1 at bar 78, price = $172.30
PL2 at bar 133, price = $176.50
Highest high between bars 78 and 133 = $185.60
ATR(14) = $3.45

Swing = $185.60 - max($172.30, $176.50)
      = $185.60 - $176.50
      = $9.10

Required = 1.5 x $3.45 = $5.175

$9.10 >= $5.175?  YES --> Condition B satisfied (genuine "open water" between lows)
```

**Condition C -- No overlap (visual open water test)**:

For two pivot lows with an intervening pivot high between them, the highest price in the 3-bar neighborhood of each pivot low must be lower than the pivot high's price. This ensures a genuine peak existed between the lows, not just choppy flat action.

```
PL1 neighborhood (bars 77-79): highs = [$173.10, $172.90, $173.50] --> max = $173.50
PL2 neighborhood (bars 132-134): highs = [$177.20, $177.00, $177.40] --> max = $177.40
Intervening pivot high = $185.60

$173.50 < $185.60?  YES
$177.40 < $185.60?  YES
--> Condition C satisfied
```

**Minimum total channel span**:

| Tier | Min Span (bars) |
|------|----------------|
| Short-term | 80 (~3 trading days) |
| Medium-term | 30 (~4 trading days) |
| Long-term | 40 (~2 months) |

### 3e. Higher-order pivots

- **Second-order pivot high**: A first-order pivot high preceded AND followed by a lower first-order pivot high.
- **Third-order pivot high**: A second-order pivot high preceded AND followed by a lower second-order pivot high.

```
First-order pivot highs:   $192.30   $193.50   $191.80   $194.20   $192.60

Second-order?
  $193.50: preceded by $192.30 (lower), followed by $191.80 (lower) --> YES, 2nd order
  $194.20: preceded by $191.80 (lower), followed by $192.60 (lower) --> YES, 2nd order

Third-order?
  $194.20: preceded by 2nd-order $193.50 (lower), needs a following 2nd-order that is lower
  --> need more data to confirm
```

### 3f. Minimum pivot count

To proceed with channel construction, need at least 3 pivots on the primary side and 1 on the opposite side. If insufficient:

```
Pivots found after all filtering: 2 pivot lows, 1 pivot high

2 < 3 (minimum for primary side) --> Widen lookback by 50% and retry

Still insufficient? --> Output: regime = "OTHERS", sub_type = "INSUFFICIENT_DATA"
```

---

## Step 4: Regime Classification

The algorithm classifies the market into one of three states, evaluated in strict order: TREND first, then BREAK, then OTHERS (default fallback).

```
                 Identify Pivots
                       |
                 Check for TREND
                    /       \
                 YES         NO
                  |           |
               TREND     Check for BREAK
                           /       \
                        YES         NO
                         |           |
                      BREAK       OTHERS
```

### 4a. TREND detection

A directional trend requires ALL of the following:

**Test 1 -- Dow Theory pivot sequence**:

```
Uptrend example:

Pivot lows:  $188.20 --> $189.50 --> $190.80
                    (+$1.30)     (+$1.30)
             Each higher than the last --> HIGHER LOWS confirmed

Pivot highs: $192.30 --> $193.50 --> $194.80
                    (+$1.20)     (+$1.30)
             Each higher than the last --> HIGHER HIGHS confirmed

Both conditions met --> Uptrend pattern detected
```

```
Downtrend example:

Pivot highs: $194.80 --> $193.20 --> $191.50
                    (-$1.60)     (-$1.70)
             Each lower than the last --> LOWER HIGHS confirmed

Pivot lows:  $190.80 --> $189.30 --> $187.60
                    (-$1.50)     (-$1.70)
             Each lower than the last --> LOWER LOWS confirmed

Both conditions met --> Downtrend pattern detected
```

**Test 2 -- Pivot spacing**: The pivots from Test 1 must satisfy all three spacing constraints from Step 3d (Conditions A, B, C).

**Test 3 -- Linear regression R-squared**:

Fit a linear regression through the primary-side pivots.

```
Uptrend: Fit regression through pivot lows
  Pivot lows: (bar 78, $172.30), (bar 133, $176.50), (bar 190, $182.40)

  Regression: price = 0.045 x bar_index + 168.79
  R-squared = 0.91

  Check slope: 0.045% per bar --> |0.045%| > MIN_SLOPE(0.01%) --> YES
  Check R-squared: 0.91 >= 0.50 --> YES

  --> TREND CONFIRMED
```

If R-squared < 0.50, the linear relationship is too weak -- not a trend:

```
Pivot lows: (bar 50, $180.00), (bar 120, $175.50), (bar 200, $182.00)
  The lows go down then up -- no consistent direction.
  R-squared = 0.12

  0.12 < 0.50 --> NOT a trend, proceed to BREAK check
```

**Test 4 -- Trend start point**: The most recent third-order pivot representing a reversal, or the most recent second-order pivot where the sequence changes character.

**Output**: `regime = "TREND"`, `trend_direction = "UPTREND"` or `"DOWNTREND"`.

### 4b. BREAK detection (if not TREND)

Check whether price has broken beyond a prior structure.

**Step 1**: Identify reference structure (prior channel, S/R zone, or consolidation boundary).

**Step 2**: Confirm break via multi-filter confirmation (see Step 8 below).

**Step 3**: Time confirmation -- price must stay beyond the structure for a confirmation window.

### 4c. OTHERS classification (if neither TREND nor BREAK)

| Sub-type | Condition |
|----------|-----------|
| SIDEWAYS | Pivots oscillate in a horizontal band, both regression slopes < MIN_SLOPE |
| CHOPPY | No consistent pattern, R-squared < 0.30 on both sides |
| TRANSITIONAL | Recently broken trend, new trend not yet established |
| INSUFFICIENT_DATA | Not enough bars or fewer than 4 confirmed pivots |

---

## Step 5: Channel Construction

This step applies only when `regime = "TREND"`. The core insight: always start by assuming the channel is parallel, then let the data tell you whether it is not.

### 5a. Pass 1: Primary trendline (demand line for uptrend)

**Step-by-step for an uptrend**:

1. Collect all confirmed pivot lows from the trend start point.
2. Need at least 3 pivot lows.
3. Fit linear regression: `price = slope x bar_index + intercept`.
4. Anchor-adjust: shift the line down so it touches the lowest pivot low.

### Numeric example: primary trendline

```
Pivot lows (uptrend):
  PL1: (bar 78,  $172.30)
  PL2: (bar 133, $176.50)
  PL3: (bar 190, $182.40)

Linear regression through these 3 points:
  slope = 0.0903  (dollars per bar)
  intercept = $165.26

Now anchor-adjust. For each pivot, compute:
  adjusted_intercept_candidate = pivot_price - slope x pivot_bar_index

  PL1: $172.30 - 0.0903 x 78  = $172.30 - $7.04  = $165.26
  PL2: $176.50 - 0.0903 x 133 = $176.50 - $12.01 = $164.49
  PL3: $182.40 - 0.0903 x 190 = $182.40 - $17.16 = $165.24

  adjusted_intercept = min($165.26, $164.49, $165.24) = $164.49

Final primary line: price = 0.0903 x bar_index + $164.49

Verify: for every bar between bar 78 and bar 190, check that:
  low[i] >= 0.0903 x i + $164.49

If any bar violates this, use that bar's low as a new anchor and recalculate.
```

### 5b. Pass 1: Parallel channel line

1. Take the primary trendline (slope = 0.0903).
2. Create a parallel line with the same slope.
3. Anchor to the single most extreme opposite pivot between the outer anchors.

```
Opposite pivots (pivot highs between bar 78 and bar 190):
  PH1: (bar 108, $185.60)
  PH2: (bar 155, $188.90)
  PH3: (bar 178, $190.20)

Most extreme = PH3 at $190.20 (highest)

Parallel line intercept:
  intercept_parallel = $190.20 - 0.0903 x 178 = $190.20 - $16.07 = $174.13

Parallel line: price = 0.0903 x bar_index + $174.13

Verify: the parallel line must NOT cut through any price bars between
bar 78 and bar 190. Check that high[i] <= 0.0903 x i + $174.13 for all i.
If it does, use the next-most-extreme pivot (PH2) instead.
```

The channel now looks like:

```
Price
  |         PH3
  |        /  .
  |   PH1/  .  ---- Upper (parallel) line: slope=0.0903, intercept=$174.13
  |    / .  .
  |   / PL2
  |  /  .
  | PL1      PL3
  | .  .  .  .  ---- Lower (primary) line: slope=0.0903, intercept=$164.49
  |________________________
            Bar index
```

### 5c. Pass 2: Parallel validation (residual analysis)

Test whether the parallel line is respected by opposite-side pivots.

**Step 1: Compute residuals**

For each pivot high, compute `residual = actual_price - parallel_line_price_at(bar_index)`:

```
PH1 (bar 108): parallel_line = 0.0903 x 108 + $174.13 = $183.88
  residual = $185.60 - $183.88 = +$1.72

PH2 (bar 155): parallel_line = 0.0903 x 155 + $174.13 = $188.13
  residual = $188.90 - $188.13 = +$0.77

PH3 (bar 178): parallel_line = 0.0903 x 178 + $174.13 = $190.20
  residual = $190.20 - $190.20 = $0.00  (this is the anchor, so residual = 0)

Residuals: [+$1.72, +$0.77, $0.00]
```

**Step 2: Evaluate**

```
median_residual = $0.77
ATR(14) = $3.45
Threshold = 0.5 x ATR(14) = $1.725

|$0.77| < $1.725?  YES

residual_trend (slope of residuals over time): negative (residuals decreasing)
  but magnitude is small.

--> channel_geometry = "PARALLEL"   (parallel confirmed)
```

### 5d. When parallel fails -- channel geometry types

If residuals reveal the parallel assumption is wrong, the algorithm fits the opposite side independently and classifies the geometry:

```
slope_diff_pct = |slope_primary - slope_opposite| / max(|slope_primary|, |slope_opposite|)
```

**PARALLEL**: `slope_diff_pct < 0.15`

```
  ___________         Both lines have similar slopes.
 /           /        Price oscillates within evenly-spaced bounds.
/___________/
```

**RISING WEDGE** (converging upward): Both slopes positive, upper slope < lower slope.

```
       /\              Lines converge upward.
      /  \             Resolution bias: BEARISH (69% break downside).
     / __ \            Bulkowski: need 5+ trendline touches (3+2).
    / /    |
   / /
  /_/

Example:
  Primary (lower) slope = +0.10%/bar
  Opposite (upper) slope = +0.06%/bar
  Lines converge --> RISING_WEDGE
  Apex bar = (intercept_upper - intercept_lower) / (slope_lower - slope_upper)
           = ($174.13 - $164.49) / (0.10 - 0.06)
           = $9.64 / 0.04 = bar 241 from start
```

**FALLING WEDGE** (converging downward): Both slopes negative, resolution bias BULLISH (92% break upside).

```
  \__
  \  \             Lines converge downward.
   \  \            Resolution bias: BULLISH.
    \ /
     \/
```

**BROADENING** (diverging): Both sides expanding -- highs overshoot AND lows break below primary.

```
     /\
    /  \           Lines diverge.
   / /\ \         Resolution bias: BEARISH / instability.
  / /  \ \
     \/
```

**ASCENDING TRIANGLE**: Flat resistance + rising support.

```
  ___________
  \          |     Flat top, rising bottom.
   \    _____|     Bullish bias.
    \  /
     \/
```

**DESCENDING TRIANGLE**: Flat support + falling resistance.

```
     /\
    /  \____       Falling top, flat bottom.
   /________|      Bearish bias.
```

**SYMMETRICAL TRIANGLE**: Both sides converging equally. Neutral until breakout.

```
     /\
    /  \
   / __ \
  / /  \ \
     \/
```

---

## Step 6: Slope and Width Validation

### 6a. Slope thresholds

All slopes are expressed as percentage price change per bar.

| Parameter | Short-Term (15-min) | Medium-Term (1-hour) | Long-Term (Daily) |
|-----------|---------------------|----------------------|-------------------|
| MIN_SLOPE | 0.005%/bar | 0.007%/bar | 0.01%/bar |
| MAX_SLOPE | 0.15%/bar | 0.30%/bar | 0.50%/bar |

### Numeric example: slope validation (long-term)

```
Primary line slope = 0.045% per bar (from our example)

MIN_SLOPE for daily = 0.01%
MAX_SLOPE for daily = 0.50%

0.01% < 0.045% < 0.50% --> VALID, within ideal range

steep_flag = false
```

### Numeric example: steep trendline warning

```
Primary line slope = 0.62% per bar (daily tier)

0.62% > MAX_SLOPE (0.50%) --> steep_flag = true

Action:
  1. Still draw the trendline (it defines current rate)
  2. Tag: steep_flag = true, sustainability_warning
  3. Draw secondary, shallower line using only earlier pivots
     (exclude most recent 1-2 pivots that caused steepening)
  4. A break of this steep line = rate-of-trend change, NOT necessarily reversal
```

### 6b. Width thresholds

Channel width is measured as a percentage of the midpoint price:

```
width_pct = (upper_line_price - lower_line_price) / midpoint x 100
```

| Parameter | Short-Term | Medium-Term | Long-Term |
|-----------|-----------|-------------|-----------|
| MIN_WIDTH_PCT | 1.0% | 1.5% | 2.0% |
| MAX_WIDTH_PCT | 15.0% | 20.0% | 30.0% |

### Numeric example: width validation (long-term)

```
At current bar (bar 220):
  Primary (lower) line:  0.0903 x 220 + $164.49 = $184.36
  Parallel (upper) line: 0.0903 x 220 + $174.13 = $193.99

  width_price = $193.99 - $184.36 = $9.63
  midpoint = ($193.99 + $184.36) / 2 = $189.18
  width_pct = $9.63 / $189.18 x 100 = 5.09%

  MIN_WIDTH_PCT (daily) = 2.0%
  MAX_WIDTH_PCT (daily) = 30.0%

  2.0% < 5.09% < 30.0% --> width_status = "VALID"
```

### ATR-based width cross-check

```
  channel_width_price = $9.63
  ATR(14) = $3.45

  width_in_ATRs = $9.63 / $3.45 = 2.79

  Required range: 2.0 to 8.0 ATRs
  2.0 < 2.79 < 8.0 --> VALID
```

### Edge case: channel too narrow

```
  width_price = $1.80, ATR(14) = $3.45
  width_in_ATRs = $1.80 / $3.45 = 0.52

  0.52 < 2.0 --> CHANNEL_TOO_NARROW
  Normal volatility will break this channel constantly -- not useful.
```

---

## Step 7: Support and Resistance Zones

S/R lines are horizontal. Sloped support/resistance is captured by the trend channel lines.

### 7a. Clustering pivots into zones

Collect all pivot highs (for resistance) and pivot lows (for support). Cluster nearby levels within a tolerance:

| Tier | ZONE_TOLERANCE_PCT | ATR Alternative |
|------|-------------------|-----------------|
| Short-term | 0.3% | 0.5 x ATR(14) |
| Medium-term | 0.4% | 0.5 x ATR(14) |
| Long-term | 0.5% | 0.5 x ATR(14) |

### Numeric example: clustering (long-term)

```
Pivot lows found at: $175.00, $174.80, $175.30, $182.40, $189.50

Tolerance = 0.5% of price = 0.5% x $175.00 = $0.875
Alternative: 0.5 x ATR(14) = 0.5 x $3.45 = $1.725

Use the larger of the two: $1.725

Cluster analysis:
  $174.80, $175.00, $175.30 --> all within $1.725 of each other --> CLUSTER 1
  $182.40 --> standalone (>$1.725 from nearest) --> CLUSTER 2
  $189.50 --> standalone --> CLUSTER 3

Cluster 1 zone:
  zone_upper = max($174.80, $175.00, $175.30) + 0.25 x ATR = $175.30 + $0.86 = $176.16
  zone_lower = min($174.80, $175.00, $175.30) - 0.25 x ATR = $174.80 - $0.86 = $173.94
  zone_midpoint = ($176.16 + $173.94) / 2 = $175.05
  touch_count = 3
```

### 7b. Zone scoring

```
zone_score = (touch_count x W_TOUCH) + (recency_score x W_RECENCY)
           + (volume_score x W_VOLUME) + (role_reversal_bonus x W_REVERSAL)

Weights: W_TOUCH=2.0, W_RECENCY=1.5, W_VOLUME=1.0, W_REVERSAL=3.0
```

### Numeric example: scoring Cluster 1

```
touch_count = 3
W_TOUCH = 2.0
Touch component = 3 x 2.0 = 6.0

Recency (exponential decay):
  decay_rate = 0.005 (per bar)
  Touch 1 at bar 78:  bars_ago = 260 - 78 = 182 --> exp(-0.005 x 182) = exp(-0.91) = 0.403
  Touch 2 at bar 133: bars_ago = 127                --> exp(-0.005 x 127) = exp(-0.635) = 0.530
  Touch 3 at bar 190: bars_ago = 70                 --> exp(-0.005 x 70) = exp(-0.35) = 0.705
  recency_score = 0.403 + 0.530 + 0.705 = 1.638
  Recency component = 1.638 x 1.5 = 2.457

Volume (normalized to average):
  Avg volume at touches = 5.2M, overall avg = 4.0M
  volume_score = 5.2 / 4.0 = 1.30
  Volume component = 1.30 x 1.0 = 1.30

Role reversal:
  Zone acted as both support AND resistance? YES (was resistance, then became support)
  role_reversal_bonus = 1
  Reversal component = 1 x 3.0 = 3.0

zone_score = 6.0 + 2.457 + 1.30 + 3.0 = 12.757

Minimum required: 4.0
12.757 >= 4.0 --> ZONE ACCEPTED
```

### 7c. Decay and weakening

**Time decay**: If a zone has not been retested within the decay window, its score is halved.

| Tier | DECAY_WINDOW |
|------|-------------|
| Short-term | 400 bars (~15 trading days) |
| Medium-term | 200 bars (~29 trading days) |
| Long-term | 120 bars (~6 months) |

```
Cluster 2 zone (single touch at bar 140, midpoint $182.40):
  touch_count = 1 --> fails minimum of 2 touches --> ZONE REJECTED
```

**Weakening with repeated tests**: After 3+ touches, each additional touch weakens the zone (the level is being eroded):

```
A zone with touch_count = 5:
  weakening_factor = 0.90 ^ (5 - 2) = 0.90 ^ 3 = 0.729
  zone_score *= 0.729

If original zone_score = 8.0:
  adjusted = 8.0 x 0.729 = 5.83
```

---

## Step 8: Breakout Confirmation

When `regime = "BREAK"`, the algorithm confirms the break using three filters. At least 2 of 3 must pass.

### Filter 1 -- Close filter

The bar must close beyond the breakout level. For higher confidence, 2 consecutive closes.

### Filter 2 -- ATR filter

Close must be beyond the level by at least `ATR_BREAKOUT_MULTIPLIER x ATR(14)`.

```
ATR_BREAKOUT_MULTIPLIER = 0.5 (same for all tiers)
```

### Filter 3 -- Volume filter

Volume on breakout bar must be >= `VOLUME_BREAKOUT_MULTIPLIER x avg_volume(20)`.

```
VOLUME_BREAKOUT_MULTIPLIER = 1.25 (same for all tiers)
```

### Numeric example: breakout confirmed

```
Resistance zone at $198.50
ATR(14) = $3.45
Average volume (20-bar) = 4.0M shares

Breakout bar:
  Close = $200.80
  Volume = 5.8M

Filter 1 (Close): $200.80 > $198.50 --> PASS
  Next bar also closes above: $201.20 > $198.50 --> 2 consecutive closes, strong confirmation

Filter 2 (ATR): $200.80 - $198.50 = $2.30
  Required: 0.5 x $3.45 = $1.725
  $2.30 >= $1.725 --> PASS

Filter 3 (Volume): 5.8M / 4.0M = 1.45
  Required: >= 1.25
  1.45 >= 1.25 --> PASS

Result: 3/3 filters pass --> BREAKOUT CONFIRMED
```

### Numeric example: false breakout

```
Resistance zone at $198.50
ATR(14) = $3.45
Average volume (20-bar) = 4.0M shares

Breakout bar:
  Close = $199.00
  Volume = 3.5M

Filter 1 (Close): $199.00 > $198.50 --> PASS (barely)

Filter 2 (ATR): $199.00 - $198.50 = $0.50
  Required: 0.5 x $3.45 = $1.725
  $0.50 < $1.725 --> FAIL

Filter 3 (Volume): 3.5M / 4.0M = 0.875
  Required: >= 1.25
  0.875 < 1.25 --> FAIL

Result: 1/3 filters pass --> BREAKOUT NOT CONFIRMED
```

### Time confirmation window

After a break is confirmed, price must stay beyond the structure for a minimum period:

| Tier | Confirmation Window |
|------|-------------------|
| Short-term | 4 bars (1 hour) |
| Medium-term | 3 bars (3 hours) |
| Long-term | 3 bars (3 trading days) |

If price returns inside the prior structure within this window:

```
Bar 1 after breakout: close = $200.80 (above $198.50) --> OK
Bar 2: close = $201.20 --> OK
Bar 3: close = $197.90 (below $198.50!) --> FAILED time confirmation

--> FALSE BREAKOUT --> reclassify regime as OTHERS
```

### Post-break behavior

After a confirmed break, the broken level becomes an S/R level with `role_reversal: true`. Price commonly retests the broken level (~60% of the time). The former resistance at $198.50 now becomes support.

---

## Step 9: Fan Principle

When a trendline is broken but the broader trend has not reversed, redraw at a shallower angle. Maximum 3 fan lines before a reversal is expected.

### Numeric example: fan iteration

```
--- Fan Line 1 (steepest) ---

Original uptrend line through:
  PL1 (bar 78, $172.30), PL2 (bar 133, $176.50), PL3 (bar 190, $182.40)
  slope = 0.0903 $/bar

Price breaks below this line at bar 210:
  Line value at bar 210 = 0.0903 x 210 + $164.49 = $183.45
  Actual low at bar 210 = $181.80
  $181.80 < $183.45 --> TRENDLINE BROKEN

--- Fan Line 2 (shallower) ---

Redraw using only pivots AFTER the break point (bar 210+):
  New pivots: PL4 (bar 225, $183.50), PL5 (bar 248, $185.20)
  Must also anchor to the original trend start if possible.
  Anchored through PL1 (bar 78, $172.30) and PL4 (bar 225, $183.50):
    slope = ($183.50 - $172.30) / (225 - 78) = $11.20 / 147 = 0.0762 $/bar

  Shallower than fan line 1 (0.0762 < 0.0903) --> Valid fan line

Price breaks below fan line 2 at bar 255:
  Line at 255 = 0.0762 x 255 + ... --> broken
  --> SECOND FAN LINE BROKEN

--- Fan Line 3 (shallowest) ---

Redraw again with even later pivots:
  New pivot: PL6 (bar 258, $184.00)
  slope = ($184.00 - $172.30) / (258 - 78) = $11.70 / 180 = 0.065 $/bar

If fan line 3 also breaks:
  --> FAN EXHAUSTED (3 fan lines broken)
  --> trend_reversal_signal = true
  --> Reclassify regime (likely OTHERS or opposite-direction TREND)
```

Visually:

```
Price
  |                          .
  |                       . /  <-- Fan 3 (shallowest)
  |                    . / /
  |                 . / / /   <-- Fan 2
  |              . / / /
  |           . / / /         <-- Fan 1 (steepest, original)
  |        . / / /
  |     . / / /
  |  PL1
  |________________________________
                Bar index
```

---

## Step 10: Multi-Tier Interaction

After all three tiers are analyzed independently, this layer compares regimes across tiers.

### Confluence example: full bullish

```
Long-term:   TREND (UPTREND),  R-squared = 0.91
Medium-term: TREND (UPTREND),  R-squared = 0.72
Short-term:  BREAK (BREAKOUT upward)

All tiers agree on bullish direction:
  confluence = "FULL_BULLISH"
  conviction = "HIGH"
  dominant_bias = "BULLISH"
```

### Conflict example: pullback within uptrend

```
Long-term:   TREND (UPTREND)
Medium-term: OTHERS (SIDEWAYS)
Short-term:  TREND (DOWNTREND)

Interpretation: Classic pullback within an uptrend.
  The short-term downtrend is a counter-trend move within the long-term uptrend.
  The medium-term sideways confirms consolidation.

  confluence = "PARTIAL_BULLISH"
  conviction = "MEDIUM"
  dominant_bias = "BULLISH"
  conflicts = [{
    tiers: [long_term, short_term],
    type: "DIRECTION_CONFLICT",
    interpretation: "Short-term counter-trend move within long-term uptrend"
  }]
```

### Tier dominance rule

When tiers conflict, the higher tier provides the bias, the lower tier provides the timing:

```
Long-term  --> Overall bias (bullish/bearish/neutral)
Medium-term --> Swing direction (which side of the channel to trade)
Short-term  --> Entry/exit precision (exactly when to act)

A short-term SELL signal in a long-term UPTREND:
  --> Lower conviction, tighter stops
  --> Treat as potential pullback entry, not a reversal trade

A short-term BUY signal in a long-term UPTREND:
  --> Higher conviction, wider stops
  --> Trend-aligned trade with full position size
```

### Stop selection by tier

| Holding Period | Primary Stop Source | Context |
|---------------|-------------------|---------|
| Intraday to a few days | Short-term channel line | Medium-term direction |
| A few days to a few weeks | Medium-term channel line | Long-term direction |
| A few weeks to months | Long-term channel line or major S/R | -- |

---

## Step 11: Reading the Report

### Output structure

The algorithm produces one JSON per ticker containing:

```
{
  "ticker": "AAPL",
  "short_term":  { regime, channel, S/R zones, fan lines, ... },
  "medium_term": { regime, channel, S/R zones, fan lines, ... },
  "long_term":   { regime, channel, S/R zones, fan lines, ... },
  "multi_tier_interaction": { confluence, conviction, conflicts, ... },
  "status": "SUCCESS"
}
```

### Key fields per tier

| Field | What it tells you |
|-------|------------------|
| `regime.state` | TREND, BREAK, or OTHERS |
| `regime.trend_direction` | UPTREND or DOWNTREND (TREND only) |
| `regime.r_squared` | How well pivots fit a line (0.0 to 1.0; higher = cleaner trend) |
| `trend_channel.channel_geometry` | PARALLEL, RISING_WEDGE, FALLING_WEDGE, BROADENING, TRIANGLE |
| `trend_channel.steep_flag` | true = unsustainably steep, break expected |
| `trend_channel.channel_width_pct` | Width as % of price; too narrow = noise, too wide = useless |
| `trend_channel.current_price_position.pct_within_channel` | 0% = at lower line, 100% = at upper line |
| `support_resistance_zones[].zone_score` | Higher = stronger zone |
| `support_resistance_zones[].role_reversal` | true = former support became resistance (or vice versa) |

### Current price position within the channel

```
                     Upper line (resistance)
  100% ──────────────────────────────────
                                          Price at 62.1%
                                          (upper half = "MID_UPPER")
   50% ──────────────────────────────────

    0% ──────────────────────────────────
                     Lower line (support)

Zones:
  0-25%:   LOWER_QUARTER  (near support -- potential buy zone in uptrend)
  25-50%:  LOWER_HALF
  50-75%:  MID_UPPER
  75-100%: UPPER_QUARTER  (near resistance -- potential sell zone in uptrend)
```

### Projected values

The report projects where the channel lines will be at the next bar:

```
"projected_values": {
  "next_bar": {
    "primary_line_price": $189.20,    <-- where the support line will be tomorrow
    "opposite_line_price": $202.50    <-- where the resistance line will be tomorrow
  }
}
```

---

## Edge Cases Summary

### Not enough pivots

```
After all filtering: 2 pivot lows, 1 pivot high.
2 < 3 (minimum for primary side)

Action 1: Widen lookback by 50% (e.g., 260 days --> 390 days) and rerun.
Action 2: If still insufficient --> regime = "OTHERS", sub_type = "INSUFFICIENT_DATA"
```

### Steep trendline

```
Slope = 0.62%/bar (daily), MAX_SLOPE = 0.50%/bar

Output:
  steep_flag = true
  sustainability_warning = "Trendline slope exceeds sustainable rate"
  secondary_trendline = shallower line from earlier pivots only
  interpretation = "A break of this steep line is expected and
                    represents a rate-of-trend change, not necessarily reversal"
```

### False breakout --> reclassify

```
Price breaks above $198.50 resistance.
Filter 1 (close) passes, Filter 2 (ATR) fails, Filter 3 (volume) fails.
Only 1/3 filters pass --> breakout NOT confirmed.

OR: breakout confirmed but price returns below $198.50 within
the time confirmation window (3 bars for daily).

--> Reclassify regime as OTHERS
--> The $198.50 level remains as resistance (not broken)
```

### Fan exhaustion --> reversal signal

```
Fan line 1 (steepest): BROKEN at bar 210
Fan line 2 (shallower): BROKEN at bar 255
Fan line 3 (shallowest): BROKEN at bar 270

3 fan lines broken --> FAN_EXHAUSTED
trend_reversal_signal = true

Action: Reclassify regime.
  If new downtrend pivots forming --> regime = "TREND", direction = "DOWNTREND"
  If unclear --> regime = "OTHERS", sub_type = "TRANSITIONAL"
```

### IPO / recently listed stock

```
Data history = 45 trading days

Long-term tier (needs 260 days): INSUFFICIENT_DATA
Medium-term tier (needs 60 days): INSUFFICIENT_DATA
Short-term tier (needs 20 days): Can function normally

Only short-term analysis is available.
```

### Large gap (earnings, overnight)

```
Gap size = $8.50, ATR(14) = $3.45
$8.50 > 2 x $3.45 = $6.90 --> GAP detected

Actions:
  - Gap bar is NOT treated as a pivot point
  - Draw S/R at gap boundaries (gap top and gap bottom)
  - Use post-gap prices for trendline fitting
    (unless pre-gap trend is clearly continuing)
```

### Regime transitions

```
TREND --> BREAK:
  The broken trendline becomes an S/R level with role_reversal = true

OTHERS --> TREND:
  The horizontal range boundaries become S/R context for the new channel

BREAK --> TREND:
  The break level and pullback/throwback level become key S/R
```
