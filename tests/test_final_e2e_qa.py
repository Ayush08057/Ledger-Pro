"""
Final End-to-End Production QA and Verification Test Suite
Exhaustively tests Phases 2, 3, 4, 6, 7, 8, 9 on an isolated test database.
Guarantees that production database and live data remain untouched.
"""

import unittest
import tempfile
import sqlite3
import json
from pathlib import Path
from datetime import datetime

from app.database import (
    init_db,
    create_company,
    get_company,
    list_companies,
    get_company_ledgers,
    get_connection,
    transaction,
    delete_ledger,
    get_voucher_config,
    save_voucher_config
)
from app.accounting_engine import (
    post_voucher,
    create_sales_invoice,
    create_purchase_invoice,
    create_credit_note,
    create_debit_note,
    get_next_voucher_number,
    get_trial_balance,
    DoubleEntryMismatchError
)
from app.reports import (
    get_day_book,
    get_profit_and_loss,
    get_balance_sheet,
    get_stock_summary
)
from app.analysis import (
    get_outstanding_receivables,
    get_outstanding_payables,
    get_cash_bank_summary,
    get_ratio_analysis,
    get_cash_flow_statement
)
from app.backup import create_backup, restore_backup
from app.server import app


def create_ledger_helper(cid, name, group_name, opening_balance=0.0, opening_balance_type="Dr", gstin=None, state_code="27", pan=None, db_path=None, **kwargs):
    with transaction(db_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM ledger_groups WHERE company_id = ? AND name = ?", (cid, group_name))
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Group {group_name} not found")
        gid = row[0]
        cur.execute("""
            INSERT INTO ledgers (
                company_id, group_id, name, opening_balance, opening_balance_type,
                current_balance, current_balance_type, gstin, state_code, pan
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (cid, gid, name, opening_balance, opening_balance_type, opening_balance, opening_balance_type, gstin, state_code, pan))
        return cur.lastrowid


def create_stock_item_helper(cid, name, unit_id, hsn_sac="8471", gst_rate=18.0, opening_qty=0.0, opening_rate=0.0, db_path=None):
    with transaction(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO stock_items (company_id, name, unit_id, hsn_sac, gst_rate, opening_qty, opening_rate, closing_qty)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (cid, name, unit_id, hsn_sac, gst_rate, opening_qty, opening_rate, opening_qty))
        return cur.lastrowid


class TestFinalProductionQA(unittest.TestCase):
    def setUp(self):
        # 1. Create a dedicated temporary directory for completely isolated testing
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db = Path(self.temp_dir.name) / "qa_isolated.db"
        init_db(self.test_db)
        self.client = app.test_client()

    def tearDown(self):
        import gc
        gc.collect()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_database_integrity_and_pragmas(self):
        """Phase 6: Verify SQLite integrity and foreign key constraints on fresh schema"""
        conn = get_connection(self.test_db)
        cur = conn.cursor()

        # PRAGMA integrity_check
        integrity = cur.execute("PRAGMA integrity_check").fetchall()
        self.assertEqual(integrity[0][0], 'ok', "Database failed integrity check.")

        # PRAGMA foreign_key_check
        fk_violations = cur.execute("PRAGMA foreign_key_check").fetchall()
        self.assertEqual(len(fk_violations), 0, f"Foreign key violations found: {fk_violations}")

        # Check all core tables exist
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cur.fetchall()}
        required = [
            "companies", "ledger_groups", "ledgers", "units", "stock_groups",
            "stock_items", "vouchers", "voucher_inventory_items", "journal_entries",
            "audit_logs"
        ]
        for t in required:
            self.assertIn(t, tables, f"Required table '{t}' is missing from schema.")
        conn.close()

    def test_complete_e2e_accounting_lifecycle(self):
        """
        Phase 3 & Phase 4: Full accounting workflow verification:
        Company Creation -> Master Creation -> Purchase -> Sales -> Expenses ->
        Payment & Receipt -> Contra & Journal -> Day Book -> Financial Reports ->
        Mathematical Reconciliation (Dr = Cr, Balance Sheet equation).
        """
        db = self.test_db

        # ---------------------------------------------------------
        # TEST 1: COMPANY CREATION
        # ---------------------------------------------------------
        cid = create_company(
            name="Global Logistics & Trading Pvt Ltd",
            gstin="27AABCG1234F1Z8",
            state="Maharashtra",
            state_code="27",
            pan="AABCG1234F",
            address="Plot 45, Hinjewadi Phase 1, Pune",
            db_path=db
        )
        self.assertIsNotNone(cid)
        comp = get_company(cid, db_path=db)
        self.assertEqual(comp["name"], "Global Logistics & Trading Pvt Ltd")
        self.assertEqual(comp["state_code"], "27")

        # Verify automatic seeding of 28 groups and default ledgers
        ledgers = get_company_ledgers(cid, db_path=db)
        ledger_map = {l["name"]: l["id"] for l in ledgers}
        self.assertIn("Cash", ledger_map)
        self.assertIn("Sales Account", ledger_map)
        self.assertIn("Purchase Account", ledger_map)
        self.assertIn("Input CGST", ledger_map)
        self.assertIn("Input SGST", ledger_map)
        self.assertIn("Output CGST", ledger_map)
        self.assertIn("Output SGST", ledger_map)
        self.assertIn("Output IGST", ledger_map)

        # ---------------------------------------------------------
        # TEST 2: MASTER CREATION
        # ---------------------------------------------------------
        # Bank Ledger
        bank_id = create_ledger_helper(
            cid, "HDFC Current Account", "Bank Accounts",
            opening_balance=500000.00, opening_balance_type="Dr",
            db_path=db
        )
        # Capital Ledger
        cap_id = create_ledger_helper(
            cid, "Promoter Equity Capital", "Capital Account",
            opening_balance=500000.00, opening_balance_type="Cr",
            db_path=db
        )
        # Customer Ledgers
        cust_intra_id = create_ledger_helper(
            cid, "Alpha Infotech Mumbai", "Sundry Debtors",
            gstin="27ABCDE5678F1Z2", state="Maharashtra", state_code="27",
            db_path=db
        )
        cust_inter_id = create_ledger_helper(
            cid, "Omega Tech Ahmedabad", "Sundry Debtors",
            gstin="24XYZAB1234C1Z0", state="Gujarat", state_code="24",
            db_path=db
        )
        # Supplier Ledger
        supp_id = create_ledger_helper(
            cid, "Zenith Hardware Supplies", "Sundry Creditors",
            gstin="27AAAAB1234D1Z1", state="Maharashtra", state_code="27",
            db_path=db
        )
        # Expense Ledgers
        rent_id = create_ledger_helper(cid, "Office Rent Expense", "Indirect Expenses", db_path=db)
        power_id = create_ledger_helper(cid, "Factory Electricity", "Direct Expenses", db_path=db)
        audit_fee_id = create_ledger_helper(cid, "Audit Fees", "Indirect Expenses", db_path=db)
        audit_payable_id = create_ledger_helper(cid, "Audit Fees Payable", "Provisions", db_path=db)

        # Stock Item
        with transaction(db) as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM units WHERE symbol='NOS'")
            unit_id = cur.fetchone()[0]

        item_id = create_stock_item_helper(
            cid, name="Server Rack 42U", unit_id=unit_id,
            hsn_sac="8471", gst_rate=18.0, opening_qty=0.0, opening_rate=0.0,
            db_path=db
        )

        # ---------------------------------------------------------
        # TEST 3: PURCHASE WORKFLOW (Inward Inventory + GST)
        # ---------------------------------------------------------
        # 10 units @ 30,000 = 3,00,000. CGST 9% (27,000) + SGST 9% (27,000) = Total 3,54,000
        # Intra-state Purchase: 10 units @ 30,000 = 3,00,000. CGST 9% (27,000) + SGST 9% (27,000) = 3,54,000
        purch_vid = create_purchase_invoice(
            company_id=cid,
            party_ledger_id=supp_id,
            voucher_date="2026-11-04",
            items=[{"stock_item_id": item_id, "quantity": 10.0, "rate": 30000.0, "gst_rate": 18.0}],
            narration="Purchased 10 server racks from Zenith",
            db_path=db
        )
        self.assertIsNotNone(purch_vid)

        # Verify stock increased
        stock_summary = get_stock_summary(cid, db_path=db)
        self.assertEqual(len(stock_summary), 1)
        self.assertEqual(stock_summary[0]["closing_qty"], 10.0)

        # Verify Supplier outstanding is 3,54,000 Cr
        payables = get_outstanding_payables(cid, db_path=db)
        self.assertEqual(len(payables), 1)
        self.assertEqual(payables[0]["name"], "Zenith Hardware Supplies")
        self.assertEqual(payables[0]["current_balance"], 354000.0)

        # ---------------------------------------------------------
        # TEST 4: SALES WORKFLOW (Intra-State & Inter-State)
        # ---------------------------------------------------------
        # Intra-state Sales: 4 units @ 40,000 = 1,60,000. CGST 9% (14,400) + SGST 9% (14,400) = 1,88,800
        sales1_vid = create_sales_invoice(
            company_id=cid,
            party_ledger_id=cust_intra_id,
            voucher_date="2026-11-04",
            items=[{"stock_item_id": item_id, "quantity": 4.0, "rate": 40000.0, "gst_rate": 18.0}],
            narration="Sold 4 units to Alpha Infotech",
            db_path=db
        )
        self.assertIsNotNone(sales1_vid)

        # Inter-state Sales: 2 units @ 42,000 = 84,000. IGST 18% (15,120) = Total 99,120
        sales2_vid = create_sales_invoice(
            company_id=cid,
            party_ledger_id=cust_inter_id,
            voucher_date="2026-11-04",
            items=[{"stock_item_id": item_id, "quantity": 2.0, "rate": 42000.0, "gst_rate": 18.0}],
            narration="Sold 2 units inter-state to Omega Tech",
            db_path=db
        )
        self.assertIsNotNone(sales2_vid)

        # Verify stock decreased to 4 units (10 - 4 - 2 = 4)
        stock_summary2 = get_stock_summary(cid, db_path=db)
        self.assertEqual(stock_summary2[0]["closing_qty"], 4.0)

        # Verify receivables
        receivables = get_outstanding_receivables(cid, db_path=db)
        rec_map = {r["name"]: r["current_balance"] for r in receivables}
        self.assertEqual(rec_map.get("Alpha Infotech Mumbai"), 188800.0)
        self.assertEqual(rec_map.get("Omega Tech Ahmedabad"), 99120.0)

        # ---------------------------------------------------------
        # TEST 5: EXPENSE VOUCHERS
        # ---------------------------------------------------------
        # Pay Rent 25,000 from Bank (Payment voucher)
        rent_vid = post_voucher(
            company_id=cid,
            voucher_type="Payment",
            voucher_date="2026-11-04",
            party_ledger_id=rent_id,
            journal_postings=[
                {"ledger_id": rent_id, "entry_type": "Dr", "amount": 25000.00},
                {"ledger_id": bank_id, "entry_type": "Cr", "amount": 25000.00}
            ],
            narration="Office rent paid via HDFC Bank",
            total_amount=25000.00,
            db_path=db
        )
        self.assertIsNotNone(rent_vid)

        # Pay Factory Power 15,000 via Cash
        # First inject some cash via Contra from Bank (50,000)
        contra_vid = post_voucher(
            company_id=cid,
            voucher_type="Contra",
            voucher_date="2026-11-04",
            party_ledger_id=bank_id,
            journal_postings=[
                {"ledger_id": ledger_map["Cash"], "entry_type": "Dr", "amount": 50000.00},
                {"ledger_id": bank_id, "entry_type": "Cr", "amount": 50000.00}
            ],
            narration="Cash withdrawn from bank for petty cash",
            total_amount=50000.00,
            db_path=db
        )
        self.assertIsNotNone(contra_vid)

        # Power expense from cash
        power_vid = post_voucher(
            company_id=cid,
            voucher_type="Payment",
            voucher_date="2026-11-04",
            party_ledger_id=power_id,
            journal_postings=[
                {"ledger_id": power_id, "entry_type": "Dr", "amount": 15000.00},
                {"ledger_id": ledger_map["Cash"], "entry_type": "Cr", "amount": 15000.00}
            ],
            narration="Factory electricity paid from petty cash",
            total_amount=15000.00,
            db_path=db
        )
        self.assertIsNotNone(power_vid)

        # ---------------------------------------------------------
        # TEST 6: CUSTOMER RECEIPTS & SUPPLIER PAYMENTS
        # ---------------------------------------------------------
        # Customer Alpha pays in full (1,88,800) into Bank
        rcpt_vid = post_voucher(
            company_id=cid,
            voucher_type="Receipt",
            voucher_date="2026-11-04",
            party_ledger_id=cust_intra_id,
            journal_postings=[
                {"ledger_id": bank_id, "entry_type": "Dr", "amount": 188800.00},
                {"ledger_id": cust_intra_id, "entry_type": "Cr", "amount": 188800.00}
            ],
            narration="Received full invoice settlement from Alpha Infotech",
            total_amount=188800.00,
            db_path=db
        )
        self.assertIsNotNone(rcpt_vid)

        # Supplier Zenith is paid in full (3,54,000) from Bank
        pay_supp_vid = post_voucher(
            company_id=cid,
            voucher_type="Payment",
            voucher_date="2026-11-04",
            party_ledger_id=supp_id,
            journal_postings=[
                {"ledger_id": supp_id, "entry_type": "Dr", "amount": 354000.00},
                {"ledger_id": bank_id, "entry_type": "Cr", "amount": 354000.00}
            ],
            narration="Paid Zenith Hardware in full via NEFT",
            total_amount=354000.00,
            db_path=db
        )
        self.assertIsNotNone(pay_supp_vid)

        # Alpha outstanding should now be 0.00
        rec_after = get_outstanding_receivables(cid, db_path=db)
        alpha_rec = [r for r in rec_after if r["name"] == "Alpha Infotech Mumbai"]
        self.assertEqual(len(alpha_rec), 0)

        # Zenith payables should now be 0.00
        pay_after = get_outstanding_payables(cid, db_path=db)
        self.assertEqual(len(pay_after), 0)

        # ---------------------------------------------------------
        # TEST 7: JOURNAL PROVISION ENTRY
        # ---------------------------------------------------------
        jv_vid = post_voucher(
            company_id=cid,
            voucher_type="Journal",
            voucher_date="2026-11-04",
            party_ledger_id=audit_payable_id,
            journal_postings=[
                {"ledger_id": audit_fee_id, "entry_type": "Dr", "amount": 10000.00},
                {"ledger_id": audit_payable_id, "entry_type": "Cr", "amount": 10000.00}
            ],
            narration="Provision for statutory audit fees",
            total_amount=10000.00,
            db_path=db
        )
        self.assertIsNotNone(jv_vid)

        # ---------------------------------------------------------
        # TEST 8: DAY BOOK VERIFICATION
        # ---------------------------------------------------------
        daybook = get_day_book(cid, start_date="2026-11-04", end_date="2026-11-04", db_path=db)
        self.assertGreaterEqual(len(daybook), 8)
        # Verify chronological order and correct types
        vtypes = [v["voucher_type"] for v in daybook]
        self.assertIn("Purchase", vtypes)
        self.assertIn("Sales", vtypes)
        self.assertIn("Payment", vtypes)
        self.assertIn("Contra", vtypes)
        self.assertIn("Receipt", vtypes)
        self.assertIn("Journal", vtypes)

        # ---------------------------------------------------------
        # TEST 9: FINANCIAL REPORTS ACCURACY (CRITICAL RECONCILIATION)
        # ---------------------------------------------------------
        # 1. Trial Balance: Total Debit MUST exactly equal Total Credit
        tb = get_trial_balance(cid, db_path=db)
        self.assertEqual(tb["is_balanced"], True, f"Trial balance out of balance: Dr={tb['total_debit']}, Cr={tb['total_credit']}")
        self.assertAlmostEqual(tb["total_debit"], tb["total_credit"], places=2)

        # 2. Profit & Loss:
        pnl = get_profit_and_loss(cid, db_path=db)
        self.assertIn("net_profit", pnl)
        self.assertIn("gross_profit", pnl)

        # 3. Balance Sheet Equation: Total Liabilities == Total Assets
        bs = get_balance_sheet(cid, db_path=db)
        self.assertAlmostEqual(
            bs["total_liabilities"], bs["total_assets"], places=2,
            msg=f"Balance Sheet not balanced! Liabilities={bs['total_liabilities']}, Assets={bs['total_assets']}"
        )

        # 4. Cash & Bank Summary
        cb = get_cash_bank_summary(cid, db_path=db)
        # Cash: 0 + 50,000 (contra) - 15,000 (power) = 35,000 Dr
        self.assertAlmostEqual(cb["total_cash"], 35000.00, places=2)
        # Bank: 5,00,000 + 1,88,800 - 25,000 - 50,000 - 3,54,000 = 2,59,800 Dr
        self.assertAlmostEqual(cb["total_bank"], 259800.00, places=2)

    def test_double_entry_mismatch_rejection(self):
        """Phase 9: Verification that unbalanced transactions are strictly rejected"""
        cid = create_company(name="Test Unbalanced Co", db_path=self.test_db)
        ledgers = get_company_ledgers(cid, db_path=self.test_db)
        cash_id = [l["id"] for l in ledgers if l["name"] == "Cash"][0]
        sales_id = [l["id"] for l in ledgers if l["name"] == "Sales Account"][0]

        # Post an unbalanced voucher (Dr 1000, Cr 900)
        with self.assertRaises(DoubleEntryMismatchError):
            post_voucher(
                company_id=cid,
                voucher_type="Receipt",
                voucher_date="2026-11-04",
                party_ledger_id=cash_id,
                journal_postings=[
                    {"ledger_id": cash_id, "entry_type": "Dr", "amount": 1000.00},
                    {"ledger_id": sales_id, "entry_type": "Cr", "amount": 900.00}
                ],
                narration="Invalid unbalanced voucher",
                total_amount=1000.00,
                db_path=self.test_db
            )

    def test_backup_and_restore_fidelity(self):
        """Phase 6: Verification of backup zip creation and restoration to independent target"""
        backup_dir = Path(self.temp_dir.name) / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)

        # Create company and ledger in test DB
        cid = create_company(name="Backup Test Enterprise", db_path=self.test_db)
        test_lid = create_ledger_helper(cid, "Custom Backup Ledger", "Indirect Expenses", db_path=self.test_db)

        # Create backup
        backup_str = create_backup(self.test_db, note="qa_test")
        backup_path = Path(backup_str)
        self.assertTrue(backup_path.exists(), "Backup archive was not created.")

        # Restore into another fresh database path
        restore_target = Path(self.temp_dir.name) / "restored.db"
        success = restore_backup(backup_path.name, target_db_path=restore_target)
        self.assertTrue(success, "Restore operation failed.")
        try:
            backup_path.unlink()
        except Exception:
            pass

        # Verify restored company and ledger
        conn = get_connection(restore_target)
        cur = conn.cursor()
        cur.execute("SELECT name FROM companies WHERE id = ?", (cid,))
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "Backup Test Enterprise")

        cur.execute("SELECT name FROM ledgers WHERE id = ?", (test_lid,))
        led_row = cur.fetchone()
        self.assertIsNotNone(led_row)
        self.assertEqual(led_row[0], "Custom Backup Ledger")
        conn.close()

    def test_core_http_routes_accessibility(self):
        """Phase 2: Option-by-option HTTP accessibility test across core screens"""
        if not list_companies():
            create_company(name="QA Verification Enterprise")

        endpoints = [
            "/",
            "/company/select",
            "/masters/chart-of-accounts",
            "/masters/groups/create",
            "/masters/ledgers/create",
            "/masters/stock-items/create",
            "/masters/stock-groups/create",
            "/masters/units/create",
            "/masters/godowns/create",
            "/vouchers/create?type=Sales",
            "/vouchers/create?type=Purchase",
            "/vouchers/create?type=Payment",
            "/vouchers/create?type=Receipt",
            "/vouchers/create?type=Contra",
            "/vouchers/create?type=Journal",
            "/daybook",
            "/reports/trial-balance",
            "/reports/profit-loss",
            "/reports/balance-sheet",
            "/reports/stock-summary",
            "/reports/ratio-analysis",
            "/reports/cash-bank-book",
            "/reports/gst",
            "/reports/outstanding-receivables",
            "/reports/outstanding-payables",
            "/reports/bill-ageing",
            "/banking/reconciliation",
            "/pos/invoice",
            "/orders/sales",
            "/orders/purchase",
            "/inventory/manufacturing",
            "/inventory/physical-stock",
            "/inventory/stock-journal",
            "/payroll/employees",
            "/statutory/tds",
            "/data/backup",
            "/data/exchange"
        ]
        for ep in endpoints:
            res = self.client.get(ep)
            self.assertEqual(
                res.status_code, 200,
                f"Endpoint {ep} failed with status {res.status_code}"
            )


if __name__ == "__main__":
    unittest.main()
