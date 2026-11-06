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
    Automatically supports US and Asia-Southeast regional database endpoints.
    """
    config = get_firebase_config()
    db_url = config.get("database_url", "").strip()

    if not db_url or "YOUR_PROJECT_ID" in db_url:
        return False

    project_id = config.get("project_id", "ledger-pro-19a1e")
    urls_to_try = [
        db_url,
        f"https://{project_id}-default-rtdb.firebaseio.com",
        f"https://{project_id}-default-rtdb.asia-southeast1.firebasedatabase.app"
    ]
    
    data = get_mobile_dashboard_data(company_id)
    payload = json.dumps(data).encode("utf-8")
    auth_token = config.get("auth_token", "").strip()

    for u in urls_to_try:
        if not u.startswith("http"):
            u = "https://" + u
        if u.endswith("/"):
            u = u[:-1]
        endpoint = f"{u}/dashboard.json"
        if auth_token:
            endpoint += f"?auth={auth_token}"

        try:
            req = urllib.request.Request(
                endpoint,
                data=payload,
                method="PUT",
                headers={"Content-Type": "application/json", "User-Agent": "LedgerProSync/1.0"}
            )
            with urllib.request.urlopen(req, timeout=6) as res:
                if res.status in (200, 204):
                    return True
        except Exception:
            continue
    return False


def async_firebase_sync(company_id: int = 1):
    """
    Triggers the sync in a non-blocking background thread
    so the offline desktop software is never slowed down.
    """
    thread = threading.Thread(target=push_dashboard_to_firebase, args=(company_id,), daemon=True)
    thread.start()

