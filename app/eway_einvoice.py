"""
TallySoft e-Invoice & e-Way Bill JSON Generation Module
Produces NIC-compliant JSON payloads for Indian government portal bulk uploading.
"""

from typing import Dict, Any, List
from datetime import datetime


def generate_einvoice_json(company: Dict[str, Any], party: Dict[str, Any], voucher: Dict[str, Any], items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Builds standard e-Invoice Schema (INV-01) JSON payload.
    """
    doc_date = datetime.strptime(voucher["voucher_date"], "%Y-%m-%d").strftime("%d/%m/%Y")
    
    # Line items formatting
    item_list = []
    tot_val = 0.0
    tot_cgst = 0.0
    tot_sgst = 0.0
    tot_igst = 0.0

    for idx, it in enumerate(items, start=1):
        qty = float(it["quantity"])
        rate = float(it["rate"])
        taxable = float(it["taxable_amount"])
        gst_rate = float(it.get("gst_rate", 0.0))
        cgst = float(it.get("cgst_amount", 0.0))
        sgst = float(it.get("sgst_amount", 0.0))
        igst = float(it.get("igst_amount", 0.0))
        tot_item = float(it["total_amount"])

        tot_val += taxable
        tot_cgst += cgst
        tot_sgst += sgst
        tot_igst += igst

        item_list.append({
            "SlNo": str(idx),
            "PrdDesc": it.get("item_name") or "Goods",
            "IsServc": "N",
            "HsnCd": it.get("hsn_sac") or "8471",
            "Qty": qty,
            "Unit": it.get("unit_symbol") or "NOS",
            "UnitPrice": rate,
            "TotAmt": taxable,
            "Discount": float(it.get("discount_percent", 0.0)),
            "AssAmt": taxable,
            "GstRt": gst_rate,
            "IgstAmt": igst,
            "CgstAmt": cgst,
            "SgstAmt": sgst,
            "TotItemVal": tot_item
        })

    payload = {
        "Version": "1.1",
        "TranDtls": {
            "TaxSch": "GST",
            "SupTyp": "B2B",
            "RegRev": "N",
            "EcmGstin": None,
            "IgstOnIntra": "N"
        },
        "DocDtls": {
            "Typ": "INV",
            "No": voucher["voucher_number"],
            "Dt": doc_date
        },
        "SellerDtls": {
            "Gstin": company.get("gstin") or "27ABCDE1234F1Z5",
            "LglNm": company.get("legal_name") or company.get("name"),
            "TrdNm": company.get("name"),
            "Loc": company.get("state"),
            "Pin": 400001,
            "Stcd": company.get("state_code", "27")
        },
        "BuyerDtls": {
            "Gstin": party.get("gstin") or "27AABCA1234A1Z5",
            "LglNm": party.get("name"),
            "TrdNm": party.get("name"),
            "Pos": party.get("state_code") or company.get("state_code", "27"),
            "Loc": party.get("state") or company.get("state"),
            "Pin": 400001,
            "Stcd": party.get("state_code") or company.get("state_code", "27")
        },
        "ValDtls": {
            "AssVal": round(tot_val, 2),
            "CgstVal": round(tot_cgst, 2),
            "SgstVal": round(tot_sgst, 2),
            "IgstVal": round(tot_igst, 2),
            "CesVal": 0.0,
            "StCesVal": 0.0,
            "Discount": 0.0,
            "OthChrg": 0.0,
            "RndOffAmt": float(voucher.get("round_off", 0.0)),
            "TotInvVal": float(voucher.get("total_amount", 0.0))
        },
        "ItemList": item_list
    }
    return payload


def generate_ewaybill_json(company: Dict[str, Any], party: Dict[str, Any], voucher: Dict[str, Any], items: List[Dict[str, Any]], distance_km: int = 50) -> Dict[str, Any]:
    """
    Builds NIC-compliant e-Way Bill JSON payload.
    """
    doc_date = datetime.strptime(voucher["voucher_date"], "%Y-%m-%d").strftime("%d/%m/%Y")
    einvoice = generate_einvoice_json(company, party, voucher, items)
    val_dtls = einvoice["ValDtls"]

    return {
        "supplyType": "O",
        "subSupplyType": "1",
        "docType": "INV",
        "docNo": voucher["voucher_number"],
        "docDate": doc_date,
        "fromGstin": company.get("gstin") or "27ABCDE1234F1Z5",
        "fromTrdName": company.get("name"),
        "fromStateCode": int(company.get("state_code", "27")),
        "toGstin": party.get("gstin") or "27AABCA1234A1Z5",
        "toTrdName": party.get("name"),
        "toStateCode": int(party.get("state_code") or company.get("state_code", "27")),
        "totalValue": val_dtls["AssVal"],
        "cgstValue": val_dtls["CgstVal"],
        "sgstValue": val_dtls["SgstVal"],
        "igstValue": val_dtls["IgstVal"],
        "totInvValue": val_dtls["TotInvVal"],
        "transDistance": str(distance_km),
        "transporterName": "",
        "transporterId": "",
        "transDocNo": "",
        "transMode": "1",
        "itemList": [
            {
                "itemNo": int(it["SlNo"]),
                "productName": it["PrdDesc"],
                "hsnCode": int(it["HsnCd"]),
                "quantity": it["Qty"],
                "qtyUnit": it["Unit"],
                "taxableAmount": it["AssAmt"]
            }
            for it in einvoice["ItemList"]
        ]
    }

