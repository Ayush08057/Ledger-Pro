"""
TallySoft Bill-Wise Accounting Engine
Handles New Ref, Against Ref (Agst Ref), Advance, and On Account tracking,
settling invoices, and calculating Bill-by-Bill Ageing Analysis (0-30, 31-60, 61-90, >90 days).
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from app.database import transaction, get_connection


def init_bill_wise_schema(db_path=None):
    """
    Initializes bill_allocations table without affecting any existing table.
    """
    with transaction(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bill_allocations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                party_ledger_id INTEGER NOT NULL,
                voucher_id INTEGER,
                bill_ref_type TEXT NOT NULL CHECK(bill_ref_type IN ('New Ref', 'Agst Ref', 'Advance', 'On Account')),
                bill_number TEXT NOT NULL,
                bill_date TEXT NOT NULL,
                due_date TEXT,
                amount REAL NOT NULL CHECK(amount > 0),
                settled_amount REAL NOT NULL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
                FOREIGN KEY (party_ledger_id) REFERENCES ledgers(id) ON DELETE CASCADE,
                FOREIGN KEY (voucher_id) REFERENCES vouchers(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_bill_party ON bill_allocations(party_ledger_id, bill_number);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_bill_comp ON bill_allocations(company_id);")


def record_bill_reference(
    company_id: int,
    party_ledger_id: int,
    bill_ref_type: str,
    bill_number: str,
    bill_date: str,
    amount: float,
    voucher_id: Optional[int] = None,
    due_date: Optional[str] = None,
    db_path=None
) -> int:
    """
    Records a bill reference (e.g. New Ref on Sales/Purchase, or Advance on Receipt).
    """
    init_bill_wise_schema(db_path)
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO bill_allocations (
                company_id, party_ledger_id, voucher_id, bill_ref_type,
                bill_number, bill_date, due_date, amount, settled_amount
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0.0)
        """, (
            company_id, party_ledger_id, voucher_id, bill_ref_type,
            bill_number, bill_date, due_date or bill_date, round(float(amount), 2)
        ))
        return cursor.lastrowid


def get_pending_bills(company_id: int, party_ledger_id: int, db_path=None) -> List[Dict[str, Any]]:
    """
    Returns all unpaid or partially paid bills for a specific party.
    """
    init_bill_wise_schema(db_path)
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, bill_number, bill_date, due_date, bill_ref_type,
                   amount, settled_amount, (amount - settled_amount) AS pending_amount
            FROM bill_allocations
            WHERE company_id = ? AND party_ledger_id = ? 
                  AND bill_ref_type IN ('New Ref', 'Advance')
                  AND (amount - settled_amount) > 0.01
            ORDER BY bill_date ASC, id ASC
        """, (company_id, party_ledger_id))
        return [dict(r) for r in cursor.fetchall()]


def settle_bill_against_ref(
    company_id: int,
    party_ledger_id: int,
    bill_number: str,
    settle_amount: float,
    settling_voucher_id: Optional[int] = None,
    settle_date: Optional[str] = None,
    db_path=None
) -> bool:
    """
    Settles an existing bill reference using 'Agst Ref' (Against Reference).
    """
    init_bill_wise_schema(db_path)
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        # Find the original New Ref bill
        cursor.execute("""
            SELECT id, amount, settled_amount, bill_date 
            FROM bill_allocations
            WHERE company_id = ? AND party_ledger_id = ? AND bill_number = ?
                  AND bill_ref_type IN ('New Ref', 'Advance')
            LIMIT 1
        """, (company_id, party_ledger_id, bill_number))
        row = cursor.fetchone()
        if not row:
            return False

        bill_id = row["id"]
        cur_settled = float(row["settled_amount"])
        new_settled = cur_settled + float(settle_amount)

        # Update original bill settled amount
        cursor.execute("""
            UPDATE bill_allocations
            SET settled_amount = ?
            WHERE id = ?
        """, (round(new_settled, 2), bill_id))

        # Record Agst Ref record for the settling payment/receipt
        cursor.execute("""
            INSERT INTO bill_allocations (
                company_id, party_ledger_id, voucher_id, bill_ref_type,
                bill_number, bill_date, amount, settled_amount
            ) VALUES (?, ?, ?, 'Agst Ref', ?, ?, ?, ?)
        """, (
            company_id, party_ledger_id, settling_voucher_id, bill_number,
            settle_date or datetime.now().strftime("%Y-%m-%d"),
            round(float(settle_amount), 2), round(float(settle_amount), 2)
        ))
        return True


def get_bill_ageing_analysis(company_id: int, party_ledger_id: Optional[int] = None, as_on_date: str = "", db_path=None) -> List[Dict[str, Any]]:
    """
    Generates Tally standard Bill-wise Ageing Analysis (0-30, 31-60, 61-90, >90 days overdue).
    """
    init_bill_wise_schema(db_path)
    ref_date = datetime.strptime(as_on_date, "%Y-%m-%d") if as_on_date else datetime.now()

    with transaction(db_path) as conn:
        cursor = conn.cursor()
        query = """
            SELECT b.id, b.bill_number, b.bill_date, b.due_date, b.amount, b.settled_amount,
                   (b.amount - b.settled_amount) AS pending_amount,
                   l.id AS party_id, l.name AS party_name, l.phone, g.name AS group_name
            FROM bill_allocations b
            JOIN ledgers l ON b.party_ledger_id = l.id
            JOIN ledger_groups g ON l.group_id = g.id
            WHERE b.company_id = ? AND b.bill_ref_type IN ('New Ref', 'Advance')
                  AND (b.amount - b.settled_amount) > 0.01
        """
        params = [company_id]
        if party_ledger_id:
            query += " AND b.party_ledger_id = ?"
            params.append(party_ledger_id)
        query += " ORDER BY b.bill_date ASC"

        cursor.execute(query, params)
        rows = cursor.fetchall()

        results = []
        for r in rows:
            pending = float(r["pending_amount"])
            bill_dt = datetime.strptime(r["bill_date"], "%Y-%m-%d")
            days_old = max(0, (ref_date - bill_dt).days)

            # Slabs
            bucket_0_30 = pending if days_old <= 30 else 0.0
            bucket_31_60 = pending if 30 < days_old <= 60 else 0.0
            bucket_61_90 = pending if 60 < days_old <= 90 else 0.0
            bucket_over_90 = pending if days_old > 90 else 0.0

            results.append({
                "party_name": r["party_name"],
                "group_name": r["group_name"],
                "bill_number": r["bill_number"],
                "bill_date": r["bill_date"],
                "days_old": days_old,
                "pending_amount": round(pending, 2),
                "slab_0_30": round(bucket_0_30, 2),
                "slab_31_60": round(bucket_31_60, 2),
                "slab_61_90": round(bucket_61_90, 2),
                "slab_over_90": round(bucket_over_90, 2)
            })

        return results

