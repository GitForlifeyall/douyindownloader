#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/metricool_profile_manager.py
==================================
Manages persistent isolated browser profiles for Metricool accounts.

Features:
1. Performs automated Metricool login using saved credentials.
2. Intercepts email OTP verification codes via Microsoft Graph API.
3. Automatically types OTP and completes authentication into Metricool dashboard.
4. Saves full persistent browser profile, cookies, and session state into:
   output/profiles metricool/<account_name>/
   (and mirrored at: profiles metricool/<account_name>/)
5. Supports both Playwright persistent context and Camoufox stealth browser.
6. Provides '--open <email>' to launch directly into an existing authenticated session.
"""

import argparse
import html
import json
import logging
import os
import re
import shutil
import string
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("metricool_profile_mgr")

OUTPUT_PROFILES_DIR = Path("output/profiles metricool")
ROOT_PROFILES_DIR = Path("profiles metricool")
REGISTERED_ACCOUNTS_FILE = Path("output/metricool_registered_accounts.json")


def sanitize_profile_name(email: str) -> str:
    """Creates a clean filesystem-safe folder name from an email."""
    name = email.split("@")[0]
    return re.sub(r"[^\w\-]", "_", name)


def load_known_account(email: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Loads account credentials from registered accounts JSON."""
    if not REGISTERED_ACCOUNTS_FILE.exists():
        return None
    try:
        data = json.loads(REGISTERED_ACCOUNTS_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return None
        if email:
            for acc in data:
                if acc.get("email", "").lower() == email.lower():
                    return acc
        elif data:
            return data[0]
    except Exception as e:
        logger.warning(f"Could not read registered accounts: {e}")
    return None


def get_ms_access_token(client_id: str, refresh_token: str) -> str:
    """Exchanges Microsoft refresh token for Graph API access token."""
    token_url = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
    payload = urllib.parse.urlencode({
        "client_id": client_id,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": "https://graph.microsoft.com/Mail.Read offline_access",
    }).encode("utf-8")

    req = urllib.request.Request(
        token_url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return data["access_token"]


def poll_metricool_login_otp(
    client_id: str,
    refresh_token: str,
    max_wait_seconds: int = 60,
    poll_interval: int = 4,
) -> Optional[str]:
    """Polls Outlook inbox for Metricool's 6-digit login verification OTP code."""
    logger.info("Polling Outlook inbox for login verification code...")
    start_time = time.time()

    while time.time() - start_time < max_wait_seconds:
        try:
            token = get_ms_access_token(client_id, refresh_token)
            url = "https://graph.microsoft.com/v1.0/me/messages?$top=3&$select=subject,sender,bodyPreview,body,receivedDateTime&$orderby=receivedDateTime%20desc"
            req = urllib.request.Request(
                url,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                msgs = json.loads(resp.read().decode("utf-8")).get("value", [])
                for m in msgs:
                    subject = m.get("subject", "")
                    content = m.get("body", {}).get("content", "") + " " + m.get("bodyPreview", "")
                    if "verify your email" in subject.lower() or "metricool" in subject.lower():
                        match = re.search(r"\b(\d{6})\b", content)
                        if match:
                            otp = match.group(1)
                            logger.info(f"Retrieved login verification OTP: {otp}")
                            return otp
        except Exception as e:
            logger.warning(f"Inbox poll warning: {e}")

        time.sleep(poll_interval)

    logger.warning("Timed out waiting for login OTP email.")
    return None


def is_camoufox_ready() -> bool:
    """Checks if camoufox-cli is installed and its browser binary is downloaded."""
    try:
        res = subprocess.run(["camoufox-cli", "url"], capture_output=True, text=True, timeout=5)
        return res.returncode == 0 or "Camoufox" in res.stderr
    except Exception:
        return False


def login_and_save_profile(
    email: str,
    password: str,
    refresh_token: Optional[str] = None,
    client_id: Optional[str] = None,
    headless: bool = False,
    engine: str = "camoufox",
) -> Dict[str, Any]:
    """
    Automates Metricool login, completes email OTP verification,
    and saves the persistent profile and cookies to 'output/profiles metricool/<stem>/'.
    """
    stem = sanitize_profile_name(email)
    profile_path = OUTPUT_PROFILES_DIR / stem
    profile_path.mkdir(parents=True, exist_ok=True)

    # Mirror path
    ROOT_PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    root_profile_path = ROOT_PROFILES_DIR / stem

    logger.info(f"Setting up persistent profile ({engine}) at: {profile_path}")

    if engine == "camoufox":
        camoufox_script = Path("tools/metricool_camoufox.mjs").resolve()
        cmd = [
            "node",
            str(camoufox_script),
            "--email", email,
            "--password", password,
            "--profile-dir", str(profile_path),
        ]
        if client_id:
            cmd.extend(["--client-id", client_id])
        if refresh_token:
            cmd.extend(["--refresh-token", refresh_token])
        if headless:
            cmd.append("--headless")

        logger.info(f"Running Camoufox login script: {' '.join(cmd[:4])} ...")
        proc = subprocess.run(cmd, capture_output=False, text=True)
        
        # Load exported session info
        session_info_file = profile_path / "session_info.json"
        if session_info_file.exists():
            try:
                info = json.loads(session_info_file.read_text(encoding="utf-8"))
                return {
                    "email": email,
                    "profile_dir": str(profile_path),
                    "status": info.get("status", "logged_in"),
                    "logged_in_at": info.get("saved_at", datetime.now(timezone.utc).isoformat()),
                    "cookies_count": info.get("cookies_count", 0),
                    "dashboard_url": info.get("dashboard_url", "https://app.metricool.com/"),
                }
            except Exception:
                pass

        return {
            "email": email,
            "profile_dir": str(profile_path),
            "status": "completed" if proc.returncode == 0 else "failed",
            "logged_in_at": datetime.now(timezone.utc).isoformat(),
            "cookies_count": len(json.loads((profile_path / "cookies.json").read_text(encoding="utf-8"))) if (profile_path / "cookies.json").exists() else 0,
            "dashboard_url": "https://app.metricool.com/evolution/brandSummary",
        }

    from playwright.sync_api import sync_playwright

    result = {
        "email": email,
        "profile_dir": str(profile_path),
        "status": "pending",
        "logged_in_at": datetime.now(timezone.utc).isoformat(),
        "cookies_count": 0,
        "dashboard_url": None,
    }

    with sync_playwright() as p:
        logger.info(f"Launching integrated browser (headless={headless})...")
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_path),
            channel="chrome",
            headless=headless,
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()

        try:
            logger.info("Navigating to https://app.metricool.com/login...")
            page.goto("https://app.metricool.com/login", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            email_input = page.locator("input.v-field__input[name='email']")
            pass_input = page.locator("input.v-field__input[name='password']")
            submit_btn = page.locator("button:has-text('Access')")

            if email_input.is_visible() and pass_input.is_visible():
                logger.info(f"Entering credentials for: {email}")
                email_input.fill(email)
                page.wait_for_timeout(300)
                pass_input.fill(password)
                page.wait_for_timeout(400)

                logger.info("Submitting login form ('Access')...")
                submit_btn.click()
                page.wait_for_timeout(4000)

            # Check if 2FA / OTP verification is requested
            otp_box = page.locator("input[name='otp'], input.v-otp-input__field")
            if otp_box.count() > 0 or "login" in page.url:
                logger.info("Email verification screen detected.")
                if refresh_token and client_id:
                    otp_code = poll_metricool_login_otp(client_id, refresh_token, max_wait_seconds=60)
                    if otp_code:
                        logger.info(f"Entering 6-digit OTP code: {otp_code}")
                        if otp_box.count() > 0:
                            otp_box.first.click()
                            page.keyboard.type(otp_code, delay=150)
                            page.wait_for_timeout(1000)

                            confirm_btn = page.locator("button:has-text('Confirm code'), button[type='submit']")
                            if confirm_btn.count() > 0 and confirm_btn.first.is_visible():
                                confirm_btn.first.click()
                                page.wait_for_timeout(5000)
                else:
                    logger.warning("No OAuth credentials provided for OTP auto-fill. Please enter code manually in browser window.")
                    page.wait_for_timeout(15000)

            # Wait for dashboard navigation
            page.wait_for_timeout(4000)
            current_url = page.url
            current_title = page.title()
            logger.info(f"Final Page Title: '{current_title}' | URL: {current_url}")

            # Export session cookies
            cookies = context.cookies()
            cookies_file = profile_path / "cookies.json"
            cookies_file.write_text(json.dumps(cookies, indent=2), encoding="utf-8")
            result["cookies_count"] = len(cookies)
            result["dashboard_url"] = current_url

            if "login" not in current_url:
                result["status"] = "logged_in"
                logger.info(f"SUCCESS: Logged in and saved persistent profile ({len(cookies)} cookies)!")
            else:
                result["status"] = "partial"
                logger.info(f"Session cookies saved ({len(cookies)} cookies). Profile is stored on disk.")

            # Save session info
            session_info = {
                "email": email,
                "status": result["status"],
                "last_active": datetime.now(timezone.utc).isoformat(),
                "cookies_count": len(cookies),
                "dashboard_url": current_url,
                "profile_path": str(profile_path),
            }
            (profile_path / "session_info.json").write_text(json.dumps(session_info, indent=2), encoding="utf-8")

            # Mirror to root 'profiles metricool'
            try:
                root_profile_path.mkdir(parents=True, exist_ok=True)
                (root_profile_path / "cookies.json").write_text(json.dumps(cookies, indent=2), encoding="utf-8")
                (root_profile_path / "session_info.json").write_text(json.dumps(session_info, indent=2), encoding="utf-8")
            except Exception as e:
                logger.debug(f"Mirror write note: {e}")

        finally:
            context.close()

    return result


def open_profile(email: str, headless: bool = False, engine: str = "camoufox"):
    """Launches an existing saved profile directly into the logged-in dashboard."""
    stem = sanitize_profile_name(email)
    profile_path = OUTPUT_PROFILES_DIR / stem

    if not profile_path.exists():
        raise FileNotFoundError(f"Profile directory not found: {profile_path}")

    logger.info(f"Launching authenticated profile ({engine}) for: {email}")

    if engine == "camoufox":
        camoufox_script = Path("tools/metricool_camoufox.mjs").resolve()
        cmd = [
            "node",
            str(camoufox_script),
            "--email", email,
            "--profile-dir", str(profile_path),
            "--open",
        ]
        if headless:
            cmd.append("--headless")
        subprocess.run(cmd)
        return

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_path),
            channel="chrome",
            headless=headless,
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()
        page.goto("https://app.metricool.com/", wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        logger.info(f"Opened: {page.url} ({page.title()})")
        logger.info("Browser session active. Close the window when finished.")
        page.wait_for_timeout(30000)
        context.close()


def list_saved_profiles() -> List[Dict[str, Any]]:
    """Lists all saved profiles and their status."""
    profiles = []
    if OUTPUT_PROFILES_DIR.exists():
        for d in OUTPUT_PROFILES_DIR.iterdir():
            if d.is_dir():
                info_file = d / "session_info.json"
                if info_file.exists():
                    try:
                        info = json.loads(info_file.read_text(encoding="utf-8"))
                        profiles.append(info)
                    except Exception:
                        pass
                else:
                    profiles.append({"name": d.name, "path": str(d)})
    return profiles


def main():
    parser = argparse.ArgumentParser(description="Metricool Persistent Profile Manager")
    parser.add_argument("--account", type=str, default=None, help="Account token string: email|x|refresh_token|client_id")
    parser.add_argument("--email", type=str, default=None, help="Email address (uses saved password from registered accounts)")
    parser.add_argument("--password", type=str, default=None, help="Account password")
    parser.add_argument("--engine", choices=["camoufox", "chrome"], default="camoufox", help="Browser engine (default: camoufox)")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--open", type=str, default=None, help="Open existing saved profile by email")
    parser.add_argument("--list", action="store_true", help="List all saved profiles")

    args = parser.parse_args()

    if args.list:
        profiles = list_saved_profiles()
        print(f"\nFound {len(profiles)} saved profiles in '{OUTPUT_PROFILES_DIR}':")
        for p in profiles:
            print(f" - Email: {p.get('email', p.get('name'))} | Status: {p.get('status')} | Cookies: {p.get('cookies_count')} | Last Active: {p.get('last_active')}")
        return

    if args.open:
        open_profile(args.open, headless=args.headless, engine=args.engine)
        return

    # Determine credentials
    email = args.email
    password = args.password
    refresh_token = None
    client_id = None

    if args.account:
        parts = args.account.strip().split("|")
        email = parts[0]
        if len(parts) >= 4:
            refresh_token = parts[2]
            client_id = parts[3]
    elif not email:
        known = load_known_account()
        if known:
            email = known.get("email")
            password = known.get("password")
            logger.info(f"Using known registered account: {email}")

    if not password and email:
        known = load_known_account(email)
        if known:
            password = known.get("password")

    if not email or not password:
        parser.error("Must provide --email and --password, or --account token string, or have a saved account in output/metricool_registered_accounts.json")

    res = login_and_save_profile(
        email=email,
        password=password,
        refresh_token=refresh_token,
        client_id=client_id,
        headless=args.headless,
        engine=args.engine,
    )

    print("\n" + "=" * 60)
    print("METRICOOL PROFILE LOGIN RESULT:")
    print("=" * 60)
    print(f"Email:        {res['email']}")
    print(f"Status:       {res['status']}")
    print(f"Cookies:      {res['cookies_count']}")
    print(f"Saved Path:   {res['profile_dir']}")
    print(f"Dashboard:    {res['dashboard_url']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
