#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/metricool_signup_selenium.py
==================================
Automated Metricool account registration & full onboarding completion using Selenium WebDriver.

Features:
- Outlook OAuth2 Graph API inbox reading for instant activation link or 6-digit OTP code.
- Anti-detection Chrome options (disables blink automation flags, stealth user-agent).
- Complete automated signup on https://app.metricool.com/register (bypasses honeypot traps).
- Automated end-to-end Onboarding Dialog traversal:
    * Dialog 1: "What describes you best?" -> Selects "Marketing agency" + "Just me" -> Clicks "Continue".
    * Dialog 2: "How are you going to use Metricool?" -> Selects "Programming and publishing of content" -> Clicks "Continue".
    * Dialog 3: "Connect your social networks" -> Clicks "Finish".
    * Dialog 4: "Wait! Are you sure you want to leave?" -> Clicks "Accept".
    * Dismisses any subsequent tour, welcome, or cookie dialogs.
- Persistent profile creation in 'output/profiles metricool/<account>/' (mirrored to 'profiles metricool/').
- Exports cookies.json, session_info.json, and appends to metricool_registered_accounts.json.
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

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from tools.temp_mail_manager import create_mailbox, get_token_for_address, poll_for_verification as poll_temp_mail_verification
except ImportError:
    from temp_mail_manager import create_mailbox, get_token_for_address, poll_for_verification as poll_temp_mail_verification

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("metricool_selenium")

OUTPUT_DIR = Path("output")
REGISTERED_ACCOUNTS_FILE = OUTPUT_DIR / "metricool_registered_accounts.json"
ROOT_PROFILES_DIR = Path("profiles metricool")
OUTPUT_PROFILES_DIR = OUTPUT_DIR / "profiles metricool"


def parse_account_string(raw: str) -> Dict[str, str]:
    """Parses email|x|refresh_token|client_id."""
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
    """Generates a secure password satisfying all complexity requirements."""
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
    """Polls Outlook inbox for Metricool verification emails. Returns (code, url)."""
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

                    # 1. 6-digit OTP code
                    code_match = re.search(r"\b(\d{6})\b", full_text)
                    code = code_match.group(1) if code_match else None

                    # 2. Confirmation / activation link
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


def setup_selenium_driver(profile_path: Optional[Path] = None, headless: bool = False) -> webdriver.Chrome:
    """Configures a stealth Chrome Selenium driver with optional persistent profile."""
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1280,900")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-infobars")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    )
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    if profile_path:
        profile_path.mkdir(parents=True, exist_ok=True)
        options.add_argument(f"--user-data-dir={profile_path.resolve()}")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver


def click_element_safely(driver: webdriver.Chrome, element, delay: float = 0.5):
    """Clicks an element using normal click with JavaScript fallback."""
    try:
        element.click()
    except Exception:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();", element)
    time.sleep(delay)


def click_by_text(driver: webdriver.Chrome, text: str, delay: float = 0.5) -> bool:
    """Finds a visible element containing text and clicks it via JavaScript."""
    try:
        res = driver.execute_script("""
            const targetText = arguments[0].toLowerCase();
            const elements = Array.from(document.querySelectorAll('button, .v-card, .v-selection-control, div, span, p, label'));
            // Find most specific element with the target text
            const matches = elements.filter(el => {
                if (!el.innerText) return false;
                const txt = el.innerText.trim().toLowerCase();
                const visible = el.offsetParent !== null || window.getComputedStyle(el).display !== 'none';
                return visible && txt.includes(targetText);
            });
            matches.sort((a, b) => a.innerText.length - b.innerText.length);
            if (matches.length > 0) {
                matches[0].scrollIntoView({block: 'center'});
                matches[0].click();
                return true;
            }
            return false;
        """, text)
        if res:
            time.sleep(delay)
            return True
    except Exception as e:
        logger.warning(f"click_by_text('{text}') error: {e}")
    return False


