"""
Unit tests for Financial Budgets & Variance Analysis Engine
"""

import unittest
import tempfile
from pathlib import Path
from app.database import init_db, create_company, get_connection
from app.accounting_engine import post_voucher
from app.budget_engine import (
    init_budget_schema,
    create_budget,
    list_budgets,
    get_budget_variance_report
)


class TestBudget(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db = Path(self.temp_dir.name) / "test_budget.db"
        init_db(self.test_db)
        init_budget_schema(self.test_db)

        self.company_id = create_company(
            name="Horizon Enterprises Ltd",
            state="Maharashtra",
            state_code="27",
            db_path=self.test_db
        )

        conn = get_connection(self.test_db)
        cur = conn.cursor()

        # Find Groups
        cur.execute("SELECT id FROM ledger_groups WHERE company_id = ? AND name = 'Indirect Expenses'", (self.company_id,))
        grp_exp = cur.fetchone()[0]

        cur.execute("SELECT id FROM ledgers WHERE company_id = ? AND name = 'Cash'", (self.company_id,))
        self.cash_id = cur.fetchone()[0]

        # Create expense ledgers
        cur.execute("INSERT INTO ledgers (company_id, group_id, name) VALUES (?, ?, 'Marketing & Promotion A/c')", (self.company_id, grp_exp))
        self.exp_mktg = cur.lastrowid

        cur.execute("INSERT INTO ledgers (company_id, group_id, name) VALUES (?, ?, 'Office Rent & Rates A/c')", (self.company_id, grp_exp))
        self.exp_rent = cur.lastrowid

        conn.commit()
        conn.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_01_budget_creation_and_variance(self):
        # 1. Create a 6-month budget
        # Marketing: ₹50,000 budget
        # Rent: ₹100,000 budget
        b_id = create_budget(
            company_id=self.company_id,
            name="H2 Operating Budget",
            from_date="2026-10-01",
            to_date="2027-03-31",
            allocations=[
                {"ledger_id": self.exp_mktg, "allocated_amount": 50000.0},
                {"ledger_id": self.exp_rent, "allocated_amount": 100000.0}
            ],
            db_path=self.test_db
        )
        self.assertIsNotNone(b_id)

        # 2. Incur actual expenses via Payment vouchers
        # Spent ₹40,000 on Marketing (within budget)
        post_voucher(
            company_id=self.company_id,
            voucher_type="Payment",
            voucher_date="2026-11-03",
            party_ledger_id=self.cash_id,
            journal_postings=[
                {"ledger_id": self.exp_mktg, "entry_type": "Dr", "amount": 40000.0},
                {"ledger_id": self.cash_id, "entry_type": "Cr", "amount": 40000.0}
            ],
            db_path=self.test_db
        )

        # Spent ₹120,000 on Rent (exceeded budget by ₹20,000)
        post_voucher(
            company_id=self.company_id,
            voucher_type="Payment",
            voucher_date="2026-11-03",
            party_ledger_id=self.cash_id,
            journal_postings=[
                {"ledger_id": self.exp_rent, "entry_type": "Dr", "amount": 120000.0},
                {"ledger_id": self.cash_id, "entry_type": "Cr", "amount": 120000.0}
            ],
            db_path=self.test_db
        )

        # 3. Check Variance Report
        rep = get_budget_variance_report(self.company_id, b_id, self.test_db)
        self.assertIsNotNone(rep)
        self.assertEqual(rep['total_budget'], 150000.0)
        self.assertEqual(rep['total_actual'], 160000.0)
        self.assertEqual(rep['net_variance'], -10000.0)  # Spent 10k over total budget

        mktg_line = next(l for l in rep['lines'] if l['ledger_id'] == self.exp_mktg)
        self.assertEqual(mktg_line['allocated_amount'], 50000.0)
        self.assertEqual(mktg_line['actual_amount'], 40000.0)
        self.assertEqual(mktg_line['variance'], 10000.0)
        self.assertEqual(mktg_line['status'], "Within Budget")

        rent_line = next(l for l in rep['lines'] if l['ledger_id'] == self.exp_rent)
        self.assertEqual(rent_line['allocated_amount'], 100000.0)
        self.assertEqual(rent_line['actual_amount'], 120000.0)
        self.assertEqual(rent_line['variance'], -20000.0)
        self.assertEqual(rent_line['status'], "Over Budget")

        # 4. Check budget list
        budgets = list_budgets(self.company_id, self.test_db)
        self.assertEqual(len(budgets), 1)
        self.assertEqual(budgets[0]['name'], "H2 Operating Budget")


if __name__ == "__main__":
    unittest.main()

