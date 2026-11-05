"""
Vercel Serverless Function entry point for Ledger Pro (Flask)
"""
import sys
from pathlib import Path

# Ensure project root is in sys.path for serverless execution
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.server import app
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

# Cold-start database schema validation in /tmp
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
    pass

# Export WSGI application object for Vercel
# Vercel Python runtime detects 'app'
