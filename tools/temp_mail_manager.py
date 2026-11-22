#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/temp_mail_manager.py
==========================
Multi-Provider Free Temporary Mailbox Manager with persistent token/session storage.

Supported Zero-Cost Free Services (No API Key Required):
1. 'tempmail-plus' (TempMail.plus):
   - Fast, open REST API with 7 rotated domains (@mailto.plus, @fexpost.com, @fexbox.org, @mailbox.in.ua, @rover.info, @chitthi.in).
   - Supports PIN / token protection, persistent mailbox inspection anytime.
2. 'guerrilla' (Guerrilla Mail API):
   - 15+ year running free service with persistent sid_token sessions.
   - Domains: @sharklasers.com, @guerrillamail.info, @grr.la, @guerrillamail.biz, @guerrillamail.com.
3. 'temp-mail.io' (Temp-Mail.org open engine):
   - Dynamic domain pool (@lnovic.com, @gmeenramy.com, @olipii.com, @ooynib.com, @tanpony.com).
   - Permanent token-based mailbox querying.
4. 'mail.tm' (Mail.tm REST API):
   - Permanent JWT bearer token authentication.

Optional Paid / Key-based Services:
5. 'privatix' (Privatix RapidAPI official temp-mail.org API):
   - Requires --rapidapi-key or RAPIDAPI_KEY env.
"""

import argparse
import hashlib
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
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("temp_mail")

PRIVATIX_RAPIDAPI_BASE = "https://privatix-temp-mail-v1.p.rapidapi.com"
TEMP_MAIL_IO_BASE = "https://api.internal.temp-mail.io/api/v3"
TEMPMAIL_PLUS_BASE = "https://tempmail.plus"
GUERRILLA_MAIL_BASE = "https://api.guerrillamail.com/ajax.php"
MAIL_TM_BASE = "https://api.mail.tm"

OUTPUT_DIR = Path("output")
TOKENS_VAULT_FILE = OUTPUT_DIR / "temp_mail_tokens.json"


def _http_request(
    url: str,
    method: str = "GET",
    payload: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 15,
) -> Any:
    """Helper to perform HTTP JSON API calls."""
    data = json.dumps(payload).encode("utf-8") if payload else None
    req_headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    }
    if headers:
        req_headers.update(headers)

    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def get_rapidapi_key(passed_key: Optional[str] = None) -> Optional[str]:
    """Retrieves RapidAPI key from argument or environment."""
    if passed_key:
        return passed_key.strip()
    return os.getenv("RAPIDAPI_KEY", "").strip() or None


# =============================================================================
# 1. TempMail.plus Provider (100% Free, Zero-Key)
# =============================================================================
TEMPMAIL_PLUS_DOMAINS = [
    "mailto.plus",
    "fexpost.com",
    "fexbox.org",
    "mailbox.in.ua",
    "rover.info",
    "chitthi.in",
]


def create_mailbox_tempmail_plus(custom_username: Optional[str] = None, domain: Optional[str] = None) -> Dict[str, Any]:
    """Creates a temporary mailbox record on TempMail.plus network."""
    chosen_domain = domain if (domain and domain in TEMPMAIL_PLUS_DOMAINS) else "mailto.plus"
    prefix = custom_username or f"user_{secrets.token_hex(4)}"
    email = f"{prefix}@{chosen_domain}"

    alphabet = string.ascii_letters + string.digits + "!@#$%^"
    password = "".join(secrets.choice(alphabet) for _ in range(14)) + "A1!"
    pin = secrets.token_hex(4)

    return {
        "address": email,
        "password": password,
        "token": pin,
        "account_id": pin,
        "domain": chosen_domain,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "service": "tempmail-plus",
    }


def fetch_messages_tempmail_plus(email: str, pin: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieves messages from TempMail.plus API."""
    pin_param = f"&epin={pin}" if pin else ""
    url = f"{TEMPMAIL_PLUS_BASE}/api/mails?email={urllib.parse.quote(email)}&limit=20{pin_param}"
    try:
        data = _http_request(url)
        if not data or not data.get("result"):
            return []
        mail_list = data.get("mail_list", [])
        res = []
        for m in mail_list:
            mail_id = m.get("mail_id")
            # Fetch full detail for body content
            detail_url = f"{TEMPMAIL_PLUS_BASE}/api/mails/{mail_id}?email={urllib.parse.quote(email)}{pin_param}"
            detail = _http_request(detail_url)
            res.append({
                "id": mail_id,
                "from": m.get("from_mail") or m.get("from_name"),
                "subject": m.get("subject"),
                "body_text": detail.get("text", "") or detail.get("html", ""),
                "body_html": detail.get("html", ""),
                "created_at": m.get("time"),
            })
        return res
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise


