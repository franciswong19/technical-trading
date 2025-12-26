# gsheet_handler.py
import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
from gspread.utils import ValueInputOption


# ==========================================
# GSPREAD HELPER FUNCTIONS
# ==========================================

def authenticate_gsheet(creds_file_path):
    """
    Authenticates with Google Sheets API. 
    Checks for a GitHub Secret first, then falls back to the local JSON file.
    """
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    try:
        # 1. Check if we are running on GitHub (looking for the Secret)
        google_json_str = os.getenv('SERVICE_ACCOUNT_KEY_GITHUB')

        if google_json_str:
            print("Environment variable found. Authenticating via GitHub Secret...")
            creds_info = json.loads(google_json_str)
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scopes=scope)
        else:
            # 2. Fallback to local file if Secret is not found
            print(f"Environment variable not found. Using local file: {creds_file_path}")
            creds = ServiceAccountCredentials.from_json_keyfile_name(creds_file_path, scopes=scope)

        client = gspread.authorize(creds)
        print("GSheet authentication successful.")
        return client
    except Exception as e:
        print(f"Error during GSheet authentication: {e}")
        return None


def extract_data(client, spreadsheet_id, input_tab_name):
    """
    Reads all records from the specified GSheet tab into a Pandas DataFrame.

    Returns:
    - pandas.DataFrame: DataFrame containing the input data, or an empty DataFrame/None on failure.
    """
    try:
        sheet = client.open_by_key(spreadsheet_id)
        worksheet = sheet.worksheet(input_tab_name)

        print(f"Reading data from tab: '{input_tab_name}'...")
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)

        if df.empty:
            print("Input tab is empty.")
            return None

        return df
    except Exception as e:
        print(f"Error extracting data from GSheet: {e}")
        return None


def export_data(client, spreadsheet_id, output_tab_name, df):
    """
    Appends the processed DataFrame rows to the specified GSheet tab.
    Does NOT clear the tab and does NOT include headers.
    """
    if df is None or df.empty:
        print("DataFrame is empty. Skipping export.")
        return

    try:
        sheet = client.open_by_key(spreadsheet_id)

        # 1. Get or create the worksheet
        try:
            out_worksheet = sheet.worksheet(output_tab_name)
        except gspread.exceptions.WorksheetNotFound:
            print(f"Tab '{output_tab_name}' not found. Creating it...")
            out_worksheet = sheet.add_worksheet(title=output_tab_name, rows=100, cols=len(df.columns) + 5)

        # 2. Prepare data: Replace NaNs with empty string
        # --- ADD THIS LINE TO CONVERT TIMESTAMPS TO STRINGS ---
        for col in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                df[col] = df[col].astype(str)
        # -----------------------------------------------------

        df_clean = df.fillna('')

        # 3. Append only the data rows (remove .columns.values.tolist() call)
        # Using append_rows with 'ValueInputOption.user_entered' ensures
        # numbers and dates are formatted correctly in GSheet
        out_worksheet.append_rows(
            values=df_clean.values.tolist(),
            value_input_option=ValueInputOption.user_entered
        )

        print(f"Success! Data appended to tab: '{output_tab_name}'")

    except Exception as e:
        print(f"Error appending data to GSheet: {e}")