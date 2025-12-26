import os
import json

def test_secrets():
    print("Checking for Polygon Key...")
    poly_key = os.getenv('POLYGON_API_KEY')
    if poly_key:
        print(f"✅ Polygon Key Found! (Ends with: ...{poly_key[-3:]})")
    else:
        print("❌ Polygon Key Missing!")

    print("\nChecking for Google Credentials...")
    g_json = os.getenv('GCP_SERVICE_ACCOUNT_JSON')
    if g_json:
        try:
            parsed = json.loads(g_json)
            print(f"✅ Google JSON Found! Service Account: {parsed.get('client_email')}")
        except Exception as e:
            print(f"❌ Google JSON found but failed to parse: {e}")
    else:
        print("❌ Google JSON Missing!")

if __name__ == "__main__":
    test_secrets()