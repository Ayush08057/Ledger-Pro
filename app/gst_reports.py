"""
TallySoft Statutory GST Reports Module
Generates GSTR-1 (Outward Supplies) and GSTR-3B (Summary Return) summaries.
"""

from typing import Dict, Any, List
from app.database import transaction


def get_gstr1_report(company_id: int, start_date: str = "", end_date: str = "", db_path=None) -> Dict[str, Any]:
    """
    Computes GSTR-1 Return Data:
    - Table 4: B2B Invoices (Customers with GSTIN)
    - Table 7: B2C Invoices (Unregistered / Consumers)
    - Table 12: HSN Summary of Outward Supplies
    """
    with transaction(db_path) as conn:
        cursor = conn.cursor()

        # Query Sales Vouchers
        query = """
            SELECT v.id, v.voucher_number, v.voucher_date, v.place_of_supply, v.is_interstate,
                   v.subtotal, v.tax_amount, v.total_amount,
                   p.name AS party_name, p.gstin AS party_gstin, p.state_code AS party_state_code
            FROM vouchers v
            LEFT JOIN ledgers p ON v.party_ledger_id = p.id
            WHERE v.company_id = ? AND v.voucher_type = 'Sales'
        """
        params = [company_id]
        if start_date:
            query += " AND v.voucher_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND v.voucher_date <= ?"
            params.append(end_date)
        query += " ORDER BY v.voucher_date ASC, v.id ASC"

        cursor.execute(query, params)
        sales_vouchers = cursor.fetchall()

        b2b_invoices = []
        b2c_invoices = []
        tot_b2b_taxable = 0.0
        tot_b2b_tax = 0.0
        tot_b2c_taxable = 0.0
        tot_b2c_tax = 0.0

        voucher_ids = []
        for row in sales_vouchers:
            v_dict = dict(row)
            voucher_ids.append(v_dict["id"])
            gstin = (v_dict["party_gstin"] or "").strip()
            if gstin and len(gstin) == 15:
                b2b_invoices.append(v_dict)
                tot_b2b_taxable += float(v_dict["subtotal"])
                tot_b2b_tax += float(v_dict["tax_amount"])
            else:
                b2c_invoices.append(v_dict)
                tot_b2c_taxable += float(v_dict["subtotal"])
                tot_b2c_tax += float(v_dict["tax_amount"])

        # HSN Summary (Table 12)
        hsn_summary = []
        if voucher_ids:
            placeholders = ",".join("?" for _ in voucher_ids)
            cursor.execute(f"""
                SELECT vii.hsn_sac, s.name AS item_name, u.symbol AS uom,
                       SUM(vii.quantity) AS total_qty,
                       SUM(vii.taxable_amount) AS total_taxable,
                       SUM(vii.cgst_amount) AS total_cgst,
                       SUM(vii.sgst_amount) AS total_sgst,
                       SUM(vii.igst_amount) AS total_igst,
                       SUM(vii.total_amount) AS total_amount
                FROM voucher_inventory_items vii
                JOIN stock_items s ON vii.stock_item_id = s.id
                JOIN units u ON vii.unit_id = u.id
                WHERE vii.voucher_id IN ({placeholders})
                GROUP BY vii.hsn_sac, s.name, u.symbol
                ORDER BY vii.hsn_sac
            """, voucher_ids)
            hsn_summary = [dict(r) for r in cursor.fetchall()]

        return {
            "b2b_invoices": b2b_invoices,
            "total_b2b_taxable": round(tot_b2b_taxable, 2),
            "total_b2b_tax": round(tot_b2b_tax, 2),
            "b2c_invoices": b2c_invoices,
            "total_b2c_taxable": round(tot_b2c_taxable, 2),
            "total_b2c_tax": round(tot_b2c_tax, 2),
            "hsn_summary": hsn_summary,
            "grand_taxable": round(tot_b2b_taxable + tot_b2c_taxable, 2),
            "grand_tax": round(tot_b2b_tax + tot_b2c_tax, 2)
        }


def get_gstr3b_report(company_id: int, start_date: str = "", end_date: str = "", db_path=None) -> Dict[str, Any]:
    """
    Computes GSTR-3B Return Summary:
    - Table 3.1: Outward taxable supplies liability (from Sales)
    - Table 4: Eligible ITC (from Purchases)
    - Net Tax Payable (Outward Tax - ITC)
    """
    with transaction(db_path) as conn:
        cursor = conn.cursor()

        # Outward supplies (Sales)
        cursor.execute("""
            SELECT 
                COALESCE(SUM(vii.taxable_amount), 0.0) AS taxable_val,
                COALESCE(SUM(vii.igst_amount), 0.0) AS igst,
                COALESCE(SUM(vii.cgst_amount), 0.0) AS cgst,
                COALESCE(SUM(vii.sgst_amount), 0.0) AS sgst
            FROM voucher_inventory_items vii
            JOIN vouchers v ON vii.voucher_id = v.id
            WHERE v.company_id = ? AND v.voucher_type = 'Sales'
        """, (company_id,))
        outward = dict(cursor.fetchone())

        # Inward supplies / Eligible ITC (Purchases)
        cursor.execute("""
            SELECT 
                COALESCE(SUM(vii.taxable_amount), 0.0) AS taxable_val,
                COALESCE(SUM(vii.igst_amount), 0.0) AS igst,
                COALESCE(SUM(vii.cgst_amount), 0.0) AS cgst,
                COALESCE(SUM(vii.sgst_amount), 0.0) AS sgst
            FROM voucher_inventory_items vii
            JOIN vouchers v ON vii.voucher_id = v.id
            WHERE v.company_id = ? AND v.voucher_type = 'Purchase'
        """, (company_id,))
        inward_itc = dict(cursor.fetchone())

        # Net Tax Payable = Max(0, Outward - Inward)
        net_igst = round(outward["igst"] - inward_itc["igst"], 2)
        net_cgst = round(outward["cgst"] - inward_itc["cgst"], 2)
        net_sgst = round(outward["sgst"] - inward_itc["sgst"], 2)

        return {
            "outward": {
                "taxable_value": round(outward["taxable_val"], 2),
                "igst": round(outward["igst"], 2),
                "cgst": round(outward["cgst"], 2),
                "sgst": round(outward["sgst"], 2),
                "total_tax": round(outward["igst"] + outward["cgst"] + outward["sgst"], 2)
            },
            "itc": {
                "taxable_value": round(inward_itc["taxable_val"], 2),
                "igst": round(inward_itc["igst"], 2),
                "cgst": round(inward_itc["cgst"], 2),
                "sgst": round(inward_itc["sgst"], 2),
                "total_itc": round(inward_itc["igst"] + inward_itc["cgst"] + inward_itc["sgst"], 2)
            },
            "net_payable": {
                "igst": max(0.0, net_igst),
                "cgst": max(0.0, net_cgst),
                "sgst": max(0.0, net_sgst),
                "total": max(0.0, net_igst) + max(0.0, net_cgst) + max(0.0, net_sgst)
            }
        }

