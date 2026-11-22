#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/supabase_logger.py
========================
Synchronizes registered social accounts to Supabase PostgreSQL table via PostgREST.
Zero third-party dependencies (uses Python standard urllib).
"""

import os
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional
import urllib.request
import urllib.error

logger = logging.getLogger("supabase_logger")
CONFIG_FILE = Path(__file__).parent.parent / "config" / "supabase_config.json"


def get_supabase_config() -> Dict[str, Any]:
    supabase_url = os.environ.get("SUPABASE_URL", "")
    supabase_key = os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    table_name = "social_accounts"
    enabled = True

    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if not supabase_url and data.get("supabase_url"):
                supabase_url = data.get("supabase_url", "").strip()
            if not supabase_key and data.get("supabase_key"):
                supabase_key = data.get("supabase_key", "").strip()
            if data.get("table_name"):
                table_name = data.get("table_name", "").strip()
            if "enabled" in data:
                enabled = bool(data.get("enabled", True))
        except Exception:
            pass

    supabase_url = supabase_url.rstrip("/")
    return {
        "supabase_url": supabase_url,
        "supabase_key": supabase_key,
        "table_name": table_name,
        "enabled": enabled
    }


def set_supabase_config(supabase_url: str, supabase_key: str, table_name: str = "social_accounts", enabled: bool = True) -> bool:
    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps({
            "supabase_url": supabase_url.strip().rstrip("/"),
            "supabase_key": supabase_key.strip(),
            "table_name": table_name.strip(),
            "enabled": enabled
        }, indent=2), encoding="utf-8")
        return True
    except Exception as e:
        logger.error(f"Failed to write Supabase config: {e}")
        return False


def log_to_supabase(account_data: Dict[str, Any]) -> Dict[str, Any]:
    """Upserts account record to Supabase via PostgREST. Fails silently."""
    cfg = get_supabase_config()
    supabase_url = cfg["supabase_url"]
    supabase_key = cfg["supabase_key"]
    table_name = cfg["table_name"]

    if not cfg["enabled"] or not supabase_url or not supabase_key or not supabase_url.startswith("http"):
        return {"skipped": True, "reason": "Supabase not configured or disabled"}

    email = (account_data.get("email") or "").lower().strip()
    if not email:
        return {"skipped": True, "reason": "Email required for Supabase upsert"}

    tf = account_data.get("two_factor") or {}
    tf_secret = account_data.get("two_factor_secret") or account_data.get("totp_secret") or tf.get("secret_key") or ""
    b_codes = account_data.get("backup_codes") or tf.get("backup_codes") or ""
    if isinstance(b_codes, list):
        b_codes = ", ".join(str(c) for c in b_codes)

    # Auto-resolve proxy if missing from caller
    proxy_val = account_data.get("proxy") or account_data.get("proxy_used") or ""
    if not proxy_val and email:
        try:
            idents_file = PROJECT_ROOT / "output" / "identities.json"
            if idents_file.exists():
                idents = json.loads(idents_file.read_text(encoding="utf-8"))
                if isinstance(idents, list):
                    for i in idents:
                        if (i.get("email") or "").lower() == email:
                            proxy_val = i.get("proxy") or ""
                            break
        except Exception:
            pass

    payload = {
        "platform": (account_data.get("platform") or "Metricool").upper(),
        "email": email,
        "username": account_data.get("username", ""),
        "password": account_data.get("password", ""),
        "profile_url": account_data.get("profile_url") or account_data.get("url") or "",
        "full_mail_string": account_data.get("full_mail_string") or account_data.get("account_string") or "",
        "two_factor_secret": tf_secret,
        "backup_codes": b_codes,
        "status": (account_data.get("status") or "ACTIVE").upper(),
        "details": account_data.get("details") or {}
    }

    # Only attach proxy if present to prevent wiping existing proxy on partial updates
    if proxy_val:
        payload["proxy"] = proxy_val

    try:
        req_data = json.dumps(payload).encode("utf-8")
        endpoint = f"{supabase_url}/rest/v1/{table_name}?on_conflict=email"
        req = urllib.request.Request(
            endpoint,
            data=req_data,
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates,return=representation"
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            result = json.loads(body) if body else []
            logger.info(f"[Supabase] Upserted {payload['platform']} account ({email}) to Supabase.")

            # Also ensure mail is saved in separate email_accounts table with existence check
            try:
                log_email_to_supabase({
                    "email": email,
                    "password": payload.get("password", ""),
                    "full_mail_string": payload.get("full_mail_string", ""),
                    "platform": payload.get("platform", "").lower(),
                    "status": payload.get("status", "ACTIVE"),
                    "details": {"proxy": payload.get("proxy", "")}
                })
            except Exception:
                pass

            return {"success": True, "data": result}
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="ignore")
        logger.warning(f"[Supabase HTTP {e.code}] {err_msg}")
        return {"success": False, "status": e.code, "error": err_msg}
    except Exception as e:
        logger.warning(f"[Supabase] Could not sync to Supabase ({e}). Local record preserved.")
        return {"success": False, "error": str(e)}


EMAILS_TABLE = "email_accounts"


def check_email_exists(email: str) -> Dict[str, Any]:
    """
    Checks if an email already exists in the separate email_accounts table in Supabase.
    Returns: {"exists": bool, "record": Optional[Dict], "table_missing": bool, "error": Optional[str]}
    """
    cfg = get_supabase_config()
    supabase_url = cfg["supabase_url"]
    supabase_key = cfg["supabase_key"]

    if not cfg["enabled"] or not supabase_url or not supabase_key or not supabase_url.startswith("http"):
        return {"exists": False, "error": "Supabase not configured or disabled", "table_missing": False}

    clean_email = (email or "").lower().strip()
    if not clean_email:
        return {"exists": False, "error": "Email is empty", "table_missing": False}

    try:
        query_url = f"{supabase_url}/rest/v1/{EMAILS_TABLE}?email=eq.{urllib.parse.quote(clean_email)}&select=id,email,provider,status,used_in_platforms,last_used_platform,last_used_at,created_at"
        req = urllib.request.Request(
            query_url,
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Accept": "application/json"
            },
            method="GET"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            records = json.loads(body) if body else []
            if isinstance(records, list) and len(records) > 0:
                return {"exists": True, "record": records[0], "table_missing": False}
            return {"exists": False, "record": None, "table_missing": False}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        if e.code == 404 and "Could not find the table" in err_body:
            return {"exists": False, "table_missing": True, "error": err_body}
        return {"exists": False, "error": err_body, "table_missing": False}
    except Exception as e:
        return {"exists": False, "error": str(e), "table_missing": False}


def log_email_to_supabase(mail_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Saves an email into the separate email_accounts table in Supabase.
    Checks before appending if it already exists:
    - If exists: merges platform into used_in_platforms, updates credentials & last_used_at.
    - If new: appends a fresh record into email_accounts.
    """
    cfg = get_supabase_config()
    supabase_url = cfg["supabase_url"]
    supabase_key = cfg["supabase_key"]

    if not cfg["enabled"] or not supabase_url or not supabase_key or not supabase_url.startswith("http"):
        return {"skipped": True, "reason": "Supabase not configured or disabled"}

    clean_email = (mail_data.get("email") or "").lower().strip()
    if not clean_email:
        return {"skipped": True, "reason": "Email required"}

    # Extract components from full_mail_string if available
    password = mail_data.get("password") or ""
    refresh_token = mail_data.get("refresh_token") or ""
    client_id = mail_data.get("client_id") or ""
    full_string = mail_data.get("full_mail_string") or mail_data.get("account_string") or ""
    if full_string and "|" in full_string:
        parts = full_string.split("|")
        if len(parts) >= 2 and not password:
            password = parts[1].strip()
        if len(parts) >= 3 and not refresh_token:
            refresh_token = parts[2].strip()
        if len(parts) >= 4 and not client_id:
            client_id = parts[3].strip()

    # Derive provider
    provider = mail_data.get("provider") or ""
    if not provider:
        domain = clean_email.split("@")[-1] if "@" in clean_email else ""
        if any(d in domain for d in ["outlook", "hotmail", "live", "msn"]):
            provider = "outlook"
        elif any(d in domain for d in ["gmail", "google"]):
            provider = "gmail"
        elif "yahoo" in domain:
            provider = "yahoo"
        elif any(d in domain for d in ["lnovic", "temp-mail"]):
            provider = "temp-mail"
        else:
            provider = domain.split(".")[0] if domain else "other"

    platform = (mail_data.get("platform") or mail_data.get("last_used_platform") or "").lower()
    now_iso = datetime.now(timezone.utc).isoformat()

    # 1. Check if email already exists in Supabase
    check = check_email_exists(clean_email)
    if check.get("table_missing"):
        logger.warning(f"[Supabase] Note: table '{EMAILS_TABLE}' not created yet in Supabase. Run tools/supabase_schema.sql.")
        return {"skipped": True, "table_missing": True, "reason": f"Table {EMAILS_TABLE} not created"}

    if check.get("exists") and check.get("record"):
        rec = check["record"]
        logger.info(f"[Supabase] Email ({clean_email}) already exists in Supabase. Merging platform info...")
        existing_platforms = rec.get("used_in_platforms") or []
        if isinstance(existing_platforms, str):
            existing_platforms = [p.strip() for p in existing_platforms.split(",") if p.strip()]
        if platform and platform not in existing_platforms:
            existing_platforms.append(platform)

        patch_payload = {
            "used_in_platforms": existing_platforms,
            "last_used_platform": platform or rec.get("last_used_platform", ""),
            "last_used_at": now_iso,
            "updated_at": now_iso
        }
        if password and not rec.get("password"):
            patch_payload["password"] = password
        if refresh_token and not rec.get("refresh_token"):
            patch_payload["refresh_token"] = refresh_token
        if client_id and not rec.get("client_id"):
            patch_payload["client_id"] = client_id
        if full_string:
            patch_payload["full_mail_string"] = full_string
        if mail_data.get("status"):
            patch_payload["status"] = mail_data["status"]

        try:
            patch_url = f"{supabase_url}/rest/v1/{EMAILS_TABLE}?email=eq.{urllib.parse.quote(clean_email)}"
            patch_req = urllib.request.Request(
                patch_url,
                data=json.dumps(patch_payload).encode("utf-8"),
                headers={
                    "apikey": supabase_key,
                    "Authorization": f"Bearer {supabase_key}",
                    "Content-Type": "application/json",
                    "Prefer": "return=representation"
                },
                method="PATCH"
            )
            with urllib.request.urlopen(patch_req, timeout=10) as resp:
                body = resp.read().decode("utf-8")
                updated = json.loads(body) if body else []
                return {"success": True, "is_new": False, "data": updated[0] if updated else patch_payload}
        except Exception as e:
            logger.warning(f"[Supabase] Error patching existing email: {e}")
            return {"success": True, "is_new": False, "data": rec}
    else:
        # Brand new email: append
        logger.info(f"[Supabase] Email ({clean_email}) is new. Appending to '{EMAILS_TABLE}' in Supabase...")
        insert_payload = {
            "email": clean_email,
            "password": password,
            "refresh_token": refresh_token,
            "client_id": client_id,
            "full_mail_string": full_string,
            "provider": provider,
            "status": mail_data.get("status") or "ACTIVE",
            "used_in_platforms": [platform] if platform else [],
            "last_used_platform": platform or "",
            "last_used_at": now_iso,
            "created_at": now_iso,
            "updated_at": now_iso,
            "details": mail_data.get("details") or {}
        }

        try:
            insert_url = f"{supabase_url}/rest/v1/{EMAILS_TABLE}"
            insert_req = urllib.request.Request(
                insert_url,
                data=json.dumps(insert_payload).encode("utf-8"),
                headers={
                    "apikey": supabase_key,
                    "Authorization": f"Bearer {supabase_key}",
                    "Content-Type": "application/json",
                    "Prefer": "return=representation"
                },
                method="POST"
            )
            with urllib.request.urlopen(insert_req, timeout=10) as resp:
                body = resp.read().decode("utf-8")
                created = json.loads(body) if body else []
                logger.info(f"[Supabase] Successfully appended new email ({clean_email}) to '{EMAILS_TABLE}'!")
                return {"success": True, "is_new": True, "data": created[0] if created else insert_payload}
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8", errors="ignore")
            logger.warning(f"[Supabase HTTP {e.code}] Error inserting email: {err_msg}")
            return {"success": False, "is_new": True, "error": err_msg}
        except Exception as e:
            logger.warning(f"[Supabase] Failed to insert email: {e}")
            return {"success": False, "error": str(e)}


if __name__ == "__main__":
    import sys
    cfg = get_supabase_config()
    print(f"Supabase URL: {cfg['supabase_url'] or '(none configured)'}")
    if "--test" in sys.argv:
        res = log_to_supabase({
            "platform": "Test-Python",
            "email": "test_py_supabase@outlook.com",
            "username": "py_bot_supa",
            "status": "TEST_OK"
        })
        print(f"Result: {res}")
