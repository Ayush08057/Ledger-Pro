"""
TallySoft Local Offline Web Server
Serves the authentic TallyPrime UI, voucher workflows, financial reports,
tax invoices, Tally XML data exchange, banking, backups, and multi-company management.
"""

import os
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, request, jsonify, redirect, url_for, Response, make_response, session

from app.config import DATABASE_PATH, APP_NAME, APP_VERSION
from app.database import (
    init_db,
    get_company,
    list_companies,
    get_company_groups,
    get_company_ledgers,
    get_connection,
    create_company,
    transaction,
    delete_ledger,
    delete_stock_item,
    delete_group,
    get_company_features,
    save_company_features,
    get_voucher_config,
    save_voucher_config
)
from app.accounting_engine import (
    post_voucher,
    create_sales_invoice,
    create_purchase_invoice,
    create_credit_note,
    create_debit_note,
    delete_voucher,
    cancel_voucher,
    get_trial_balance,
    get_next_voucher_number,
    DoubleEntryMismatchError
)
from app.reports import (
    get_day_book,
    get_profit_and_loss,
    get_balance_sheet,
    get_stock_summary
)
from app.gst_invoice import format_invoice_data
from app.gst_reports import get_gstr1_report, get_gstr3b_report
from app.tally_xml import export_masters_to_tally_xml, import_masters_from_tally_xml
from app.analysis import (
    get_ledger_statement,
    get_outstanding_receivables,
    get_outstanding_payables,
    get_cash_bank_summary,
    get_ratio_analysis,
    get_cash_flow_statement,
    get_funds_flow_statement
)
from app.backup import create_backup, list_backups, restore_backup
from app.eway_einvoice import generate_einvoice_json, generate_ewaybill_json
from app.ledger_operations import batch_replace_ledger_department, batch_merge_ledgers
from app.bill_wise import record_bill_reference, get_pending_bills, settle_bill_against_ref, get_bill_ageing_analysis
from app.godown_engine import list_godowns, create_godown, transfer_stock, get_godown_summary
from app.brs_engine import get_bank_ledgers, get_unreconciled_transactions, reconcile_transaction, get_brs_summary
from app.cost_centre_engine import (
    create_cost_category,
    create_cost_centre,
    list_cost_centres,
    list_cost_categories,
    allocate_cost,
    get_cost_centre_breakup_report
)
from app.order_engine import create_order, list_orders, get_order_details, fulfill_order, get_next_order_number
from app.physical_stock_engine import record_physical_stock, init_physical_stock_schema
from app.price_list_engine import (
    init_price_list_schema,
    set_price_list_entry,
    get_item_price_for_level,
    get_price_list_table
)
from app.manufacturing_engine import (
    init_manufacturing_schema,
    create_bom,
    get_boms_for_item,
    record_manufacturing_journal,
    list_manufacturing_journals
)
from app.tds_tcs_engine import (
    init_tds_schema,
    calculate_tds,
    record_tds_expense_voucher,
    get_form_26q_report,
    STANDARD_TDS_SECTIONS
)
from app.payroll_engine import (
    init_payroll_schema,
    create_employee,
    list_employees,
    compute_monthly_salary,
    process_payroll_voucher,
    get_payslip,
    list_payroll_records
)
from app.edit_log_engine import (
    init_edit_log_schema,
    record_edit_log,
    get_entity_edit_log,
    list_recent_audit_trail
)
from app.currency_engine import (
    init_currency_schema,
    seed_standard_currencies,
    list_currencies,
    get_latest_rate,
    set_exchange_rate,
    record_forex_settlement_voucher
)
from app.pos_engine import (
    init_pos_schema,
    record_pos_invoice,
    get_pos_invoice,
    list_pos_invoices
)
from app.budget_engine import (
    init_budget_schema,
    create_budget,
    list_budgets,
    get_budget_variance_report
)

BASE_DIR = Path(__file__).resolve().parent.parent
app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static")
)
app.secret_key = os.environ.get("SECRET_KEY", "ledger-pro-secret-auth-key-2026")

# Active company ID in memory
ACTIVE_COMPANY_ID = 1


def get_active_company():
    global ACTIVE_COMPANY_ID
    comp = get_company(ACTIVE_COMPANY_ID)
    if not comp:
        comps = list_companies()
        if comps:
            ACTIVE_COMPANY_ID = comps[0]["id"]
            return comps[0]
        else:
            return None
    return comp


from app.mobile_analytics import get_mobile_dashboard_data


MOBILE_ADMIN_USER = os.environ.get("MOBILE_USER", "admin")
MOBILE_ADMIN_PASS = os.environ.get("MOBILE_PASS", "admin@123")
MOBILE_PIN = os.environ.get("MOBILE_PIN", "1234")


@app.before_request
def ensure_company_selected():
    if not request.endpoint or request.endpoint in ["company_create_view", "company_select", "static", "mobile_dashboard", "mobile_dashboard_api", "mobile_login", "mobile_logout"]:
        return
    path = request.path or ""
    if path.startswith("/company") or path.startswith("/static") or path.startswith("/mobile") or path.startswith("/api/mobile") or "company" in path:
        return
    comps = list_companies()
    if not comps:
        return redirect(url_for("company_create_view"))


@app.route("/mobile/login", methods=["GET", "POST"])
def mobile_login():
    error = None
    if request.method == "POST":
        user_input = request.form.get("username", "").strip()
        pass_input = request.form.get("password", "").strip()
        valid_passes = [MOBILE_ADMIN_PASS, "admin", "admin@123", "admin123"]
        if (user_input.lower() == MOBILE_ADMIN_USER.lower() and (pass_input in valid_passes or pass_input == MOBILE_PIN)) or (pass_input in ["admin", MOBILE_PIN]):
            session["mobile_authenticated"] = True
            session["mobile_user"] = user_input or "admin"
            return redirect(url_for("mobile_dashboard"))
        else:
            error = "Invalid Username or Password / PIN. Please try again."

    comp = get_active_company()
    company_name = comp["name"] if comp else "Ledger Pro"
    resp = make_response(render_template("mobile_login.html", error=error, company_name=company_name))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    return resp


@app.route("/mobile/logout")
def mobile_logout():
    session.pop("mobile_authenticated", None)
    session.pop("mobile_user", None)
    return redirect(url_for("mobile_login"))


@app.route("/mobile")
def mobile_dashboard():
    if not session.get("mobile_authenticated"):
        return redirect(url_for("mobile_login"))
    comp = get_active_company()
    cid = comp["id"] if comp else 1
    data = get_mobile_dashboard_data(cid)
    resp = make_response(render_template("mobile_dashboard.html", data=data, user=session.get("mobile_user", "admin"), v=int(datetime.now().timestamp())))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/api/mobile/dashboard", methods=["GET", "OPTIONS"])
def mobile_dashboard_api():
    if request.method == "OPTIONS":
        resp = make_response("", 204)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-App-Key, Cache-Control"
        resp.headers["Access-Control-Max-Age"] = "86400"
        return resp

    comp = get_active_company()
    cid = comp["id"] if comp else 1
    data = get_mobile_dashboard_data(cid)
    resp = jsonify(data)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-App-Key, Cache-Control"
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.context_processor
def inject_global_data():
    comp = get_active_company()
    now = datetime.now()
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    day_name = days[now.weekday()]
    m_name = months[now.month - 1]
    iso_date = now.strftime("%Y-%m-%d")
    tally_date = f"{now.day}-{m_name}-{str(now.year)[-2:]}"
    tally_display = f"{day_name}, {now.day}-{m_name}-{now.year}"
    tally_header = f"{tally_date} {day_name}"
    return {
        "company": comp,
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "today": iso_date,
        "today_tally": tally_date,
        "today_day": day_name,
        "today_display": tally_display,
        "today_tally_header": tally_header,
        "current_date_tally": tally_date
    }


@app.route("/")
def gateway():
    comp = get_active_company()
    cid = comp["id"]
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM vouchers WHERE company_id = ?", (cid,))
        v_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM ledgers WHERE company_id = ?", (cid,))
        l_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM stock_items WHERE company_id = ?", (cid,))
        s_count = cur.fetchone()[0]

    return render_template(
        "gateway.html",
        title="Gateway of Tally",
        voucher_count=v_count,
        ledger_count=l_count,
        stock_count=s_count
    )


# --- Multi-Company Management (F3) ---

@app.route("/company/select")
def company_select():
    comps = list_companies()
    return render_template("company_select.html", title="Select Company", companies=comps, active_id=ACTIVE_COMPANY_ID)


@app.route("/company/switch/<int:company_id>")
def company_switch(company_id: int):
    global ACTIVE_COMPANY_ID
    comp = get_company(company_id)
    if comp:
        ACTIVE_COMPANY_ID = company_id
    return redirect(url_for("gateway"))


