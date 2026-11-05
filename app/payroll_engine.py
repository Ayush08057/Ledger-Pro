"""
TallySoft Payroll Engine
Handles Employee Masters, Attendance, Pay Heads (Earnings & Deductions),
Monthly Salary Processing, Payslip Generation, and Payroll Journal Posting.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from app.database import transaction
from app.accounting_engine import post_voucher
from app.gst_invoice import number_to_words_inr


def init_payroll_schema(db_path=None):
    """
    Initializes employees, pay_heads, attendance, and payroll_vouchers tables.
    """
    with transaction(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                emp_code TEXT NOT NULL,
                name TEXT NOT NULL,
                designation TEXT,
                department TEXT,
                date_of_joining TEXT NOT NULL,
                pan_number TEXT,
                bank_account_number TEXT,
                bank_name TEXT,
                bank_ifsc TEXT,
                pf_number TEXT,
                esi_number TEXT,
                basic_salary REAL NOT NULL DEFAULT 0.0,
                hra_allowance REAL NOT NULL DEFAULT 0.0,
                conveyance_allowance REAL NOT NULL DEFAULT 0.0,
                special_allowance REAL NOT NULL DEFAULT 0.0,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
                UNIQUE(company_id, emp_code)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS payroll_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                employee_id INTEGER NOT NULL,
                pay_month TEXT NOT NULL, -- Format: YYYY-MM
                working_days REAL NOT NULL DEFAULT 30.0,
                present_days REAL NOT NULL DEFAULT 30.0,
                basic_earned REAL NOT NULL DEFAULT 0.0,
                hra_earned REAL NOT NULL DEFAULT 0.0,
                conveyance_earned REAL NOT NULL DEFAULT 0.0,
                special_earned REAL NOT NULL DEFAULT 0.0,
                gross_salary REAL NOT NULL DEFAULT 0.0,
                pf_deduction REAL NOT NULL DEFAULT 0.0,
                esi_deduction REAL NOT NULL DEFAULT 0.0,
                pt_deduction REAL NOT NULL DEFAULT 0.0,
                tds_deduction REAL NOT NULL DEFAULT 0.0,
                total_deductions REAL NOT NULL DEFAULT 0.0,
                net_salary REAL NOT NULL DEFAULT 0.0,
                voucher_id INTEGER,
                processed_date TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
                FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE,
                FOREIGN KEY (voucher_id) REFERENCES vouchers(id) ON DELETE SET NULL,
                UNIQUE(company_id, employee_id, pay_month)
            )
        """)


