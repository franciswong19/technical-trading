---
name: template-normal-buy
description: Print the NORMAL BUY request template — standard buy with 10-min monitoring before market close
---

Print the following template exactly as shown:

```
Trading account: <account_id (port XXXX)>
Exchange: US / XETRA / EURONEXT
Request type: NORMAL BUY
Duration: BEFORE CLOSE

--- Ticker 1 ---
Ticker:
Fulfillment: <1% - 100%>
Initial Order type: midprice / trailing stop at X.X% / trailing stop at X.X% with threshold price XX.XX / fixed stop at XX.XX
Stop type: NORMAL / HEIGHTENED / FIXED PRICE AT XX.XX

--- Ticker 2 ---
Ticker:
Fulfillment: <1% - 100%>
Initial Order type: midprice / trailing stop at X.X% / trailing stop at X.X% with threshold price XX.XX / fixed stop at XX.XX
Stop type: NORMAL / HEIGHTENED / FIXED PRICE AT XX.XX
```

Then tell the user:
- Add or remove ticker blocks as needed. Multiple tickers are supported.
- For multiple accounts, separate with commas (e.g. U1234567 (port 4001), U8765432 (port 4003)).
- **Fixed defaults (do not specify):** Transaction type = BUY, Duration = BEFORE CLOSE.
- **Not applicable:** Subsequent order type, Cycle threshold.
- **Initial order type reference:**
  - `midprice` = place a midprice limit order immediately
  - `trailing stop at X.X%` = place a trailing stop immediately (replace X.X with percentage)
  - `trailing stop at X.X% with threshold price XX.XX` = only place a trailing stop once price drops **below** XX.XX; at the 3:45 PM deadline if price is below XX.XX a market order is placed instead; if price never drops below XX.XX no order is placed
  - `fixed stop at XX.XX` = poll every 5 min; place a **market order immediately** once price rises **at or above** XX.XX; at the 3:45 PM deadline if price is at or above XX.XX a market order is placed; if price never reaches XX.XX no order is placed
- **Stop type reference:**
  - NORMAL = stop loss placed 8% below the fill price
  - HEIGHTENED = stop loss placed 3% below the fill price
  - FIXED PRICE AT XX.XX = stop loss placed at an exact price (replace XX.XX with the price)
- A stop loss is **mandatory** for every buy order.