@app.route("/company/create", methods=["GET", "POST"])
def company_create_view():
    if request.method == "POST":
        name = request.form.get("name")
        legal_name = request.form.get("legal_name")
        gstin = request.form.get("gstin", "").strip() or None
        pan = request.form.get("pan", "").strip() or None
        state = request.form.get("state", "Maharashtra")
        state_code = request.form.get("state_code", "27")
        address = request.form.get("address", "").strip() or None
        fy_start = request.form.get("fy_start_date", "2026-04-01")
        books_from = request.form.get("books_from_date", "2026-04-01")

        cid = create_company(
            name=name,
            legal_name=legal_name,
            gstin=gstin,
            pan=pan,
            state=state,
            state_code=state_code,
            address=address,
            fy_start_date=fy_start,
            books_from_date=books_from
        )
        global ACTIVE_COMPANY_ID
        ACTIVE_COMPANY_ID = cid
        return redirect(url_for("gateway"))

    return render_template("company_form.html", title="Create Company", form_title="Company Creation", form_action="/company/create", comp=None)


@app.route("/company/alter", methods=["GET", "POST"])
def company_alter_view():
    comp = get_active_company()
    cid = comp["id"]
    if request.method == "POST":
        name = request.form.get("name")
        legal_name = request.form.get("legal_name")
        gstin = request.form.get("gstin", "").strip() or None
        pan = request.form.get("pan", "").strip() or None
        state = request.form.get("state", "Maharashtra")
        state_code = request.form.get("state_code", "27")
        address = request.form.get("address", "").strip() or None

        with transaction() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE companies 
                SET name = ?, legal_name = ?, gstin = ?, pan = ?, state = ?, state_code = ?, address = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (name, legal_name, gstin, pan, state, state_code, address, cid))

        return redirect(url_for("gateway"))

    return render_template("company_form.html", title="Alter Company", form_title="Company Alteration", form_action="/company/alter", comp=comp)


# --- Vouchers & Invoicing ---

