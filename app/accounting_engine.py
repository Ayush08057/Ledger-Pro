"""
TallySoft Core Double-Entry Accounting & Inventory Engine
Enforces strict double-entry invariants, ledger balances, inventory movements,
and financial report generation.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from app.database import transaction, get_connection
from app.gst_engine import is_interstate_transaction, calculate_item_gst, extract_state_code_from_gstin


class DoubleEntryMismatchError(Exception):
    """Raised when total debits do not equal total credits."""
    pass


class InsufficientStockError(Exception):
    """Raised when trying to sell more stock than available (if strict stock is enabled)."""
    pass


def get_next_voucher_number(conn, company_id: int, voucher_type: str) -> str:
    """
    Generates the next sequential voucher number for the given voucher type.
    Format: VTYPE-0001
    """
    prefix_map = {
        "Sales": "SALES",
        "Purchase": "PUR",
        "Payment": "PMT",
        "Receipt": "RCPT",
        "Contra": "CNTR",
        "Journal": "JRNL",
        "Credit Note": "CRN",
        "Debit Note": "DBN"
    }
    prefix = prefix_map.get(voucher_type, voucher_type[:4].upper())
    cursor = conn.cursor()
    cursor.execute("""
        SELECT voucher_number FROM vouchers
        WHERE company_id = ? AND voucher_type = ?
        ORDER BY id DESC LIMIT 1
    """, (company_id, voucher_type))
    row = cursor.fetchone()
    if not row:
        return f"{prefix}-0001"
    
    last_num = row[0]
    try:
        seq = int(last_num.split("-")[-1]) + 1
        return f"{prefix}-{seq:04d}"
    except Exception:
        return f"{prefix}-{int(datetime.now().timestamp())}"


def update_ledger_balances(conn, company_id: int, ledger_ids: List[int]):
    """
    Recalculates and updates the current_balance and current_balance_type for specified ledgers.
    """
    cursor = conn.cursor()
    for lid in set(ledger_ids):
        # Fetch opening balance
        cursor.execute("SELECT opening_balance, opening_balance_type FROM ledgers WHERE id = ?", (lid,))
        row = cursor.fetchone()
        if not row:
            continue
        op_bal = float(row["opening_balance"])
        op_type = row["opening_balance_type"]

        # Sum Dr and Cr journal entries
        cursor.execute("""
            SELECT 
                COALESCE(SUM(CASE WHEN entry_type = 'Dr' THEN amount ELSE 0 END), 0.0) AS total_dr,
                COALESCE(SUM(CASE WHEN entry_type = 'Cr' THEN amount ELSE 0 END), 0.0) AS total_cr
            FROM journal_entries
            WHERE ledger_id = ?
        """, (lid,))
        postings = cursor.fetchone()
        tot_dr = float(postings["total_dr"])
        tot_cr = float(postings["total_cr"])

        # Net balance calculation
        net = (op_bal if op_type == "Dr" else -op_bal) + tot_dr - tot_cr
        cur_bal = abs(round(net, 2))
        cur_type = "Dr" if net >= 0 else "Cr"

        cursor.execute("""
            UPDATE ledgers 
            SET current_balance = ?, current_balance_type = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (cur_bal, cur_type, lid))


