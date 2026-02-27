---
name: template
description: Print the trade execution request template for the user to fill in
---

Tell the user that there are now specific templates for each request type, and list them:

- `/template-sell-everything-now` — Emergency liquidation of all positions
- `/template-normal-buy` — Standard buy with 10-min monitoring, before close
- `/template-normal-sell` — Standard sell with 10-min monitoring, before close
- `/template-fast-buy` — Time-limited buy at midprice with 1-min monitoring
- `/template-fast-sell` — Time-limited sell at midprice with 1-min monitoring
- `/template-hot-potato` — Cycle-based buy/sell with dual trailing stops, single ticker

Tell the user to run the specific command for the request type they want to use.
