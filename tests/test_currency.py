"""
Unit tests for Multi-Currency & Forex Gain/Loss Engine
"""

import unittest
import tempfile
from pathlib import Path
from app.database import init_db, create_company, get_connection
from app.currency_engine import (
    init_currency_schema,
    seed_standard_currencies,
    list_currencies,
    get_latest_rate,
    set_exchange_rate,
    calculate_forex_gain_loss,
    record_forex_settlement_voucher
)


class TestMultiCurrency(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db = Path(self.temp_dir.name) / "test_currency.db"
        init_db(self.test_db)
        init_currency_schema(self.test_db)

        self.company_id = create_company(
            name="Global Exports Pvt Ltd",
            state="Maharashtra",
            state_code="27",
            db_path=self.test_db
        )

        conn = get_connection(self.test_db)
        cur = conn.cursor()

        # Look up groups
        cur.execute("SELECT id FROM ledger_groups WHERE company_id = ? AND name = 'Sundry Debtors'", (self.company_id,))
        grp_debtors = cur.fetchone()[0]

        cur.execute("SELECT id FROM ledger_groups WHERE company_id = ? AND name = 'Bank Accounts'", (self.company_id,))
        grp_bank = cur.fetchone()[0]

        cur.execute("SELECT id FROM ledger_groups WHERE company_id = ? AND name = 'Indirect Incomes'", (self.company_id,))
        grp_income = cur.fetchone()[0]

        # Create ledgers
        cur.execute("INSERT INTO ledgers (company_id, group_id, name) VALUES (?, ?, 'Global Tech LLC USA')", (self.company_id, grp_debtors))
        self.party_id = cur.lastrowid

        cur.execute("INSERT INTO ledgers (company_id, group_id, name) VALUES (?, ?, 'Citibank Foreign Exchange A/c')", (self.company_id, grp_bank))
        self.bank_id = cur.lastrowid

        cur.execute("INSERT INTO ledgers (company_id, group_id, name) VALUES (?, ?, 'Forex Exchange Gain/Loss A/c')", (self.company_id, grp_income))
        self.forex_id = cur.lastrowid

        conn.commit()
        conn.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_01_currency_rates_and_seeding(self):
        seed_standard_currencies(self.company_id, self.test_db)
        currs = list_currencies(self.company_id, self.test_db)
        self.assertGreaterEqual(len(currs), 5)

        usd = next(c for c in currs if c['code'] == 'USD')
        self.assertEqual(usd['symbol'], '$')
        self.assertEqual(usd['latest_rate'], 83.50)

        # Update rate for latest date
        from datetime import datetime, timedelta
        next_date = (datetime.today() + timedelta(days=1)).strftime('%Y-%m-%d')
        set_exchange_rate(self.company_id, usd['id'], next_date, 84.20, self.test_db)
        new_rate = get_latest_rate(self.company_id, usd['id'], self.test_db)
        self.assertEqual(new_rate, 84.20)

    def test_02_forex_gain_settlement_receipt(self):
        # Scenario: Export invoice was $1,000 booked at 83.50 (= INR 83,500)
        # Payment received when USD rate is 84.50 (= INR 84,500)
        # Realized Gain = INR 1,000
        calc = calculate_forex_gain_loss(booked_rate=83.50, settled_rate=84.50, foreign_amount=1000.0)
        self.assertTrue(calc['is_gain'])
        self.assertEqual(calc['diff_amount'], 1000.0)
        self.assertEqual(calc['booked_inr'], 83500.0)
        self.assertEqual(calc['settled_inr'], 84500.0)

        res = record_forex_settlement_voucher(
            company_id=self.company_id,
            voucher_date="2026-11-03",
            party_ledger_id=self.party_id,
            bank_ledger_id=self.bank_id,
            forex_ledger_id=self.forex_id,
            foreign_amount=1000.0,
            booked_rate=83.50,
            settled_rate=84.50,
            transaction_type="Receipt",
            db_path=self.test_db
        )
        self.assertIsNotNone(res['voucher_id'])

        # Check that bank received 84,500 Dr
        conn = get_connection(self.test_db)
        bank_led = conn.execute("SELECT current_balance, current_balance_type FROM ledgers WHERE id = ?", (self.bank_id,)).fetchone()
        self.assertEqual(bank_led['current_balance'], 84500.0)
        self.assertEqual(bank_led['current_balance_type'], 'Dr')
        conn.close()


if __name__ == "__main__":
    unittest.main()

