#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/sync_emails_to_supabase.py
================================
Syncs and manages emails in the dedicated 'public.email_accounts' Supabase table.
Checks whether an email already exists in Supabase before appending.

Usage:
  python tools/sync_emails_to_supabase.py --check email@domain.com
  python tools/sync_emails_to_supabase.py --add "email|password|refresh_token|client_id"
  python tools/sync_emails_to_supabase.py --sync-all
"""

import sys
import json
import argparse
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parent
sys.path.insert(0, str(TOOLS_DIR))

import supabase_logger


def check_single_email(email: str):
    print(f"Checking Supabase for email: {email}...")
    res = supabase_logger.check_email_exists(email)
    if res.get("table_missing"):
        print("\n[!] Supabase table 'email_accounts' does not exist yet.")
        print("Please run the SQL schema in your Supabase SQL Editor:")
        print(f"File: {PROJECT_ROOT / 'tools' / 'supabase_schema.sql'}\n")
        return

    if res.get("exists"):
        rec = res["record"]
        print(f"\n[EXISTS] Email is already registered in Supabase:")
        print(f"  Email:        {rec.get('email')}")
        print(f"  Provider:     {rec.get('provider')}")
        print(f"  Status:       {rec.get('status')}")
        print(f"  Platforms:    {rec.get('used_in_platforms')}")
        print(f"  Last Used:    {rec.get('last_used_platform')} at {rec.get('last_used_at')}")
    else:
        print(f"\n[AVAILABLE] Email '{email}' does NOT exist in Supabase yet. Safe to use & append.")


def add_or_update_email(account_str: str, platform: str = ""):
    parts = account_str.strip().split("|")
    email = parts[0].strip()
    print(f"Processing email: {email}...")

    # Check existence first
    check = supabase_logger.check_email_exists(email)
    if check.get("table_missing"):
        print("\n[!] Supabase table 'email_accounts' does not exist yet.")
        print("Please run the SQL schema in your Supabase SQL Editor:")
        print(f"File: {PROJECT_ROOT / 'tools' / 'supabase_schema.sql'}\n")
        return

    if check.get("exists"):
        print(f"  -> Email already exists in Supabase. Merging platform info...")
    else:
        print(f"  -> Email is new. Appending to 'email_accounts' table in Supabase...")

    res = supabase_logger.log_email_to_supabase({
        "email": email,
        "full_mail_string": account_str,
        "platform": platform,
    })

    if res.get("success"):
        action = "Appended new email" if res.get("is_new") else "Updated existing email"
        print(f"[OK] {action} in Supabase: {email}")
    else:
        print(f"[ERROR] Failed to save email: {res.get('error') or res.get('reason')}")


def sync_all_identities():
    identities_file = PROJECT_ROOT / "output" / "identities.json"
    if not identities_file.exists():
        print("No output/identities.json found.")
        return

    data = json.loads(identities_file.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        data = [data]

    print(f"Found {len(data)} identities in local store. Syncing to Supabase 'email_accounts'...")
    new_count = 0
    updated_count = 0

    for rec in data:
        email = rec.get("email")
        if not email:
            continue
        account_str = rec.get("account_string", "")
        # Find which platforms were used
        platforms = []
        for p_name, p_val in rec.get("platforms", {}).items():
            if isinstance(p_val, dict) and p_val.get("status") in ("ok", "active", "suspended", "checkpoint", "running"):
                platforms.append(p_name)

        res = supabase_logger.log_email_to_supabase({
            "email": email,
            "full_mail_string": account_str,
            "platform": platforms[0] if platforms else "",
            "used_in_platforms": platforms,
            "status": "ACTIVE" if rec.get("state") == "active" else "USED"
        })

        if res.get("table_missing"):
            print("\n[!] Supabase table 'email_accounts' does not exist yet.")
            print("Please run the SQL schema in your Supabase SQL Editor:")
            print(f"File: {PROJECT_ROOT / 'tools' / 'supabase_schema.sql'}\n")
            return

        if res.get("success"):
            if res.get("is_new"):
                new_count += 1
                print(f"  [NEW] Appended {email}")
            else:
                updated_count += 1
                print(f"  [EXISTING] Merged {email}")
        else:
            print(f"  [SKIP/ERROR] {email}: {res.get('error') or res.get('reason')}")

    print(f"\nDone! Appended {new_count} new emails, updated {updated_count} existing emails in Supabase.")


def main():
    parser = argparse.ArgumentParser(description="Supabase Email Accounts Manager")
    parser.add_argument("--check", type=str, help="Check if an email already exists in Supabase")
    parser.add_argument("--add", type=str, help="Add or update an email/account_string in Supabase with duplicate check")
    parser.add_argument("--platform", type=str, default="", help="Platform to associate (e.g. facebook, metricool)")
    parser.add_argument("--sync-all", action="store_true", help="Sync all emails from local identities to Supabase")

    args = parser.parse_args()

    if args.check:
        check_single_email(args.check)
    elif args.add:
        add_or_update_email(args.add, args.platform)
    elif args.sync_all:
        sync_all_identities()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
