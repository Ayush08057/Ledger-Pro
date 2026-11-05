"""
Vercel Serverless Function entry point for Ledger Pro (Flask)
"""
import sys
import os
from pathlib import Path

# Add possible root directories to sys.path so 'app' package is always found
current_dir = Path(__file__).resolve().parent
for p in [current_dir.parent, current_dir, Path(os.getcwd())]:
    p_str = str(p)
    if p_str not in sys.path:
        sys.path.insert(0, p_str)

from app.server import app

# Cold-start database schema validation in /tmp
from app.database import init_db
from app.manufacturing_engine import init_manufacturing_schema
from app.physical_stock_engine import init_physical_stock_schema
from app.tds_tcs_engine import init_tds_schema
from app.payroll_engine import init_payroll_schema
from app.edit_log_engine import init_edit_log_schema
from app.currency_engine import init_currency_schema
from app.pos_engine import init_pos_schema
from app.budget_engine import init_budget_schema
from app.price_list_engine import init_price_list_schema

try:
    init_db()
    init_manufacturing_schema()
    init_physical_stock_schema()
    init_tds_schema()
    init_payroll_schema()
    init_edit_log_schema()
    init_currency_schema()
    init_pos_schema()
    init_budget_schema()
    init_price_list_schema()
except Exception as e:
    print(f"Serverless init notice: {e}")
