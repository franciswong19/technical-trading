import sys
import os
import pandas as pd
import time
from pathlib import Path

# --- THIS BLOCK MUST BE BEFORE 'from utils import ...' ---
current_dir = Path(__file__).resolve().parent  # This is the 'mda_picks' folder
project_root = current_dir.parent             # This is the 'TechnicalTrading' root
sys.path.append(str(project_root))            # Adds root to Python's search list

# Now the imports will work
from utils import utils_gsheet_handler
from utils import utils_tp_sl_simulation as sim

# ==========================================
# CONFIGURATION
# ==========================================
SPREADSHEET_ID = "1gEHjNEI-0Zr-_cMzHsOnEurcA0q2rGtdDgEyRKFgY38"
INPUT_TAB_NAME = "segment_6_pos"
OUTPUT_TAB_NAME = "df_backtest"

TRADING_DAYS = 10
CALENDAR_DAYS = 20

# TP, SL, Start Day, End Day
TP_SL_CONFIG = [
    [1.15, 0.90, 0, 1],
    [1.15, 0.90, 2, 3],
    [1.15, 0.90, 4, TRADING_DAYS - 1]
]


def main():
    print("--- Starting Backtest Simulation ---")
    creds = project_root / 'creds' / 'service_account_key.json'
    client = utils_gsheet_handler.authenticate_gsheet(str(creds))
    if not client: return

    # --- PART 1: PRE-PROCESS ---
    df_raw = utils_gsheet_handler.extract_data(client, SPREADSHEET_ID, INPUT_TAB_NAME)
    if df_raw is None or df_raw.empty: return

    # 1. Filter and dedupe
    df = df_raw[
        (df_raw['is_positive_mg'] == 1) & (df_raw['mcap'] >= 500) &
        ((df_raw['is_processed'] != 1) | (df_raw['is_processed'].isna()) | (df_raw['is_processed'] == ""))
        ].copy()

    # 2. Define the columns you want to deduplicate by (the "keys")
    dedupe_keys = ['date', 'ticker', 'sector', 'is_positive_mg']

    # 3. Use groupby to find the maximum for mcap and price within those groups
    df = df.groupby(dedupe_keys, as_index=False).agg({
        'mcap': 'max',
        'price': 'max'
    })

    # Optional: Reorder columns to match your original subset_cols if needed
    subset_cols = ['date', 'ticker', 'sector', 'price', 'mcap', 'is_positive_mg']
    df = df[subset_cols].reset_index(drop=True)

    if df.empty:
        print("No new valid picks found for simulation.")
        return

    # --- PART 2 & 3: EXECUTION ---
    final_results = []
    print(f"Processing {len(df)} unique ticker-date combinations...")

    for idx, row in df.iterrows():
        print(f"[{idx + 1}/{len(df)}] Simulating {row['ticker']}...")

        outcome = sim.run_simulation(
            ticker=row['ticker'],
            pick_date=row['date'],
            calendar_days=CALENDAR_DAYS,
            tp_sl_list=TP_SL_CONFIG,
            trading_days_limit=TRADING_DAYS
        )

        if not outcome.get("error"):
            # Combine original data with outcome results
            final_results.append({**row.to_dict(), **outcome})
            print(f"  -> {outcome['trigger']} Success.")
        else:
            print(f"  -> Error: {outcome['error']}")

        time.sleep(12)  # API Limit protection

    # --- PART 4: EXPORT ---
    if final_results:
        df_export = pd.DataFrame(final_results).drop(columns=['error'], errors='ignore')
        utils_gsheet_handler.export_data(client, SPREADSHEET_ID, OUTPUT_TAB_NAME, df_export)
        print("Backtest results exported successfully.")


if __name__ == "__main__":
    main()