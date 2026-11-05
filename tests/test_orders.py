"""
Unit Tests for Order Processing (Sales Orders & Purchase Orders)
"""

import unittest
import tempfile
from pathlib import Path

from app.database import init_db, create_company, get_connection
from app.order_engine import (
    create_order,
    list_orders,
    get_order_details,
    fulfill_order
)
from app.server import app


class TestOrderProcessing(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db_path = Path(self.temp_dir.name) / "test_orders.db"
        init_db(self.test_db_path)

        # Create demo company
        self.cid = create_company(
            name="Apex Manufacturing",
            state="Maharashtra",
            state_code="27",
            db_path=self.test_db_path
        )

        conn = get_connection(self.test_db_path)
        cur = conn.cursor()

        # Find Groups
        cur.execute("SELECT id FROM ledger_groups WHERE company_id = ? AND name = 'Sundry Debtors'", (self.cid,))
        debtor_grp = cur.fetchone()[0]

        # Create Customer
        cur.execute("""
            INSERT INTO ledgers (company_id, name, group_id, gstin, state_code)
            VALUES (?, 'Global Retail Hub', ?, '27GGGGG1111G1Z3', '27')
        """, (self.cid, debtor_grp))
        self.customer_id = cur.lastrowid

        # Create Stock Item
        cur.execute("SELECT id FROM units WHERE company_id = ? AND symbol = 'NOS'", (self.cid,))
        unit_id = cur.fetchone()[0]

        cur.execute("""
            INSERT INTO stock_items (company_id, name, unit_id, hsn_sac, gst_rate, opening_qty, opening_rate, closing_qty)
            VALUES (?, 'Industrial Valve 2-Inch', ?, '8481', 18.0, 100, 1500.0, 100)
        """, (self.cid, unit_id))
        self.item_id = cur.lastrowid
        self.unit_id = unit_id

        conn.commit()
        conn.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_create_and_list_sales_order(self):
        """Test creating a Sales Order with tax calculation and listing"""
        # 10 valves @ ₹2,000 + 18% GST (₹3,600) = ₹23,600
        oid = create_order(
            company_id=self.cid,
            order_type="Sales Order",
            order_date="2026-11-03",
            due_date="2026-11-20",
            party_ledger_id=self.customer_id,
            items=[{
                "stock_item_id": self.item_id,
                "quantity": 10.0,
                "rate": 2000.0,
                "gst_rate": 18.0,
                "unit_id": self.unit_id
            }],
            narration="Advance order for construction site",
            db_path=self.test_db_path
        )
        self.assertIsNotNone(oid)

        # Check order details
        order = get_order_details(self.cid, oid, db_path=self.test_db_path)
        self.assertEqual(order["order_number"], "SO-0001")
        self.assertEqual(order["status"], "Pending")
        self.assertEqual(order["subtotal"], 20000.0)
        self.assertEqual(order["tax_amount"], 3600.0)
        self.assertEqual(order["total_amount"], 23600.0)
        self.assertEqual(len(order["items"]), 1)

        # Check pending orders list
        orders = list_orders(self.cid, order_type="Sales Order", status="Pending", db_path=self.test_db_path)
        self.assertEqual(len(orders), 1)

        # Fulfill order
        fulfill_order(self.cid, oid, db_path=self.test_db_path)
        order_fulfilled = get_order_details(self.cid, oid, db_path=self.test_db_path)
        self.assertEqual(order_fulfilled["status"], "Fulfilled")

    def test_api_order_creation(self):
        """Test creating order via API endpoint"""
        client = app.test_client()
        payload = {
            "order_type": "Purchase Order",
            "order_date": "2026-11-03",
            "due_date": "2026-11-25",
            "party_ledger_id": self.customer_id,
            "items": [{
                "stock_item_id": self.item_id,
                "quantity": 5.0,
                "rate": 1200.0,
                "gst_rate": 18.0,
                "unit_id": self.unit_id
            }],
            "narration": "Restock PO"
        }
        res = client.post("/api/orders/create", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertIn("order_id", data)


if __name__ == "__main__":
    unittest.main()