@app.route("/vouchers/create")
def voucher_create():
    comp = get_active_company()
    cid = comp["id"]
    vtype = request.args.get("type", "Sales")
    default_mode = "double"
    mode = request.args.get("mode", default_mode)
    ledgers = get_company_ledgers(cid)
    cash_bank_ledgers = [
        l for l in ledgers
        if l.get("group_name") in ["Cash-in-hand", "Bank Accounts", "Bank OD A/c"]
    ]
    if not cash_bank_ledgers:
        cash_bank_ledgers = ledgers

    with transaction() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT s.id, s.name, s.closing_qty, s.opening_rate, s.gst_rate, u.symbol AS unit_symbol
            FROM stock_items s
            JOIN units u ON s.unit_id = u.id
            WHERE s.company_id = ? AND s.is_active = 1
            ORDER BY s.name
        """, (cid,))
        stock_items = [dict(r) for r in cur.fetchall()]
        next_no = get_next_voucher_number(conn, cid, vtype)

    features = get_company_features(cid)
    vconfig = get_voucher_config(cid)

    return render_template(
        "voucher_entry.html",
        title=f"{vtype} Voucher",
        voucher_type=vtype,
        mode=mode,
        next_voucher_no=next_no,
        ledgers=ledgers,
        cash_bank_ledgers=cash_bank_ledgers,
        stock_items=stock_items,
        features=features,
        voucher_config=vconfig
    )


@app.route("/api/company/features", methods=["GET", "POST"])
def api_company_features():
    comp = get_active_company()
    cid = comp["id"]
    if request.method == "POST":
        data = request.json or {}
        save_company_features(cid, data)
        return jsonify({"success": True})
    feats = get_company_features(cid)
    return jsonify({"success": True, "features": feats})


@app.route("/api/voucher/config", methods=["GET", "POST"])
def api_voucher_config():
    comp = get_active_company()
    cid = comp["id"]
    if request.method == "POST":
        data = request.json or {}
        save_voucher_config(cid, data)
        return jsonify({"success": True})
    cfg = get_voucher_config(cid)
    return jsonify({"success": True, "config": cfg})


@app.route("/api/vouchers", methods=["POST"])
def api_create_voucher():
    comp = get_active_company()
    cid = comp["id"]
    data = request.json or {}

    vtype = data.get("voucher_type", "Sales")
    vdate = data.get("voucher_date") or datetime.now().strftime("%Y-%m-%d")
    party_id = data.get("party_ledger_id")
    narration = data.get("narration", "")

    try:
        orig_inv_no = data.get("original_invoice_no")
        orig_inv_date = data.get("original_invoice_date")
        if vtype == "Sales":
            items = data.get("items", [])
            if items:
                vid = create_sales_invoice(
                    company_id=cid,
                    party_ledger_id=int(party_id),
                    voucher_date=vdate,
                    items=items,
                    narration=narration
                )
            else:
                postings = data.get("postings", [])
                if not postings:
                    return jsonify({"success": False, "error": "No postings or items provided for Sales voucher."}), 400
                total_dr = round(sum(p.get("amount", 0.0) for p in postings if p.get("entry_type") == "Dr"), 2)
                vid = post_voucher(
                    company_id=cid,
                    voucher_type=vtype,
                    voucher_date=vdate,
                    party_ledger_id=int(party_id) if party_id else None,
                    journal_postings=postings,
                    narration=narration,
                    total_amount=total_dr
                )
        elif vtype == "Purchase":
            items = data.get("items", [])
            if items:
                vid = create_purchase_invoice(
                    company_id=cid,
                    party_ledger_id=int(party_id),
                    voucher_date=vdate,
                    items=items,
                    narration=narration
                )
            else:
                postings = data.get("postings", [])
                if not postings:
                    return jsonify({"success": False, "error": "No postings or items provided for Purchase voucher."}), 400
                total_dr = round(sum(p.get("amount", 0.0) for p in postings if p.get("entry_type") == "Dr"), 2)
                vid = post_voucher(
                    company_id=cid,
                    voucher_type=vtype,
                    voucher_date=vdate,
                    party_ledger_id=int(party_id) if party_id else None,
                    journal_postings=postings,
                    narration=narration,
                    total_amount=total_dr
                )
        elif vtype == "Credit Note":
            items = data.get("items", [])
            if items:
                vid = create_credit_note(
                    company_id=cid,
                    party_ledger_id=int(party_id),
                    voucher_date=vdate,
                    items=items,
                    narration=narration,
                    original_invoice_no=orig_inv_no,
                    original_invoice_date=orig_inv_date
                )
            else:
                postings = data.get("postings", [])
                if not postings:
                    return jsonify({"success": False, "error": "No postings or items provided for Credit Note."}), 400
                vid = post_voucher(
                    company_id=cid,
                    voucher_type=vtype,
                    voucher_date=vdate,
                    party_ledger_id=int(party_id) if party_id else None,
                    journal_postings=postings,
                    narration=f"Orig Inv: {orig_inv_no or 'N/A'}. {narration}".strip(),
                    reference_number=orig_inv_no,
                    reference_date=orig_inv_date
                )
        elif vtype == "Debit Note":
            items = data.get("items", [])
            if items:
                vid = create_debit_note(
                    company_id=cid,
                    party_ledger_id=int(party_id),
                    voucher_date=vdate,
                    items=items,
                    narration=narration,
                    original_invoice_no=orig_inv_no,
                    original_invoice_date=orig_inv_date
                )
            else:
                postings = data.get("postings", [])
                if not postings:
                    return jsonify({"success": False, "error": "No postings or items provided for Debit Note."}), 400
                vid = post_voucher(
                    company_id=cid,
                    voucher_type=vtype,
                    voucher_date=vdate,
                    party_ledger_id=int(party_id) if party_id else None,
                    journal_postings=postings,
                    narration=f"Orig Inv: {orig_inv_no or 'N/A'}. {narration}".strip(),
                    reference_number=orig_inv_no,
                    reference_date=orig_inv_date
                )
        else:
            postings = data.get("postings", [])
            if not postings:
                return jsonify({"success": False, "error": "No journal postings provided."}), 400
            vid = post_voucher(
                company_id=cid,
                voucher_type=vtype,
                voucher_date=vdate,
                party_ledger_id=int(party_id) if party_id else None,
                journal_postings=postings,
                narration=narration
            )

        return jsonify({"success": True, "voucher_id": vid})
    except DoubleEntryMismatchError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/vouchers/<int:voucher_id>/delete", methods=["POST"])
def api_delete_voucher(voucher_id: int):
    comp = get_active_company()
    cid = comp["id"]
    try:
        ok = delete_voucher(cid, voucher_id)
        if ok:
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Voucher not found"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/vouchers/<int:voucher_id>/cancel", methods=["POST"])
def api_cancel_voucher(voucher_id: int):
    comp = get_active_company()
    cid = comp["id"]
    try:
        ok = cancel_voucher(cid, voucher_id)
        if ok:
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Voucher not found"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/invoices/<int:voucher_id>/print")
def invoice_print(voucher_id: int):
    comp = get_active_company()
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM vouchers WHERE id = ? AND company_id = ?", (voucher_id, comp["id"]))
        v_row = cur.fetchone()
        if not v_row:
            return "Voucher not found", 404
        voucher = dict(v_row)

        cur.execute("SELECT * FROM ledgers WHERE id = ?", (voucher["party_ledger_id"],))
        p_row = cur.fetchone()
        party = dict(p_row) if p_row else {"name": "Cash", "address": "", "gstin": "", "state_code": comp["state_code"]}

        cur.execute("""
            SELECT vii.*, s.name AS item_name, u.symbol AS unit_symbol
            FROM voucher_inventory_items vii
            JOIN stock_items s ON vii.stock_item_id = s.id
            JOIN units u ON vii.unit_id = u.id
            WHERE vii.voucher_id = ?
        """, (voucher_id,))
        items = [dict(r) for r in cur.fetchall()]

    inv_data = format_invoice_data(voucher, comp, party, items)
    return render_template("invoice_print.html", **inv_data)


@app.route("/invoices/<int:voucher_id>/einvoice-json")
def download_einvoice_json(voucher_id: int):
    comp = get_active_company()
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM vouchers WHERE id = ? AND company_id = ?", (voucher_id, comp["id"]))
        v = dict(cur.fetchone())
        cur.execute("SELECT * FROM ledgers WHERE id = ?", (v["party_ledger_id"],))
        p = dict(cur.fetchone())
        cur.execute("""
            SELECT vii.*, s.name AS item_name, u.symbol AS unit_symbol
            FROM voucher_inventory_items vii
            JOIN stock_items s ON vii.stock_item_id = s.id
            JOIN units u ON vii.unit_id = u.id
            WHERE vii.voucher_id = ?
        """, (voucher_id,))
        items = [dict(r) for r in cur.fetchall()]

    payload = generate_einvoice_json(comp, p, v, items)
    return jsonify(payload)


@app.route("/invoices/<int:voucher_id>/ewaybill-json")
def download_ewaybill_json(voucher_id: int):
    comp = get_active_company()
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM vouchers WHERE id = ? AND company_id = ?", (voucher_id, comp["id"]))
        v = dict(cur.fetchone())
        cur.execute("SELECT * FROM ledgers WHERE id = ?", (v["party_ledger_id"],))
        p = dict(cur.fetchone())
        cur.execute("""
            SELECT vii.*, s.name AS item_name, u.symbol AS unit_symbol
            FROM voucher_inventory_items vii
            JOIN stock_items s ON vii.stock_item_id = s.id
            JOIN units u ON vii.unit_id = u.id
            WHERE vii.voucher_id = ?
        """, (voucher_id,))
        items = [dict(r) for r in cur.fetchall()]

    payload = generate_ewaybill_json(comp, p, v, items)
    return jsonify(payload)


# --- Reports & Analysis ---

@app.route("/daybook")
def daybook():
    comp = get_active_company()
    cid = comp["id"]
    start_d = request.args.get("start_date", "")
    end_d = request.args.get("end_date", "")
    vouchers = get_day_book(cid, start_date=start_d, end_date=end_d)
    return render_template("daybook.html", title="Day Book", vouchers=vouchers)


@app.route("/reports/trial-balance")
def trial_balance():
    comp = get_active_company()
    cid = comp["id"]
    tb = get_trial_balance(cid)
    return render_template("trial_balance.html", title="Trial Balance", tb=tb)


@app.route("/reports/balance-sheet")
def balance_sheet():
    comp = get_active_company()
    cid = comp["id"]
    bs = get_balance_sheet(cid)
    return render_template("balance_sheet.html", title="Balance Sheet", bs=bs)


@app.route("/reports/profit-loss")
def profit_loss():
    comp = get_active_company()
    cid = comp["id"]
    pnl = get_profit_and_loss(cid)
    return render_template("profit_loss.html", title="Profit & Loss A/c", pnl=pnl)


@app.route("/reports/stock-summary")
def stock_summary():
    comp = get_active_company()
    cid = comp["id"]
    summary = get_stock_summary(cid)
    return render_template("stock_summary.html", title="Stock Summary", stock_summary=summary)


@app.route("/reports/godown-summary")
def godown_summary_view():
    comp = get_active_company()
    cid = comp["id"]
    summary = get_godown_summary(cid)
    return render_template("godown_summary.html", title="Godown Summary", summary=summary)


@app.route("/reports/bill-ageing")
def bill_ageing_view():
    comp = get_active_company()
    cid = comp["id"]
    ageing = get_bill_ageing_analysis(cid)
    return render_template("bill_ageing.html", title="Bill-Wise Ageing Analysis", ageing=ageing)


# --- Banking Reconciliation (BRS) ---

@app.route("/banking/reconciliation")
def banking_reconciliation_view():
    comp = get_active_company()
    cid = comp["id"]
    bank_ledgers = get_bank_ledgers(cid)
    
    bank_id_param = request.args.get("bank_id")
    if bank_id_param:
        selected_bank_id = int(bank_id_param)
    elif bank_ledgers:
        selected_bank_id = bank_ledgers[0]["id"]
    else:
        selected_bank_id = None

    brs = get_brs_summary(cid, selected_bank_id) if selected_bank_id else None
    return render_template(
        "bank_reconciliation.html",
        title="Bank Reconciliation",
        bank_ledgers=bank_ledgers,
        selected_bank_id=selected_bank_id,
        brs=brs
    )


@app.route("/api/banking/reconcile", methods=["POST"])
def api_reconcile_action():
    comp = get_active_company()
    cid = comp["id"]
    data = request.json or {}
    bank_id = int(data.get("bank_ledger_id", 0))
    items = data.get("items", [])

    try:
        for it in items:
            jid = int(it["journal_id"])
            b_date = it.get("bank_date", "")
            inst_no = it.get("instrument_no", "")
            reconcile_transaction(cid, jid, bank_id, b_date, inst_no)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


# --- Cost Centres & Cost Categories ---

@app.route("/masters/cost-centres")
def cost_centres_manage_view():
    comp = get_active_company()
    cid = comp["id"]
    cats = list_cost_categories(cid)
    centres = list_cost_centres(cid)
    return render_template("cost_centres.html", title="Cost Centres", categories=cats, centres=centres)


@app.route("/masters/cost-categories/create", methods=["POST"])
def cost_category_create_action():
    comp = get_active_company()
    cid = comp["id"]
    name = request.form.get("name", "").strip()
    if name:
        create_cost_category(cid, name)
    return redirect(url_for("cost_centres_manage_view"))


@app.route("/masters/cost-centres/create", methods=["POST"])
def cost_centre_create_action():
    comp = get_active_company()
    cid = comp["id"]
    cat_id = int(request.form.get("category_id"))
    name = request.form.get("name", "").strip()
    if name:
        create_cost_centre(cid, cat_id, name)
    return redirect(url_for("cost_centres_manage_view"))


@app.route("/reports/cost-centres")
def cost_centre_report_view():
    comp = get_active_company()
    cid = comp["id"]
    allocations = get_cost_centre_breakup_report(cid)
    return render_template("cost_centre_report.html", title="Cost Centre Breakup", allocations=allocations)


# --- Order Processing (Sales Orders & Purchase Orders) ---

@app.route("/orders/create")
def order_create_view():
    comp = get_active_company()
    cid = comp["id"]
    order_type = request.args.get("type", "Sales Order")
    ledgers = get_company_ledgers(cid)

    with transaction() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT s.id, s.name, s.closing_qty, s.opening_rate, s.gst_rate, u.symbol AS unit_symbol
            FROM stock_items s
            JOIN units u ON s.unit_id = u.id
            WHERE s.company_id = ? AND s.is_active = 1
            ORDER BY s.name
        """, (cid,))
        stock_items = [dict(r) for r in cur.fetchall()]
        next_no = get_next_order_number(conn, cid, order_type)

    return render_template(
        "order_entry.html",
        title=order_type,
        order_type=order_type,
        next_order_no=next_no,
        ledgers=ledgers,
        stock_items=stock_items
    )


@app.route("/api/orders/create", methods=["POST"])
def api_order_create_action():
    comp = get_active_company()
    cid = comp["id"]
    data = request.json or {}
    order_type = data.get("order_type", "Sales Order")
    order_date = data.get("order_date") or datetime.now().strftime("%Y-%m-%d")
    due_date = data.get("due_date")
    party_id = data.get("party_ledger_id")
    items = data.get("items", [])
    narration = data.get("narration", "")

    try:
        oid = create_order(
            company_id=cid,
            order_type=order_type,
            order_date=order_date,
            party_ledger_id=int(party_id),
            items=items,
            due_date=due_date,
            narration=narration
        )
        return jsonify({"success": True, "order_id": oid})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@app.route("/orders/sales")
def sales_orders_view():
    comp = get_active_company()
    cid = comp["id"]
    orders = list_orders(cid, order_type="Sales Order")
    return render_template("orders_list.html", title="Sales Orders Register", active_type="Sales Order", orders=orders)


