"""
TallySoft Order Processing Engine (Sales Orders & Purchase Orders)
Manages order generation, fulfillment tracking, and pending order outstandings.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from app.database import transaction
from app.gst_engine import is_interstate_transaction, calculate_item_gst


def init_order_schema(db_path=None):
    """
    Initializes orders and order_items tables safely without disturbing existing tables.
    """
    with transaction(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                order_type TEXT NOT NULL CHECK(order_type IN ('Sales Order', 'Purchase Order')),
                order_number TEXT NOT NULL,
                order_date TEXT NOT NULL,
                party_ledger_id INTEGER NOT NULL,
                due_date TEXT,
                status TEXT NOT NULL DEFAULT 'Pending' CHECK(status IN ('Pending', 'Partially Fulfilled', 'Fulfilled', 'Cancelled')),
                subtotal REAL NOT NULL DEFAULT 0.0,
                tax_amount REAL NOT NULL DEFAULT 0.0,
                total_amount REAL NOT NULL DEFAULT 0.0,
                narration TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
                FOREIGN KEY (party_ledger_id) REFERENCES ledgers(id) ON DELETE RESTRICT,
                UNIQUE(company_id, order_type, order_number)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                stock_item_id INTEGER NOT NULL,
                quantity REAL NOT NULL CHECK(quantity > 0),
                fulfilled_qty REAL NOT NULL DEFAULT 0.0,
                unit_id INTEGER NOT NULL,
                rate REAL NOT NULL CHECK(rate >= 0),
                gst_rate REAL NOT NULL DEFAULT 0.0,
                taxable_amount REAL NOT NULL,
                total_amount REAL NOT NULL,
                FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
                FOREIGN KEY (stock_item_id) REFERENCES stock_items(id) ON DELETE RESTRICT,
                FOREIGN KEY (unit_id) REFERENCES units(id) ON DELETE RESTRICT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_company ON orders(company_id, order_type);")


def get_next_order_number(conn, company_id: int, order_type: str) -> str:
    prefix = "SO" if order_type == "Sales Order" else "PO"
    cur = conn.cursor()
    cur.execute("SELECT order_number FROM orders WHERE company_id = ? AND order_type = ? ORDER BY id DESC LIMIT 1", (company_id, order_type))
    row = cur.fetchone()
    if not row:
        return f"{prefix}-0001"
    try:
        seq = int(row[0].split("-")[-1]) + 1
        return f"{prefix}-{seq:04d}"
    except Exception:
        return f"{prefix}-{int(datetime.now().timestamp())}"


def create_order(
    company_id: int,
    order_type: str,
    order_date: str,
    party_ledger_id: int,
    items: List[Dict[str, Any]],
    due_date: Optional[str] = None,
    narration: str = "",
    order_number: Optional[str] = None,
    db_path=None
) -> int:
    """
    Creates a Sales Order or Purchase Order.
    """
    init_order_schema(db_path)
    with transaction(db_path) as conn:
        cursor = conn.cursor()

        # Company & party state for tax
        cursor.execute("SELECT state_code FROM companies WHERE id = ?", (company_id,))
        comp = cursor.fetchone()
        comp_state = comp["state_code"] if comp else "27"

        cursor.execute("SELECT state_code FROM ledgers WHERE id = ?", (party_ledger_id,))
        party = cursor.fetchone()
        party_state = party["state_code"] if party and party["state_code"] else comp_state
        is_interstate = is_interstate_transaction(comp_state, party_state)

        o_num = order_number or get_next_order_number(conn, company_id, order_type)

        tot_taxable = 0.0
        tot_tax = 0.0
        processed_items = []

        for it in items:
            qty = float(it["quantity"])
            rate = float(it["rate"])
            taxable = round(qty * rate, 2)
            gst_rate = float(it.get("gst_rate", 0.0))
            gst_info = calculate_item_gst(taxable, gst_rate, is_interstate)

            tot_taxable += taxable
            tot_tax += gst_info["total_tax"]

            processed_items.append({
                "stock_item_id": it["stock_item_id"],
                "quantity": qty,
                "unit_id": it.get("unit_id", 1),
                "rate": rate,
                "gst_rate": gst_rate,
                "taxable_amount": taxable,
                "total_amount": gst_info["total_amount"]
            })

        final_total = round(tot_taxable + tot_tax, 2)

        cursor.execute("""
            INSERT INTO orders (
                company_id, order_type, order_number, order_date,
                party_ledger_id, due_date, status, subtotal, tax_amount, total_amount, narration
            ) VALUES (?, ?, ?, ?, ?, ?, 'Pending', ?, ?, ?, ?)
        """, (
            company_id, order_type, o_num, order_date,
            party_ledger_id, due_date or order_date,
            round(tot_taxable, 2), round(tot_tax, 2), final_total, narration
        ))
        order_id = cursor.lastrowid

        for pit in processed_items:
            cursor.execute("""
                INSERT INTO order_items (
                    order_id, stock_item_id, quantity, fulfilled_qty,
                    unit_id, rate, gst_rate, taxable_amount, total_amount
                ) VALUES (?, ?, ?, 0.0, ?, ?, ?, ?, ?)
            """, (
                order_id, pit["stock_item_id"], pit["quantity"],
                pit["unit_id"], pit["rate"], pit["gst_rate"],
                pit["taxable_amount"], pit["total_amount"]
            ))

        return order_id


def list_orders(company_id: int, order_type: Optional[str] = None, status: Optional[str] = None, db_path=None) -> List[Dict[str, Any]]:
    """
    Returns list of orders with party details and pending quantities.
    """
    init_order_schema(db_path)
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        query = """
            SELECT o.*, l.name AS party_name, l.phone AS party_phone, l.gstin AS party_gstin,
                   (SELECT COUNT(*) FROM order_items oi WHERE oi.order_id = o.id) AS item_count,
                   (SELECT SUM(quantity - fulfilled_qty) FROM order_items oi WHERE oi.order_id = o.id) AS pending_qty
            FROM orders o
            JOIN ledgers l ON o.party_ledger_id = l.id
            WHERE o.company_id = ?
        """
        params = [company_id]
        if order_type:
            query += " AND o.order_type = ?"
            params.append(order_type)
        if status:
            query += " AND o.status = ?"
            params.append(status)
        query += " ORDER BY o.order_date DESC, o.id DESC"

        cursor.execute(query, params)
        return [dict(r) for r in cursor.fetchall()]


def get_order_details(company_id: int, order_id: int, db_path=None) -> Optional[Dict[str, Any]]:
    """
    Retrieves complete order header and items.
    """
    init_order_schema(db_path)
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT o.*, l.name AS party_name, l.address AS party_address, l.gstin AS party_gstin, l.state_code AS party_state
            FROM orders o
            JOIN ledgers l ON o.party_ledger_id = l.id
            WHERE o.id = ? AND o.company_id = ?
        """, (order_id, company_id))
        order_row = cursor.fetchone()
        if not order_row:
            return None

        order = dict(order_row)
        cursor.execute("""
            SELECT oi.*, s.name AS item_name, s.hsn_sac, u.symbol AS unit_symbol
            FROM order_items oi
            JOIN stock_items s ON oi.stock_item_id = s.id
            JOIN units u ON oi.unit_id = u.id
            WHERE oi.order_id = ?
        """, (order_id,))
        order["items"] = [dict(r) for r in cursor.fetchall()]
        return order


def fulfill_order(company_id: int, order_id: int, db_path=None) -> bool:
    """
    Marks an order as completely fulfilled.
    """
    init_order_schema(db_path)
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE order_items 
            SET fulfilled_qty = quantity 
            WHERE order_id = ?
        """, (order_id,))
        cursor.execute("""
            UPDATE orders 
            SET status = 'Fulfilled' 
            WHERE id = ? AND company_id = ?
        """, (order_id, company_id))
        return True

