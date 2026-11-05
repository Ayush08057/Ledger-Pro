"""
Unit Tests for Phase 4: Multi-Company Management, Ledger Statements, Outstandings, Cash/Bank & Ratio Analysis
"""

import unittest
import tempfile
from pathlib import Path

from app.database import init_db, create_company, get_connection
from app.accounting_engine import create_sales_invoice, create_purchase_invoice, post_voucher
from app.analysis import (
    get_ledger_statement,
    get_outstanding_receivables,
    get_outstanding_payables,
    get_cash_bank_summary,
    get_ratio_analysis
)


class TestPhase4Financials(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = Path(self.temp_dir.name) / "test_tally_p4.db"
        init_db(self.test_db_path)

        # Create demo company
        self.cid = create_company(
            name="Paramount Enterprises",
            legal_name="Paramount Enterprises Ltd",
            gstin="27PPPPP1234P1Z8",
            pan="PPPPP1234P",
            state="Maharashtra",
            state_code="27",
            db_path=self.test_db_path
        )

        conn = get_connection(self.test_db_path)
        cur = conn.cursor()

        # Create Debtor
        cur.execute("SELECT id FROM ledger_groups WHERE company_id = ? AND name = 'Sundry Debtors'", (self.cid,))
        d_grp = cur.fetchone()[0]
        cur.execute("""
            INSERT INTO ledgers (company_id, name, group_id, gstin, state_code)
            VALUES (?, 'Aditya Enterprises', ?, '27AAAAA1111A1Z1', '27')
        """, (self.cid, d_grp))
        self.debtor_id = cur.lastrowid

        # Create Creditor
        cur.execute("SELECT id FROM ledger_groups WHERE company_id = ? AND name = 'Sundry Creditors'", (self.cid,))
        c_grp = cur.fetchone()[0]
        cur.execute("""
            INSERT INTO ledgers (company_id, name, group_id, gstin, state_code)
            VALUES (?, 'Bharat Machinery', ?, '27BBBBB2222B1Z2', '27')
        """, (self.cid, c_grp))
        self.creditor_id = cur.lastrowid

        # Create Unit & Stock Item
        cur.execute("SELECT id FROM units WHERE company_id = ? AND symbol = 'NOS'", (self.cid,))
        unit_id = cur.fetchone()[0]
        cur.execute("""
            INSERT INTO stock_items (company_id, name, unit_id, hsn_sac, gst_rate, opening_qty, opening_rate, closing_qty)
            VALUES (?, 'Industrial Pump', ?, '8413', 18.0, 10, 10000.0, 10)
        """, (self.cid, unit_id))
        self.item_id = cur.lastrowid
        self.unit_id = unit_id

        conn.commit()
        conn.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_ledger_statement_and_running_balance(self):
        """Test ledger statement generation and running balance calculation"""
        # Record a sales invoice to the debtor: 1 pump @ ₹15,000 + 18% GST (₹2,700) = ₹17,700 Dr
        create_sales_invoice(
            company_id=self.cid,
            party_ledger_id=self.debtor_id,
            voucher_date="2026-11-03",
            items=[{
                "stock_item_id": self.item_id,
                "quantity": 1,
                "rate": 15000.0,
                "gst_rate": 18.0,
                "unit_id": self.unit_id
            }],
            db_path=self.test_db_path
        )

        statement = get_ledger_statement(self.cid, self.debtor_id, db_path=self.test_db_path)
        self.assertEqual(len(statement["lines"]), 1)
        self.assertEqual(statement["total_debit"], 17700.0)
        self.assertEqual(statement["closing_balance"], 17700.0)
        self.assertEqual(statement["closing_balance_type"], "Dr")

    def test_outstanding_receivables_and_payables(self):
        """Test bills receivable and bills payable summaries"""
        # Create Sale to debtor: ₹17,700
        create_sales_invoice(
            company_id=self.cid,
            party_ledger_id=self.debtor_id,
            voucher_date="2026-11-03",
            items=[{
                "stock_item_id": self.item_id,
                "quantity": 1,
                "rate": 15000.0,
                "gst_rate": 18.0,
                "unit_id": self.unit_id
            }],
            db_path=self.test_db_path
        )

        # Create Purchase from creditor: 2 pumps @ ₹8,000 + 18% GST (₹2,880) = ₹18,880 Cr
        create_purchase_invoice(
            company_id=self.cid,
            party_ledger_id=self.creditor_id,
            voucher_date="2026-11-03",
            items=[{
                "stock_item_id": self.item_id,
                "quantity": 2,
                "rate": 8000.0,
                "gst_rate": 18.0,
                "unit_id": self.unit_id
            }],
            db_path=self.test_db_path
        )

        receivables = get_outstanding_receivables(self.cid, db_path=self.test_db_path)
        self.assertEqual(len(receivables), 1)
        self.assertEqual(receivables[0]["name"], "Aditya Enterprises")
        self.assertEqual(receivables[0]["current_balance"], 17700.0)

        payables = get_outstanding_payables(self.cid, db_path=self.test_db_path)
        self.assertEqual(len(payables), 1)
        self.assertEqual(payables[0]["name"], "Bharat Machinery")
        self.assertEqual(payables[0]["current_balance"], 18880.0)

    def test_cash_bank_summary(self):
        """Test Cash & Bank book liquidity aggregation"""
        summary = get_cash_bank_summary(self.cid, db_path=self.test_db_path)
        self.assertIn("accounts", summary)
        self.assertIn("total_cash", summary)
        self.assertIn("total_bank", summary)

    def test_ratio_analysis(self):
        """Test financial ratios computation"""
        create_sales_invoice(
            company_id=self.cid,
            party_ledger_id=self.debtor_id,
            voucher_date="2026-11-03",
            items=[{
                "stock_item_id": self.item_id,
                "quantity": 1,
                "rate": 20000.0,
                "gst_rate": 18.0,
                "unit_id": self.unit_id
            }],
            db_path=self.test_db_path
        )

        ratios = get_ratio_analysis(self.cid, db_path=self.test_db_path)
        self.assertGreater(ratios["sales_turnover"], 0)
        self.assertIn("current_ratio", ratios)
        self.assertIn("gross_profit_percent", ratios)


if __name__ == "__main__":
    unittest.main()

