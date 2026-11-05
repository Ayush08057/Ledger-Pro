"""
Unit Tests for Bank Reconciliation Statement (BRS) & Cost Centres
"""

import unittest
import tempfile
from pathlib import Path

from app.database import init_db, create_company, get_connection
from app.accounting_engine import post_voucher
from app.brs_engine import (
    get_bank_ledgers,
    get_unreconciled_transactions,
    reconcile_transaction,
    get_brs_summary
)
from app.cost_centre_engine import (
    create_cost_category,
    create_cost_centre,
    list_cost_centres,
    allocate_cost,
    get_cost_centre_breakup_report
)


class TestBrsAndCostCentres(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = Path(self.temp_dir.name) / "test_brs_cc.db"
        init_db(self.test_db_path)

        # Create demo company
        self.cid = create_company(
            name="Quantum Enterprises",
            state="Maharashtra",
            state_code="27",
            db_path=self.test_db_path
        )

        conn = get_connection(self.test_db_path)
        cur = conn.cursor()

        # Find Bank Accounts group
        cur.execute("SELECT id FROM ledger_groups WHERE company_id = ? AND name = 'Bank Accounts'", (self.cid,))
        bank_grp = cur.fetchone()[0]

        # Find Sundry Creditors group
        cur.execute("SELECT id FROM ledger_groups WHERE company_id = ? AND name = 'Sundry Creditors'", (self.cid,))
        creditor_grp = cur.fetchone()[0]

        # Create HDFC Bank Ledger with opening balance ₹1,00,000 Dr
        cur.execute("""
            INSERT INTO ledgers (company_id, name, group_id, opening_balance, opening_balance_type, current_balance, current_balance_type)
            VALUES (?, 'HDFC Bank Current A/c', ?, 100000.0, 'Dr', 100000.0, 'Dr')
        """, (self.cid, bank_grp))
        self.bank_id = cur.lastrowid

        # Create Supplier Ledger
        cur.execute("""
            INSERT INTO ledgers (company_id, name, group_id, opening_balance, opening_balance_type, current_balance)
            VALUES (?, 'Precision Supplies', ?, 0.0, 'Cr', 0.0)
        """, (self.cid, creditor_grp))
        self.supplier_id = cur.lastrowid

        conn.commit()
        conn.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_bank_reconciliation_workflow(self):
        """Test BRS uncleared cheque detection and clearance reconciliation"""
        # 1. Record a payment to Precision Supplies via HDFC Bank: ₹25,000 (Cr HDFC Bank)
        vid = post_voucher(
            company_id=self.cid,
            voucher_type="Payment",
            voucher_date="2026-11-03",
            party_ledger_id=self.supplier_id,
            journal_postings=[
                {"ledger_id": self.supplier_id, "entry_type": "Dr", "amount": 25000.0, "narration": "Vendor Payment"},
                {"ledger_id": self.bank_id, "entry_type": "Cr", "amount": 25000.0, "narration": "Payment via Chq #100201"}
            ],
            db_path=self.test_db_path
        )
        self.assertIsNotNone(vid)

        # 2. Before clearance: Check BRS summary
        brs_before = get_brs_summary(self.cid, self.bank_id, db_path=self.test_db_path)
        # Book balance: 100,000 - 25,000 = 75,000
        self.assertEqual(brs_before["book_balance"], 75000.0)
        # Uncleared payment cheque: 25,000
        self.assertEqual(brs_before["uncleared_payments"], 25000.0)
        # Bank Statement Balance before presentation: 75,000 + 25,000 = 100,000
        self.assertEqual(brs_before["bank_statement_balance"], 100000.0)
        self.assertFalse(brs_before["is_reconciled"])

        # 3. Reconcile: Cheque cleared in bank on 2026-11-05
        txns = get_unreconciled_transactions(self.cid, self.bank_id, db_path=self.test_db_path)
        bank_posting = [t for t in txns if t["entry_type"] == "Cr"][0]
        reconcile_transaction(
            company_id=self.cid,
            journal_entry_id=bank_posting["journal_id"],
            bank_ledger_id=self.bank_id,
            bank_date="2026-11-05",
            instrument_no="100201",
            db_path=self.test_db_path
        )

        # 4. After clearance: Check BRS summary
        brs_after = get_brs_summary(self.cid, self.bank_id, db_path=self.test_db_path)
        self.assertEqual(brs_after["uncleared_payments"], 0.0)
        self.assertEqual(brs_after["book_balance"], 75000.0)
        self.assertEqual(brs_after["bank_statement_balance"], 75000.0)
        self.assertTrue(brs_after["is_reconciled"])

    def test_cost_centres_and_breakup_report(self):
        """Test Cost Category creation, Cost Centre assignment, and expense allocation"""
        # Create category "Projects" and centre "Project Alpha"
        cat_id = create_cost_category(self.cid, "Projects", db_path=self.test_db_path)
        centre_id = create_cost_centre(self.cid, cat_id, "Project Alpha", db_path=self.test_db_path)

        centres = list_cost_centres(self.cid, db_path=self.test_db_path)
        self.assertEqual(len(centres), 1)
        self.assertEqual(centres[0]["centre_name"], "Project Alpha")

        # Record expense voucher
        conn = get_connection(self.test_db_path)
        cur = conn.cursor()
        cur.execute("SELECT id FROM ledger_groups WHERE company_id = ? AND name = 'Indirect Expenses'", (self.cid,))
        exp_grp = cur.fetchone()[0]

        cur.execute("""
            INSERT INTO ledgers (company_id, name, group_id, opening_balance, opening_balance_type, current_balance)
            VALUES (?, 'Consulting Fees', ?, 0.0, 'Dr', 0.0)
        """, (self.cid, exp_grp))
        exp_led_id = cur.lastrowid
        conn.commit()
        conn.close()

        vid = post_voucher(
            company_id=self.cid,
            voucher_type="Payment",
            voucher_date="2026-11-03",
            party_ledger_id=None,
            journal_postings=[
                {"ledger_id": exp_led_id, "entry_type": "Dr", "amount": 10000.0, "narration": "Technical Consultation"},
                {"ledger_id": self.bank_id, "entry_type": "Cr", "amount": 10000.0, "narration": "Bank Transfer"}
            ],
            db_path=self.test_db_path
        )
        self.assertIsNotNone(vid)

        # Allocate ₹10,000 to Project Alpha
        conn = get_connection(self.test_db_path)
        cur = conn.cursor()
        cur.execute("SELECT id FROM journal_entries WHERE voucher_id = ? AND entry_type = 'Dr'", (vid,))
        dr_jid = cur.fetchone()[0]
        conn.close()

        alloc_id = allocate_cost(self.cid, vid, dr_jid, centre_id, 10000.0, db_path=self.test_db_path)
        self.assertIsNotNone(alloc_id)

        # Check Cost Centre Breakup Report
        report = get_cost_centre_breakup_report(self.cid, db_path=self.test_db_path)
        self.assertEqual(len(report), 1)
        self.assertEqual(report[0]["centre_name"], "Project Alpha")
        self.assertEqual(report[0]["amount"], 10000.0)


if __name__ == "__main__":
    unittest.main()
