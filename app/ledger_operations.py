"""
TallySoft Ledger Operations: Batch Replace, Reclassify Department & Merge
Allows users to multi-select ledgers and transfer them to a new department/group
or merge transactions into a target ledger (Ctrl+Y operation).
"""

from typing import List, Dict, Any
from app.database import transaction
from app.accounting_engine import update_ledger_balances


def batch_replace_ledger_department(
    company_id: int,
    ledger_ids: List[int],
    target_group_id: int,
    db_path=None
) -> Dict[str, Any]:
    """
    Reclassifies multiple selected ledgers into a new department (ledger group).
    """
    if not ledger_ids:
        return {"success": False, "error": "No ledgers selected for replacement."}

    with transaction(db_path) as conn:
        cursor = conn.cursor()

        # Verify target group exists and belongs to company (or is builtin)
        cursor.execute("SELECT id, name, nature FROM ledger_groups WHERE id = ?", (target_group_id,))
        group_row = cursor.fetchone()
        if not group_row:
            return {"success": False, "error": "Target department/group does not exist."}
        
        target_group_name = group_row["name"]

        # Update all selected ledgers
        placeholders = ",".join("?" for _ in ledger_ids)
        params = [target_group_id] + list(ledger_ids) + [company_id]
        cursor.execute(f"""
            UPDATE ledgers 
            SET group_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id IN ({placeholders}) AND company_id = ?
        """, params)
        updated_count = cursor.rowcount

        # Log in audit trail
        for lid in ledger_ids:
            cursor.execute("""
                INSERT INTO audit_logs (company_id, entity_type, entity_id, action, details)
                VALUES (?, 'Ledger', ?, 'UPDATE', ?)
            """, (company_id, lid, f"Ledger department/group replaced to '{target_group_name}' via Ctrl+Y"))

        return {
            "success": True,
            "message": f"Successfully replaced department for {updated_count} ledger(s) to '{target_group_name}'.",
            "updated_count": updated_count,
            "target_group_name": target_group_name
        }


def batch_merge_ledgers(
    company_id: int,
    source_ledger_ids: List[int],
    target_ledger_id: int,
    db_path=None
) -> Dict[str, Any]:
    """
    Transfers all journal entries, vouchers, and opening balances from source ledgers
    into a target ledger, preserving complete double-entry integrity.
    """
    if not source_ledger_ids:
        return {"success": False, "error": "No source ledgers selected."}

    if target_ledger_id in source_ledger_ids:
        source_ledger_ids = [lid for lid in source_ledger_ids if lid != target_ledger_id]
        if not source_ledger_ids:
            return {"success": False, "error": "Cannot merge a ledger into itself."}

    with transaction(db_path) as conn:
        cursor = conn.cursor()

        # Verify target ledger
        cursor.execute("SELECT id, name FROM ledgers WHERE id = ? AND company_id = ?", (target_ledger_id, company_id))
        target_row = cursor.fetchone()
        if not target_row:
            return {"success": False, "error": "Target ledger not found."}
        target_name = target_row["name"]

        placeholders = ",".join("?" for _ in source_ledger_ids)

        # 1. Update journal entries
        cursor.execute(f"""
            UPDATE journal_entries
            SET ledger_id = ?
            WHERE ledger_id IN ({placeholders}) AND company_id = ?
        """, [target_ledger_id] + list(source_ledger_ids) + [company_id])
        moved_postings = cursor.rowcount

        # 2. Update vouchers party_ledger_id
        cursor.execute(f"""
            UPDATE vouchers
            SET party_ledger_id = ?
            WHERE party_ledger_id IN ({placeholders}) AND company_id = ?
        """, [target_ledger_id] + list(source_ledger_ids) + [company_id])
        moved_vouchers = cursor.rowcount

        # 3. Transfer opening balances (accumulate to target ledger)
        cursor.execute(f"""
            SELECT id, name, opening_balance, opening_balance_type 
            FROM ledgers WHERE id IN ({placeholders}) AND company_id = ?
        """, list(source_ledger_ids) + [company_id])
        source_ledgers = cursor.fetchall()

        cursor.execute("SELECT opening_balance, opening_balance_type FROM ledgers WHERE id = ?", (target_ledger_id,))
        tgt_op = cursor.fetchone()
        tgt_net = (tgt_op["opening_balance"] if tgt_op["opening_balance_type"] == "Dr" else -tgt_op["opening_balance"])

        for s in source_ledgers:
            s_bal = float(s["opening_balance"])
            if s_bal > 0:
                tgt_net += (s_bal if s["opening_balance_type"] == "Dr" else -s_bal)
            # Reset source opening balance
            cursor.execute("UPDATE ledgers SET opening_balance = 0.0, current_balance = 0.0, is_active = 0 WHERE id = ?", (s["id"],))

        new_op_bal = abs(round(tgt_net, 2))
        new_op_type = "Dr" if tgt_net >= 0 else "Cr"
        cursor.execute("""
            UPDATE ledgers 
            SET opening_balance = ?, opening_balance_type = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (new_op_bal, new_op_type, target_ledger_id))

        # 4. Recalculate balances
        affected = list(source_ledger_ids) + [target_ledger_id]
        update_ledger_balances(conn, company_id, affected)

        # 5. Audit Log
        cursor.execute("""
            INSERT INTO audit_logs (company_id, entity_type, entity_id, action, details)
            VALUES (?, 'Ledger', ?, 'UPDATE', ?)
        """, (company_id, target_ledger_id, f"Merged {len(source_ledger_ids)} ledgers into '{target_name}' (moved {moved_postings} postings)"))

        return {
            "success": True,
            "message": f"Successfully merged {len(source_ledger_ids)} ledger(s) into '{target_name}' ({moved_postings} entries transferred).",
            "target_ledger_name": target_name,
            "moved_postings": moved_postings
        }

