"""
Dynamic Mobile Analytics Engine for Ledger Pro
Queries live accounting records from SQLite and produces dynamic metrics
for mobile dashboards, bar charts, donut charts, and customer rankings.
Strictly zero hardcoding: all figures are computed directly from vouchers & ledgers.
"""
from datetime import datetime, date
from typing import Dict, Any, List
from app.database import get_connection


def get_mobile_dashboard_data(company_id: int) -> Dict[str, Any]:
    """
    Computes all live metrics, monthly trends, and charts dynamically
    for the selected company.
    """
    conn = get_connection()
    cur = conn.cursor()

    today_str = date.today().strftime("%Y-%m-%d")
    current_month_prefix = date.today().strftime("%Y-%m")
    current_year_prefix = date.today().strftime("%Y")

    # 1. Company Info
    cur.execute("SELECT id, name, gstin, state FROM companies WHERE id = ?", (company_id,))
    comp_row = cur.fetchone()
    company_name = comp_row["name"] if comp_row else "Ledger Pro"
    gstin = (comp_row["gstin"] if comp_row else "") or ""

    # 2. Sales Metrics: Today, This Month, This Year, All-time Sales
    # Exclude zero-amount cancelled vouchers
    cur.execute("""
        SELECT 
            COALESCE(SUM(CASE WHEN voucher_date = ? THEN total_amount ELSE 0 END), 0) AS today_sales,
            COALESCE(SUM(CASE WHEN voucher_date LIKE ? THEN total_amount ELSE 0 END), 0) AS month_sales,
            COALESCE(SUM(CASE WHEN voucher_date LIKE ? THEN total_amount ELSE 0 END), 0) AS year_sales,
            COUNT(CASE WHEN voucher_date LIKE ? AND total_amount > 0 THEN 1 END) AS month_invoices_count,
            COALESCE(SUM(total_amount), 0) AS all_time_sales
        FROM vouchers
        WHERE company_id = ? 
          AND voucher_type = 'Sales' 
          AND total_amount > 0 
          AND (narration IS NULL OR narration NOT LIKE '[CANCELLED]%')
    """, (today_str, f"{current_month_prefix}%", f"{current_year_prefix}%", f"{current_month_prefix}%", company_id))
    sales_stats = cur.fetchone()

    today_sales = float(sales_stats["today_sales"])
    month_sales = float(sales_stats["month_sales"])
    year_sales = float(sales_stats["year_sales"])
    month_invoices = int(sales_stats["month_invoices_count"])
    all_time_sales = float(sales_stats["all_time_sales"])

    # 3. Cash & Bank Balances (from ledgers under 'Cash-in-hand' and 'Bank Accounts')
    cur.execute("""
        SELECT 
            g.name AS group_name,
            l.current_balance,
            l.current_balance_type
        FROM ledgers l
        JOIN ledger_groups g ON l.group_id = g.id
        WHERE l.company_id = ? AND (g.name LIKE '%Cash%' OR g.name LIKE '%Bank%')
    """, (company_id,))
    
    cash_balance = 0.0
    bank_balance = 0.0
    for row in cur.fetchall():
        bal = float(row["current_balance"] or 0.0)
        bal_type = row["current_balance_type"] or "Dr"
        # For Assets, Debit is positive, Credit is negative/overdraft
        multiplier = 1.0 if bal_type == "Dr" else -1.0
        signed_bal = bal * multiplier

        grp = row["group_name"].lower()
        if "cash" in grp:
            cash_balance += signed_bal
        elif "bank" in grp:
            bank_balance += signed_bal

    # 4. Total Receivables (Sundry Debtors)
    cur.execute("""
        SELECT 
            COALESCE(SUM(
                CASE 
                    WHEN l.current_balance_type = 'Dr' THEN l.current_balance 
                    ELSE -l.current_balance 
                END
            ), 0) AS receivables
        FROM ledgers l
        JOIN ledger_groups g ON l.group_id = g.id
        WHERE l.company_id = ? AND g.name LIKE '%Debtors%'
    """, (company_id,))
    rec_row = cur.fetchone()
    total_receivables = max(0.0, float(rec_row["receivables"]) if rec_row and rec_row["receivables"] else 0.0)

    # 5. Total Payables (Sundry Creditors)
    cur.execute("""
        SELECT 
            COALESCE(SUM(
                CASE 
                    WHEN l.current_balance_type = 'Cr' THEN l.current_balance 
                    ELSE -l.current_balance 
                END
            ), 0) AS payables
        FROM ledgers l
        JOIN ledger_groups g ON l.group_id = g.id
        WHERE l.company_id = ? AND g.name LIKE '%Creditors%'
    """, (company_id,))
    pay_row = cur.fetchone()
    total_payables = max(0.0, float(pay_row["payables"]) if pay_row and pay_row["payables"] else 0.0)

    # 6. Monthly Sales Trend (Last 6 Months for the Bar Chart)
    cur.execute("""
        SELECT 
            strftime('%Y-%m', voucher_date) AS yr_mo,
            COALESCE(SUM(total_amount), 0) AS total
        FROM vouchers
        WHERE company_id = ? 
          AND voucher_type = 'Sales' 
          AND total_amount > 0 
          AND (narration IS NULL OR narration NOT LIKE '[CANCELLED]%')
        GROUP BY yr_mo
        ORDER BY yr_mo DESC
        LIMIT 6
    """, (company_id,))
    trend_rows = cur.fetchall()

    month_names = {
        "01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr", "05": "May", "06": "Jun",
        "07": "Jul", "08": "Aug", "09": "Sep", "10": "Oct", "11": "Nov", "12": "Dec"
    }

    bar_labels = []
    bar_values = []
    for r in reversed(trend_rows):
        ym = r["yr_mo"]
        if ym and "-" in ym:
            yr, mo = ym.split("-")
            bar_labels.append(f"{month_names.get(mo, mo)} {yr}")
            bar_values.append(round(float(r["total"]), 2))

    if not bar_labels:
        curr_m = date.today().month
        curr_y = date.today().year
        # Generate last 3 calendar month labels
        for offset in [2, 1, 0]:
            m = curr_m - offset
            y = curr_y
            if m <= 0:
                m += 12
                y -= 1
            bar_labels.append(f"{date(y, m, 1).strftime('%b')} {y}")
            bar_values.append(0.0)

    # 7. Sales Breakdown by Payment Mode (Cash vs Bank vs Credit) for Donut Chart
    cur.execute("""
        SELECT 
            g.name AS group_name,
            COALESCE(SUM(v.total_amount), 0) AS total
        FROM vouchers v
        LEFT JOIN ledgers l ON v.party_ledger_id = l.id
        LEFT JOIN ledger_groups g ON l.group_id = g.id
        WHERE v.company_id = ? 
          AND v.voucher_type = 'Sales' 
          AND v.total_amount > 0 
          AND (v.narration IS NULL OR v.narration NOT LIKE '[CANCELLED]%')
        GROUP BY g.name
    """, (company_id,))
    mode_rows = cur.fetchall()

    cash_sales = 0.0
    bank_sales = 0.0
    credit_sales = 0.0
    for r in mode_rows:
        gname = (r["group_name"] or "").lower()
        val = float(r["total"])
        if "cash" in gname:
            cash_sales += val
        elif "bank" in gname:
            bank_sales += val
        else:
            credit_sales += val

    # 8. Top 5 Customers by Sales Volume
    cur.execute("""
        SELECT 
            COALESCE(l.name, 'Cash Customer') AS customer_name,
            COUNT(v.id) AS bills_count,
            COALESCE(SUM(v.total_amount), 0) AS total_spent
        FROM vouchers v
        LEFT JOIN ledgers l ON v.party_ledger_id = l.id
        WHERE v.company_id = ? 
          AND v.voucher_type = 'Sales' 
          AND v.total_amount > 0 
          AND (v.narration IS NULL OR v.narration NOT LIKE '[CANCELLED]%')
        GROUP BY v.party_ledger_id, l.name
        ORDER BY total_spent DESC
        LIMIT 5
    """, (company_id,))
    top_customers: List[Dict[str, Any]] = []
    for r in cur.fetchall():
        spent = round(float(r["total_spent"]), 2)
        pct = round((spent / all_time_sales * 100), 1) if all_time_sales > 0 else 0.0
        top_customers.append({
            "name": r["customer_name"],
            "bills": int(r["bills_count"]),
            "amount": spent,
            "percentage": pct
        })

    # 9. Recent 5 Sales Invoices
    cur.execute("""
        SELECT 
            v.voucher_number,
            v.voucher_date,
            v.total_amount,
            COALESCE(l.name, 'Cash Sale') AS customer_name
        FROM vouchers v
        LEFT JOIN ledgers l ON v.party_ledger_id = l.id
        WHERE v.company_id = ? 
          AND v.voucher_type = 'Sales' 
          AND v.total_amount > 0 
          AND (v.narration IS NULL OR v.narration NOT LIKE '[CANCELLED]%')
        ORDER BY v.voucher_date DESC, v.id DESC
        LIMIT 5
    """, (company_id,))
    recent_invoices: List[Dict[str, Any]] = []
    for r in cur.fetchall():
        recent_invoices.append({
            "voucher_number": r["voucher_number"],
            "date": r["voucher_date"],
            "customer": r["customer_name"],
            "amount": round(float(r["total_amount"]), 2)
        })

    conn.close()

    return {
        "company_name": company_name,
        "gstin": gstin,
        "synced_at": datetime.now().strftime("%I:%M %p, %d %b %Y"),
        "metrics": {
            "today_sales": round(today_sales, 2),
            "month_sales": round(month_sales, 2),
            "year_sales": round(year_sales, 2),
            "month_invoices": month_invoices,
            "cash_balance": round(cash_balance, 2),
            "bank_balance": round(bank_balance, 2),
            "total_receivables": round(total_receivables, 2),
            "total_payables": round(total_payables, 2)
        },
        "charts": {
            "bar_chart": {
                "labels": bar_labels,
                "values": bar_values
            },
            "donut_chart": {
                "labels": ["Cash Sales", "Bank / UPI", "Credit (Udhar)"],
                "values": [round(cash_sales, 2), round(bank_sales, 2), round(credit_sales, 2)]
            }
        },
        "top_customers": top_customers,
        "recent_invoices": recent_invoices
    }
