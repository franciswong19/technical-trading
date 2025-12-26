# utils/utils_polygon_connection.py
import os

def get_api_key(filename="polygon_api_key.txt"):
    """
    Retrieves the Polygon API key.
    Checks for a GitHub Secret (environment variable) first.
    Falls back to loading from a text file inside the 'creds' folder.
    """
    # 1. First, try to get the key from the GitHub Secret / Environment Variable
    api_key = os.getenv('POLYGON_API_KEY_GITHUB')
    
    if api_key:
        print("Using POLYGON_API_KEY from environment variables.")
        return api_key

    # 2. Fallback: Load from the local text file if not in the cloud
    current_dir = os.path.dirname(os.path.abspath(__file__))
    key_path = os.path.join(current_dir, '..', 'creds', filename)

    try:
        if os.path.exists(key_path):
            with open(key_path, "r") as f:
                api_key = f.read().strip()
                if api_key:
                    print(f"Using local key from: {filename}")
                    return api_key
                else:
                    print(f"Warning: {filename} is empty.")
        else:
            print(f"Error: Local key file '{filename}' not found at {os.path.abspath(key_path)}")
            
    except Exception as e:
        print(f"An error occurred while reading the local key: {e}")
        
    return ""

# Initialize the global API_KEY for other files to import
API_KEY = get_api_key()