---
name: template-fast-sell
description: Print the FAST SELL request template — time-limited sell with 1-min monitoring at midprice
---

Print the following template exactly as shown:

```
Trading account: LIVE-US, LIVE-US-2, LIVE-EU
Exchange: US / XETRA / EURONEXT
Request type: FAST SELL
Duration: XX MINS

--- Ticker 1 ---
Ticker:
Fulfillment: <1% - 100%>

--- Ticker 2 ---
Ticker:
Fulfillment: <1% - 100%>
```

Then tell the user:
- Duration must be **at least 3 minutes** (replace XX with a number >= 3).
- Add or remove ticker blocks as needed. Multiple tickers are supported.
- For multiple accounts, separate with commas (e.g. LIVE-US, LIVE-US-2).
- **Fixed defaults (do not specify):** Transaction type = SELL, Initial order type = Midprice.
- **Not applicable:** Subsequent order type, Stop type, Cycle threshold.