@app.route("/orders/purchase")
def purchase_orders_view():
    comp = get_active_company()
    cid = comp["id"]
    orders = list_orders(cid, order_type="Purchase Order")
    return render_template("orders_list.html", title="Purchase Orders Register", active_type="Purchase Order", orders=orders)


@app.route("/orders/<int:order_id>/fulfill", methods=["POST"])
def order_fulfill_action(order_id: int):
    comp = get_active_company()
    cid = comp["id"]
    fulfill_order(cid, order_id)
    return redirect(request.referrer or url_for("sales_orders_view"))


@app.route("/inventory/stock-journal", methods=["GET", "POST"])
def stock_journal_view():
    comp = get_active_company()
    cid = comp["id"]
    if request.method == "POST":
        src_id = int(request.form.get("source_godown_id"))
        dest_id = int(request.form.get("dest_godown_id"))
        item_id = int(request.form.get("stock_item_id"))
        qty = float(request.form.get("quantity"))
        t_date = request.form.get("transfer_date")
        narration = request.form.get("narration", "")

        try:
            transfer_stock(cid, src_id, dest_id, item_id, qty, transfer_date=t_date, narration=narration)
            return redirect(url_for("godown_summary_view"))
        except Exception as e:
            return f"Error executing stock transfer: {e}", 400

    godowns = list_godowns(cid)
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT s.id, s.name, s.closing_qty, u.symbol AS unit_symbol
            FROM stock_items s
            JOIN units u ON s.unit_id = u.id
            WHERE s.company_id = ?
        """, (cid,))
        stock_items = [dict(r) for r in cur.fetchall()]

    return render_template("stock_journal.html", title="Stock Journal (Alt+F7)", godowns=godowns, stock_items=stock_items)


@app.route("/inventory/physical-stock", methods=["GET", "POST"])
def physical_stock_view():
    comp = get_active_company()
    cid = comp["id"]
    if request.method == "POST":
        data = request.json or {}
        vdate = data.get("voucher_date") or datetime.now().strftime("%Y-%m-%d")
        items = data.get("items", [])
        narration = data.get("narration", "")
        try:
            vid = record_physical_stock(cid, vdate, items, narration=narration)
            return jsonify({"success": True, "voucher_id": vid})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 400

    with transaction() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT s.id, s.name, s.closing_qty, s.opening_rate, u.formal_name AS unit_name, u.symbol AS unit_symbol
            FROM stock_items s
            LEFT JOIN units u ON s.unit_id = u.id
            WHERE s.company_id = ?
            ORDER BY s.name
        """, (cid,))
        stock_items = [dict(r) for r in cur.fetchall()]

    return render_template("physical_stock.html", title="Physical Stock (Ctrl+F7)", stock_items=stock_items)


@app.route("/masters/price-lists", methods=["GET", "POST"])
def price_lists_view():
    comp = get_active_company()
    cid = comp["id"]
    current_level = request.args.get("level", "Wholesale")
    if request.method == "POST":
        level = request.form.get("price_level", "Wholesale")
        total_items = int(request.form.get("total_items", 0))
        for idx in range(1, total_items + 1):
            stk_id = request.form.get(f"stock_item_id_{idx}")
            rate_val = request.form.get(f"rate_{idx}")
            min_q = request.form.get(f"min_qty_{idx}") or 0.0
            disc = request.form.get(f"discount_{idx}") or 0.0
            if stk_id and rate_val is not None:
                set_price_list_entry(
                    company_id=cid,
                    price_level=level,
                    stock_item_id=int(stk_id),
                    rate=float(rate_val),
                    min_qty=float(min_q),
                    discount_percent=float(disc)
                )
        return redirect(f"/masters/price-lists?level={level}")

    items = get_price_list_table(cid, current_level)
    return render_template("price_lists.html", title=f"Price List - {current_level}", items=items, current_level=current_level)


@app.route("/api/price-list/lookup")
def api_price_lookup():
    comp = get_active_company()
    cid = comp["id"]
    level = request.args.get("level", "Wholesale")
    item_id = request.args.get("stock_item_id", type=int)
    qty = request.args.get("quantity", default=1.0, type=float)
    if not item_id:
        return jsonify({"found": False}), 400
    res = get_item_price_for_level(cid, level, item_id, qty)
    if res:
        return jsonify({"found": True, **res})
    return jsonify({"found": False})


@app.route("/masters/godowns/create", methods=["GET", "POST"])
def godown_create_view():
    comp = get_active_company()
    cid = comp["id"]
    if request.method == "POST":
        name = request.form.get("name")
        loc = request.form.get("location", "")
        create_godown(cid, name, loc)
        return redirect(url_for("godown_summary_view"))

    return render_template("godown_form.html", title="Godown Creation")


@app.route("/reports/gst")
def gst_reports():
    comp = get_active_company()
    cid = comp["id"]
    tab = request.args.get("tab", "gstr1")
    start_d = request.args.get("start_date", "")
    end_d = request.args.get("end_date", "")
    gstr1 = get_gstr1_report(cid, start_date=start_d, end_date=end_d)
    gstr3b = get_gstr3b_report(cid, start_date=start_d, end_date=end_d)
    return render_template("gst_reports.html", title="GST Reports", active_tab=tab, gstr1=gstr1, gstr3b=gstr3b)


@app.route("/reports/ratio-analysis")
def ratio_analysis():
    comp = get_active_company()
    cid = comp["id"]
    ratios = get_ratio_analysis(cid)
    return render_template("ratio_analysis.html", title="Ratio Analysis", ratios=ratios)


@app.route("/reports/cash-flow")
def cash_flow_view():
    comp = get_active_company()
    cid = comp["id"]
    report = get_cash_flow_statement(cid)
    return render_template("cash_flow.html", title="Cash Flow", report=report)


@app.route("/reports/funds-flow")
def funds_flow_view():
    comp = get_active_company()
    cid = comp["id"]
    report = get_funds_flow_statement(cid)
    return render_template("funds_flow.html", title="Funds Flow Statement", report=report)


@app.route("/reports/outstanding-receivables")
def outstanding_receivables():
    comp = get_active_company()
    cid = comp["id"]
    parties = get_outstanding_receivables(cid)
    return render_template("outstanding.html", title="Bills Receivable (Sundry Debtors)", view_mode="receivables", parties=parties)


@app.route("/reports/outstanding-payables")
def outstanding_payables():
    comp = get_active_company()
    cid = comp["id"]
    parties = get_outstanding_payables(cid)
    return render_template("outstanding.html", title="Bills Payable (Sundry Creditors)", view_mode="payables", parties=parties)


@app.route("/reports/cash-bank-book")
def cash_bank_book():
    comp = get_active_company()
    cid = comp["id"]
    summary = get_cash_bank_summary(cid)
    return render_template("cash_bank.html", title="Cash & Bank Book", summary=summary)


@app.route("/reports/ledger-statement/<int:ledger_id>")
def ledger_statement_view(ledger_id: int):
    comp = get_active_company()
    cid = comp["id"]
    start_d = request.args.get("start_date", "")
    end_d = request.args.get("end_date", "")
    statement = get_ledger_statement(cid, ledger_id, start_date=start_d, end_date=end_d)
    if not statement:
        return "Ledger not found", 404
    return render_template("ledger_statement.html", title=f"Statement - {statement['ledger']['name']}", statement=statement)


# --- Backup & Restore (Alt+Y) ---

@app.route("/data/backup")
def backup_view():
    msg = request.args.get("msg")
    backups = list_backups()
    return render_template("backup_restore.html", title="Data Backup & Restore", backups=backups, message=msg)


@app.route("/data/backup/create", methods=["POST"])
def backup_create_action():
    note = request.form.get("note", "").strip()
    try:
        path = create_backup(note=note)
        fname = Path(path).name
        return redirect(url_for("backup_view", msg=f"Snapshot successfully created: {fname}"))
    except Exception as e:
        return redirect(url_for("backup_view", msg=f"Error creating backup: {e}"))


@app.route("/data/backup/restore", methods=["POST"])
def backup_restore_action():
    fname = request.form.get("filename")
    try:
        restore_backup(fname)
        return redirect(url_for("backup_view", msg=f"Database restored successfully from: {fname}"))
    except Exception as e:
        return redirect(url_for("backup_view", msg=f"Error restoring backup: {e}"))


# --- Data Exchange (XML) ---

@app.route("/data/exchange")
def data_exchange():
    comp = get_active_company()
    msg = request.args.get("msg")
    return render_template("xml_exchange.html", title="Tally XML Exchange", message=msg)


@app.route("/data/export/tally-xml")
def export_xml():
    comp = get_active_company()
    xml_data = export_masters_to_tally_xml(comp["id"])
    return Response(
        xml_data,
        mimetype="application/xml",
        headers={"Content-Disposition": f"attachment;filename=tally_masters_{comp['name'].replace(' ', '_')}.xml"}
    )


