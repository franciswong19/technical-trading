"""
utils_ibkr_portfolio.py

Reusable functions for connecting to IBKR and fetching portfolio data.
Refactored from mda_picks/fetch_ibkr_portfolio.py to be importable.
"""

from ib_insync import IB


def connect_ibkr(host='127.0.0.1', port=7496, client_id=9, timeout=5):
    """
    Connect to IBKR TWS/IB Gateway and return the IB instance.

    Args:
        host: TWS/IB Gateway host (default localhost)
        port: Port number (7496=Live, 7497=Paper)
        client_id: Unique client ID for this connection
        timeout: Connection timeout in seconds

    Returns:
        IB instance (connected)

    Raises:
        ConnectionError: If connection fails
    """
    ib = IB()
    try:
        ib.connect(host, port, clientId=client_id, timeout=timeout)
        print(f"Connected to IBKR TWS/IB Gateway. Client ID: {client_id}")
        return ib
    except Exception as e:
        raise ConnectionError(f"Failed to connect to IBKR at {host}:{port} (clientId={client_id}): {e}")


def get_account_summary(ib, account):
    """
    Fetch account summary for a specific account.

    Args:
        ib: Connected IB instance
        account: IBKR account ID (e.g. 'U13868670')

    Returns:
        dict with keys: 'NetLiquidation', 'TotalCashValue' (float values)
    """
    summary = {}
    account_data = ib.accountSummary(account=account)
    for item in account_data:
        if item.tag in ['NetLiquidation', 'TotalCashValue']:
            summary[item.tag] = float(item.value)
    return summary


def get_positions(ib, account):
    """
    Fetch all positions for a specific account.

    Args:
        ib: Connected IB instance
        account: IBKR account ID

    Returns:
        list of dicts with keys: 'symbol', 'position', 'market_price', 'market_value', 'currency'
    """
    positions = ib.positions()
    filtered = [p for p in positions if p.account == account]

    result = []
    for pos in filtered:
        market_price = pos.marketPrice if pos.marketPrice is not None else 0
        value = market_price * pos.position
        result.append({
            'symbol': pos.contract.symbol,
            'position': int(pos.position),
            'market_price': market_price,
            'market_value': round(value, 2),
            'currency': pos.contract.currency,
            'contract': pos.contract,
        })
    return result


def disconnect_ibkr(ib):
    """Gracefully disconnect from IBKR."""
    if ib.isConnected():
        ib.disconnect()
        print("Disconnected from IBKR")


# Allow standalone execution for quick portfolio check
if __name__ == "__main__":
    HOST = '127.0.0.1'
    PORT = 7496
    CLIENT_ID = 9
    TARGET_ACCOUNT = 'U13868670'

    ib = connect_ibkr(HOST, PORT, CLIENT_ID)

    print("\n=== Account Summary ===")
    summary = get_account_summary(ib, TARGET_ACCOUNT)
    for tag, value in summary.items():
        print(f"{tag}: {value}")

    print("\n=== Positions ===")
    positions = get_positions(ib, TARGET_ACCOUNT)
    if not positions:
        print("No positions in this account.")
    for pos in positions:
        print(f"{pos['symbol']}: {pos['position']} shares, value={pos['market_value']:.2f} {pos['currency']}")

    disconnect_ibkr(ib)
