"""
TallySoft Database Management Module
Provides connection handling, schema initialization, and company lifecycle management.
"""

import sqlite3
import os
import json
from pathlib import Path
from contextlib import contextmanager
from typing import Optional, List, Dict, Any

from app.config import DATABASE_PATH, DATA_DIR, IS_SERVERLESS
from app.seed_data import seed_company_defaults

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """
    Returns an SQLite connection with Foreign Keys enabled and Row factory configured.
    """
    path = db_path or DATABASE_PATH
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.execute("PRAGMA foreign_keys = ON;")
    if not IS_SERVERLESS:
        try:
            conn.execute("PRAGMA journal_mode = WAL;")  # Write-Ahead Logging for speed & safety
        except Exception:
            pass
    else:
        try:
            conn.execute("PRAGMA journal_mode = DELETE;")
        except Exception:
            pass

    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def transaction(db_path: Optional[Path] = None):
    """
    Context manager for atomic database operations. Rolls back on exception.
    """
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Optional[Path] = None):
    """
    Executes schema.sql to initialize all tables, constraints, and indexes.
    """
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    with transaction(db_path) as conn:
        conn.executescript(schema_sql)


def create_company(
    name: str,
    legal_name: Optional[str] = None,
    gstin: Optional[str] = None,
    pan: Optional[str] = None,
    state: str = "Maharashtra",
    state_code: str = "27",
    address: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    currency_symbol: str = "₹",
    fy_start_date: str = "2026-04-01",
    fy_end_date: str = "2027-03-31",
    books_from_date: str = "2026-04-01",
    db_path: Optional[Path] = None,
) -> int:
    """
    Creates a new Company and seeds standard Tally Groups, default Tax Ledgers, and UOMs.
    """
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO companies (
                name, legal_name, gstin, pan, state, state_code,
                address, phone, email, currency_symbol,
                fy_start_date, fy_end_date, books_from_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                legal_name or name,
                gstin,
                pan,
                state,
                state_code,
                address,
                phone,
                email,
                currency_symbol,
                fy_start_date,
                fy_end_date,
                books_from_date,
            ),
        )
        company_id = cursor.lastrowid

        # Seed standard Indian/Tally master data
        seed_company_defaults(conn, company_id)

        # Audit log entry
        cursor.execute(
            """
            INSERT INTO audit_logs (company_id, entity_type, entity_id, action, details)
            VALUES (?, 'Company', ?, 'CREATE', ?)
            """,
            (company_id, company_id, f"Company '{name}' initialized with standard master charts."),
        )

        return company_id


