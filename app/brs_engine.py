"""
TallySoft Bank Reconciliation Statement (BRS) Engine
Tracks book transactions, instrument numbers, bank clearance dates,
and computes reconciliation difference against bank statements.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from app.database import transaction


def init_brs_schema(db_path=None):
    """
    Initializes bank reconciliation schema safely.
    """
    with transaction(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bank_reconciliations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                journal_entry_id INTEGER NOT NULL UNIQUE,
                bank_ledger_id INTEGER NOT NULL,
                instrument_no TEXT,
                instrument_date TEXT,
                bank_date TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
                FOREIGN KEY (journal_entry_id) REFERENCES journal_entries(id) ON DELETE CASCADE,
                FOREIGN KEY (bank_ledger_id) REFERENCES ledgers(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_brs_bank ON bank_reconciliations(bank_ledger_id);")


def get_bank_ledgers(company_id: int, db_path=None) -> List[Dict[str, Any]]:
    """
    Returns ledgers under 'Bank Accounts' and 'Bank OD A/c'.
    """
    with transaction(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT l.id, l.name, g.name AS group_name, l.current_balance, l.current_balance_type
            FROM ledgers l
            JOIN ledger_groups g ON l.group_id = g.id
            WHERE l.company_id = ? AND g.name IN ('Bank Accounts', 'Bank OD A/c')
            ORDER BY l.name
        """, (company_id,))
        return [dict(r) for r in cur.fetchall()]


def get_unreconciled_transactions(company_id: int, bank_ledger_id: int, db_path=None) -> List[Dict[str, Any]]:
    """
    Returns all journal entries for a bank account with their reconciliation status.
    """
    init_brs_schema(db_path)
    with transaction(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT j.id AS journal_id, j.entry_date, j.entry_type, j.amount, j.narration,
                   v.id AS voucher_id, v.voucher_number, v.voucher_type,
                   br.instrument_no, br.instrument_date, br.bank_date,
                   COALESCE(p.name, 'Direct Transaction') AS party_name
            FROM journal_entries j
            JOIN vouchers v ON j.voucher_id = v.id
            LEFT JOIN ledgers p ON v.party_ledger_id = p.id
            LEFT JOIN bank_reconciliations br ON br.journal_entry_id = j.id
            WHERE j.company_id = ? AND j.ledger_id = ?
            ORDER BY j.entry_date ASC, j.id ASC
        """, (company_id, bank_ledger_id))
        return [dict(r) for r in cur.fetchall()]


def reconcile_transaction(
    company_id: int,
    journal_entry_id: int,
    bank_ledger_id: int,
    bank_date: str,
    instrument_no: str = "",
    db_path=None
) -> bool:
    """
    Marks a transaction as reconciled by setting its bank clearance date.
    """
    init_brs_schema(db_path)
    with transaction(db_path) as conn:
        cur = conn.cursor()
        b_date = bank_date.strip() if bank_date and bank_date.strip() else None
        cur.execute("""
            INSERT INTO bank_reconciliations (company_id, journal_entry_id, bank_ledger_id, bank_date, instrument_no)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(journal_entry_id)
            DO UPDATE SET bank_date = excluded.bank_date, instrument_no = excluded.instrument_no
        """, (company_id, journal_entry_id, bank_ledger_id, b_date, instrument_no.strip()))
        return True


def get_brs_summary(company_id: int, bank_ledger_id: int, as_on_date: str = "", db_path=None) -> Dict[str, Any]:
    """
    Computes standard Tally BRS Summary:
    1. Balance as per Company Books
    2. Amounts not reflected in Bank:
       - Uncleared Deposits (Dr entries not cleared)
       - Uncleared Cheques / Outward payments (Cr entries not cleared)
    3. Balance as per Bank Statement
    """
    init_brs_schema(db_path)
    with transaction(db_path) as conn:
        cur = conn.cursor()

        # Fetch bank ledger details
        cur.execute("SELECT name, opening_balance, opening_balance_type, current_balance, current_balance_type FROM ledgers WHERE id = ?", (bank_ledger_id,))
        bank = dict(cur.fetchone())

        # Fetch all transactions and their clearance dates
        txns = get_unreconciled_transactions(company_id, bank_ledger_id, db_path=db_path)

        book_bal = bank["current_balance"] if bank["current_balance_type"] == "Dr" else -bank["current_balance"]

        uncleared_deposits = 0.0
        uncleared_payments = 0.0

        for t in txns:
            is_cleared = bool(t.get("bank_date") and t["bank_date"].strip())
            amt = float(t["amount"])
            if not is_cleared:
                if t["entry_type"] == "Dr":  # Deposit into bank not yet cleared
                    uncleared_deposits += amt
                elif t["entry_type"] == "Cr":  # Cheque issued not yet presented
                    uncleared_payments += amt

        # Bank Statement Balance = Book Balance - Uncleared Deposits + Uncleared Payments
        bank_statement_balance = book_bal - uncleared_deposits + uncleared_payments

        return {
            "bank_name": bank["name"],
            "book_balance": round(book_bal, 2),
            "book_balance_type": "Dr" if book_bal >= 0 else "Cr",
            "uncleared_deposits": round(uncleared_deposits, 2),
            "uncleared_payments": round(uncleared_payments, 2),
            "bank_statement_balance": round(abs(bank_statement_balance), 2),
            "bank_statement_balance_type": "Dr" if bank_statement_balance >= 0 else "Cr",
            "is_reconciled": (uncleared_deposits == 0.0 and uncleared_payments == 0.0),
            "transactions": txns
        }

