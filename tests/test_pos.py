"""
Unit tests for Point of Sale (POS) Invoicing Engine
"""

import unittest
import tempfile
from pathlib import Path
from app.database import init_db, create_company, get_connection
from app.pos_engine import (
    init_pos_schema,
    record_pos_invoice,
    get_pos_invoice,
    list_pos_invoices
)


class TestPOS(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db = Path(self.temp_dir.name) / "test_pos.db"
        init_db(self.test_db)
        init_pos_schema(self.test_db)

        self.company_id = create_company(
            name="Retail Mart Supermarket",
            state="Maharashtra",
            state_code="27",
            db_path=self.test_db
        )

        conn = get_connection(self.test_db)
        cur = conn.cursor()

        # Find ledgers
        cur.execute("SELECT id FROM ledgers WHERE company_id = ? AND name = 'Cash'", (self.company_id,))
        self.cash_id = cur.fetchone()[0]

        cur.execute("SELECT id FROM ledgers WHERE company_id = ? AND name = 'Sales Account'", (self.company_id,))
        self.sales_id = cur.fetchone()[0]

        cur.execute("SELECT id FROM ledger_groups WHERE company_id = ? AND name = 'Sundry Debtors'", (self.company_id,))
        grp_deb = cur.fetchone()[0]

        cur.execute("SELECT id FROM ledger_groups WHERE company_id = ? AND name = 'Bank Accounts'", (self.company_id,))
        grp_bank = cur.fetchone()[0]

        # Create Walk-in customer & Bank ledger
        cur.execute("INSERT INTO ledgers (company_id, group_id, name, state_code) VALUES (?, ?, 'Counter Customer', '27')", (self.company_id, grp_deb))
        self.customer_id = cur.lastrowid

        cur.execute("INSERT INTO ledgers (company_id, group_id, name) VALUES (?, ?, 'HDFC POS Bank A/c')", (self.company_id, grp_bank))
        self.bank_id = cur.lastrowid

        # Create stock items
        cur.execute("SELECT id FROM units WHERE company_id = ? AND symbol = 'NOS'", (self.company_id,))
        uom_id = cur.fetchone()[0]

        cur.execute("""
            INSERT INTO stock_items (company_id, name, unit_id, opening_qty, opening_rate, opening_value, closing_qty, closing_value, gst_rate)
            VALUES (?, 'Wireless Mouse', ?, 50, 400.0, 20000.0, 50, 20000.0, 18.0)
        """, (self.company_id, uom_id))
        self.item_mouse = cur.lastrowid

        cur.execute("""
            INSERT INTO stock_items (company_id, name, unit_id, opening_qty, opening_rate, opening_value, closing_qty, closing_value, gst_rate)
            VALUES (?, 'USB Keyboard', ?, 30, 600.0, 18000.0, 30, 18000.0, 18.0)
        """, (self.company_id, uom_id))
        self.item_kb = cur.lastrowid

        conn.commit()
        conn.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_01_pos_cash_tender_and_change(self):
        # 1 Mouse @ ₹500 + 18% GST = ₹590 total
        # Customer pays ₹1,000 cash -> Change returned = ₹410
        res = record_pos_invoice(
            company_id=self.company_id,
            pos_date="2026-11-03",
            party_ledger_id=self.customer_id,
            cash_ledger_id=self.cash_id,
            sales_ledger_id=self.sales_id,
            items=[
                {"stock_item_id": self.item_mouse, "quantity": 1, "rate": 500.0, "gst_rate": 18.0}
            ],
            cash_tendered=1000.0,
            db_path=self.test_db
        )

        self.assertEqual(res['subtotal'], 500.0)
        self.assertEqual(res['tax_amount'], 90.0)
        self.assertEqual(res['total_amount'], 590.0)
        self.assertEqual(res['cash_tendered'], 1000.0)
        self.assertEqual(res['change_returned'], 410.0)

        # Check stock decrement
        conn = get_connection(self.test_db)
        mouse = conn.execute("SELECT closing_qty FROM stock_items WHERE id = ?", (self.item_mouse,)).fetchone()
        self.assertEqual(mouse['closing_qty'], 49.0)
        conn.close()

        # Check invoice details fetch
        inv = get_pos_invoice(res['pos_id'], self.test_db)
        self.assertIsNotNone(inv)
        self.assertEqual(inv['pos_number'], "POS-00001")
        self.assertEqual(len(inv['items']), 1)
        self.assertEqual(inv['items'][0]['item_name'], "Wireless Mouse")

    def test_02_pos_split_payment_multi_mode(self):
        # 2 Keyboards @ ₹1,000 = ₹2,000 + 18% GST (360) = ₹2,360
        # Split tender: ₹1,000 Card, ₹1,000 UPI, ₹360 Cash
        res = record_pos_invoice(
            company_id=self.company_id,
            pos_date="2026-11-03",
            party_ledger_id=self.customer_id,
            cash_ledger_id=self.cash_id,
            sales_ledger_id=self.sales_id,
            bank_ledger_id=self.bank_id,
            items=[
                {"stock_item_id": self.item_kb, "quantity": 2, "rate": 1000.0, "gst_rate": 18.0}
            ],
            card_amount=1000.0,
            upi_amount=1000.0,
            cash_tendered=360.0,
            db_path=self.test_db
        )

        self.assertEqual(res['total_amount'], 2360.0)
        self.assertEqual(res['change_returned'], 0.0)

        invoices = list_pos_invoices(self.company_id, self.test_db)
        self.assertEqual(len(invoices), 1)


if __name__ == "__main__":
    unittest.main()

