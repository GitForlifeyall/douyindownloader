#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/metricool_profile_manager.py
==================================
Manages persistent isolated anti-detect browser profiles for Metricool accounts powered by Camoufox.

Features:
1. Performs automated Metricool registration or login using Camoufox Anti-Detect Browser.
2. Intercepts email verification links or OTP verification codes via Microsoft Graph API or Temp-Mail.io.
3. Automatically completes all 4 onboarding survey dialogs.
4. Saves full persistent browser profile, cookies, and session state into:
   output/profiles metricool/<account_name>/
   (and mirrored at: profiles metricool/<account_name>/)
5. Provides '--open <email>' to launch directly into an existing authenticated session.
6. Provides '--list' to inspect all active profiles.
"""

import argparse
import json
import logging
import os
import re
import shutil
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
            return data[-1]
    except Exception as e:
        logger.warning(f"Could not read registered accounts: {e}")
    return None


def run_camoufox(
    action: str = "login",
    email: Optional[str] = None,
    password: Optional[str] = None,
    client_id: Optional[str] = None,
    refresh_token: Optional[str] = None,
    use_temp_mail: bool = False,
    proxy: Optional[str] = None,
    headless: bool = False,
) -> Dict[str, Any]:
    """Runs tools/metricool_camoufox.mjs to execute signup, login, or open."""
    camoufox_script = Path("tools/metricool_camoufox.mjs").resolve()
    stem = sanitize_profile_name(email) if email else "new_account"
    profile_path = OUTPUT_PROFILES_DIR / stem

    cmd = ["node", str(camoufox_script), "--action", action]

    if email:
        cmd.extend(["--email", email])
    if password:
        cmd.extend(["--password", password])
    if client_id:
        cmd.extend(["--client-id", client_id])
    if refresh_token:
        cmd.extend(["--refresh-token", refresh_token])
    if use_temp_mail:
        cmd.append("--temp-mail")
    if proxy:
        cmd.extend(["--proxy", proxy])
    if headless:
        cmd.append("--headless")

    logger.info(f"Running Camoufox ({action}): {' '.join(cmd[:6])} ...")
    proc = subprocess.run(cmd, text=True)

    # If signup generated a fresh email, look up the newest directory or registered account
    if action == "signup" and not email:
        known = load_known_account()
        if known and known.get("email"):
            email = known["email"]
            stem = sanitize_profile_name(email)
            profile_path = OUTPUT_PROFILES_DIR / stem

    session_info_file = profile_path / "session_info.json"
    if session_info_file.exists():
        try:
            info = json.loads(session_info_file.read_text(encoding="utf-8"))
            return {
                "email": info.get("email", email),
                "password": info.get("password", password),
                "profile_dir": str(profile_path),
                "status": info.get("status", "logged_in"),
                "logged_in_at": info.get("saved_at", datetime.now(timezone.utc).isoformat()),
                "cookies_count": info.get("cookies_count", 0),
                "dashboard_url": info.get("dashboard_url", "https://app.metricool.com/"),
            }
        except Exception:
            pass

    return {
        "email": email or "unknown",
        "profile_dir": str(profile_path),
        "status": "completed" if proc.returncode == 0 else "failed",
        "logged_in_at": datetime.now(timezone.utc).isoformat(),
        "cookies_count": len(json.loads((profile_path / "cookies.json").read_text(encoding="utf-8"))) if (profile_path / "cookies.json").exists() else 0,
        "dashboard_url": "https://app.metricool.com/evolution/brandSummary",
    }


def open_profile(email: str, proxy: Optional[str] = None, headless: bool = False):
    """Launches an existing saved profile directly into the logged-in dashboard using Camoufox."""
    stem = sanitize_profile_name(email)
    profile_path = OUTPUT_PROFILES_DIR / stem

    if not profile_path.exists():
        # Check root mirror
        if (ROOT_PROFILES_DIR / stem).exists():
            profile_path = ROOT_PROFILES_DIR / stem
        else:
            raise FileNotFoundError(f"Profile directory not found: {profile_path}")

    logger.info(f"Launching authenticated profile in Camoufox for: {email}")
    camoufox_script = Path("tools/metricool_camoufox.mjs").resolve()
    cmd = [
        "node",
        str(camoufox_script),
        "--action", "open",
        "--email", email,
        "--profile-dir", str(profile_path),
    ]
    if proxy:
        cmd.extend(["--proxy", proxy])
    if headless:
        cmd.append("--headless")
    subprocess.run(cmd)


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
                    profiles.append({"email": d.name, "name": d.name, "profile_path": str(d), "status": "unknown"})
    return profiles


def main():
    parser = argparse.ArgumentParser(description="Metricool Persistent Profile Manager (Camoufox Anti-Detect)")
    parser.add_argument("--signup", action="store_true", help="Register a new Metricool account via Camoufox")
    parser.add_argument("--login", action="store_true", help="Login to an existing Metricool account via Camoufox")
    parser.add_argument("--account", type=str, default=None, help="Account token string: email|x|refresh_token|client_id")
    parser.add_argument("--temp-mail", action="store_true", help="Use clean temporary email for signup")
    parser.add_argument("--email", type=str, default=None, help="Email address")
    parser.add_argument("--password", type=str, default=None, help="Account password")
    parser.add_argument("--proxy", type=str, default=None, help="Residential proxy string (user:pass@host:port)")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--open", type=str, default=None, help="Open existing saved profile by email")
    parser.add_argument("--list", action="store_true", help="List all saved profiles")

    args = parser.parse_args()

    if args.list:
        profiles = list_saved_profiles()
        print(f"\nFound {len(profiles)} saved profiles in '{OUTPUT_PROFILES_DIR}':")
        if not profiles:
            print("  (No profiles saved yet)")
        for p in profiles:
            print(f" - Email: {p.get('email', p.get('name'))} | Status: {p.get('status')} | Cookies: {p.get('cookies_count')} | Saved: {p.get('saved_at') or p.get('last_active')}")
        return

    if args.open:
        open_profile(args.open, proxy=args.proxy, headless=args.headless)
        return

    # Parse account string if provided
    email = args.email
    password = args.password
    refresh_token = None
    client_id = None

    if args.account:
        parts = args.account.strip().split("|")
        email = parts[0]
        if len(parts) >= 2 and parts[1] != "x":
            password = parts[1]
        if len(parts) >= 4:
            refresh_token = parts[2]
            client_id = parts[3]

    action = "signup" if args.signup else ("login" if args.login else ("signup" if args.temp_mail else "login"))

    # If login and missing password, check registry
    if action == "login" and not password and email:
        known = load_known_account(email)
        if known:
            password = known.get("password")

    res = run_camoufox(
        action=action,
        email=email,
        password=password,
        client_id=client_id,
        refresh_token=refresh_token,
        use_temp_mail=args.temp_mail or (action == "signup" and not email),
        proxy=args.proxy,
        headless=args.headless,
    )

    print("\n" + "=" * 60)
    print(f"CAMOUFOX METRICOOL {action.upper()} RESULT:")
    print("=" * 60)
    print(f"Email:        {res.get('email')}")
    print(f"Status:       {res.get('status')}")
    print(f"Cookies:      {res.get('cookies_count')}")
    print(f"Saved Path:   {res.get('profile_dir')}")
    print(f"Dashboard:    {res.get('dashboard_url')}")
    print("=" * 60)


if __name__ == "__main__":
    main()
