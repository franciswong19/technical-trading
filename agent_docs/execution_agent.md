# Execution Sub-Agent Reference

## Role
The execution sub-agent handles all time-sensitive IBKR operations. It runs as Python scripts that Claude (the main agent) invokes. These scripts handle monitoring loops, order modification, and stop loss placement autonomously.

## Invocation
Each executor is invoked as:
```
python -m trade_executor.executors.<type> --request <path_to_request.json>
```

Where `<type>` is one of:
- `sell_everything` - SELL EVERYTHING NOW
- `normal_buy` - NORMAL BUY
- `normal_sell` - NORMAL SELL
- `fast_buy` - FAST BUY
- `fast_sell` - FAST SELL
- `hot_potato` - HOT POTATO

## Request JSON Schema
Written by the main agent to `trade_executor/state/requests/<request_id>.json`:
```json
{
  "request_id": "20260218-001",
  "accounts": [{"alias": "LIVE-US", "account_id": "U13868670", "port": 7496}],
  "exchange": "US",
  "ticker_params": [{
    "ticker": "AAPL",
    "fulfillment_pct": 0.10,
    "initial_order_type": "midprice",
    "initial_trailing_pct": null,
    "subsequent_order_type": null,
    "subsequent_trailing_pct": null,
    "stop_type": "NORMAL",
    "stop_fixed_price": null,
    "stop_adhoc_trailing_pct": null,
    "cycle_threshold": null
  }],
  "request_type": "NORMAL_BUY",
  "transaction_type": "BUY",
  "duration_type": "BEFORE_CLOSE",
  "duration_minutes": null
}
```

## Result JSON Schema
Written by the executor to `trade_executor/state/results/<request_id>.json`:
```json
{
  "request_id": "20260218-001",
  "status": "COMPLETED",
  "started_at": "2026-02-18T10:30:00-05:00",
  "completed_at": "2026-02-18T15:45:00-05:00",
  "exchange": "US",
  "request_type": "NORMAL_BUY",
  "account_results": [{
    "account_id": "U13868670",
    "ticker_results": [{
      "ticker": "AAPL",
      "action": "BUY",
      "seq_num": 1,
      "target_qty": 50,
      "filled_qty": 50,
      "avg_fill_price": 185.23,
      "order_type_used": "midprice",
      "escalated_to_market": false,
      "stop_loss_placed": true,
      "stop_loss_price": 170.41,
      "stop_loss_order_id": null,
      "error": null
    }]
  }],
  "errors": []
}
```

## Status Values
- `COMPLETED` - All orders filled, all stops placed
- `PARTIAL` - Some orders filled, some errors occurred
- `FAILED` - Fatal error (e.g. IBKR connection failure)

## Monitoring Intervals
| Request Type | Check Interval | Deadline Behavior |
|---|---|---|
| SELL EVERYTHING NOW | N/A (wait 60s) | Immediate |
| NORMAL BUY/SELL | 10 min | Exchange cutoff (15 min before close) |
| FAST BUY/SELL | 1 min | Timed (start + XX min) |
| HOT POTATO | 1 min fill / 5 min stops | Timed + exchange cutoff |

## Error Handling
- Connection failure: Aborts entire request
- Order rejection: Aborts remaining tickers for that account
- Fill timeout on market escalation: Records error, continues
- Stop loss placement failure: Records error, flags in result
- Duplicate prevention: Refuses to run if result file exists