def handle_metricool_onboarding(driver: webdriver.Chrome, max_wait_seconds: int = 40):
    """
    Automates dismissing and completing all Metricool onboarding modals after account activation:
    1. Dialog 1: 'What describes you best?' -> Selects 'Marketing agency' + 'Just me' -> 'Continue'.
    2. Dialog 2: 'How are you going to use Metricool?' -> Selects 'Programming and publishing of content' -> 'Continue'.
    3. Dialog 3: 'Connect your social networks' -> Clicks 'Finish'.
    4. Dialog 4: 'Wait! Are you sure you want to leave?' -> Clicks 'Accept'.
    5. Clean up any remaining tour/welcome popups.
    """
    logger.info("Checking for Metricool onboarding survey dialogs...")
    start_time = time.time()
    wait = WebDriverWait(driver, 10)

    # Allow page to stabilize
    time.sleep(3)

    while time.time() - start_time < max_wait_seconds:
        page_source = driver.page_source

        # =========================================================================
        # DIALOG 1: "What describes you best?"
        # =========================================================================
        if "What describes you best?" in page_source:
            logger.info("[Onboarding] Dialog 1 detected: 'What describes you best?'")

            # 1. Select Role ("Marketing agency" or "Content creator")
            for role in ["Marketing agency", "Content creator, personal brand or influencer"]:
                if click_by_text(driver, role, delay=0.4):
                    logger.info(f"[Onboarding] Selected role: '{role}'")
                    break

            # 2. Select Team size ("Just me" or "I will work with more colleagues")
            for team in ["Just me", "I will work with more colleagues"]:
                if click_by_text(driver, team, delay=0.4):
                    logger.info(f"[Onboarding] Selected team: '{team}'")
                    break

            # 3. Click "Continue" button
            logger.info("[Onboarding] Clicking Continue on Dialog 1...")
            click_by_text(driver, "Continue", delay=3.0)
            continue

        # =========================================================================
        # DIALOG 2: "How are you going to use Metricool?"
        # =========================================================================
        if "How are you going to use Metricool?" in page_source:
            logger.info("[Onboarding] Dialog 2 detected: 'How are you going to use Metricool?'")

            for usage in ["Programming and publishing of content", "Analysis and reports"]:
                if click_by_text(driver, usage, delay=0.4):
                    logger.info(f"[Onboarding] Selected usage: '{usage}'")
                    break

            logger.info("[Onboarding] Clicking Continue on Dialog 2...")
            click_by_text(driver, "Continue", delay=3.0)
            continue

        # =========================================================================
        # DIALOG 3: "Connect your social networks"
        # =========================================================================
        if "Connect your social networks" in page_source:
            logger.info("[Onboarding] Dialog 3 detected: 'Connect your social networks'")
            logger.info("[Onboarding] Clicking Finish on Dialog 3...")
            click_by_text(driver, "Finish", delay=2.5)
            continue

        # =========================================================================
        # DIALOG 4: Confirmation "Wait! Are you sure you want to leave?"
        # =========================================================================
        if "Wait! Are you sure you want to leave?" in page_source or "Cancel\nAccept" in page_source:
            logger.info("[Onboarding] Dialog 4 confirmation prompt detected...")
            logger.info("[Onboarding] Clicking Accept to complete onboarding...")
            click_by_text(driver, "Accept", delay=3.0)
            continue

        # =========================================================================
        # Any Tour / Welcome / Cookie Modals
        # =========================================================================
        tour_buttons = ["Skip tour", "Skip", "Got it", "Understood", "Close"]
        tour_dismissed = False
        for text in tour_buttons:
            try:
                btns = driver.find_elements(By.XPATH, f"//button[contains(., '{text}')]")
                for b in btns:
                    if b.is_displayed():
                        logger.info(f"[Onboarding] Dismissing modal with button: '{text}'")
                        click_element_safely(driver, b, delay=1.0)
                        tour_dismissed = True
                        break
            except Exception:
                pass

        if tour_dismissed:
            continue

        # Check if overlays have cleared
        overlays = driver.find_elements(By.CSS_SELECTOR, ".v-overlay--active .v-dialog")
        visible_overlays = [o for o in overlays if o.is_displayed()]
        if not visible_overlays:
            logger.info("[Onboarding] All onboarding dialogs completed and dismissed cleanly!")
            break

        time.sleep(1.5)


