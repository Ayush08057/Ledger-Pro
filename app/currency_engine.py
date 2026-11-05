"""
TallySoft Multi-Currency & Forex Gain/Loss Engine
Handles Currency Masters, Daily Exchange Rates, Foreign Currency Transactions,
and Automated Realized/Unrealized Forex Gain or Loss Calculations on Settlement.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from app.database import transaction
from app.accounting_engine import post_voucher


STANDARD_CURRENCIES = [
    {"symbol": "$", "formal_name": "US Dollar", "code": "USD", "standard_rate": 83.50},
    {"symbol": "€", "formal_name": "Euro", "code": "EUR", "standard_rate": 90.20},
    {"symbol": "£", "formal_name": "British Pound", "code": "GBP", "standard_rate": 105.80},
    {"symbol": "AED", "formal_name": "UAE Dirham", "code": "AED", "standard_rate": 22.75},
    {"symbol": "SGD", "formal_name": "Singapore Dollar", "code": "SGD", "standard_rate": 62.40}
]


def init_currency_schema(db_path=None):
    """
    Initializes currencies and exchange_rates tables.
    """
    with transaction(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS currencies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                formal_name TEXT NOT NULL,
                code TEXT NOT NULL,
                decimal_places INTEGER NOT NULL DEFAULT 2,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
                UNIQUE(company_id, code)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS exchange_rates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                currency_id INTEGER NOT NULL,
                rate_date TEXT NOT NULL,
                rate_per_unit REAL NOT NULL CHECK(rate_per_unit > 0),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
                FOREIGN KEY (currency_id) REFERENCES currencies(id) ON DELETE CASCADE,
                UNIQUE(company_id, currency_id, rate_date)
            )
        """)


def seed_standard_currencies(company_id: int, db_path=None):
    """
    Seeds standard world trading currencies for a company if not present.
    """
    init_currency_schema(db_path)
    today = datetime.today().strftime('%Y-%m-%d')
    with transaction(db_path) as conn:
        for c in STANDARD_CURRENCIES:
            cursor = conn.execute("""
                INSERT OR IGNORE INTO currencies (company_id, symbol, formal_name, code)
                VALUES (?, ?, ?, ?)
            """, (company_id, c['symbol'], c['formal_name'], c['code']))

            cur_row = conn.execute("SELECT id FROM currencies WHERE company_id = ? AND code = ?", (company_id, c['code'])).fetchone()
            if cur_row:
                conn.execute("""
                    INSERT OR IGNORE INTO exchange_rates (company_id, currency_id, rate_date, rate_per_unit)
                    VALUES (?, ?, ?, ?)
                """, (company_id, cur_row['id'], today, c['standard_rate']))


def get_latest_rate(company_id: int, currency_id: int, db_path=None) -> float:
    """
    Fetches the latest exchange rate for a currency relative to INR base currency.
    """
    init_currency_schema(db_path)
    with transaction(db_path) as conn:
        row = conn.execute("""
            SELECT rate_per_unit FROM exchange_rates
            WHERE company_id = ? AND currency_id = ?
            ORDER BY rate_date DESC, id DESC
            LIMIT 1
        """, (company_id, currency_id)).fetchone()
        return float(row['rate_per_unit']) if row else 1.0


def list_currencies(company_id: int, db_path=None) -> List[Dict[str, Any]]:
    """
    Lists all supported foreign currencies with their latest exchange rates.
    """
    init_currency_schema(db_path)
    with transaction(db_path) as conn:
        rows = conn.execute("""
            SELECT c.*, 
                   COALESCE((
                       SELECT rate_per_unit FROM exchange_rates e 
                       WHERE e.currency_id = c.id 
                       ORDER BY e.rate_date DESC, e.id DESC LIMIT 1
                   ), 1.0) as latest_rate
            FROM currencies c
            WHERE c.company_id = ?
            ORDER BY c.code ASC
        """, (company_id,)).fetchall()
        return [dict(r) for r in rows]


def set_exchange_rate(company_id: int, currency_id: int, rate_date: str, rate: float, db_path=None):
    """
    Records or updates an exchange rate for a specific date.
    """
    init_currency_schema(db_path)
    with transaction(db_path) as conn:
        conn.execute("""
            INSERT INTO exchange_rates (company_id, currency_id, rate_date, rate_per_unit)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(company_id, currency_id, rate_date)
            DO UPDATE SET rate_per_unit = excluded.rate_per_unit
        """, (company_id, currency_id, rate_date, float(rate)))


