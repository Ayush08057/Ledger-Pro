"""
TallySoft Standard Chart of Accounts and Initial Master Data Seeder
Contains the 28 standard Tally Groups, default statutory ledgers, and standard UOMs.
"""

# 15 Primary Groups: (Name, Nature, Affects_Gross_Profit)
PRIMARY_GROUPS = [
    ("Capital Account", "Liability", 0),
    ("Loans (Liability)", "Liability", 0),
    ("Current Liabilities", "Liability", 0),
    ("Fixed Assets", "Asset", 0),
    ("Investments", "Asset", 0),
    ("Current Assets", "Asset", 0),
    ("Branch / Divisions", "Liability", 0),
    ("Misc. Expenses (ASSET)", "Asset", 0),
    ("Suspense A/c", "Liability", 0),
    ("Sales Accounts", "Income", 1),
    ("Purchase Accounts", "Expense", 1),
    ("Direct Incomes", "Income", 1),
    ("Indirect Incomes", "Income", 0),
    ("Direct Expenses", "Expense", 1),
    ("Indirect Expenses", "Expense", 0),
]

# 13 Sub-Groups: (Name, Parent Group Name, Nature, Affects_Gross_Profit)
SUB_GROUPS = [
    # Under Capital Account
    ("Reserves & Surplus", "Capital Account", "Liability", 0),
    # Under Loans (Liability)
    ("Bank OD A/c", "Loans (Liability)", "Liability", 0),
    ("Secured Loans", "Loans (Liability)", "Liability", 0),
    ("Unsecured Loans", "Loans (Liability)", "Liability", 0),
    # Under Current Liabilities
    ("Duties & Taxes", "Current Liabilities", "Liability", 0),
    ("Provisions", "Current Liabilities", "Liability", 0),
    ("Sundry Creditors", "Current Liabilities", "Liability", 0),
    # Under Current Assets
    ("Stock-in-Hand", "Current Assets", "Asset", 0),
    ("Deposits (Asset)", "Current Assets", "Asset", 0),
    ("Loans & Advances (Asset)", "Current Assets", "Asset", 0),
    ("Sundry Debtors", "Current Assets", "Asset", 0),
    ("Cash-in-Hand", "Current Assets", "Asset", 0),
    ("Bank Accounts", "Current Assets", "Asset", 0),
]

# Default Ledgers created with each company: (Name, Group Name, Opening Balance Type, Is_Builtin)
DEFAULT_LEDGERS = [
    ("Cash", "Cash-in-Hand", "Dr", 1),
    ("Profit & Loss A/c", "Reserves & Surplus", "Cr", 1),
    ("Sales Account", "Sales Accounts", "Cr", 1),
    ("Purchase Account", "Purchase Accounts", "Dr", 1),
    # GST Duties & Taxes Ledgers
    ("Input CGST", "Duties & Taxes", "Dr", 1),
    ("Input SGST", "Duties & Taxes", "Dr", 1),
    ("Input IGST", "Duties & Taxes", "Dr", 1),
    ("Output CGST", "Duties & Taxes", "Cr", 1),
    ("Output SGST", "Duties & Taxes", "Cr", 1),
    ("Output IGST", "Duties & Taxes", "Cr", 1),
    # Round Off
    ("Round Off", "Indirect Expenses", "Dr", 1),
]

# Standard Units of Measurement
DEFAULT_UNITS = [
    ("PCS", "Pieces", 0),
    ("NOS", "Numbers", 0),
    ("KGS", "Kilograms", 2),
    ("BOX", "Boxes", 0),
    ("MTR", "Meters", 2),
    ("LTR", "Litres", 2),
]


def seed_company_defaults(conn, company_id: int):
    """
    Seeds the standard 28 Tally Groups, default ledgers, and standard units for a company.
    """
    cursor = conn.cursor()

    # 1. Seed Primary Groups
    group_id_map = {}
    for name, nature, affects_gp in PRIMARY_GROUPS:
        cursor.execute("""
            INSERT OR IGNORE INTO ledger_groups (company_id, name, parent_group_id, nature, affects_gross_profit, is_builtin)
            VALUES (?, ?, NULL, ?, ?, 1)
        """, (company_id, name, nature, affects_gp))
        cursor.execute("SELECT id FROM ledger_groups WHERE company_id = ? AND name = ?", (company_id, name))
        row = cursor.fetchone()
        if row:
            group_id_map[name] = row[0]

    # 2. Seed Sub-Groups
    for name, parent_name, nature, affects_gp in SUB_GROUPS:
        parent_id = group_id_map.get(parent_name)
        if not parent_id:
            cursor.execute("SELECT id FROM ledger_groups WHERE company_id = ? AND name = ?", (company_id, parent_name))
            p_row = cursor.fetchone()
            parent_id = p_row[0] if p_row else None
            if parent_id:
                group_id_map[parent_name] = parent_id

        cursor.execute("""
            INSERT OR IGNORE INTO ledger_groups (company_id, name, parent_group_id, nature, affects_gross_profit, is_builtin)
            VALUES (?, ?, ?, ?, ?, 1)
        """, (company_id, name, parent_id, nature, affects_gp))
        cursor.execute("SELECT id FROM ledger_groups WHERE company_id = ? AND name = ?", (company_id, name))
        row = cursor.fetchone()
        if row:
            group_id_map[name] = row[0]

    # 3. Seed Default Ledgers
    for name, group_name, bal_type, is_builtin in DEFAULT_LEDGERS:
        grp_id = group_id_map.get(group_name)
        if not grp_id:
            cursor.execute("SELECT id FROM ledger_groups WHERE company_id = ? AND name = ?", (company_id, group_name))
            row = cursor.fetchone()
            grp_id = row[0] if row else None

        if grp_id:
            cursor.execute("""
                INSERT OR IGNORE INTO ledgers (company_id, name, group_id, opening_balance, opening_balance_type,
                                              current_balance, current_balance_type, is_builtin, is_active)
                VALUES (?, ?, ?, 0.0, ?, 0.0, ?, ?, 1)
            """, (company_id, name, grp_id, bal_type, bal_type, is_builtin))

    # 4. Seed Standard Units of Measurement
    for symbol, formal_name, decimals in DEFAULT_UNITS:
        cursor.execute("""
            INSERT OR IGNORE INTO units (company_id, symbol, formal_name, decimal_places)
            VALUES (?, ?, ?, ?)
        """, (company_id, symbol, formal_name, decimals))

    conn.commit()

