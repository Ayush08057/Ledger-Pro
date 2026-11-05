"""
TallySoft Statutory Audit Trail & Edit Log Engine
Implements Ministry of Corporate Affairs (MCA) and TallyPrime Edit Log compliance.
Records immutable versioned snapshots for vouchers, ledgers, and items,
with full field-level diffs and history tracking.
"""

import json
from typing import List, Dict, Any, Optional
from datetime import datetime
from app.database import transaction


def init_edit_log_schema(db_path=None):
    """
    Initializes edit log snapshots table safely.
    """
    with transaction(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS edit_log_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                entity_type TEXT NOT NULL CHECK(entity_type IN ('Voucher', 'Ledger', 'StockItem', 'Company')),
                entity_id INTEGER NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                action TEXT NOT NULL CHECK(action IN ('CREATE', 'ALTER', 'UPDATE', 'DELETE', 'CANCEL')),
                user_name TEXT NOT NULL DEFAULT 'Admin',
                snapshot_json TEXT NOT NULL,
                changes_summary TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_edit_log_entity 
            ON edit_log_snapshots(entity_type, entity_id, version)
        """)


def record_edit_log(
    company_id: int,
    entity_type: str,
    entity_id: int,
    action: str,
    current_data: Dict[str, Any],
    user_name: str = "Admin",
    db_path=None
) -> int:
    """
    Records an immutable version snapshot of the entity.
    Automatically increments version number and computes difference summary.
    """
    init_edit_log_schema(db_path)
    with transaction(db_path) as conn:
        # Get latest version number
        row = conn.execute("""
            SELECT MAX(version) as max_v, snapshot_json 
            FROM edit_log_snapshots
            WHERE company_id = ? AND entity_type = ? AND entity_id = ?
        """, (company_id, entity_type, entity_id)).fetchone()

        max_v = row['max_v'] if row and row['max_v'] else 0
        new_v = max_v + 1

        changes = []
        if max_v > 0 and row['snapshot_json']:
            old_data = json.loads(row['snapshot_json'])
            for k, val in current_data.items():
                if k in old_data and old_data[k] != val:
                    changes.append(f"{k}: '{old_data[k]}' -> '{val}'")
            changes_summary = "; ".join(changes) if changes else "No field changes detected"
        else:
            changes_summary = f"{entity_type} created initially (Version 1)"

        cursor = conn.execute("""
            INSERT INTO edit_log_snapshots (
                company_id, entity_type, entity_id, version, action,
                user_name, snapshot_json, changes_summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            company_id, entity_type, entity_id, new_v, action,
            user_name, json.dumps(current_data, default=str), changes_summary
        ))

        # Also insert into general audit_logs for backward compatibility
        audit_action = 'UPDATE' if action == 'ALTER' else ('DELETE' if action == 'CANCEL' else action)
        if audit_action not in ('CREATE', 'UPDATE', 'DELETE'):
            audit_action = 'UPDATE'

        conn.execute("""
            INSERT INTO audit_logs (company_id, entity_type, entity_id, action, details)
            VALUES (?, ?, ?, ?, ?)
        """, (company_id, entity_type, entity_id, audit_action, changes_summary))

        return cursor.lastrowid


def get_entity_edit_log(company_id: int, entity_type: str, entity_id: int, db_path=None) -> List[Dict[str, Any]]:
    """
    Fetches complete chronological edit log history for a specific entity.
    """
    init_edit_log_schema(db_path)
    with transaction(db_path) as conn:
        rows = conn.execute("""
            SELECT id, company_id, entity_type, entity_id, version, action,
                   user_name, snapshot_json, changes_summary, created_at
            FROM edit_log_snapshots
            WHERE company_id = ? AND entity_type = ? AND entity_id = ?
            ORDER BY version DESC
        """, (company_id, entity_type, entity_id)).fetchall()

        result = []
        for r in rows:
            item = dict(r)
            try:
                item['snapshot'] = json.loads(item['snapshot_json'])
            except Exception:
                item['snapshot'] = {}
            result.append(item)
        return result


def list_recent_audit_trail(company_id: int, limit: int = 50, db_path=None) -> List[Dict[str, Any]]:
    """
    Fetches recent organization-wide audit trail entries across all vouchers and masters.
    """
    init_edit_log_schema(db_path)
    with transaction(db_path) as conn:
        rows = conn.execute("""
            SELECT id, company_id, entity_type, entity_id, version, action,
                   user_name, changes_summary, created_at
            FROM edit_log_snapshots
            WHERE company_id = ?
            ORDER BY id DESC
            LIMIT ?
        """, (company_id, limit)).fetchall()
        return [dict(r) for r in rows]