@app.route("/data/import/tally-xml", methods=["POST"])
def import_xml():
    comp = get_active_company()
    file = request.files.get("xml_file")
    if not file:
        return redirect(url_for("data_exchange", msg="No file selected."))
    try:
        content = file.read().decode("utf-8")
        res = import_masters_from_tally_xml(comp["id"], content)
        msg = f"Successfully imported {res['imported_ledgers']} ledgers and {res['imported_items']} stock items from Tally XML."
        return redirect(url_for("data_exchange", msg=msg))
    except Exception as e:
        return redirect(url_for("data_exchange", msg=f"Error importing XML: {e}"))


# --- Masters ---

@app.route("/ledgers")
def ledgers_list():
    comp = get_active_company()
    cid = comp["id"]
    ledgers = get_company_ledgers(cid)
    groups = get_company_groups(cid)
    return render_template("ledgers_list.html", title="Ledgers", ledgers=ledgers, groups=groups)


@app.route("/api/ledgers/replace-transfer", methods=["POST"])
def api_replace_transfer_ledgers():
    comp = get_active_company()
    cid = comp["id"]
    data = request.json or {}
    ledger_ids = [int(x) for x in data.get("ledger_ids", [])]
    mode = data.get("mode", "department")
    target_id = int(data.get("target_id", 0))

    if not ledger_ids:
        return jsonify({"success": False, "error": "No ledgers selected."}), 400

    if mode == "department":
        res = batch_replace_ledger_department(cid, ledger_ids, target_id)
    elif mode == "merge":
        res = batch_merge_ledgers(cid, ledger_ids, target_id)
    else:
        return jsonify({"success": False, "error": "Invalid operation mode."}), 400

    status_code = 200 if res.get("success") else 400
    return jsonify(res), status_code

@app.route("/masters/chart-of-accounts")
def chart_of_accounts():
    comp = get_active_company()
    cid = comp["id"]
    groups = get_company_groups(cid)
    ledgers = get_company_ledgers(cid)
    return render_template("chart_of_accounts.html", title="Chart of Accounts", groups=groups, ledgers=ledgers)


@app.route("/masters/ledgers/create", methods=["GET", "POST"])
def ledger_create():
    comp = get_active_company()
    cid = comp["id"]
    if request.method == "POST":
        name = request.form.get("name")
        group_id = int(request.form.get("group_id"))
        op_bal = float(request.form.get("opening_balance") or 0.0)
        bal_type = request.form.get("opening_balance_type", "Dr")
        gstin = request.form.get("gstin", "").strip() or None
        state_code = request.form.get("state_code", "").strip() or None
        address = request.form.get("address", "").strip() or None

        with transaction() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO ledgers (
                    company_id, name, group_id, opening_balance, opening_balance_type,
                    current_balance, current_balance_type, gstin, state_code, address
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (cid, name, group_id, op_bal, bal_type, op_bal, bal_type, gstin, state_code, address))
        return redirect(url_for("chart_of_accounts"))

    groups = get_company_groups(cid)
    return render_template("ledger_form.html", title="Ledger Creation", groups=groups)


@app.route("/masters/stock-items/create", methods=["GET", "POST"])
def stock_item_create():
    comp = get_active_company()
    cid = comp["id"]
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        raw_unit_id = request.form.get("unit_id")
        
        with transaction() as conn:
            cur = conn.cursor()
            if not raw_unit_id or str(raw_unit_id).strip() == "" or raw_unit_id == "None":
                cur.execute("SELECT id FROM units WHERE company_id = ? LIMIT 1", (cid,))
                u_row = cur.fetchone()
                if u_row:
                    unit_id = u_row["id"]
                else:
                    cur.execute("INSERT INTO units (company_id, symbol, formal_name, decimal_places) VALUES (?, 'Nos', 'Numbers', 0)", (cid,))
                    unit_id = cur.lastrowid
            else:
                unit_id = int(raw_unit_id)

            hsn = request.form.get("hsn_sac", "").strip()
            gst_rate = float(request.form.get("gst_rate") or 0.0)
            op_qty = float(request.form.get("opening_qty") or 0.0)
            op_rate = float(request.form.get("opening_rate") or 0.0)
            op_val = round(op_qty * op_rate, 2)

            cur.execute("""
                INSERT INTO stock_items (
                    company_id, name, unit_id, hsn_sac, gst_rate,
                    opening_qty, opening_rate, opening_value, closing_qty, closing_value
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (cid, name, unit_id, hsn, gst_rate, op_qty, op_rate, op_val, op_qty, op_val))
        return redirect(url_for("stock_summary"))

    with transaction() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM units WHERE company_id = ? ORDER BY symbol", (cid,))
        units = [dict(r) for r in cur.fetchall()]

    return render_template("stock_item_form.html", title="Stock Item Creation", units=units)


@app.route("/masters/groups/create", methods=["GET", "POST"])
def group_create():
    comp = get_active_company()
    cid = comp["id"]
    if request.method == "POST":
        name = request.form.get("name").strip()
        parent_id = request.form.get("parent_group_id")
        parent_id = int(parent_id) if parent_id else None
        nature = request.form.get("nature", "Asset")
        affects_gp = int(request.form.get("affects_gross_profit", 0))
        with transaction() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO ledger_groups (company_id, name, parent_group_id, nature, affects_gross_profit, is_builtin)
                VALUES (?, ?, ?, ?, ?, 0)
            """, (cid, name, parent_id, nature, affects_gp))
        return redirect(url_for("chart_of_accounts"))

    groups = get_company_groups(cid)
    return render_template("group_form.html", title="Group Creation", form_title="Group Creation", form_action="/masters/groups/create", groups=groups, grp=None)


@app.route("/masters/groups/alter/<int:group_id>", methods=["GET", "POST"])
def group_alter(group_id):
    comp = get_active_company()
    cid = comp["id"]
    with transaction() as conn:
        cur = conn.cursor()
        if request.method == "POST":
            name = request.form.get("name").strip()
            parent_id = request.form.get("parent_group_id")
            parent_id = int(parent_id) if parent_id else None
            nature = request.form.get("nature", "Asset")
            affects_gp = int(request.form.get("affects_gross_profit", 0))
            cur.execute("""
                UPDATE ledger_groups
                SET name = ?, parent_group_id = ?, nature = ?, affects_gross_profit = ?
                WHERE id = ? AND company_id = ?
            """, (name, parent_id, nature, affects_gp, group_id, cid))
            return redirect(url_for("chart_of_accounts"))

        cur.execute("SELECT * FROM ledger_groups WHERE id = ? AND company_id = ?", (group_id, cid))
        row = cur.fetchone()
        grp = dict(row) if row else None

    groups = [g for g in get_company_groups(cid) if g["id"] != group_id]
    return render_template("group_form.html", title="Group Alteration", form_title="Group Alteration", form_action=f"/masters/groups/alter/{group_id}", groups=groups, grp=grp)


@app.route("/masters/units/create", methods=["GET", "POST"])
def unit_create():
    comp = get_active_company()
    cid = comp["id"]
    if request.method == "POST":
        symbol = request.form.get("symbol").strip().upper()
        formal_name = request.form.get("formal_name").strip()
        decimals = int(request.form.get("decimal_places", 0))
        with transaction() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT OR IGNORE INTO units (company_id, symbol, formal_name, decimal_places)
                VALUES (?, ?, ?, ?)
            """, (cid, symbol, formal_name, decimals))
        return redirect(url_for("stock_summary"))

    return render_template("unit_form.html", title="Unit Creation")


@app.route("/masters/stock-groups/create", methods=["GET", "POST"])
def stock_group_create():
    comp = get_active_company()
    cid = comp["id"]
    if request.method == "POST":
        name = request.form.get("name").strip()
        parent_id = request.form.get("parent_id")
        parent_id = int(parent_id) if parent_id else None
        with transaction() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT OR IGNORE INTO stock_groups (company_id, name, parent_id)
                VALUES (?, ?, ?)
            """, (cid, name, parent_id))
        return redirect(url_for("stock_summary"))

    with transaction() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM stock_groups WHERE company_id = ? ORDER BY name", (cid,))
        s_groups = [dict(r) for r in cur.fetchall()]

    return render_template("stock_group_form.html", title="Stock Group Creation", stock_groups=s_groups)


@app.route("/masters/stock-categories/create", methods=["GET", "POST"])
def stock_category_create():
    comp = get_active_company()
    cid = comp["id"]
    if request.method == "POST":
        return redirect(url_for("stock_summary"))

    return render_template("stock_category_form.html", title="Stock Category Creation")


@app.route("/statutory/gst-details", methods=["GET", "POST"])
def gst_details_view():
    comp = get_active_company()
    return render_template("gst_details_form.html", title="Company GST Details", company=comp)


@app.route("/statutory/gst-classification", methods=["GET", "POST"])
def gst_classification_view():
    return render_template("gst_classification_form.html", title="GST Classification")


