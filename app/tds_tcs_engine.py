"""
TallySoft Statutory TDS / TCS Engine
Handles Tax Deducted at Source (TDS) and Tax Collected at Source (TCS) calculations,
statutory ledger allocations, and Form 26Q return preparation.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from app.database import transaction
from app.accounting_engine import post_voucher


STANDARD_TDS_SECTIONS = [
    {
        "section_code": "194C",
        "description": "Payments to Contractors & Sub-contractors",
        "rate_individual": 1.0,
        "rate_others": 2.0,
        "threshold": 30000.0,
        "annual_threshold": 100000.0
    },
    {
        "section_code": "194J",
        "description": "Fees for Professional or Technical Services",
        "rate_individual": 10.0,
        "rate_others": 10.0,
        "threshold": 30000.0,
        "annual_threshold": 30000.0
    },
    {
        "section_code": "194I_BUILDING",
        "description": "Rent of Land, Building or Furniture",
        "rate_individual": 10.0,
        "rate_others": 10.0,
        "threshold": 240000.0,
        "annual_threshold": 240000.0
    },
    {
        "section_code": "194I_PLANT",
        "description": "Rent of Plant, Machinery or Equipment",
        "rate_individual": 2.0,
        "rate_others": 2.0,
        "threshold": 240000.0,
        "annual_threshold": 240000.0
    },
    {
        "section_code": "194H",
        "description": "Commission or Brokerage",
        "rate_individual": 5.0,
        "rate_others": 5.0,
        "threshold": 15000.0,
        "annual_threshold": 15000.0
    },
    {
        "section_code": "206C",
        "description": "TCS on Sale of Goods / Scrap",
        "rate_individual": 1.0,
        "rate_others": 1.0,
        "threshold": 0.0,
        "annual_threshold": 0.0
    }
]


def init_tds_schema(db_path=None):
    """
    Initializes TDS nature of payments, deductee entries, and challans tables.
    """
    with transaction(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tds_sections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                section_code TEXT NOT NULL UNIQUE,
                description TEXT NOT NULL,
                rate_individual REAL NOT NULL,
                rate_others REAL NOT NULL,
                threshold REAL NOT NULL DEFAULT 0.0,
                annual_threshold REAL NOT NULL DEFAULT 0.0
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS tds_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                voucher_id INTEGER,
                section_code TEXT NOT NULL,
                deductee_ledger_id INTEGER NOT NULL,
                pan_number TEXT,
                booking_date TEXT NOT NULL,
                gross_amount REAL NOT NULL,
                tds_rate REAL NOT NULL,
                tds_amount REAL NOT NULL,
                net_amount REAL NOT NULL,
                challan_number TEXT,
                challan_date TEXT,
                is_deposited INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
                FOREIGN KEY (voucher_id) REFERENCES vouchers(id) ON DELETE SET NULL,
                FOREIGN KEY (deductee_ledger_id) REFERENCES ledgers(id) ON DELETE RESTRICT
            )
        """)

        # Seed standard sections if empty
        count = conn.execute("SELECT COUNT(*) as cnt FROM tds_sections").fetchone()['cnt']
        if count == 0:
            for s in STANDARD_TDS_SECTIONS:
                conn.execute("""
                    INSERT OR IGNORE INTO tds_sections (section_code, description, rate_individual, rate_others, threshold, annual_threshold)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (s['section_code'], s['description'], s['rate_individual'], s['rate_others'], s['threshold'], s['annual_threshold']))


def calculate_tds(
    gross_amount: float,
    section_code: str,
    deductee_type: str = "Company",
    has_pan: bool = True
) -> Dict[str, Any]:
    """
    Calculates applicable TDS amount according to statutory rate or Higher Deduction (20% if no PAN).
    """
    if not has_pan:
        # Statutory 206AA: Rate is higher of statutory rate or 20%
        rate = 20.0
    else:
        # Match section
        sec = next((s for s in STANDARD_TDS_SECTIONS if s['section_code'] == section_code), None)
        if not sec:
            rate = 10.0
        elif deductee_type.lower() in ("individual", "huf"):
            rate = sec['rate_individual']
        else:
            rate = sec['rate_others']

    tds_amount = round((gross_amount * rate) / 100.0, 2)
    net_amount = round(gross_amount - tds_amount, 2)
    return {
        "section_code": section_code,
        "gross_amount": gross_amount,
        "tds_rate": rate,
        "tds_amount": tds_amount,
        "net_amount": net_amount
    }


def record_tds_expense_voucher(
    company_id: int,
    voucher_date: str,
    expense_ledger_id: int,
    party_ledger_id: int,
    tds_ledger_id: int,
    gross_amount: float,
    section_code: str,
    deductee_type: str = "Company",
    narration: Optional[str] = None,
    db_path=None
) -> Dict[str, Any]:
    """
    Posts a complete balanced Double-Entry voucher with TDS deduction:
    - Debit: Expense Ledger (Gross Amount)
    - Credit: Party Ledger (Net Amount)
    - Credit: TDS Payable Ledger (TDS Amount)
    Also records statutory entry for Form 26Q reporting.
    """
    init_tds_schema(db_path)
    with transaction(db_path) as conn:
        # Check Party PAN
        party = conn.execute("SELECT name, pan FROM ledgers WHERE id = ?", (party_ledger_id,)).fetchone()
        pan = party['pan'] if party and party['pan'] else ""
        has_pan = bool(pan and len(pan.strip()) == 10)

        calc = calculate_tds(gross_amount, section_code, deductee_type, has_pan)

        # Journal Entry Items for Double Entry balance
        journal_items = [
            {
                "ledger_id": expense_ledger_id,
                "entry_type": "Dr",
                "amount": calc['gross_amount']
            },
            {
                "ledger_id": party_ledger_id,
                "entry_type": "Cr",
                "amount": calc['net_amount']
            },
            {
                "ledger_id": tds_ledger_id,
                "entry_type": "Cr",
                "amount": calc['tds_amount']
            }
        ]

        # Post balanced accounting voucher
        voucher_id = post_voucher(
            company_id=company_id,
            voucher_type="Journal",
            voucher_date=voucher_date,
            party_ledger_id=party_ledger_id,
            journal_postings=journal_items,
            narration=narration or f"TDS deduction u/s {section_code} @ {calc['tds_rate']}% on {party['name'] if party else 'Party'}",
            db_path=db_path
        )

        # Record TDS entry for 26Q
        conn.execute("""
            INSERT INTO tds_entries (
                company_id, voucher_id, section_code, deductee_ledger_id,
                pan_number, booking_date, gross_amount, tds_rate, tds_amount, net_amount
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            company_id, voucher_id, section_code, party_ledger_id,
            pan, voucher_date, calc['gross_amount'], calc['tds_rate'],
            calc['tds_amount'], calc['net_amount']
        ))

        return {
            "voucher_id": voucher_id,
            "section_code": section_code,
            "gross_amount": calc['gross_amount'],
            "tds_rate": calc['tds_rate'],
            "tds_amount": calc['tds_amount'],
            "net_amount": calc['net_amount'],
            "pan": pan
        }


