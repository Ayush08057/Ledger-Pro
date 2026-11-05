-- ====================================================================
-- TallySoft Offline Accounting System
-- SQLite Schema Definition with Full Foreign Keys and Constraints
-- ====================================================================

PRAGMA foreign_keys = ON;

-- 1. Companies Master
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    legal_name TEXT,
    gstin TEXT CHECK(length(gstin) = 15 OR gstin IS NULL OR gstin = ''),
    pan TEXT,
    state TEXT NOT NULL DEFAULT 'Maharashtra',
    state_code TEXT NOT NULL DEFAULT '27',
    address TEXT,
    phone TEXT,
    email TEXT,
    currency_symbol TEXT NOT NULL DEFAULT '₹',
    fy_start_date TEXT NOT NULL DEFAULT '2026-04-01',
    fy_end_date TEXT NOT NULL DEFAULT '2027-03-31',
    books_from_date TEXT NOT NULL DEFAULT '2026-04-01',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Chart of Accounts: Ledger Groups (28 Standard Indian/Tally Groups)
CREATE TABLE IF NOT EXISTS ledger_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER,
    name TEXT NOT NULL,
    parent_group_id INTEGER,
    nature TEXT NOT NULL CHECK(nature IN ('Asset', 'Liability', 'Income', 'Expense')),
    affects_gross_profit INTEGER NOT NULL DEFAULT 0 CHECK(affects_gross_profit IN (0, 1)),
    is_builtin INTEGER NOT NULL DEFAULT 1 CHECK(is_builtin IN (0, 1)),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_group_id) REFERENCES ledger_groups(id) ON DELETE RESTRICT,
    UNIQUE(company_id, name)
);

-- 3. Ledgers (Accounts)
CREATE TABLE IF NOT EXISTS ledgers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    group_id INTEGER NOT NULL,
    opening_balance REAL NOT NULL DEFAULT 0.0 CHECK(opening_balance >= 0),
    opening_balance_type TEXT NOT NULL DEFAULT 'Dr' CHECK(opening_balance_type IN ('Dr', 'Cr')),
    current_balance REAL NOT NULL DEFAULT 0.0,
    current_balance_type TEXT NOT NULL DEFAULT 'Dr' CHECK(current_balance_type IN ('Dr', 'Cr')),
    gstin TEXT,
    pan TEXT,
    state_code TEXT,
    address TEXT,
    phone TEXT,
    email TEXT,
    bank_account_number TEXT,
    bank_ifsc TEXT,
    is_builtin INTEGER NOT NULL DEFAULT 0 CHECK(is_builtin IN (0, 1)),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
    FOREIGN KEY (group_id) REFERENCES ledger_groups(id) ON DELETE RESTRICT,
    UNIQUE(company_id, name)
);

-- 4. Units of Measurement (UOM)
CREATE TABLE IF NOT EXISTS units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    formal_name TEXT NOT NULL,
    decimal_places INTEGER NOT NULL DEFAULT 0 CHECK(decimal_places BETWEEN 0 AND 4),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
    UNIQUE(company_id, symbol)
);

-- 5. Stock Groups
CREATE TABLE IF NOT EXISTS stock_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    parent_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_id) REFERENCES stock_groups(id) ON DELETE RESTRICT,
    UNIQUE(company_id, name)
);

-- 6. Stock Items
CREATE TABLE IF NOT EXISTS stock_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    group_id INTEGER,
    unit_id INTEGER NOT NULL,
    hsn_sac TEXT,
    gst_rate REAL NOT NULL DEFAULT 0.0 CHECK(gst_rate >= 0),
    opening_qty REAL NOT NULL DEFAULT 0.0,
    opening_rate REAL NOT NULL DEFAULT 0.0,
    opening_value REAL NOT NULL DEFAULT 0.0,
    closing_qty REAL NOT NULL DEFAULT 0.0,
    closing_value REAL NOT NULL DEFAULT 0.0,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
    FOREIGN KEY (group_id) REFERENCES stock_groups(id) ON DELETE SET NULL,
    FOREIGN KEY (unit_id) REFERENCES units(id) ON DELETE RESTRICT,
    UNIQUE(company_id, name)
);

