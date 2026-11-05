"""
Unit Tests for Replace Ledger / Department Reclassification & Merge (Ctrl+Y Operation)
"""

import unittest
import tempfile
from pathlib import Path

from app.database import init_db, create_company, get_connection
from app.accounting_engine import post_voucher
from app.ledger_operations import batch_replace_ledger_department, batch_merge_ledgers
from app.server import app


class TestLedgerReplaceOperations(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = Path(self.temp_dir.name) / "test_replace.db"
        init_db(self.test_db_path)

        # Create demo company
        self.cid = create_company(
            name="Vanguard Industries",
            state="Maharashtra",
            state_code="27",
            db_path=self.test_db_path
        )

        conn = get_connection(self.test_db_path)
        cur = conn.cursor()

        # Find Groups: Indirect Expenses and Direct Expenses
        cur.execute("SELECT id FROM ledger_groups WHERE company_id = ? AND name = 'Indirect Expenses'", (self.cid,))
        self.indirect_exp_id = cur.fetchone()[0]

        cur.execute("SELECT id FROM ledger_groups WHERE company_id = ? AND name = 'Direct Expenses'", (self.cid,))
        self.direct_exp_id = cur.fetchone()[0]

        cur.execute("SELECT id FROM ledger_groups WHERE company_id = ? AND name = 'Sundry Debtors'", (self.cid,))
        self.debtors_id = cur.fetchone()[0]

        # Create 3 sample ledgers under Indirect Expenses
        cur.execute("""
            INSERT INTO ledgers (company_id, name, group_id, opening_balance, opening_balance_type, current_balance)
            VALUES (?, 'Office Freight', ?, 1000.0, 'Dr', 1000.0)
        """, (self.cid, self.indirect_exp_id))
        self.led1_id = cur.lastrowid

        cur.execute("""
            INSERT INTO ledgers (company_id, name, group_id, opening_balance, opening_balance_type, current_balance)
            VALUES (?, 'Factory Cartage', ?, 2000.0, 'Dr', 2000.0)
        """, (self.cid, self.indirect_exp_id))
        self.led2_id = cur.lastrowid

        cur.execute("""
            INSERT INTO ledgers (company_id, name, group_id, opening_balance, opening_balance_type, current_balance)
            VALUES (?, 'Master Freight & Logistics', ?, 500.0, 'Dr', 500.0)
        """, (self.cid, self.direct_exp_id))
        self.target_ledger_id = cur.lastrowid

        conn.commit()
        conn.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_batch_replace_department(self):
        """Test reclassifying multiple ledgers to a new department/group"""
        # Move 'Office Freight' and 'Factory Cartage' from Indirect to Direct Expenses
        res = batch_replace_ledger_department(
            company_id=self.cid,
            ledger_ids=[self.led1_id, self.led2_id],
            target_group_id=self.direct_exp_id,
            db_path=self.test_db_path
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["updated_count"], 2)

        # Verify group_id changed in SQLite
        conn = get_connection(self.test_db_path)
        cur = conn.cursor()
        cur.execute("SELECT group_id FROM ledgers WHERE id = ?", (self.led1_id,))
        g1 = cur.fetchone()[0]
        cur.execute("SELECT group_id FROM ledgers WHERE id = ?", (self.led2_id,))
        g2 = cur.fetchone()[0]
        conn.close()

        self.assertEqual(g1, self.direct_exp_id)
        self.assertEqual(g2, self.direct_exp_id)

    def test_batch_merge_ledgers(self):
        """Test merging multiple source ledgers into a target ledger"""
        # Create a voucher with entries using led1
        conn = get_connection(self.test_db_path)
        cur = conn.cursor()
        cur.execute("SELECT id FROM ledgers WHERE company_id = ? AND name = 'Cash'", (self.cid,))
        cash_id = cur.fetchone()[0]
        conn.close()

        vid = post_voucher(
            company_id=self.cid,
            voucher_type="Payment",
            voucher_date="2026-11-03",
            party_ledger_id=self.led1_id,
            journal_postings=[
                {"ledger_id": self.led1_id, "entry_type": "Dr", "amount": 1500.0},
                {"ledger_id": cash_id, "entry_type": "Cr", "amount": 1500.0}
            ],
            db_path=self.test_db_path
        )
        self.assertIsNotNone(vid)

        # Merge led1 into target_ledger
        res = batch_merge_ledgers(
            company_id=self.cid,
            source_ledger_ids=[self.led1_id],
            target_ledger_id=self.target_ledger_id,
            db_path=self.test_db_path
        )
        self.assertTrue(res["success"])

        # Check journal_entries: posting should now point to target_ledger_id
        conn = get_connection(self.test_db_path)
        cur = conn.cursor()
        cur.execute("SELECT ledger_id FROM journal_entries WHERE voucher_id = ? AND entry_type = 'Dr'", (vid,))
        new_lid = cur.fetchone()[0]
        conn.close()

        self.assertEqual(new_lid, self.target_ledger_id)

    def test_api_endpoint(self):
        """Test /api/ledgers/replace-transfer Flask endpoint"""
        client = app.test_client()
        # Test Department replacement via API
        payload = {
            "ledger_ids": [self.led1_id],
            "mode": "department",
            "target_id": self.debtors_id
        }
        res = client.post("/api/ledgers/replace-transfer", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])


if __name__ == "__main__":
    unittest.main()

