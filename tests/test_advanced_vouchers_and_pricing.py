"""
Unit tests for Credit Note, Debit Note, Physical Stock Reconciliation,
and Multiple Price Levels in TallySoft.
"""

import unittest
import os
import sqlite3
from app.config import DATABASE_PATH
from app.database import init_db, create_company, transaction
from app.accounting_engine import (
    create_sales_invoice,
    create_purchase_invoice,
    create_credit_note,
    create_debit_note,
    get_trial_balance
)
from app.physical_stock_engine import record_physical_stock, init_physical_stock_schema
from app.price_list_engine import (
    init_price_list_schema,
    set_price_list_entry,
    get_item_price_for_level,
    get_price_list_table
)
from app.server import app


class TestAdvancedVouchersAndPricing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        init_physical_stock_schema()
        init_price_list_schema()
        with transaction() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM companies LIMIT 1")
            row = cur.fetchone()
            if not row:
                cls.company_id = create_company(
                    name="Advanced Test Company Pvt Ltd",
                    gstin="27AABCT1234F1Z5",
                    state="Maharashtra",
                    state_code="27"
                )
            else:
                cls.company_id = row[0]

            # Ensure a test stock item exists
            cur.execute("""
                INSERT OR IGNORE INTO stock_items (company_id, name, unit_id, opening_qty, opening_rate, opening_value, closing_qty, closing_value, gst_rate)
                VALUES (?, 'Standard Monitor 24in', 1, 10, 8000.0, 80000.0, 10, 80000.0, 18.0)
            """, (cls.company_id,))
            cur.execute("SELECT id FROM stock_items WHERE company_id = ? AND name = 'Standard Monitor 24in'", (cls.company_id,))
            cls.stock_item_id = cur.fetchone()[0]

            # Ensure a test party ledger exists
            cur.execute("SELECT id FROM ledger_groups WHERE company_id = ? AND name = 'Sundry Debtors'", (cls.company_id,))
            grp_debtors = cur.fetchone()[0]
            cur.execute("""
                INSERT OR IGNORE INTO ledgers (company_id, name, group_id, state_code)
                VALUES (?, 'Apex Electronics Mumbai', ?, '27')
            """, (cls.company_id, grp_debtors))
            cur.execute("SELECT id FROM ledgers WHERE company_id = ? AND name = 'Apex Electronics Mumbai'", (cls.company_id,))
            cls.party_id = cur.fetchone()[0]

        cls.client = app.test_client()

    def test_01_credit_note_workflow(self):
        """Test GST Credit Note (Sales Return) posting, stock inward update, Dr/Cr equality."""
        items = [{
            "stock_item_id": self.stock_item_id,
            "quantity": 2.0,
            "rate": 10000.0,
            "gst_rate": 18.0
        }]
        # Initial stock count
        with transaction() as conn:
            cur = conn.cursor()
            cur.execute("SELECT closing_qty FROM stock_items WHERE id = ?", (self.stock_item_id,))
            init_qty = cur.fetchone()[0]

        vid = create_credit_note(
            company_id=self.company_id,
            party_ledger_id=self.party_id,
            voucher_date="2026-11-03",
            items=items,
            narration="Sales return from Apex Electronics",
            original_invoice_no="SALES-0001",
            original_invoice_date="2026-11-01"
        )
        self.assertGreater(vid, 0)

        # Verify stock inward movement: closing_qty increased by 2
        with transaction() as conn:
            cur = conn.cursor()
            cur.execute("SELECT closing_qty FROM stock_items WHERE id = ?", (self.stock_item_id,))
            post_qty = cur.fetchone()[0]
            self.assertAlmostEqual(post_qty, init_qty + 2.0)

            cur.execute("SELECT voucher_number, total_amount, reference_number FROM vouchers WHERE id = ?", (vid,))
            vrow = cur.fetchone()
            self.assertTrue(vrow["voucher_number"].startswith("CRN-"))
            self.assertEqual(vrow["reference_number"], "SALES-0001")
            self.assertAlmostEqual(vrow["total_amount"], 23600.0) # 20000 + 18% = 23600

        # Verify Trial Balance maintains strict double-entry balance
        tb = get_trial_balance(self.company_id)
        self.assertTrue(tb["is_balanced"], f"Trial balance mismatch: Dr {tb['total_debit']} != Cr {tb['total_credit']}")

    def test_02_debit_note_workflow(self):
        """Test GST Debit Note (Purchase Return) posting, stock outward update, Dr/Cr equality."""
        items = [{
            "stock_item_id": self.stock_item_id,
            "quantity": 1.0,
            "rate": 8000.0,
            "gst_rate": 18.0
        }]
        with transaction() as conn:
            cur = conn.cursor()
            cur.execute("SELECT closing_qty FROM stock_items WHERE id = ?", (self.stock_item_id,))
            init_qty = cur.fetchone()[0]

        vid = create_debit_note(
            company_id=self.company_id,
            party_ledger_id=self.party_id,
            voucher_date="2026-11-03",
            items=items,
            narration="Purchase return to supplier",
            original_invoice_no="PUR-0001",
            original_invoice_date="2026-11-01"
        )
        self.assertGreater(vid, 0)

        with transaction() as conn:
            cur = conn.cursor()
            cur.execute("SELECT closing_qty FROM stock_items WHERE id = ?", (self.stock_item_id,))
            post_qty = cur.fetchone()[0]
            self.assertAlmostEqual(post_qty, init_qty - 1.0)

            cur.execute("SELECT voucher_number, total_amount FROM vouchers WHERE id = ?", (vid,))
            vrow = cur.fetchone()
            self.assertTrue(vrow["voucher_number"].startswith("DBN-"))
            self.assertAlmostEqual(vrow["total_amount"], 9440.0) # 8000 + 18% = 9440

        tb = get_trial_balance(self.company_id)
        self.assertTrue(tb["is_balanced"])

    def test_03_physical_stock_reconciliation(self):
        """Test Physical stock count verification, closing quantity sync, and audit logging."""
        counted_qty = 25.0
        vid = record_physical_stock(
            company_id=self.company_id,
            voucher_date="2026-11-03",
            items=[{
                "stock_item_id": self.stock_item_id,
                "physical_qty": counted_qty,
                "rate": 8000.0
            }],
            narration="Annual inventory audit physical verification"
        )
        self.assertGreater(vid, 0)

        with transaction() as conn:
            cur = conn.cursor()
            cur.execute("SELECT closing_qty FROM stock_items WHERE id = ?", (self.stock_item_id,))
            curr_qty = cur.fetchone()[0]
            self.assertEqual(curr_qty, counted_qty)

            cur.execute("SELECT details FROM audit_logs WHERE entity_type = 'StockItem' AND entity_id = ?", (vid,))
            log = cur.fetchone()
            self.assertIsNotNone(log)
            self.assertIn("verified on 2026-11-03", log[0])

    def test_04_multiple_price_levels(self):
        """Test Wholesale vs Retail price level setup and slab lookup."""
        set_price_list_entry(
            company_id=self.company_id,
            price_level="Wholesale",
            stock_item_id=self.stock_item_id,
            rate=7500.0,
            min_qty=10.0,
            discount_percent=5.0
        )
        set_price_list_entry(
            company_id=self.company_id,
            price_level="Retail",
            stock_item_id=self.stock_item_id,
            rate=9500.0,
            min_qty=1.0,
            discount_percent=0.0
        )

        # Lookup Wholesale slab for qty 15
        wh_price = get_item_price_for_level(self.company_id, "Wholesale", self.stock_item_id, quantity=15.0)
        self.assertIsNotNone(wh_price)
        self.assertEqual(wh_price["rate"], 7500.0)
        self.assertEqual(wh_price["discount_percent"], 5.0)

        # Lookup Retail slab
        rt_price = get_item_price_for_level(self.company_id, "Retail", self.stock_item_id, quantity=2.0)
        self.assertIsNotNone(rt_price)
        self.assertEqual(rt_price["rate"], 9500.0)

    def test_05_http_routes_for_new_features(self):
        """Test HTTP GET endpoints for Credit Note, Debit Note, Physical Stock, Price Lists."""
        resp1 = self.client.get("/vouchers/create?type=Credit%20Note")
        self.assertEqual(resp1.status_code, 200)
        self.assertIn(b"Credit Note", resp1.data)
        self.assertIn(b"Original Invoice No:", resp1.data)

        resp2 = self.client.get("/vouchers/create?type=Debit%20Note")
        self.assertEqual(resp2.status_code, 200)
        self.assertIn(b"Debit Note", resp2.data)

        resp3 = self.client.get("/inventory/physical-stock")
        self.assertEqual(resp3.status_code, 200)
        self.assertIn(b"Physical Stock Verification", resp3.data)

        resp4 = self.client.get("/masters/price-lists?level=Wholesale")
        self.assertEqual(resp4.status_code, 200)
        self.assertIn(b"Price Lists", resp4.data)


    def test_06_master_deletion_and_protection(self):
        """Test master deletion: allowed when unused, blocked when transactions/built-in exist."""
        from app.database import delete_ledger, delete_stock_item, delete_group

        # 1. Block deleting standard Cash ledger
        with transaction() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM ledgers WHERE company_id = ? AND name = 'Cash'", (self.company_id,))
            cash_id = cur.fetchone()[0]
        res = delete_ledger(self.company_id, cash_id)
        self.assertFalse(res["success"])
        self.assertIn("Cannot delete standard system ledger", res["error"])

        # 2. Allow deleting an unused temporary ledger
        with transaction() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM ledger_groups WHERE company_id = ? AND name = 'Indirect Expenses'", (self.company_id,))
            grp_exp = cur.fetchone()[0]
            cur.execute("INSERT INTO ledgers (company_id, name, group_id) VALUES (?, 'Temporary Scrap Exp', ?)", (self.company_id, grp_exp))
            temp_id = cur.lastrowid

        res2 = delete_ledger(self.company_id, temp_id)
        self.assertTrue(res2["success"])

        # Verify deletion via HTTP endpoint
        with transaction() as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO ledgers (company_id, name, group_id) VALUES (?, 'HTTP Test Ledger', ?)", (self.company_id, grp_exp))
            http_lid = cur.lastrowid

        resp = self.client.post(f"/api/masters/ledgers/{http_lid}/delete")
        self.assertEqual(resp.status_code, 200)

    def test_07_voucher_cancellation_and_deletion(self):
        """Test cancelling and deleting vouchers via API."""
        from app.accounting_engine import create_sales_invoice

        vid = create_sales_invoice(
            company_id=self.company_id,
            party_ledger_id=self.party_id,
            voucher_date="2026-11-03",
            items=[{"stock_item_id": self.stock_item_id, "quantity": 1.0, "rate": 5000.0, "gst_rate": 18.0}],
            narration="To be cancelled"
        )
        # Cancel voucher
        resp_c = self.client.post(f"/api/vouchers/{vid}/cancel")
        self.assertEqual(resp_c.status_code, 200)

        with transaction() as conn:
            cur = conn.cursor()
            cur.execute("SELECT total_amount, narration FROM vouchers WHERE id = ?", (vid,))
            row = cur.fetchone()
            self.assertEqual(row["total_amount"], 0.0)
            self.assertTrue(row["narration"].startswith("[CANCELLED]"))

        # Delete voucher
        resp_d = self.client.post(f"/api/vouchers/{vid}/delete")
        self.assertEqual(resp_d.status_code, 200)

        with transaction() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM vouchers WHERE id = ?", (vid,))
            self.assertEqual(cur.fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
