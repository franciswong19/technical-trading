# utils/utils_polygon_connection.py

import os


def get_api_key(filename="polygon_api_key.txt"):
    """
    Attempts to load the Polygon API key from a text file inside the 'creds' folder.
    """
    # Get the directory of this current file (utils/)
    current_dir = os.path.dirname(os.path.abspath(__file__))

    # UPDATE: Path to the key file inside the 'creds' folder
    # We go up one level to the root, then into 'creds', then find the filename
    key_path = os.path.join(current_dir, '..', 'creds', filename)

    try:
        with open(key_path, "r") as f:
            api_key = f.read().strip()
            if not api_key:
                print(f"Warning: {filename} is empty.")
            return api_key
    except FileNotFoundError:
        print(f"Error: '{filename}' not found at {os.path.abspath(key_path)}")
        return ""


# Initialize the global API_KEY for other files to import
API_KEY = get_api_key()