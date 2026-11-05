"""
TallySoft Cost Categories & Cost Centres Engine
Enables multi-dimensional expense and revenue allocation across projects,
departments, and branches without duplicating ledger accounts.
"""

from typing import List, Dict, Any, Optional
from app.database import transaction


def init_cost_centre_schema(db_path=None):
    """
    Initializes cost_categories, cost_centres, and voucher_cost_allocations.
    """
    with transaction(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cost_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                is_revenue INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
                UNIQUE(company_id, name)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cost_centres (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                category_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
                FOREIGN KEY (category_id) REFERENCES cost_categories(id) ON DELETE CASCADE,
                UNIQUE(company_id, name)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS voucher_cost_allocations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                voucher_id INTEGER NOT NULL,
                journal_entry_id INTEGER NOT NULL,
                cost_centre_id INTEGER NOT NULL,
                amount REAL NOT NULL CHECK(amount > 0),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
                FOREIGN KEY (voucher_id) REFERENCES vouchers(id) ON DELETE CASCADE,
                FOREIGN KEY (journal_entry_id) REFERENCES journal_entries(id) ON DELETE CASCADE,
                FOREIGN KEY (cost_centre_id) REFERENCES cost_centres(id) ON DELETE CASCADE
            )
        """)


def seed_default_cost_centres(conn, company_id: int):
    """
    Ensures default 'Primary Cost Category' exists.
    """
    conn.execute("""
        INSERT OR IGNORE INTO cost_categories (company_id, name)
        VALUES (?, 'Primary Cost Category')
    """, (company_id,))


def create_cost_category(company_id: int, name: str, is_revenue: int = 1, db_path=None) -> int:
    init_cost_centre_schema(db_path)
    with transaction(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO cost_categories (company_id, name, is_revenue)
            VALUES (?, ?, ?)
        """, (company_id, name.strip(), is_revenue))
        return cur.lastrowid


def create_cost_centre(company_id: int, category_id: int, name: str, db_path=None) -> int:
    init_cost_centre_schema(db_path)
    with transaction(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO cost_centres (company_id, category_id, name)
            VALUES (?, ?, ?)
        """, (company_id, category_id, name.strip()))
        return cur.lastrowid


def list_cost_centres(company_id: int, db_path=None) -> List[Dict[str, Any]]:
    init_cost_centre_schema(db_path)
    with transaction(db_path) as conn:
        seed_default_cost_centres(conn, company_id)
        cur = conn.cursor()
        cur.execute("""
            SELECT cc.id, cc.name AS centre_name, cat.id AS category_id, cat.name AS category_name
            FROM cost_centres cc
            JOIN cost_categories cat ON cc.category_id = cat.id
            WHERE cc.company_id = ?
            ORDER BY cat.name, cc.name
        """, (company_id,))
        return [dict(r) for r in cur.fetchall()]


def list_cost_categories(company_id: int, db_path=None) -> List[Dict[str, Any]]:
    init_cost_centre_schema(db_path)
    with transaction(db_path) as conn:
        seed_default_cost_centres(conn, company_id)
        cur = conn.cursor()
        cur.execute("SELECT * FROM cost_categories WHERE company_id = ? ORDER BY name", (company_id,))
        return [dict(r) for r in cur.fetchall()]


def allocate_cost(
    company_id: int,
    voucher_id: int,
    journal_entry_id: int,
    cost_centre_id: int,
    amount: float,
    db_path=None
) -> int:
    init_cost_centre_schema(db_path)
    with transaction(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO voucher_cost_allocations (company_id, voucher_id, journal_entry_id, cost_centre_id, amount)
            VALUES (?, ?, ?, ?, ?)
        """, (company_id, voucher_id, journal_entry_id, cost_centre_id, round(float(amount), 2)))
        return cur.lastrowid


def get_cost_centre_breakup_report(company_id: int, db_path=None) -> List[Dict[str, Any]]:
    """
    Returns itemized expense and revenue breakdown by Cost Category and Cost Centre.
    """
    init_cost_centre_schema(db_path)
    with transaction(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT cat.name AS category_name, cc.name AS centre_name,
                   l.name AS ledger_name, g.nature,
                   v.voucher_number, v.voucher_date, v.voucher_type,
                   vca.amount
            FROM voucher_cost_allocations vca
            JOIN cost_centres cc ON vca.cost_centre_id = cc.id
            JOIN cost_categories cat ON cc.category_id = cat.id
            JOIN journal_entries j ON vca.journal_entry_id = j.id
            JOIN ledgers l ON j.ledger_id = l.id
            JOIN ledger_groups g ON l.group_id = g.id
            JOIN vouchers v ON vca.voucher_id = v.id
            WHERE vca.company_id = ?
            ORDER BY cat.name, cc.name, v.voucher_date DESC
        """, (company_id,))
        return [dict(r) for r in cur.fetchall()]