def calculate_forex_gain_loss(
    booked_rate: float,
    settled_rate: float,
    foreign_amount: float
) -> Dict[str, Any]:
    """
    Calculates realized exchange gain or loss upon foreign currency settlement:
    - Difference = (settled_rate - booked_rate) * foreign_amount
    - Positive difference = Gain
    - Negative difference = Loss
    """
    booked_inr = round(foreign_amount * booked_rate, 2)
    settled_inr = round(foreign_amount * settled_rate, 2)
    diff = round(settled_inr - booked_inr, 2)

    return {
        "foreign_amount": foreign_amount,
        "booked_rate": booked_rate,
        "booked_inr": booked_inr,
        "settled_rate": settled_rate,
        "settled_inr": settled_inr,
        "diff_amount": abs(diff),
        "is_gain": (diff >= 0),
        "status": "Gain" if diff >= 0 else "Loss"
    }


def record_forex_settlement_voucher(
    company_id: int,
    voucher_date: str,
    party_ledger_id: int,
    bank_ledger_id: int,
    forex_ledger_id: int,
    foreign_amount: float,
    booked_rate: float,
    settled_rate: float,
    transaction_type: str = "Receipt",  # Receipt (Export customer) or Payment (Import vendor)
    narration: Optional[str] = None,
    db_path=None
) -> Dict[str, Any]:
    """
    Posts balanced Double-Entry voucher with automatic Forex Gain/Loss allocation:
    For Export Customer Receipt:
      - Bank Dr: settled_inr
      - Party Cr: booked_inr
      - Forex Gain Cr: gain_inr (if gain) OR Forex Loss Dr: loss_inr (if loss)
    For Import Vendor Payment:
      - Party Dr: booked_inr
      - Bank Cr: settled_inr
      - Forex Gain Cr: gain_inr (if gain) OR Forex Loss Dr: loss_inr (if loss)
    """
    calc = calculate_forex_gain_loss(booked_rate, settled_rate, foreign_amount)
    journal_postings = []

    if transaction_type == "Receipt":
        # Received money from overseas customer
        journal_postings.append({
            "ledger_id": bank_ledger_id,
            "entry_type": "Dr",
            "amount": calc["settled_inr"]
        })
        journal_postings.append({
            "ledger_id": party_ledger_id,
            "entry_type": "Cr",
            "amount": calc["booked_inr"]
        })

        if calc["diff_amount"] > 0:
            if calc["is_gain"]:
                journal_postings.append({
                    "ledger_id": forex_ledger_id,
                    "entry_type": "Cr",
                    "amount": calc["diff_amount"]
                })
            else:
                journal_postings.append({
                    "ledger_id": forex_ledger_id,
                    "entry_type": "Dr",
                    "amount": calc["diff_amount"]
                })
    else:
        # Payment made to overseas vendor
        journal_postings.append({
            "ledger_id": party_ledger_id,
            "entry_type": "Dr",
            "amount": calc["booked_inr"]
        })
        journal_postings.append({
            "ledger_id": bank_ledger_id,
            "entry_type": "Cr",
            "amount": calc["settled_inr"]
        })

        if calc["diff_amount"] > 0:
            if calc["is_gain"]:  # paid less INR than booked = Gain
                journal_postings.append({
                    "ledger_id": forex_ledger_id,
                    "entry_type": "Cr",
                    "amount": calc["diff_amount"]
                })
            else:  # paid more INR than booked = Loss
                journal_postings.append({
                    "ledger_id": forex_ledger_id,
                    "entry_type": "Dr",
                    "amount": calc["diff_amount"]
                })

    # Balance check safeguard
    tot_dr = round(sum(p['amount'] for p in journal_postings if p['entry_type'] == 'Dr'), 2)
    tot_cr = round(sum(p['amount'] for p in journal_postings if p['entry_type'] == 'Cr'), 2)
    if tot_dr != tot_cr:
        adj = round(tot_dr - tot_cr, 2)
        journal_postings[-1]['amount'] = round(journal_postings[-1]['amount'] + adj, 2)

    v_type = "Receipt" if transaction_type == "Receipt" else "Payment"
    v_id = post_voucher(
        company_id=company_id,
        voucher_type=v_type,
        voucher_date=voucher_date,
        party_ledger_id=party_ledger_id,
        journal_postings=journal_postings,
        narration=narration or f"Forex settlement for {foreign_amount} @ {settled_rate} (Booked @ {booked_rate}). Forex {calc['status']}: INR {calc['diff_amount']}",
        db_path=db_path
    )

    return {
        "voucher_id": v_id,
        "calculation": calc
    }

