#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/metricool_account_creator.py
==================================
Automated Metricool account registration with Microsoft Outlook OAuth2 inbox reading.

Accepts account tokens in format:
  email|password_or_x|refresh_token|client_id

Pipeline:
1. Exchanges Microsoft OAuth2 refresh_token for Graph API access token (Mail.Read).
2. Launches Google Chrome via Playwright.
3. Navigates to Metricool registration page (https://app.metricool.com/register).
4. Fills email and generated secure password.
5. Accepts terms and submits registration.
6. Polls Outlook inbox via Graph API for Metricool's verification code or confirmation link.
7. Completes verification in Chrome and saves account record to disk.
"""

import argparse
import html
import json
import logging
import os
import re
import secrets
import string
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("metricool_creator")

try:
    from tools.supabase_logger import log_to_supabase
except ImportError:
    try:
        from supabase_logger import log_to_supabase
    except ImportError:
        def log_to_supabase(d): return {}

OUTPUT_DIR = Path("output")
REGISTERED_ACCOUNTS_FILE = OUTPUT_DIR / "metricool_registered_accounts.json"


def parse_account_string(raw: str) -> Dict[str, str]:
    """
    Parses string format:
    email|x|refresh_token|client_id
    """
    parts = raw.strip().split("|")
    if len(parts) < 4:
        raise ValueError(
            f"Invalid account format. Expected 4 pipe-delimited fields (email|x|refresh_token|client_id), got {len(parts)} parts."
        )
    return {
        "email": parts[0].strip(),
        "password_placeholder": parts[1].strip(),
        "refresh_token": parts[2].strip(),
        "client_id": parts[3].strip(),
    }


def generate_secure_password(length: int = 16) -> str:
    """Generates a high-entropy compliant password with letters, digits, and symbols."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(c.islower() for c in pwd)
            and any(c.isupper() for c in pwd)
            and any(c.isdigit() for c in pwd)
            and any(c in "!@#$%^&*" for c in pwd)
        ):
            return pwd


def get_ms_access_token(client_id: str, refresh_token: str) -> str:
    """Exchanges Microsoft consumer refresh token for a Graph API access token."""
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
        token = data.get("access_token")
        if not token:
            raise RuntimeError(f"Microsoft OAuth response missing access_token: {data}")
        return token


def fetch_recent_emails(access_token: str, top: int = 10) -> list:
    """Fetches recent emails from Outlook via Microsoft Graph API."""
    url = f"https://graph.microsoft.com/v1.0/me/messages?$top={top}&$select=subject,sender,bodyPreview,body,receivedDateTime&$orderby=receivedDateTime%20desc"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return data.get("value", [])


