import unittest
import os
import tempfile
import sqlite3
import gc
from app.server import app
from app.database import init_db, create_company

class TestSingleEntryAndMasters(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp()
        os.close(self.db_fd)
        init_db(self.db_path)
        create_company("Test Single Entry Co", db_path=self.db_path)

        app.config["TESTING"] = True
        self.client = app.test_client()

        # Patch DATABASE_PATH in app.database and app.server
        import app.server as s
        import app.database as d
        self.orig_server_db = s.DATABASE_PATH
        self.orig_db_path = d.DATABASE_PATH
        s.DATABASE_PATH = self.db_path
        d.DATABASE_PATH = self.db_path

    def tearDown(self):
        import app.server as s
        import app.database as d
        s.DATABASE_PATH = self.orig_server_db
        d.DATABASE_PATH = self.orig_db_path
        gc.collect()
        try:
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
        except OSError:
            pass

    def test_single_entry_voucher_modes(self):
        """Test GET /vouchers/create with mode=single and mode=double"""
        resp_single = self.client.get("/vouchers/create?type=Payment&mode=single")
        self.assertEqual(resp_single.status_code, 200)
        self.assertIn(b"Single Entry", resp_single.data)
        self.assertIn(b"Account:", resp_single.data)
        self.assertIn(b"Particulars", resp_single.data)

        resp_double = self.client.get("/vouchers/create?type=Payment&mode=double")
        self.assertEqual(resp_double.status_code, 200)
        self.assertIn(b"Double Entry", resp_double.data)
        self.assertIn(b"Dr / Cr", resp_double.data)

    def test_group_creation_and_alteration(self):
        """Test creating and altering a ledger group"""
        resp = self.client.get("/masters/groups/create")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Group Creation", resp.data)

        post_resp = self.client.post("/masters/groups/create", data={
            "name": "Factory Overheads",
            "parent_group_id": "",
            "nature": "Expense",
            "affects_gross_profit": "1"
        }, follow_redirects=True)
        self.assertEqual(post_resp.status_code, 200)

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT id, name, nature FROM ledger_groups WHERE name = 'Factory Overheads'")
        row = cur.fetchone()
        self.assertIsNotNone(row)
        gid = row[0]
        conn.close()

        alter_resp = self.client.get(f"/masters/groups/alter/{gid}")
        self.assertEqual(alter_resp.status_code, 200)
        self.assertIn(b"Group Alteration", alter_resp.data)

        alter_post = self.client.post(f"/masters/groups/alter/{gid}", data={
            "name": "Direct Factory Overheads",
            "parent_group_id": "",
            "nature": "Expense",
            "affects_gross_profit": "1"
        }, follow_redirects=True)
        self.assertEqual(alter_post.status_code, 200)

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM ledger_groups WHERE id = ?", (gid,))
        self.assertEqual(cur.fetchone()[0], "Direct Factory Overheads")
        conn.close()

    def test_unit_creation(self):
        """Test creating a UOM unit"""
        resp = self.client.get("/masters/units/create")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Unit Creation", resp.data)

        post_resp = self.client.post("/masters/units/create", data={
            "symbol": "LTR",
            "formal_name": "Litres",
            "decimal_places": "2"
        }, follow_redirects=True)
        self.assertEqual(post_resp.status_code, 200)

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT symbol, formal_name, decimal_places FROM units WHERE symbol = 'LTR'")
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[1], "Litres")
        self.assertEqual(row[2], 2)
        conn.close()

    def test_stock_group_creation(self):
        """Test creating a stock group"""
        resp = self.client.get("/masters/stock-groups/create")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Stock Group Creation", resp.data)

        post_resp = self.client.post("/masters/stock-groups/create", data={
            "name": "Electronics & Peripherals",
            "parent_id": "",
            "add_quantities": "1"
        }, follow_redirects=True)
        self.assertEqual(post_resp.status_code, 200)

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM stock_groups WHERE name = 'Electronics & Peripherals'")
        self.assertIsNotNone(cur.fetchone())
        conn.close()

    def test_voucher_type_creation(self):
        """Test creating a custom voucher type"""
        resp = self.client.get("/masters/voucher-types/create")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Voucher Type Creation", resp.data)

        post_resp = self.client.post("/masters/voucher-types/create", data={
            "name": "Export Tax Invoice",
            "type_of_voucher": "Sales",
            "abbreviation": "EXPINV",
            "numbering_method": "Automatic"
        }, follow_redirects=True)
        self.assertEqual(post_resp.status_code, 200)

    def test_ledger_alteration(self):
        """Test altering an existing ledger"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO ledgers (company_id, name, group_id, opening_balance, opening_balance_type, current_balance, current_balance_type)
            VALUES (1, 'Initial Supplier', 1, 1000.0, 'Cr', 1000.0, 'Cr')
        """)
        lid = cur.lastrowid
        conn.commit()
        conn.close()

        resp = self.client.get(f"/masters/ledgers/alter/{lid}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Ledger Alteration", resp.data)

        post_resp = self.client.post(f"/masters/ledgers/alter/{lid}", data={
            "name": "Altered Supplier Ltd",
            "group_id": "1",
            "opening_balance": "5000.00",
            "opening_balance_type": "Dr",
            "gstin": "27AAAAA0000A1Z5",
            "pan": "AAAAA0000A",
            "state_code": "27",
            "address": "123 Commercial Street"
        }, follow_redirects=True)
        self.assertEqual(post_resp.status_code, 200)

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT name, pan FROM ledgers WHERE id = ?", (lid,))
        new_row = cur.fetchone()
        self.assertEqual(new_row[0], "Altered Supplier Ltd")
        self.assertEqual(new_row[1], "AAAAA0000A")
        conn.close()

    def test_masters_alter_lists(self):
        """Test master alteration listing menus"""
        for mtype in ["groups", "ledgers", "stock-items", "godowns", "units", "voucher-types"]:
            resp = self.client.get(f"/masters/alter/{mtype}")
            self.assertEqual(resp.status_code, 200)
            self.assertIn(b"Alter Master", resp.data)

    def test_cash_flow_and_funds_flow(self):
        """Test Cash Flow and Funds Flow reports"""
        cf_resp = self.client.get("/reports/cash-flow")
        self.assertEqual(cf_resp.status_code, 200)
        self.assertIn(b"Cash Flow Statement", cf_resp.data)

        ff_resp = self.client.get("/reports/funds-flow")
        self.assertEqual(ff_resp.status_code, 200)
        self.assertIn(b"Funds Flow Statement", ff_resp.data)
        self.assertIn(b"Sources of Funds", ff_resp.data)
        self.assertIn(b"Applications of Funds", ff_resp.data)

    def test_stock_category_and_statutory_masters(self):
        """Test stock category and statutory GST creation screens"""
        resp_cat = self.client.get("/masters/stock-categories/create")
        self.assertEqual(resp_cat.status_code, 200)
        self.assertIn(b"Stock Category", resp_cat.data)

        resp_gst = self.client.get("/statutory/gst-details")
        self.assertEqual(resp_gst.status_code, 200)
        self.assertIn(b"GST Registration Details", resp_gst.data)

        resp_class = self.client.get("/statutory/gst-classification")
        self.assertEqual(resp_class.status_code, 200)
        self.assertIn(b"GST Classification Details", resp_class.data)

if __name__ == "__main__":
    unittest.main()