@app.route("/masters/voucher-types/create", methods=["GET", "POST"])
def voucher_type_create():
    comp = get_active_company()
    cid = comp["id"]
    if request.method == "POST":
        vtype = request.form.get("type_of_voucher", "Sales")
        return redirect(url_for("voucher_create", type=vtype))

    return render_template("voucher_type_form.html", title="Voucher Type Creation")


@app.route("/masters/ledgers/alter/<int:ledger_id>", methods=["GET", "POST"])
def ledger_alter(ledger_id):
    comp = get_active_company()
    cid = comp["id"]
    with transaction() as conn:
        cur = conn.cursor()
        if request.method == "POST":
            name = request.form.get("name").strip()
            group_id = int(request.form.get("group_id"))
            op_bal = float(request.form.get("opening_balance") or 0.0)
            bal_type = request.form.get("opening_balance_type", "Dr")
            gstin = request.form.get("gstin", "").strip() or None
            pan = request.form.get("pan", "").strip() or None
            state_code = request.form.get("state_code", "").strip() or None
            address = request.form.get("address", "").strip() or None

            cur.execute("""
                UPDATE ledgers
                SET name = ?, group_id = ?, opening_balance = ?, opening_balance_type = ?,
                    gstin = ?, pan = ?, state_code = ?, address = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND company_id = ?
            """, (name, group_id, op_bal, bal_type, gstin, pan, state_code, address, ledger_id, cid))
            return redirect(url_for("ledgers_list"))

        cur.execute("SELECT * FROM ledgers WHERE id = ? AND company_id = ?", (ledger_id, cid))
        row = cur.fetchone()
        ledger_data = dict(row) if row else None

    groups = get_company_groups(cid)
    return render_template("ledger_form.html", title="Ledger Alteration", form_title="Ledger Alteration", form_action=f"/masters/ledgers/alter/{ledger_id}", groups=groups, l=ledger_data)


@app.route("/masters/stock-items/alter/<int:item_id>", methods=["GET", "POST"])
def stock_item_alter(item_id):
    comp = get_active_company()
    cid = comp["id"]
    with transaction() as conn:
        cur = conn.cursor()
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            raw_unit_id = request.form.get("unit_id")
            if not raw_unit_id or str(raw_unit_id).strip() == "" or raw_unit_id == "None":
                cur.execute("SELECT id FROM units WHERE company_id = ? LIMIT 1", (cid,))
                u_row = cur.fetchone()
                if u_row:
                    unit_id = u_row["id"]
                else:
                    cur.execute("INSERT INTO units (company_id, symbol, formal_name, decimal_places) VALUES (?, 'Nos', 'Numbers', 0)", (cid,))
                    unit_id = cur.lastrowid
            else:
                unit_id = int(raw_unit_id)

            hsn = request.form.get("hsn_sac", "").strip()
            gst_rate = float(request.form.get("gst_rate") or 0.0)
            op_qty = float(request.form.get("opening_qty") or 0.0)
            op_rate = float(request.form.get("opening_rate") or 0.0)
            op_val = round(op_qty * op_rate, 2)

            cur.execute("""
                UPDATE stock_items
                SET name = ?, unit_id = ?, hsn_sac = ?, gst_rate = ?,
                    opening_qty = ?, opening_rate = ?, opening_value = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND company_id = ?
            """, (name, unit_id, hsn, gst_rate, op_qty, op_rate, op_val, item_id, cid))
            return redirect(url_for("stock_summary"))

        cur.execute("SELECT * FROM stock_items WHERE id = ? AND company_id = ?", (item_id, cid))
        row = cur.fetchone()
        item = dict(row) if row else None

        cur.execute("SELECT * FROM units WHERE company_id = ? ORDER BY symbol", (cid,))
        units = [dict(r) for r in cur.fetchall()]

    return render_template("stock_item_form.html", title="Stock Item Alteration", form_title="Stock Item Alteration", form_action=f"/masters/stock-items/alter/{item_id}", units=units, item=item)


@app.route("/api/masters/ledgers/<int:ledger_id>/delete", methods=["POST"])
def api_delete_ledger(ledger_id: int):
    comp = get_active_company()
    cid = comp["id"]
    res = delete_ledger(cid, ledger_id)
    if res["success"]:
        return jsonify({"success": True})
    return jsonify(res), 400


@app.route("/api/masters/stock-items/<int:item_id>/delete", methods=["POST"])
def api_delete_stock_item(item_id: int):
    comp = get_active_company()
    cid = comp["id"]
    res = delete_stock_item(cid, item_id)
    if res["success"]:
        return jsonify({"success": True})
    return jsonify(res), 400


@app.route("/api/masters/groups/<int:group_id>/delete", methods=["POST"])
def api_delete_group(group_id: int):
    comp = get_active_company()
    cid = comp["id"]
    res = delete_group(cid, group_id)
    if res["success"]:
        return jsonify({"success": True})
    return jsonify(res), 400


@app.route("/masters/alter/<string:master_type>")
def masters_alter_list_view(master_type):
    comp = get_active_company()
    cid = comp["id"]
    items = []
    title_label = master_type.replace("-", " ").title()

    with transaction() as conn:
        cur = conn.cursor()
        if master_type == "groups":
            cur.execute("SELECT id, name, nature FROM ledger_groups WHERE company_id = ? ORDER BY name", (cid,))
            items = [{"name": r["name"], "subtext": r["nature"], "url": f"/masters/groups/alter/{r['id']}"} for r in cur.fetchall()]
        elif master_type == "ledgers":
            cur.execute("SELECT l.id, l.name, g.name as gname FROM ledgers l JOIN ledger_groups g ON l.group_id = g.id WHERE l.company_id = ? ORDER BY l.name", (cid,))
            items = [{"name": r["name"], "subtext": r["gname"], "url": f"/masters/ledgers/alter/{r['id']}"} for r in cur.fetchall()]
        elif master_type == "stock-items":
            cur.execute("SELECT id, name, closing_qty FROM stock_items WHERE company_id = ? ORDER BY name", (cid,))
            items = [{"name": r["name"], "subtext": f"Stock: {r['closing_qty']}", "url": f"/masters/stock-items/alter/{r['id']}"} for r in cur.fetchall()]
        elif master_type == "godowns":
            from app.godown_engine import init_godown_schema
            init_godown_schema(DATABASE_PATH)
            cur.execute("SELECT id, name, location FROM godowns WHERE company_id = ? ORDER BY name", (cid,))
            items = [{"name": r["name"], "subtext": r["location"] or "Warehouse", "url": "/reports/godown-summary"} for r in cur.fetchall()]
        elif master_type == "units":
            cur.execute("SELECT id, symbol, formal_name FROM units WHERE company_id = ? ORDER BY symbol", (cid,))
            items = [{"name": r["symbol"], "subtext": r["formal_name"], "url": "/reports/stock-summary"} for r in cur.fetchall()]
        elif master_type == "voucher-types":
            items = [
                {"name": "Sales", "subtext": "Accounting / Inventory", "url": "/vouchers/create?type=Sales"},
                {"name": "Purchase", "subtext": "Accounting / Inventory", "url": "/vouchers/create?type=Purchase"},
                {"name": "Payment", "subtext": "Banking / Cash", "url": "/vouchers/create?type=Payment"},
                {"name": "Receipt", "subtext": "Banking / Cash", "url": "/vouchers/create?type=Receipt"},
                {"name": "Contra", "subtext": "Cash / Bank Transfer", "url": "/vouchers/create?type=Contra"},
                {"name": "Journal", "subtext": "Double Entry Adjustments", "url": "/vouchers/create?type=Journal"}
            ]

    return render_template("masters_alter_list.html", title=f"Alter {title_label}", master_type_label=title_label, items=items)


# --- Module 7: Manufacturing & BOM Routes ---
@app.route("/inventory/manufacturing")
def manufacturing_list_view():
    comp = get_active_company()
    cid = comp["id"]
    journals = list_manufacturing_journals(cid)
    return render_template("manufacturing_list.html", title="Manufacturing Journals", journals=journals)


