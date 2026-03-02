# Agentic Trade Execution System

A Claude Code-powered agentic system for executing live stock trades on **US (NYSE/NASDAQ)**, **XETRA**, and **Euronext** exchanges via Interactive Brokers.

## Table of Contents

- [Architecture](#architecture)
- [Directory Structure](#directory-structure)
- [Setup](#setup)
- [Usage](#usage)
  - [Template Request](#template-request)
  - [Execution Request](#execution-request)
- [Request Types](#request-types)
  - [SELL EVERYTHING NOW](#1-sell-everything-now)
  - [NORMAL BUY](#2-normal-buy)
  - [NORMAL SELL](#3-normal-sell)
  - [FAST BUY](#4-fast-buy)
  - [FAST SELL](#5-fast-sell)
  - [HOT POTATO](#6-hot-potato)
- [Prompt Template](#prompt-template)
- [Execution Workflow](#execution-workflow)
- [Module Reference](#module-reference)
  - [config.py](#configpy)
  - [ibkr_client.py](#ibkr_clientpy)
  - [quantity_calculator.py](#quantity_calculatorpy)
  - [order_monitor.py](#order_monitorpy)
  - [stop_loss_manager.py](#stop_loss_managerpy)
  - [order_factory.py](#order_factorypy)
  - [request_id.py](#request_idpy)
  - [trade_recorder.py](#trade_recorderpy)
  - [Data Models](#data-models)
- [Executor Scripts](#executor-scripts)
- [Google Sheet Structure](#google-sheet-structure)
- [Exchange Support](#exchange-support)
- [Multi-Account Mirroring](#multi-account-mirroring)
- [Stop Types](#stop-types)
- [Error Handling](#error-handling)
- [Safety Rules](#safety-rules)
- [Configuration Reference](#configuration-reference)

---

## Architecture

The system consists of three agents communicating via JSON files on disk:

```
User (terminal)
  |
  v
Main Agent (Claude, guided by CLAUDE.md)
  |  - Parses and validates user requests
  |  - Generates request IDs (YYYYMMDD-XXX)
  |  - Shows confirmation summary, waits for "yes"
  |  - Dispatches execution, verifies results
  |
  |---> Execution Sub-Agent (Python executor scripts)
  |       |  - Connects to IBKR via ib_insync
  |       |  - Places orders (midprice, market, trailing stop)
  |       |  - Runs monitoring loops (fill detection, qty recalculation)
  |       |  - Handles deadline escalation to market orders
  |       |  - Places stop losses (with 15-minute delay)
  |       |  - Writes result JSON on completion
  |
  |---> Book-keeping Sub-Agent (trade_recorder.py)
          |  - Reads result JSON
          |  - Authenticates to Google Sheets
          |  - Appends execution records across 4 tabs
```

**Key design principle**: Python scripts handle all time-sensitive operations (monitoring loops, order modification, stop placement). Claude handles orchestration, validation, and verification. This ensures reliable execution even for long-running requests.

---

## Directory Structure

```
TechnicalTrading/
  CLAUDE.md                                  # Main agent instructions
  .claude/commands/
    template.md                              # /template slash command
  agent_docs/
    execution_agent.md                       # Execution sub-agent reference
    bookkeeping_agent.md                     # Book-keeping sub-agent reference
  utils/
    utils_ibkr_portfolio.py                  # IBKR portfolio functions (connect, positions, summary)
    utils_ibkr_trading_execution.py          # IBKR trading functions (orders, prices, calendars)
    utils_gsheet_handler.py                  # Google Sheets auth & read/write (existing)
  trade_executor/
    __init__.py
    README.md                                # This file
    config.py                                # Central configuration
    ibkr_client.py                           # IBKRClient class (all broker interactions)
    quantity_calculator.py                   # Buy/sell qty calculations + cash validation
    order_factory.py                         # IBKR Order object creation
    order_monitor.py                         # Polling loop engine (exchange-aware deadlines)
    stop_loss_manager.py                     # Stop loss placement + 15-min delay timer
    request_id.py                            # YYYYMMDD-XXX ID generator
    trade_recorder.py                        # Google Sheets book-keeping
    models/
      __init__.py
      request.py                             # TradeRequest & TickerParams dataclasses
      execution_result.py                    # ExecutionResult & TickerResult dataclasses
    executors/
      __init__.py
      sell_everything.py                     # SELL EVERYTHING NOW
      normal_buy.py                          # NORMAL BUY
      normal_sell.py                         # NORMAL SELL
      fast_buy.py                            # FAST BUY
      fast_sell.py                           # FAST SELL
      hot_potato.py                          # HOT POTATO
    state/                                   # Runtime state (gitignored)
      request_counter.json                   # {"date": "YYYYMMDD", "last_seq": N}
      requests/                              # Input JSONs written by Claude
      results/                               # Output JSONs written by executors
      status/                                # Live status updates (future use)
```

---

## Setup

### Prerequisites

- Python 3.10+
- Interactive Brokers TWS or IB Gateway running locally
- IBKR account(s) with API access enabled
- Google Cloud service account with Sheets API access

### Python Dependencies

```
ib_insync
pandas
pandas_market_calendars
pytz
gspread
oauth2client
```

### Configuration Steps

1. **IBKR Accounts**: Edit `trade_executor/config.py` and update the `ACCOUNTS` dictionary:
   ```python
   ACCOUNTS = {
       'LIVE-US': {'account_id': 'U13868670', 'port': 7496},
       # Add more accounts as needed:
       # 'LIVE-EU': {'account_id': 'UXXXXXXX', 'port': 7496},
   }
   ```

2. **Google Sheet**: Create a new Google Sheet named "Trade Execution Log". Share it with your service account email. Copy the spreadsheet ID from the URL and set it in `config.py`:
   ```python
   EXECUTION_LOG_SPREADSHEET_ID = 'your-spreadsheet-id-here'
   ```

3. **Credentials**: Ensure `creds/service_account_key.json` exists for Google Sheets authentication.

4. **IBKR TWS/Gateway**: Must be running on `127.0.0.1:7496` (live) with API connections enabled in TWS settings.

---

## Usage

### Template Request

Type `/template` in Claude Code to get a blank prompt template to fill in.

### Execution Request

Paste a filled-in template or describe your trade in natural language. Claude will:

1. Parse your request
2. Validate all fields
3. Show a confirmation summary
4. Wait for your explicit "yes"
5. Execute the trade
6. Report results
7. Record to Google Sheets

**Example**:
```
Trading account: LIVE-US
Exchange: US
Request type: FAST BUY
Transaction type: BUY
Duration: 10 MINS

--- Ticker 1 ---
Ticker: AAPL
Fulfillment: 5%
Initial Order type: midprice
Stop type: NORMAL

--- Ticker 2 ---
Ticker: MSFT
Fulfillment: 3%
Initial Order type: midprice
Stop type: HEIGHTENED
```

---

## Request Types

### 1. SELL EVERYTHING NOW

**Purpose**: Emergency liquidation of all positions in the specified account(s).

| Field | Value |
|-------|-------|
| Tickers | N/A (sells all positions) |
| Transaction | SELL (fixed) |
| Fulfillment | 100% (fixed) |
| Order type | Market (fixed) |
| Stop type | N/A |
| Duration | IMMED |

**Execution flow**:
1. Connect to each account
2. Cancel ALL open orders
3. Retrieve all current positions
4. Place market sell orders for every position
5. Wait up to 60 seconds per order for fill
6. Report results

---

### 2. NORMAL BUY

**Purpose**: Standard buy with patient monitoring. Designed for orders where you want to get a good fill price but need guaranteed execution by end of day.

| Field | Value |
|-------|-------|
| Tickers | Multiple (per-ticker params) |
| Transaction | BUY |
| Fulfillment | 1% - 100% of portfolio value |
| Order type | Midprice OR Trailing Stop at X.X% |
| Stop type | NORMAL / HEIGHTENED / FIXED PRICE |
| Duration | BEFORE CLOSE |

**Execution flow**:
1. For each account, get portfolio value and cash value
2. **Cash check**: Verify `cash >= portfolio_value * fulfillment_pct`
3. Calculate qty: `floor(portfolio_value * fulfillment_pct / current_price)`
4. Place midprice or trailing stop order
5. **Monitor every 10 minutes**:
   - **If filled** → Start 15-minute timer → Place stop loss according to stop type
   - **If not filled** → Get current price, recalculate qty, modify order
   - **At exchange cutoff (15 min before close)** → Recalculate qty, switch to market order
6. Exit when all tickers filled

---

### 3. NORMAL SELL

**Purpose**: Standard sell with patient monitoring. Same timing as NORMAL BUY but for selling positions.

| Field | Value |
|-------|-------|
| Tickers | Multiple (per-ticker params) |
| Transaction | SELL |
| Fulfillment | 1% - 100% of current holdings |
| Order type | Midprice OR Trailing Stop at X.X% |
| Stop type | N/A |
| Duration | BEFORE CLOSE |

**Execution flow**:
1. For each account, get current holdings per ticker
2. Calculate qty: `floor(current_holdings * fulfillment_pct)`
3. Place midprice or trailing stop order
4. **Monitor every 10 minutes**:
   - **If sold** → Done for that ticker
   - **At exchange cutoff (15 min before close)** → Switch to market order

---

### 4. FAST BUY

**Purpose**: Time-sensitive buy with aggressive monitoring. For when you need to buy quickly within a specific time window.

| Field | Value |
|-------|-------|
| Tickers | Multiple (per-ticker params) |
| Transaction | BUY |
| Fulfillment | 1% - 100% of portfolio value |
| Order type | Midprice (fixed) |
| Stop type | NORMAL / HEIGHTENED / FIXED PRICE |
| Duration | XX MINS (minimum 3) |

**Execution flow**:
Same as NORMAL BUY but:
- **1-minute** check interval (instead of 10 minutes)
- **Timed deadline** (start + XX minutes, not end-of-day)
- Always midprice order type
- Escalates to market **1 minute before deadline**
- Includes same cash check and stop loss placement

---

### 5. FAST SELL

**Purpose**: Time-sensitive sell with aggressive monitoring.

| Field | Value |
|-------|-------|
| Tickers | Multiple (per-ticker params) |
| Transaction | SELL |
| Fulfillment | 1% - 100% of current holdings |
| Order type | Midprice (fixed) |
| Stop type | N/A |
| Duration | XX MINS (minimum 3) |

**Execution flow**:
Same as NORMAL SELL but with 1-minute monitoring and timed deadline.

---

### 6. HOT POTATO

**Purpose**: Cycle-based trading strategy. Repeatedly enters and exits a position using trailing stops, cycling until a threshold count or end-of-day.

| Field | Value |
|-------|-------|
| Tickers | **Single ticker only** |
| Transaction | BUY or SELL — direction of each cycle's entry order |
| Transaction before close | BUY or SELL — desired position state at end-of-day (required) |
| Fulfillment | 1% - 100% |
| Initial order type | Midprice OR Trailing Stop at X.X% |
| Subsequent order type | Trailing Stop at X.X% (required) |
| Stop type | ADHOC trailing stop at X.X% |
| Duration | XX MINS (minimum 3) |
| Cycle threshold | Default 3 (user-configurable) |

**Execution flow**:
1. Place initial order using `initial_order_type`
2. **Monitor every 1 minute** for fill (escalate to market 1 min before deadline)
3. On fill: **Wait 15 minutes** → Place BOTH:
   - Fixed stop loss at buy price (breakeven protection)
   - Trailing stop at `stop_adhoc_trailing_pct`%
4. **Monitor every 5 minutes** which stop triggers first
5. On trigger: Cancel the other stop, increment cycle counter
6. If counter < `cycle_threshold`: Repeat from step 1 using `subsequent_order_type`
7. If counter >= threshold: Stop cycling
8. **End-of-day handling** (at exchange cutoff) — driven by `transaction_type_before_close`:
   - BUY + currently holding → Do nothing (already in desired state)
   - BUY + not holding → Market buy (ensure you end up holding)
   - SELL + currently holding → Market sell (ensure flat)
   - SELL + not holding → Do nothing (already flat)

> **`transaction_type` vs `transaction_type_before_close`**:
> `transaction_type` is the direction of each cycle's entry order (BUY or SELL).
> `transaction_type_before_close` is the desired position state at end-of-day, used only for the end-of-day safety net.
> All four combinations are valid:
>
> | `transaction_type` | `transaction_type_before_close` | Pattern |
> |--------------------|----------------------------------|---------|
> | BUY | BUY | Day-trade style: cycle buys, end the day **holding** (overnight position) |
> | BUY | SELL | Day-trade style: cycle buys, go **flat before close** (no overnight exposure) |
> | SELL | SELL | Cycle sells/reduce, end the day **flat** |
> | SELL | BUY | Cycle sells during session, then **buy back** to ensure holding at close |

---

## Prompt Template

Shared fields at the top apply to all tickers. Per-ticker blocks allow different parameters.

```
Trading account: <account1, account2>
Exchange: US / XETRA / EURONEXT
Request type: SELL EVERYTHING NOW / NORMAL BUY / NORMAL SELL / FAST BUY / FAST SELL / HOT POTATO
Transaction type: BUY / SELL
Transaction type before close: BUY / SELL (HOT POTATO only)
Duration: IMMED / BEFORE CLOSE / XX MINS

--- Ticker 1 ---
Ticker: <symbol>
Fulfillment: <1% - 100%>
Initial Order type: market / midprice / trailing stop at X.X%
Subsequent Order type: trailing stop at X.X% (HOT POTATO only)
Stop type: NORMAL / HEIGHTENED / FIXED PRICE AT XX.XX / ADHOC trailing stop at X.X% (HOT POTATO only)
Cycle threshold: <number, default 3> (HOT POTATO only)

--- Ticker 2 ---
Ticker: <symbol>
Fulfillment: <1% - 100%>
Initial Order type: market / midprice / trailing stop at X.X%
Stop type: NORMAL / HEIGHTENED / FIXED PRICE AT XX.XX
```

**Notes**:
- Delete options you are not using
- Multiple accounts: separate with commas (e.g. `LIVE-US, LIVE-EU`)
- SELL EVERYTHING NOW: No ticker blocks needed
- HOT POTATO: Only 1 ticker block allowed
- Fields not applicable to your request type can be omitted

---

## Execution Workflow

```
Step 1: User provides filled template
         ↓
Step 2: Claude parses all fields
         ↓
Step 3: Claude validates field combinations per request type
         ↓  (if invalid → asks user to correct)
Step 4: Claude generates request ID (YYYYMMDD-XXX)
         ↓
Step 5: Claude displays confirmation summary
         ↓  (waits for explicit "yes")
Step 6: Claude writes request JSON to state/requests/<id>.json
         ↓
Step 7: Claude invokes: python -m trade_executor.executors.<type> --request <path>
         ↓
Step 8: Executor connects to IBKR, places orders, runs monitoring loops
         ↓  (handles all time-sensitive operations autonomously)
Step 9: Executor writes result JSON to state/results/<id>.json
         ↓
Step 10: Claude reads result, verifies fills and stop losses
         ↓  (flags HIGH PRIORITY warnings if stops missing)
Step 11: Claude invokes: python -m trade_executor.trade_recorder --result <path>
         ↓
Step 12: Trade recorder appends to Google Sheets (4 tabs)
         ↓
Step 13: Claude displays final execution report to user
```

---

## Module Reference

### config.py

Central configuration. All tunable parameters in one file.

| Constant | Default | Description |
|----------|---------|-------------|
| `IBKR_HOST` | `'127.0.0.1'` | TWS/Gateway host |
| `LIVE_PORT` | `7496` | Live trading port |
| `PAPER_PORT` | `7497` | Paper trading port |
| `BASE_CLIENT_ID` | `10` | Starting client ID (avoids conflict with existing scripts using 1, 2, 9) |
| `STOP_NORMAL_PCT` | `0.08` | 8% below buy price |
| `STOP_HEIGHTENED_PCT` | `0.03` | 3% below buy price |
| `NORMAL_CHECK_INTERVAL` | `600` | 10 minutes (seconds) |
| `FAST_CHECK_INTERVAL` | `60` | 1 minute (seconds) |
| `HOT_POTATO_STOP_CHECK_INTERVAL` | `300` | 5 minutes (seconds) |
| `STOP_LOSS_DELAY` | `900` | 15 minutes after fill before placing stop (seconds) |
| `MINIMUM_DURATION_MINUTES` | `3` | Minimum duration for timed requests |
| `DEFAULT_CYCLE_THRESHOLD` | `3` | Default HOT POTATO cycle limit |

**Accounts registry** (`ACCOUNTS`): Dictionary mapping aliases to `{account_id, port}`.

**Exchange configuration** (`EXCHANGES`): Dictionary with entries for `US`, `XETRA`, `EURONEXT`, each containing timezone, calendar name, cutoff minutes, currency, and IBKR exchange routing.

---

### ibkr_client.py

`IBKRClient` class wrapping all Interactive Brokers interactions. One instance per account.

**Constructor**: `IBKRClient(account_id, port, client_id, host='127.0.0.1')`

| Method | Description |
|--------|-------------|
| `connect()` | Connect to IBKR. Immediately calls `reqAllOpenOrders()` to sync orders from all sessions (TWS, mobile, other API clients). Raises `IBKRConnectionError` on failure. |
| `disconnect()` | Graceful disconnect. |
| `get_portfolio_value()` | Returns `NetLiquidation` (float). |
| `get_cash_value()` | Returns `TotalCashValue` (float). |
| `get_positions()` | Returns list of `{symbol, position, market_price, contract}` dicts. |
| `get_position_qty(ticker)` | Returns shares held for a specific ticker (int). |
| `get_current_price(ticker, exchange)` | Returns live market price. Exchange-aware contract. |
| `place_midprice_order(ticker, action, qty, exchange)` | Places PEG MID order. Returns Trade. |
| `place_market_order(ticker, action, qty, exchange)` | Places MarketOrder. Returns Trade. |
| `place_trailing_stop_order(ticker, action, qty, trail_pct, exchange)` | Places TRAIL order. Returns Trade. |
| `place_stop_loss(ticker, qty, stop_price, exchange)` | Places protective StopOrder (SELL). Returns Trade. |
| `modify_order_qty(trade, new_qty)` | Modifies quantity on an existing order. |
| `cancel_order(trade)` | Cancels a specific order. |
| `cancel_all_orders()` | Cancels all open orders via `reqGlobalCancel()`. Returns count. |
| `get_pending_buy_value(exchange)` | Returns estimated cash committed to pending BUY orders from all sessions (LMT/STP price × remaining qty). MKT and PEG MID orders are excluded. Used to compute `available_cash` before BUY checks. |
| `is_filled(trade)` | Returns True if trade is fully filled. |
| `get_fill_price(trade)` | Returns average fill price (float). |
| `get_filled_qty(trade)` | Returns total filled shares (int). |
| `wait_for_fill(trade, timeout_seconds)` | Blocks until filled or timeout. Returns bool. |

**Exchange-aware contracts**: Internally calls `_create_contract(ticker, exchange)` which reads `EXCHANGES[exchange]` to determine `ibkr_exchange` (SMART, IBIS, SBF) and `currency` (USD, EUR).

**Order verification**: Every `place_*` method calls `_place_and_verify()` which checks if IBKR immediately set the order status to `Inactive` (rejected). If so, raises `OrderRejectedError` with the IBKR error message.

**Custom exceptions**: `IBKRConnectionError`, `OrderRejectedError`.

---

### quantity_calculator.py

Two calculation functions and one custom exception.

**`InsufficientCashError(required, available, ticker)`**
Raised when the account does not have enough cash. Includes `required`, `available`, and `ticker` attributes.

**`calculate_buy_qty(portfolio_value, cash_value, fulfillment_pct, price, ticker)`**
- Formula: `floor(portfolio_value * fulfillment_pct / price)`
- **Cash validation**: Checks `cash_value >= portfolio_value * fulfillment_pct` BEFORE calculating. Raises `InsufficientCashError` if insufficient.
- Validates: `price > 0`, `0 < fulfillment_pct <= 1.0`
- Returns `int >= 0`

**`calculate_sell_qty(current_holdings, fulfillment_pct, ticker)`**
- Formula: `floor(current_holdings * fulfillment_pct)`
- Returns 0 if `current_holdings <= 0`
- Validates: `0 < fulfillment_pct <= 1.0`
- Returns `int >= 0`

---

### order_monitor.py

`OrderMonitor` class - the core polling loop engine that handles fill detection, quantity recalculation callbacks, and deadline-based escalation. All deadlines are computed dynamically based on the exchange configuration.

**Constructor**: `OrderMonitor(client, check_interval_seconds, deadline_type, exchange, deadline_minutes=None)`

- `deadline_type='BEFORE_CLOSE'`: Uses `pandas_market_calendars` to get today's market close time for the exchange, then subtracts `cutoff_minutes_before_close` (15 minutes). For US this yields 3:45 PM ET. For XETRA this yields 5:15 PM CET.
- `deadline_type='TIMED'`: Deadline = `now + deadline_minutes`.
- `deadline_type='IMMEDIATE'`: Deadline = `now + 2 minutes`.

**`monitor_until_fill_or_deadline(trade, ticker, on_check_callback=None)`**

Main monitoring loop:
1. Sleeps for `check_interval` in 1-second increments (allows early fill detection)
2. If filled → returns `{filled: True, trade, escalated: False, deadline_reached: False}`
3. If near deadline → returns `{filled: False, deadline_reached: True}`
4. Calls `on_check_callback(trade, ticker)` each interval (used by buy executors to recalculate qty and modify order)
5. Loops back to step 1

**`escalate_to_market(trade, ticker, action, qty)`**

Cancels the current order, places a market order, returns the new Trade.

**`wait_for_stop_trigger(stop_trades, check_interval=300)`**

HOT POTATO specific. Monitors a list of stop orders and detects which triggers first. Returns `{triggered_name, triggered_trade, remaining}` or `{triggered_name: None}` if deadline reached.

---

### stop_loss_manager.py

`StopLossManager` class managing stop loss placement lifecycle, including the 15-minute delay.

**Constructor**: `StopLossManager(client, exchange)`

**`calculate_stop_price(buy_price, stop_type, fixed_price=None)`**

| Stop Type | Formula | Example (buy at $100) |
|-----------|---------|----------------------|
| NORMAL | `buy_price * (1 - 0.08)` | $92.00 |
| HEIGHTENED | `buy_price * (1 - 0.03)` | $97.00 |
| FIXED_PRICE | `fixed_price` (user-specified) | User's price |

**`schedule_stop_loss(ticker, qty, buy_price, stop_type, fixed_price=None, delay_seconds=900)`**

Uses `threading.Timer` to place the stop loss after a 15-minute delay. The timer runs as a daemon thread. When it fires, calls `place_stop_loss_now()`.

**`place_stop_loss_now(ticker, qty, buy_price, stop_type, fixed_price=None)`**

Places the stop loss immediately via `client.place_stop_loss()`. Returns `{trade, stop_price, ticker, success}`.

**`place_trailing_and_fixed_stops(ticker, qty, buy_price, trailing_pct)`**

HOT POTATO specific. Places BOTH:
1. A fixed stop at buy price (breakeven protection)
2. A trailing stop at `trailing_pct`%

Returns `{fixed_stop_trade, trailing_stop_trade, success}`.

**`cleanup()`** - Cancels all pending timers. Must be called on shutdown.

---

### order_factory.py

Factory functions for creating IBKR Order objects. Provides a consistent interface for order creation.

| Function | IBKR Order Type | Description |
|----------|----------------|-------------|
| `create_midprice_order(action, qty)` | `PEG MID` | Pegged-to-Midpoint |
| `create_market_order(action, qty)` | `MKT` | Standard market order |
| `create_trailing_stop_order(action, qty, trail_pct)` | `TRAIL` | Trailing stop with percentage |
| `create_stop_loss_order(qty, stop_price)` | `STP` | Protective sell stop |

---

### request_id.py

Generates sequential request IDs in `YYYYMMDD-XXX` format.

**`generate_request_id()`**
- Reads `state/request_counter.json`
- If date matches today: increments `last_seq`
- If new day: resets to 1
- Writes updated counter back
- Returns formatted ID (e.g. `20260218-001`, `20260218-002`)

**`get_current_counter()`** - Reads counter without incrementing.

Counter file format: `{"date": "20260218", "last_seq": 3}`

---

### trade_recorder.py

Book-keeping sub-agent. Writes execution results to Google Sheets.

**Invocation**: `python -m trade_executor.trade_recorder --result <path_to_result.json>`

**`record_execution(result_path)`** - Main entry point. Returns `True` on success.

Performs 4 operations:
1. `_append_execution_log()` - One row per account + ticker to Execution Log tab
2. `_append_errors()` - One row per error to Errors tab
3. `_append_stop_loss_tracker()` - One row per placed stop to Stop Loss Tracker tab
4. `_update_daily_summary()` - Aggregated stats to Daily Summary tab

Uses `utils/utils_gsheet_handler.py` for authentication (`authenticate_gsheet`) and writing (`export_data`).

---

### Data Models

#### `models/request.py`

**`TickerParams`** dataclass - Per-ticker parameters:

| Field | Type | Description |
|-------|------|-------------|
| `ticker` | `str` | Stock symbol (e.g. 'AAPL') |
| `fulfillment_pct` | `float` | 0.01 to 1.0 (1% to 100%) |
| `initial_order_type` | `str` | 'market' / 'midprice' / 'trailing_stop' |
| `initial_trailing_pct` | `float?` | Trailing % if initial is trailing stop |
| `subsequent_order_type` | `str?` | HOT POTATO only: 'trailing_stop' |
| `subsequent_trailing_pct` | `float?` | HOT POTATO only: trailing % |
| `stop_type` | `str?` | 'NORMAL' / 'HEIGHTENED' / 'FIXED_PRICE' / 'ADHOC' |
| `stop_fixed_price` | `float?` | If stop_type is FIXED_PRICE |
| `stop_adhoc_trailing_pct` | `float?` | If stop_type is ADHOC (HOT POTATO) |
| `cycle_threshold` | `int?` | HOT POTATO only, default 3 |

**`TradeRequest`** dataclass - Complete request:

| Field | Type | Description |
|-------|------|-------------|
| `request_id` | `str` | YYYYMMDD-XXX |
| `accounts` | `list[dict]` | `[{alias, account_id, port}]` |
| `exchange` | `str` | 'US' / 'XETRA' / 'EURONEXT' |
| `ticker_params` | `list[TickerParams]` | Per-ticker parameters |
| `request_type` | `str` | 'SELL_EVERYTHING_NOW' / 'NORMAL_BUY' / etc. |
| `transaction_type` | `str` | 'BUY' / 'SELL' — direction of each entry order |
| `transaction_type_before_close` | `str?` | HOT POTATO only: 'BUY' / 'SELL' — desired position at end-of-day |
| `duration_type` | `str` | 'IMMEDIATE' / 'BEFORE_CLOSE' / 'TIMED' |
| `duration_minutes` | `int?` | If duration_type is TIMED |

Methods: `to_json(path)`, `from_json(path)`, `to_dict()`

#### `models/execution_result.py`

**`TickerResult`** dataclass - Per-ticker outcome:

| Field | Type | Description |
|-------|------|-------------|
| `ticker` | `str` | Stock symbol |
| `action` | `str` | 'BUY' / 'SELL' |
| `seq_num` | `int` | Sequence number (>1 for HOT POTATO cycles) |
| `target_qty` | `int` | Calculated quantity |
| `filled_qty` | `int` | Actually filled quantity |
| `avg_fill_price` | `float` | Average fill price |
| `order_type_used` | `str` | 'midprice' / 'market' / 'trailing_stop' |
| `escalated_to_market` | `bool` | Whether order was escalated |
| `stop_loss_placed` | `bool` | Whether stop loss was placed |
| `stop_loss_price` | `float?` | Stop loss price if placed |
| `stop_loss_order_id` | `int?` | IBKR order ID for stop |
| `error` | `str?` | Error message if any |

**`AccountResult`** dataclass: `{account_id, ticker_results: list[TickerResult]}`

**`ExecutionResult`** dataclass:

| Field | Type | Description |
|-------|------|-------------|
| `request_id` | `str` | YYYYMMDD-XXX |
| `status` | `str` | 'COMPLETED' / 'PARTIAL' / 'FAILED' |
| `started_at` | `str` | ISO timestamp |
| `completed_at` | `str` | ISO timestamp |
| `exchange` | `str` | Exchange key |
| `request_type` | `str` | Request type |
| `account_results` | `list[AccountResult]` | Per-account results |
| `errors` | `list[str]` | Error messages |

Methods: `to_json(path)`, `from_json(path)`, `to_dict()`

---

## Executor Scripts

Each executor is a standalone script invoked as:
```
python -m trade_executor.executors.<type> --request <path_to_request.json>
```

| Executor | Script | Monitoring | Deadline | Escalation |
|----------|--------|-----------|----------|------------|
| SELL EVERYTHING NOW | `sell_everything.py` | None (60s wait) | Immediate | Already market |
| NORMAL BUY | `normal_buy.py` | Every 10 min | 15 min before market close | Recalc qty + market |
| NORMAL SELL | `normal_sell.py` | Every 10 min | 15 min before market close | Market |
| FAST BUY | `fast_buy.py` | Every 1 min | Start + XX min | Recalc qty + market |
| FAST SELL | `fast_sell.py` | Every 1 min | Start + XX min | Market |
| HOT POTATO | `hot_potato.py` | 1 min (fill) / 5 min (stops) | Start + XX min | Market + end-of-day handling |

All executors:
- Check for duplicate execution (refuse to run if result file exists)
- Write result JSON on completion (even on failure)
- Use `try/finally` to ensure IBKR disconnection

---

## Google Sheet Structure

Spreadsheet: **"Trade Execution Log"** (4 tabs)

### Tab 1: Execution Log

One row per account + ticker + sequence. **Unique key**: `Request ID + Account ID + Ticker + Seq #`

| Column | Description |
|--------|-------------|
| Request ID | YYYYMMDD-XXX |
| Seq # | 1 for most types; increments for HOT POTATO cycles |
| Timestamp | ISO timestamp of completion |
| Account ID | IBKR account ID |
| Ticker | Stock symbol |
| Action | BUY / SELL |
| Request Type | NORMAL_BUY, FAST_SELL, etc. |
| Target Qty | Calculated quantity |
| Filled Qty | Actually filled |
| Avg Fill Price | Average fill price |
| Order Type Used | midprice / market / trailing_stop |
| Escalated to Market | TRUE / FALSE |
| Stop Loss Placed | TRUE / FALSE |
| Stop Loss Price | Price if placed |
| Stop Type | NORMAL / HEIGHTENED / FIXED_PRICE |
| Fulfillment % | Target percentage |
| Portfolio Value | At time of calculation |
| Exchange | US / XETRA / EURONEXT |
| Duration Type | IMMEDIATE / BEFORE_CLOSE / TIMED |
| Error | Error message if any |

### Tab 2: Daily Summary

Aggregated per request. **Unique key**: `Date`

| Column | Description |
|--------|-------------|
| Date | YYYY-MM-DD |
| Total Requests | Count of requests |
| Total Orders | Count of individual orders |
| Total Filled | Successfully filled |
| Total Failed | Failed orders |
| Total Buy Value | Sum of buy fills ($) |
| Total Sell Value | Sum of sell fills ($) |
| Escalation Count | Orders escalated to market |

### Tab 3: Errors

Append-only event log. **No unique key**.

| Column | Description |
|--------|-------------|
| Timestamp | ISO timestamp |
| Request ID | YYYYMMDD-XXX |
| Account ID | IBKR account |
| Ticker | Stock symbol |
| Error Type | EXECUTION_ERROR |
| Error Message | Full error details |

### Tab 4: Stop Loss Tracker

Active stop loss orders. **Unique key**: `Request ID + Account ID + Ticker + Seq #`

| Column | Description |
|--------|-------------|
| Request ID | YYYYMMDD-XXX |
| Seq # | Sequence number |
| Account ID | IBKR account |
| Ticker | Stock symbol |
| Buy Price | Original fill price |
| Stop Type | NORMAL / HEIGHTENED / FIXED_PRICE |
| Stop Price | Calculated stop price |
| Placed At | ISO timestamp |
| Status | ACTIVE (updated manually) |

---

## Exchange Support

The system supports three exchange groups with dynamically computed deadlines:

| Exchange | Timezone | Calendar | Close Time | Cutoff | Currency | IBKR Route |
|----------|----------|----------|------------|--------|----------|------------|
| US | US/Eastern | NYSE | 4:00 PM ET | 3:45 PM ET | USD | SMART |
| XETRA | Europe/Berlin | XETRA | 5:30 PM CET | 5:15 PM CET | EUR | IBIS |
| EURONEXT | Europe/Paris | EURONEXT | 5:30 PM CET | 5:15 PM CET | EUR | SBF |

All time-sensitive logic (escalation deadlines, market hours validation) uses `pandas_market_calendars` to get the actual close time for today, then subtracts `cutoff_minutes_before_close`. This handles half-days, holidays, and schedule changes automatically.

---

## Multi-Account Mirroring

When multiple accounts are specified (e.g. `LIVE-US, LIVE-EU`):

- **Same intent**: All accounts execute the same tickers, same direction, same percentages
- **Independent quantities**: Each account calculates qty based on its OWN portfolio value/holdings
- **Independent connections**: Each account gets its own `IBKRClient` with a unique `client_id` (`BASE_CLIENT_ID + index`)
- **Execution order**:
  - **Sequential** for NORMAL and HOT POTATO (time is not critical during placement)
  - **Threaded** for FAST and SELL EVERYTHING (time-critical)
- **Independent results**: The result JSON captures per-account, per-ticker outcomes

---

## Stop Types

| Type | Rule | Example (buy at $100) | Used By |
|------|------|-----------------------|---------|
| NORMAL | 8% below buy price | Stop at $92.00 | NORMAL BUY, FAST BUY |
| HEIGHTENED | 3% below buy price | Stop at $97.00 | NORMAL BUY, FAST BUY |
| FIXED PRICE | User-specified exact price | Stop at user's price | NORMAL BUY, FAST BUY |
| ADHOC | Trailing stop at X.X% | Trail at user's % | HOT POTATO only |

All stop losses (except ADHOC) are placed after a **15-minute delay** following the fill. This delay is configurable via `STOP_LOSS_DELAY` in `config.py`.

---

## Error Handling

### Severity Levels

| Level | Examples | System Behavior |
|-------|----------|-----------------|
| **FATAL** | IBKR connection failure | Abort entire request. Result status = `FAILED`. |
| **ERROR** | Order rejected, stop loss placement failed, insufficient cash | Record failure for that ticker, continue others. Result status = `PARTIAL`. |
| **WARNING** | Escalated to market, partial fill | Record in result, inform user. Result status = `COMPLETED`. |

### Specific Error Scenarios

| Scenario | Behavior |
|----------|----------|
| IBKR connection fails | `IBKRConnectionError` raised. Entire request aborted for that account. |
| Order rejected by IBKR | `OrderRejectedError` raised. That ticker aborted. Others continue. |
| Insufficient cash for buy | `InsufficientCashError` raised. That ticker skipped. Others continue. |
| Fill timeout on market escalation | Error recorded. 60-second timeout. |
| Stop loss placement fails | **HIGH PRIORITY WARNING**. User notified of exposure without protection. |
| Executor crashes mid-execution | No result file written. Claude reports CRITICAL ALERT. |
| Duplicate request ID | Executor refuses to run if result file already exists. |
| Market closed | `pandas_market_calendars` check. Empty schedule = no trading. |

---

## Safety Rules

1. **NEVER** place a live trade without explicit user confirmation ("yes")
2. **NEVER** default to paper trading port (7497). Always verify port 7496 for live.
3. **ALWAYS** show the confirmation summary before dispatching
4. If IBKR connection fails, **STOP** and report. Do not retry automatically.
5. If any order is rejected by IBKR, **STOP** and report the full error.
6. **Cash validation**: Before any BUY, verify sufficient cash. Abort if insufficient.
7. If stop loss fails after a buy fill, flag as **HIGH PRIORITY WARNING**
8. If executor crashes without result file, report **CRITICAL ALERT**
9. **Duplicate prevention**: Refuse to run if result file already exists for request ID
10. **Market hours validation** before placing orders (exchange-aware)

---

## Configuration Reference

### Adding a New Account

Edit `trade_executor/config.py`:
```python
ACCOUNTS = {
    'LIVE-US': {'account_id': 'U13868670', 'port': 7496},
    'LIVE-EU': {'account_id': 'UXXXXXXX', 'port': 7496},  # Add here
}
```

### Switching to Paper Trading (for testing)

Change port in the account config:
```python
ACCOUNTS = {
    'PAPER-US': {'account_id': 'DUO713598', 'port': 7497},
}
```

### Changing Stop Loss Percentages

```python
STOP_NORMAL_PCT = 0.08      # Change from 8% to desired
STOP_HEIGHTENED_PCT = 0.03  # Change from 3% to desired
```

### Changing Monitoring Intervals

```python
NORMAL_CHECK_INTERVAL = 600   # 10 minutes (seconds)
FAST_CHECK_INTERVAL = 60      # 1 minute (seconds)
STOP_LOSS_DELAY = 900         # 15 minutes after fill (seconds)
```

### Setting Up Google Sheets

```python
EXECUTION_LOG_SPREADSHEET_ID = 'paste-your-spreadsheet-id-here'
```
