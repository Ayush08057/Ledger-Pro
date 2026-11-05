"""
Unit Tests for Phase 1: Database Scaffolding, Foreign Keys & Chart of Accounts
"""

import unittest
import sqlite3
import os
import tempfile
from pathlib import Path

from app.database import init_db, create_company, list_companies, get_company_groups, get_company_ledgers, get_connection
from app.seed_data import PRIMARY_GROUPS, SUB_GROUPS, DEFAULT_LEDGERS, DEFAULT_UNITS


class TestPhase1DatabaseAndCoA(unittest.TestCase):
    def setUp(self):
        # Create a temporary database for test isolation
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = Path(self.temp_dir.name) / "test_tally.db"
        init_db(self.test_db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_schema_creation_and_tables(self):
        """Verify all required accounting tables exist"""
        expected_tables = {
            "companies",
            "ledger_groups",
            "ledgers",
            "units",
            "stock_groups",
            "stock_items",
            "vouchers",
            "voucher_inventory_items",
            "journal_entries",
            "audit_logs",
        }
        conn = get_connection(self.test_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()

        for t in expected_tables:
            self.assertIn(t, tables, f"Expected table '{t}' was not found in schema.")

    def test_company_creation_and_seeding(self):
        """Verify company creation seeds exactly 28 groups and all standard ledgers"""
        cid = create_company(
            name="Alpha Enterprises",
            legal_name="Alpha Enterprises Pvt Ltd",
            gstin="27ABCDE1234F1Z5",
            pan="ABCDE1234F",
            state="Maharashtra",
            state_code="27",
            db_path=self.test_db_path,
        )
        self.assertEqual(cid, 1)

        groups = get_company_groups(cid, db_path=self.test_db_path)
        # 15 primary + 13 sub-groups = 28 groups
        self.assertEqual(len(groups), len(PRIMARY_GROUPS) + len(SUB_GROUPS))

        # Check that specific key groups exist
        group_names = {g['name'] for g in groups}
        self.assertIn("Capital Account", group_names)
        self.assertIn("Current Assets", group_names)
        self.assertIn("Duties & Taxes", group_names)
        self.assertIn("Sundry Debtors", group_names)
        self.assertIn("Sundry Creditors", group_names)

        # Check default ledgers
        ledgers = get_company_ledgers(cid, db_path=self.test_db_path)
        ledger_names = {l['name'] for l in ledgers}
        self.assertEqual(len(ledgers), len(DEFAULT_LEDGERS))
        self.assertIn("Cash", ledger_names)
        self.assertIn("Profit & Loss A/c", ledger_names)
        self.assertIn("Input CGST", ledger_names)
        self.assertIn("Output CGST", ledger_names)

        # Check standard units
        conn = get_connection(self.test_db_path)
        cur = conn.cursor()
        cur.execute("SELECT symbol FROM units WHERE company_id = ?", (cid,))
        unit_symbols = {row[0] for row in cur.fetchall()}
        conn.close()
        self.assertEqual(len(unit_symbols), len(DEFAULT_UNITS))
        self.assertIn("PCS", unit_symbols)
        self.assertIn("KGS", unit_symbols)

    def test_foreign_key_enforcement(self):
        """Verify that SQLite foreign key constraints are actively enforced"""
        conn = get_connection(self.test_db_path)
        cursor = conn.cursor()

        # Attempting to insert a ledger with non-existent company_id should raise IntegrityError
        with self.assertRaises(sqlite3.IntegrityError):
            cursor.execute(
                """
                INSERT INTO ledgers (company_id, name, group_id)
                VALUES (9999, 'Orphan Ledger', 1)
                """
            )
        conn.close()

    def test_double_entry_constraint_checks(self):
        """Verify check constraints on journal entries (e.g. entry_type must be Dr or Cr)"""
        cid = create_company(name="Beta Traders", db_path=self.test_db_path)
        conn = get_connection(self.test_db_path)
        cursor = conn.cursor()

        # Create a voucher first
        cursor.execute(
            """
            INSERT INTO vouchers (company_id, voucher_number, voucher_type, voucher_date)
            VALUES (?, 'JV-001', 'Journal', '2026-11-03')
            """,
            (cid,)
        )
        vid = cursor.lastrowid

        # Fetch Cash ledger id
        cursor.execute("SELECT id FROM ledgers WHERE company_id = ? AND name = 'Cash'", (cid,))
        cash_id = cursor.fetchone()[0]

        # Inserting invalid entry_type (e.g. 'Invalid') should fail check constraint
        with self.assertRaises(sqlite3.IntegrityError):
            cursor.execute(
                """
                INSERT INTO journal_entries (voucher_id, company_id, ledger_id, entry_type, amount, entry_date)
                VALUES (?, ?, ?, 'INVALID', 5000.0, '2026-11-03')
                """,
                (vid, cid, cash_id)
            )

        # Inserting non-positive amount should fail check constraint
        with self.assertRaises(sqlite3.IntegrityError):
            cursor.execute(
                """
                INSERT INTO journal_entries (voucher_id, company_id, ledger_id, entry_type, amount, entry_date)
                VALUES (?, ?, ?, 'Dr', -500.0, '2026-11-03')
                """,
                (vid, cid, cash_id)
            )

        conn.close()


if __name__ == "__main__":
    unittest.main()