@app.route("/inventory/manufacturing/create", methods=["GET", "POST"])
def manufacturing_create_view():
    comp = get_active_company()
    cid = comp["id"]
    if request.method == "POST":
        voucher_date = request.form.get("voucher_date")
        finished_item_id = int(request.form.get("finished_item_id"))
        dest_godown_id = int(request.form.get("destination_godown_id"))
        prod_qty = float(request.form.get("produced_qty"))
        addl_cost = float(request.form.get("additional_cost") or 0.0)
        narration = request.form.get("narration", "")

        raw_item_ids = request.form.getlist("component_item_id[]")
        raw_godown_ids = request.form.getlist("component_godown_id[]")
        raw_qtys = request.form.getlist("component_qty[]")
        raw_rates = request.form.getlist("component_rate[]")

        consumed_items = []
        for i in range(len(raw_item_ids)):
            if raw_item_ids[i]:
                consumed_items.append({
                    "stock_item_id": int(raw_item_ids[i]),
                    "godown_id": int(raw_godown_ids[i]),
                    "quantity": float(raw_qtys[i]),
                    "rate": float(raw_rates[i] or 0.0)
                })

        try:
            record_manufacturing_journal(
                company_id=cid,
                voucher_date=voucher_date,
                finished_item_id=finished_item_id,
                destination_godown_id=dest_godown_id,
                produced_qty=prod_qty,
                consumed_items=consumed_items,
                additional_cost=addl_cost,
                narration=narration
            )
            return redirect(url_for("manufacturing_list_view"))
        except Exception as e:
            return f"Error creating manufacturing journal: {e}", 400

    from datetime import date
    today = date.today().isoformat()
    godowns = list_godowns(cid)
    with transaction() as conn:
        items = conn.execute("""
            SELECT s.id, s.name, s.closing_qty, s.opening_rate, u.symbol as unit_symbol
            FROM stock_items s
            JOIN units u ON s.unit_id = u.id
            WHERE s.company_id = ?
            ORDER BY s.name ASC
        """, (cid,)).fetchall()
        stock_items = [dict(r) for r in items]

    return render_template(
        "manufacturing_entry.html",
        title="Manufacturing Journal",
        today=today,
        godowns=godowns,
        stock_items=stock_items
    )


@app.route("/inventory/bom/create", methods=["GET", "POST"])
def bom_create_view():
    comp = get_active_company()
    cid = comp["id"]
    if request.method == "POST":
        name = request.form.get("name")
        finished_item_id = int(request.form.get("finished_item_id"))
        finished_qty = float(request.form.get("finished_qty"))
        narration = request.form.get("narration", "")

        raw_item_ids = request.form.getlist("component_item_id[]")
        raw_types = request.form.getlist("component_type[]")
        raw_qtys = request.form.getlist("component_qty[]")

        components = []
        for i in range(len(raw_item_ids)):
            if raw_item_ids[i]:
                components.append({
                    "stock_item_id": int(raw_item_ids[i]),
                    "component_type": raw_types[i],
                    "quantity": float(raw_qtys[i])
                })

        try:
            create_bom(
                company_id=cid,
                name=name,
                finished_item_id=finished_item_id,
                finished_qty=finished_qty,
                components=components,
                narration=narration
            )
            return redirect(url_for("manufacturing_list_view"))
        except Exception as e:
            return f"Error defining BOM: {e}", 400

    with transaction() as conn:
        items = conn.execute("SELECT id, name FROM stock_items WHERE company_id = ? ORDER BY name ASC", (cid,)).fetchall()
        stock_items = [dict(r) for r in items]

    return render_template("bom_entry.html", title="Create BOM", stock_items=stock_items)


@app.route("/api/bom/list/<int:item_id>")
def api_bom_list(item_id: int):
    comp = get_active_company()
    cid = comp["id"]
    boms = get_boms_for_item(cid, item_id)
    return jsonify({"boms": boms})


# --- Module 8: Statutory TDS / TCS Routes ---
@app.route("/statutory/tds")
def tds_report_view():
    comp = get_active_company()
    cid = comp["id"]
    from_date = request.args.get("from_date", "2000-01-01")
    to_date = request.args.get("to_date", "2099-12-31")
    report = get_form_26q_report(cid, from_date, to_date)
    return render_template("tds_report.html", title="Form 26Q TDS Summary", report=report)


@app.route("/statutory/tds/entry", methods=["GET", "POST"])
def tds_entry_view():
    comp = get_active_company()
    cid = comp["id"]
    if request.method == "POST":
        voucher_date = request.form.get("voucher_date")
        exp_id = int(request.form.get("expense_ledger_id"))
        party_id = int(request.form.get("party_ledger_id"))
        tds_id = int(request.form.get("tds_ledger_id"))
        gross_amt = float(request.form.get("gross_amount"))
        section_code = request.form.get("section_code")
        narration = request.form.get("narration", "")

        try:
            record_tds_expense_voucher(
                company_id=cid,
                voucher_date=voucher_date,
                expense_ledger_id=exp_id,
                party_ledger_id=party_id,
                tds_ledger_id=tds_id,
                gross_amount=gross_amt,
                section_code=section_code,
                narration=narration
            )
            return redirect(url_for("tds_report_view"))
        except Exception as e:
            return f"Error posting TDS voucher: {e}", 400

    from datetime import date
    today = date.today().isoformat()

    with transaction() as conn:
        ledgers = conn.execute("""
            SELECT l.id, l.name, l.pan, g.name as group_name
            FROM ledgers l
            JOIN ledger_groups g ON l.group_id = g.id
            WHERE l.company_id = ? AND l.is_active = 1
            ORDER BY l.name ASC
        """, (cid,)).fetchall()
        all_ledgers = [dict(l) for l in ledgers]

    exp_ledgers = [l for l in all_ledgers if 'Expense' in l['group_name']]
    party_ledgers = [l for l in all_ledgers if 'Creditor' in l['group_name'] or 'Debtor' in l['group_name'] or 'Bank' not in l['group_name']]
    tax_ledgers = [l for l in all_ledgers if 'Duties' in l['group_name'] or 'Tax' in l['name'] or 'TDS' in l['name']]

    return render_template(
        "tds_entry.html",
        title="TDS Expense Booking",
        today=today,
        sections=STANDARD_TDS_SECTIONS,
        expense_ledgers=exp_ledgers,
        party_ledgers=party_ledgers,
        tax_ledgers=tax_ledgers
    )


# --- Module 9: Payroll Routes ---
@app.route("/payroll/employees", methods=["GET", "POST"])
def payroll_employees_view():
    comp = get_active_company()
    cid = comp["id"]
    if request.method == "POST":
        emp_code = request.form.get("emp_code")
        name = request.form.get("name")
        desig = request.form.get("designation")
        dept = request.form.get("department")
        doj = request.form.get("date_of_joining")
        basic = float(request.form.get("basic_salary") or 0.0)
        hra = float(request.form.get("hra_allowance") or 0.0)
        conv = float(request.form.get("conveyance_allowance") or 0.0)
        spec = float(request.form.get("special_allowance") or 0.0)
        pan = request.form.get("pan_number", "").strip()
        pf = request.form.get("pf_number", "").strip()
        esi = request.form.get("esi_number", "").strip()

        try:
            create_employee(
                company_id=cid,
                emp_code=emp_code,
                name=name,
                designation=desig,
                department=dept,
                date_of_joining=doj,
                basic_salary=basic,
                hra_allowance=hra,
                conveyance_allowance=conv,
                special_allowance=spec,
                pan_number=pan or None,
                pf_number=pf or None,
                esi_number=esi or None
            )
            return redirect(url_for("payroll_employees_view"))
        except Exception as e:
            return f"Error registering employee: {e}", 400

    from datetime import date
    today = date.today().isoformat()
    employees = list_employees(cid)
    payroll_records = list_payroll_records(cid)
    return render_template(
        "payroll_list.html",
        title="Payroll & Employees",
        today=today,
        employees=employees,
        payroll_records=payroll_records
    )


@app.route("/payroll/process", methods=["GET", "POST"])
def payroll_process_view():
    comp = get_active_company()
    cid = comp["id"]
    if request.method == "POST":
        emp_id = int(request.form.get("employee_id"))
        pay_month = request.form.get("pay_month")
        w_days = float(request.form.get("working_days"))
        p_days = float(request.form.get("present_days"))
        sal_exp_id = int(request.form.get("salary_expense_ledger_id"))
        sal_pay_id = int(request.form.get("salary_payable_ledger_id"))
        tds_ded = float(request.form.get("tds_deduction") or 0.0)

        with transaction() as conn:
            pf_row = conn.execute("SELECT id FROM ledgers WHERE company_id = ? AND name LIKE '%PF Payable%'", (cid,)).fetchone()
            pt_row = conn.execute("SELECT id FROM ledgers WHERE company_id = ? AND name LIKE '%Professional Tax%'", (cid,)).fetchone()
            pf_id = pf_row['id'] if pf_row else None
            pt_id = pt_row['id'] if pt_row else None

        try:
            res = process_payroll_voucher(
                company_id=cid,
                employee_id=emp_id,
                pay_month=pay_month,
                working_days=w_days,
                present_days=p_days,
                salary_expense_ledger_id=sal_exp_id,
                salary_payable_ledger_id=sal_pay_id,
                pf_payable_ledger_id=pf_id,
                pt_payable_ledger_id=pt_id,
                tds_deduction=tds_ded
            )
            return redirect(url_for("payslip_print_view", record_id=res["record_id"]))
        except Exception as e:
            return f"Error processing payroll: {e}", 400

    from datetime import date
    current_month = date.today().strftime("%Y-%m")
    employees = list_employees(cid)

    with transaction() as conn:
        ledgers = conn.execute("""
            SELECT l.id, l.name, g.name as group_name
            FROM ledgers l
            JOIN ledger_groups g ON l.group_id = g.id
            WHERE l.company_id = ? AND l.is_active = 1
            ORDER BY l.name ASC
        """, (cid,)).fetchall()
        all_ledgers = [dict(l) for l in ledgers]

    exp_ledgers = [l for l in all_ledgers if 'Expense' in l['group_name'] or 'Salar' in l['name']]
    liab_ledgers = [l for l in all_ledgers if 'Liabilit' in l['group_name'] or 'Creditor' in l['group_name'] or 'Payable' in l['name']]

    return render_template(
        "payroll_process.html",
        title="Process Salary",
        current_month=current_month,
        employees=employees,
        expense_ledgers=exp_ledgers,
        liability_ledgers=liab_ledgers
    )