def register_metricool_account_selenium(
    account_str: Optional[str] = None,
    use_temp_mail: bool = False,
    temp_mail_address: Optional[str] = None,
    temp_service: str = "temp-mail.io",
    password: Optional[str] = None,
    headless: bool = False,
    timeout: int = 30,
) -> Dict[str, Any]:
    """
    Main Selenium signup automation for Metricool:
    Supports both Outlook OAuth2 accounts and Multi-Provider persistent Temp Mail accounts.
    """
    is_temp = use_temp_mail or (not account_str)
    temp_token = None

    if is_temp:
        # Temp Mail Mode
        if temp_mail_address:
            temp_token = get_token_for_address(temp_mail_address)
            email = temp_mail_address
            chosen_password = password or generate_secure_password()
            provider = "temp_mail"
        else:
            mb = create_mailbox(service=temp_service)
            email = mb["address"]
            chosen_password = password or mb["password"]
            temp_token = mb["token"]
            provider = mb.get("service", temp_service)

        logger.info(f"[Selenium] Using Persistent Temp Mail [{provider}]: {email} (Token: {str(temp_token)[:20]}...)")
    else:
        # Outlook OAuth2 Mode
        acc_info = parse_account_string(account_str)
        email = acc_info["email"]
        refresh_token = acc_info["refresh_token"]
        client_id = acc_info["client_id"]
        chosen_password = password or generate_secure_password()
        provider = "outlook_oauth2"

        # Verify MS Graph connectivity
        try:
            get_ms_access_token(client_id, refresh_token)
            logger.info("[Selenium] Microsoft Graph OAuth2 token exchange verified.")
        except Exception as e:
            raise RuntimeError(f"Failed to authenticate with Microsoft OAuth2: {e}")

    sanitized_email = email.split("@")[0]

    logger.info("=" * 60)
    logger.info(f"[Selenium] Starting Metricool Registration for: {email}")
    logger.info(f"[Selenium] Provider: {provider}")
    logger.info(f"[Selenium] Secure Password: {chosen_password}")
    logger.info("=" * 60)

    # Set up profile directory
    profile_dir = OUTPUT_PROFILES_DIR / sanitized_email
    profile_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "email": email,
        "password": chosen_password,
        "provider": provider,
        "registered_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
        "verification_type": None,
        "verification_data": None,
        "profile_dir": str(profile_dir),
    }
    if temp_token:
        result["temp_mail_token"] = temp_token

    driver = setup_selenium_driver(profile_path=profile_dir, headless=headless)
    wait = WebDriverWait(driver, timeout)

    try:
        logger.info("[Selenium] Navigating to https://app.metricool.com/register...")
        driver.get("https://app.metricool.com/register")
        time.sleep(3)

        # 2. Fill credentials avoiding honeypots
        logger.info("[Selenium] Locating registration input fields...")
        email_input = wait.until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, "input.v-field__input[name='email']"))
        )
        pass_input = wait.until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, "input.v-field__input[name='password']"))
        )

        email_input.clear()
        email_input.send_keys(email)
        time.sleep(0.3)

        pass_input.clear()
        pass_input.send_keys(chosen_password)
        time.sleep(0.3)

        # 3. Check legal consent checkboxes
        checkboxes = driver.find_elements(By.CSS_SELECTOR, "input[type='checkbox']")
        logger.info(f"[Selenium] Checking {len(checkboxes)} consent checkboxes...")
        for cb in checkboxes:
            try:
                if not cb.is_selected():
                    click_element_safely(driver, cb, delay=0.2)
            except Exception:
                pass

        # 4. Click Submit Button
        submit_btn = driver.find_element(By.XPATH, "//button[contains(., 'Start for free')]")
        logger.info("[Selenium] Submitting registration form ('Start for free')...")
        click_element_safely(driver, submit_btn, delay=4.0)

        logger.info(f"[Selenium] Current page URL: {driver.current_url}")

        # 5. Poll inbox for verification (Temp Mail or Outlook)
        if is_temp:
            code, link = poll_temp_mail_verification(email, max_wait_seconds=60, search_keyword="metricool")
        else:
            code, link = poll_metricool_verification(client_id, refresh_token, max_wait_seconds=60)

        if code:
            logger.info(f"[Selenium] Retrieved 6-digit verification code: {code}")
            result["verification_type"] = "code"
            result["verification_data"] = code

            # Enter OTP code into Metricool
            otp_inputs = driver.find_elements(By.CSS_SELECTOR, "input[name='otp'], .v-otp-input input, input.v-field__input")
            if len(otp_inputs) >= 6:
                for idx, digit in enumerate(code[:6]):
                    otp_inputs[idx].send_keys(digit)
                    time.sleep(0.1)
            elif len(otp_inputs) == 1:
                otp_inputs[0].send_keys(code)

            time.sleep(1)
            try:
                confirm_btn = driver.find_element(By.XPATH, "//button[contains(., 'Confirm code') or contains(., 'Verify')]")
                click_element_safely(driver, confirm_btn, delay=4.0)
            except Exception:
                pass

        elif link:
            logger.info(f"[Selenium] Retrieved verification link: {link}")
            result["verification_type"] = "link"
            result["verification_data"] = link
            logger.info("[Selenium] Navigating to verification link...")
            driver.get(link)
            time.sleep(5)

        # 6. Complete all Onboarding Dialogs
        handle_metricool_onboarding(driver)

        # 7. Final URL & status
        final_url = driver.current_url
        logger.info(f"[Selenium] Final Dashboard URL: {final_url}")
        result["dashboard_url"] = final_url
        result["status"] = "logged_in" if "brandSummary" in final_url or "app.metricool.com" in final_url else "partial"

        # 8. Export Cookies & Session Metadata
        cookies = driver.get_cookies()
        cookies_path = profile_dir / "cookies.json"
        cookies_path.write_text(json.dumps(cookies, indent=2), encoding="utf-8")
        logger.info(f"[Selenium] Saved {len(cookies)} cookies to: {cookies_path}")

        session_info = {
            "email": email,
            "status": result["status"],
            "dashboard_url": final_url,
            "cookies_count": len(cookies),
            "profile_path": str(profile_dir.resolve()),
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "engine": "selenium_chrome",
        }
        (profile_dir / "session_info.json").write_text(json.dumps(session_info, indent=2), encoding="utf-8")

        # Mirror to root 'profiles metricool'
        root_mirror = ROOT_PROFILES_DIR / sanitized_email
        root_mirror.mkdir(parents=True, exist_ok=True)
        try:
            (root_mirror / "cookies.json").write_text(json.dumps(cookies, indent=2), encoding="utf-8")
            (root_mirror / "session_info.json").write_text(json.dumps(session_info, indent=2), encoding="utf-8")
        except Exception:
            pass

    finally:
        driver.quit()

    # Save to registered accounts list
    save_registered_account(result)
    return result


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

    existing = [a for a in existing if a.get("email") != account_record.get("email")]
    existing.append(account_record)

    REGISTERED_ACCOUNTS_FILE.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    logger.info(f"[Selenium] Account credentials saved to: {REGISTERED_ACCOUNTS_FILE}")


