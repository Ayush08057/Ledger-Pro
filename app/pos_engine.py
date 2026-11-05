"""
TallySoft Point of Sale (POS) Invoicing Engine
Provides fast retail counter billing, multi-mode split tender (Cash, Card, UPI, Credit),
cash tender/change return calculation, inventory decrement, and 80mm thermal receipt formatting.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from app.database import transaction
from app.accounting_engine import post_voucher
from app.gst_engine import is_interstate_transaction, calculate_item_gst


def init_pos_schema(db_path=None):
    """
    Initializes pos_invoices and pos_invoice_items tables safely.
    """
    with transaction(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pos_invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                voucher_id INTEGER,
                pos_number TEXT NOT NULL,
                pos_date TEXT NOT NULL,
                party_ledger_id INTEGER NOT NULL,
                subtotal REAL NOT NULL DEFAULT 0.0,
                tax_amount REAL NOT NULL DEFAULT 0.0,
                discount_amount REAL NOT NULL DEFAULT 0.0,
                total_amount REAL NOT NULL DEFAULT 0.0,
                cash_tendered REAL NOT NULL DEFAULT 0.0,
                change_returned REAL NOT NULL DEFAULT 0.0,
                cash_amount REAL NOT NULL DEFAULT 0.0,
                card_amount REAL NOT NULL DEFAULT 0.0,
                upi_amount REAL NOT NULL DEFAULT 0.0,
                credit_amount REAL NOT NULL DEFAULT 0.0,
                narration TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
                FOREIGN KEY (voucher_id) REFERENCES vouchers(id) ON DELETE SET NULL,
                FOREIGN KEY (party_ledger_id) REFERENCES ledgers(id) ON DELETE RESTRICT,
                UNIQUE(company_id, pos_number)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS pos_invoice_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pos_id INTEGER NOT NULL,
                stock_item_id INTEGER NOT NULL,
                quantity REAL NOT NULL CHECK(quantity > 0),
                rate REAL NOT NULL CHECK(rate >= 0),
                taxable_amount REAL NOT NULL,
                gst_rate REAL NOT NULL DEFAULT 0.0,
                gst_amount REAL NOT NULL DEFAULT 0.0,
                total_amount REAL NOT NULL,
                FOREIGN KEY (pos_id) REFERENCES pos_invoices(id) ON DELETE CASCADE,
                FOREIGN KEY (stock_item_id) REFERENCES stock_items(id) ON DELETE RESTRICT
            )
        """)


