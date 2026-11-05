# TallySoft Offline Accounting System
## Client Handover & Operational Manual
**Application Version:** 1.0.0 Stable Offline Production Release  
**Target Environment:** Microsoft Windows 10 / 11 (64-bit)  
**Distribution Directory:** `E:\Tally Soft`

---

## 1. System Overview

**TallySoft** is a standalone, offline, double-entry accounting and GST compliance system designed to mirror the authentic keyboard ergonomics, menu architecture, and financial reporting standards of TallyPrime.

### Core Architectural Highlights
- **100% Offline & Private:** Operates entirely locally on your Windows machine with zero cloud tracking, zero external network calls, and zero subscription lockouts.
- **Strict Double-Entry Engine:** Automatic debit/credit validation (`Dr = Cr`) preventing out-of-balance vouchers.
- **Indian GST Engine:** Automatic intra-state (CGST + SGST) and inter-state (IGST) split with GSTR-1 (B2B, B2CS, HSN) and GSTR-3B statutory generation.
- **Zero-Loss Data Safety:** Built on SQLite WAL mode with point-in-time atomic online database snapshots (`backups/`).

---

## 2. Quick Installation & Launch Guide

### System Requirements
- Windows 10 or Windows 11 (64-bit)
- Python 3.10 or higher installed (with "Add Python to PATH" enabled)
- Any modern web browser (Google Chrome, Microsoft Edge, Mozilla Firefox)

### Step 1: One-Time Automated Setup
1. Open the project folder `E:\Tally Soft`.
2. Double-click the file **`setup_environment.bat`**.
3. The script will:
   - Check your Python installation.
   - Install local runtime requirements (`Flask`).
   - Initialize the clean SQLite production database schema.
   - Create a **"TallySoft Offline Accounting"** shortcut directly on your Windows Desktop.

### Step 2: Daily Launch
- Simply double-click the **`TallySoft Offline Accounting`** desktop shortcut, or run **`start_tally.bat`** from the `E:\Tally Soft` folder.
- The software will automatically start the local background service and open your browser at:
  ```
  http://127.0.0.1:5000
  ```

---

## 3. Initial Company Creation Guide

When you launch TallySoft for the first time:

1. Press **`Alt + K`** or click **`K: Company`** on the top blue bar.
2. Select **`Create Company`** (or navigate to `/company/create`).
3. Fill in the company details:
   - **Company Name:** (e.g. *Zenith Technologies Pvt Ltd*)
   - **Mailing Name & Address:** Registered address for invoice headers.
   - **State:** Select state from the dropdown (e.g. *Maharashtra*). The system will automatically populate the 2-digit GST state code (e.g. *27*).
   - **GSTIN:** 15-character Goods and Services Tax Identification Number.
   - **Financial Year Begins From:** (e.g. *01-Apr-2026*)
   - **Books Beginning From:** (e.g. *01-Apr-2026*)
4. Press **`Ctrl + A`** or click **`Accept`**.
5. The software will automatically seed the standard **28 Tally Ledger Groups** (Capital Account, Current Assets, Current Liabilities, Sundry Debtors, Sundry Creditors, Direct Incomes, etc.) and default tax ledgers (`Input CGST`, `Output CGST`, `Input SGST`, `Output SGST`, `Input IGST`, `Output IGST`, `Round Off`).

---

## 4. Master Creation Guide

### 4.1 Creating Ledgers
1. From the Gateway of Tally, select **`Create`** -> **`Ledger`** (or press shortcut).
2. Enter the **Ledger Name** (e.g., *Alpha Infotech*, *State Bank of India*, *Office Electricity*).
3. Select the **Under (Group)**:
   - For Customers: Select **`Sundry Debtors`**.
   - For Suppliers: Select **`Sundry Creditors`**.
   - For Bank Accounts: Select **`Bank Accounts`**.
   - For Operational Costs: Select **`Indirect Expenses`** or **`Direct Expenses`**.
