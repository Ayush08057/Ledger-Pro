"""
Integration Tests for Server Endpoints & Tally User Interface
"""

import unittest
from app.server import app, init_db
from app.database import create_company, get_connection

class TestServerUI(unittest.TestCase):
    def setUp(self):
        init_db()
        self.client = app.test_client()
        self.client.testing = True

    def test_gateway_route(self):
        """Gateway of Tally returns 200 OK and contains Gateway menu items"""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Gateway of Tally", res.data)
        self.assertIn(b"MASTERS", res.data)
        self.assertIn(b"TRANSACTIONS", res.data)
        self.assertIn(b"REPORTS", res.data)

    def test_voucher_create_screen(self):
        """Voucher creation screen returns 200 OK for Sales, Purchase, and Payment"""
        for vtype in ["Sales", "Purchase", "Payment", "Receipt", "Contra", "Journal"]:
            res = self.client.get(f"/vouchers/create?type={vtype}")
            self.assertEqual(res.status_code, 200)
            self.assertIn(vtype.encode(), res.data)

    def test_reports_screens(self):
        """All financial reports return 200 OK"""
        for route in ["/daybook", "/reports/trial-balance", "/reports/balance-sheet", "/reports/profit-loss", "/reports/stock-summary", "/masters/chart-of-accounts"]:
            res = self.client.get(route)
            self.assertEqual(res.status_code, 200, f"Route {route} failed with status {res.status_code}")

    def test_create_and_post_sales_voucher_api(self):
        """Test API creation of Sales voucher via Flask client"""
        # Get debtor and stock item
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM ledgers WHERE company_id = 1 AND name = 'Cash'")
        cash_id = cur.fetchone()[0]

        # Insert a test stock item if none exists
        cur.execute("SELECT id FROM stock_items WHERE company_id = 1")
        stock_row = cur.fetchone()
        if not stock_row:
            cur.execute("""
                INSERT INTO stock_items (company_id, name, unit_id, gst_rate, opening_qty, opening_rate, closing_qty)
                VALUES (1, 'Test Item A', 1, 18.0, 100, 500.0, 100)
            """)
            conn.commit()
            item_id = cur.lastrowid
        else:
            item_id = stock_row[0]
        conn.close()

        payload = {
            "voucher_type": "Sales",
            "voucher_date": "2026-11-03",
            "party_ledger_id": cash_id,
            "narration": "Test Cash Sales via Web Interface",
            "items": [
                {
                    "stock_item_id": item_id,
                    "quantity": 1,
                    "rate": 1000.0,
                    "gst_rate": 18.0,
                    "unit_id": 1
                }
            ]
        }
        res = self.client.post("/api/vouchers", json=payload)
        self.assertEqual(res.status_code, 200)
        json_data = res.get_json()
        self.assertTrue(json_data["success"])
        self.assertIn("voucher_id", json_data)

    def test_manufacturing_and_payroll_routes(self):
        """Verify routes for Manufacturing, TDS Form 26Q, and Payroll"""
        for route in [
            "/inventory/manufacturing",
            "/inventory/manufacturing/create",
            "/inventory/bom/create",
            "/statutory/tds",
            "/statutory/tds/entry",
            "/payroll/employees",
            "/payroll/process",
            "/masters/currencies",
            "/pos/invoice",
            "/budgets",
            "/budgets/create",
            "/reports/cash-flow"
        ]:
            res = self.client.get(route)
            self.assertEqual(res.status_code, 200, f"Route {route} failed with status {res.status_code}")

    def test_company_features_api(self):
        """Test GET and POST for F11 Company Features Alteration"""
        get_res = self.client.get("/api/company/features")
        self.assertEqual(get_res.status_code, 200)
        data = get_res.get_json()
        self.assertTrue(data["success"])
        self.assertIn("features", data)
        self.assertEqual(data["features"]["maintain_accounts"], "Yes")

        post_res = self.client.post("/api/company/features", json={
            "enable_cost_centres": "Yes",
            "enable_batches": "Yes"
        })
        self.assertEqual(post_res.status_code, 200)

        verify_res = self.client.get("/api/company/features")
        vdata = verify_res.get_json()
        self.assertEqual(vdata["features"]["enable_cost_centres"], "Yes")
        self.assertEqual(vdata["features"]["enable_batches"], "Yes")

    def test_voucher_config_api(self):
        """Test GET and POST for F12 Voucher Configuration"""
        # Test updating to Yes and No
        post_res1 = self.client.post("/api/voucher/config", json={"use_dr_cr": "Yes"})
        self.assertEqual(post_res1.status_code, 200)
        get_res1 = self.client.get("/api/voucher/config")
        self.assertEqual(get_res1.get_json()["config"]["use_dr_cr"], "Yes")

        post_res2 = self.client.post("/api/voucher/config", json={"use_dr_cr": "No"})
        self.assertEqual(post_res2.status_code, 200)
        get_res2 = self.client.get("/api/voucher/config")
        self.assertEqual(get_res2.get_json()["config"]["use_dr_cr"], "No")

        # Restore default Yes
        self.client.post("/api/voucher/config", json={"use_dr_cr": "Yes"})

    def test_accounting_sales_and_purchase_voucher_postings(self):
        """Test posting Sales and Purchase vouchers via direct Dr/Cr accounting entry"""
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM ledgers WHERE company_id = 1 AND name = 'Cash'")
        cash_id = cur.fetchone()[0]
        cur.execute("SELECT id FROM ledgers WHERE company_id = 1 AND name = 'Sales Account'")
        sales_id = cur.fetchone()[0]
        conn.close()

        payload = {
            "voucher_type": "Sales",
            "voucher_date": "2026-11-03",
            "narration": "Direct Accounting Sales Voucher Entry",
            "postings": [
                {"ledger_id": cash_id, "entry_type": "Dr", "amount": 25000.00},
                {"ledger_id": sales_id, "entry_type": "Cr", "amount": 25000.00}
            ]
        }
        res = self.client.post("/api/vouchers", json=payload)
        self.assertEqual(res.status_code, 200)
        json_data = res.get_json()
        self.assertTrue(json_data["success"])
        self.assertIn("voucher_id", json_data)

    def test_daybook_screen_content(self):
        """Day Book screen renders columns matching authentic Tally layout"""
        res = self.client.get("/daybook")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Day Book", res.data)
        self.assertIn(b"Debit Amount", res.data)
        self.assertIn(b"Credit Amount", res.data)
        self.assertIn(b"Vch Type", res.data)
        self.assertIn(b"Vch No.", res.data)

    def test_live_dates_and_days_in_ui(self):
        """Verify Gateway, Vouchers, and Header render live dates and days"""
        from datetime import datetime
        now = datetime.now()
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        day_name = days[now.weekday()]
        m_name = months[now.month - 1]
        tally_date = f"{now.day}-{m_name}-{str(now.year)[-2:]}"

        # 1. Gateway
        res_gw = self.client.get("/")
        self.assertEqual(res_gw.status_code, 200)
        html_gw = res_gw.get_data(as_text=True)
        self.assertIn("currentDateDisplay", html_gw)
        self.assertIn(day_name, html_gw)

        # 2. Voucher Entry
        res_vch = self.client.get("/vouchers/create?type=Payment")
        self.assertEqual(res_vch.status_code, 200)
        html_vch = res_vch.get_data(as_text=True)
        self.assertIn("voucherDayDisplay", html_vch)
        self.assertIn(day_name, html_vch)
        self.assertIn(tally_date, html_vch)
        self.assertIn("tallyHeaderDateFormatted", html_vch)
        self.assertIn("tallyHeaderDayFormatted", html_vch)

if __name__ == "__main__":
    unittest.main()