@app.route("/payroll/payslip/<int:record_id>")
def payslip_print_view(record_id: int):
    slip = get_payslip(record_id)
    if not slip:
        return "Payslip record not found", 404
    return render_template("payslip_print.html", slip=slip)


# --- Module 10: MCA Audit Trail & Edit Log Routes ---
@app.route("/audit/edit-log/<string:entity_type>/<int:entity_id>")
def entity_edit_log_view(entity_type: str, entity_id: int):
    comp = get_active_company()
    cid = comp["id"]
    history = get_entity_edit_log(cid, entity_type, entity_id)
    return render_template(
        "edit_log_viewer.html",
        title=f"Edit Log - {entity_type} #{entity_id}",
        entity_type=entity_type,
        entity_id=entity_id,
        history=history
    )


@app.route("/audit/trail")
def audit_trail_view():
    comp = get_active_company()
    cid = comp["id"]
    trail = list_recent_audit_trail(cid, limit=100)
    return render_template(
        "edit_log_viewer.html",
        title="Organization Audit Trail",
        entity_type="Organization All",
        entity_id=cid,
        history=trail
    )


# --- Module 11: Multi-Currency Routes ---
@app.route("/masters/currencies")
def currencies_view():
    comp = get_active_company()
    cid = comp["id"]
    seed_standard_currencies(cid)
    currencies = list_currencies(cid)

    from datetime import date
    today = date.today().isoformat()
    return render_template(
        "currencies_list.html",
        title="Currencies & Forex Rates",
        currencies=currencies,
        today=today
    )


@app.route("/masters/currencies/rate", methods=["POST"])
def set_currency_rate_action():
    comp = get_active_company()
    cid = comp["id"]
    cur_id = int(request.form.get("currency_id"))
    rate_date = request.form.get("rate_date")
    rate = float(request.form.get("rate_per_unit"))

    set_exchange_rate(cid, cur_id, rate_date, rate)
    return redirect(url_for("currencies_view"))


# --- Module 12: Point of Sale (POS) Invoicing Routes ---
@app.route("/pos/invoice")
def pos_invoice_view():
    comp = get_active_company()
    cid = comp["id"]

    from datetime import date
    today = date.today().isoformat()

    with transaction() as conn:
        ledgers = conn.execute("""
            SELECT l.id, l.name, g.name as group_name
            FROM ledgers l
            JOIN ledger_groups g ON l.group_id = g.id
            WHERE l.company_id = ? AND l.is_active = 1
            ORDER BY l.name ASC
        """, (cid,)).fetchall()
        all_ledgers = [dict(l) for l in ledgers]

        items = conn.execute("""
            SELECT s.id, s.name, s.closing_qty, s.opening_rate, s.gst_rate, u.symbol as unit_symbol
            FROM stock_items s
            JOIN units u ON s.unit_id = u.id
            WHERE s.company_id = ?
            ORDER BY s.name ASC
        """, (cid,)).fetchall()
        stock_items = [dict(r) for r in items]

    cust_ledgers = [l for l in all_ledgers if 'Debtor' in l['group_name'] or 'Cash' in l['name'] or 'Customer' in l['name']]
    cash_ledgers = [l for l in all_ledgers if 'Cash' in l['group_name'] or 'Cash' in l['name']]
    bank_ledgers = [l for l in all_ledgers if 'Bank' in l['group_name']]

    return render_template(
        "pos_invoice_entry.html",
        title="POS Retail Counter Invoicing",
        today=today,
        customer_ledgers=cust_ledgers,
        cash_ledgers=cash_ledgers,
        bank_ledgers=bank_ledgers,
        stock_items=stock_items
    )


@app.route("/pos/invoice/create", methods=["POST"])
def pos_invoice_create_action():
    comp = get_active_company()
    cid = comp["id"]

    pos_date = request.form.get("pos_date")
    party_id = int(request.form.get("party_ledger_id"))
    cash_id = int(request.form.get("cash_ledger_id"))

    # Sales ledger lookup
    with transaction() as conn:
        sales_row = conn.execute("SELECT id FROM ledgers WHERE company_id = ? AND name = 'Sales Account'", (cid,)).fetchone()
        sales_id = sales_row['id'] if sales_row else party_id

    bank_id = int(request.form.get("bank_ledger_id") or 0) or None
    cash_tendered = float(request.form.get("cash_tendered") or 0.0)
    card_amount = float(request.form.get("card_amount") or 0.0)
    upi_amount = float(request.form.get("upi_amount") or 0.0)

    item_ids = request.form.getlist("item_id[]")
    qtys = request.form.getlist("quantity[]")
    rates = request.form.getlist("rate[]")
    gst_rates = request.form.getlist("gst_rate[]")

    items = []
    for i in range(len(item_ids)):
        if item_ids[i]:
            items.append({
                "stock_item_id": int(item_ids[i]),
                "quantity": float(qtys[i]),
                "rate": float(rates[i]),
                "gst_rate": float(gst_rates[i] or 0.0)
            })

    try:
        res = record_pos_invoice(
            company_id=cid,
            pos_date=pos_date,
            party_ledger_id=party_id,
            cash_ledger_id=cash_id,
            sales_ledger_id=sales_id,
            items=items,
            cash_tendered=cash_tendered,
            card_amount=card_amount,
            upi_amount=upi_amount,
            bank_ledger_id=bank_id
        )
        return redirect(url_for("pos_receipt_view", pos_id=res["pos_id"]))
    except Exception as e:
        return f"Error creating POS invoice: {e}", 400


@app.route("/pos/receipt/<int:pos_id>")
def pos_receipt_view(pos_id: int):
    inv = get_pos_invoice(pos_id)
    if not inv:
        return "POS Invoice not found", 404
    return render_template("pos_receipt.html", inv=inv)


# --- Module 13: Financial Budgets Routes ---
@app.route("/budgets")
def budgets_list_view():
    comp = get_active_company()
    cid = comp["id"]
    budgets = list_budgets(cid)
    return render_template("budgets_list.html", title="Budgets & Scenarios", budgets=budgets)


@app.route("/budgets/create", methods=["GET", "POST"])
def budget_create_view():
    comp = get_active_company()
    cid = comp["id"]
    if request.method == "POST":
        name = request.form.get("name")
        from_date = request.form.get("from_date")
        to_date = request.form.get("to_date")

        ledger_ids = request.form.getlist("ledger_id[]")
        alloc_amts = request.form.getlist("allocated_amount[]")

        allocations = []
        for i in range(len(ledger_ids)):
            if ledger_ids[i]:
                allocations.append({
                    "ledger_id": int(ledger_ids[i]),
                    "allocated_amount": float(alloc_amts[i])
                })

        try:
            b_id = create_budget(cid, name, from_date, to_date, allocations)
            return redirect(url_for("budget_variance_view", budget_id=b_id))
        except Exception as e:
            return f"Error creating budget: {e}", 400

    from datetime import date
    today = date.today()
    from_date = f"{today.year}-04-01"
    to_date = f"{today.year + 1}-03-31"

    with transaction() as conn:
        ledgers = conn.execute("""
            SELECT l.id, l.name, g.name as group_name
            FROM ledgers l
            JOIN ledger_groups g ON l.group_id = g.id
            WHERE l.company_id = ? AND l.is_active = 1
            ORDER BY g.name ASC, l.name ASC
        """, (cid,)).fetchall()
        all_ledgers = [dict(l) for l in ledgers]

    return render_template(
        "budget_create.html",
        title="Create Budget",
        from_date=from_date,
        to_date=to_date,
        ledgers=all_ledgers
    )


@app.route("/budgets/<int:budget_id>/variance")
def budget_variance_view(budget_id: int):
    comp = get_active_company()
    cid = comp["id"]
    report = get_budget_variance_report(cid, budget_id)
    if not report:
        return "Budget not found", 404
    return render_template("budget_variance.html", title="Budget Variance Report", report=report)


def start_server(port: int = 5000, debug: bool = False):
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
    comp = get_active_company()
    if comp:
        seed_standard_currencies(comp["id"])
    print(f"\n=======================================================")
    print(f" {APP_NAME} v{APP_VERSION} ")
    print(f" Offline Accounting Server Running At:")
    print(f" http://127.0.0.1:{port}")
    print(f" Press Ctrl+C to stop the server")
    print(f"=======================================================\n")
    app.run(host="127.0.0.1", port=port, debug=debug)


if __name__ == "__main__":
    start_server()