# =============================================================================
# 2. Guerrilla Mail Provider (100% Free, Zero-Key)
# =============================================================================
GUERRILLA_DOMAINS = [
    "sharklasers.com",
    "guerrillamail.info",
    "grr.la",
    "guerrillamail.biz",
    "guerrillamail.com",
    "guerrillamail.de",
    "guerrillamail.net",
    "guerrillamail.org",
    "pokemail.net",
    "spam4.me",
]


def create_mailbox_guerrilla(custom_username: Optional[str] = None, domain: Optional[str] = None) -> Dict[str, Any]:
    """Creates a temporary mailbox on Guerrilla Mail and returns a persistent sid_token."""
    chosen_domain = domain if (domain and domain in GUERRILLA_DOMAINS) else "sharklasers.com"
    prefix = custom_username or f"user_{secrets.token_hex(4)}"

    # 1. Initialize session to get sid_token
    init_res = _http_request(f"{GUERRILLA_MAIL_BASE}?f=get_email_address")
    sid_token = init_res.get("sid_token")
    if not sid_token:
        raise RuntimeError(f"Guerrilla Mail initialization failed: {init_res}")

    # 2. Set custom username and target domain
    set_url = (
        f"{GUERRILLA_MAIL_BASE}?f=set_email_user&email_user={urllib.parse.quote(prefix)}"
        f"&site={urllib.parse.quote(chosen_domain)}&sid_token={sid_token}&lang=en"
    )
    set_res = _http_request(set_url)
    email = set_res.get("email_addr") or f"{prefix}@{chosen_domain}"

    alphabet = string.ascii_letters + string.digits + "!@#$%^"
    password = "".join(secrets.choice(alphabet) for _ in range(14)) + "A1!"

    return {
        "address": email,
        "password": password,
        "token": sid_token,
        "account_id": sid_token,
        "domain": chosen_domain,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "service": "guerrilla",
    }


def fetch_messages_guerrilla(sid_token: str) -> List[Dict[str, Any]]:
    """Retrieves messages for a Guerrilla Mail session token."""
    check_url = f"{GUERRILLA_MAIL_BASE}?f=check_email&seq=0&sid_token={sid_token}"
    data = _http_request(check_url)
    raw_list = data.get("list", [])
    res = []
    for m in raw_list:
        mail_id = m.get("mail_id")
        subject = m.get("mail_subject", "")
        # Skip standard Guerrilla Mail welcome mail
        if "welcome to guerrilla mail" in subject.lower():
            continue

        # Fetch detail body
        detail_url = f"{GUERRILLA_MAIL_BASE}?f=fetch_email&email_id={mail_id}&sid_token={sid_token}"
        detail = _http_request(detail_url)
        res.append({
            "id": mail_id,
            "from": m.get("mail_from"),
            "subject": subject,
            "body_text": detail.get("mail_body", ""),
            "body_html": detail.get("mail_body", ""),
            "created_at": m.get("mail_date"),
        })
    return res


# =============================================================================
# 3. Temp-Mail.io Provider (100% Free, Zero-Key)
# =============================================================================
def get_temp_mail_io_domains() -> List[str]:
    """Retrieves active domains pool from Temp-Mail.io."""
    try:
        data = _http_request(f"{TEMP_MAIL_IO_BASE}/domains")
        return [d["name"] for d in data.get("domains", [])]
    except Exception:
        return ["gmeenramy.com", "lnovic.com", "olipii.com", "tanpony.com", "ooynib.com"]


