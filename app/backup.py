"""
TallySoft Backup & Restore Engine
Provides point-in-time database snapshot backups and restoration (Tally Alt+Y Data).
"""

import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

from app.config import DATABASE_PATH, BASE_DIR, IS_SERVERLESS

if IS_SERVERLESS:
    BACKUP_DIR = Path("/tmp/backups")
else:
    BACKUP_DIR = BASE_DIR / "backups"

try:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    BACKUP_DIR = Path("/tmp/backups")
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def create_backup(db_path: Path = None, note: str = "") -> str:
    """
    Creates an atomic SQLite backup file using the SQLite Online Backup API.
    """
    src_path = db_path or DATABASE_PATH
    if not src_path.exists():
        raise FileNotFoundError(f"Database at {src_path} does not exist.")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    clean_note = f"_{note.strip()}" if note else ""
    backup_filename = f"tally_backup_{timestamp}{clean_note}.db"
    backup_filepath = BACKUP_DIR / backup_filename

    # Use SQLite Online Backup API for 100% atomic snapshot while server is running
    src_conn = sqlite3.connect(str(src_path))
    dst_conn = sqlite3.connect(str(backup_filepath))
    with dst_conn:
        src_conn.backup(dst_conn)
    dst_conn.close()
    src_conn.close()

    return str(backup_filepath)


def list_backups() -> List[Dict[str, Any]]:
    """
    Returns list of existing backup files sorted by creation date descending.
    """
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    backups = []
    for f in sorted(BACKUP_DIR.glob("*.db"), key=os.path.getmtime, reverse=True):
        size_kb = round(f.stat().st_size / 1024, 2)
        mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%d-%b-%Y %H:%M:%S")
        backups.append({
            "filename": f.name,
            "filepath": str(f),
            "size_kb": size_kb,
            "created_at": mtime
        })
    return backups


def restore_backup(backup_filename: str, target_db_path: Path = None) -> bool:
    """
    Restores the database from a specified backup file.
    """
    backup_file = BACKUP_DIR / backup_filename
    if not backup_file.exists():
        raise FileNotFoundError(f"Backup file {backup_file} not found.")

    dst_path = target_db_path or DATABASE_PATH

    # Copy backup to target DB using SQLite backup API
    src_conn = sqlite3.connect(str(backup_file))
    dst_conn = sqlite3.connect(str(dst_path))
    with dst_conn:
        src_conn.backup(dst_conn)
    dst_conn.close()
    src_conn.close()

    return True

