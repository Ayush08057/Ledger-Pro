"""
TallySoft GST Tax Invoice Generator
Formats invoices according to standard Indian GST Rule 46 and Tally invoice layouts.
Includes Indian currency number-to-words converter.
"""

from typing import Dict, Any, List


def number_to_words_inr(num: float) -> str:
    """
    Converts a numeric amount to Indian currency words format.
    Example: 141600.00 -> 'INR One Lakh Forty-One Thousand Six Hundred and Zero Paise Only'
    """
    units = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine"]
    teens = ["Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
             "Seventeen", "Eighteen", "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]

    def two_digits(n: int) -> str:
        if n == 0:
            return ""
        elif n < 10:
            return units[n]
        elif 10 <= n < 20:
            return teens[n - 10]
        else:
            t = tens[n // 10]
            u = units[n % 10]
            return f"{t} {u}".strip()

    def three_digits(n: int) -> str:
        h = n // 100
        rem = n % 100
        res = ""
        if h > 0:
            res += f"{units[h]} Hundred"
        if rem > 0:
            if res:
                res += " and "
            res += two_digits(rem)
        return res

    if num == 0:
        return "INR Zero Only"

    whole = int(round(num, 2))
    paise = int(round((round(num, 2) - whole) * 100))

    parts = []
    # Crores (>= 1,00,00,000)
    crores = whole // 10000000
    whole %= 10000000
    if crores > 0:
        parts.append(f"{two_digits(crores)} Crore")

    # Lakhs (>= 1,00,000)
    lakhs = whole // 100000
    whole %= 100000
    if lakhs > 0:
        parts.append(f"{two_digits(lakhs)} Lakh")

    # Thousands (>= 1,000)
    thousands = whole // 1000
    whole %= 1000
    if thousands > 0:
        parts.append(f"{two_digits(thousands)} Thousand")

    # Hundreds and below
    if whole > 0:
        parts.append(three_digits(whole))

    words_rupees = " ".join(parts).strip()
    words_paise = f" and {two_digits(paise)} Paise" if paise > 0 else ""

    return f"INR {words_rupees}{words_paise} Only"


def format_invoice_data(voucher: Dict[str, Any], company: Dict[str, Any], party: Dict[str, Any], items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Builds the complete structured payload required for the official Tally-format Tax Invoice.
    """
    # HSN/SAC summary aggregation
    hsn_summary = {}
    for item in items:
        hsn = item.get("hsn_sac") or "N/A"
        if hsn not in hsn_summary:
            hsn_summary[hsn] = {
                "hsn_sac": hsn,
                "taxable_amount": 0.0,
                "cgst_rate": item.get("cgst_rate", 0.0),
                "cgst_amount": 0.0,
                "sgst_rate": item.get("sgst_rate", 0.0),
                "sgst_amount": 0.0,
                "igst_rate": item.get("igst_rate", 0.0),
                "igst_amount": 0.0,
                "total_tax": 0.0
            }
        hsn_summary[hsn]["taxable_amount"] += float(item.get("taxable_amount", 0.0))
        hsn_summary[hsn]["cgst_amount"] += float(item.get("cgst_amount", 0.0))
        hsn_summary[hsn]["sgst_amount"] += float(item.get("sgst_amount", 0.0))
        hsn_summary[hsn]["igst_amount"] += float(item.get("igst_amount", 0.0))
        hsn_summary[hsn]["total_tax"] += float(item.get("cgst_amount", 0.0)) + float(item.get("sgst_amount", 0.0)) + float(item.get("igst_amount", 0.0))

    # Round totals
    for h in hsn_summary.values():
        h["taxable_amount"] = round(h["taxable_amount"], 2)
        h["cgst_amount"] = round(h["cgst_amount"], 2)
        h["sgst_amount"] = round(h["sgst_amount"], 2)
        h["igst_amount"] = round(h["igst_amount"], 2)
        h["total_tax"] = round(h["total_tax"], 2)

    total_amount = float(voucher.get("total_amount", 0.0))
    amount_in_words = number_to_words_inr(total_amount)

    return {
        "voucher": voucher,
        "company": company,
        "party": party,
        "items": items,
        "hsn_summary": list(hsn_summary.values()),
        "amount_in_words": amount_in_words
    }

