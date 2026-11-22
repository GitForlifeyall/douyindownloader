#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/migrate_identities.py
===========================
One-shot importer that folds the existing per-platform registries, risk logs and
profile folders into the unified identity store (output/identities.json).

Sources read (never modified):
  output/facebook_registered_accounts.json
  output/instagram_registered_accounts.json
  output/metricool_registered_accounts.json   (may not exist)
  output/facebook_risk_log.json
  output/instagram_risk_log.json
  output/profiles facebook/*/
  output/profiles instagram/*/
  output/profiles metricool/*/

Orphans are imported too, so the "risk logs have more entries than registries"
gap becomes visible in one place instead of being silently lost:

  * a risk-log entry with no registry record  -> platform status "failed"
    note "orphan risk log: run never wrote a registry record"
  * a profile folder with no registry record   -> platform status "failed"
    note "orphan profile: run aborted before saving credentials"

Run:
  python tools/migrate_identities.py --dry-run
  python tools/migrate_identities.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import identity_store as store

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"

REGISTRY_FILES = {
    "facebook": OUTPUT_DIR / "facebook_registered_accounts.json",
    "instagram": OUTPUT_DIR / "instagram_registered_accounts.json",
    "metricool": OUTPUT_DIR / "metricool_registered_accounts.json",
}

RISK_LOG_FILES = {
    "facebook": OUTPUT_DIR / "facebook_risk_log.json",
    "instagram": OUTPUT_DIR / "instagram_risk_log.json",
    "metricool": OUTPUT_DIR / "metricool_risk_log.json",
}

LEGACY_PROFILE_ROOTS = {
    "facebook": OUTPUT_DIR / "profiles facebook",
    "instagram": OUTPUT_DIR / "profiles instagram",
    "metricool": OUTPUT_DIR / "profiles metricool",
}

OK_WORDS = {"confirmed", "active", "ok", "success", "created", "logged_in", "complete"}
SUSPENDED_WORDS = {"suspended", "disabled", "banned", "checkpoint", "restricted"}


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _normalize_status(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    if not text:
        return "none"
    if text in SUSPENDED_WORDS:
        return "suspended"
    if text in OK_WORDS:
        return "ok"
    if "suspend" in text or "ban" in text or "disable" in text:
        return "suspended"
    return "failed"


def _clean_proxy(raw: Any) -> str:
    text = str(raw or "").strip()
    for prefix in ("http://", "https://", "socks5://"):
        if text.lower().startswith(prefix):
            text = text[len(prefix):]
    return text


def _proxy_country(record: Dict[str, Any]) -> str:
    loc = record.get("proxy_location") or {}
    if isinstance(loc, dict):
        value = loc.get("country") or ""
        if value and value != "Unknown":
            return str(value)
    return ""


def _legacy_dirs(email: str) -> List[str]:
    """Existing per-platform profile folders for this mailbox local part."""
    local = str(email).split("@")[0]
    found: List[str] = []
    for root in LEGACY_PROFILE_ROOTS.values():
        candidate = root / local
        if candidate.exists():
            try:
                found.append(str(candidate.relative_to(PROJECT_ROOT)))
            except ValueError:
                found.append(str(candidate))
    return found


def collect() -> Dict[str, Dict[str, Any]]:
    """Merge every source into one dict keyed by lowercased email."""
    merged: Dict[str, Dict[str, Any]] = {}

    def bucket(email: str) -> Dict[str, Any]:
        key = str(email).strip().lower()
        if key not in merged:
            merged[key] = {
                "email": str(email).strip(),
                "account_string": "",
                "proxy": "",
                "proxy_ip": "",
                "proxy_country": "",
                "fingerprint_hash": None,
                "platforms": {},
                "notes": [],
            }
        return merged[key]

    # 1. Registries: authoritative for credentials + status.
    for platform, path in REGISTRY_FILES.items():
        records = _load_json(path)
        if not isinstance(records, list):
            continue
        for rec in records:
            email = str(rec.get("email") or "").strip()
            if not email:
                continue
            item = bucket(email)
            item["proxy"] = item["proxy"] or _clean_proxy(rec.get("proxy_used"))
            item["proxy_ip"] = item["proxy_ip"] or str(rec.get("proxy_ip") or "")
            item["proxy_country"] = item["proxy_country"] or _proxy_country(rec)
            if not item["fingerprint_hash"]:
                item["fingerprint_hash"] = rec.get("fingerprint_hash")
            status = _normalize_status(rec.get("status"))
            url = (
                rec.get("page_url")
                or rec.get("instagram_url")
                or rec.get("metricool_url")
                or ""
            )
            item["platforms"][platform] = {
                "status": status,
                "url": str(url or ""),
                "at": rec.get("account_created_at") or rec.get("created_at"),
                "note": (
                    f"suspended: {rec.get('suspension_url')}"
                    if status == "suspended" and rec.get("suspension_url")
                    else ""
                ),
            }
            item["notes"].append(
                f"imported from {path.name} ({platform}, status={status})"
            )

    # 2. Risk logs: fill gaps and record orphans.
    for platform, path in RISK_LOG_FILES.items():
        records = _load_json(path)
        if not isinstance(records, list):
            continue
        for rec in records:
            email = str(rec.get("email") or "").strip()
            if not email:
                continue
            item = bucket(email)
            warnings = rec.get("warnings") or []
            if platform in item["platforms"]:
                existing = item["platforms"][platform]
                if not existing.get("at"):
                    existing["at"] = rec.get("created_at")
                continue
            item["platforms"][platform] = {
                "status": "failed",
                "url": "",
                "at": rec.get("created_at"),
                "note": (
                    "orphan risk log: run never wrote a registry record"
                    + (f" | first warning: {warnings[0][:120]}" if warnings else "")
                ),
            }
            item["notes"].append(
                f"imported orphan risk-log entry from {path.name} ({platform})"
            )

    # 3. Profile folders: record legacy dirs, catch profiles with no records at all.
    for platform, root in LEGACY_PROFILE_ROOTS.items():
        if not root.exists():
            continue
        for folder in sorted(p for p in root.iterdir() if p.is_dir()):
            info = _load_json(folder / "account_info.json") or {}
            email = str(info.get("email") or "").strip()
            if not email:
                # Fall back to the folder name so the profile is not lost.
                email = f"{folder.name}@unknown"
                item = bucket(email)
                item["notes"].append(
                    f"orphan profile folder {folder.name} has no account_info email"
                )
            else:
                item = bucket(email)
            if platform not in item["platforms"]:
                item["platforms"][platform] = {
                    "status": "failed",
                    "url": "",
                    "at": None,
                    "note": "orphan profile: run aborted before saving credentials",
                }
            if not item["proxy"] and info.get("proxy_used"):
                item["proxy"] = _clean_proxy(info.get("proxy_used"))

    # 4. Attach legacy profile dirs for every identity.
    for key, item in merged.items():
        dirs = _legacy_dirs(item["email"])
        if dirs:
            item["legacy_profile_dirs"] = dirs

    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description="Import existing accounts into the identity store")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan, write nothing")
    args = parser.parse_args()

    merged = collect()
    if not merged:
        print("Nothing to import (no registries, risk logs or profiles found).")
        return 0

    existing = {str(r.get("email", "")).lower() for r in store.list_identities()}
    created = updated = 0

    rows = []
    for key, item in sorted(merged.items()):
        platforms = item.get("platforms") or {}
        marks = " ".join(
            f"{p[:2]}={(platforms.get(p) or {}).get('status', '-')}"
            for p in store.PLATFORMS
        )
        state_hint = "new" if not platforms else "imported"
        rows.append((item["email"], marks, item.get("legacy_profile_dirs") or [], state_hint))
        if args.dry_run:
            continue
        fields: Dict[str, Any] = {
            "account_string": item.get("account_string") or "",
            "proxy": item.get("proxy") or "",
            "proxy_ip": item.get("proxy_ip") or "",
            "proxy_country": item.get("proxy_country") or "",
            "platforms": platforms,
        }
        if item.get("fingerprint_hash"):
            fields["fingerprint_hash"] = item["fingerprint_hash"]
        if item.get("legacy_profile_dirs"):
            fields["legacy_profile_dirs"] = item["legacy_profile_dirs"]
        for note in item.get("notes") or []:
            fields["note"] = note
        store.upsert(item["email"], **fields)
        if key in existing:
            updated += 1
        else:
            created += 1

    print(f"{'EMAIL':40s} {'PLATFORMS':34s} LEGACY PROFILE DIRS")
    for email, marks, dirs, _hint in rows:
        print(f"{email:40s} {marks:34s} {', '.join(dirs) if dirs else '-'}")

    if args.dry_run:
        print(f"\n[dry-run] would create/update {len(rows)} identities")
    else:
        print(f"\nDone. created={created} updated={updated} total={len(merged)}")
        print(f"Store: {store.IDENTITIES_FILE}")
        print(json.dumps(store.summary(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
