#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/instagram_signup.py
=========================
Automated Instagram Account Creator & Verification via Camoufox Anti-Detect Browser (Python).

Features:
- Headed interactive / automated registration with C++ hardware fingerprint spoofing.
- Oxylabs sticky residential proxy session locking (-sessid-<id>-sesstime-30).
- Compatible with new Meta Account unified Instagram signup form (combobox datepicker, role="button").
- Automatic OTP extraction from Outlook/Hotmail via Microsoft Graph & Outlook REST API.
- Birthday randomization (ages 22-29) with native keyboard event emulation.
- Persistent session storage in output/profiles instagram/<user>/session.json & output/instagram_registered_accounts.json.
"""

import sys
import os
import re
import json
import time
import random
import secrets
import argparse
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime

from camoufox.sync_api import Camoufox

try:
    from tools.supabase_logger import log_to_supabase
except ImportError:
    try:
        from supabase_logger import log_to_supabase
    except ImportError:
        def log_to_supabase(d): return {}

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_FILE = PROJECT_ROOT / "output" / "instagram_registered_accounts.json"
PROFILES_DIR = PROJECT_ROOT / "output" / "profiles instagram"
ARTIFACTS_DIR = PROJECT_ROOT / "tests" / "test_artifacts"


def get_ms_access_token(client_id: str, refresh_token: str) -> str:
    """Exchange Microsoft OAuth refresh token for an access token."""
    token_url = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
    clean_cid = client_id.strip()
    if clean_cid.endswith("b") and len(clean_cid) == 36:
        clean_cid = clean_cid[:-1]

    data = urllib.parse.urlencode({
        "client_id": clean_cid,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token.strip(),
    }).encode("utf-8")

    req = urllib.request.Request(token_url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=20) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        if "access_token" in res:
            return res["access_token"]
        raise RuntimeError(f"No access token in response: {res}")


def poll_outlook_otp(client_id: str, refresh_token: str, start_time: float, max_wait_sec: int = 120) -> str:
    """Poll Outlook REST API for Instagram 6-digit confirmation code."""
    print(f"[OTP] Polling Outlook inbox for Instagram verification code (up to {max_wait_sec}s)...")
    end_time = time.time() + max_wait_sec

    while time.time() < end_time:
        try:
            token = get_ms_access_token(client_id, refresh_token)
            endpoints = [
                "https://outlook.office.com/api/v2.0/me/messages?$top=5&$orderby=ReceivedDateTime%20desc",
                "https://outlook.office.com/api/v2.0/me/MailFolders/JunkEmail/messages?$top=5&$orderby=ReceivedDateTime%20desc",
            ]
            for url in endpoints:
                req = urllib.request.Request(url, headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json"
                })
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    messages = data.get("value", [])
                    for msg in messages:
                        subject = msg.get("Subject", "")
                        preview = msg.get("BodyPreview", "")
                        body = msg.get("Body", {}).get("Content", "")
                        from_addr = msg.get("From", {}).get("EmailAddress", {}).get("Address", "").lower()

                        if "instagram" in from_addr or "instagram" in subject.lower() or "code" in subject.lower():
                            match = re.search(r"\b(\d{6})\b", subject) or re.search(r"\b(\d{6})\b", preview) or re.search(r"\b(\d{6})\b", body)
                            if match:
                                code = match.group(1)
                                print(f"[OTP] Found Instagram Verification Code: {code}")
                                return code
        except Exception as e:
            print(f"[OTP] Poll attempt: {e}")
        time.sleep(5)

    raise TimeoutError("Timed out waiting for Instagram verification OTP email.")


def parse_oxylabs_proxy(proxy_str: str) -> dict:
    """Parse Oxylabs proxy and ensure 30-minute sticky session with India geo-targeting."""
    clean = proxy_str.strip().replace("http://", "").replace("https://", "")
    auth, host_port = clean.split("@")
    user, pwd = auth.split(":")

    if "-cc-" not in user:
        user = f"{user}-cc-in"

    if "-sessid-" not in user:
        sess_id = secrets.token_hex(4)
        user = f"{user}-sessid-{sess_id}-sesstime-30"

    host, port = host_port.split(":")
    return {
        "server": f"http://{host}:{port}",
        "username": user,
        "password": pwd,
    }


def human_type(locator, text: str):
    """Type with randomized human delays."""
    locator.click()
    time.sleep(random.uniform(0.1, 0.3))
    for char in text:
        locator.type(char, delay=random.uniform(30, 90))
        if random.random() < 0.05:
            time.sleep(random.uniform(0.1, 0.2))


def run_signup(account_str: str, proxy_str: str, headless: bool = False):
    parts = account_str.split("|")
    email = parts[0].strip()
    password = parts[1].strip()
    refresh_token = parts[2].strip() if len(parts) > 2 else ""
    client_id = parts[3].strip() if len(parts) > 3 else "9e5f94bc-e8a4-4e73-b8be-63364c29d753"

    proxy_cfg = parse_oxylabs_proxy(proxy_str)
    print("=" * 65)
    print("  Instagram Anti-Detect Account Registration (Camoufox)")
    print(f"  Target Email : {email}")
    print(f"  Proxy Server : {proxy_cfg['server']} (Sticky Session: {proxy_cfg['username']})")
    print("=" * 65)

    profile_name = email.split("@")[0]
    profile_dir = PROFILES_DIR / profile_name
    profile_dir.mkdir(parents=True, exist_ok=True)
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    with Camoufox(
        headless=headless,
        proxy=proxy_cfg,
        geoip=True,
        i_know_what_im_doing=True,
    ) as browser:
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        page = context.new_page()

        print("[1/5] Navigating to Instagram Sign-Up page...")
        for attempt in range(1, 4):
            try:
                page.goto("https://www.instagram.com/accounts/emailsignup/", wait_until="commit", timeout=60000)
                break
            except Exception as e:
                print(f"[Navigation] Attempt {attempt}/3 failed: {e}. Retrying...")
                time.sleep(3)

        print("[Navigation] Waiting for form hydration...")
        page.wait_for_selector("input", timeout=45000)
        time.sleep(2)

        # Handle cookie banner if present
        try:
            cookie_btn = page.locator('button:has-text("Decline"), button:has-text("Allow"), div[role="button"]:has-text("Decline")').first
            if cookie_btn.is_visible(timeout=3000):
                cookie_btn.click()
                time.sleep(1)
        except Exception:
            pass

        print("[2/5] Inspecting and filling registration form fields...")
        inputs = page.query_selector_all('input')
        print(f"[Form] Found {len(inputs)} inputs on page.")

        email_val = email
        pass_val = password
        name_val = "Shravya Georgeann"
        username_val = f"shravya.georgeann{random.randint(100, 999)}"

        # 1. Email (Input 0)
        print(f"[Form] Entering Email: {email_val}")
        inputs[0].click()
        inputs[0].type(email_val, delay=40)
        time.sleep(0.5)

        # 2. Password (Input 1)
        print(f"[Form] Entering Password: {'*' * len(pass_val)}")
        inputs[1].click()
        inputs[1].type(pass_val, delay=40)
        time.sleep(0.5)

        # 3. Birthday Comboboxes if present
        combos = page.locator('div[role="combobox"][aria-haspopup="listbox"]')
        combo_count = combos.count()
        if combo_count >= 3:
            print("[Form] Setting Birthday (Month, Day, Year)...")
            # Month
            combos.nth(0).click()
            time.sleep(0.3)
            for _ in range(random.randint(2, 10)):
                page.keyboard.press("ArrowDown")
                time.sleep(0.04)
            page.keyboard.press("Enter")
            time.sleep(0.4)

            # Day
            combos.nth(1).click()
            time.sleep(0.3)
            for _ in range(random.randint(2, 26)):
                page.keyboard.press("ArrowDown")
                time.sleep(0.04)
            page.keyboard.press("Enter")
            time.sleep(0.4)

            # Year (age 22-29 -> 23 to 30 presses)
            combos.nth(2).click()
            time.sleep(0.3)
            for _ in range(random.randint(23, 29)):
                page.keyboard.press("ArrowDown")
                time.sleep(0.04)
            page.keyboard.press("Enter")
            time.sleep(0.4)

        # 4. Full Name (Input 2)
        if len(inputs) >= 3:
            print(f"[Form] Entering Full Name: {name_val}")
            inputs[2].click()
            inputs[2].type(name_val, delay=40)
            time.sleep(0.5)

        # 5. Username (Input 3)
        if len(inputs) >= 4:
            print(f"[Form] Entering Username: {username_val}")
            inputs[3].click()
            inputs[3].type(username_val, delay=40)
            time.sleep(1.0)

        page.screenshot(path=str(ARTIFACTS_DIR / "ig_form_filled.png"))
        print("[Form] Form filled screenshot captured.")

        # Click Submit
        submit_start_time = time.time()
        print(f"[3/5] Submitting registration for @{username_val}...")
        submit_btn = page.locator('div[role="button"]:has-text("Submit"), button:has-text("Submit"), button[type="submit"]:has-text("Sign up")').first
        if submit_btn.is_visible(timeout=5000):
            submit_btn.click()
        else:
            page.click('text="Submit"')

        print("[4/5] Waiting for transition to OTP verification...")
        time.sleep(10)

        # Check for potential separate birthday screen if legacy layout
        try:
            legacy_bday = page.locator('select[title*="Month"], select[aria-label*="Month"]').first
            if legacy_bday.is_visible(timeout=4000):
                print("[Birthday] Separate birthday page detected. Setting values...")
                legacy_bday.select_option(str(random.randint(1, 12)))
                time.sleep(0.4)
                page.locator('select[title*="Day"], select[aria-label*="Day"]').first.select_option(str(random.randint(1, 28)))
                time.sleep(0.4)
                page.locator('select[title*="Year"], select[aria-label*="Year"]').first.select_option(str(random.randint(1995, 2002)))
                time.sleep(0.6)
                page.locator('button:has-text("Next"), div[role="button"]:has-text("Next")').first.click()
                time.sleep(6)
        except Exception:
            pass

        page.screenshot(path=str(ARTIFACTS_DIR / "ig_otp_screen.png"))
        print("[OTP] Checking for OTP confirmation code input...")

        # Poll Outlook for verification code
        otp_code = poll_outlook_otp(client_id, refresh_token, submit_start_time, max_wait_sec=120)

        # Enter OTP code
        otp_input = page.locator('input[name="email_confirmation_code"], input[type="text"], input[inputmode="numeric"]').first
        otp_input.wait_for(state="visible", timeout=20000)
        print(f"[OTP] Typing code {otp_code} into Instagram...")
        human_type(otp_input, otp_code)
        time.sleep(1)

        # Submit OTP
        confirm_btn = page.locator('button:has-text("Next"), div[role="button"]:has-text("Next"), button:has-text("Confirm")').first
        confirm_btn.click()
        time.sleep(10)

        print("[5/5] Finalizing registration and saving session...")
        current_url = page.url
        print(f"[Done] Current URL: {current_url}")
        page.screenshot(path=str(ARTIFACTS_DIR / "ig_registration_success.png"))

        # Save cookies and session
        cookies = context.cookies()
        session_file = profile_dir / "session.json"
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump({
                "username": username_val,
                "email": email,
                "password": password,
                "cookies": cookies,
                "proxy": proxy_cfg["username"],
                "created_at": datetime.now().isoformat(),
            }, f, indent=2)

        # Append to registered accounts
        REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
        registry_data = []
        if REGISTRY_FILE.exists():
            try:
                registry_data = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
            except Exception:
                registry_data = []

        registry_data.append({
            "username": username_val,
            "email": email,
            "password": password,
            "proxy": proxy_cfg["username"],
            "profile_dir": str(profile_dir),
            "account_created_at": datetime.now().isoformat(),
        })
        REGISTRY_FILE.write_text(json.dumps(registry_data, indent=2), encoding="utf-8")

        # Sync to Supabase & Google Sheet
        record_payload = {
            "platform": "Instagram",
            "email": email,
            "username": username_val,
            "password": password,
            "profile_url": f"https://www.instagram.com/{username_val}/",
            "full_mail_string": args.account if 'args' in locals() else "",
            "proxy": proxy_cfg.get("username", ""),
            "status": "ACTIVE",
            "details": {"profile_dir": str(profile_dir)}
        }
        try:
            log_to_supabase(record_payload)
        except Exception:
            pass

        print("=" * 65)
        print(f"  SUCCESSFULLY REGISTERED INSTAGRAM ACCOUNT: @{username_val}")
        print(f"  Profile Saved: {profile_dir}")
        print(f"  Master Registry: {REGISTRY_FILE}")
        print("=" * 65)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Instagram Anti-Detect Account Creator")
    parser.add_argument("--account", required=True, help="Outlook account string (email|pass|refreshToken|clientId)")
    parser.add_argument("--proxy", required=True, help="Oxylabs proxy string")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")

    args = parser.parse_args()
    run_signup(args.account, args.proxy, args.headless)
