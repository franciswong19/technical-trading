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
Initial Order type: midprice / trailing stop at X.X%

--- Ticker 2 ---
Ticker:
Fulfillment: <1% - 100%>
Initial Order type: midprice / trailing stop at X.X%
```

Then tell the user:
- Add or remove ticker blocks as needed. Multiple tickers are supported.
- For multiple accounts, separate with commas (e.g. U11871718, U13868670).
- **Fixed defaults (do not specify):** Transaction type = SELL, Duration = BEFORE CLOSE.
- **Not applicable:** Subsequent order type, Stop type, Cycle threshold.
