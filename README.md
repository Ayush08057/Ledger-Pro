# TallySoft - Customized Offline Accounting System

An independent, local-first offline accounting application adhering to Tally accounting mechanics, full double-entry validation, and Indian statutory GST compliance.

---

## Technical Highlights

- **Workspace Path**: `E:\Tally Soft`
- **One-Click Windows Launcher**: Double-click `start_tally.bat` to launch the offline server and auto-open your browser.
- **Data Engine**: SQLite 3 with strict foreign key constraints (`PRAGMA foreign_keys = ON;`) and WAL mode for zero-latency local operations.
- **Data Protection & Backups**:
  - **Online Snapshot Backups (Alt+Y)**: Atomic SQLite snapshots generated without server downtime or lockups (`backups/`).
  - **1-Click Restore**: Point-in-time database restoration.
- **Chart of Accounts**: 28 Standard Tally Groups (15 Primary Groups + 13 Sub-groups) automatically seeded for every company.
- **Voucher Workflows**:
  - `F4: Contra` (Bank & Cash transfers)
  - `F5: Payment` (Disbursements)
  - `F6: Receipt` (Collections)
  - `F7: Journal` (Adjustments & Year-End closings)
  - `F8: Sales` (Item Invoicing with automatic CGST/SGST/IGST breakdown and stock deduction)
  - `F9: Purchase` (Vendor Invoicing with automatic ITC tax breakdown and stock addition)
  - `Alt+F7: Stock Journal` (Inter-Godown warehouse inventory transfers)
- **Bill-Wise Reference Accounting**:
  - `New Ref`: Auto-tagged on Sales and Purchase invoices
  - `Agst Ref`: Settle specific unpaid bills on Receipt and Payment vouchers
  - **Bill-by-Bill Ageing Analysis**: Overdue aging categorized into 0–30, 31–60, 61–90, and >90 days
- **Multi-Godown & Warehouse Management**:
  - Unlimited storage locations and warehouses
  - Real-time Godown-wise stock position and valuation
- **Universal Navigation ("Go To" - Alt+G)**:
  - Instant spotlight search jumping to any screen, report, master, or voucher from anywhere
- **Financial Reports & Analysis**:
  - **Day Book**: Chronological transaction audit trail with custom Date/Period filtering (**F2**)
  - **Trial Balance**: Real-time Debit & Credit equality validation
  - **Balance Sheet**: Schedule III / T-format Statement
  - **Profit & Loss A/c**: Trading & P&L with Gross & Net profit
  - **Stock Summary**: Real-time Inward, Outward & Closing Stock Valuation
  - **Godown Summary**: Location-wise inventory tracking (**W**)
  - **Bill-Wise Ageing**: Overdue aging categorized into 0–30, 31–60, 61–90, and >90 days (**A**)
  - **Ratio Analysis**: Current Ratio, Quick Ratio, GP% & NP% Margins (**R**)
  - **Outstandings**: Bills Receivable (Sundry Debtors) & Bills Payable (Sundry Creditors) (**O**)
  - **Cash/Bank Book**: Liquidity and bank account balances (**K**)
  - **Bank Reconciliation Statement (BRS)**: Live bank clearance tracking, uncleared cheques, and statement matching
  - **Cost Centre Break-Up Report**: Multi-dimensional project and department expense allocations
  - **Ledger Drilldown Statement**: Itemized account statement with running balance (**L**)
- **Statutory GST Returns & Tax Invoice**:
  - **Rule 46 Tax Invoice**: Print-ready GST Invoice with HSN breakdown and Indian words conversion
  - **Government JSON Exports**: Direct download of **e-Invoice (INV-01)** and **e-Way Bill** JSON payloads
  - **GSTR-1**: Table 4 (B2B), Table 7 (B2C), and Table 12 (HSN summary)
  - **GSTR-3B**: Table 3.1 (Outward Tax), Table 4 (Eligible ITC), and Net Tax Payable
- **Tally XML Interoperability**:
  - Standard Tally `<ENVELOPE><BODY><IMPORTDATA>...` XML Export & Import
- **Multi-Company Management**:
  - `F3`: Select, Create, Alter, and Switch Company on the fly

---

## Keyboard Shortcuts

