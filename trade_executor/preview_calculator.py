"""
preview_calculator.py

Connects to IBKR to fetch live prices and account data, then calculates
estimated qty, value, and stop price for each ticker in a trade request.
Used to show a pre-confirmation preview before the user approves execution.

No orders are placed -- this is read-only.
"""

import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trade_executor.config import (
    ACCOUNTS, BASE_CLIENT_ID, EXCHANGES,
    STOP_NORMAL_PCT, STOP_HEIGHTENED_PCT,
    REQUEST_SELL_EVERYTHING_NOW,
)
from trade_executor.models.request import TradeRequest
from trade_executor.ibkr_client import IBKRClient, IBKRConnectionError
from trade_executor.quantity_calculator import (
    calculate_buy_qty, calculate_sell_qty,
    InsufficientCashError, InsufficientCashForRequestError,
    validate_total_cash,
)


def _calculate_stop_price(price: float, stop_type: str,
                          fixed_price: float = None) -> float | None:
    """Calculate estimated stop loss price (pure math, no IBKR call)."""
    if stop_type == 'NORMAL':
        return round(price * (1 - STOP_NORMAL_PCT), 2)
    elif stop_type == 'HEIGHTENED':
        return round(price * (1 - STOP_HEIGHTENED_PCT), 2)
    elif stop_type == 'FIXED_PRICE':
        return round(fixed_price, 2) if fixed_price is not None else None
    return None


def generate_preview(request: TradeRequest) -> dict:
    """Generate preview data for all accounts and tickers in the request.

    Args:
        request: Parsed TradeRequest

    Returns:
        dict with preview data per account per ticker
    """
    is_buy = request.transaction_type == 'BUY'
    exchange = request.exchange
    currency = EXCHANGES[exchange]['currency']
    result = {"accounts": []}

    for idx, acct in enumerate(request.accounts):
        account_id = acct['account_id']
        port = acct['port']
        alias = acct.get('alias', account_id)
        client_id = BASE_CLIENT_ID + 50 + idx  # Offset to avoid conflicts

        acct_result = {
            "account_id": account_id,
            "alias": alias,
            "portfolio_value": None,
            "cash_value": None,
            "tickers": [],
        }

        client = IBKRClient(account_id, port, client_id)
        try:
            client.connect()

            # Fetch account-level data
            portfolio_value = client.get_portfolio_value(currency=currency)
            cash_value = client.get_cash_value(currency=currency)
            acct_result["portfolio_value"] = round(portfolio_value, 2)
            acct_result["cash_value"] = round(cash_value, 2)

            # Aggregate cash check for BUY requests
            if is_buy:
                try:
                    validate_total_cash(portfolio_value, cash_value,
                                        request.ticker_params)
                except InsufficientCashForRequestError as e:
                    acct_result["tickers"] = [{
                        "ticker": tp.ticker,
                        "price": None,
                        "qty": None,
                        "est_value": None,
                        "est_stop_price": None,
                        "error": str(e),
                    } for tp in request.ticker_params]
                    result["accounts"].append(acct_result)
                    client.disconnect()
                    continue

            for tp in request.ticker_params:
                ticker_preview = {
                    "ticker": tp.ticker,
                    "price": None,
                    "qty": None,
                    "est_value": None,
                    "est_stop_price": None,
                    "error": None,
                }

                try:
                    price = client.get_current_price(tp.ticker, exchange)
                    ticker_preview["price"] = round(price, 2)

                    holdings = None
                    if is_buy:
                        qty = calculate_buy_qty(
                            portfolio_value, cash_value,
                            tp.fulfillment_pct, price,
                            ticker=tp.ticker,
                        )
                    else:
                        holdings = client.get_position_qty(tp.ticker)
                        qty = calculate_sell_qty(
                            holdings, tp.fulfillment_pct,
                            ticker=tp.ticker,
                        )

                    if qty == 0:
                        if is_buy:
                            ticker_preview["error"] = (
                                f"BUY qty is 0 for {tp.ticker}: "
                                f"portfolio_value=${portfolio_value:,.2f}, "
                                f"fulfillment={tp.fulfillment_pct * 100:.0f}%, "
                                f"price=${price:.2f}"
                            )
                        else:
                            if holdings == 0:
                                ticker_preview["error"] = (
                                    f"No position in {tp.ticker} — not currently held"
                                )
                            else:
                                ticker_preview["error"] = (
                                    f"SELL qty rounds to 0 for {tp.ticker}: "
                                    f"holdings={holdings}, "
                                    f"fulfillment={tp.fulfillment_pct * 100:.0f}%"
                                )

                    ticker_preview["qty"] = qty
                    ticker_preview["est_value"] = round(qty * price, 2)

                    # Estimated stop price for BUY requests
                    if is_buy and tp.stop_type:
                        stop_price = _calculate_stop_price(
                            price, tp.stop_type, tp.stop_fixed_price,
                        )
                        ticker_preview["est_stop_price"] = stop_price

                except InsufficientCashError as e:
                    ticker_preview["error"] = str(e)
                except Exception as e:
                    ticker_preview["error"] = str(e)

                acct_result["tickers"].append(ticker_preview)

        except IBKRConnectionError as e:
            acct_result["tickers"] = [{
                "ticker": tp.ticker,
                "price": None,
                "qty": None,
                "est_value": None,
                "est_stop_price": None,
                "error": f"IBKR connection failed: {e}",
            } for tp in request.ticker_params]
        finally:
            client.disconnect()

        result["accounts"].append(acct_result)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Preview calculator: fetch live prices and estimate qty/value"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        '--request',
        help='Path to a single request JSON file',
    )
    group.add_argument(
        '--requests', nargs='+', metavar='FILE',
        help='Paths to multiple per-ticker request files (merges ticker_params for aggregate cash check)',
    )
    args = parser.parse_args()

    if args.requests:
        all_requests = [TradeRequest.from_json(p) for p in args.requests]
        request = all_requests[0]
        merged_ticker_params = []
        for r in all_requests:
            merged_ticker_params.extend(r.ticker_params)
        request.ticker_params = merged_ticker_params
    else:
        request = TradeRequest.from_json(args.request)

    if request.request_type == REQUEST_SELL_EVERYTHING_NOW:
        print(json.dumps({"error": "Preview not supported for SELL EVERYTHING NOW"}))
        sys.exit(0)

    preview = generate_preview(request)
    print(json.dumps(preview, indent=2))


if __name__ == '__main__':
    main()
