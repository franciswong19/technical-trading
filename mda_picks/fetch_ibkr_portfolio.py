"""
fetch_ibkr_portfolio.py

This script connects to a running TWS or IB Gateway session and fetches:
- Portfolio value (NetLiquidation)
- Cash value
- Positions with current market value

You can specify which account to target if your login has multiple accounts.
"""

from ib_insync import IB

# =========================
# CONFIGURATION PARAMETERS
# =========================
HOST = '127.0.0.1'          # TWS/IB Gateway host (usually localhost)
PORT = 7496                 # Port for Paper (7497) or Live (7496)
CLIENT_ID = 9               # Unique client ID for this script
TARGET_ACCOUNT = 'U13868670' # Your IBKR account number to target
# =========================

def main():
    # Connect to IBKR
    ib = IB()
    try:
        ib.connect(HOST, PORT, clientId=CLIENT_ID, timeout=5)
        print(f"Connected to IBKR TWS/IB Gateway. Client ID: {CLIENT_ID}\n")
    except Exception as e:
        print(f"Error connecting to IBKR: {e}")
        return

    # Fetch account summary for target account
    try:
        account_summary = ib.accountSummary(account=TARGET_ACCOUNT)
        print("=== Account Summary ===")
        for item in account_summary:
            if item.tag in ['NetLiquidation', 'TotalCashValue']:
                print(f"{item.tag}: {item.value} {item.currency}")
    except Exception as e:
        print(f"Error fetching account summary: {e}")

    # Fetch positions and filter for target account
    try:
        positions = ib.positions()
        filtered_positions = [p for p in positions if p.account == TARGET_ACCOUNT]
        print("\n=== Positions ===")
        if not filtered_positions:
            print("No positions in this account.")
        for pos in filtered_positions:
            market_price = pos.marketPrice if pos.marketPrice is not None else 0
            value = market_price * pos.position
            print(f"{pos.contract.symbol}: {pos.position} shares, value={value:.2f} {pos.contract.currency}")
    except Exception as e:
        print(f"Error fetching positions: {e}")

    # Disconnect
    ib.disconnect()
    print("\nDisconnected from IBKR")

if __name__ == "__main__":
    main()
