"""
TallySoft Advanced Financial Analysis & Banking Module
Calculates Ledger Statements, Outstanding Receivables/Payables,
Cash & Bank Books, and Tally Ratio Analysis.
"""

from typing import Dict, Any, List
from datetime import datetime
from app.database import transaction
from app.reports import get_profit_and_loss, get_balance_sheet


def get_ledger_statement(company_id: int, ledger_id: int, start_date: str = "", end_date: str = "", db_path=None) -> Dict[str, Any]:
    """
    Returns itemized statement of accounts for a specific ledger with running balance.
    """
    with transaction(db_path) as conn:
        cursor = conn.cursor()

        # Fetch ledger and group
        cursor.execute("""
            SELECT l.*, g.name AS group_name, g.nature
            FROM ledgers l
            JOIN ledger_groups g ON l.group_id = g.id
            WHERE l.id = ? AND l.company_id = ?
        """, (ledger_id, company_id))
        ledger_row = cursor.fetchone()
        if not ledger_row:
            return {}
        ledger = dict(ledger_row)

        op_bal = float(ledger["opening_balance"])
        op_type = ledger["opening_balance_type"]

        # Fetch journal postings
        query = """
            SELECT j.id, j.entry_date, j.entry_type, j.amount, j.narration,
                   v.voucher_number, v.voucher_type
            FROM journal_entries j
            JOIN vouchers v ON j.voucher_id = v.id
            WHERE j.ledger_id = ? AND j.company_id = ?
        """
        params = [ledger_id, company_id]
        if start_date:
            query += " AND j.entry_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND j.entry_date <= ?"
            params.append(end_date)
        query += " ORDER BY j.entry_date ASC, j.id ASC"

        cursor.execute(query, params)
        postings = cursor.fetchall()

        running_net = op_bal if op_type == "Dr" else -op_bal
        lines = []
        tot_dr = 0.0
        tot_cr = 0.0

        for p in postings:
            amt = float(p["amount"])
            if p["entry_type"] == "Dr":
                tot_dr += amt
                running_net += amt
            else:
                tot_cr += amt
                running_net -= amt

            cur_type = "Dr" if running_net >= 0 else "Cr"
            lines.append({
                "date": p["entry_date"],
                "voucher_no": p["voucher_number"],
                "voucher_type": p["voucher_type"],
                "narration": p["narration"],
                "debit": amt if p["entry_type"] == "Dr" else 0.0,
                "credit": amt if p["entry_type"] == "Cr" else 0.0,
                "balance": abs(round(running_net, 2)),
                "balance_type": cur_type
            })

        return {
            "ledger": ledger,
            "opening_balance": op_bal,
            "opening_balance_type": op_type,
            "lines": lines,
            "total_debit": round(tot_dr, 2),
            "total_credit": round(tot_cr, 2),
            "closing_balance": abs(round(running_net, 2)),
            "closing_balance_type": "Dr" if running_net >= 0 else "Cr"
        }


def get_outstanding_receivables(company_id: int, db_path=None) -> List[Dict[str, Any]]:
    """
    Returns bills receivable (Sundry Debtors with Dr balance).
    """
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT l.id, l.name, l.phone, l.gstin, l.state_code,
                   l.current_balance, l.current_balance_type,
                   (
                       SELECT MAX(v.voucher_date) 
                       FROM vouchers v 
                       WHERE v.party_ledger_id = l.id
                   ) AS last_bill_date
            FROM ledgers l
            JOIN ledger_groups g ON l.group_id = g.id
            WHERE l.company_id = ? AND g.name = 'Sundry Debtors' AND l.current_balance > 0 AND l.current_balance_type = 'Dr'
            ORDER BY l.current_balance DESC
        """, (company_id,))
        return [dict(r) for r in cursor.fetchall()]


def get_outstanding_payables(company_id: int, db_path=None) -> List[Dict[str, Any]]:
    """
    Returns bills payable (Sundry Creditors with Cr balance).
    """
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT l.id, l.name, l.phone, l.gstin, l.state_code,
                   l.current_balance, l.current_balance_type,
                   (
                       SELECT MAX(v.voucher_date) 
                       FROM vouchers v 
                       WHERE v.party_ledger_id = l.id
                   ) AS last_bill_date
            FROM ledgers l
            JOIN ledger_groups g ON l.group_id = g.id
            WHERE l.company_id = ? AND g.name = 'Sundry Creditors' AND l.current_balance > 0 AND l.current_balance_type = 'Cr'
            ORDER BY l.current_balance DESC
        """, (company_id,))
        return [dict(r) for r in cursor.fetchall()]