def post_voucher(
    company_id: int,
    voucher_type: str,
    voucher_date: str,
    party_ledger_id: Optional[int],
    journal_postings: List[Dict[str, Any]],
    narration: str = "",
    voucher_number: Optional[str] = None,
    inventory_items: Optional[List[Dict[str, Any]]] = None,
    reference_number: Optional[str] = None,
    reference_date: Optional[str] = None,
    subtotal: float = 0.0,
    tax_amount: float = 0.0,
    round_off: float = 0.0,
    total_amount: float = 0.0,
    db_path=None
) -> int:
    """
    Posts a voucher with strict double-entry verification.
    journal_postings format: [{"ledger_id": int, "entry_type": "Dr"|"Cr", "amount": float, "narration": str}]
    """
    # 1. Double-Entry Verification: Total Dr must equal Total Cr
    total_dr = round(sum(p["amount"] for p in journal_postings if p["entry_type"] == "Dr"), 2)
    total_cr = round(sum(p["amount"] for p in journal_postings if p["entry_type"] == "Cr"), 2)

    if abs(total_dr - total_cr) > 0.01:
        raise DoubleEntryMismatchError(
            f"Double entry mismatch! Total Debit (₹{total_dr}) does not equal Total Credit (₹{total_cr})."
        )

    final_total = total_dr if total_amount <= 0 else round(total_amount, 2)

    with transaction(db_path) as conn:
        cursor = conn.cursor()

        v_num = voucher_number or get_next_voucher_number(conn, company_id, voucher_type)

        # Insert Voucher Header
        cursor.execute("""
            INSERT INTO vouchers (
                company_id, voucher_number, voucher_type, voucher_date,
                party_ledger_id, reference_number, reference_date,
                subtotal, tax_amount, round_off, total_amount, narration
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            company_id, v_num, voucher_type, voucher_date,
            party_ledger_id, reference_number, reference_date,
            subtotal, tax_amount, round_off, final_total, narration
        ))
        voucher_id = cursor.lastrowid

        # Insert Journal Postings
        affected_ledgers = []
        for p in journal_postings:
            cursor.execute("""
                INSERT INTO journal_entries (
                    voucher_id, company_id, ledger_id, entry_type, amount, narration, entry_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                voucher_id, company_id, p["ledger_id"], p["entry_type"],
                round(float(p["amount"]), 2), p.get("narration", narration), voucher_date
            ))
            affected_ledgers.append(p["ledger_id"])

        # Insert Inventory Items and update stock balances
        if inventory_items:
            for item in inventory_items:
                cursor.execute("""
                    INSERT INTO voucher_inventory_items (
                        voucher_id, stock_item_id, description, hsn_sac,
                        quantity, unit_id, rate, discount_percent, taxable_amount,
                        gst_rate, cgst_rate, cgst_amount, sgst_rate, sgst_amount,
                        igst_rate, igst_amount, total_amount
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    voucher_id, item["stock_item_id"], item.get("description", ""), item.get("hsn_sac", ""),
                    item["quantity"], item["unit_id"], item["rate"], item.get("discount_percent", 0.0),
                    item["taxable_amount"], item.get("gst_rate", 0.0),
                    item.get("cgst_rate", 0.0), item.get("cgst_amount", 0.0),
                    item.get("sgst_rate", 0.0), item.get("sgst_amount", 0.0),
                    item.get("igst_rate", 0.0), item.get("igst_amount", 0.0),
                    item["total_amount"]
                ))

                # Update Stock Quantity
                qty = float(item["quantity"])
                if voucher_type in ("Sales", "Debit Note"):  # Outward stock movement
                    cursor.execute("""
                        UPDATE stock_items 
                        SET closing_qty = closing_qty - ?, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (qty, item["stock_item_id"]))
                elif voucher_type in ("Purchase", "Credit Note"):  # Inward stock movement
                    cursor.execute("""
                        UPDATE stock_items 
                        SET closing_qty = closing_qty + ?, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (qty, item["stock_item_id"]))

        # Update ledger running balances
        update_ledger_balances(conn, company_id, affected_ledgers)

        # Audit log entry
        cursor.execute("""
            INSERT INTO audit_logs (company_id, entity_type, entity_id, action, details)
            VALUES (?, 'Voucher', ?, 'CREATE', ?)
        """, (company_id, voucher_id, f"Voucher {v_num} ({voucher_type}) created for ₹{final_total}"))

        # Trigger non-blocking realtime sync to mobile view / Firebase
        try:
            from app.firebase_sync import async_firebase_sync
            async_firebase_sync(company_id)
        except Exception:
            pass

        return voucher_id


def delete_voucher(company_id: int, voucher_id: int, db_path=None) -> bool:
    """
    Deletes a voucher, reverses inventory stock adjustments, updates affected ledger balances,
    and logs an audit trail entry.
    """
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT voucher_number, voucher_type, total_amount FROM vouchers WHERE id = ? AND company_id = ?", (voucher_id, company_id))
        v_row = cursor.fetchone()
        if not v_row:
            return False
        v_num, v_type, total_amt = v_row["voucher_number"], v_row["voucher_type"], v_row["total_amount"]

        # 1. Fetch affected ledgers from journal entries
        cursor.execute("SELECT DISTINCT ledger_id FROM journal_entries WHERE voucher_id = ?", (voucher_id,))
        affected_ledgers = [r[0] for r in cursor.fetchall()]

        # 2. Revert inventory movements
        cursor.execute("SELECT stock_item_id, quantity FROM voucher_inventory_items WHERE voucher_id = ?", (voucher_id,))
        inv_items = cursor.fetchall()
        for it in inv_items:
            item_id, qty = it["stock_item_id"], float(it["quantity"])
            if v_type in ("Sales", "Debit Note"):
                cursor.execute("UPDATE stock_items SET closing_qty = closing_qty + ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (qty, item_id))
            elif v_type in ("Purchase", "Credit Note"):
                cursor.execute("UPDATE stock_items SET closing_qty = closing_qty - ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (qty, item_id))

        # 3. Delete voucher (cascades to journal_entries and voucher_inventory_items)
        cursor.execute("DELETE FROM vouchers WHERE id = ?", (voucher_id,))

        # 4. Update running balances of affected ledgers
        update_ledger_balances(conn, company_id, affected_ledgers)

        # 5. Record Audit Log
        cursor.execute("""
            INSERT INTO audit_logs (company_id, entity_type, entity_id, action, details)
            VALUES (?, 'Voucher', ?, 'DELETE', ?)
        """, (company_id, voucher_id, f"Voucher {v_num} ({v_type}) of amount ₹{total_amt} was deleted"))

        return True


def cancel_voucher(company_id: int, voucher_id: int, db_path=None) -> bool:
    """
    Cancels a voucher (preserving the voucher sequence number), zeros out journal entries
    and inventory quantities, recalculates balances, and records an audit log.
    """
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT voucher_number, voucher_type, total_amount FROM vouchers WHERE id = ? AND company_id = ?", (voucher_id, company_id))
        v_row = cursor.fetchone()
        if not v_row:
            return False
        v_num, v_type, total_amt = v_row["voucher_number"], v_row["voucher_type"], v_row["total_amount"]

        # 1. Fetch affected ledgers
        cursor.execute("SELECT DISTINCT ledger_id FROM journal_entries WHERE voucher_id = ?", (voucher_id,))
        affected_ledgers = [r[0] for r in cursor.fetchall()]

        # 2. Revert inventory movements
        cursor.execute("SELECT stock_item_id, quantity FROM voucher_inventory_items WHERE voucher_id = ?", (voucher_id,))
        inv_items = cursor.fetchall()
        for it in inv_items:
            item_id, qty = it["stock_item_id"], float(it["quantity"])
            if v_type in ("Sales", "Debit Note"):
                cursor.execute("UPDATE stock_items SET closing_qty = closing_qty + ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (qty, item_id))
            elif v_type in ("Purchase", "Credit Note"):
                cursor.execute("UPDATE stock_items SET closing_qty = closing_qty - ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (qty, item_id))

        # 3. Remove inventory lines and journal entries for this voucher
        cursor.execute("DELETE FROM voucher_inventory_items WHERE voucher_id = ?", (voucher_id,))
        cursor.execute("DELETE FROM journal_entries WHERE voucher_id = ?", (voucher_id,))

        # 4. Update voucher header to CANCELLED with 0 amounts
        cursor.execute("""
            UPDATE vouchers
            SET subtotal = 0.0, tax_amount = 0.0, round_off = 0.0, total_amount = 0.0,
                narration = '[CANCELLED] ' || COALESCE(narration, ''), updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (voucher_id,))

        # 5. Update running balances
        update_ledger_balances(conn, company_id, affected_ledgers)

        # 6. Record Audit Log
        cursor.execute("""
            INSERT INTO audit_logs (company_id, entity_type, entity_id, action, details)
            VALUES (?, 'Voucher', ?, 'UPDATE', ?)
        """, (company_id, voucher_id, f"Voucher {v_num} ({v_type}) was marked CANCELLED"))

        return True


