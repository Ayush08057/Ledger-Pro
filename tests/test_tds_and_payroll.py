"""
Unit tests for TDS / TCS Statutory Engine and Payroll System
"""

import unittest
import tempfile
from pathlib import Path
from app.database import init_db, create_company, get_connection
from app.tds_tcs_engine import (
    init_tds_schema,
    calculate_tds,
    record_tds_expense_voucher,
    get_form_26q_report
)
from app.payroll_engine import (
    init_payroll_schema,
    create_employee,
    list_employees,
    compute_monthly_salary,
    process_payroll_voucher,
    get_payslip,
    list_payroll_records
)


class TestTDSAndPayroll(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db = Path(self.temp_dir.name) / "test_tds_payroll.db"
        init_db(self.test_db)
        init_tds_schema(self.test_db)
        init_payroll_schema(self.test_db)

        self.company_id = create_company(
            name="Bharat Enterprises Ltd",
            state="Maharashtra",
            state_code="27",
            db_path=self.test_db
        )

        conn = get_connection(self.test_db)
        cursor = conn.cursor()

        # Look up groups
        grp_indir_exp = conn.execute("SELECT id FROM ledger_groups WHERE company_id = ? AND name = 'Indirect Expenses'", (self.company_id,)).fetchone()[0]
        grp_sundry_cred = conn.execute("SELECT id FROM ledger_groups WHERE company_id = ? AND name = 'Sundry Creditors'", (self.company_id,)).fetchone()[0]
        grp_curr_liab = conn.execute("SELECT id FROM ledger_groups WHERE company_id = ? AND name = 'Current Liabilities'", (self.company_id,)).fetchone()[0]
        grp_duties = conn.execute("SELECT id FROM ledger_groups WHERE company_id = ? AND name = 'Duties & Taxes'", (self.company_id,)).fetchone()[0]

        # Create Ledgers for TDS
        cursor.execute("INSERT INTO ledgers (company_id, group_id, name) VALUES (?, ?, 'Legal & Professional Charges')", (self.company_id, grp_indir_exp))
        self.exp_legal = cursor.lastrowid

        cursor.execute("INSERT INTO ledgers (company_id, group_id, name, pan) VALUES (?, ?, 'Sharma & Associates', 'AAACS1234F')", (self.company_id, grp_sundry_cred))
        self.party_lawyer = cursor.lastrowid

        cursor.execute("INSERT INTO ledgers (company_id, group_id, name) VALUES (?, ?, 'TDS Payable u/s 194J')", (self.company_id, grp_duties))
        self.tds_194j = cursor.lastrowid

        # Create Ledgers for Payroll
        cursor.execute("INSERT INTO ledgers (company_id, group_id, name) VALUES (?, ?, 'Salaries & Wages A/c')", (self.company_id, grp_indir_exp))
        self.salary_exp = cursor.lastrowid

        cursor.execute("INSERT INTO ledgers (company_id, group_id, name) VALUES (?, ?, 'Salary Payable A/c')", (self.company_id, grp_curr_liab))
        self.salary_payable = cursor.lastrowid

        cursor.execute("INSERT INTO ledgers (company_id, group_id, name) VALUES (?, ?, 'PF Payable A/c')", (self.company_id, grp_duties))
        self.pf_payable = cursor.lastrowid

        cursor.execute("INSERT INTO ledgers (company_id, group_id, name) VALUES (?, ?, 'Professional Tax Payable A/c')", (self.company_id, grp_duties))
        self.pt_payable = cursor.lastrowid

        conn.commit()
        conn.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_01_tds_calculation_and_voucher(self):
        # 1. Test standard 194J calculation (10%)
        calc = calculate_tds(100000.0, "194J", "Company", has_pan=True)
        self.assertEqual(calc['tds_rate'], 10.0)
        self.assertEqual(calc['tds_amount'], 10000.0)
        self.assertEqual(calc['net_amount'], 90000.0)

        # 2. Test higher deduction without PAN (206AA -> 20%)
        calc_nopan = calculate_tds(50000.0, "194C", "Individual", has_pan=False)
        self.assertEqual(calc_nopan['tds_rate'], 20.0)
        self.assertEqual(calc_nopan['tds_amount'], 10000.0)

        # 3. Post TDS voucher
        res = record_tds_expense_voucher(
            company_id=self.company_id,
            voucher_date="2026-11-03",
            expense_ledger_id=self.exp_legal,
            party_ledger_id=self.party_lawyer,
            tds_ledger_id=self.tds_194j,
            gross_amount=100000.0,
            section_code="194J",
            deductee_type="Company",
            narration="Legal retainer fee for Nov 2026",
            db_path=self.test_db
        )
        self.assertIsNotNone(res['voucher_id'])
        self.assertEqual(res['gross_amount'], 100000.0)
        self.assertEqual(res['tds_amount'], 10000.0)
        self.assertEqual(res['net_amount'], 90000.0)

        # 4. Verify Form 26Q report
        rep = get_form_26q_report(self.company_id, db_path=self.test_db)
        self.assertEqual(rep['total_gross'], 100000.0)
        self.assertEqual(rep['total_tds'], 10000.0)
        self.assertEqual(len(rep['entries']), 1)
        self.assertEqual(rep['entries'][0]['section_code'], "194J")

    def test_02_payroll_workflow(self):
        # 1. Register employee
        emp_id = create_employee(
            company_id=self.company_id,
            emp_code="EMP-101",
            name="Rahul Sharma",
            designation="Senior Accountant",
            department="Finance",
            date_of_joining="2024-04-01",
            basic_salary=40000.0,
            hra_allowance=15000.0,
            conveyance_allowance=3000.0,
            special_allowance=2000.0,
            pan_number="ABCDE1234F",
            bank_account_number="987654321012",
            bank_name="HDFC Bank",
            bank_ifsc="HDFC0001234",
            pf_number="MH/BAN/0012345/101",
            db_path=self.test_db
        )
        self.assertIsNotNone(emp_id)

        # 2. Check employee list
        emps = list_employees(self.company_id, self.test_db)
        self.assertEqual(len(emps), 1)
        self.assertEqual(emps[0]['emp_code'], "EMP-101")

        # 3. Process Monthly Payroll for 30 days present out of 30
        res = process_payroll_voucher(
            company_id=self.company_id,
            employee_id=emp_id,
            pay_month="2026-11",
            working_days=30.0,
            present_days=30.0,
            salary_expense_ledger_id=self.salary_exp,
            salary_payable_ledger_id=self.salary_payable,
            pf_payable_ledger_id=self.pf_payable,
            pt_payable_ledger_id=self.pt_payable,
            db_path=self.test_db
        )

        # Gross: 40k + 15k + 3k + 2k = 60,000
        # PF: 12% of 40,000 = 4,800
        # PT: 200 (since gross >= 15,000)
        # Total Deductions: 5,000
        # Net Salary: 55,000
        self.assertEqual(res['gross_salary'], 60000.0)
        self.assertEqual(res['pf_deduction'], 4800.0)
        self.assertEqual(res['pt_deduction'], 200.0)
        self.assertEqual(res['total_deductions'], 5000.0)
        self.assertEqual(res['net_salary'], 55000.0)
        self.assertIn("Fifty Five Thousand", res['net_salary_words'])

        # 4. Verify Payslip fetch
        slip = get_payslip(res['record_id'], self.test_db)
        self.assertIsNotNone(slip)
        self.assertEqual(slip['emp_name'], "Rahul Sharma")
        self.assertEqual(slip['net_salary'], 55000.0)

        # 5. Verify records list
        records = list_payroll_records(self.company_id, "2026-11", self.test_db)
        self.assertEqual(len(records), 1)


if __name__ == "__main__":
    unittest.main()