def create_employee(
    company_id: int,
    emp_code: str,
    name: str,
    designation: str,
    department: str,
    date_of_joining: str,
    basic_salary: float,
    hra_allowance: float = 0.0,
    conveyance_allowance: float = 0.0,
    special_allowance: float = 0.0,
    pan_number: Optional[str] = None,
    bank_account_number: Optional[str] = None,
    bank_name: Optional[str] = None,
    bank_ifsc: Optional[str] = None,
    pf_number: Optional[str] = None,
    esi_number: Optional[str] = None,
    db_path=None
) -> int:
    """
    Registers a new employee master record.
    """
    init_payroll_schema(db_path)
    with transaction(db_path) as conn:
        cursor = conn.execute("""
            INSERT INTO employees (
                company_id, emp_code, name, designation, department,
                date_of_joining, basic_salary, hra_allowance, conveyance_allowance,
                special_allowance, pan_number, bank_account_number, bank_name,
                bank_ifsc, pf_number, esi_number
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            company_id, emp_code.strip(), name.strip(), designation.strip(),
            department.strip(), date_of_joining, float(basic_salary),
            float(hra_allowance), float(conveyance_allowance), float(special_allowance),
            pan_number, bank_account_number, bank_name, bank_ifsc, pf_number, esi_number
        ))
        return cursor.lastrowid


def list_employees(company_id: int, db_path=None) -> List[Dict[str, Any]]:
    """
    Returns list of active employees for a company.
    """
    init_payroll_schema(db_path)
    with transaction(db_path) as conn:
        rows = conn.execute("""
            SELECT * FROM employees WHERE company_id = ? AND is_active = 1 ORDER BY emp_code ASC
        """, (company_id,)).fetchall()
        return [dict(r) for r in rows]


def compute_monthly_salary(
    employee: Dict[str, Any],
    working_days: float,
    present_days: float,
    tds_deduction: float = 0.0
) -> Dict[str, Any]:
    """
    Computes pro-rated earnings, statutory PF (12%), ESI (0.75%), Professional Tax (PT), and Net Pay.
    """
    ratio = (present_days / working_days) if working_days > 0 else 1.0

    basic_earned = round(employee['basic_salary'] * ratio, 2)
    hra_earned = round(employee['hra_allowance'] * ratio, 2)
    conveyance_earned = round(employee['conveyance_allowance'] * ratio, 2)
    special_earned = round(employee['special_allowance'] * ratio, 2)

    gross_salary = round(basic_earned + hra_earned + conveyance_earned + special_earned, 2)

    # PF calculation (12% of earned basic)
    pf_deduction = round(basic_earned * 0.12, 2) if employee.get('pf_number') else 0.0

    # ESI calculation (0.75% of gross if gross <= 21,000)
    esi_deduction = 0.0
    if employee.get('esi_number') and gross_salary <= 21000:
        esi_deduction = round(gross_salary * 0.0075, 2)

    # Professional Tax (standard ₹200 for gross > ₹15,000)
    pt_deduction = 200.0 if gross_salary >= 15000 else 0.0

    total_deductions = round(pf_deduction + esi_deduction + pt_deduction + float(tds_deduction), 2)
    net_salary = round(gross_salary - total_deductions, 2)

    return {
        "working_days": working_days,
        "present_days": present_days,
        "basic_earned": basic_earned,
        "hra_earned": hra_earned,
        "conveyance_earned": conveyance_earned,
        "special_earned": special_earned,
        "gross_salary": gross_salary,
        "pf_deduction": pf_deduction,
        "esi_deduction": esi_deduction,
        "pt_deduction": pt_deduction,
        "tds_deduction": float(tds_deduction),
        "total_deductions": total_deductions,
        "net_salary": net_salary
    }


def process_payroll_voucher(
    company_id: int,
    employee_id: int,
    pay_month: str,
    working_days: float,
    present_days: float,
    salary_expense_ledger_id: int,
    salary_payable_ledger_id: int,
    pf_payable_ledger_id: Optional[int] = None,
    pt_payable_ledger_id: Optional[int] = None,
    tds_deduction: float = 0.0,
    voucher_date: Optional[str] = None,
    db_path=None
) -> Dict[str, Any]:
    """
    Processes employee salary, saves payroll record, and posts balanced Double-Entry payroll journal:
    - Debit: Salary Expense A/c (Gross Salary)
    - Credit: PF Payable A/c (PF Deduction) [if any]
    - Credit: PT Payable A/c (PT Deduction) [if any]
    - Credit: Salary Payable A/c (Net Salary)
    """
    init_payroll_schema(db_path)
    with transaction(db_path) as conn:
        emp = conn.execute("SELECT * FROM employees WHERE id = ? AND company_id = ?", (employee_id, company_id)).fetchone()
        if not emp:
            raise ValueError(f"Employee {employee_id} not found")

        v_date = voucher_date or datetime.today().strftime('%Y-%m-%d')
        calc = compute_monthly_salary(dict(emp), working_days, present_days, tds_deduction)

        # Build balanced double entry journal
        journal_items = [
            {
                "ledger_id": salary_expense_ledger_id,
                "entry_type": "Dr",
                "amount": calc['gross_salary']
            }
        ]

        if calc['pf_deduction'] > 0 and pf_payable_ledger_id:
            journal_items.append({
                "ledger_id": pf_payable_ledger_id,
                "entry_type": "Cr",
                "amount": calc['pf_deduction']
            })

        if calc['pt_deduction'] > 0 and pt_payable_ledger_id:
            journal_items.append({
                "ledger_id": pt_payable_ledger_id,
                "entry_type": "Cr",
                "amount": calc['pt_deduction']
            })

        # Net Salary to Salary Payable or Employee Ledger
        journal_items.append({
            "ledger_id": salary_payable_ledger_id,
            "entry_type": "Cr",
            "amount": calc['net_salary']
        })

        # If there is any rounding difference, adjust against salary payable
        total_dr = sum(i['amount'] for i in journal_items if i['entry_type'] == 'Dr')
        total_cr = sum(i['amount'] for i in journal_items if i['entry_type'] == 'Cr')
        if round(total_dr, 2) != round(total_cr, 2):
            diff = round(total_dr - total_cr, 2)
            journal_items[-1]['amount'] = round(journal_items[-1]['amount'] + diff, 2)

        voucher_id = post_voucher(
            company_id=company_id,
            voucher_type="Journal",
            voucher_date=v_date,
            party_ledger_id=salary_payable_ledger_id,
            journal_postings=journal_items,
            narration=f"Salary for {pay_month} - {emp['name']} ({emp['emp_code']})",
            db_path=db_path
        )

        cursor = conn.execute("""
            INSERT INTO payroll_records (
                company_id, employee_id, pay_month, working_days, present_days,
                basic_earned, hra_earned, conveyance_earned, special_earned,
                gross_salary, pf_deduction, esi_deduction, pt_deduction,
                tds_deduction, total_deductions, net_salary, voucher_id, processed_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(company_id, employee_id, pay_month)
            DO UPDATE SET
                working_days = excluded.working_days,
                present_days = excluded.present_days,
                basic_earned = excluded.basic_earned,
                hra_earned = excluded.hra_earned,
                conveyance_earned = excluded.conveyance_earned,
                special_earned = excluded.special_earned,
                gross_salary = excluded.gross_salary,
                pf_deduction = excluded.pf_deduction,
                esi_deduction = excluded.esi_deduction,
                pt_deduction = excluded.pt_deduction,
                tds_deduction = excluded.tds_deduction,
                total_deductions = excluded.total_deductions,
                net_salary = excluded.net_salary,
                voucher_id = excluded.voucher_id,
                processed_date = excluded.processed_date
        """, (
            company_id, employee_id, pay_month, working_days, present_days,
            calc['basic_earned'], calc['hra_earned'], calc['conveyance_earned'], calc['special_earned'],
            calc['gross_salary'], calc['pf_deduction'], calc['esi_deduction'], calc['pt_deduction'],
            calc['tds_deduction'], calc['total_deductions'], calc['net_salary'], voucher_id, v_date
        ))

        calc['record_id'] = cursor.lastrowid
        calc['voucher_id'] = voucher_id
        calc['emp_name'] = emp['name']
        calc['emp_code'] = emp['emp_code']
        calc['net_salary_words'] = number_to_words_inr(calc['net_salary'])
        return calc


def get_payslip(payroll_record_id: int, db_path=None) -> Optional[Dict[str, Any]]:
    """
    Fetches full payslip details for rendering/printing.
    """
    init_payroll_schema(db_path)
    with transaction(db_path) as conn:
        record = conn.execute("""
            SELECT p.*, e.name as emp_name, e.emp_code, e.designation, e.department,
                   e.date_of_joining, e.pan_number, e.bank_account_number, e.bank_name,
                   e.bank_ifsc, e.pf_number, e.esi_number, c.name as company_name,
                   c.address as company_address, c.gstin as company_gstin
            FROM payroll_records p
            JOIN employees e ON p.employee_id = e.id
            JOIN companies c ON p.company_id = c.id
            WHERE p.id = ?
        """, (payroll_record_id,)).fetchone()

        if not record:
            return None

        data = dict(record)
        data['net_salary_words'] = number_to_words_inr(data['net_salary'])
        return data


def list_payroll_records(company_id: int, pay_month: Optional[str] = None, db_path=None) -> List[Dict[str, Any]]:
    """
    Lists processed payroll records for a month.
    """
    init_payroll_schema(db_path)
    with transaction(db_path) as conn:
        query = """
            SELECT p.*, e.name as emp_name, e.emp_code, e.department, e.designation
            FROM payroll_records p
            JOIN employees e ON p.employee_id = e.id
            WHERE p.company_id = ?
        """
        params = [company_id]
        if pay_month:
            query += " AND p.pay_month = ?"
            params.append(pay_month)
        query += " ORDER BY p.pay_month DESC, e.emp_code ASC"

        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
