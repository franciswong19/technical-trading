---
name: template-normal-sell
description: Print the NORMAL SELL request template — standard sell with 10-min monitoring before market close
---

Print the following template exactly as shown:

```
Trading account:
Exchange: US / XETRA / EURONEXT
Request type: NORMAL SELL
Duration: BEFORE CLOSE

--- Ticker 1 ---
Ticker:
Fulfillment: <1% - 100%>
Initial Order type: midprice / trailing stop at X.X% / trailing stop at X.X% with threshold price XX.XX

--- Ticker 2 ---
Ticker:
Fulfillment: <1% - 100%>
Initial Order type: midprice / trailing stop at X.X% / trailing stop at X.X% with threshold price XX.XX
```

Then tell the user:
- Add or remove ticker blocks as needed. Multiple tickers are supported.
- For multiple accounts, separate with commas (e.g. U11871718, U13868670).
- **Fixed defaults (do not specify):** Transaction type = SELL, Duration = BEFORE CLOSE.
- **Not applicable:** Subsequent order type, Stop type, Cycle threshold.
- **Initial order type reference:**
  - `midprice` = place a midprice limit order immediately
  - `trailing stop at X.X%` = place a trailing stop immediately (replace X.X with percentage)
  - `trailing stop at X.X% with threshold price XX.XX` = only place a trailing stop once price rises **above** XX.XX; at the 3:45 PM deadline if price is above XX.XX a market order is placed instead; if price never rises above XX.XX no order is placed
