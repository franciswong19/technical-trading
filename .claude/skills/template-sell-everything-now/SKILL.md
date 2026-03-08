---
name: template-sell-everything-now
description: Print the SELL EVERYTHING NOW request template — emergency liquidation of all positions
---

Print the following template exactly as shown:

```
Trading account: <account_id (port XXXX)>
Exchange: US / XETRA / EURONEXT
Request type: SELL EVERYTHING NOW
```

Then tell the user:
- This liquidates **ALL open positions** in the specified account immediately.
- Select only ONE exchange per request (US, XETRA, or EURONEXT).
- For multiple accounts on the same exchange, separate with commas (e.g. U1234567 (port 4001), U8765432 (port 4003)).
- **Fixed defaults (do not specify):** Transaction type = SELL, Duration = IMMED, Fulfillment = 100%, Initial order type = Market.
- **Not applicable:** Ticker, Subsequent order type, Stop type, Cycle threshold.