-- 7. Vouchers Header
CREATE TABLE IF NOT EXISTS vouchers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    voucher_number TEXT NOT NULL,
    voucher_type TEXT NOT NULL CHECK(voucher_type IN (
        'Sales', 'Purchase', 'Payment', 'Receipt', 'Contra', 'Journal', 'Credit Note', 'Debit Note'
    )),
    voucher_date TEXT NOT NULL,
    party_ledger_id INTEGER,
    reference_number TEXT,
    reference_date TEXT,
    place_of_supply TEXT,
    is_interstate INTEGER NOT NULL DEFAULT 0 CHECK(is_interstate IN (0, 1)),
    subtotal REAL NOT NULL DEFAULT 0.0,
    tax_amount REAL NOT NULL DEFAULT 0.0,
    round_off REAL NOT NULL DEFAULT 0.0,
    total_amount REAL NOT NULL DEFAULT 0.0,
    narration TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
    FOREIGN KEY (party_ledger_id) REFERENCES ledgers(id) ON DELETE RESTRICT,
    UNIQUE(company_id, voucher_type, voucher_number)
);

-- 8. Voucher Inventory Line Items (for Sales, Purchase, Invoicing)
CREATE TABLE IF NOT EXISTS voucher_inventory_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    voucher_id INTEGER NOT NULL,
    stock_item_id INTEGER NOT NULL,
    description TEXT,
    hsn_sac TEXT,
    quantity REAL NOT NULL CHECK(quantity > 0),
    unit_id INTEGER NOT NULL,
    rate REAL NOT NULL CHECK(rate >= 0),
    discount_percent REAL NOT NULL DEFAULT 0.0 CHECK(discount_percent >= 0 AND discount_percent <= 100),
    taxable_amount REAL NOT NULL CHECK(taxable_amount >= 0),
    gst_rate REAL NOT NULL DEFAULT 0.0 CHECK(gst_rate >= 0),
    cgst_rate REAL NOT NULL DEFAULT 0.0,
    cgst_amount REAL NOT NULL DEFAULT 0.0,
    sgst_rate REAL NOT NULL DEFAULT 0.0,
    sgst_amount REAL NOT NULL DEFAULT 0.0,
    igst_rate REAL NOT NULL DEFAULT 0.0,
    igst_amount REAL NOT NULL DEFAULT 0.0,
    total_amount REAL NOT NULL CHECK(total_amount >= 0),
    FOREIGN KEY (voucher_id) REFERENCES vouchers(id) ON DELETE CASCADE,
    FOREIGN KEY (stock_item_id) REFERENCES stock_items(id) ON DELETE RESTRICT,
    FOREIGN KEY (unit_id) REFERENCES units(id) ON DELETE RESTRICT
);

-- 9. Double-Entry Journal Postings (Strict Dr / Cr Ledger Postings)
CREATE TABLE IF NOT EXISTS journal_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    voucher_id INTEGER NOT NULL,
    company_id INTEGER NOT NULL,
    ledger_id INTEGER NOT NULL,
    entry_type TEXT NOT NULL CHECK(entry_type IN ('Dr', 'Cr')),
    amount REAL NOT NULL CHECK(amount > 0),
    narration TEXT,
    entry_date TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (voucher_id) REFERENCES vouchers(id) ON DELETE CASCADE,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
    FOREIGN KEY (ledger_id) REFERENCES ledgers(id) ON DELETE RESTRICT
);

-- 10. Edit Log & Audit Trail (TallyPrime Edit Log compliance)
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    entity_type TEXT NOT NULL CHECK(entity_type IN ('Voucher', 'Ledger', 'StockItem', 'Company')),
    entity_id INTEGER NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('CREATE', 'UPDATE', 'DELETE')),
    details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

-- 11. Company Features & Voucher Configs
CREATE TABLE IF NOT EXISTS company_features (
    company_id INTEGER PRIMARY KEY,
    features_json TEXT NOT NULL DEFAULT '{}',
    voucher_config_json TEXT NOT NULL DEFAULT '{}',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

-- Performance Indexes
CREATE INDEX IF NOT EXISTS idx_ledgers_group ON ledgers(group_id);
CREATE INDEX IF NOT EXISTS idx_ledgers_company ON ledgers(company_id);
CREATE INDEX IF NOT EXISTS idx_stock_items_group ON stock_items(group_id);
CREATE INDEX IF NOT EXISTS idx_vouchers_date ON vouchers(voucher_date);
CREATE INDEX IF NOT EXISTS idx_vouchers_type ON vouchers(voucher_type);
CREATE INDEX IF NOT EXISTS idx_journal_ledger_date ON journal_entries(ledger_id, entry_date);
CREATE INDEX IF NOT EXISTS idx_journal_voucher ON journal_entries(voucher_id);

