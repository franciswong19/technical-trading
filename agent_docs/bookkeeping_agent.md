# Book-keeping Sub-Agent Reference

## Role
Records trade execution results to Google Sheets after each completed request. Uses the existing `utils/utils_gsheet_handler.py` for authentication and data export.

## Invocation
```
python -m trade_executor.trade_recorder --result <path_to_result.json>
```

## Google Sheet: "Trade Execution Log"
Spreadsheet ID configured in `trade_executor/config.py` as `EXECUTION_LOG_SPREADSHEET_ID`.

### Tab: Execution Log
One row per account + ticker + sequence number.
- **Unique key**: Request ID + Account ID + Ticker + Seq #
- Seq # = 1 for most types; increments for HOT POTATO cycles

Columns: Request ID, Seq #, Timestamp, Account ID, Ticker, Action, Request Type, Target Qty, Filled Qty, Avg Fill Price, Order Type Used, Escalated to Market, Stop Loss Placed, Stop Loss Price, Stop Type, Fulfillment %, Portfolio Value, Exchange, Duration Type, Error

### Tab: Daily Summary
Aggregated per request (one row per execution).
- **Unique key**: Date (aggregated manually if multiple requests per day)

Columns: Date, Total Requests, Total Orders, Total Filled, Total Failed, Total Buy Value, Total Sell Value, Escalation Count

### Tab: Errors
Append-only event log (no unique key).

Columns: Timestamp, Request ID, Account ID, Ticker, Error Type, Error Message

### Tab: Stop Loss Tracker
Active stop loss orders for monitoring.
- **Unique key**: Request ID + Account ID + Ticker + Seq #

Columns: Request ID, Seq #, Account ID, Ticker, Buy Price, Stop Type, Stop Price, Placed At, Status

## Recording Logic
1. Read the result JSON
2. Authenticate to Google Sheets
3. For each account_result -> ticker_result, append one row to Execution Log
4. If errors exist, append to Errors tab
5. If buy orders with stops, append to Stop Loss Tracker
6. Append summary row to Daily Summary
