"""
TallySoft Manufacturing Journal & Bill of Materials (BOM) Engine
Handles standard product recipes (BOM), raw material consumption,
additional manufacturing costs, by-products, and finished goods inventory generation.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from app.database import transaction


def init_manufacturing_schema(db_path=None):
    """
    Initializes BOM masters, BOM components, and manufacturing journal tables.
    """
    from app.godown_engine import init_godown_schema
    init_godown_schema(db_path)

    with transaction(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bom_masters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                finished_item_id INTEGER NOT NULL,
                finished_qty REAL NOT NULL DEFAULT 1.0 CHECK(finished_qty > 0),
                unit_id INTEGER,
                narration TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
                FOREIGN KEY (finished_item_id) REFERENCES stock_items(id) ON DELETE CASCADE,
                FOREIGN KEY (unit_id) REFERENCES units(id) ON DELETE SET NULL,
                UNIQUE(company_id, finished_item_id, name)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS bom_components (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bom_id INTEGER NOT NULL,
                stock_item_id INTEGER NOT NULL,
                component_type TEXT NOT NULL DEFAULT 'Component' CHECK(component_type IN ('Component', 'By-Product', 'Co-Product', 'Scrap')),
                quantity REAL NOT NULL CHECK(quantity > 0),
                unit_id INTEGER,
                FOREIGN KEY (bom_id) REFERENCES bom_masters(id) ON DELETE CASCADE,
                FOREIGN KEY (stock_item_id) REFERENCES stock_items(id) ON DELETE RESTRICT,
                FOREIGN KEY (unit_id) REFERENCES units(id) ON DELETE SET NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS manufacturing_journals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                voucher_number TEXT NOT NULL,
                voucher_date TEXT NOT NULL,
                bom_id INTEGER,
                finished_item_id INTEGER NOT NULL,
                destination_godown_id INTEGER NOT NULL,
                produced_qty REAL NOT NULL CHECK(produced_qty > 0),
                raw_materials_cost REAL NOT NULL DEFAULT 0.0,
                additional_cost REAL NOT NULL DEFAULT 0.0,
                total_cost REAL NOT NULL DEFAULT 0.0,
                effective_rate REAL NOT NULL DEFAULT 0.0,
                narration TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
                FOREIGN KEY (bom_id) REFERENCES bom_masters(id) ON DELETE SET NULL,
                FOREIGN KEY (finished_item_id) REFERENCES stock_items(id) ON DELETE RESTRICT,
                FOREIGN KEY (destination_godown_id) REFERENCES godowns(id) ON DELETE RESTRICT,
                UNIQUE(company_id, voucher_number)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS manufacturing_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mfg_journal_id INTEGER NOT NULL,
                stock_item_id INTEGER NOT NULL,
                godown_id INTEGER NOT NULL,
                quantity REAL NOT NULL CHECK(quantity > 0),
                rate REAL NOT NULL DEFAULT 0.0,
                amount REAL NOT NULL DEFAULT 0.0,
                item_type TEXT NOT NULL DEFAULT 'Consumption' CHECK(item_type IN ('Consumption', 'By-Product', 'Co-Product', 'Scrap')),
                FOREIGN KEY (mfg_journal_id) REFERENCES manufacturing_journals(id) ON DELETE CASCADE,
                FOREIGN KEY (stock_item_id) REFERENCES stock_items(id) ON DELETE RESTRICT,
                FOREIGN KEY (godown_id) REFERENCES godowns(id) ON DELETE RESTRICT
            )
        """)


