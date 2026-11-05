"""
TallySoft Reporting Engine
Generates Balance Sheet, Profit & Loss A/c, Trial Balance, Day Book, and Stock Summary.
"""

from typing import Dict, Any, List
from app.database import transaction


def get_day_book(company_id: int, start_date: str = "", end_date: str = "", db_path=None) -> List[Dict[str, Any]]:
    """
    Returns vouchers recorded within the date range.
    """
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        query = """
            SELECT v.id, v.voucher_number, v.voucher_type, v.voucher_date,
                   COALESCE(p.name, 'General Entry') AS party_name,
                   v.total_amount, v.narration
            FROM vouchers v
            LEFT JOIN ledgers p ON v.party_ledger_id = p.id
            WHERE v.company_id = ?
        """
        params = [company_id]
        if start_date:
            query += " AND v.voucher_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND v.voucher_date <= ?"
            params.append(end_date)
        query += " ORDER BY v.voucher_date DESC, v.id DESC"

        cursor.execute(query, params)
        vouchers = [dict(row) for row in cursor.fetchall()]
        for v in vouchers:
            vtype = v.get("voucher_type", "")
            tot = float(v.get("total_amount") or 0.0)
            if vtype in ["Receipt", "Sales", "Credit Note"]:
                v["credit_amount"] = tot
                v["debit_amount"] = 0.0
            elif vtype in ["Payment", "Purchase", "Debit Note"]:
                v["debit_amount"] = tot
                v["credit_amount"] = 0.0
            else:
                cursor.execute("SELECT entry_type, amount FROM journal_entries WHERE voucher_id = ? LIMIT 1", (v["id"],))
                je = cursor.fetchone()
                if je and je["entry_type"] == "Dr":
                    v["debit_amount"] = tot
                    v["credit_amount"] = 0.0
                else:
                    v["credit_amount"] = tot
                    v["debit_amount"] = 0.0
        return vouchers


