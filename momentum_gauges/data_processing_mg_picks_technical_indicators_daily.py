import os
import sys
import time
import pandas as pd
from pathlib import Path

# --- PATH SETUP ---
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
sys.path.append(str(project_root))

# Import your modules
from utils import utils_gsheet_handler
from utils import utils_technical_indicators

# ==========================================
# USER CONFIGURATION
# ==========================================
SPREADSHEET_ID = "13RfATfhAOOp_RCr3a_clcwXjrVdaFRib0_JTxUj729Q"
INPUT_TAB_NAME = "shortlist"
# Recommended: change output tab so you don't overwrite your main processed data
OUTPUT_TAB_NAME = "df_processed"

# Polygon API Settings
LOOKBACK = 365
MULTIPLIER = 1
TIMESPAN = "day"
WINDOW = 10
#DATE = '2025-12-22'
# Gets current date, subtracts 1 day, and formats as 'YYYY-MM-DD'
DATE = (pd.Timestamp.now() - pd.Timedelta(days=1)).strftime('%Y-%m-%d')

CREDS_FILE_PATH = project_root / 'creds' / 'service_account_key.json'


# ==========================================
# EXECUTION
# ==========================================
def main():
    print(f"--- Starting Filtered Pipeline ---")

    # 1. Authenticate and Extract Data
    client = utils_gsheet_handler.authenticate_gsheet(str(CREDS_FILE_PATH))
    if not client: return

    # CHANGE 1: Use the full extracted dataframe directly (no processing filter)
    df = utils_gsheet_handler.extract_data(client, SPREADSHEET_ID, INPUT_TAB_NAME)
    if df is None or df.empty:
        print("No data found.")
        return

    # --- ADDED LINE: Assign the global DATE to the entire column ---
    df["date"] = DATE

    # 2. Processing Loop
    print(f"Processing {len(df)} tickers...")

    for index, row in df.iterrows():
        ticker = row.get("ticker")
        date = row.get("date")

        if not ticker or not date:
            continue

        print(f"[{index + 1}/{len(df)}] Processing {ticker}...", end=" ")

        results = utils_technical_indicators.process_technical_indicators(
            ticker=ticker,
            end_date=date,
            lookback=LOOKBACK,
            multiplier=MULTIPLIER,
            timespan=TIMESPAN,
            window=WINDOW
        )

        if results:
            for key, value in results.items():
                df.at[index, key] = value
            # CHANGE 2: Removed 'is_processed' update line
            print("Done.")
        else:
            print("Failed.")

        time.sleep(12)

    # CHANGE 3: Final filter for crossover values of 0, 1, or 2
    crossover_cols = [col for col in df.columns if "crossover" in col]
    if crossover_cols:
        print("\nFiltering for recent signals (0, 1, 2)...")
        # Keep rows where ANY crossover column has a value of 0, 1, or 2
        df = df[df[crossover_cols].isin([0, 1, 2]).any(axis=1)].copy()

    # 3. Export Results
    print(f"Exporting {len(df)} filtered rows...")
    utils_gsheet_handler.export_data(client, SPREADSHEET_ID, OUTPUT_TAB_NAME, df)
    print("Pipeline Complete.")


if __name__ == "__main__":
    main()