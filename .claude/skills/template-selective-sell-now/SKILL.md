---
name: template-selective-sell-now
description: Print the SELECTIVE SELL NOW request template — immediate market sell of specified tickers only
---

Print the following template exactly as shown:

```
Trading account: <account_id (port XXXX)>
Exchange: US / XETRA / EURONEXT
Request type: SELECTIVE SELL NOW
Tickers: <TICKER1, TICKER2, ...>
```

Then tell the user:
- This immediately market-sells **only the specified tickers** (unlike SELL EVERYTHING NOW which liquidates all positions).
- Tickers not found in the portfolio are skipped with a non-fatal warning — no error, just noted in the result.
- Select only ONE exchange per request (US, XETRA, or EURONEXT).
- For multiple accounts on the same exchange, separate with commas (e.g. U1234567 (port 4001), U8765432 (port 4003)).
- **Fixed defaults (do not specify):** Transaction type = SELL, Duration = IMMED, Fulfillment = 100%, Initial order type = Market.
- **Not applicable:** Subsequent order type, Stop type, Cycle threshold.
