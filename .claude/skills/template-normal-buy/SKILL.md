---
name: template-normal-buy
description: Print the NORMAL BUY request template — standard buy with 10-min monitoring before market close
---

Print the following template exactly as shown:

```
Trading account: LIVE-US, LIVE-US-2, LIVE-EU
Exchange: US / XETRA / EURONEXT
Request type: NORMAL BUY
Duration: BEFORE CLOSE

--- Ticker 1 ---
Ticker:
Fulfillment: <1% - 100%>
Initial Order type: midprice / trailing stop at X.X%
Stop type: NORMAL / HEIGHTENED / FIXED PRICE AT XX.XX

--- Ticker 2 ---
Ticker:
Fulfillment: <1% - 100%>
Initial Order type: midprice / trailing stop at X.X%
Stop type: NORMAL / HEIGHTENED / FIXED PRICE AT XX.XX
```

Then tell the user:
- Add or remove ticker blocks as needed. Multiple tickers are supported.
- For multiple accounts, separate with commas (e.g. LIVE-US, LIVE-US-2).
- **Fixed defaults (do not specify):** Transaction type = BUY, Duration = BEFORE CLOSE.
- **Not applicable:** Subsequent order type, Cycle threshold.
- **Stop type reference:**
  - NORMAL = stop loss placed 8% below the fill price
  - HEIGHTENED = stop loss placed 3% below the fill price
  - FIXED PRICE AT XX.XX = stop loss placed at an exact price (replace XX.XX with the price)
- A stop loss is **mandatory** for every buy order.