def get_cash_bank_summary(company_id: int, db_path=None) -> Dict[str, Any]:
    """
    Returns Cash & Bank Book balances.
    """
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT l.id, l.name, g.name AS group_name,
                   l.opening_balance, l.opening_balance_type,
                   l.current_balance, l.current_balance_type
            FROM ledgers l
            JOIN ledger_groups g ON l.group_id = g.id
            WHERE l.company_id = ? AND g.name IN ('Cash-in-Hand', 'Bank Accounts', 'Bank OD A/c')
            ORDER BY g.name, l.name
        """, (company_id,))
        rows = [dict(r) for r in cursor.fetchall()]

        tot_cash = sum(r["current_balance"] for r in rows if r["group_name"] == "Cash-in-Hand" and r["current_balance_type"] == "Dr")
        tot_bank = sum(r["current_balance"] for r in rows if r["group_name"] == "Bank Accounts" and r["current_balance_type"] == "Dr")

        return {
            "accounts": rows,
            "total_cash": round(tot_cash, 2),
            "total_bank": round(tot_bank, 2),
            "total_liquid_funds": round(tot_cash + tot_bank, 2)
        }


def get_ratio_analysis(company_id: int, db_path=None) -> Dict[str, Any]:
    """
    Computes key financial ratios as presented in TallyPrime:
    - Current Ratio
    - Quick Ratio
    - Debt Equity Ratio
    - Gross Profit Margin %
    - Net Profit Margin %
    """
    pnl = get_profit_and_loss(company_id, db_path=db_path)
    bs = get_balance_sheet(company_id, db_path=db_path)

    # Current Assets & Current Liabilities
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COALESCE(SUM(l.current_balance), 0.0)
            FROM ledgers l
            JOIN ledger_groups g ON l.group_id = g.id
            LEFT JOIN ledger_groups p ON g.parent_group_id = p.id
            WHERE l.company_id = ? AND (g.name = 'Current Assets' OR p.name = 'Current Assets')
                  AND l.current_balance_type = 'Dr'
        """, (company_id,))
        current_assets = float(cursor.fetchone()[0])

        cursor.execute("""
            SELECT COALESCE(SUM(l.current_balance), 0.0)
            FROM ledgers l
            JOIN ledger_groups g ON l.group_id = g.id
            LEFT JOIN ledger_groups p ON g.parent_group_id = p.id
            WHERE l.company_id = ? AND (g.name = 'Current Liabilities' OR p.name = 'Current Liabilities')
                  AND l.current_balance_type = 'Cr'
        """, (company_id,))
        current_liabilities = float(cursor.fetchone()[0])

        # Closing stock value
        cursor.execute("""
            SELECT COALESCE(SUM(closing_qty * opening_rate), 0.0)
            FROM stock_items WHERE company_id = ?
        """, (company_id,))
        stock_value = float(cursor.fetchone()[0])

    tot_sales = pnl["total_sales_incomes"]
    gp = pnl["gross_profit"]
    np = pnl["net_profit"]

    current_ratio = round(current_assets / current_liabilities, 2) if current_liabilities > 0 else (current_assets if current_assets > 0 else 1.0)
    quick_assets = max(0.0, current_assets - stock_value)
    quick_ratio = round(quick_assets / current_liabilities, 2) if current_liabilities > 0 else 1.0

    gp_margin = round((gp / tot_sales) * 100.0, 2) if tot_sales > 0 else 0.0
    np_margin = round((np / tot_sales) * 100.0, 2) if tot_sales > 0 else 0.0

    return {
        "current_assets": current_assets,
        "current_liabilities": current_liabilities,
        "stock_value": stock_value,
        "quick_assets": quick_assets,
        "current_ratio": current_ratio,
        "quick_ratio": quick_ratio,
        "sales_turnover": tot_sales,
        "gross_profit": gp,
        "gross_profit_percent": gp_margin,
        "net_profit": np,
        "net_profit_percent": np_margin
    }