4. Enter statutory info: State Code, GSTIN, PAN, and Bank Details.
5. Enter **Opening Balance** (if any) and designate **Dr** (Asset/Expense) or **Cr** (Liability/Equity).
6. Press **`Ctrl + A`** or click **`Accept`**.

### 4.2 Creating Stock Items
1. From the Gateway of Tally, select **`Create`** -> **`Stock Item`**.
2. Enter **Item Name** (e.g., *Dell 27-inch 4K Monitor*).
3. Assign **Stock Group** (e.g., *Hardware Components*).
4. Select **Unit of Measure (UOM)** (e.g., *Nos*, *Pcs*, *Kgs*).
5. Specify **Applicable GST Rate** (e.g., *18%*, *12%*, *5%*, *28%*).
6. Enter Opening Quantity and Rate (if opening stock exists).
7. Save with **`Ctrl + A`**.

---

## 5. Daily Accounting Voucher Entry Guide

Navigate to **`Gateway of Tally` -> `Vouchers`** (or press **`V`**). Use the standard function keys to switch voucher types:

### 5.1 Sales Voucher (`F8`)
- **Use Case:** Billing goods or services to customers.
- **Workflow:**
  1. Select **Party A/c Name** (Sundry Debtor or Cash).
  2. The invoice mode displays party GSTIN and billing address.
  3. Select stock items, enter Quantity and Rate.
  4. The system calculates taxable amounts and automatically applies:
     - **CGST + SGST** if customer is in the same state.
     - **IGST** if customer is in a different state.
  5. Press **`Ctrl + A`** to save and post.
  6. Click **`Print Tax Invoice`** to generate the GST Tax Invoice.

### 5.2 Purchase Voucher (`F9`)
- **Use Case:** Inward supplies and raw materials from vendors.
- **Workflow:**
  1. Enter Supplier Invoice Number and Date.
  2. Select Supplier Ledger (Sundry Creditor).
  3. Add items and rates.
  4. Save voucher. Stock quantities increase automatically and the supplier account is credited.

### 5.3 Payment Voucher (`F5`)
- **Use Case:** Paying suppliers, expenses, salaries, or taxes.
- **Workflow:**
  1. Select Account to credit (**Cash** or **Bank Account**).
  2. Select Ledger to debit (e.g., *Vendor Name* or *Office Rent*).
  3. Enter Amount and Cheque / Reference number.
  4. Save voucher.

### 5.4 Receipt Voucher (`F6`)
- **Use Case:** Receiving funds from customers or other incomes.
- **Workflow:**
  1. Select Account to debit (**Cash** or **Bank Account**).
  2. Select Ledger to credit (e.g., *Customer Name*).
  3. Enter Amount received.
  4. Save voucher. Customer outstanding balance reduces automatically.

### 5.5 Contra Voucher (`F4`)
- **Use Case:** Internal cash and bank transfers (Cash deposit, Cash withdrawal, Bank-to-Bank transfer).
- **Workflow:**
  1. Select receiving ledger (Dr) and paying ledger (Cr).
  2. Enter transfer amount. No outside party or tax ledger is affected.

### 5.6 Journal Voucher (`F7`)
- **Use Case:** Adjusting entries, depreciation, provisions, prepaid expenses, and credit corrections.
- **Rule:** Total Debits must exactly equal Total Credits.

---

## 6. Financial Reports & Invoicing

Access reports directly from the **Gateway of Tally**:
- **Balance Sheet (`B`):** Schedule III T-Format displaying Liabilities (Capital, Reserves & Surplus, Net Profit, Current Liabilities) and Assets (Fixed Assets, Current Assets, Bank, Cash, Debtors).
- **Profit & Loss A/c (`P`):** Trading Account (Sales, Cost of Goods Sold, Gross Profit) and P&L Account (Operating Incomes, Indirect Expenses, Net Profit).
- **Trial Balance (`Gateway -> Display -> Trial Balance`):** All ledger balances with real-time equality check (`Total Dr == Total Cr`).
- **Day Book (`Gateway -> Display -> Day Book`):** Chronological log of all transactions with date range filters.
- **Cash / Bank Summary (`Gateway -> Display -> Account Books`):** Daily closing cash and bank balances.
- **GST Reports (`Gateway -> Display -> Statutory Reports`):**
  - **GSTR-1:** B2B Table 4, B2CS Table 7, HSN Summary Table 12.
  - **GSTR-3B:** Outward supplies, eligible Input Tax Credit (ITC).

