"""
TallySoft GST Calculation Engine
Handles GSTIN validation, State Code detection, Interstate vs Intrastate tax distribution,
and HSN/SAC tax breakdown.
"""

from typing import Dict, Any, Tuple
from app.config import GST_STATE_CODES


def extract_state_code_from_gstin(gstin: str) -> str:
    """
    Extracts the 2-digit state code from a 15-character GSTIN.
    """
    if gstin and len(gstin.strip()) >= 2:
        code = gstin.strip()[:2]
        if code.isdigit():
            return code
    return ""


def is_interstate_transaction(company_state_code: str, party_state_code: str) -> bool:
    """
    Determines if transaction is Interstate (IGST) or Intrastate (CGST + SGST).
    """
    if not company_state_code or not party_state_code:
        return False
    return company_state_code.strip() != party_state_code.strip()


def calculate_item_gst(
    taxable_amount: float,
    gst_rate: float,
    is_interstate: bool
) -> Dict[str, float]:
    """
    Computes CGST, SGST, IGST, and total tax based on tax rate and supply state.
    For Intrastate: CGST = Rate/2, SGST = Rate/2
    For Interstate: IGST = Rate
    """
    taxable = round(float(taxable_amount), 2)
    rate = round(float(gst_rate), 2)

    if rate <= 0 or taxable <= 0:
        return {
            "taxable_amount": taxable,
            "gst_rate": 0.0,
            "cgst_rate": 0.0,
            "cgst_amount": 0.0,
            "sgst_rate": 0.0,
            "sgst_amount": 0.0,
            "igst_rate": 0.0,
            "igst_amount": 0.0,
            "total_tax": 0.0,
            "total_amount": taxable
        }

    if is_interstate:
        igst_amount = round(taxable * (rate / 100.0), 2)
        total_tax = igst_amount
        return {
            "taxable_amount": taxable,
            "gst_rate": rate,
            "cgst_rate": 0.0,
            "cgst_amount": 0.0,
            "sgst_rate": 0.0,
            "sgst_amount": 0.0,
            "igst_rate": rate,
            "igst_amount": igst_amount,
            "total_tax": total_tax,
            "total_amount": round(taxable + total_tax, 2)
        }
    else:
        half_rate = round(rate / 2.0, 2)
        cgst_amount = round(taxable * (half_rate / 100.0), 2)
        sgst_amount = round(taxable * (half_rate / 100.0), 2)
        total_tax = round(cgst_amount + sgst_amount, 2)
        return {
            "taxable_amount": taxable,
            "gst_rate": rate,
            "cgst_rate": half_rate,
            "cgst_amount": cgst_amount,
            "sgst_rate": half_rate,
            "sgst_amount": sgst_amount,
            "igst_rate": 0.0,
            "igst_amount": 0.0,
            "total_tax": total_tax,
            "total_amount": round(taxable + total_tax, 2)
        }

