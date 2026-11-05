"""
TallySoft Multi-Godown (Warehouse) & Stock Journal Transfer Engine
Supports multiple storage locations, location-wise inventory positions,
and Stock Journal (Alt+F7) inter-godown transfers.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from app.database import transaction


def init_godown_schema(db_path=None):
    """
    Initializes godowns and stock_transfers tables.
    """
    with transaction(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS godowns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                location TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
                UNIQUE(company_id, name)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS godown_stock (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                godown_id INTEGER NOT NULL,
                stock_item_id INTEGER NOT NULL,
                closing_qty REAL NOT NULL DEFAULT 0.0,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
                FOREIGN KEY (godown_id) REFERENCES godowns(id) ON DELETE CASCADE,
                FOREIGN KEY (stock_item_id) REFERENCES stock_items(id) ON DELETE CASCADE,
                UNIQUE(company_id, godown_id, stock_item_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stock_transfers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                transfer_number TEXT NOT NULL,
                transfer_date TEXT NOT NULL,
                source_godown_id INTEGER NOT NULL,
                dest_godown_id INTEGER NOT NULL,
                stock_item_id INTEGER NOT NULL,
                quantity REAL NOT NULL CHECK(quantity > 0),
                rate REAL NOT NULL DEFAULT 0.0,
                amount REAL NOT NULL DEFAULT 0.0,
                narration TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
                FOREIGN KEY (source_godown_id) REFERENCES godowns(id) ON DELETE RESTRICT,
                FOREIGN KEY (dest_godown_id) REFERENCES godowns(id) ON DELETE RESTRICT,
                FOREIGN KEY (stock_item_id) REFERENCES stock_items(id) ON DELETE RESTRICT
            )
        """)


def seed_default_godown(conn, company_id: int):
    """
    Ensures 'Main Location' exists for the company.
    """
    conn.execute("""
        INSERT OR IGNORE INTO godowns (company_id, name, location)
        VALUES (?, 'Main Location', 'Primary Warehouse')
    """, (company_id,))


def list_godowns(company_id: int, db_path=None) -> List[Dict[str, Any]]:
    """
    Returns all active godowns for the company.
    """
    init_godown_schema(db_path)
    with transaction(db_path) as conn:
        seed_default_godown(conn, company_id)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM godowns WHERE company_id = ? AND is_active = 1 ORDER BY name", (company_id,))
        return [dict(r) for r in cursor.fetchall()]


def create_godown(company_id: int, name: str, location: str = "", db_path=None) -> int:
    """
    Creates a new godown / warehouse.
    """
    init_godown_schema(db_path)
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO godowns (company_id, name, location)
            VALUES (?, ?, ?)
        """, (company_id, name.strip(), location.strip()))
        return cursor.lastrowid


def transfer_stock(
    company_id: int,
    source_godown_id: int,
    dest_godown_id: int,
    stock_item_id: int,
    quantity: float,
    rate: float = 0.0,
    transfer_date: str = "",
    narration: str = "",
    db_path=None
) -> int:
    """
    Executes a Stock Journal (Alt+F7) transfer: decreases stock in source godown and increases in dest godown.
    """
    if source_godown_id == dest_godown_id:
        raise ValueError("Source and destination godowns must be different.")

    init_godown_schema(db_path)
    t_date = transfer_date or datetime.now().strftime("%Y-%m-%d")
    qty = round(float(quantity), 2)
    amt = round(qty * float(rate), 2)

    with transaction(db_path) as conn:
        cursor = conn.cursor()

        # Generate transfer number
        cursor.execute("SELECT COUNT(*) FROM stock_transfers WHERE company_id = ?", (company_id,))
        num = cursor.fetchone()[0] + 1
        transfer_no = f"TRF-{num:04d}"

        # Insert transfer record
        cursor.execute("""
            INSERT INTO stock_transfers (
                company_id, transfer_number, transfer_date,
                source_godown_id, dest_godown_id, stock_item_id,
                quantity, rate, amount, narration
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            company_id, transfer_no, t_date,
            source_godown_id, dest_godown_id, stock_item_id,
            qty, rate, amt, narration
        ))
        trf_id = cursor.lastrowid

        # Update source godown stock
        cursor.execute("""
            INSERT INTO godown_stock (company_id, godown_id, stock_item_id, closing_qty)
            VALUES (?, ?, ?, -?)
            ON CONFLICT(company_id, godown_id, stock_item_id)
            DO UPDATE SET closing_qty = closing_qty - ?
        """, (company_id, source_godown_id, stock_item_id, qty, qty))

        # Update dest godown stock
        cursor.execute("""
            INSERT INTO godown_stock (company_id, godown_id, stock_item_id, closing_qty)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(company_id, godown_id, stock_item_id)
            DO UPDATE SET closing_qty = closing_qty + ?
        """, (company_id, dest_godown_id, stock_item_id, qty, qty))

        return trf_id


def get_godown_summary(company_id: int, db_path=None) -> List[Dict[str, Any]]:
    """
    Returns godown-wise inventory distribution.
    """
    init_godown_schema(db_path)
    with transaction(db_path) as conn:
        seed_default_godown(conn, company_id)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT g.id AS godown_id, g.name AS godown_name,
                   s.id AS stock_item_id, s.name AS item_name, u.symbol AS unit_symbol,
                   s.opening_rate,
                   COALESCE(gs.closing_qty, 0.0) AS quantity,
                   (COALESCE(gs.closing_qty, 0.0) * s.opening_rate) AS stock_value
            FROM godowns g
            CROSS JOIN stock_items s ON s.company_id = g.company_id
            JOIN units u ON s.unit_id = u.id
            LEFT JOIN godown_stock gs ON gs.godown_id = g.id AND gs.stock_item_id = s.id
            WHERE g.company_id = ? AND g.is_active = 1
            ORDER BY g.name, s.name
        """, (company_id,))
        return [dict(r) for r in cursor.fetchall()]