def main():
    parser = argparse.ArgumentParser(description="Metricool Account Registration & Onboarding via Selenium")
    parser.add_argument(
        "--account",
        type=str,
        default=None,
        help="Account string in format: email|x|refresh_token|client_id (Outlook OAuth2)",
    )
    parser.add_argument(
        "--temp-mail",
        nargs="?",
        const="NEW",
        default=None,
        help="Use persistent temp mail (creates new mailbox if omitted or pass existing email)",
    )
    parser.add_argument(
        "--temp-service",
        type=str,
        default="tempmail-plus",
        choices=["tempmail-plus", "guerrilla", "temp-mail.io", "mail.tm"],
        help="Free temp mail provider to use (default: tempmail-plus)",
    )
    parser.add_argument("--password", type=str, default=None, help="Custom password (auto-generated if omitted)")
    parser.add_argument("--headless", action="store_true", help="Run browser headless")

    args = parser.parse_args()

    use_temp = bool(args.temp_mail) or (not args.account)
    temp_addr = args.temp_mail if (args.temp_mail and args.temp_mail != "NEW") else None

    res = register_metricool_account_selenium(
        account_str=args.account,
        use_temp_mail=use_temp,
        temp_mail_address=temp_addr,
        temp_service=args.temp_service,
        password=args.password,
        headless=args.headless,
    )
    print("\n" + "=" * 60)
    print("SELENIUM METRICOOL REGISTRATION & ONBOARDING RESULT:")
    print("=" * 60)
    print(f"Email:        {res['email']}")
    print(f"Password:     {res['password']}")
    print(f"Provider:     {res.get('provider')}")
    print(f"Status:       {res['status']}")
    print(f"Dashboard:    {res.get('dashboard_url')}")
    print(f"Profile:      {res.get('profile_dir')}")
    print(f"Verification: {res.get('verification_type')} -> {res.get('verification_data')}")
    if res.get("temp_mail_token"):
        print(f"Temp Token:   {res['temp_mail_token'][:25]}... (saved in output/temp_mail_tokens.json)")
    print("=" * 60)


if __name__ == "__main__":
    main()
