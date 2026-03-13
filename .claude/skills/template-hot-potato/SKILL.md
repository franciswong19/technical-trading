---
name: template-hot-potato
description: Print the HOT POTATO request template — cycle-based buy/sell with dual trailing stops on a single ticker
---

Print the following template exactly as shown:

```
Trading account: <account_id (port XXXX)>
Exchange: US / XETRA / EURONEXT
Request type: HOT POTATO
Transaction type: BUY / SELL
Transaction type before close: BUY / SELL
Duration: XX MINS

--- Ticker ---
Ticker:
Fulfillment: <1% - 100%>
Initial Order type: midprice / trailing stop at X.X% / trailing stop at X.X% with threshold price XX.XX / fixed stop at XX.XX
Subsequent Order type: trailing stop at X.X%
Stop type 1: fixed stop at X.X%
Stop type 2: ADHOC trailing stop at X.X%
Cycle threshold: <number, default 3>
```

Then tell the user:
- HOT POTATO supports **exactly one ticker** — no additional ticker blocks.
- Duration must be **at least 3 minutes** (replace XX with a number >= 3).
- **No fixed defaults** — all parameters in the template must be specified by the user.
- **Transaction type**: direction of each cycle's entry order (BUY or SELL).
- **Transaction type before close**: desired position state at end-of-day. **Required. May differ from Transaction type.** All four combinations are valid:
  - BUY / BUY — cycle buys during session, end the day **holding** (overnight position)
  - BUY / SELL — cycle buys during session, go **flat before close** (no overnight exposure)
  - SELL / SELL — cycle sells/reduce during session, end **flat**
  - SELL / BUY — cycle sells during session, **buy back** to ensure holding at close
- **Initial Order type**: the order used to enter the position on cycle 0:
  - `midprice` = place midprice order immediately
  - `trailing stop at X.X%` = place trailing stop immediately
  - `trailing stop at X.X% with threshold price XX.XX` = for BUY, only place trailing stop once price drops below XX.XX; for SELL, once price rises above XX.XX; at the timed deadline if condition is met a market order is placed; only applies to cycle 0 — subsequent cycles always use the Subsequent Order type directly
  - `fixed stop at XX.XX` = for BUY, place a market order immediately once price rises at or above XX.XX; for SELL, once price falls at or below XX.XX; no trailing stop — market order fires directly on trigger; only applies to cycle 0
- **Subsequent Order type**: the trailing stop used to exit/re-enter on each cycle — this is **required**.
- **Stop type 1**: a fixed stop placed at X.X% offset from the fill price (e.g. `fixed stop at 1.5%`). For BUY cycles: stop is X.X% below fill price (SELL stop). For SELL cycles: stop is X.X% above fill price (BUY stop).
- **Stop type 2**: the ADHOC trailing stop percentage that acts as the hard stop loss for the whole session (e.g. `ADHOC trailing stop at 2.5%`).
- **Cycle threshold**: how many cycles before stopping (default is 3 if omitted).
