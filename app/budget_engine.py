"""
TallySoft Financial Budgets & Variance Analysis Engine
Allows setting period-specific financial budgets for Ledgers and Groups,
and generates automated Budget vs Actual Variance Analysis reports.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from app.database import transaction


def init_budget_schema(db_path=None):
    """
    Initializes budgets and budget_items tables safely.
    """
    with transaction(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                from_date TEXT NOT NULL,
                to_date TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
                UNIQUE(company_id, name)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS budget_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                budget_id INTEGER NOT NULL,
                ledger_id INTEGER NOT NULL,
                allocated_amount REAL NOT NULL CHECK(allocated_amount >= 0),
                FOREIGN KEY (budget_id) REFERENCES budgets(id) ON DELETE CASCADE,
                FOREIGN KEY (ledger_id) REFERENCES ledgers(id) ON DELETE CASCADE,
                UNIQUE(budget_id, ledger_id)
            )
        """)


def create_budget(
    company_id: int,
    name: str,
    from_date: str,
    to_date: str,
    allocations: List[Dict[str, Any]],
    db_path=None
) -> int:
    """
    Creates a new budget master with ledger allocations.
    allocations: [{"ledger_id": int, "allocated_amount": float}]
    """
    init_budget_schema(db_path)
    with transaction(db_path) as conn:
        cursor = conn.execute("""
            INSERT INTO budgets (company_id, name, from_date, to_date)
            VALUES (?, ?, ?, ?)
        """, (company_id, name.strip(), from_date, to_date))
        budget_id = cursor.lastrowid

        for alloc in allocations:
            conn.execute("""
                INSERT INTO budget_items (budget_id, ledger_id, allocated_amount)
                VALUES (?, ?, ?)
            """, (budget_id, int(alloc['ledger_id']), float(alloc['allocated_amount'])))

        return budget_id


def list_budgets(company_id: int, db_path=None) -> List[Dict[str, Any]]:
    """
    Lists all budgets defined for a company.
    """
    init_budget_schema(db_path)
    with transaction(db_path) as conn:
        rows = conn.execute("""
            SELECT b.*, 
                   COUNT(bi.id) as allocated_ledgers_count,
                   COALESCE(SUM(bi.allocated_amount), 0.0) as total_allocated_budget
            FROM budgets b
            LEFT JOIN budget_items bi ON b.id = bi.budget_id
            WHERE b.company_id = ?
            GROUP BY b.id
            ORDER BY b.from_date DESC
        """, (company_id,)).fetchall()
        return [dict(r) for r in rows]


def get_budget_variance_report(
    company_id: int,
    budget_id: int,
    db_path=None
) -> Optional[Dict[str, Any]]:
    """
    Generates Budget vs Actual Variance Report:
    - Analyzes actual journal debits incurred during the budget period.
    - Computes variance amount and utilization percentage.
    """
    init_budget_schema(db_path)
    with transaction(db_path) as conn:
        budget = conn.execute("SELECT * FROM budgets WHERE id = ? AND company_id = ?", (budget_id, company_id)).fetchone()
        if not budget:
            return None

        b_data = dict(budget)
        items = conn.execute("""
            SELECT bi.*, l.name as ledger_name, g.name as group_name
            FROM budget_items bi
            JOIN ledgers l ON bi.ledger_id = l.id
            JOIN ledger_groups g ON l.group_id = g.id
            WHERE bi.budget_id = ?
            ORDER BY l.name ASC
        """, (budget_id,)).fetchall()

        report_lines = []
        total_budget = 0.0
        total_actual = 0.0

        for it in items:
            lid = it['ledger_id']
            alloc_amt = float(it['allocated_amount'])
            total_budget += alloc_amt

            # Sum actual debit transactions within budget date range
            act_row = conn.execute("""
                SELECT COALESCE(SUM(amount), 0.0) as total_debit
                FROM journal_entries
                WHERE company_id = ? AND ledger_id = ? AND entry_type = 'Dr'
                  AND entry_date BETWEEN ? AND ?
            """, (company_id, lid, b_data['from_date'], b_data['to_date'])).fetchone()

            actual_amt = round(float(act_row['total_debit']), 2)
            total_actual += actual_amt

            variance = round(alloc_amt - actual_amt, 2)
            pct_used = round((actual_amt / alloc_amt * 100), 1) if alloc_amt > 0 else 0.0
            is_over = (actual_amt > alloc_amt)

            report_lines.append({
                "ledger_id": lid,
                "ledger_name": it['ledger_name'],
                "group_name": it['group_name'],
                "allocated_amount": alloc_amt,
                "actual_amount": actual_amt,
                "variance": variance,
                "percentage_used": pct_used,
                "is_over_budget": is_over,
                "status": "Over Budget" if is_over else "Within Budget"
            })

        net_variance = round(total_budget - total_actual, 2)
        total_pct = round((total_actual / total_budget * 100), 1) if total_budget > 0 else 0.0

        return {
            "budget": b_data,
            "total_budget": round(total_budget, 2),
            "total_actual": round(total_actual, 2),
            "net_variance": net_variance,
            "total_percentage_used": total_pct,
            "lines": report_lines
        }