def get_form_26q_report(company_id: int, from_date: str = "2000-01-01", to_date: str = "2099-12-31", db_path=None) -> Dict[str, Any]:
    """
    Generates Form 26Q TDS Return Summary:
    - Section-wise aggregation
    - Deductee-wise transaction details
    - Total Gross Amount, Total TDS Deducted, Total Deposited
    """
    init_tds_schema(db_path)
    with transaction(db_path) as conn:
        entries = conn.execute("""
            SELECT t.*, l.name as deductee_name, v.voucher_number
            FROM tds_entries t
            JOIN ledgers l ON t.deductee_ledger_id = l.id
            LEFT JOIN vouchers v ON t.voucher_id = v.id
            WHERE t.company_id = ? AND t.booking_date BETWEEN ? AND ?
            ORDER BY t.booking_date DESC, t.id DESC
        """, (company_id, from_date, to_date)).fetchall()

        entries_list = [dict(e) for e in entries]

        # Section-wise aggregation
        summary_by_section = {}
        total_gross = 0.0
        total_tds = 0.0

        for e in entries_list:
            sec = e['section_code']
            if sec not in summary_by_section:
                summary_by_section[sec] = {
                    "section_code": sec,
                    "count": 0,
                    "gross_amount": 0.0,
                    "tds_amount": 0.0
                }
            summary_by_section[sec]['count'] += 1
            summary_by_section[sec]['gross_amount'] = round(summary_by_section[sec]['gross_amount'] + e['gross_amount'], 2)
            summary_by_section[sec]['tds_amount'] = round(summary_by_section[sec]['tds_amount'] + e['tds_amount'], 2)
            total_gross += e['gross_amount']
            total_tds += e['tds_amount']

        return {
            "from_date": from_date,
            "to_date": to_date,
            "total_gross": round(total_gross, 2),
            "total_tds": round(total_tds, 2),
            "section_summary": list(summary_by_section.values()),
            "entries": entries_list
        }
