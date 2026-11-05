#!/usr/bin/env python3
"""
TallySoft Offline Accounting System - CLI & Service Entry Point
"""

import sys
import argparse
from app.config import DATABASE_PATH, APP_NAME, APP_VERSION
from app.database import init_db, create_company, list_companies, get_company_groups, get_company_ledgers


def main():
    parser = argparse.ArgumentParser(description=f"{APP_NAME} v{APP_VERSION}")
    subparsers = parser.add_subparsers(dest="command", help="Available sub-commands")

    # Command: serve / ui
    p_serve = subparsers.add_parser("serve", help="Launch the offline TallyPrime web interface")
    p_serve.add_argument("--port", type=int, default=5000, help="Port to listen on (default: 5000)")

    # Command: init
    subparsers.add_parser("init", help="Initialize SQLite database schema")

    # Command: create-company
    p_comp = subparsers.add_parser("create-company", help="Create a new company")
    p_comp.add_argument("--name", required=True, help="Company trading name")
    p_comp.add_argument("--gstin", default="", help="15-character GSTIN")
    p_comp.add_argument("--state", default="Maharashtra", help="State name")
    p_comp.add_argument("--state-code", default="27", help="2-digit GST state code")
    p_comp.add_argument("--pan", default="", help="PAN number")
    p_comp.add_argument("--address", default="", help="Registered address")

    # Command: list-companies
    subparsers.add_parser("list-companies", help="List registered companies")

    # Command: list-groups
    p_groups = subparsers.add_parser("list-groups", help="List ledger groups for a company")
    p_groups.add_argument("--company-id", type=int, default=1, help="Company ID (default: 1)")

    # Command: list-ledgers
    p_ledgers = subparsers.add_parser("list-ledgers", help="List ledgers for a company")
    p_ledgers.add_argument("--company-id", type=int, default=1, help="Company ID (default: 1)")

    # If no args provided, default to serve
    if len(sys.argv) == 1:
        from app.server import start_server
        start_server()
        return

    args = parser.parse_args()

    if args.command == "serve":
        from app.server import start_server
        start_server(port=args.port)

    elif args.command == "init":
        print(f"Initializing database at: {DATABASE_PATH}")
        init_db()
        print("Database schema successfully created with full constraints.")

    elif args.command == "create-company":
        init_db()
        try:
            cid = create_company(
                name=args.name,
                gstin=args.gstin if args.gstin else None,
                state=args.state,
                state_code=args.state_code,
                pan=args.pan if args.pan else None,
                address=args.address if args.address else None,
            )
            print(f"Company created successfully! Company ID: {cid}")
            print(f"Standard 28 Tally Groups, Default Tax Ledgers, and UOMs initialized.")
        except Exception as e:
            print(f"Error creating company: {e}")

    elif args.command == "list-companies":
        comps = list_companies()
        if not comps:
            print("No companies found in database.")
        else:
            print(f"\nRegistered Companies ({len(comps)}):")
            print("-" * 75)
            print(f"{'ID':<4} | {'Name':<30} | {'GSTIN':<16} | {'State':<15}")
            print("-" * 75)
            for c in comps:
                gstin = c['gstin'] or 'UNREGISTERED'
                print(f"{c['id']:<4} | {c['name']:<30} | {gstin:<16} | {c['state']:<15}")

    elif args.command == "list-groups":
        groups = get_company_groups(args.company_id)
        if not groups:
            print(f"No groups found for company ID {args.company_id}.")
        else:
            print(f"\nLedger Groups for Company #{args.company_id} ({len(groups)} groups):")
            print("-" * 75)
            print(f"{'ID':<4} | {'Group Name':<30} | {'Nature':<12} | {'Parent Group':<20}")
            print("-" * 75)
            for g in groups:
                parent = g['parent_name'] or 'PRIMARY'
                print(f"{g['id']:<4} | {g['name']:<30} | {g['nature']:<12} | {parent:<20}")

    elif args.command == "list-ledgers":
        ledgers = get_company_ledgers(args.company_id)
        if not ledgers:
            print(f"No ledgers found for company ID {args.company_id}.")
        else:
            print(f"\nLedgers for Company #{args.company_id} ({len(ledgers)} ledgers):")
            print("-" * 75)
            print(f"{'ID':<4} | {'Ledger Name':<25} | {'Group':<25} | {'Balance Type':<10}")
            print("-" * 75)
            for l in ledgers:
                print(f"{l['id']:<4} | {l['name']:<25} | {l['group_name']:<25} | {l['opening_balance_type']:<10}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
