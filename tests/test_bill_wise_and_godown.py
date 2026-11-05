"""
Unit Tests for Bill-Wise Reference Tracking, Ageing Slabs & Multi-Godown Stock Transfers
"""

import unittest
import tempfile
from pathlib import Path

from app.database import init_db, create_company, get_connection
from app.accounting_engine import create_sales_invoice
from app.bill_wise import (
    record_bill_reference,
    get_pending_bills,
    settle_bill_against_ref,
    get_bill_ageing_analysis
)
from app.godown_engine import (
    create_godown,
    list_godowns,
    transfer_stock,
    get_godown_summary
)


class TestBillWiseAndGodown(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = Path(self.temp_dir.name) / "test_bw_godown.db"
        init_db(self.test_db_path)

        # Create demo company
        self.cid = create_company(
            name="Matrix Logistics",
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
            VALUES (?, 'Starlight Retail', ?, '27SSSS1111S1Z4', '27')
        """, (self.cid, d_grp))
        self.debtor_id = cur.lastrowid

        # Create Stock Item
        cur.execute("SELECT id FROM units WHERE company_id = ? AND symbol = 'NOS'", (self.cid,))
        unit_id = cur.fetchone()[0]
        cur.execute("""
            INSERT INTO stock_items (company_id, name, unit_id, hsn_sac, gst_rate, opening_qty, opening_rate, closing_qty)
            VALUES (?, 'Solar Inverter 5kVA', ?, '8504', 18.0, 20, 25000.0, 20)
        """, (self.cid, unit_id))
        self.item_id = cur.lastrowid
        self.unit_id = unit_id

        conn.commit()
        conn.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_bill_wise_creation_and_settlement(self):
        """Test New Ref creation on Sales Invoice and Agst Ref settlement"""
        # Create Sales invoice: 1 inverter @ ₹30,000 + 18% GST (₹5,400) = ₹35,400
        vid = create_sales_invoice(
            company_id=self.cid,
            party_ledger_id=self.debtor_id,
            voucher_date="2026-11-03",
            items=[{
                "stock_item_id": self.item_id,
                "quantity": 1,
                "rate": 30000.0,
                "gst_rate": 18.0,
                "unit_id": self.unit_id
            }],
            db_path=self.test_db_path
        )
        self.assertIsNotNone(vid)

        # Check pending bills
        pending = get_pending_bills(self.cid, self.debtor_id, db_path=self.test_db_path)
        self.assertEqual(len(pending), 1)
        bill_no = pending[0]["bill_number"]
        self.assertEqual(pending[0]["pending_amount"], 35400.0)

        # Settle partial amount ₹20,000 against this bill (Agst Ref)
        settled = settle_bill_against_ref(
            company_id=self.cid,
            party_ledger_id=self.debtor_id,
            bill_number=bill_no,
            settle_amount=20000.0,
            db_path=self.test_db_path
        )
        self.assertTrue(settled)

        # Check remaining pending bill balance: 35,400 - 20,000 = 15,400
        pending_after = get_pending_bills(self.cid, self.debtor_id, db_path=self.test_db_path)
        self.assertEqual(len(pending_after), 1)
        self.assertEqual(pending_after[0]["pending_amount"], 15400.0)

    def test_bill_ageing_slabs(self):
        """Test bill ageing calculation across aging slabs"""
        # Record a 45-day-old bill
        record_bill_reference(
            company_id=self.cid,
            party_ledger_id=self.debtor_id,
            bill_ref_type="New Ref",
            bill_number="OLD-BILL-01",
            bill_date="2026-09-15",
            amount=50000.0,
            db_path=self.test_db_path
        )

        ageing = get_bill_ageing_analysis(self.cid, as_on_date="2026-11-03", db_path=self.test_db_path)
        self.assertGreater(len(ageing), 0)
        old_bill = [b for b in ageing if b["bill_number"] == "OLD-BILL-01"][0]
        self.assertGreater(old_bill["days_old"], 30)
        self.assertEqual(old_bill["slab_31_60"], 50000.0)

    def test_multi_godown_stock_transfer(self):
        """Test creating warehouses and transferring stock between locations (Alt+F7)"""
        g_central = create_godown(self.cid, "Central Depot", "Bhiwandi", db_path=self.test_db_path)
        g_retail = create_godown(self.cid, "Retail Outlet", "Mumbai Fort", db_path=self.test_db_path)

        godowns = list_godowns(self.cid, db_path=self.test_db_path)
        self.assertGreaterEqual(len(godowns), 2)

        # Transfer 5 inverters from Central Depot to Retail Outlet
        trf_id = transfer_stock(
            company_id=self.cid,
            source_godown_id=g_central,
            dest_godown_id=g_retail,
            stock_item_id=self.item_id,
            quantity=5.0,
            rate=25000.0,
            transfer_date="2026-11-03",
            narration="Inter-godown replenishment",
            db_path=self.test_db_path
        )
        self.assertIsNotNone(trf_id)

        # Verify godown summary
        summary = get_godown_summary(self.cid, db_path=self.test_db_path)
        retail_rows = [r for r in summary if r["godown_id"] == g_retail and r["stock_item_id"] == self.item_id]
        self.assertEqual(len(retail_rows), 1)
        self.assertEqual(retail_rows[0]["quantity"], 5.0)


if __name__ == "__main__":
    unittest.main()

