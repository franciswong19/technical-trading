"""
request_id.py

Generates sequential request IDs in the format YYYYMMDD-XXX.
XXX resets to 001 at the start of each new calendar day.
"""

import os
import json
from datetime import datetime

import pytz

from trade_executor.config import REQUEST_COUNTER_FILE, STATE_DIR, EXCHANGES


def generate_request_id(exchange: str) -> str:
    """
    Generate the next sequential request ID.

    Format: YYYYMMDD-XXX where XXX is zero-padded (001, 002, ..., 999).
    Resets to 001 at the start of each new calendar day.
    The date uses the exchange's local timezone.

    Args:
        exchange: Exchange key ('US', 'XETRA', 'EURONEXT')

    Returns:
        str: Request ID (e.g. '20260218-001')
    """
    tz = pytz.timezone(EXCHANGES[exchange]['timezone'])
    today = datetime.now(tz).strftime('%Y%m%d')

    # Ensure state directory exists
    os.makedirs(STATE_DIR, exist_ok=True)

    # Read current counter
    counter_data = {'date': today, 'last_seq': 0}
    if os.path.exists(REQUEST_COUNTER_FILE):
        with open(REQUEST_COUNTER_FILE, 'r') as f:
            try:
                counter_data = json.load(f)
            except (json.JSONDecodeError, KeyError):
                counter_data = {'date': today, 'last_seq': 0}

    # Reset if new day
    if counter_data.get('date') != today:
        counter_data = {'date': today, 'last_seq': 0}

    # Increment
    next_seq = counter_data['last_seq'] + 1
    counter_data['last_seq'] = next_seq

    # Write back
    with open(REQUEST_COUNTER_FILE, 'w') as f:
        json.dump(counter_data, f)

    return f"{today}-{next_seq:03d}"


def get_current_counter() -> dict:
    """Read the current counter state without incrementing.

    Returns:
        dict: {'date': 'YYYYMMDD', 'last_seq': int}
    """
    if os.path.exists(REQUEST_COUNTER_FILE):
        with open(REQUEST_COUNTER_FILE, 'r') as f:
            try:
                return json.load(f)
            except (json.JSONDecodeError, KeyError):
                pass
    return {'date': '', 'last_seq': 0}
