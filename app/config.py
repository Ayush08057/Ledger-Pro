import os
import shutil
import tempfile
from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).resolve().parent.parent

# Detect serverless / cloud / read-only filesystem environment
IS_SERVERLESS = (
    bool(os.environ.get("VERCEL")) or
    bool(os.environ.get("VERCEL_ENV")) or
    bool(os.environ.get("AWS_LAMBDA_FUNCTION_NAME")) or
    bool(os.environ.get("LAMBDA_TASK_ROOT")) or
    "/var/task" in str(BASE_DIR) or
    not os.access(str(BASE_DIR), os.W_OK)
)
IS_VERCEL = IS_SERVERLESS

if IS_SERVERLESS:
    # In serverless environments, writable temp directory is tempfile.gettempdir() (/tmp on Linux/Vercel)
    DATA_DIR = Path(tempfile.gettempdir()) / "ledger_pro_data"
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    DATABASE_PATH = DATA_DIR / "tally_offline.db"
    starter_db = BASE_DIR / "data" / "tally_offline.db"
    if not DATABASE_PATH.exists() and starter_db.exists():
        try:
            shutil.copy2(starter_db, DATABASE_PATH)
        except Exception:
            pass
else:
    DATA_DIR = BASE_DIR / "data"
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        DATA_DIR = Path(tempfile.gettempdir()) / "ledger_pro_data"
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
    DATABASE_PATH = DATA_DIR / "tally_offline.db"

# Application Configuration
APP_NAME = "Ledger Pro"
APP_VERSION = "1.0.0"

# Indian States with standard GST State Codes
GST_STATE_CODES = {
    "01": "Jammu & Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "26": "Dadra & Nagar Haveli and Daman & Diu",
    "27": "Maharashtra",
    "29": "Karnataka",
    "30": "Goa",
    "31": "Lakshadweep",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "34": "Puducherry",
    "35": "Andaman & Nicobar Islands",
    "36": "Telangana",
    "37": "Andhra Pradesh",
    "38": "Ladakh",
    "97": "Other Territory"
}

# Standard GST Tax Slabs (%)
GST_SLABS = [0.0, 5.0, 12.0, 18.0, 28.0]