def get_cash_flow_statement(company_id: int, fy_year: int = 2026, db_path=None) -> Dict[str, Any]:
    """
    Computes monthly Cash & Funds Flow Statement across April through March (Tally style).
    Tracks cash movements: Inflow (Dr), Outflow (Cr), and Nett Flow per month.
    """
    months = [
        ("April", f"{fy_year}-04"),
        ("May", f"{fy_year}-05"),
        ("June", f"{fy_year}-06"),
        ("July", f"{fy_year}-07"),
        ("August", f"{fy_year}-08"),
        ("September", f"{fy_year}-09"),
        ("October", f"{fy_year}-10"),
        ("November", f"{fy_year}-11"),
        ("December", f"{fy_year}-12"),
        ("January", f"{fy_year+1}-01"),
        ("February", f"{fy_year+1}-02"),
        ("March", f"{fy_year+1}-03")
    ]

    monthly_flows = []
    tot_inflow = 0.0
    tot_outflow = 0.0

    with transaction(db_path) as conn:
        cursor = conn.cursor()
        # Find all cash and bank ledgers
        cursor.execute("""
            SELECT l.id FROM ledgers l
            JOIN ledger_groups g ON l.group_id = g.id
            WHERE l.company_id = ? AND g.name IN ('Cash-in-Hand', 'Bank Accounts', 'Bank OD A/c')
        """, (company_id,))
        cb_ids = [r[0] for r in cursor.fetchall()]

        for m_name, ym in months:
            inflow = 0.0
            outflow = 0.0
            if cb_ids:
                placeholders = ",".join("?" * len(cb_ids))
                # Inflow is Dr
                cursor.execute(f"""
                    SELECT COALESCE(SUM(amount), 0.0)
                    FROM journal_entries
                    WHERE company_id = ? AND entry_type = 'Dr'
                      AND ledger_id IN ({placeholders})
                      AND strftime('%Y-%m', entry_date) = ?
                """, [company_id] + cb_ids + [ym])
                inflow = float(cursor.fetchone()[0])

                # Outflow is Cr
                cursor.execute(f"""
                    SELECT COALESCE(SUM(amount), 0.0)
                    FROM journal_entries
                    WHERE company_id = ? AND entry_type = 'Cr'
                      AND ledger_id IN ({placeholders})
                      AND strftime('%Y-%m', entry_date) = ?
                """, [company_id] + cb_ids + [ym])
                outflow = float(cursor.fetchone()[0])

            nett = round(inflow - outflow, 2)
            tot_inflow += inflow
            tot_outflow += outflow

            monthly_flows.append({
                "month_name": m_name,
                "year_month": ym,
                "inflow": round(inflow, 2),
                "outflow": round(outflow, 2),
                "nett_flow": nett
            })

    grand_nett = round(tot_inflow - tot_outflow, 2)
    return {
        "company_id": company_id,
        "fy_year": fy_year,
        "monthly_flows": monthly_flows,
        "total_inflow": round(tot_inflow, 2),
        "total_outflow": round(tot_outflow, 2),
        "grand_nett_flow": grand_nett
    }


def get_funds_flow_statement(company_id: int, fy_year: int = 2026, db_path=None) -> Dict[str, Any]:
    """
    Computes authentic Tally Funds Flow Statement:
    Sources of Funds vs Applications of Funds and Nett Change in Working Capital.
    """
    cash_flow = get_cash_flow_statement(company_id, fy_year, db_path)
    sources = []
    applications = []

    net_ops = cash_flow["grand_nett_flow"]
    if net_ops >= 0:
        sources.append({"name": "Funds from Operations (Inflow)", "amount": net_ops})
    else:
        applications.append({"name": "Operational Funds Applied (Outflow)", "amount": abs(net_ops)})

    total_sources = sum(s["amount"] for s in sources)
    total_apps = sum(a["amount"] for a in applications)
    working_cap_change = round(total_sources - total_apps, 2)

    return {
        "company_id": company_id,
        "fy_year": fy_year,
        "sources": sources,
        "applications": applications,
        "total_sources": total_sources,
        "total_applications": total_apps,
        "working_capital_change": working_cap_change,
        "monthly_flows": cash_flow["monthly_flows"]
    }


