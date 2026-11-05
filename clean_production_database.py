"""
Ledger Pro - Production Database Sanitization & Reset Utility
Cleans all temporary development/testing records and leaves the production database
in a pristine state, ready for client deployment.
"""

import sys
import sqlite3
from pathlib import Path
from app.config import DATABASE_PATH, BASE_DIR
from app.database import init_db
from app.manufacturing_engine import init_manufacturing_schema
from app.physical_stock_engine import init_physical_stock_schema
from app.tds_tcs_engine import init_tds_schema
from app.payroll_engine import init_payroll_schema
from app.edit_log_engine import init_edit_log_schema
from app.currency_engine import init_currency_schema
from app.pos_engine import init_pos_schema
from app.budget_engine import init_budget_schema
from app.price_list_engine import init_price_list_schema


def clean_database():
    print("[1/4] Ensuring clean file state...")
    wal = Path(str(DATABASE_PATH) + "-wal")
    shm = Path(str(DATABASE_PATH) + "-shm")

    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()
    if wal.exists():
        wal.unlink()
    if shm.exists():
        shm.unlink()

    print("[2/4] Initializing clean production schemas (all 39 tables & constraints)...")
    init_db(DATABASE_PATH)
    init_manufacturing_schema()
    init_physical_stock_schema()
    init_tds_schema()
    init_payroll_schema()
    init_edit_log_schema()
    init_currency_schema()
    init_pos_schema()
    init_budget_schema()
    init_price_list_schema()

    print("[3/4] Verifying database integrity and constraints...")
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute("PRAGMA integrity_check")
    integ = c.fetchone()[0]
    if integ != "ok":
        raise RuntimeError(f"Database integrity check failed: {integ}")

    c.execute("PRAGMA foreign_key_check")
    fk_violations = c.fetchall()
    if fk_violations:
        raise RuntimeError(f"Foreign key violations detected: {fk_violations}")

    c.execute("SELECT COUNT(*) FROM companies")
    ccount = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM vouchers")
    vcount = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM ledgers")
    lcount = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM stock_items")
    scount = c.fetchone()[0]
    conn.close()

    print("[4/4] Validation Summary:")
    print(f"  - Database Status: {integ.upper()}")
    print(f"  - Foreign Key Errors: {len(fk_violations)}")
    print(f"  - Companies: {ccount} (Clean)")
    print(f"  - Vouchers: {vcount} (Clean)")
    print(f"  - Ledgers: {lcount} (Clean)")
    print(f"  - Stock Items: {scount} (Clean)")
    print("\nSUCCESS: Production database is 100% fresh, pristine, and ready for client onboarding!")


if __name__ == "__main__":
    clean_database()
