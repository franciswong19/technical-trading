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
SPREADSHEET_ID = "1gEHjNEI-0Zr-_cMzHsOnEurcA0q2rGtdDgEyRKFgY38"
INPUT_TAB_NAME = "segment_6_pos"
OUTPUT_TAB_NAME = "df_daily"

# Polygon API Settings
LOOKBACK = 365
MULTIPLIER = 1
TIMESPAN = "day"
WINDOW = 10

CREDS_FILE_PATH = project_root / 'creds' / 'service_account_key.json'


# ==========================================
# EXECUTION
# ==========================================
def main():
    print(f"--- Starting Daily Pipeline ---")

    # 1. Authenticate and Extract Data
    client = utils_gsheet_handler.authenticate_gsheet(str(CREDS_FILE_PATH))
    if not client: return

    df_full = utils_gsheet_handler.extract_data(client, SPREADSHEET_ID, INPUT_TAB_NAME)
    if df_full is None or df_full.empty:
        print("No data found.")
        return

    # --- FILTER FOR UNPROCESSED ROWS ---
    # Filters rows where 'is_processed' is empty, null, or 0
    df = df_full[ (df_full['is_positive_mg'] == 1) &
                  (df_full['is_processed'].isna() | (df_full['is_processed'] == "") | (df_full['is_processed'] == 0))].copy()

    if df.empty:
        print("All rows are already processed. Exiting.")
        return

    # 2. Processing Loop
    print(f"Processing {len(df)} unprocessed tickers...")

    for index, row in df.iterrows():
        ticker = row.get("ticker")
        date = row.get("date")

        if not ticker or not date:
            continue

        print(f"[{index + 1}] Processing {ticker}...", end=" ")

        # --- THE FIX: CALLING THE TECHNICAL INDICATORS FILE ---
        # This calls the orchestrator function in utils_technical_indicators.py
        results = utils_technical_indicators.process_technical_indicators(
            ticker=ticker,
            end_date=date,
            lookback=LOOKBACK,
            multiplier=MULTIPLIER,
            timespan=TIMESPAN,
            window=WINDOW
        )

        if results:
            # Map results (e.g. rsi_30_crossover_period) to the DataFrame
            for key, value in results.items():
                df.at[index, key] = value

            # Update status
            df.at[index, 'is_processed'] = 1
            print("Done.")
        else:
            print("Failed.")

        # --- API LIMIT PROTECTION ---
        time.sleep(12)

    # 3. Export Results
    # Note: We export 'df' (the processed subset). 
    # If you want to see all rows, you'd merge this back into df_full.
    print("\nExporting results...")
    utils_gsheet_handler.export_data(client, SPREADSHEET_ID, OUTPUT_TAB_NAME, df)
    print("Pipeline Complete.")


if __name__ == "__main__":
    main()