def create_sales_invoice(
    company_id: int,
    party_ledger_id: int,
    voucher_date: str,
    items: List[Dict[str, Any]],
    narration: str = "",
    reference_number: Optional[str] = None,
    db_path=None
) -> int:
    """
    High-level helper for creating a complete GST Sales Invoice with inventory & automated Dr/Cr postings.
    """
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        # Fetch company state code
        cursor.execute("SELECT state_code FROM companies WHERE id = ?", (company_id,))
        comp = cursor.fetchone()
        comp_state = comp["state_code"] if comp else "27"

        # Fetch party state code & ledgers
        cursor.execute("SELECT state_code, name FROM ledgers WHERE id = ?", (party_ledger_id,))
        party = cursor.fetchone()
        party_state = party["state_code"] if party and party["state_code"] else comp_state
        is_interstate = is_interstate_transaction(comp_state, party_state)

        # Fetch standard tax and sales ledgers
        def get_ledger(name):
            cursor.execute("SELECT id FROM ledgers WHERE company_id = ? AND name = ?", (company_id, name))
            r = cursor.fetchone()
            return r[0] if r else None

        sales_ledger_id = get_ledger("Sales Account")
        cgst_ledger_id = get_ledger("Output CGST")
        sgst_ledger_id = get_ledger("Output SGST")
        igst_ledger_id = get_ledger("Output IGST")
        roundoff_ledger_id = get_ledger("Round Off")

    # Compute items and taxes
    processed_items = []
    tot_taxable = 0.0
    tot_cgst = 0.0
    tot_sgst = 0.0
    tot_igst = 0.0

    for it in items:
        taxable = round(float(it["quantity"]) * float(it["rate"]), 2)
        disc = float(it.get("discount_percent", 0.0))
        if disc > 0:
            taxable = round(taxable * (1.0 - (disc / 100.0)), 2)

        gst_info = calculate_item_gst(taxable, it.get("gst_rate", 0.0), is_interstate)
        tot_taxable += taxable
        tot_cgst += gst_info["cgst_amount"]
        tot_sgst += gst_info["sgst_amount"]
        tot_igst += gst_info["igst_amount"]

        it_record = dict(it)
        it_record.update(gst_info)
        if "unit_id" not in it_record or not it_record["unit_id"]:
            with transaction(db_path) as c:
                cur2 = c.cursor()
                cur2.execute("SELECT unit_id FROM stock_items WHERE id = ?", (it["stock_item_id"],))
                r = cur2.fetchone()
                it_record["unit_id"] = r[0] if r else 1
        processed_items.append(it_record)

    tot_tax = round(tot_cgst + tot_sgst + tot_igst, 2)
    raw_total = round(tot_taxable + tot_tax, 2)
    rounded_total = round(raw_total)
    round_off_amount = round(rounded_total - raw_total, 2)

    # Prepare double-entry postings:
    # Dr Party Ledger (Full Amount)
    # Cr Sales Account (Taxable Subtotal)
    # Cr Output CGST / SGST / IGST
    postings = [
        {"ledger_id": party_ledger_id, "entry_type": "Dr", "amount": rounded_total, "narration": narration},
        {"ledger_id": sales_ledger_id, "entry_type": "Cr", "amount": tot_taxable, "narration": "Sales Taxable Value"}
    ]

    if is_interstate and tot_igst > 0:
        postings.append({"ledger_id": igst_ledger_id, "entry_type": "Cr", "amount": tot_igst, "narration": "Output IGST"})
    else:
        if tot_cgst > 0:
            postings.append({"ledger_id": cgst_ledger_id, "entry_type": "Cr", "amount": tot_cgst, "narration": "Output CGST"})
        if tot_sgst > 0:
            postings.append({"ledger_id": sgst_ledger_id, "entry_type": "Cr", "amount": tot_sgst, "narration": "Output SGST"})

    if round_off_amount != 0.0:
        if round_off_amount > 0:
            postings.append({"ledger_id": roundoff_ledger_id, "entry_type": "Cr", "amount": abs(round_off_amount), "narration": "Round Off"})
        else:
            postings.append({"ledger_id": roundoff_ledger_id, "entry_type": "Dr", "amount": abs(round_off_amount), "narration": "Round Off"})

    vid = post_voucher(
        company_id=company_id,
        voucher_type="Sales",
        voucher_date=voucher_date,
        party_ledger_id=party_ledger_id,
        journal_postings=postings,
        narration=narration,
        inventory_items=processed_items,
        reference_number=reference_number,
        subtotal=tot_taxable,
        tax_amount=tot_tax,
        round_off=round_off_amount,
        total_amount=rounded_total,
        db_path=db_path
    )

    # Record Bill Reference (New Ref) for Bill-Wise Tracking & Ageing
    try:
        from app.bill_wise import record_bill_reference
        with transaction(db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT voucher_number FROM vouchers WHERE id = ?", (vid,))
            v_num = cur.fetchone()[0]
        record_bill_reference(
            company_id=company_id,
            party_ledger_id=party_ledger_id,
            bill_ref_type="New Ref",
            bill_number=v_num,
            bill_date=voucher_date,
            amount=rounded_total,
            voucher_id=vid,
            db_path=db_path
        )
    except Exception:
        pass

    return vid


def create_credit_note(
    company_id: int,
    party_ledger_id: int,
    voucher_date: str,
    items: List[Dict[str, Any]],
    narration: str = "",
    original_invoice_no: Optional[str] = None,
    original_invoice_date: Optional[str] = None,
    db_path=None
) -> int:
    """
    Creates a GST Credit Note (Sales Return) reversing output tax, crediting party,
    and receiving returned stock inward.
    """
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT state_code FROM companies WHERE id = ?", (company_id,))
        comp = cursor.fetchone()
        comp_state = comp["state_code"] if comp else "27"

        cursor.execute("SELECT state_code, name FROM ledgers WHERE id = ?", (party_ledger_id,))
        party = cursor.fetchone()
        party_state = party["state_code"] if party and party["state_code"] else comp_state
        is_interstate = is_interstate_transaction(comp_state, party_state)

        def get_ledger(name):
            cursor.execute("SELECT id FROM ledgers WHERE company_id = ? AND name = ?", (company_id, name))
            r = cursor.fetchone()
            return r[0] if r else None

        sales_ledger_id = get_ledger("Sales Account")
        cgst_ledger_id = get_ledger("Output CGST")
        sgst_ledger_id = get_ledger("Output SGST")
        igst_ledger_id = get_ledger("Output IGST")
        roundoff_ledger_id = get_ledger("Round Off")

    processed_items = []
    tot_taxable = 0.0
    tot_cgst = 0.0
    tot_sgst = 0.0
    tot_igst = 0.0

    for it in items:
        taxable = round(float(it["quantity"]) * float(it["rate"]), 2)
        disc = float(it.get("discount_percent", 0.0))
        if disc > 0:
            taxable = round(taxable * (1.0 - (disc / 100.0)), 2)

        gst_info = calculate_item_gst(taxable, it.get("gst_rate", 0.0), is_interstate)
        tot_taxable += taxable
        tot_cgst += gst_info["cgst_amount"]
        tot_sgst += gst_info["sgst_amount"]
        tot_igst += gst_info["igst_amount"]

        it_record = dict(it)
        it_record.update(gst_info)
        if "unit_id" not in it_record or not it_record["unit_id"]:
            with transaction(db_path) as c:
                cur2 = c.cursor()
                cur2.execute("SELECT unit_id FROM stock_items WHERE id = ?", (it["stock_item_id"],))
                r = cur2.fetchone()
                it_record["unit_id"] = r[0] if r else 1
        processed_items.append(it_record)

    tot_tax = round(tot_cgst + tot_sgst + tot_igst, 2)
    raw_total = round(tot_taxable + tot_tax, 2)
    rounded_total = round(raw_total)
    round_off_amount = round(rounded_total - raw_total, 2)

    # Double-entry postings for Sales Return (Credit Note):
    # Dr Sales Account (Taxable Subtotal reversed)
    # Dr Output CGST / SGST / IGST (Tax reversed)
    # Cr Party Ledger (Full Amount credited to Customer)
    postings = [
        {"ledger_id": sales_ledger_id, "entry_type": "Dr", "amount": tot_taxable, "narration": "Sales Return Reversal"},
        {"ledger_id": party_ledger_id, "entry_type": "Cr", "amount": rounded_total, "narration": narration or "Credit Note to Party"}
    ]

    if is_interstate and tot_igst > 0:
        postings.append({"ledger_id": igst_ledger_id, "entry_type": "Dr", "amount": tot_igst, "narration": "Reversal Output IGST"})
    else:
        if tot_cgst > 0:
            postings.append({"ledger_id": cgst_ledger_id, "entry_type": "Dr", "amount": tot_cgst, "narration": "Reversal Output CGST"})
        if tot_sgst > 0:
            postings.append({"ledger_id": sgst_ledger_id, "entry_type": "Dr", "amount": tot_sgst, "narration": "Reversal Output SGST"})

    if round_off_amount != 0.0:
        if round_off_amount > 0:
            postings.append({"ledger_id": roundoff_ledger_id, "entry_type": "Dr", "amount": abs(round_off_amount), "narration": "Round Off"})
        else:
            postings.append({"ledger_id": roundoff_ledger_id, "entry_type": "Cr", "amount": abs(round_off_amount), "narration": "Round Off"})

    vid = post_voucher(
        company_id=company_id,
        voucher_type="Credit Note",
        voucher_date=voucher_date,
        party_ledger_id=party_ledger_id,
        journal_postings=postings,
        narration=f"Orig Inv: {original_invoice_no or 'N/A'}. {narration}".strip(),
        inventory_items=processed_items,
        reference_number=original_invoice_no,
        reference_date=original_invoice_date,
        subtotal=tot_taxable,
        tax_amount=tot_tax,
        round_off=round_off_amount,
        total_amount=rounded_total,
        db_path=db_path
    )

    return vid


def create_debit_note(
    company_id: int,
    party_ledger_id: int,
    voucher_date: str,
    items: List[Dict[str, Any]],
    narration: str = "",
    original_invoice_no: Optional[str] = None,
    original_invoice_date: Optional[str] = None,
    db_path=None
) -> int:
    """
    Creates a GST Debit Note (Purchase Return) reversing input tax, debiting supplier,
    and returning stock outward.
    """
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT state_code FROM companies WHERE id = ?", (company_id,))
        comp = cursor.fetchone()
        comp_state = comp["state_code"] if comp else "27"

        cursor.execute("SELECT state_code, name FROM ledgers WHERE id = ?", (party_ledger_id,))
        party = cursor.fetchone()
        party_state = party["state_code"] if party and party["state_code"] else comp_state
        is_interstate = is_interstate_transaction(comp_state, party_state)

        def get_ledger(name):
            cursor.execute("SELECT id FROM ledgers WHERE company_id = ? AND name = ?", (company_id, name))
            r = cursor.fetchone()
            return r[0] if r else None

        purchase_ledger_id = get_ledger("Purchase Account")
        cgst_ledger_id = get_ledger("Input CGST")
        sgst_ledger_id = get_ledger("Input SGST")
        igst_ledger_id = get_ledger("Input IGST")
        roundoff_ledger_id = get_ledger("Round Off")

    processed_items = []
    tot_taxable = 0.0
    tot_cgst = 0.0
    tot_sgst = 0.0
    tot_igst = 0.0

    for it in items:
        taxable = round(float(it["quantity"]) * float(it["rate"]), 2)
        disc = float(it.get("discount_percent", 0.0))
        if disc > 0:
            taxable = round(taxable * (1.0 - (disc / 100.0)), 2)

        gst_info = calculate_item_gst(taxable, it.get("gst_rate", 0.0), is_interstate)
        tot_taxable += taxable
        tot_cgst += gst_info["cgst_amount"]
        tot_sgst += gst_info["sgst_amount"]
        tot_igst += gst_info["igst_amount"]

        it_record = dict(it)
        it_record.update(gst_info)
        if "unit_id" not in it_record or not it_record["unit_id"]:
            with transaction(db_path) as c:
                cur2 = c.cursor()
                cur2.execute("SELECT unit_id FROM stock_items WHERE id = ?", (it["stock_item_id"],))
                r = cur2.fetchone()
                it_record["unit_id"] = r[0] if r else 1
        processed_items.append(it_record)

    tot_tax = round(tot_cgst + tot_sgst + tot_igst, 2)
    raw_total = round(tot_taxable + tot_tax, 2)
    rounded_total = round(raw_total)
    round_off_amount = round(rounded_total - raw_total, 2)

    # Double-entry postings for Purchase Return (Debit Note):
    # Dr Party Ledger (Full Amount debited to Supplier)
    # Cr Purchase Account (Taxable Subtotal reversed)
    # Cr Input CGST / SGST / IGST (Input tax credit reversed)
    postings = [
        {"ledger_id": party_ledger_id, "entry_type": "Dr", "amount": rounded_total, "narration": narration or "Debit Note to Supplier"},
        {"ledger_id": purchase_ledger_id, "entry_type": "Cr", "amount": tot_taxable, "narration": "Purchase Return Reversal"}
    ]

    if is_interstate and tot_igst > 0:
        postings.append({"ledger_id": igst_ledger_id, "entry_type": "Cr", "amount": tot_igst, "narration": "Reversal Input IGST"})
    else:
        if tot_cgst > 0:
            postings.append({"ledger_id": cgst_ledger_id, "entry_type": "Cr", "amount": tot_cgst, "narration": "Reversal Input CGST"})
        if tot_sgst > 0:
            postings.append({"ledger_id": sgst_ledger_id, "entry_type": "Cr", "amount": tot_sgst, "narration": "Reversal Input SGST"})

    if round_off_amount != 0.0:
        if round_off_amount > 0:
            postings.append({"ledger_id": roundoff_ledger_id, "entry_type": "Cr", "amount": abs(round_off_amount), "narration": "Round Off"})
        else:
            postings.append({"ledger_id": roundoff_ledger_id, "entry_type": "Dr", "amount": abs(round_off_amount), "narration": "Round Off"})

    vid = post_voucher(
        company_id=company_id,
        voucher_type="Debit Note",
        voucher_date=voucher_date,
        party_ledger_id=party_ledger_id,
        journal_postings=postings,
        narration=f"Orig Inv: {original_invoice_no or 'N/A'}. {narration}".strip(),
        inventory_items=processed_items,
        reference_number=original_invoice_no,
        reference_date=original_invoice_date,
        subtotal=tot_taxable,
        tax_amount=tot_tax,
        round_off=round_off_amount,
        total_amount=rounded_total,
        db_path=db_path
    )

    return vid


def create_purchase_invoice(
    company_id: int,
    party_ledger_id: int,
    voucher_date: str,
    items: List[Dict[str, Any]],
    narration: str = "",
    reference_number: Optional[str] = None,
    db_path=None
) -> int:
    """
    High-level helper for creating a complete GST Purchase Invoice with inventory & automated Dr/Cr postings.
    """
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT state_code FROM companies WHERE id = ?", (company_id,))
        comp = cursor.fetchone()
        comp_state = comp["state_code"] if comp else "27"

        cursor.execute("SELECT state_code, name FROM ledgers WHERE id = ?", (party_ledger_id,))
        party = cursor.fetchone()
        party_state = party["state_code"] if party and party["state_code"] else comp_state
        is_interstate = is_interstate_transaction(comp_state, party_state)

        def get_ledger(name):
            cursor.execute("SELECT id FROM ledgers WHERE company_id = ? AND name = ?", (company_id, name))
            r = cursor.fetchone()
            return r[0] if r else None

        purchase_ledger_id = get_ledger("Purchase Account")
        cgst_ledger_id = get_ledger("Input CGST")
        sgst_ledger_id = get_ledger("Input SGST")
        igst_ledger_id = get_ledger("Input IGST")
        roundoff_ledger_id = get_ledger("Round Off")

    processed_items = []
    tot_taxable = 0.0
    tot_cgst = 0.0
    tot_sgst = 0.0
    tot_igst = 0.0

    for it in items:
        taxable = round(float(it["quantity"]) * float(it["rate"]), 2)
        disc = float(it.get("discount_percent", 0.0))
        if disc > 0:
            taxable = round(taxable * (1.0 - (disc / 100.0)), 2)

        gst_info = calculate_item_gst(taxable, it.get("gst_rate", 0.0), is_interstate)
        tot_taxable += taxable
        tot_cgst += gst_info["cgst_amount"]
        tot_sgst += gst_info["sgst_amount"]
        tot_igst += gst_info["igst_amount"]

        it_record = dict(it)
        it_record.update(gst_info)
        if "unit_id" not in it_record or not it_record["unit_id"]:
            with transaction(db_path) as c:
                cur2 = c.cursor()
                cur2.execute("SELECT unit_id FROM stock_items WHERE id = ?", (it["stock_item_id"],))
                r = cur2.fetchone()
                it_record["unit_id"] = r[0] if r else 1
        processed_items.append(it_record)

    tot_tax = round(tot_cgst + tot_sgst + tot_igst, 2)
    raw_total = round(tot_taxable + tot_tax, 2)
    rounded_total = round(raw_total)
    round_off_amount = round(rounded_total - raw_total, 2)

    # Double-entry postings:
    # Dr Purchase Account (Taxable Subtotal)
    # Dr Input CGST / SGST / IGST
    # Cr Party Ledger (Full Amount)
    postings = [
        {"ledger_id": purchase_ledger_id, "entry_type": "Dr", "amount": tot_taxable, "narration": "Purchase Value"},
        {"ledger_id": party_ledger_id, "entry_type": "Cr", "amount": rounded_total, "narration": narration}
    ]

    if is_interstate and tot_igst > 0:
        postings.append({"ledger_id": igst_ledger_id, "entry_type": "Dr", "amount": tot_igst, "narration": "Input IGST"})
    else:
        if tot_cgst > 0:
            postings.append({"ledger_id": cgst_ledger_id, "entry_type": "Dr", "amount": tot_cgst, "narration": "Input CGST"})
        if tot_sgst > 0:
            postings.append({"ledger_id": sgst_ledger_id, "entry_type": "Dr", "amount": tot_sgst, "narration": "Input SGST"})

    if round_off_amount != 0.0:
        if round_off_amount > 0:
            postings.append({"ledger_id": roundoff_ledger_id, "entry_type": "Dr", "amount": abs(round_off_amount), "narration": "Round Off"})
        else:
            postings.append({"ledger_id": roundoff_ledger_id, "entry_type": "Cr", "amount": abs(round_off_amount), "narration": "Round Off"})

    vid = post_voucher(
        company_id=company_id,
        voucher_type="Purchase",
        voucher_date=voucher_date,
        party_ledger_id=party_ledger_id,
        journal_postings=postings,
        narration=narration,
        inventory_items=processed_items,
        reference_number=reference_number,
        subtotal=tot_taxable,
        tax_amount=tot_tax,
        round_off=round_off_amount,
        total_amount=rounded_total,
        db_path=db_path
    )

    # Record Bill Reference (New Ref) for Purchase Bill-Wise Tracking & Ageing
    try:
        from app.bill_wise import record_bill_reference
        with transaction(db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT voucher_number FROM vouchers WHERE id = ?", (vid,))
            v_num = cur.fetchone()[0]
        record_bill_reference(
            company_id=company_id,
            party_ledger_id=party_ledger_id,
            bill_ref_type="New Ref",
            bill_number=v_num,
            bill_date=voucher_date,
            amount=rounded_total,
            voucher_id=vid,
            db_path=db_path
        )
    except Exception:
        pass

    return vid


def get_trial_balance(company_id: int, db_path=None) -> Dict[str, Any]:
    """
    Computes real-time Trial Balance with Total Debit and Total Credit equality check.
    """
    with transaction(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT l.id, l.name, g.name AS group_name, g.nature,
                   l.current_balance, l.current_balance_type
            FROM ledgers l
            JOIN ledger_groups g ON l.group_id = g.id
            WHERE l.company_id = ? AND l.current_balance > 0
            ORDER BY g.nature, g.name, l.name
        """, (company_id,))
        rows = cursor.fetchall()

        total_dr = 0.0
        total_cr = 0.0
        lines = []
        for r in rows:
            amt = float(r["current_balance"])
            dr_amt = amt if r["current_balance_type"] == "Dr" else 0.0
            cr_amt = amt if r["current_balance_type"] == "Cr" else 0.0
            total_dr += dr_amt
            total_cr += cr_amt
            lines.append({
                "ledger_id": r["id"],
                "ledger_name": r["name"],
                "group_name": r["group_name"],
                "nature": r["nature"],
                "debit": round(dr_amt, 2),
                "credit": round(cr_amt, 2)
            })

        return {
            "lines": lines,
            "total_debit": round(total_dr, 2),
            "total_credit": round(total_cr, 2),
            "is_balanced": abs(round(total_dr - total_cr, 2)) < 0.01
        }

