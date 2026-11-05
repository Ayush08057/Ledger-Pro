"""
TallySoft Physical Stock Verification Engine
Handles physical stock counting, discrepancy calculations against book stock,
and automatic closing inventory adjustments with audit trail logging.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from app.database import transaction, get_connection


def init_physical_stock_schema(db_path=None):
    """Initializes physical stock journal tables if not already present."""
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS physical_stock_vouchers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                voucher_number TEXT NOT NULL,
                voucher_date TEXT NOT NULL,
                total_discrepancy_value REAL NOT NULL DEFAULT 0.0,
                narration TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
                UNIQUE(company_id, voucher_number)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS physical_stock_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                voucher_id INTEGER NOT NULL,
                stock_item_id INTEGER NOT NULL,
                book_qty REAL NOT NULL DEFAULT 0.0,
                physical_qty REAL NOT NULL DEFAULT 0.0,
                difference_qty REAL NOT NULL DEFAULT 0.0,
                unit_id INTEGER,
                rate REAL NOT NULL DEFAULT 0.0,
                discrepancy_value REAL NOT NULL DEFAULT 0.0,
                FOREIGN KEY (voucher_id) REFERENCES physical_stock_vouchers(id) ON DELETE CASCADE,
                FOREIGN KEY (stock_item_id) REFERENCES stock_items(id) ON DELETE RESTRICT
            )
        """)


def record_physical_stock(
    company_id: int,
    voucher_date: str,
    items: List[Dict[str, Any]],
    narration: str = "",
    db_path=None
) -> int:
    """
    Records physical stock counts. For each item:
    - Calculates difference: physical_qty - book_qty
    - Updates stock_items closing_qty to match physical_qty
    - Records voucher and discrepancy items
    - Writes audit log
    """
    init_physical_stock_schema(db_path)

    with transaction(db_path) as conn:
        cursor = conn.cursor()

        # Check or generate voucher number
        prefix = "PSTK"
        cursor.execute("""
            SELECT voucher_number FROM physical_stock_vouchers
            WHERE company_id = ?
            ORDER BY id DESC LIMIT 1
        """, (company_id,))
        row = cursor.fetchone()
        if not row:
            v_num = f"{prefix}-0001"
        else:
            try:
                seq = int(row[0].split("-")[-1]) + 1
                v_num = f"{prefix}-{seq:04d}"
            except Exception:
                v_num = f"{prefix}-{int(datetime.now().timestamp())}"

        cursor.execute("""
            INSERT INTO physical_stock_vouchers (
                company_id, voucher_number, voucher_date, total_discrepancy_value, narration
            ) VALUES (?, ?, ?, 0.0, ?)
        """, (company_id, v_num, voucher_date, narration))
        voucher_id = cursor.lastrowid

        total_discrepancy_val = 0.0
        discrepancy_summary = []

        for item in items:
            item_id = int(item["stock_item_id"])
            phys_qty = float(item["physical_qty"])

            # Query current book stock
            cursor.execute("SELECT name, closing_qty, opening_rate, unit_id FROM stock_items WHERE id = ?", (item_id,))
            stk_row = cursor.fetchone()
            if not stk_row:
                continue

            item_name = stk_row["name"]
            book_qty = float(stk_row["closing_qty"])
            rate = float(item.get("rate") or stk_row["opening_rate"] or 0.0)
            unit_id = stk_row["unit_id"]

            diff_qty = round(phys_qty - book_qty, 4)
            diff_val = round(diff_qty * rate, 2)
            total_discrepancy_val += diff_val

            cursor.execute("""
                INSERT INTO physical_stock_items (
                    voucher_id, stock_item_id, book_qty, physical_qty,
                    difference_qty, unit_id, rate, discrepancy_value
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (voucher_id, item_id, book_qty, phys_qty, diff_qty, unit_id, rate, diff_val))

            # Adjust stock_items closing_qty to match physical count
            cursor.execute("""
                UPDATE stock_items
                SET closing_qty = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (phys_qty, item_id))

            discrepancy_summary.append(f"{item_name}: Book {book_qty} -> Physical {phys_qty} (Diff: {diff_qty:+.2f})")

        # Update total discrepancy value
        cursor.execute("""
            UPDATE physical_stock_vouchers
            SET total_discrepancy_value = ?
            WHERE id = ?
        """, (total_discrepancy_val, voucher_id))

        # Record Audit Log
        details_txt = f"Physical Stock {v_num} verified on {voucher_date}. Adjustments: " + "; ".join(discrepancy_summary)
        cursor.execute("""
            INSERT INTO audit_logs (company_id, entity_type, entity_id, action, details)
            VALUES (?, 'StockItem', ?, 'UPDATE', ?)
        """, (company_id, voucher_id, details_txt[:500]))

        return voucher_id
