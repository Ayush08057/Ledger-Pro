"""
Unit tests for Statutory Audit Trail & MCA Edit Log Engine
"""

import unittest
import tempfile
from pathlib import Path
from app.database import init_db, create_company
from app.edit_log_engine import (
    init_edit_log_schema,
    record_edit_log,
    get_entity_edit_log,
    list_recent_audit_trail
)


class TestEditLog(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db = Path(self.temp_dir.name) / "test_edit_log.db"
        init_db(self.test_db)
        init_edit_log_schema(self.test_db)

        self.company_id = create_company(
            name="Apex Technologies Ltd",
            state="Maharashtra",
            state_code="27",
            db_path=self.test_db
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_01_versioned_edit_log(self):
        # 1. Version 1: Initial Voucher Creation
        v1_data = {
            "voucher_number": "SLS-001",
            "voucher_date": "2026-11-03",
            "party_ledger": "Acme Corp",
            "amount": 50000.0,
            "status": "Active"
        }
        log_id_1 = record_edit_log(
            company_id=self.company_id,
            entity_type="Voucher",
            entity_id=101,
            action="CREATE",
            current_data=v1_data,
            user_name="Admin",
            db_path=self.test_db
        )
        self.assertIsNotNone(log_id_1)

        # 2. Version 2: Alteration / Edit
        v2_data = {
            "voucher_number": "SLS-001",
            "voucher_date": "2026-11-03",
            "party_ledger": "Acme Corp",
            "amount": 55000.0,  # Changed amount
            "status": "Active"
        }
        log_id_2 = record_edit_log(
            company_id=self.company_id,
            entity_type="Voucher",
            entity_id=101,
            action="ALTER",
            current_data=v2_data,
            user_name="Manager",
            db_path=self.test_db
        )
        self.assertIsNotNone(log_id_2)

        # 3. Retrieve edit log history
        history = get_entity_edit_log(self.company_id, "Voucher", 101, self.test_db)
        self.assertEqual(len(history), 2)
        # Ordered by version DESC (latest first)
        self.assertEqual(history[0]['version'], 2)
        self.assertEqual(history[0]['action'], "ALTER")
        self.assertIn("amount: '50000.0' -> '55000.0'", history[0]['changes_summary'])

        self.assertEqual(history[1]['version'], 1)
        self.assertEqual(history[1]['action'], "CREATE")

        # 4. Check organization audit trail listing
        trail = list_recent_audit_trail(self.company_id, db_path=self.test_db)
        self.assertGreaterEqual(len(trail), 2)


if __name__ == "__main__":
    unittest.main()

