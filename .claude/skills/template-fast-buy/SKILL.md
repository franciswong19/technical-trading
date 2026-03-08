---
name: template-fast-buy
description: Print the FAST BUY request template — time-limited buy with 1-min monitoring at midprice
---

Print the following template exactly as shown:

```
Trading account: <account_id (port XXXX)>
Exchange: US / XETRA / EURONEXT
Request type: FAST BUY
Duration: XX MINS

--- Ticker 1 ---
Ticker:
Fulfillment: <1% - 100%>
Stop type: NORMAL / HEIGHTENED / FIXED PRICE AT XX.XX

--- Ticker 2 ---
Ticker:
Fulfillment: <1% - 100%>
Stop type: NORMAL / HEIGHTENED / FIXED PRICE AT XX.XX
```

Then tell the user:
- Duration must be **at least 3 minutes** (replace XX with a number >= 3).
- Add or remove ticker blocks as needed. Multiple tickers are supported.
- For multiple accounts, separate with commas (e.g. U1234567 (port 4001), U8765432 (port 4003)).
- **Fixed defaults (do not specify):** Transaction type = BUY, Initial order type = Midprice.
- **Not applicable:** Subsequent order type, Cycle threshold.
- **Stop type reference:**
  - NORMAL = stop loss placed 8% below the fill price
  - HEIGHTENED = stop loss placed 3% below the fill price
  - FIXED PRICE AT XX.XX = stop loss placed at an exact price (replace XX.XX with the price)
- A stop loss is **mandatory** for every buy order.
