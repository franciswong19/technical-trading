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
- **All 11 parameters are applicable** to HOT POTATO (the only request type that uses all of them).
- **Initial Order type**: the order used to enter the position (midprice or trailing stop).
- **Subsequent Order type**: the trailing stop used to exit/re-enter on each cycle — this is **required**.
- **Stop type**: the ADHOC trailing stop percentage that acts as the hard stop loss for the whole session (e.g. ADHOC trailing stop at 2.5%).
- **Cycle threshold**: how many cycles before stopping (default is 3 if omitted).
