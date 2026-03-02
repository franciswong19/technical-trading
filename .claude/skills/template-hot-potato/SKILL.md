---
name: template-hot-potato
description: Print the HOT POTATO request template — cycle-based buy/sell with dual trailing stops on a single ticker
---

Print the following template exactly as shown:

```
Trading account:
Exchange: US / XETRA / EURONEXT
Request type: HOT POTATO
Transaction type: BUY / SELL
Transaction type before close: BUY / SELL
Duration: XX MINS

--- Ticker ---
Ticker:
Fulfillment: <1% - 100%>
Initial Order type: midprice / trailing stop at X.X%
Subsequent Order type: trailing stop at X.X%
Stop type: ADHOC trailing stop at X.X%
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
- **Initial Order type**: the order used to enter the position (midprice or trailing stop).
- **Subsequent Order type**: the trailing stop used to exit/re-enter on each cycle — this is **required**.
- **Stop type**: the ADHOC trailing stop percentage that acts as the hard stop loss for the whole session (e.g. ADHOC trailing stop at 2.5%).
- **Cycle threshold**: how many cycles before stopping (default is 3 if omitted).
