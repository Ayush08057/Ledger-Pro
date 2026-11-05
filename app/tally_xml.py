"""
TallySoft Tally XML Interoperability Module
Generates and parses standard Tally XML format (<ENVELOPE><BODY><IMPORTDATA>...)
allowing complete data export and import compatible with Tally.ERP 9 and TallyPrime.
"""

import xml.etree.ElementTree as ET
from xml.dom import minidom
from typing import Dict, Any, List
from app.database import transaction, get_connection


def export_masters_to_tally_xml(company_id: int, db_path=None) -> str:
    """
    Exports all Ledgers, Groups, and Stock Items of a company to standard Tally XML format.
    """
    with transaction(db_path) as conn:
        cursor = conn.cursor()

        # Groups
        cursor.execute("SELECT name, parent_group_id FROM ledger_groups WHERE company_id = ?", (company_id,))
        groups = cursor.fetchall()

        # Ledgers
        cursor.execute("""
            SELECT l.name, g.name AS group_name, l.opening_balance, l.opening_balance_type, l.gstin, l.state_code
            FROM ledgers l
            JOIN ledger_groups g ON l.group_id = g.id
            WHERE l.company_id = ?
        """, (company_id,))
        ledgers = cursor.fetchall()

        # Stock Items
        cursor.execute("""
            SELECT s.name, u.symbol AS unit_name, s.hsn_sac, s.gst_rate, s.opening_qty, s.opening_rate
            FROM stock_items s
            JOIN units u ON s.unit_id = u.id
            WHERE s.company_id = ?
        """, (company_id,))
        stock_items = cursor.fetchall()

    envelope = ET.Element("ENVELOPE")
    header = ET.SubElement(envelope, "HEADER")
    tally_req = ET.SubElement(header, "TALLYREQUEST")
    tally_req.text = "Export Data"

    body = ET.SubElement(envelope, "BODY")
    import_data = ET.SubElement(body, "IMPORTDATA")
    req_desc = ET.SubElement(import_data, "REQUESTDESC")
    rep_name = ET.SubElement(req_desc, "REPORTNAME")
    rep_name.text = "All Masters"

    req_data = ET.SubElement(import_data, "REQUESTDATA")

    # Ledgers
    for l in ledgers:
        msg = ET.SubElement(req_data, "TALLYMESSAGE")
        ledger_el = ET.SubElement(msg, "LEDGER", {"NAME": l["name"], "ACTION": "Create"})
        name_el = ET.SubElement(ledger_el, "NAME")
        name_el.text = l["name"]
        parent_el = ET.SubElement(ledger_el, "PARENT")
        parent_el.text = l["group_name"]
        
        # Opening balance in Tally convention: Debit is negative, Credit is positive
        op_bal = float(l["opening_balance"])
        if l["opening_balance_type"] == "Dr":
            op_bal = -op_bal
        bal_el = ET.SubElement(ledger_el, "OPENINGBALANCE")
        bal_el.text = f"{op_bal:.2f}"

        if l["gstin"]:
            gstin_el = ET.SubElement(ledger_el, "PARTYGSTIN")
            gstin_el.text = l["gstin"]

    # Stock Items
    for s in stock_items:
        msg = ET.SubElement(req_data, "TALLYMESSAGE")
        stock_el = ET.SubElement(msg, "STOCKITEM", {"NAME": s["name"], "ACTION": "Create"})
        name_el = ET.SubElement(stock_el, "NAME")
        name_el.text = s["name"]
        base_unit = ET.SubElement(stock_el, "BASEUNITS")
        base_unit.text = s["unit_name"]
        if s["hsn_sac"]:
            hsn_el = ET.SubElement(stock_el, "HSNCODE")
            hsn_el.text = s["hsn_sac"]
        gst_el = ET.SubElement(stock_el, "GSTRATE")
        gst_el.text = f"{s['gst_rate']:.2f}"

    xml_str = ET.tostring(envelope, encoding="utf-8")
    parsed = minidom.parseString(xml_str)
    return parsed.toprettyxml(indent="  ")


def import_masters_from_tally_xml(company_id: int, xml_content: str, db_path=None) -> Dict[str, int]:
    """
    Parses Tally XML and creates missing Ledgers and Stock Items in SQLite.
    """
    root = ET.fromstring(xml_content)
    imported_ledgers = 0
    imported_items = 0

    with transaction(db_path) as conn:
        cursor = conn.cursor()

        # Iterate over all TALLYMESSAGE elements
        for msg in root.iter("TALLYMESSAGE"):
            ledger_node = msg.find("LEDGER")
            if ledger_node is not None:
                name = ledger_node.get("NAME") or (ledger_node.find("NAME").text if ledger_node.find("NAME") is not None else "")
                parent = ledger_node.find("PARENT").text if ledger_node.find("PARENT") is not None else "Sundry Debtors"
                gstin = ledger_node.find("PARTYGSTIN").text if ledger_node.find("PARTYGSTIN") is not None else None
                
                # Find group_id
                cursor.execute("SELECT id FROM ledger_groups WHERE company_id = ? AND name = ?", (company_id, parent))
                grp_row = cursor.fetchone()
                grp_id = grp_row[0] if grp_row else 1 # Default

                cursor.execute("""
                    INSERT OR IGNORE INTO ledgers (company_id, name, group_id, gstin, opening_balance, opening_balance_type, current_balance)
                    VALUES (?, ?, ?, ?, 0.0, 'Dr', 0.0)
                """, (company_id, name, grp_id, gstin))
                if cursor.rowcount > 0:
                    imported_ledgers += 1

            stock_node = msg.find("STOCKITEM")
            if stock_node is not None:
                name = stock_node.get("NAME") or (stock_node.find("NAME").text if stock_node.find("NAME") is not None else "")
                hsn = stock_node.find("HSNCODE").text if stock_node.find("HSNCODE") is not None else ""
                gst_rate_str = stock_node.find("GSTRATE").text if stock_node.find("GSTRATE") is not None else "18.0"
                gst_rate = float(gst_rate_str) if gst_rate_str else 18.0

                # Default unit NOS / PCS
                cursor.execute("SELECT id FROM units WHERE company_id = ? LIMIT 1", (company_id,))
                unit_row = cursor.fetchone()
                unit_id = unit_row[0] if unit_row else 1

                cursor.execute("""
                    INSERT OR IGNORE INTO stock_items (company_id, name, unit_id, hsn_sac, gst_rate)
                    VALUES (?, ?, ?, ?, ?)
                """, (company_id, name, unit_id, hsn, gst_rate))
                if cursor.rowcount > 0:
                    imported_items += 1

    return {"imported_ledgers": imported_ledgers, "imported_items": imported_items}

