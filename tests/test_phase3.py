"""
Unit Tests for Phase 3: GST Tax Invoices, Statutory Returns (GSTR-1, GSTR-3B) & Tally XML Interoperability
"""

import unittest
import tempfile
from pathlib import Path

from app.database import init_db, create_company, get_connection
from app.accounting_engine import create_sales_invoice, create_purchase_invoice
from app.gst_invoice import number_to_words_inr, format_invoice_data
from app.gst_reports import get_gstr1_report, get_gstr3b_report
from app.tally_xml import export_masters_to_tally_xml, import_masters_from_tally_xml


class TestPhase3GSTAndXML(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = Path(self.temp_dir.name) / "test_tally_p3.db"
        init_db(self.test_db_path)

        # Create demo company in Maharashtra
        self.cid = create_company(
            name="Apex Infotech",
            legal_name="Apex Infotech Solutions Pvt Ltd",
            gstin="27AABCA1234A1Z5",
            pan="AABCA1234A",
            state="Maharashtra",
            state_code="27",
            db_path=self.test_db_path
        )

        conn = get_connection(self.test_db_path)
        cur = conn.cursor()

        # Create a B2B Debtor with valid GSTIN
        cur.execute("SELECT id FROM ledger_groups WHERE company_id = ? AND name = 'Sundry Debtors'", (self.cid,))
        d_grp = cur.fetchone()[0]
        cur.execute("""
            INSERT INTO ledgers (company_id, name, group_id, gstin, state_code)
            VALUES (?, 'Zenith Systems', ?, '27ZZZAA1111B1Z9', '27')
        """, (self.cid, d_grp))
        self.debtor_id = cur.lastrowid

        # Create a Stock Item
        cur.execute("SELECT id FROM units WHERE company_id = ? AND symbol = 'NOS'", (self.cid,))
        unit_id = cur.fetchone()[0]
        cur.execute("""
            INSERT INTO stock_items (company_id, name, unit_id, hsn_sac, gst_rate, opening_qty, opening_rate, closing_qty)
            VALUES (?, 'Server Rack 42U', ?, '8473', 18.0, 5, 40000.0, 5)
        """, (self.cid, unit_id))
        self.item_id = cur.lastrowid
        self.unit_id = unit_id

        conn.commit()
        conn.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_number_to_words_inr(self):
        """Test Indian currency number to words conversion"""
        self.assertEqual(number_to_words_inr(0), "INR Zero Only")
        self.assertEqual(number_to_words_inr(500), "INR Five Hundred Only")
        self.assertEqual(number_to_words_inr(141600.00), "INR One Lakh Forty One Thousand Six Hundred Only")
        self.assertIn("Lakh", number_to_words_inr(250000.00))

    def test_sales_invoice_tax_formatting_and_hsn(self):
        """Test invoice creation, HSN aggregation, and Rule 46 data formatting"""
        vid = create_sales_invoice(
            company_id=self.cid,
            party_ledger_id=self.debtor_id,
            voucher_date="2026-11-03",
            items=[{
                "stock_item_id": self.item_id,
                "quantity": 1,
                "rate": 50000.0,
                "gst_rate": 18.0,
                "unit_id": self.unit_id,
                "hsn_sac": "8473"
            }],
            narration="Test Server Rack Sale",
            db_path=self.test_db_path
        )
        self.assertIsNotNone(vid)

        conn = get_connection(self.test_db_path)
        cur = conn.cursor()
        cur.execute("SELECT * FROM vouchers WHERE id = ?", (vid,))
        v = dict(cur.fetchone())
        cur.execute("SELECT * FROM companies WHERE id = ?", (self.cid,))
        c = dict(cur.fetchone())
        cur.execute("SELECT * FROM ledgers WHERE id = ?", (self.debtor_id,))
        p = dict(cur.fetchone())
        cur.execute("""
            SELECT vii.*, s.name AS item_name, u.symbol AS unit_symbol
            FROM voucher_inventory_items vii
            JOIN stock_items s ON vii.stock_item_id = s.id
            JOIN units u ON vii.unit_id = u.id
            WHERE vii.voucher_id = ?
        """, (vid,))
        items = [dict(r) for r in cur.fetchall()]
        conn.close()

        inv = format_invoice_data(v, c, p, items)
        self.assertEqual(len(inv["hsn_summary"]), 1)
        self.assertEqual(inv["hsn_summary"][0]["hsn_sac"], "8473")
        self.assertEqual(inv["hsn_summary"][0]["taxable_amount"], 50000.0)
        self.assertEqual(inv["hsn_summary"][0]["cgst_amount"], 4500.0)
        self.assertEqual(inv["hsn_summary"][0]["sgst_amount"], 4500.0)
        self.assertIn("Fifty Nine Thousand", inv["amount_in_words"])

    def test_gstr1_and_gstr3b_statutory_reports(self):
        """Verify that sales are correctly classified under Table 4 (B2B) and GSTR-3B Table 3.1"""
        create_sales_invoice(
            company_id=self.cid,
            party_ledger_id=self.debtor_id,
            voucher_date="2026-11-03",
            items=[{
                "stock_item_id": self.item_id,
                "quantity": 2,
                "rate": 50000.0,
                "gst_rate": 18.0,
                "unit_id": self.unit_id,
                "hsn_sac": "8473"
            }],
            db_path=self.test_db_path
        )

        gstr1 = get_gstr1_report(self.cid, db_path=self.test_db_path)
        self.assertEqual(len(gstr1["b2b_invoices"]), 1)
        self.assertEqual(gstr1["total_b2b_taxable"], 100000.0)
        self.assertEqual(gstr1["total_b2b_tax"], 18000.0)

        gstr3b = get_gstr3b_report(self.cid, db_path=self.test_db_path)
        self.assertEqual(gstr3b["outward"]["taxable_value"], 100000.0)
        self.assertEqual(gstr3b["outward"]["total_tax"], 18000.0)

    def test_tally_xml_export_and_import(self):
        """Verify export to Tally XML and import back into SQLite"""
        xml_str = export_masters_to_tally_xml(self.cid, db_path=self.test_db_path)
        self.assertIn("<ENVELOPE>", xml_str)
        self.assertIn("<TALLYREQUEST>Export Data</TALLYREQUEST>", xml_str)
        self.assertIn("Zenith Systems", xml_str)
        self.assertIn("Server Rack 42U", xml_str)

        # Create a new second company and import the XML into it
        cid2 = create_company(name="Second Company", db_path=self.test_db_path)
        result = import_masters_from_tally_xml(cid2, xml_str, db_path=self.test_db_path)
        self.assertGreater(result["imported_ledgers"], 0)
        self.assertGreater(result["imported_items"], 0)


if __name__ == "__main__":
    unittest.main()

