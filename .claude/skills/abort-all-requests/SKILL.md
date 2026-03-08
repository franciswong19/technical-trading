---
name: abort-all-requests
description: Abort ALL in-flight trade requests — stops all executor processes and cancels all pending entry orders on IBKR
---

The user wants to abort ALL in-flight trade requests. Follow these steps exactly:

## Step 1: Warn the User

Tell the user:
> "This will abort ALL in-flight requests — stopping all executor processes and cancelling all pending entry orders. Stop-loss orders protecting filled positions will remain active. Proceed?"

Wait for explicit confirmation ("yes") before continuing.

## Step 2: Kill All Executor Tasks

Use `TaskList` to find all currently running tasks. Identify any tasks whose description contains executor keywords:
- `normal_buy`, `normal_sell`, `fast_buy`, `fast_sell`, `hot_potato`, `sell_everything`

Call `TaskStop` on each matching task. Report how many tasks were stopped.

## Step 3: Cancel All IBKR Entry Orders

Run:
```
python -m trade_executor.abort --all
```

Read the full output carefully.

## Step 4: Report to User

Report:
1. Which executor tasks were stopped (Step 2)
2. Which IBKR entry orders were cancelled per account per ticker

Then report the **Active orders still on IBKR** section from the script output. These are all remaining open orders — stop-losses from today's requests and any older ones:
- Present each order's details: ticker, action, order type, price, order ID
- If the script annotated an order with `[today: <request_id>]`, mention which of today's request IDs it belongs to
- Make clear these orders are active and protecting positions — they were intentionally preserved

Example format:
```
ACTIVE ORDERS STILL ON IBKR
[Account U1234567]
  - TQQQ — SELL STP @ $45.20 (order ID: 123456) [today's request: 20260307-002]
  - AMZN — SELL STP @ $180.00 (order ID: 123457) [from a previous day]
These are all valid and continue to protect your positions.
```

If the script printed any `MANUAL ACTION REQUIRED` lines, surface them prominently — these are entry orders that the API could not cancel (e.g. placed from a different session). Tell the user the exact order details and that they must cancel those manually via IB Gateway.

If any errors occurred connecting to IBKR or cancelling orders, report those too.

**IMPORTANT:** Only entry orders (unfilled buys/sells) were cancelled. All remaining stop-loss orders are still active on IBKR.

**NOTE:** SELL_EVERYTHING_NOW requests cannot be aborted — the script will skip them and say so. Tell the user to manage those manually in IB Gateway.