def poll_metricool_verification(
    client_id: str,
    refresh_token: str,
    max_wait_seconds: int = 90,
    poll_interval: int = 5,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Polls Outlook inbox for Metricool verification emails.
    Returns (verification_code, verification_url).
    """
    logger.info(f"Polling Outlook inbox for Metricool verification (timeout: {max_wait_seconds}s)...")
    start_time = time.time()

    while time.time() - start_time < max_wait_seconds:
        try:
            token = get_ms_access_token(client_id, refresh_token)
            messages = fetch_recent_emails(token, top=10)

            for m in messages:
                subject = m.get("subject", "")
                sender = m.get("sender", {}).get("emailAddress", {}).get("address", "")
                preview = m.get("bodyPreview", "")
                content = m.get("body", {}).get("content", "")
                full_text = f"{subject}\n{preview}\n{content}"

                if "metricool" in full_text.lower() or "metricool" in sender.lower():
                    logger.info(f"Found Metricool email: '{subject}' from {sender}")

                    # 1. Search for 6-digit verification code
                    code_match = re.search(r"\b(\d{6})\b", full_text)
                    code = code_match.group(1) if code_match else None

                    # 2. Search for confirmation / verification link
                    link_match = re.search(
                        r"https://[^\s\"'>]*(?:verify|confirm|activate|register|token)[^\s\"'>]*",
                        content or preview,
                        flags=re.IGNORECASE,
                    )
                    url = html.unescape(link_match.group(0)) if link_match else None

                    if code or url:
                        return code, url
        except Exception as e:
            logger.warning(f"Inbox poll warning: {e}")

        time.sleep(poll_interval)

    logger.warning("Timed out waiting for Metricool verification email.")
    return None, None


def register_metricool_account(
    account_str: str,
    password: Optional[str] = None,
    headless: bool = False,
    timeout: int = 30000,
    proxy: Optional[str] = None,
) -> Dict[str, Any]:
    """Orchestrates Playwright automation to register an account on Metricool."""
    from playwright.sync_api import sync_playwright

    acc_info = parse_account_string(account_str)
    email = acc_info["email"]
    refresh_token = acc_info["refresh_token"]
    client_id = acc_info["client_id"]
    chosen_password = password or generate_secure_password()

    logger.info(f"Starting Metricool Registration for: {email}")
    logger.info(f"Generated Password: {chosen_password}")

    # Verify MS Graph connectivity before launching browser
    try:
        test_token = get_ms_access_token(client_id, refresh_token)
        logger.info("Microsoft Graph OAuth2 token exchange verified successfully.")
    except Exception as e:
        raise RuntimeError(f"Failed to authenticate with Microsoft OAuth2: {e}")

    result = {
        "email": email,
        "password": chosen_password,
        "registered_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
        "verification_type": None,
        "verification_data": None,
    }

    with sync_playwright() as p:
        logger.info(f"Launching Google Chrome (headless={headless})...")
        launch_kwargs = {"channel": "chrome", "headless": headless}
        if proxy:
            clean = proxy.strip().replace("http://", "").replace("https://", "")
            if "@" in clean:
                auth, host_port = clean.split("@")
                user, pwd = auth.split(":")
                launch_kwargs["proxy"] = {"server": f"http://{host_port}", "username": user, "password": pwd}
            else:
                launch_kwargs["proxy"] = {"server": f"http://{clean}"}
        browser = p.chromium.launch(**launch_kwargs)
        tz_id = "Asia/Kolkata" if (proxy and any(x in proxy.lower() for x in ["-cc-in", "india", "ahmedabad", "mumbai"])) else "America/Chicago"
        locale_id = "en-IN" if tz_id == "Asia/Kolkata" else "en-US"
        context = browser.new_context(viewport={"width": 1280, "height": 800}, timezone_id=tz_id, locale=locale_id)
        page = context.new_page()

        try:
            logger.info("Navigating to https://app.metricool.com/register...")
            page.goto("https://app.metricool.com/register", wait_until="domcontentloaded", timeout=timeout)
            page.wait_for_timeout(2500)

            # Target the real visible form inputs (bypassing honeypot inputs)
            email_input = page.locator("input.v-field__input[name='email']")
            pass_input = page.locator("input.v-field__input[name='password']")

            email_input.wait_for(state="visible", timeout=10000)
            pass_input.wait_for(state="visible", timeout=10000)

            logger.info("Filling registration credentials...")
            email_input.click()
            email_input.fill(email)
            page.wait_for_timeout(400)

            pass_input.click()
            pass_input.fill(chosen_password)
            page.wait_for_timeout(400)

            # Check legal terms checkboxes by clicking Vuetify selection controls
            cb_controls = page.locator(".v-checkbox .v-selection-control, label:has-text('Legal Terms')")
            cb_count = cb_controls.count()
            logger.info(f"Clicking {cb_count} legal/consent checkbox controls...")
            for i in range(cb_count):
                try:
                    cb_controls.nth(i).click(force=True)
                    page.wait_for_timeout(300)
                except Exception:
                    pass

            # Click Submit Button
            submit_btn = page.locator("button:has-text('Get started for free'), button:has-text('started for free'), button:has-text('Start for free')").first
            logger.info("Submitting registration form ('Get started for free')...")
            try:
                submit_btn.click(force=True)
            except Exception:
                pass
            page.keyboard.press("Enter")

            # Wait for response / navigation
            page.wait_for_timeout(5000)
            current_url = page.url
            logger.info(f"Page URL after submit: {current_url}")

            # Check if there is an on-page verification code input
            code_input = page.locator("input[name*='code'], input[placeholder*='code' i], input[type='number'], input.v-otp-input")
            has_code_input = code_input.count() > 0 and code_input.first.is_visible()

            # Poll Outlook inbox for verification
            code, link = poll_metricool_verification(client_id, refresh_token, max_wait_seconds=60)

            if code:
                logger.info(f"Retrieved 6-digit verification code: {code}")
                result["verification_type"] = "code"
                result["verification_data"] = code

                if has_code_input:
                    logger.info("Entering verification code into Metricool interface...")
                    code_input.first.fill(code)
                    page.wait_for_timeout(1000)
                    confirm_btn = page.locator("button:has-text('Verify'), button:has-text('Confirm'), button:has-text('Continue')")
                    if confirm_btn.count() > 0 and confirm_btn.first.is_visible():
                        confirm_btn.first.click()
                        page.wait_for_timeout(4000)

            elif link:
                logger.info(f"Retrieved verification link: {link}")
                result["verification_type"] = "link"
                result["verification_data"] = link
                logger.info("Navigating to verification link in Chrome...")
                page.goto(link, wait_until="domcontentloaded", timeout=timeout)
                page.wait_for_timeout(4000)

            # Handle Onboarding Dialogs if present
            handle_playwright_onboarding(page)

            # Final status check
            final_url = page.url
            page_title = page.title()
            logger.info(f"Final Page Title: '{page_title}' | URL: {final_url}")

            if "register" not in final_url.lower() or result["verification_data"]:
                result["status"] = "success"
                logger.info("Registration completed successfully!")
            else:
                result["status"] = "needs_manual_check"
                logger.info("Registration submitted, awaiting confirmation.")

            page.wait_for_timeout(3000)

            if not headless:
                logger.info("[Metricool] Browser will remain open for your inspection. Close the browser window when you are done.")
                try:
                    page.wait_for_event("close", timeout=0)
                except Exception:
                    pass

        finally:
            browser.close()

    # Save to disk
    save_registered_account(result)
    return result


def handle_playwright_onboarding(page, max_wait_seconds: int = 30):
    """
    Automates traversal and dismissal of all Metricool onboarding dialogs:
    1. Dialog 1: "What describes you best?" -> 'Marketing agency' + 'Just me' -> 'Continue'.
    2. Dialog 2: "How are you going to use Metricool?" -> 'Programming and publishing of content' -> 'Continue'.
    3. Dialog 3: "Connect your social networks" -> 'Finish'.
    4. Dialog 4: "Wait! Are you sure you want to leave?" -> 'Accept'.
    5. Dismisses any remaining tour/welcome/cookie dialogs.
    """
    logger.info("Checking for Metricool onboarding survey dialogs (Playwright)...")
    start_time = time.time()
    page.wait_for_timeout(3000)

    while time.time() - start_time < max_wait_seconds:
        content = page.content()

        # Dialog 1: "What describes you best?"
        if "What describes you best?" in content:
            logger.info("[Onboarding] Dialog 1 detected: 'What describes you best?'")
            for role in ["Marketing agency", "Content creator, personal brand or influencer"]:
                loc = page.locator(f"text='{role}'").first
                if loc.count() > 0 and loc.is_visible():
                    logger.info(f"[Onboarding] Selecting role: '{role}'")
                    loc.click(force=True)
                    page.wait_for_timeout(400)
                    break

            for team in ["Just me", "I will work with more colleagues"]:
                loc = page.locator(f"text='{team}'").first
                if loc.count() > 0 and loc.is_visible():
                    logger.info(f"[Onboarding] Selecting team: '{team}'")
                    loc.click(force=True)
                    page.wait_for_timeout(400)
                    break

            cont_btn = page.locator("button:has-text('Continue')").first
            if cont_btn.count() > 0 and cont_btn.is_visible():
                logger.info("[Onboarding] Clicking Continue on Dialog 1...")
                cont_btn.click(force=True)
                page.wait_for_timeout(3000)
            continue

        # Dialog 2: "How are you going to use Metricool?"
        if "How are you going to use Metricool?" in content:
            logger.info("[Onboarding] Dialog 2 detected: 'How are you going to use Metricool?'")
            prog = page.locator("text='Programming and publishing of content'").first
            if prog.count() > 0 and prog.is_visible():
                logger.info("[Onboarding] Selecting 'Programming and publishing of content'")
                prog.click(force=True)
                page.wait_for_timeout(400)

            cont2 = page.locator("button:has-text('Continue')").last
            if cont2.count() > 0 and cont2.is_visible():
                logger.info("[Onboarding] Clicking Continue on Dialog 2...")
                cont2.click(force=True)
                page.wait_for_timeout(3000)
            continue

        # Dialog 3: "Connect your social networks"
        if "Connect your social networks" in content:
            logger.info("[Onboarding] Dialog 3 detected: 'Connect your social networks'")
            finish_btn = page.locator("button:has-text('Finish')").last
            if finish_btn.count() > 0 and finish_btn.is_visible():
                logger.info("[Onboarding] Clicking Finish on Dialog 3...")
                finish_btn.click(force=True)
                page.wait_for_timeout(3000)
            continue

        # Dialog 4: Confirmation "Wait! Are you sure you want to leave?"
        if "Wait! Are you sure you want to leave?" in content:
            logger.info("[Onboarding] Dialog 4 detected: confirmation prompt")
            accept_btn = page.locator("button:has-text('Accept')").first
            if accept_btn.count() > 0 and accept_btn.is_visible():
                logger.info("[Onboarding] Clicking Accept on confirmation dialog...")
                accept_btn.click(force=True)
                page.wait_for_timeout(3000)
            continue

        # Check for tour modals
        tour_dismissed = False
        for text in ["Skip tour", "Skip", "Got it", "Understood", "Close"]:
            btn = page.locator(f"button:has-text('{text}')").first
            if btn.count() > 0 and btn.is_visible():
                logger.info(f"[Onboarding] Dismissing modal with '{text}' button")
                btn.click(force=True)
                page.wait_for_timeout(1000)
                tour_dismissed = True
                break

        if tour_dismissed:
            continue

        # Check active overlays
        active_overlays = page.locator(".v-overlay--active .v-dialog")
        if active_overlays.count() == 0:
            logger.info("[Onboarding] All onboarding dialogs dismissed.")
            break

        page.wait_for_timeout(1500)


def save_registered_account(account_record: Dict[str, Any]):
    """Saves the registered account credentials to output file."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    existing = []
    if REGISTERED_ACCOUNTS_FILE.exists():
        try:
            existing = json.loads(REGISTERED_ACCOUNTS_FILE.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []

    # Update or append
    existing = [a for a in existing if a.get("email") != account_record.get("email")]
    existing.append(account_record)

    REGISTERED_ACCOUNTS_FILE.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    logger.info(f"Account credentials saved to: {REGISTERED_ACCOUNTS_FILE}")

    # Synchronize to Supabase
    try:
        log_to_supabase({
            "platform": "Metricool",
            "email": account_record.get("email"),
            "username": account_record.get("username") or account_record.get("email", "").split("@")[0],
            "password": account_record.get("password"),
            "profile_url": "https://app.metricool.com",
            "full_mail_string": account_record.get("full_mail_string") or account_record.get("account_string", ""),
            "two_factor_secret": account_record.get("two_factor_secret", ""),
            "backup_codes": account_record.get("backup_codes", []),
            "proxy": account_record.get("proxy", ""),
            "status": "ACTIVE",
            "details": {
                "registered_at": account_record.get("registered_at"),
                "auth_method": account_record.get("auth_method")
            }
        })
    except Exception as e:
        logger.warning(f"Supabase sync warning: {e}")


def main():
    parser = argparse.ArgumentParser(description="Metricool Account Creator via Outlook OAuth2")
    parser.add_argument(
        "--account",
        type=str,
        default="AshleyKnappd8025h@outlook.com|x|M.C517_BL2.0.U.MsaArtifacts.-ChYkL9kAZZlEWjQp!MMQ!w3OJ7LkbanFnFFHxpoCOiw6b*4rCeLJO2b1uUOVYgiUjsiaSSSL7Dp2fqMih3ZMJVvdPFDYo8TDh0EXfj9nc1y9A25lTuB9znYyUrOQzIREvzVnzkL2UvsRPORauIBNIEVUVSWIeIjEVor8GU7wjNKjBvIzLzkgTSLSrPfRV7SisfaeQRaa4k9xIgJi8ibs0CZM1!Ucu0gtwkR9sK!asfeHuca6Tnxqft6nITsIEP75Um5ucBO!ad5A!HEsI5sZmyDjI6BxgPH326HuOyqyWR20AMJyZ!hcAHjyxcTK5RNSWiZnHNKpEexPuydsol6i9xXyLzdjSGEkVl7tmymmqF*3R4SDiH5u2cnv*edZtid0N7kEfUyvh4Ar89DZOWHpowlj!2*HvIrhPaQTjZzG*XXd|9e5f94bc-e8a4-4e73-b8be-63364c29d753",
        help="Account string in format: email|x|refresh_token|client_id",
    )
    parser.add_argument("--password", type=str, default=None, help="Custom password (auto-generated if omitted)")
    parser.add_argument("--proxy", type=str, default=None, help="Proxy server string")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode (default is visible Chrome window)")

    args = parser.parse_args()
    res = register_metricool_account(args.account, password=args.password, headless=args.headless, proxy=args.proxy)
    print("\n" + "=" * 60)
    print("METRICOOL REGISTRATION RESULT:")
    print("=" * 60)
    print(f"Email:        {res['email']}")
    print(f"Password:     {res['password']}")
    print(f"Status:       {res['status']}")
    print(f"Verification: {res.get('verification_type')} -> {res.get('verification_data')}")
    print(f"Saved to:     {REGISTERED_ACCOUNTS_FILE}")
    print("=" * 60)


if __name__ == "__main__":
    main()