def record_pos_invoice(
    company_id: int,
    pos_date: str,
    party_ledger_id: int,
    cash_ledger_id: int,
    sales_ledger_id: int,
    items: List[Dict[str, Any]],
    cash_tendered: float = 0.0,
    card_amount: float = 0.0,
    upi_amount: float = 0.0,
    credit_amount: float = 0.0,
    discount_amount: float = 0.0,
    bank_ledger_id: Optional[int] = None,
    narration: Optional[str] = None,
    db_path=None
) -> Dict[str, Any]:
    """
    Creates a complete POS retail sale:
    - Calculates item taxes and subtotals.
    - Calculates change returned if cash tendered exceeds cash due.
    - Posts balanced double-entry accounting voucher:
        Dr Cash/Bank/Card/UPI/Customer, Cr Sales, Cr Output GST.
    - Deducts inventory balances.
    """
    init_pos_schema(db_path)
    with transaction(db_path) as conn:
        # Determine sequence number
        cnt_row = conn.execute("SELECT COUNT(*) as cnt FROM pos_invoices WHERE company_id = ?", (company_id,)).fetchone()
        pos_number = f"POS-{(cnt_row['cnt'] + 1):05d}"

        # Get tax ledgers
        cgst_row = conn.execute("SELECT id FROM ledgers WHERE company_id = ? AND name = 'Output CGST'", (company_id,)).fetchone()
        sgst_row = conn.execute("SELECT id FROM ledgers WHERE company_id = ? AND name = 'Output SGST'", (company_id,)).fetchone()
        igst_row = conn.execute("SELECT id FROM ledgers WHERE company_id = ? AND name = 'Output IGST'", (company_id,)).fetchone()

        cgst_ledger_id = cgst_row['id'] if cgst_row else None
        sgst_ledger_id = sgst_row['id'] if sgst_row else None
        igst_ledger_id = igst_row['id'] if igst_row else None

        # Check interstate
        party = conn.execute("SELECT state_code FROM ledgers WHERE id = ?", (party_ledger_id,)).fetchone()
        company = conn.execute("SELECT state_code FROM companies WHERE id = ?", (company_id,)).fetchone()
        party_state = party['state_code'] if party and party['state_code'] else "27"
        comp_state = company['state_code'] if company and company['state_code'] else "27"
        is_interstate = (party_state != comp_state)

        subtotal = 0.0
        total_tax = 0.0
        item_rows = []

        for it in items:
            qty = float(it['quantity'])
            rate = float(it['rate'])
            taxable = round(qty * rate, 2)
            gst_rate = float(it.get('gst_rate', 0.0))
            tax_calc = calculate_item_gst(taxable, gst_rate, is_interstate)

            subtotal += taxable
            total_tax += tax_calc['total_tax']

            item_rows.append({
                "stock_item_id": it['stock_item_id'],
                "quantity": qty,
                "rate": rate,
                "taxable_amount": taxable,
                "gst_rate": gst_rate,
                "gst_amount": tax_calc['total_tax'],
                "total_amount": tax_calc['total_amount'],
                "cgst_amount": tax_calc['cgst_amount'],
                "sgst_amount": tax_calc['sgst_amount'],
                "igst_amount": tax_calc['igst_amount']
            })

        net_total = round(subtotal + total_tax - float(discount_amount), 2)

        # Payment allocations
        non_cash_paid = round(float(card_amount) + float(upi_amount) + float(credit_amount), 2)
        cash_due = max(0.0, round(net_total - non_cash_paid, 2))

        actual_cash = min(float(cash_tendered), cash_due) if cash_tendered > 0 else cash_due
        change_returned = max(0.0, round(float(cash_tendered) - cash_due, 2)) if cash_tendered > cash_due else 0.0

        # Construct double entry journal postings
        journal_postings = []

        # Debit payments
        if actual_cash > 0:
            journal_postings.append({"ledger_id": cash_ledger_id, "entry_type": "Dr", "amount": actual_cash})
        if card_amount > 0 and bank_ledger_id:
            journal_postings.append({"ledger_id": bank_ledger_id, "entry_type": "Dr", "amount": float(card_amount)})
        if upi_amount > 0 and bank_ledger_id:
            journal_postings.append({"ledger_id": bank_ledger_id, "entry_type": "Dr", "amount": float(upi_amount)})
        if credit_amount > 0:
            journal_postings.append({"ledger_id": party_ledger_id, "entry_type": "Dr", "amount": float(credit_amount)})

        # If no split payment specified, entire amount is cash
        if not journal_postings:
            journal_postings.append({"ledger_id": cash_ledger_id, "entry_type": "Dr", "amount": net_total})

        # Credit Sales (subtotal - discount)
        taxable_sales = round(subtotal - float(discount_amount), 2)
        journal_postings.append({"ledger_id": sales_ledger_id, "entry_type": "Cr", "amount": taxable_sales})

        # Credit Tax Ledgers
        tot_cgst = round(sum(i['cgst_amount'] for i in item_rows), 2)
        tot_sgst = round(sum(i['sgst_amount'] for i in item_rows), 2)
        tot_igst = round(sum(i['igst_amount'] for i in item_rows), 2)

        if tot_cgst > 0 and cgst_ledger_id:
            journal_postings.append({"ledger_id": cgst_ledger_id, "entry_type": "Cr", "amount": tot_cgst})
        if tot_sgst > 0 and sgst_ledger_id:
            journal_postings.append({"ledger_id": sgst_ledger_id, "entry_type": "Cr", "amount": tot_sgst})
        if tot_igst > 0 and igst_ledger_id:
            journal_postings.append({"ledger_id": igst_ledger_id, "entry_type": "Cr", "amount": tot_igst})

        # Safeguard balancing
        tot_dr = round(sum(p['amount'] for p in journal_postings if p['entry_type'] == 'Dr'), 2)
        tot_cr = round(sum(p['amount'] for p in journal_postings if p['entry_type'] == 'Cr'), 2)
        if tot_dr != tot_cr:
            diff = round(tot_dr - tot_cr, 2)
            # Adjust rounding difference against first Dr entry
            journal_postings[0]['amount'] = round(journal_postings[0]['amount'] - diff, 2)

        # Inventory deduction list for post_voucher
        inv_postings = []
        for i in item_rows:
            inv_postings.append({
                "stock_item_id": i['stock_item_id'],
                "quantity": i['quantity'],
                "rate": i['rate'],
                "taxable_amount": i['taxable_amount'],
                "total_amount": i['total_amount'],
                "gst_rate": i['gst_rate'],
                "cgst_rate": (i['gst_rate'] / 2.0) if not is_interstate else 0.0,
                "cgst_amount": i['cgst_amount'],
                "sgst_rate": (i['gst_rate'] / 2.0) if not is_interstate else 0.0,
                "sgst_amount": i['sgst_amount'],
                "igst_rate": i['gst_rate'] if is_interstate else 0.0,
                "igst_amount": i['igst_amount'],
                "unit_id": 1
            })

        # Post standard accounting voucher
        voucher_id = post_voucher(
            company_id=company_id,
            voucher_type="Sales",
            voucher_date=pos_date,
            party_ledger_id=party_ledger_id,
            journal_postings=journal_postings,
            inventory_items=inv_postings,
            narration=narration or f"POS Retail Sale {pos_number}",
            subtotal=subtotal,
            tax_amount=total_tax,
            total_amount=net_total,
            db_path=db_path
        )

        # Insert POS Invoice
        cursor = conn.execute("""
            INSERT INTO pos_invoices (
                company_id, voucher_id, pos_number, pos_date, party_ledger_id,
                subtotal, tax_amount, discount_amount, total_amount,
                cash_tendered, change_returned, cash_amount, card_amount,
                upi_amount, credit_amount, narration
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            company_id, voucher_id, pos_number, pos_date, party_ledger_id,
            subtotal, total_tax, float(discount_amount), net_total,
            float(cash_tendered), change_returned, actual_cash, float(card_amount),
            float(upi_amount), float(credit_amount), narration
        ))
        pos_id = cursor.lastrowid

        # Insert item lines
        for i in item_rows:
            conn.execute("""
                INSERT INTO pos_invoice_items (
                    pos_id, stock_item_id, quantity, rate, taxable_amount, gst_rate, gst_amount, total_amount
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pos_id, i['stock_item_id'], i['quantity'], i['rate'],
                i['taxable_amount'], i['gst_rate'], i['gst_amount'], i['total_amount']
            ))

        return {
            "pos_id": pos_id,
            "pos_number": pos_number,
            "voucher_id": voucher_id,
            "subtotal": subtotal,
            "tax_amount": total_tax,
            "total_amount": net_total,
            "cash_tendered": cash_tendered,
            "change_returned": change_returned,
            "items_count": len(item_rows)
        }


