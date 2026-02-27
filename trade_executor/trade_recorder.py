"""
trade_recorder.py

Book-keeping sub-agent. Records execution results to Google Sheets.
Reuses the existing utils/utils_gsheet_handler.py authentication pattern.
"""

import argparse
import sys
import os
from datetime import datetime

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trade_executor.config import (
    EXECUTION_LOG_SPREADSHEET_ID,
    EXECUTION_LOG_TAB,
    DAILY_SUMMARY_TAB,
    ERRORS_TAB,
    STOP_LOSS_TRACKER_TAB,
    GSHEET_CREDS_PATH,
)
from trade_executor.models.execution_result import ExecutionResult
from utils.utils_gsheet_handler import authenticate_gsheet, export_data


def record_execution(result_path: str) -> bool:
    """
    Main entry point. Reads result JSON and writes to Google Sheets.

    Args:
        result_path: Path to the execution result JSON file

    Returns:
        bool: True if recording succeeded
    """
    result = ExecutionResult.from_json(result_path)

    # Authenticate
    client = authenticate_gsheet(GSHEET_CREDS_PATH)
    if client is None:
        print("[Recorder] ERROR: GSheet authentication failed")
        return False

    if not EXECUTION_LOG_SPREADSHEET_ID:
        print("[Recorder] ERROR: EXECUTION_LOG_SPREADSHEET_ID not configured in config.py")
        return False

    success = True

    # 1. Append to Execution Log
    try:
        _append_execution_log(client, result)
        print(f"[Recorder] Execution Log updated for {result.request_id}")
    except Exception as e:
        print(f"[Recorder] ERROR writing Execution Log: {e}")
        success = False

    # 2. Record errors if any
    if result.errors:
        try:
            _append_errors(client, result)
            print(f"[Recorder] Errors tab updated for {result.request_id}")
        except Exception as e:
            print(f"[Recorder] ERROR writing Errors tab: {e}")
            success = False

    # 3. Update Stop Loss Tracker for buy orders
    if result.request_type in ('NORMAL_BUY', 'FAST_BUY', 'HOT_POTATO'):
        try:
            _append_stop_loss_tracker(client, result)
            print(f"[Recorder] Stop Loss Tracker updated for {result.request_id}")
        except Exception as e:
            print(f"[Recorder] ERROR writing Stop Loss Tracker: {e}")
            success = False

    # 4. Update Daily Summary
    try:
        _update_daily_summary(client, result)
        print(f"[Recorder] Daily Summary updated for {result.request_id}")
    except Exception as e:
        print(f"[Recorder] ERROR writing Daily Summary: {e}")
        success = False

    return success


def _append_execution_log(client, result: ExecutionResult):
    """Append one row per account+ticker to Execution Log tab."""
    rows = []
    for ar in result.account_results:
        for tr in ar.ticker_results:
            rows.append({
                'Request ID': result.request_id,
                'Seq #': getattr(tr, 'seq_num', 1),
                'Timestamp': result.completed_at,
                'Account ID': ar.account_id,
                'Ticker': tr.ticker,
                'Action': tr.action,
                'Request Type': result.request_type,
                'Target Qty': tr.target_qty,
                'Filled Qty': tr.filled_qty,
                'Avg Fill Price': tr.avg_fill_price,
                'Order Type Used': tr.order_type_used,
                'Escalated to Market': tr.escalated_to_market,
                'Stop Loss Placed': tr.stop_loss_placed,
                'Stop Loss Price': tr.stop_loss_price or '',
                'Stop Type': '',  # From request, not result
                'Fulfillment %': '',  # From request, not result
                'Portfolio Value': '',  # From request context
                'Exchange': result.exchange,
                'Duration Type': '',
                'Error': tr.error or '',
            })

    if rows:
        df = pd.DataFrame(rows)
        export_data(client, EXECUTION_LOG_SPREADSHEET_ID, EXECUTION_LOG_TAB, df)


def _append_errors(client, result: ExecutionResult):
    """Append errors to the Errors tab."""
    rows = []
    for error_msg in result.errors:
        # Parse account_id and ticker from error message format: "account_id/ticker: message"
        parts = error_msg.split(':', 1)
        identifier = parts[0].strip() if parts else ''
        message = parts[1].strip() if len(parts) > 1 else error_msg

        account_id = ''
        ticker = ''
        if '/' in identifier:
            account_id, ticker = identifier.split('/', 1)

        rows.append({
            'Timestamp': result.completed_at,
            'Request ID': result.request_id,
            'Account ID': account_id,
            'Ticker': ticker,
            'Error Type': 'EXECUTION_ERROR',
            'Error Message': message,
        })

    if rows:
        df = pd.DataFrame(rows)
        export_data(client, EXECUTION_LOG_SPREADSHEET_ID, ERRORS_TAB, df)


def _append_stop_loss_tracker(client, result: ExecutionResult):
    """Append stop loss entries to the Stop Loss Tracker tab."""
    rows = []
    for ar in result.account_results:
        for tr in ar.ticker_results:
            if tr.stop_loss_placed and tr.stop_loss_price:
                rows.append({
                    'Request ID': result.request_id,
                    'Seq #': getattr(tr, 'seq_num', 1),
                    'Account ID': ar.account_id,
                    'Ticker': tr.ticker,
                    'Buy Price': tr.avg_fill_price,
                    'Stop Type': '',  # Would need to come from request
                    'Stop Price': tr.stop_loss_price,
                    'Placed At': result.completed_at,
                    'Status': 'ACTIVE',
                })

    if rows:
        df = pd.DataFrame(rows)
        export_data(client, EXECUTION_LOG_SPREADSHEET_ID, STOP_LOSS_TRACKER_TAB, df)


def _update_daily_summary(client, result: ExecutionResult):
    """Append a summary row for this request."""
    total_orders = 0
    total_filled = 0
    total_failed = 0
    total_buy_value = 0.0
    total_sell_value = 0.0
    escalation_count = 0

    for ar in result.account_results:
        for tr in ar.ticker_results:
            total_orders += 1
            if tr.filled_qty > 0:
                total_filled += 1
                value = tr.avg_fill_price * tr.filled_qty
                if tr.action == 'BUY':
                    total_buy_value += value
                else:
                    total_sell_value += value
            if tr.error:
                total_failed += 1
            if tr.escalated_to_market:
                escalation_count += 1

    date_str = result.completed_at[:10] if result.completed_at else datetime.now().strftime('%Y-%m-%d')

    row = {
        'Date': date_str,
        'Total Requests': 1,
        'Total Orders': total_orders,
        'Total Filled': total_filled,
        'Total Failed': total_failed,
        'Total Buy Value': round(total_buy_value, 2),
        'Total Sell Value': round(total_sell_value, 2),
        'Escalation Count': escalation_count,
    }

    df = pd.DataFrame([row])
    export_data(client, EXECUTION_LOG_SPREADSHEET_ID, DAILY_SUMMARY_TAB, df)


def main():
    parser = argparse.ArgumentParser(description='Trade recorder (book-keeping)')
    parser.add_argument('--result', required=True, help='Path to result JSON file')
    args = parser.parse_args()

    success = record_execution(args.result)
    if success:
        print("[Recorder] Book-keeping completed successfully")
    else:
        print("[Recorder] Book-keeping completed with errors")
        sys.exit(1)


if __name__ == '__main__':
    main()