def list_companies(db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """
    Returns all registered companies.
    """
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM companies ORDER BY id ASC")
        return [dict(row) for row in cursor.fetchall()]


def get_company(company_id: int, db_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """
    Returns company details by ID.
    """
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM companies WHERE id = ?", (company_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_company_groups(company_id: int, db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """
    Returns all ledger groups for a given company.
    """
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT g.id, g.name, g.nature, g.affects_gross_profit, p.name AS parent_name
            FROM ledger_groups g
            LEFT JOIN ledger_groups p ON g.parent_group_id = p.id
            WHERE g.company_id = ?
            ORDER BY g.nature, g.name
            """,
            (company_id,),
        )
        return [dict(row) for row in cursor.fetchall()]


def get_company_ledgers(company_id: int, db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """
    Returns all ledgers for a given company.
    """
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT l.*, g.name AS group_name, g.nature AS group_nature
            FROM ledgers l
            JOIN ledger_groups g ON l.group_id = g.id
            WHERE l.company_id = ?
            ORDER BY l.name
            """,
            (company_id,),
        )
        return [dict(row) for row in cursor.fetchall()]


def delete_ledger(company_id: int, ledger_id: int, db_path: Optional[Path] = None) -> Dict[str, Any]:
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM ledgers WHERE id = ? AND company_id = ?", (ledger_id, company_id))
        row = cursor.fetchone()
        if not row:
            return {"success": False, "error": "Ledger not found."}
        name = row["name"]
        if name in ("Cash", "Profit & Loss A/c"):
            return {"success": False, "error": f"Cannot delete standard system ledger '{name}'."}

        cursor.execute("SELECT COUNT(*) FROM journal_entries WHERE ledger_id = ?", (ledger_id,))
        if cursor.fetchone()[0] > 0:
            return {"success": False, "error": f"Cannot delete '{name}': journal transactions exist for this ledger. Use Ctrl+Y to replace/transfer instead."}

        cursor.execute("SELECT COUNT(*) FROM vouchers WHERE party_ledger_id = ?", (ledger_id,))
        if cursor.fetchone()[0] > 0:
            return {"success": False, "error": f"Cannot delete '{name}': vouchers reference this party ledger."}

        cursor.execute("DELETE FROM ledgers WHERE id = ?", (ledger_id,))
        cursor.execute("""
            INSERT INTO audit_logs (company_id, entity_type, entity_id, action, details)
            VALUES (?, 'Ledger', ?, 'DELETE', ?)
        """, (company_id, ledger_id, f"Ledger '{name}' was deleted."))
        return {"success": True}


def delete_stock_item(company_id: int, item_id: int, db_path: Optional[Path] = None) -> Dict[str, Any]:
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM stock_items WHERE id = ? AND company_id = ?", (item_id, company_id))
        row = cursor.fetchone()
        if not row:
            return {"success": False, "error": "Stock item not found."}
        name = row["name"]

        cursor.execute("SELECT COUNT(*) FROM voucher_inventory_items WHERE stock_item_id = ?", (item_id,))
        if cursor.fetchone()[0] > 0:
            return {"success": False, "error": f"Cannot delete '{name}': voucher transactions exist for this stock item."}

        cursor.execute("DELETE FROM stock_items WHERE id = ?", (item_id,))
        cursor.execute("""
            INSERT INTO audit_logs (company_id, entity_type, entity_id, action, details)
            VALUES (?, 'StockItem', ?, 'DELETE', ?)
        """, (company_id, item_id, f"Stock Item '{name}' was deleted."))
        return {"success": True}


def delete_group(company_id: int, group_id: int, db_path: Optional[Path] = None) -> Dict[str, Any]:
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name, is_builtin FROM ledger_groups WHERE id = ? AND company_id = ?", (group_id, company_id))
        row = cursor.fetchone()
        if not row:
            return {"success": False, "error": "Group not found."}
        if row["is_builtin"] == 1:
            return {"success": False, "error": f"Cannot delete standard built-in group '{row['name']}'."}

        cursor.execute("SELECT COUNT(*) FROM ledgers WHERE group_id = ?", (group_id,))
        if cursor.fetchone()[0] > 0:
            return {"success": False, "error": f"Cannot delete group '{row['name']}': ledgers exist under this group."}

        cursor.execute("SELECT COUNT(*) FROM ledger_groups WHERE parent_group_id = ?", (group_id,))
        if cursor.fetchone()[0] > 0:
            return {"success": False, "error": f"Cannot delete group '{row['name']}': sub-groups exist under this group."}

        cursor.execute("DELETE FROM ledger_groups WHERE id = ?", (group_id,))
        return {"success": True}


DEFAULT_COMPANY_FEATURES = {
    "maintain_accounts": "Yes",
    "enable_bill_wise": "Yes",
    "enable_cost_centres": "No",
    "enable_interest": "No",
    "maintain_inventory": "Yes",
    "integrate_accounts": "Yes",
    "enable_price_levels": "Yes",
    "enable_batches": "No",
    "maintain_expiry": "No",
    "enable_job_order": "No",
    "enable_cost_tracking": "No",
    "enable_job_costing": "No",
    "use_discount_column": "No",
    "use_actual_billed_qty": "No",
    "enable_gst": "Yes",
    "set_alter_gst_rate": "No",
    "enable_tds": "Yes",
    "enable_tcs": "No",
    "enable_vat": "No",
    "enable_excise": "No",
    "enable_service_tax": "No",
    "enable_browser_access": "Yes",
    "enable_tally_net": "No",
    "maintain_payroll": "Yes",
    "enable_payroll_statutory": "No",
    "enable_payment_request": "Yes",
    "enable_multiple_addresses": "No",
    "mark_modified_vouchers": "No"
}

DEFAULT_VOUCHER_CONFIG = {
    "use_dr_cr": "Yes",
    "provide_supplier_ref": "No",
    "warn_negative_cash": "Yes",
    "preallocate_bills": "No",
    "show_list_of_bills": "Yes",
    "show_final_balances_bills": "Yes",
    "skip_date_field": "Yes",
    "show_inventory_details": "Yes",
    "show_current_balance": "Yes",
    "show_balances_on_voucher_date": "No",
    "show_final_ledger_balance": "No",
    "show_bill_wise_details": "Yes",
    "show_bill_wise_multiple_lines": "Yes",
    "warn_voucher_no_16": "Yes",
    "enable_stripe_view": "No",
    "bank_default_allocations": "No",
    "bank_auto_cheque_num": "Yes",
    "bank_select_cheque_range": "Yes",
    "bank_show_allocation_details": "No",
    "bank_remove_recon_link": "No",
    "bank_print_cheque": "Yes",
    "bank_show_cheque_before_print": "Yes",
    "pg_default_allocations": "No",
    "pg_show_allocation_details": "No",
    "pg_remove_date_recon": "No"
}


def get_company_features(company_id: int, db_path: Optional[Path] = None) -> Dict[str, str]:
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS company_features (company_id INTEGER PRIMARY KEY, features_json TEXT NOT NULL DEFAULT '{}', voucher_config_json TEXT NOT NULL DEFAULT '{}', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE)")
        cursor.execute("SELECT features_json FROM company_features WHERE company_id = ?", (company_id,))
        row = cursor.fetchone()
        features = dict(DEFAULT_COMPANY_FEATURES)
        if row and row["features_json"]:
            try:
                saved = json.loads(row["features_json"])
                features.update(saved)
            except Exception:
                pass
        return features


def save_company_features(company_id: int, features: Dict[str, str], db_path: Optional[Path] = None) -> bool:
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS company_features (company_id INTEGER PRIMARY KEY, features_json TEXT NOT NULL DEFAULT '{}', voucher_config_json TEXT NOT NULL DEFAULT '{}', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE)")
        current = get_company_features(company_id, db_path)
        current.update(features)
        cursor.execute("""
            INSERT INTO company_features (company_id, features_json, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(company_id) DO UPDATE SET features_json = excluded.features_json, updated_at = CURRENT_TIMESTAMP
        """, (company_id, json.dumps(current)))
        return True


def get_voucher_config(company_id: int, db_path: Optional[Path] = None) -> Dict[str, str]:
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS company_features (company_id INTEGER PRIMARY KEY, features_json TEXT NOT NULL DEFAULT '{}', voucher_config_json TEXT NOT NULL DEFAULT '{}', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE)")
        cursor.execute("SELECT voucher_config_json FROM company_features WHERE company_id = ?", (company_id,))
        row = cursor.fetchone()
        config = dict(DEFAULT_VOUCHER_CONFIG)
        if row and row["voucher_config_json"]:
            try:
                saved = json.loads(row["voucher_config_json"])
                config.update(saved)
            except Exception:
                pass
        return config


def save_voucher_config(company_id: int, config: Dict[str, str], db_path: Optional[Path] = None) -> bool:
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS company_features (company_id INTEGER PRIMARY KEY, features_json TEXT NOT NULL DEFAULT '{}', voucher_config_json TEXT NOT NULL DEFAULT '{}', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE)")
        current = get_voucher_config(company_id, db_path)
        current.update(config)
        cursor.execute("""
            INSERT INTO company_features (company_id, voucher_config_json, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(company_id) DO UPDATE SET voucher_config_json = excluded.voucher_config_json, updated_at = CURRENT_TIMESTAMP
        """, (company_id, json.dumps(current)))
        return True

