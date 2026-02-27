"""
config.py

Central configuration for the trade execution system.
All tunable parameters live here - nothing is hardcoded in executor scripts.
"""

import os

# ==========================================
# IBKR CONNECTION
# ==========================================
IBKR_HOST = '127.0.0.1'
LIVE_PORT = 7496
PAPER_PORT = 7497

# Client IDs: use 10-19 range to avoid conflicts with existing scripts (which use 1, 2, 9)
BASE_CLIENT_ID = 10

# ==========================================
# ACCOUNTS REGISTRY
# ==========================================
# Account IDs are loaded from GitHub Secret (IBKR_ACCOUNTS env var) first,
# then fall back to local creds/ibkr_accounts.txt file.
# Env var format: "LIVE-US=U...,LIVE-US-2=U...,LIVE-EU=U..."
# Creds file format: one ALIAS=ACCOUNT_ID per line

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_account_ids():
    """
    Load account IDs from env var first, then fall back to creds file.
    Env var: IBKR_ACCOUNTS = "LIVE-US=U...,LIVE-US-2=U...,LIVE-EU=U..."
    Creds file: creds/ibkr_accounts.txt with one ALIAS=ACCOUNT_ID per line.
    """
    accounts = {}

    # 1. Try GitHub Secret (single env var, comma-separated)
    env_val = os.getenv('IBKR_ACCOUNTS')
    if env_val:
        for pair in env_val.split(','):
            pair = pair.strip()
            if '=' in pair:
                alias, account_id = pair.split('=', 1)
                accounts[alias.strip()] = account_id.strip()
        return accounts

    # 2. Fall back to local creds file
    creds_path = os.path.join(_PROJECT_ROOT, 'creds', 'ibkr_accounts.txt')
    if os.path.exists(creds_path):
        with open(creds_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and '=' in line:
                    alias, account_id = line.split('=', 1)
                    accounts[alias.strip()] = account_id.strip()

    return accounts


_ACCOUNT_IDS = _load_account_ids()

ACCOUNTS = {
    'LIVE-US': {
        'account_id': _ACCOUNT_IDS.get('LIVE-US', ''),
        'port': LIVE_PORT,
    },
    'LIVE-US-2': {
        'account_id': _ACCOUNT_IDS.get('LIVE-US-2', ''),
        'port': LIVE_PORT,
    },
    'LIVE-EU': {
        'account_id': _ACCOUNT_IDS.get('LIVE-EU', ''),
        'port': LIVE_PORT,
    },
}

# ==========================================
# EXCHANGE CONFIGURATIONS
# ==========================================
# Each exchange defines its timezone, market calendar, cutoff timing,
# currency, and IBKR routing exchange.
EXCHANGES = {
    'US': {
        'timezone': 'US/Eastern',
        'calendar': 'NYSE',
        'cutoff_minutes_before_close': 15,  # 3:45 PM ET (NYSE closes 4:00 PM)
        'currency': 'USD',
        'ibkr_exchange': 'SMART',
    },
    'XETRA': {
        'timezone': 'Europe/Berlin',
        'calendar': 'XETRA',
        'cutoff_minutes_before_close': 15,  # 5:15 PM CET (XETRA closes 5:30 PM)
        'currency': 'EUR',
        'ibkr_exchange': 'IBIS',
    },
    'EURONEXT': {
        'timezone': 'Europe/Paris',
        'calendar': 'EURONEXT',
        'cutoff_minutes_before_close': 15,  # 5:15 PM CET (Euronext closes 5:30 PM)
        'currency': 'EUR',
        'ibkr_exchange': 'AEB',  # Amsterdam; use 'SBF' for Paris, 'BVME' for Milan, etc.
    },
}

# ==========================================
# STOP LOSS PERCENTAGES
# ==========================================
STOP_NORMAL_PCT = 0.08      # 8% below buy price
STOP_HEIGHTENED_PCT = 0.03  # 3% below buy price

# ==========================================
# MONITORING INTERVALS (seconds)
# ==========================================
NORMAL_CHECK_INTERVAL = 600   # 10 minutes
FAST_CHECK_INTERVAL = 60      # 1 minute
HOT_POTATO_STOP_CHECK_INTERVAL = 300  # 5 minutes (for monitoring stop triggers)

# ==========================================
# STOP LOSS DELAY
# ==========================================
STOP_LOSS_DELAY = 900  # 15 minutes after fill before placing stop loss

# ==========================================
# DURATION
# ==========================================
MINIMUM_DURATION_MINUTES = 3

# ==========================================
# HOT POTATO
# ==========================================
DEFAULT_CYCLE_THRESHOLD = 3

# ==========================================
# REQUEST TYPES (enum-like constants)
# ==========================================
REQUEST_SELL_EVERYTHING_NOW = 'SELL_EVERYTHING_NOW'
REQUEST_NORMAL_BUY = 'NORMAL_BUY'
REQUEST_NORMAL_SELL = 'NORMAL_SELL'
REQUEST_FAST_BUY = 'FAST_BUY'
REQUEST_FAST_SELL = 'FAST_SELL'
REQUEST_HOT_POTATO = 'HOT_POTATO'

VALID_REQUEST_TYPES = [
    REQUEST_SELL_EVERYTHING_NOW,
    REQUEST_NORMAL_BUY,
    REQUEST_NORMAL_SELL,
    REQUEST_FAST_BUY,
    REQUEST_FAST_SELL,
    REQUEST_HOT_POTATO,
]

# ==========================================
# DURATION TYPES
# ==========================================
DURATION_IMMEDIATE = 'IMMEDIATE'
DURATION_BEFORE_CLOSE = 'BEFORE_CLOSE'
DURATION_TIMED = 'TIMED'

# ==========================================
# GOOGLE SHEETS
# ==========================================
EXECUTION_LOG_SPREADSHEET_ID = ''  # To be configured after creating the spreadsheet
EXECUTION_LOG_TAB = 'Execution Log'
DAILY_SUMMARY_TAB = 'Daily Summary'
ERRORS_TAB = 'Errors'
STOP_LOSS_TRACKER_TAB = 'Stop Loss Tracker'

# ==========================================
# CREDENTIALS
# ==========================================
GSHEET_CREDS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'creds', 'service_account_key.json')

# ==========================================
# STATE DIRECTORIES
# ==========================================
STATE_DIR = os.path.join(_PROJECT_ROOT, 'trade_executor', 'state')
REQUESTS_DIR = os.path.join(STATE_DIR, 'requests')
RESULTS_DIR = os.path.join(STATE_DIR, 'results')
STATUS_DIR = os.path.join(STATE_DIR, 'status')
REQUEST_COUNTER_FILE = os.path.join(STATE_DIR, 'request_counter.json')