def create_mailbox_temp_mail_io(custom_username: Optional[str] = None, domain: Optional[str] = None) -> Dict[str, Any]:
    """Creates a mailbox on Temp-Mail.io network with a saved token."""
    url = f"{TEMP_MAIL_IO_BASE}/email/new"
    payload: Dict[str, Any] = {}
    if custom_username:
        payload["name"] = custom_username
    if domain:
        payload["domain"] = domain
    if not payload:
        payload = {"min_name_length": 10, "max_name_length": 10}

    res = _http_request(url, method="POST", payload=payload)
    email = res.get("email")
    token = res.get("token")

    if not email:
        raise RuntimeError(f"Temp-Mail.io returned invalid response: {res}")

    alphabet = string.ascii_letters + string.digits + "!@#$%^"
    password = "".join(secrets.choice(alphabet) for _ in range(14)) + "A1!"

    return {
        "address": email,
        "password": password,
        "token": token,
        "account_id": token,
        "domain": email.split("@")[-1],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "service": "temp-mail.io",
    }


def fetch_messages_temp_mail_io(email: str) -> List[Dict[str, Any]]:
    """Retrieves messages for an email address from Temp-Mail.io."""
    url = f"{TEMP_MAIL_IO_BASE}/email/{email}/messages"
    data = _http_request(url)
    return data if isinstance(data, list) else []


