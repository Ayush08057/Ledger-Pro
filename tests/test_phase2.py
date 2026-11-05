"""
Unit Tests for Phase 2: Core Accounting Engine, GST Calculations & Double-Entry Invariants
"""

import unittest
import tempfile
from pathlib import Path

from app.database import init_db, create_company, get_connection
from app.gst_engine import calculate_item_gst, is_interstate_transaction, extract_state_code_from_gstin
from app.accounting_engine import (
    post_voucher,
    create_sales_invoice,
    create_purchase_invoice,
    get_trial_balance,
    DoubleEntryMismatchError
)


class TestPhase2AccountingEngine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = Path(self.temp_dir.name) / "test_tally_p2.db"
        init_db(self.test_db_path)

        # Create demo company in Maharashtra (State 27)
        self.company_id = create_company(
            name="Apex Technologies",
            gstin="27AABCA1234A1Z5",
            state="Maharashtra",
            state_code="27",
            db_path=self.test_db_path
        )

        # Create a Sundry Debtor (Customer in Maharashtra - Intrastate)
        conn = get_connection(self.test_db_path)
        cur = conn.cursor()
        cur.execute("SELECT id FROM ledger_groups WHERE company_id = ? AND name = 'Sundry Debtors'", (self.company_id,))
        debtor_grp_id = cur.fetchone()[0]

        cur.execute("""
            INSERT INTO ledgers (company_id, name, group_id, state_code, gstin)
            VALUES (?, 'Global Retailers', ?, '27', '27AABCG9876H1Z1')
        """, (self.company_id, debtor_grp_id))
        self.debtor_id = cur.lastrowid

        # Create a Sundry Creditor (Supplier in Gujarat - Interstate)
        cur.execute("SELECT id FROM ledger_groups WHERE company_id = ? AND name = 'Sundry Creditors'", (self.company_id,))
        creditor_grp_id = cur.fetchone()[0]

        cur.execute("""
            INSERT INTO ledgers (company_id, name, group_id, state_code, gstin)
            VALUES (?, 'Gujarat Chipset Ltd', ?, '24', '24BBBCG9876H1Z2')
        """, (self.company_id, creditor_grp_id))
        self.creditor_id = cur.lastrowid

        # Create Stock Item (Laptop, 18% GST)
        cur.execute("SELECT id FROM units WHERE company_id = ? AND symbol = 'NOS'", (self.company_id,))
        unit_id = cur.fetchone()[0]
        self.unit_id = unit_id

        cur.execute("""
            INSERT INTO stock_items (company_id, name, unit_id, hsn_sac, gst_rate, opening_qty, opening_rate, closing_qty)
            VALUES (?, 'Dell Latitude Laptop', ?, '8471', 18.0, 10, 50000.0, 10)
        """, (self.company_id, unit_id))
        self.stock_item_id = cur.lastrowid

        conn.commit()
        conn.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_gst_engine_calculation(self):
        """Test Intrastate vs Interstate GST calculations"""
        # Intrastate 18% on ₹1000 => CGST ₹90 (9%), SGST ₹90 (9%)
        res_intra = calculate_item_gst(1000.0, 18.0, is_interstate=False)
        self.assertEqual(res_intra["cgst_amount"], 90.0)
        self.assertEqual(res_intra["sgst_amount"], 90.0)
        self.assertEqual(res_intra["igst_amount"], 0.0)
        self.assertEqual(res_intra["total_amount"], 1180.0)

        # Interstate 18% on ₹1000 => IGST ₹180 (18%)
        res_inter = calculate_item_gst(1000.0, 18.0, is_interstate=True)
        self.assertEqual(res_inter["cgst_amount"], 0.0)
        self.assertEqual(res_inter["sgst_amount"], 0.0)
        self.assertEqual(res_inter["igst_amount"], 180.0)
        self.assertEqual(res_inter["total_amount"], 1180.0)

    def test_double_entry_mismatch_rejection(self):
        """Test that unbalanced debit/credit postings are rejected"""
        with self.assertRaises(DoubleEntryMismatchError):
            post_voucher(
                company_id=self.company_id,
                voucher_type="Journal",
                voucher_date="2026-11-03",
                party_ledger_id=None,
                journal_postings=[
                    {"ledger_id": self.debtor_id, "entry_type": "Dr", "amount": 1000.0},
                    {"ledger_id": self.creditor_id, "entry_type": "Cr", "amount": 900.0} # Unbalanced!
                ],
                db_path=self.test_db_path
            )

    def test_sales_invoice_creation_and_stock_reduction(self):
        """Test creating an intrastate Sales Invoice: checks stock deduction and trial balance"""
        items = [
            {
                "stock_item_id": self.stock_item_id,
                "description": "Dell Laptop Sale",
                "hsn_sac": "8471",
                "quantity": 2,
                "unit_id": self.unit_id,
                "rate": 60000.0,
                "discount_percent": 0.0,
                "gst_rate": 18.0
            }
        ]
        # 2 laptops * 60,000 = 120,000 taxable. 18% GST (CGST 9% = 10,800, SGST 9% = 10,800). Total = 141,600
        vid = create_sales_invoice(
            company_id=self.company_id,
            party_ledger_id=self.debtor_id,
            voucher_date="2026-11-03",
            items=items,
            narration="Sale of 2 Laptops to Global Retailers",
            db_path=self.test_db_path
        )
        self.assertIsNotNone(vid)

        # Verify stock decreased by 2 (10 - 2 = 8)
        conn = get_connection(self.test_db_path)
        cur = conn.cursor()
        cur.execute("SELECT closing_qty FROM stock_items WHERE id = ?", (self.stock_item_id,))
        qty = cur.fetchone()[0]
        self.assertEqual(qty, 8.0)

        # Verify debtor balance is ₹141,600 Dr
        cur.execute("SELECT current_balance, current_balance_type FROM ledgers WHERE id = ?", (self.debtor_id,))
        bal_row = cur.fetchone()
        self.assertEqual(bal_row["current_balance"], 141600.0)
        self.assertEqual(bal_row["current_balance_type"], "Dr")
        conn.close()

        # Verify Trial Balance is perfectly balanced
        tb = get_trial_balance(self.company_id, db_path=self.test_db_path)
        self.assertTrue(tb["is_balanced"])
        self.assertEqual(tb["total_debit"], tb["total_credit"])

    def test_purchase_invoice_interstate_and_stock_addition(self):
        """Test creating an interstate Purchase Invoice with IGST and stock increase"""
        items = [
            {
                "stock_item_id": self.stock_item_id,
                "description": "Dell Laptop Purchase",
                "hsn_sac": "8471",
                "quantity": 5,
                "unit_id": self.unit_id,
                "rate": 45000.0,
                "discount_percent": 0.0,
                "gst_rate": 18.0
            }
        ]
        # 5 laptops * 45,000 = 225,000 taxable. 18% IGST = 40,500. Total = 265,500
        vid = create_purchase_invoice(
            company_id=self.company_id,
            party_ledger_id=self.creditor_id,
            voucher_date="2026-11-03",
            items=items,
            narration="Purchase of 5 Laptops from Gujarat Supplier",
            db_path=self.test_db_path
        )
        self.assertIsNotNone(vid)

        # Stock should now be 10 + 5 = 15
        conn = get_connection(self.test_db_path)
        cur = conn.cursor()
        cur.execute("SELECT closing_qty FROM stock_items WHERE id = ?", (self.stock_item_id,))
        qty = cur.fetchone()[0]
        self.assertEqual(qty, 15.0)

        # Verify Trial Balance remains strictly balanced
        tb = get_trial_balance(self.company_id, db_path=self.test_db_path)
        self.assertTrue(tb["is_balanced"])
        self.assertEqual(tb["total_debit"], tb["total_credit"])


if __name__ == "__main__":
    unittest.main()

