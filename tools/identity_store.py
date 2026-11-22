#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/identity_store.py
=======================
Canonical store for "one identity = one browser profile = one proxy".

An identity is the single record that ties a mailbox to the browser profile
used by Metricool, Facebook and Instagram, and to the one proxy that profile
always exits from.

Store: output/identities.json  (atomic writes, no secrets printed by CLI)

Record shape:
{
  "identity_id": "shravyageorgeann433",
  "email": "shravyageorgeann433@outlook.in",
  "account_string": "email|password|refresh_token|client_id",
  "profile_dir": "output/profiles/shravyageorgeann433",
  "proxy": "user:pass@host:port",
  "proxy_ip": "", "proxy_country": "", "proxy_isp": "",
  "proxy_verified_at": null,
  "fingerprint_hash": null,
  "state": "new|active|complete|failed|discarded",
  "created_at": "...", "updated_at": "...",
  "platforms": {
    "metricool": {"status": "none", "url": "", "at": null, "note": ""},
    "facebook":  {"status": "none", "url": "", "at": null, "note": ""},
    "instagram": {"status": "none", "url": "", "at": null, "note": ""}
  }
}

Platform status values: none | ok | suspended | failed | aborted
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
IDENTITIES_FILE = OUTPUT_DIR / "identities.json"
ARCHIVE_DIR = OUTPUT_DIR / "identities_archive"
PROFILES_ROOT = OUTPUT_DIR / "profiles"

PLATFORMS = ("metricool", "facebook", "instagram")