| Shortcut | Screen / Action |
| :--- | :--- |
| **Esc** | Return to Gateway of Tally / Go Back |
| **Alt + G** | Universal "Go To" Search Modal (All Screens) |
| **F2** | Change Period / Active Date |
| **F3** | Select / Switch Company |
| **F4** | Contra Voucher (Cash/Bank) |
| **F5** | Payment Voucher |
| **F6** | Receipt Voucher |
| **F7** | Journal Voucher |
| **F8** | Sales Voucher (Invoice) |
| **F9** | Purchase Voucher |
| **Alt + F7** | Stock Journal (Inter-Godown Transfer) |
| **Ctrl + A** / **Enter** | Accept Dialog (`Yes` / `No`) |
| **D** | Day Book |
| **B** | Balance Sheet |
| **P** | Profit & Loss Account |
| **S** | Stock Summary |
| **W** | Godown / Warehouse Summary |
| **A** | Bill-Wise Ageing Analysis |
| **R** | Ratio Analysis |
| **T** | Trial Balance |
| **O** | Outstandings (Receivables/Payables) |
| **K** | Banking / Cash Book |
| **G** | Statutory GST Reports (GSTR-1 / 3B) |
| **Alt + Y** | Database Backup & Restore |
| **Ctrl + Y** | Replace / Transfer Selected Ledgers (Department / Merge) |
| **Alt + E** | Data Exchange (Tally XML) |
| **C** | Create Master / Ledger |
| **A** | Alter / Chart of Accounts |

---

## Directory Layout

```
E:\Tally Soft\
│
├── start_tally.bat           # 1-Click Windows batch launcher
├── run.py                    # Unified CLI & server launcher
├── README.md                 # Documentation
│
├── app\
│   ├── __init__.py           
│   ├── config.py             # Paths, GST state mappings & tax slabs
│   ├── schema.sql            # Normalized SQLite schema with foreign keys & check constraints
│   ├── seed_data.py          # 28 Standard Tally groups, tax ledgers & units
│   ├── database.py           # Connection handling, atomic transactions & migrations
│   ├── gst_engine.py         # Interstate vs Intrastate tax calculation & GSTIN parser
│   ├── gst_invoice.py        # Rule 46 GST Tax Invoice & Indian currency words
│   ├── gst_reports.py        # GSTR-1 & GSTR-3B statutory return summaries
│   ├── tally_xml.py          # Bidirectional Tally <ENVELOPE> XML Import/Export
│   ├── eway_einvoice.py      # Government NIC e-Way Bill & e-Invoice JSON generator
│   ├── backup.py             # Atomic SQLite snapshot backups & restoration
│   ├── accounting_engine.py  # Double-entry posting, voucher balancing & inventory valuation
│   ├── reports.py            # Balance Sheet, P&L, Trial Balance, Day Book, Stock Summary
│   ├── analysis.py           # Ledger statement, Outstandings, Cash/Bank & Ratio Analysis
│   └── server.py             # Local offline web application & JSON API
│
├── backups\                  # Point-in-time SQLite snapshot archives (.db)
├── data\
│   └── tally_offline.db      # Permanent SQLite database
│
├── templates\
│   ├── base.html             # Topbar, company period & right-side function key button bar
│   ├── gateway.html          # Gateway of Tally menu with hotkeys
│   ├── voucher_entry.html    # Interactive F4-F9 voucher entry screen & Accept dialog
│   ├── invoice_print.html    # Formal GST Tax Invoice format
│   ├── gst_reports.html      # GSTR-1 and GSTR-3B reports
│   ├── xml_exchange.html     # Tally XML Import & Export portal
│   ├── backup_restore.html   # Backup & Restore manager
│   ├── company_select.html   # Company Selector (F3)
│   ├── company_form.html     # Company Creation & Alteration Form
│   ├── ledger_statement.html # Ledger statement with running balance
│   ├── outstanding.html      # Bills Receivable & Payable
│   ├── cash_bank.html        # Cash & Bank Book liquidity
│   ├── ratio_analysis.html   # Financial performance ratios
│   ├── daybook.html          # Day Book with direct invoice print action
│   ├── trial_balance.html    # Real-time Trial Balance with Dr/Cr verification
│   ├── balance_sheet.html    # T-format Schedule III Balance Sheet
│   ├── profit_loss.html      # Trading & Profit & Loss Statement
│   ├── stock_summary.html    # Item-wise Inward/Outward/Closing stock report
│   ├── chart_of_accounts.html# 28-Group hierarchy view
│   ├── ledger_form.html      # Ledger creation screen (Alt+C)
│   └── stock_item_form.html  # Stock item creation screen
│
└── tests\
    ├── test_phase1.py        # Database schema, foreign keys & constraint tests
    ├── test_phase2.py        # Accounting engine, GST math & stock movement tests
    ├── test_phase3.py        # Invoicing, GST returns & Tally XML tests
    ├── test_phase4.py        # Multi-company, Outstandings, Ledger & Ratio tests
    └── test_phase5.py        # Backups, restoration, e-Invoice & e-Way bill tests
```

---

## How to Run

### Option 1: 1-Click Launch (Recommended)
Double-click:
```
E:\Tally Soft\start_tally.bat
```

### Option 2: Terminal Command
```bash
python run.py serve
```
Then navigate to: **`http://127.0.0.1:5000`**

### Run All 22 Automated Tests
```bash
python -m unittest discover tests
```