---

## 7. Data Backup and Disaster Recovery

TallySoft protects your data through atomic SQLite online snapshot backups:

### To Create a Backup:
1. Click **`Y: Data`** on the top menu bar (or press **`Alt + Y`**).
2. Select **`Backup`**.
3. Optionally enter a memo note (e.g., *Pre_Audit_Backup*).
4. Click **`Create Backup`**.
5. An atomic snapshot file named `tally_backup_YYYYMMDD_HHMMSS.db` is saved into `E:\Tally Soft\backups\`.

### To Restore a Backup:
1. Click **`Alt + Y`** -> **`Restore`**.
2. Select the backup snapshot from the chronological list.
3. Confirm restoration. The database is safely restored without restarting your machine.

---

## 8. Complete Keyboard Shortcuts Reference

| Shortcut | Description / Action |
| :--- | :--- |
| **`Enter`** | Accept field / Move to next field / Open highlighted item |
| **`Esc`** | Cancel form / Close modal / Go back one screen |
| **`Ctrl + A`** | Accept and Save voucher or master immediately |
| **`Alt + K`** | Company Menu (Create, Alter, Select, Shut) |
| **`Alt + Y`** | Data Menu (Backup & Restore) |
| **`Alt + Z`** | Exchange Menu (Tally XML Export / Import) |
| **`Alt + G`** | "Go To" universal search and navigation palette |
| **`Alt + F1`** | Toggle Detailed vs Condensed report view |
| **`F2`** | Change Date / Period |
| **`F4`** | Contra Voucher |
| **`F5`** | Payment Voucher |
| **`F6`** | Receipt Voucher |
| **`F7`** | Journal Voucher |
| **`F8`** | Sales Voucher |
| **`F9`** | Purchase Voucher |
| **`F10`** | Other Vouchers list |
| **`F11`** | Company Features configuration |
| **`F12`** | Voucher Configuration modal (Cr/Dr, negative cash warning, bill-wise) |

---

## 9. Troubleshooting & FAQ

### Issue: Port 5000 is in use by another application
- **Solution:** Launch with a custom port using the command line:
  ```cmd
  python run.py serve --port 5050
  ```
  Then access `http://127.0.0.1:5050` in your browser.

### Issue: Accidentally entered an incorrect voucher
- **Solution:** 
  1. Open **`Day Book`**.
  2. Click on the voucher to view details.
  3. Click **`Cancel Voucher`** to safely reverse all ledger postings while retaining audit trail numbering, or click **`Delete Voucher`** if you wish to remove it entirely.

### Issue: Trial balance reports out of balance
- **Solution:** TallySoft prevents saving any voucher where Dr != Cr. If opening balances of ledgers do not match, review **`Gateway -> Chart of Accounts`** and verify the opening balances of your Capital and Asset accounts.

### Issue: Database file location
- The production database is stored at:
  ```
  E:\Tally Soft\data\tally_offline.db
  ```
  Never open or edit this file directly with text editors. Use `Alt + Y -> Backup` to make copies.

---

## 10. Production Release Notes

**Version 1.0.0 (04-Nov-2026):**
- Initial production release ready for client operations.
- Full double-entry accounting engine with 75 verified automated tests.
- Indian GST tax calculations, invoice templates, and GSTR-1/3B reporting.
- Real-time stock tracking with FIFO valuation.
- Authentic TallyPrime keyboard navigation with F12 configuration modal.
- Standalone desktop launcher (`start_tally.bat`) and desktop shortcut installer (`create_desktop_shortcut.bat`).
