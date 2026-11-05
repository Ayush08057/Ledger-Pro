"""
Firebase Realtime Sync Engine for Ledger Pro
Pushes real-time dashboard snapshots from the offline SQLite database
to Firebase Realtime Database using the fast, standard Firebase REST protocol.
"""
import json
import os
import threading
import urllib.request
import urllib.error
from pathlib import Path
from app.mobile_analytics import get_mobile_dashboard_data

CONFIG_FILE = Path(__file__).resolve().parent.parent / "config" / "firebase_config.json"


def get_firebase_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "database_url": os.environ.get("FIREBASE_DATABASE_URL", ""),
        "auth_token": os.environ.get("FIREBASE_AUTH_TOKEN", ""),
        "auto_sync_enabled": True
    }


def push_dashboard_to_firebase(company_id: int = 1) -> bool:
    """
    Computes real-time analytics from local SQLite and pushes
    directly to Firebase Realtime Database at /dashboard.json.
    """
    config = get_firebase_config()
    db_url = config.get("database_url", "").strip()

    # If user hasn't configured Firebase yet or left placeholder, skip gracefully
    if not db_url or "YOUR_PROJECT_ID" in db_url:
        return False

    if not db_url.startswith("http"):
        db_url = "https://" + db_url
    if db_url.endswith("/"):
        db_url = db_url[:-1]

    target_endpoint = f"{db_url}/dashboard.json"
    auth_token = config.get("auth_token", "").strip()
    if auth_token:
        target_endpoint += f"?auth={auth_token}"

    try:
        data = get_mobile_dashboard_data(company_id)
        payload = json.dumps(data).encode("utf-8")

        req = urllib.request.Request(
            target_endpoint,
            data=payload,
            method="PUT",
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=8) as res:
            return res.status in (200, 204)
    except Exception as e:
        print(f"[Firebase Sync Notice] {e}")
        return False


def async_firebase_sync(company_id: int = 1):
    """
    Triggers the sync in a non-blocking background thread
    so the offline desktop software is never slowed down.
    """
    thread = threading.Thread(target=push_dashboard_to_firebase, args=(company_id,), daemon=True)
    thread.start()