OK_STATUSES = {"ok", "confirmed", "active", "logged_in", "success", "complete"}
SUSPENDED_STATUSES = {"suspended", "disabled", "banned", "checkpoint"}
FAILED_STATUSES = {"failed", "error", "needs_otp", "pending_otp", "partial"}
ABORTED_STATUSES = {"aborted", "skipped"}
RUNNING_STATUSES = {"running"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_platform() -> Dict[str, Any]:
    return {"status": "none", "url": "", "at": None, "note": ""}


def _read() -> List[Dict[str, Any]]:
    if not IDENTITIES_FILE.exists():
        return []
    try:
        data = json.loads(IDENTITIES_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write(records: List[Dict[str, Any]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = IDENTITIES_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, IDENTITIES_FILE)


def slugify_email(email: str) -> str:
    """Profile-safe id from the mailbox local part (matches the signup scripts)."""
    local = str(email or "").split("@")[0]
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "", local)
    if not cleaned or cleaned in (".", ".."):
        cleaned = "identity_" + hashlib.sha256(str(email).encode()).hexdigest()[:8]
    return cleaned


def identity_id_for(email: str) -> str:
    """Stable id; disambiguates two domains sharing a local part."""
    base = slugify_email(email)
    records = _read()
    for rec in records:
        if rec.get("identity_id") == base and str(rec.get("email", "")).lower() != str(email).lower():
            suffix = hashlib.sha256(str(email).lower().encode()).hexdigest()[:6]
            return f"{base}_{suffix}"
    return base


def default_profile_dir(identity_id: str) -> Path:
    return PROFILES_ROOT / identity_id


def find_by_email(email: str) -> Optional[Dict[str, Any]]:
    target = str(email or "").strip().lower()
    if not target:
        return None
    for rec in _read():
        if str(rec.get("email", "")).strip().lower() == target:
            return rec
    return None


def get(identity_id: str) -> Optional[Dict[str, Any]]:
    for rec in _read():
        if rec.get("identity_id") == identity_id:
            return rec
    return None


def derive_state(rec: Dict[str, Any]) -> str:
    if rec.get("state") == "discarded":
        return "discarded"
    platforms = rec.get("platforms") or {}
    statuses = [((platforms.get(p) or {}).get("status") or "none") for p in PLATFORMS]
    if any(s in SUSPENDED_STATUSES for s in statuses):
        return "failed"
    ok = sum(1 for s in statuses if s in OK_STATUSES)
    if ok == len(PLATFORMS):
        return "complete"
    if any(s in RUNNING_STATUSES for s in statuses):
        return "running"
    if ok > 0:
        return "active"
    if any(s in FAILED_STATUSES or s in ABORTED_STATUSES for s in statuses):
        return "failed"
    return "new"


def _normalize(rec: Dict[str, Any]) -> Dict[str, Any]:
    rec.setdefault("identity_id", identity_id_for(rec.get("email", "")))
    rec.setdefault("account_string", "")
    rec.setdefault("profile_dir", str(default_profile_dir(rec["identity_id"])))
    rec.setdefault("proxy", "")
    rec.setdefault("proxy_ip", "")
    rec.setdefault("proxy_country", "")
    rec.setdefault("proxy_isp", "")
    rec.setdefault("proxy_timezone", "")
    rec.setdefault("session_nonce", 0)
    rec.setdefault("proxy_verified_at", None)
    rec.setdefault("fingerprint_hash", None)
    rec.setdefault("created_at", _now())
    rec.setdefault("notes", [])
    platforms = rec.get("platforms") or {}
    for p in PLATFORMS:
        platforms.setdefault(p, _empty_platform())
    rec["platforms"] = platforms
    rec["updated_at"] = _now()
    rec["state"] = derive_state(rec)
    return rec


def upsert(email: str, **fields: Any) -> Dict[str, Any]:
    """Create or update the identity for this email. Returns the stored record."""
    email = str(email or "").strip()
    if not email:
        raise ValueError("email is required")
    records = _read()
    target = email.lower()
    idx = next((i for i, r in enumerate(records)
                if str(r.get("email", "")).strip().lower() == target), None)
    if idx is None:
        rec = {
            "identity_id": fields.get("identity_id") or identity_id_for(email),
            "email": email,
            "account_string": "",
            "profile_dir": "",
            "proxy": "",
            "proxy_ip": "",
            "proxy_country": "",
            "proxy_isp": "",
            "proxy_timezone": "",
            "proxy_verified_at": None,
            "session_nonce": 0,
            "fingerprint_hash": None,
            "created_at": _now(),
            "notes": [],
            "platforms": {p: _empty_platform() for p in PLATFORMS},
        }
        records.append(rec)
        idx = len(records) - 1
    rec = records[idx]
    for key, value in fields.items():
        if key == "platforms":
            platforms = rec.setdefault("platforms", {})
            for p, pdata in value.items():
                platforms.setdefault(p, _empty_platform()).update(pdata)
        elif key == "note":
            rec.setdefault("notes", []).append({"at": _now(), "text": str(value)})
        elif key != "identity_id" or not rec.get("identity_id"):
            rec[key] = value
    if not rec.get("profile_dir"):
        rec["profile_dir"] = str(default_profile_dir(rec["identity_id"]))
    records[idx] = _normalize(rec)
    _write(records)
    return records[idx]


def new_identity(email: str, account_string: str = "", proxy: str = "",
                 identity_id: Optional[str] = None) -> Dict[str, Any]:
    return upsert(
        email,
        account_string=account_string,
        proxy=proxy,
        **({"identity_id": identity_id} if identity_id else {}),
    )


def set_proxy(identity_id: str, proxy: str, ip: str = "", country: str = "",
              isp: str = "", verified: bool = False, timezone: str = "") -> Dict[str, Any]:
    rec = get(identity_id)
    if not rec:
        raise KeyError(f"unknown identity: {identity_id}")
    return upsert(
        rec["email"],
        proxy=proxy,
        proxy_ip=ip,
        proxy_country=country,
        proxy_isp=isp,
        proxy_timezone=timezone or rec.get("proxy_timezone", ""),
        proxy_verified_at=_now() if verified else rec.get("proxy_verified_at"),
    )


def set_platform(identity_id: str, platform: str, status: str,
                 url: str = "", note: str = "") -> Dict[str, Any]:
    if platform not in PLATFORMS:
        raise ValueError(f"unknown platform: {platform}")
    rec = get(identity_id)
    if not rec:
        raise KeyError(f"unknown identity: {identity_id}")
    return upsert(
        rec["email"],
        platforms={platform: {"status": status, "url": url, "at": _now(), "note": note}},
    )


def set_fingerprint(identity_id: str, fingerprint_hash: str) -> Dict[str, Any]:
    rec = get(identity_id)
    if not rec:
        raise KeyError(f"unknown identity: {identity_id}")
    return upsert(rec["email"], fingerprint_hash=fingerprint_hash)


def rotate_session(identity_id: str) -> Dict[str, Any]:
    """Increments the session_nonce for the identity to trigger a fresh sticky session on the next run."""
    rec = get(identity_id)
    if not rec:
        raise KeyError(f"unknown identity: {identity_id}")
    nonce = int(rec.get("session_nonce") or 0) + 1
    return upsert(rec["email"], session_nonce=nonce, note=f"session rotated to nonce={nonce}")


def ensure_profile_dir(identity_id: str) -> Path:
    rec = get(identity_id)
    if not rec:
        raise KeyError(f"unknown identity: {identity_id}")
    path = Path(rec.get("profile_dir") or default_profile_dir(identity_id))
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def discard(identity_id: str, remove_profile: bool = True) -> Dict[str, Any]:
    """Archive the profile and mark the identity discarded (keeps the record)."""
    rec = get(identity_id)
    if not rec:
        raise KeyError(f"unknown identity: {identity_id}")
    profile = Path(rec.get("profile_dir") or "")
    if remove_profile and profile.exists():
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dest = ARCHIVE_DIR / f"{identity_id}_{stamp}"
        try:
            shutil.move(str(profile), str(dest))
        except Exception as exc:
            upsert(rec["email"], note=f"profile archive failed: {exc}")
    return upsert(rec["email"], state="discarded", note="identity discarded")


def list_identities() -> List[Dict[str, Any]]:
    return sorted(_read(), key=lambda r: str(r.get("updated_at", "")), reverse=True)


def summary() -> Dict[str, Any]:
    records = _read()
    counts = {"total": len(records), "new": 0, "active": 0, "complete": 0, "failed": 0, "discarded": 0}
    for rec in records:
        state = rec.get("state") or derive_state(rec)
        counts[state] = counts.get(state, 0) + 1
    per_platform = {p: {"ok": 0, "suspended": 0, "none": 0} for p in PLATFORMS}
    for rec in records:
        for p in PLATFORMS:
            status = ((rec.get("platforms") or {}).get(p) or {}).get("status", "none")
            if status in OK_STATUSES:
                per_platform[p]["ok"] += 1
            elif status in SUSPENDED_STATUSES:
                per_platform[p]["suspended"] += 1
            else:
                per_platform[p]["none"] += 1
    return {"counts": counts, "per_platform": per_platform}


def _main() -> int:
    parser = argparse.ArgumentParser(description="Identity store (one identity = one profile = one proxy)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List identities")
    sub.add_parser("summary", help="Show counts")

    p_get = sub.add_parser("get", help="Show one identity")
    p_get.add_argument("identity_id")

    p_new = sub.add_parser("new", help="Create/update an identity")
    p_new.add_argument("--email", required=True)
    p_new.add_argument("--account", default="")
    p_new.add_argument("--proxy", default="")

    p_proxy = sub.add_parser("set-proxy", help="Set the identity proxy")
    p_proxy.add_argument("identity_id")
    p_proxy.add_argument("--proxy", required=True)

    p_status = sub.add_parser("set-status", help="Set a platform status")
    p_status.add_argument("identity_id")
    p_status.add_argument("--platform", required=True, choices=PLATFORMS)
    p_status.add_argument("--status", required=True)
    p_status.add_argument("--note", default="")

    p_discard = sub.add_parser("discard", help="Archive profile and mark discarded")
    p_discard.add_argument("identity_id")

    args = parser.parse_args()
    if args.cmd == "list":
        for rec in list_identities():
            platforms = rec.get("platforms") or {}
            marks = " ".join(
                f"{p[:2]}={(platforms.get(p) or {}).get('status', 'none')}" for p in PLATFORMS
            )
            print(f"{rec['identity_id']:32s} {rec.get('state', '?'):10s} "
                  f"{rec.get('proxy_country', ''):3s} {marks}  {rec.get('email', '')}")
        return 0
    if args.cmd == "summary":
        print(json.dumps(summary(), indent=2))
        return 0
    if args.cmd == "get":
        rec = get(args.identity_id)
        if not rec:
            print(f"not found: {args.identity_id}")
            return 1
        print(json.dumps(rec, indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "new":
        rec = new_identity(args.email, args.account, args.proxy)
        print(json.dumps(rec, indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "set-proxy":
        rec = set_proxy(args.identity_id, args.proxy)
        print(f"{args.identity_id}: proxy updated")
        return 0
    if args.cmd == "set-status":
        rec = set_platform(args.identity_id, args.platform, args.status, note=args.note)
        print(f"{args.identity_id}: {args.platform} -> {args.status}")
        return 0
    if args.cmd == "discard":
        discard(args.identity_id)
        print(f"{args.identity_id}: discarded")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(_main())
