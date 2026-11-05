import os
import shutil
from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).resolve().parent.parent

# Vercel Serverless Environment Detection
IS_VERCEL = bool(os.environ.get("VERCEL"))

if IS_VERCEL:
    # Vercel serverless functions have a read-only filesystem except /tmp
    DATA_DIR = Path("/tmp/data")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DATABASE_PATH = DATA_DIR / "tally_offline.db"
    starter_db = BASE_DIR / "data" / "tally_offline.db"
    if not DATABASE_PATH.exists() and starter_db.exists():
        try:
            shutil.copy2(starter_db, DATABASE_PATH)
        except Exception:
            pass
else:
    DATA_DIR = BASE_DIR / "data"
    DATABASE_PATH = DATA_DIR / "tally_offline.db"
    DATA_DIR.mkdir(parents=True, exist_ok=True)

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