def create_bom(
    company_id: int,
    name: str,
    finished_item_id: int,
    finished_qty: float,
    components: List[Dict[str, Any]],
    unit_id: Optional[int] = None,
    narration: Optional[str] = None,
    db_path=None
) -> int:
    """
    Creates a Bill of Materials master and its components.
    """
    init_manufacturing_schema(db_path)
    with transaction(db_path) as conn:
        cursor = conn.execute("""
            INSERT INTO bom_masters (company_id, name, finished_item_id, finished_qty, unit_id, narration)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (company_id, name.strip(), finished_item_id, float(finished_qty), unit_id, narration))
        bom_id = cursor.lastrowid

        for comp in components:
            conn.execute("""
                INSERT INTO bom_components (bom_id, stock_item_id, component_type, quantity, unit_id)
                VALUES (?, ?, ?, ?, ?)
            """, (
                bom_id,
                comp['stock_item_id'],
                comp.get('component_type', 'Component'),
                float(comp['quantity']),
                comp.get('unit_id')
            ))

        return bom_id


def get_boms_for_item(company_id: int, finished_item_id: int, db_path=None) -> List[Dict[str, Any]]:
    """
    Retrieves all BOMs defined for a specific finished stock item.
    """
    init_manufacturing_schema(db_path)
    with transaction(db_path) as conn:
        boms = conn.execute("""
            SELECT b.*, s.name as finished_item_name, u.symbol as unit_symbol
            FROM bom_masters b
            JOIN stock_items s ON b.finished_item_id = s.id
            LEFT JOIN units u ON b.unit_id = u.id
            WHERE b.company_id = ? AND b.finished_item_id = ?
            ORDER BY b.name ASC
        """, (company_id, finished_item_id)).fetchall()

        result = []
        for b in boms:
            b_dict = dict(b)
            comps = conn.execute("""
                SELECT c.*, s.name as item_name, s.opening_rate, u.symbol as unit_symbol
                FROM bom_components c
                JOIN stock_items s ON c.stock_item_id = s.id
                LEFT JOIN units u ON c.unit_id = u.id
                WHERE c.bom_id = ?
            """, (b['id'],)).fetchall()
            b_dict['components'] = [dict(c) for c in comps]
            result.append(b_dict)
        return result


def record_manufacturing_journal(
    company_id: int,
    voucher_date: str,
    finished_item_id: int,
    destination_godown_id: int,
    produced_qty: float,
    consumed_items: List[Dict[str, Any]],
    bom_id: Optional[int] = None,
    additional_cost: float = 0.0,
    narration: Optional[str] = None,
    db_path=None
) -> Dict[str, Any]:
    """
    Executes a Manufacturing Journal voucher:
    - Verifies raw material stock in specified godowns.
    - Consumes raw materials (deducts stock from source godown and general stock).
    - Adds finished goods to destination godown and general stock.
    - Computes total cost and effective rate per finished unit.
    """
    init_manufacturing_schema(db_path)
    with transaction(db_path) as conn:
        # Generate voucher number
        row = conn.execute("""
            SELECT COUNT(*) as cnt FROM manufacturing_journals WHERE company_id = ?
        """, (company_id,)).fetchone()
        v_num = f"MFG-{(row['cnt'] + 1):04d}"

        # Calculate raw materials cost
        raw_materials_cost = 0.0
        for item in consumed_items:
            qty = float(item['quantity'])
            rate = float(item.get('rate', 0.0))
            if rate == 0.0:
                # Fallback to item opening rate
                stock_row = conn.execute("SELECT opening_rate FROM stock_items WHERE id = ?", (item['stock_item_id'],)).fetchone()
                if stock_row:
                    rate = stock_row['opening_rate'] or 0.0
            amount = round(qty * rate, 2)
            raw_materials_cost += amount

        total_cost = round(raw_materials_cost + float(additional_cost), 2)
        effective_rate = round(total_cost / produced_qty, 2) if produced_qty > 0 else 0.0

        # Insert manufacturing journal
        cursor = conn.execute("""
            INSERT INTO manufacturing_journals (
                company_id, voucher_number, voucher_date, bom_id, finished_item_id,
                destination_godown_id, produced_qty, raw_materials_cost,
                additional_cost, total_cost, effective_rate, narration
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            company_id, v_num, voucher_date, bom_id, finished_item_id,
            destination_godown_id, float(produced_qty), raw_materials_cost,
            float(additional_cost), total_cost, effective_rate, narration
        ))
        mfg_id = cursor.lastrowid

        # Deduct consumed raw materials
        for item in consumed_items:
            stock_id = item['stock_item_id']
            src_godown = item['godown_id']
            qty = float(item['quantity'])
            rate = float(item.get('rate', 0.0))
            amount = round(qty * rate, 2)
            item_type = item.get('item_type', 'Consumption')

            conn.execute("""
                INSERT INTO manufacturing_items (
                    mfg_journal_id, stock_item_id, godown_id, quantity, rate, amount, item_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (mfg_id, stock_id, src_godown, qty, rate, amount, item_type))

            # Deduct from godown_stock
            conn.execute("""
                INSERT INTO godown_stock (company_id, godown_id, stock_item_id, closing_qty)
                VALUES (?, ?, ?, -?)
                ON CONFLICT(company_id, godown_id, stock_item_id)
                DO UPDATE SET closing_qty = closing_qty - excluded.closing_qty
            """, (company_id, src_godown, stock_id, -qty))

            # Deduct from overall stock_items closing_qty
            conn.execute("""
                UPDATE stock_items
                SET closing_qty = closing_qty - ?,
                    closing_value = CASE WHEN closing_qty - ? <= 0 THEN 0.0 ELSE closing_value - ? END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (qty, qty, amount, stock_id))

        # Add finished goods to destination godown
        conn.execute("""
            INSERT INTO godown_stock (company_id, godown_id, stock_item_id, closing_qty)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(company_id, godown_id, stock_item_id)
            DO UPDATE SET closing_qty = closing_qty + excluded.closing_qty
        """, (company_id, destination_godown_id, finished_item_id, float(produced_qty)))

        # Update finished stock item balance and cost
        conn.execute("""
            UPDATE stock_items
            SET closing_qty = closing_qty + ?,
                closing_value = closing_value + ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (float(produced_qty), total_cost, finished_item_id))

        return {
            "mfg_id": mfg_id,
            "voucher_number": v_num,
            "produced_qty": produced_qty,
            "raw_materials_cost": raw_materials_cost,
            "additional_cost": additional_cost,
            "total_cost": total_cost,
            "effective_rate": effective_rate
        }


def list_manufacturing_journals(company_id: int, db_path=None) -> List[Dict[str, Any]]:
    """
    Returns list of all manufacturing journals.
    """
    init_manufacturing_schema(db_path)
    with transaction(db_path) as conn:
        rows = conn.execute("""
            SELECT m.*, s.name as finished_item_name, g.name as destination_godown_name, b.name as bom_name
            FROM manufacturing_journals m
            JOIN stock_items s ON m.finished_item_id = s.id
            JOIN godowns g ON m.destination_godown_id = g.id
            LEFT JOIN bom_masters b ON m.bom_id = b.id
            WHERE m.company_id = ?
            ORDER BY m.voucher_date DESC, m.id DESC
        """, (company_id,)).fetchall()
        return [dict(r) for r in rows]
