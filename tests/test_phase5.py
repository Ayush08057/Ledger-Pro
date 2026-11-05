"""
Unit Tests for Phase 5: Database Backups, Restoration, e-Invoice & e-Way Bill JSON
"""

import unittest
import tempfile
import os
from pathlib import Path

from app.database import init_db, create_company, get_connection
from app.accounting_engine import create_sales_invoice
from app.backup import create_backup, list_backups, restore_backup, BACKUP_DIR
from app.eway_einvoice import generate_einvoice_json, generate_ewaybill_json


class TestPhase5BackupsAndEWay(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = Path(self.temp_dir.name) / "test_tally_p5.db"
        init_db(self.test_db_path)

        # Create demo company
        self.cid = create_company(
            name="Horizon Engineering",
            legal_name="Horizon Engineering Ltd",
            gstin="27HHHHH1234H1Z3",
            pan="HHHHH1234H",
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
            VALUES (?, 'Techno Industries', ?, '27TTTTT1111T1Z5', '27')
        """, (self.cid, d_grp))
        self.debtor_id = cur.lastrowid

        # Create Item
        cur.execute("SELECT id FROM units WHERE company_id = ? AND symbol = 'NOS'", (self.cid,))
        unit_id = cur.fetchone()[0]
        cur.execute("""
            INSERT INTO stock_items (company_id, name, unit_id, hsn_sac, gst_rate, opening_qty, opening_rate, closing_qty)
            VALUES (?, 'CNC Drill Bit', ?, '8207', 18.0, 50, 200.0, 50)
        """, (self.cid, unit_id))
        self.item_id = cur.lastrowid
        self.unit_id = unit_id

        conn.commit()
        conn.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_database_backup_and_restore(self):
        """Test atomic snapshot backup and restoration"""
        # Create a voucher first
        vid = create_sales_invoice(
            company_id=self.cid,
            party_ledger_id=self.debtor_id,
            voucher_date="2026-11-03",
            items=[{
                "stock_item_id": self.item_id,
                "quantity": 5,
                "rate": 300.0,
                "gst_rate": 18.0,
                "unit_id": self.unit_id
            }],
            db_path=self.test_db_path
        )
        self.assertIsNotNone(vid)

        # Create backup
        backup_path_str = create_backup(db_path=self.test_db_path, note="unit_test")
        backup_path = Path(backup_path_str)
        self.assertTrue(backup_path.exists())

        # Verify backup listing
        backups = list_backups()
        self.assertGreater(len(backups), 0)

        # Test restore into a fresh empty database
        restore_target = Path(self.temp_dir.name) / "restored.db"
        restore_backup(backup_path.name, target_db_path=restore_target)
        self.assertTrue(restore_target.exists())

        # Verify that restored DB contains the company and voucher
        conn = get_connection(restore_target)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM vouchers WHERE company_id = ?", (self.cid,))
        count = cur.fetchone()[0]
        conn.close()
        self.assertEqual(count, 1)

        # Cleanup created backup file
        if backup_path.exists():
            backup_path.unlink()

    def test_einvoice_and_ewaybill_json_generation(self):
        """Test e-Invoice and e-Way bill JSON generation"""
        vid = create_sales_invoice(
            company_id=self.cid,
            party_ledger_id=self.debtor_id,
            voucher_date="2026-11-03",
            items=[{
                "stock_item_id": self.item_id,
                "quantity": 10,
                "rate": 500.0,
                "gst_rate": 18.0,
                "unit_id": self.unit_id,
                "hsn_sac": "8207"
            }],
            db_path=self.test_db_path
        )

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

        # 1. Test e-Invoice
        einvoice = generate_einvoice_json(c, p, v, items)
        self.assertEqual(einvoice["Version"], "1.1")
        self.assertEqual(einvoice["DocDtls"]["Typ"], "INV")
        self.assertEqual(einvoice["ValDtls"]["AssVal"], 5000.0)
        self.assertEqual(einvoice["ValDtls"]["TotInvVal"], 5900.0)

        # 2. Test e-Way Bill
        eway = generate_ewaybill_json(c, p, v, items)
        self.assertEqual(eway["supplyType"], "O")
        self.assertEqual(eway["totalValue"], 5000.0)
        self.assertEqual(eway["totInvValue"], 5900.0)
        self.assertEqual(len(eway["itemList"]), 1)


if __name__ == "__main__":
    unittest.main()