def get_pos_invoice(pos_id: int, db_path=None) -> Optional[Dict[str, Any]]:
    """
    Fetches full POS invoice details with items for 80mm thermal receipt rendering.
    """
    init_pos_schema(db_path)
    with transaction(db_path) as conn:
        inv = conn.execute("""
            SELECT p.*, l.name as party_name, c.name as company_name, c.gstin as company_gstin,
                   c.address as company_address, c.phone as company_phone
            FROM pos_invoices p
            JOIN ledgers l ON p.party_ledger_id = l.id
            JOIN companies c ON p.company_id = c.id
            WHERE p.id = ?
        """, (pos_id,)).fetchone()

        if not inv:
            return None

        data = dict(inv)
        items = conn.execute("""
            SELECT pi.*, s.name as item_name, u.symbol as unit_symbol
            FROM pos_invoice_items pi
            JOIN stock_items s ON pi.stock_item_id = s.id
            JOIN units u ON s.unit_id = u.id
            WHERE pi.pos_id = ?
        """, (pos_id,)).fetchall()
        data['items'] = [dict(i) for i in items]
        return data


def list_pos_invoices(company_id: int, db_path=None) -> List[Dict[str, Any]]:
    """
    Lists recent POS counter billing invoices.
    """
    init_pos_schema(db_path)
    with transaction(db_path) as conn:
        rows = conn.execute("""
            SELECT p.*, l.name as party_name
            FROM pos_invoices p
            JOIN ledgers l ON p.party_ledger_id = l.id
            WHERE p.company_id = ?
            ORDER BY p.id DESC
        """, (company_id,)).fetchall()
        return [dict(r) for r in rows]