def get_profit_and_loss(company_id: int, db_path=None) -> Dict[str, Any]:
    """
    Generates Profit & Loss Statement:
    Trading Account:
      - Sales Accounts, Direct Incomes
      - Purchase Accounts, Direct Expenses
      - Gross Profit = Incomes - Expenses
    Profit & Loss Account:
      - Indirect Incomes
      - Indirect Expenses
      - Net Profit
    """
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT l.id, l.name, g.name AS group_name, g.nature, g.affects_gross_profit,
                   l.current_balance, l.current_balance_type
            FROM ledgers l
            JOIN ledger_groups g ON l.group_id = g.id
            WHERE l.company_id = ? AND g.nature IN ('Income', 'Expense') AND l.current_balance > 0
            ORDER BY g.nature, l.name
        """, (company_id,))
        rows = cursor.fetchall()

        sales_incomes = []
        purchases_expenses = []
        indirect_incomes = []
        indirect_expenses = []

        tot_sales = 0.0
        tot_purchases = 0.0
        tot_ind_inc = 0.0
        tot_ind_exp = 0.0

        for r in rows:
            amt = float(r["current_balance"])
            nature = r["nature"]
            affects_gp = r["affects_gross_profit"]

            item = {"name": r["name"], "group": r["group_name"], "amount": amt}
            if nature == "Income":
                if affects_gp:
                    sales_incomes.append(item)
                    tot_sales += amt
                else:
                    indirect_incomes.append(item)
                    tot_ind_inc += amt
            elif nature == "Expense":
                if affects_gp:
                    purchases_expenses.append(item)
                    tot_purchases += amt
                else:
                    indirect_expenses.append(item)
                    tot_ind_exp += amt

        gross_profit = round(tot_sales - tot_purchases, 2)
        net_profit = round(gross_profit + tot_ind_inc - tot_ind_exp, 2)

        return {
            "sales_incomes": sales_incomes,
            "total_sales_incomes": round(tot_sales, 2),
            "purchases_expenses": purchases_expenses,
            "total_purchases_expenses": round(tot_purchases, 2),
            "gross_profit": gross_profit,
            "indirect_incomes": indirect_incomes,
            "total_indirect_incomes": round(tot_ind_inc, 2),
            "indirect_expenses": indirect_expenses,
            "total_indirect_expenses": round(tot_ind_exp, 2),
            "net_profit": net_profit
        }


def get_balance_sheet(company_id: int, db_path=None) -> Dict[str, Any]:
    """
    Generates Balance Sheet in standard Tally / Schedule III T-Format:
    Liabilities (Capital, Loans, Current Liabilities, Net Profit)
    Assets (Fixed Assets, Investments, Current Assets, Closing Stock)
    """
    pnl = get_profit_and_loss(company_id, db_path=db_path)
    net_profit = pnl["net_profit"]

    with transaction(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT l.id, l.name, g.name AS group_name, g.nature,
                   l.current_balance, l.current_balance_type
            FROM ledgers l
            JOIN ledger_groups g ON l.group_id = g.id
            WHERE l.company_id = ? AND g.nature IN ('Asset', 'Liability') AND l.current_balance > 0
            ORDER BY g.nature, g.name, l.name
        """, (company_id,))
        rows = cursor.fetchall()

        liabilities = []
        assets = []
        tot_liab = 0.0
        tot_assets = 0.0

        for r in rows:
            amt = float(r["current_balance"])
            bal_type = r["current_balance_type"]
            nature = r["nature"]

            if nature == "Liability":
                eff_amt = amt if bal_type == "Cr" else -amt
                liabilities.append({"name": r["name"], "group": r["group_name"], "amount": eff_amt})
                tot_liab += eff_amt
            elif nature == "Asset":
                eff_amt = amt if bal_type == "Dr" else -amt
                assets.append({"name": r["name"], "group": r["group_name"], "amount": eff_amt})
                tot_assets += eff_amt

        # Add Net Profit to Liabilities (Reserves & Surplus)
        if net_profit != 0.0:
            liabilities.append({"name": "Profit & Loss A/c (Current Period)", "group": "Reserves & Surplus", "amount": net_profit})
            tot_liab += net_profit

        return {
            "liabilities": liabilities,
            "total_liabilities": round(tot_liab, 2),
            "assets": assets,
            "total_assets": round(tot_assets, 2),
            "is_balanced": abs(round(tot_liab - tot_assets, 2)) < 0.01,
            "difference": round(tot_liab - tot_assets, 2)
        }


def get_stock_summary(company_id: int, db_path=None) -> List[Dict[str, Any]]:
    """
    Returns Item-wise Stock Summary with Opening, Inward, Outward, and Closing.
    """
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.id, s.name, u.symbol AS unit_symbol, s.hsn_sac, s.gst_rate,
                   s.opening_qty, s.opening_rate, (s.opening_qty * s.opening_rate) AS opening_value,
                   s.closing_qty,
                   COALESCE((
                       SELECT SUM(vii.quantity)
                       FROM voucher_inventory_items vii
                       JOIN vouchers v ON vii.voucher_id = v.id
                       WHERE vii.stock_item_id = s.id AND v.voucher_type IN ('Purchase', 'Credit Note')
                   ), 0.0) AS inward_qty,
                   COALESCE((
                       SELECT SUM(vii.quantity)
                       FROM voucher_inventory_items vii
                       JOIN vouchers v ON vii.voucher_id = v.id
                       WHERE vii.stock_item_id = s.id AND v.voucher_type IN ('Sales', 'Debit Note')
                   ), 0.0) AS outward_qty
            FROM stock_items s
            JOIN units u ON s.unit_id = u.id
            WHERE s.company_id = ?
            ORDER BY s.name
        """, (company_id,))
        rows = cursor.fetchall()

        summary = []
        for r in rows:
            closing_val = round(r["closing_qty"] * r["opening_rate"], 2)
            summary.append({
                "id": r["id"],
                "name": r["name"],
                "unit": r["unit_symbol"],
                "hsn_sac": r["hsn_sac"],
                "gst_rate": r["gst_rate"],
                "opening_qty": r["opening_qty"],
                "inward_qty": r["inward_qty"],
                "outward_qty": r["outward_qty"],
                "closing_qty": r["closing_qty"],
                "rate": r["opening_rate"],
                "closing_value": closing_val
            })
        return summary

