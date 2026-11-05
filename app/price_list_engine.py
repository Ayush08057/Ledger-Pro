"""
TallySoft Multiple Price Levels & Price Lists Engine
Supports Wholesale, Retail, Dealer tiers with quantity slabs and automated rate lookup.
"""

from typing import List, Dict, Any, Optional
from app.database import transaction, get_connection


def init_price_list_schema(db_path=None):
    """Initializes price levels and price lists schema."""
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS price_lists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                price_level TEXT NOT NULL,
                stock_item_id INTEGER NOT NULL,
                min_qty REAL NOT NULL DEFAULT 0.0,
                rate REAL NOT NULL DEFAULT 0.0,
                discount_percent REAL NOT NULL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
                FOREIGN KEY (stock_item_id) REFERENCES stock_items(id) ON DELETE CASCADE,
                UNIQUE(company_id, price_level, stock_item_id, min_qty)
            )
        """)


def set_price_list_entry(
    company_id: int,
    price_level: str,
    stock_item_id: int,
    rate: float,
    min_qty: float = 0.0,
    discount_percent: float = 0.0,
    db_path=None
):
    """Inserts or updates a price list entry for an item and price level."""
    init_price_list_schema(db_path)
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO price_lists (company_id, price_level, stock_item_id, min_qty, rate, discount_percent)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(company_id, price_level, stock_item_id, min_qty) DO UPDATE SET
                rate = excluded.rate,
                discount_percent = excluded.discount_percent
        """, (company_id, price_level.strip(), stock_item_id, min_qty, rate, discount_percent))


def get_item_price_for_level(
    company_id: int,
    price_level: str,
    stock_item_id: int,
    quantity: float = 1.0,
    db_path=None
) -> Optional[Dict[str, Any]]:
    """Looks up matching price slab for an item based on price level and quantity."""
    init_price_list_schema(db_path)
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT rate, discount_percent, min_qty
            FROM price_lists
            WHERE company_id = ? AND price_level = ? AND stock_item_id = ? AND min_qty <= ?
            ORDER BY min_qty DESC LIMIT 1
        """, (company_id, price_level.strip(), stock_item_id, quantity))
        row = cursor.fetchone()
        if row:
            return {
                "rate": float(row["rate"]),
                "discount_percent": float(row["discount_percent"]),
                "min_qty": float(row["min_qty"])
            }
        return None


def get_price_list_table(company_id: int, price_level: str, db_path=None) -> List[Dict[str, Any]]:
    """Fetches all items and their assigned rate for a given price level."""
    init_price_list_schema(db_path)
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.id AS stock_item_id, s.name AS item_name, s.opening_rate AS standard_rate,
                   u.symbol AS unit_symbol,
                   p.rate AS level_rate, p.discount_percent, p.min_qty
            FROM stock_items s
            LEFT JOIN units u ON s.unit_id = u.id
            LEFT JOIN price_lists p ON s.id = p.stock_item_id AND p.price_level = ? AND p.company_id = ?
            WHERE s.company_id = ?
            ORDER BY s.name
        """, (price_level.strip(), company_id, company_id))
        return [dict(r) for r in cursor.fetchall()]