# =============================================================================
# 4. Privatix RapidAPI Provider (Official Temp-Mail.org)
# =============================================================================
def create_mailbox_privatix(api_key: str, custom_username: Optional[str] = None) -> Dict[str, Any]:
    """Creates a temporary mailbox via official Privatix RapidAPI."""
    url = f"{PRIVATIX_RAPIDAPI_BASE}/request/domains/format/json/"
    headers = {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": "privatix-temp-mail-v1.p.rapidapi.com",
    }
    domains = _http_request(url, headers=headers)
    if not domains or not isinstance(domains, list):
        raise RuntimeError(f"Privatix RapidAPI failed to return domains: {domains}")

    chosen_domain = domains[0]
    if not chosen_domain.startswith("@"):
        chosen_domain = f"@{chosen_domain}"

    prefix = custom_username or f"user_{secrets.token_hex(4)}"
    email = f"{prefix}{chosen_domain}"

    alphabet = string.ascii_letters + string.digits + "!@#$%^"
    password = "".join(secrets.choice(alphabet) for _ in range(14)) + "A1!"

    return {
        "address": email,
        "password": password,
        "token": api_key,
        "account_id": hashlib.md5(email.lower().strip().encode("utf-8")).hexdigest(),
        "domain": chosen_domain.lstrip("@"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "service": "privatix_rapidapi",
    }


def fetch_messages_privatix(email: str, api_key: str) -> List[Dict[str, Any]]:
    """Retrieves messages for an email address from Privatix RapidAPI."""
    md5_hash = hashlib.md5(email.lower().strip().encode("utf-8")).hexdigest()
    url = f"{PRIVATIX_RAPIDAPI_BASE}/request/mail/id/{md5_hash}/format/json/"
    headers = {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": "privatix-temp-mail-v1.p.rapidapi.com",
    }
    try:
        data = _http_request(url, headers=headers)
        if isinstance(data, list):
            res = []
            for m in data:
                res.append({
                    "id": m.get("mail_id"),
                    "from": m.get("mail_from"),
                    "subject": m.get("mail_subject"),
                    "body_text": m.get("mail_text", ""),
                    "body_html": m.get("mail_html", ""),
                    "created_at": m.get("mail_timestamp"),
                })
            return res
        return []
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise


# =============================================================================
# 5. Mail.tm Provider (Permanent JWT Bearer Tokens)
# =============================================================================
def create_mailbox_mail_tm(custom_username: Optional[str] = None) -> Dict[str, Any]:
    """Creates a mailbox on Mail.tm with permanent JWT token."""
    domain = "fldubai.com"
    username = custom_username or f"user_{secrets.token_hex(4)}"
    email_address = f"{username}@{domain}"
    alphabet = string.ascii_letters + string.digits + "!@#$%^"
    password = "".join(secrets.choice(alphabet) for _ in range(14)) + "A1!"

    acc_res = _http_request(f"{MAIL_TM_BASE}/accounts", method="POST", payload={"address": email_address, "password": password})
    token_res = _http_request(f"{MAIL_TM_BASE}/token", method="POST", payload={"address": email_address, "password": password})
    token = token_res.get("token")

    return {
        "address": email_address,
        "password": password,
        "token": token,
        "account_id": acc_res.get("id"),
        "domain": domain,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "service": "mail.tm",
    }


def fetch_messages_mail_tm(token: str) -> List[Dict[str, Any]]:
    """Retrieves messages for Mail.tm JWT token."""
    url = f"{MAIL_TM_BASE}/messages?page=1"
    data = _http_request(url, headers={"Authorization": f"Bearer {token}"})
    if isinstance(data, list):
        return data
    return data.get("hydra:member", []) if isinstance(data, dict) else []


# =============================================================================
# Master Dispatcher & Vault Operations
# =============================================================================
def save_token_to_vault(record: Dict[str, Any]):
    """Appends or updates the token record in the persistent vault file."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    vault = []
    if TOKENS_VAULT_FILE.exists():
        try:
            vault = json.loads(TOKENS_VAULT_FILE.read_text(encoding="utf-8"))
            if not isinstance(vault, list):
                vault = []
        except Exception:
            vault = []

    vault = [v for v in vault if v.get("address") != record.get("address")]
    vault.append(record)

    TOKENS_VAULT_FILE.write_text(json.dumps(vault, indent=2), encoding="utf-8")
    logger.info(f"Saved token for '{record.get('address')}' to {TOKENS_VAULT_FILE}")


def get_mailbox_record(identifier: str) -> Optional[Dict[str, Any]]:
    """Finds mailbox record by email address or token."""
    if TOKENS_VAULT_FILE.exists():
        try:
            vault = json.loads(TOKENS_VAULT_FILE.read_text(encoding="utf-8"))
            for rec in vault:
                if rec.get("address", "").lower() == identifier.lower() or rec.get("token") == identifier:
                    return rec
        except Exception:
            pass
    return None


def get_token_for_address(identifier: str) -> Optional[str]:
    """Finds token for a given email address or returns identifier if already token."""
    rec = get_mailbox_record(identifier)
    return rec.get("token") if rec else (identifier if len(identifier) > 10 else None)


def create_mailbox(
    service: str = "tempmail-plus",
    custom_username: Optional[str] = None,
    domain: Optional[str] = None,
    rapidapi_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Creates a new temporary mailbox with persistent token/credentials.
    Supported services:
    - 'tempmail-plus': 100% Free TempMail.plus REST API.
    - 'guerrilla': 100% Free Guerrilla Mail API (@sharklasers.com, etc.).
    - 'temp-mail.io': 100% Free Temp-Mail.org open engine.
    - 'mail.tm': 100% Free Mail.tm JWT API.
    - 'privatix': Paid Privatix RapidAPI official API.
    """
    service = service.lower().strip()

    if service in ["privatix", "rapidapi"]:
        api_key = get_rapidapi_key(rapidapi_key)
        if not api_key:
            raise ValueError("RapidAPI key is required for Privatix. Pass --rapidapi-key <KEY> or set RAPIDAPI_KEY.")
        record = create_mailbox_privatix(api_key=api_key, custom_username=custom_username)

    elif service in ["tempmail-plus", "tempmail_plus", "plus"]:
        record = create_mailbox_tempmail_plus(custom_username=custom_username, domain=domain)

    elif service in ["guerrilla", "guerrillamail"]:
        record = create_mailbox_guerrilla(custom_username=custom_username, domain=domain)

    elif service in ["mail.tm", "mailtm"]:
        record = create_mailbox_mail_tm(custom_username=custom_username)

    else:
        # Default: temp-mail.io
        record = create_mailbox_temp_mail_io(custom_username=custom_username, domain=domain)

    save_token_to_vault(record)
    return record


def fetch_messages(email_or_token: str) -> List[Dict[str, Any]]:
    """Retrieves messages for a mailbox by inspecting the vault record."""
    rec = get_mailbox_record(email_or_token)
    email = rec.get("address") if rec else email_or_token
    token = rec.get("token") if rec else email_or_token
    service = rec.get("service") if rec else "tempmail-plus"

    if "@" in email:
        domain = email.split("@")[-1].lower()
        if domain in TEMPMAIL_PLUS_DOMAINS:
            service = "tempmail-plus"
        elif domain in GUERRILLA_DOMAINS:
            service = "guerrilla"

    if service == "tempmail-plus":
        return fetch_messages_tempmail_plus(email, pin=token)
    elif service == "guerrilla":
        return fetch_messages_guerrilla(sid_token=token)
    elif service == "privatix_rapidapi":
        return fetch_messages_privatix(email, token)
    elif service == "mail.tm":
        return fetch_messages_mail_tm(token)
    else:
        # temp-mail.io
        return fetch_messages_temp_mail_io(email)


def poll_for_verification(
    email_or_token: str,
    max_wait_seconds: int = 60,
    poll_interval: int = 3,
    search_keyword: str = "",
) -> Tuple[Optional[str], Optional[str]]:
    """
    Polls the mailbox for incoming verification emails.
    Extracts 6-digit OTP code and verification link.
    """
    logger.info(f"Polling inbox for {email_or_token} (timeout: {max_wait_seconds}s)...")
    start = time.time()

    while time.time() - start < max_wait_seconds:
        try:
            msgs = fetch_messages(email_or_token)
            for m in msgs:
                subject = m.get("subject", "")
                from_addr = str(m.get("from", ""))
                body_text = m.get("body_text", "") or m.get("intro", "")
                body_html = m.get("body_html", "") or ""

                full_body = f"{subject}\n{from_addr}\n{body_text}\n{body_html}"

                if search_keyword and search_keyword.lower() not in full_body.lower():
                    continue

                logger.info(f"Incoming email found: '{subject}' from {from_addr}")

                # 1. Verification code (6 digits)
                code_match = re.search(r"\b(\d{6})\b", full_body)
                code = code_match.group(1) if code_match else None

                # 2. Verification link
                link_match = re.search(
                    r"https?://[^\s\"'>]*(?:verify|confirm|activate|register|token)[^\s\"'>]*",
                    full_body,
                    flags=re.IGNORECASE,
                )
                url = html.unescape(link_match.group(0)) if link_match else None

                if code or url:
                    return code, url

        except Exception as e:
            logger.warning(f"Error checking inbox: {e}")

        time.sleep(poll_interval)

    logger.warning("Timeout reached waiting for email.")
    return None, None


def main():
    parser = argparse.ArgumentParser(description="Multi-Provider Free Persistent Temp Mail Manager")
    parser.add_argument("--create", action="store_true", help="Create a new mailbox with persistent token")
    parser.add_argument(
        "--service",
        type=str,
        default="tempmail-plus",
        choices=["tempmail-plus", "guerrilla", "temp-mail.io", "mail.tm", "privatix"],
        help="Temp mail provider (default: tempmail-plus)",
    )
    parser.add_argument("--domain", type=str, default=None, help="Custom domain (e.g. fexpost.com, sharklasers.com)")
    parser.add_argument("--rapidapi-key", type=str, default=None, help="RapidAPI key for Privatix Temp-Mail API")
    parser.add_argument("--name", type=str, default=None, help="Custom prefix for the email address")
    parser.add_argument("--test-all", action="store_true", help="Create and test mailboxes on all 4 free temp mail services")
    parser.add_argument("--list", action="store_true", help="List all saved mailboxes in the vault")
    parser.add_argument("--inbox", type=str, default=None, help="Email address or token to inspect")
    parser.add_argument("--poll", type=str, default=None, help="Email address or token to poll for verification code")
    parser.add_argument("--keyword", type=str, default="", help="Filter keyword for --poll (e.g. 'metricool')")
    parser.add_argument("--wait", type=int, default=60, help="Max wait seconds for --poll")

    args = parser.parse_args()

    if args.test_all:
        services = [
            ("temp-mail.io", "lnovic.com"),
            ("tempmail-plus", "mailto.plus"),
            ("guerrilla", "sharklasers.com"),
            ("mail.tm", "fldubai.com"),
        ]
        print("\n" + "=" * 75)
        print("TESTING & CREATING MAILBOXES ACROSS ALL 4 FREE TEMP MAIL SERVICES")
        print("=" * 75)
        results = []
        for svc, dom in services:
            try:
                rec = create_mailbox(service=svc, domain=dom)
                msgs = fetch_messages(rec["address"])
                status = f"CONNECTED ({len(msgs)} msgs)"
                results.append((rec, status))
                print(f"[+] {svc.upper():15} | Address: {rec['address']:32} | Status: {status}")
            except Exception as e:
                print(f"[-] {svc.upper():15} | Failed: {e}")

        print("\n" + "=" * 75)
        print("HOW TO CHECK EACH INBOX ANYTIME:")
        print("=" * 75)
        for rec, _ in results:
            print(f"- {rec['service']:15}: python tools/temp_mail_manager.py --inbox {rec['address']}")
        print("=" * 75)
        return

    if args.create:
        rec = create_mailbox(
            service=args.service,
            custom_username=args.name,
            domain=args.domain,
            rapidapi_key=args.rapidapi_key,
        )
        print("\n" + "=" * 60)
        print(f"TEMPORARY MAILBOX CREATED [{rec['service'].upper()}]:")
        print("=" * 60)
        print(f"Address:   {rec['address']}")
        print(f"Password:  {rec['password']}")
        print(f"Token:     {rec['token']}")
        print(f"Domain:    {rec['domain']}")
        print(f"Service:   {rec['service']}")
        print(f"Vault:     {TOKENS_VAULT_FILE}")
        print("=" * 60)
        print("\nYou can access this mailbox anytime with:")
        print(f"  python tools/temp_mail_manager.py --inbox {rec['address']}")
        print(f"  python tools/temp_mail_manager.py --poll {rec['address']}")
        return

    if args.list:
        if not TOKENS_VAULT_FILE.exists():
            print("No saved mailboxes found in vault.")
            return
        vault = json.loads(TOKENS_VAULT_FILE.read_text(encoding="utf-8"))
        print("\n" + "=" * 60)
        print(f"SAVED MAILBOX VAULT ({len(vault)} accounts):")
        print("=" * 60)
        for i, acc in enumerate(vault, 1):
            print(f"{i}. {acc.get('address')} | Service: {acc.get('service')} | Token: {str(acc.get('token'))[:20]}...")
        print("=" * 60)
        return

    if args.inbox:
        msgs = fetch_messages(args.inbox)
        print("\n" + "=" * 60)
        print(f"INBOX FOR {args.inbox} ({len(msgs)} messages):")
        print("=" * 60)
        if not msgs:
            print("Inbox is empty.")
        for m in msgs:
            print(f"- From: {m.get('from')} | Date: {m.get('created_at')}")
            print(f"  Subject: {m.get('subject')}")
            print(f"  Snippet: {str(m.get('body_text', ''))[:120]}")
            print("-" * 40)
        return

    if args.poll:
        code, link = poll_for_verification(args.poll, max_wait_seconds=args.wait, search_keyword=args.keyword)
        print("\n" + "=" * 60)
        print("POLL RESULT:")
        print("=" * 60)
        print(f"OTP Code:          {code}")
        print(f"Verification Link: {link}")
        print("=" * 60)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
