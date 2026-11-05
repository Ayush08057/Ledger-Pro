"""
Unit tests for Manufacturing Journal & Bill of Materials (BOM) Engine
"""

import unittest
import tempfile
from pathlib import Path
from app.database import init_db, create_company, get_connection
from app.godown_engine import init_godown_schema, create_godown
from app.manufacturing_engine import (
    init_manufacturing_schema,
    create_bom,
    get_boms_for_item,
    record_manufacturing_journal,
    list_manufacturing_journals
)


class TestManufacturing(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db = Path(self.temp_dir.name) / "test_mfg.db"
        init_db(self.test_db)
        init_godown_schema(self.test_db)
        init_manufacturing_schema(self.test_db)

        self.company_id = create_company(
            name="Apex Electronics Ltd",
            state="Maharashtra",
            state_code="27",
            db_path=self.test_db
        )

        conn = get_connection(self.test_db)
        cursor = conn.cursor()

        cursor.execute("SELECT id FROM units WHERE company_id = ? AND symbol = 'NOS'", (self.company_id,))
        self.uom_id = cursor.fetchone()[0]

        # Create Godowns
        self.raw_godown_id = create_godown(self.company_id, "Raw Materials Store", "Warehouse A", self.test_db)
        self.mfg_godown_id = create_godown(self.company_id, "Finished Goods Yard", "Warehouse B", self.test_db)

        # Create Raw Material Items
        cursor.execute("""
            INSERT INTO stock_items (company_id, name, unit_id, opening_qty, opening_rate, opening_value, closing_qty, closing_value)
            VALUES (?, 'Processor i7', ?, 50, 20000.0, 1000000.0, 50, 1000000.0)
        """, (self.company_id, self.uom_id))
        self.item_cpu = cursor.lastrowid

        cursor.execute("""
            INSERT INTO stock_items (company_id, name, unit_id, opening_qty, opening_rate, opening_value, closing_qty, closing_value)
            VALUES (?, 'Motherboard B760', ?, 50, 10000.0, 500000.0, 50, 500000.0)
        """, (self.company_id, self.uom_id))
        self.item_mb = cursor.lastrowid

        # Seed raw materials into Raw Godown
        cursor.execute("""
            INSERT INTO godown_stock (company_id, godown_id, stock_item_id, closing_qty)
            VALUES (?, ?, ?, 50)
        """, (self.company_id, self.raw_godown_id, self.item_cpu))

        cursor.execute("""
            INSERT INTO godown_stock (company_id, godown_id, stock_item_id, closing_qty)
            VALUES (?, ?, ?, 50)
        """, (self.company_id, self.raw_godown_id, self.item_mb))

        # Create Finished Item
        cursor.execute("""
            INSERT INTO stock_items (company_id, name, unit_id, opening_qty, opening_rate, opening_value, closing_qty, closing_value)
            VALUES (?, 'Gaming PC Pro', ?, 0, 0, 0, 0, 0)
        """, (self.company_id, self.uom_id))
        self.item_pc = cursor.lastrowid

        conn.commit()
        conn.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_01_create_bom(self):
        bom_id = create_bom(
            company_id=self.company_id,
            name="Standard Build",
            finished_item_id=self.item_pc,
            finished_qty=1.0,
            components=[
                {"stock_item_id": self.item_cpu, "quantity": 1.0},
                {"stock_item_id": self.item_mb, "quantity": 1.0}
            ],
            unit_id=self.uom_id,
            narration="Standard Gaming PC Assembly",
            db_path=self.test_db
        )
        self.assertIsNotNone(bom_id)

        boms = get_boms_for_item(self.company_id, self.item_pc, self.test_db)
        self.assertEqual(len(boms), 1)
        self.assertEqual(boms[0]['name'], "Standard Build")
        self.assertEqual(len(boms[0]['components']), 2)

    def test_02_record_manufacturing_journal(self):
        # Manufacture 5 Gaming PCs
        res = record_manufacturing_journal(
            company_id=self.company_id,
            voucher_date="2026-11-03",
            finished_item_id=self.item_pc,
            destination_godown_id=self.mfg_godown_id,
            produced_qty=5.0,
            consumed_items=[
                {"stock_item_id": self.item_cpu, "godown_id": self.raw_godown_id, "quantity": 5.0, "rate": 20000.0},
                {"stock_item_id": self.item_mb, "godown_id": self.raw_godown_id, "quantity": 5.0, "rate": 10000.0}
            ],
            additional_cost=5000.0,  # 5,000 labor overheads
            narration="Batch 001 Assembly",
            db_path=self.test_db
        )

        # 5 * 20000 + 5 * 10000 = 100,000 + 50,000 = 150,000 raw material cost
        # + 5000 additional = 155,000 total cost
        # Effective rate = 155,000 / 5 = 31,000 per PC
        self.assertEqual(res['raw_materials_cost'], 150000.0)
        self.assertEqual(res['additional_cost'], 5000.0)
        self.assertEqual(res['total_cost'], 155000.0)
        self.assertEqual(res['effective_rate'], 31000.0)

        # Check stock updates
        conn = get_connection(self.test_db)
        # Check raw materials deducted
        cpu = conn.execute("SELECT closing_qty FROM stock_items WHERE id = ?", (self.item_cpu,)).fetchone()
        self.assertEqual(cpu['closing_qty'], 45.0)

        # Check finished item increased
        pc = conn.execute("SELECT closing_qty, closing_value FROM stock_items WHERE id = ?", (self.item_pc,)).fetchone()
        self.assertEqual(pc['closing_qty'], 5.0)
        self.assertEqual(pc['closing_value'], 155000.0)

        # Check destination godown stock
        g_pc = conn.execute("SELECT closing_qty FROM godown_stock WHERE godown_id = ? AND stock_item_id = ?", (self.mfg_godown_id, self.item_pc)).fetchone()
        self.assertEqual(g_pc['closing_qty'], 5.0)

        conn.close()

        # Check listing
        mfgs = list_manufacturing_journals(self.company_id, self.test_db)
        self.assertEqual(len(mfgs), 1)
        self.assertEqual(mfgs[0]['produced_qty'], 5.0)


if __name__ == "__main__":
    unittest.main()
