#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/run_identity.py
=====================
Run ONE platform (Metricool / Facebook / Instagram) inside an identity's shared
browser profile, behind the proxy gate.

This is the only supported entry point for account creation. It guarantees:

  1. The proxy is verified BEFORE a browser opens (tools/proxy_check.py).
     A rejected proxy never burns an account.
  2. Metricool, Facebook and Instagram all launch with the same --profile-dir,
     so Meta sees the same device that Metricool already trusts.
  3. Every run writes a terminal record to the identity store, even when the
     script crashes or is killed. No more "risk log has an entry but the
     registry does not".

Usage:
  python tools/run_identity.py --identity hanijyra562 --platform facebook
  python tools/run_identity.py --identity hanijyra562 --platform metricool --headless
  python tools/run_identity.py --identity hanijyra562 --platform instagram --dry-run

Exit codes: 0 ok | 1 failed/aborted | 2 proxy gate rejected | 3 usage error
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
TOOLS_DIR = PROJECT_ROOT / "tools"

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import identity_store as store
import proxy_check
import supabase_logger

REGISTRY_FILES = {
    "facebook": OUTPUT_DIR / "facebook_registered_accounts.json",
    "instagram": OUTPUT_DIR / "instagram_registered_accounts.json",
    "metricool": OUTPUT_DIR / "metricool_registered_accounts.json",
    "combo": OUTPUT_DIR / "facebook_registered_accounts.json",
}

SCRIPTS = {
    "facebook": TOOLS_DIR / "facebook_signup_camoufox.mjs",
    "instagram": TOOLS_DIR / "instagram_signup_camoufox.mjs",
    "metricool": TOOLS_DIR / "metricool_camoufox.mjs",
    "combo": TOOLS_DIR / "facebook_signup_camoufox.mjs",
}

ADOPT_IGNORE = (
    "cache2", "startupCache", "shader-cache", "crashes", "minidumps",
    "datareporting", "saved-telemetry-pings", "storage", "cache",
)


def node_exe() -> str:
    candidate = os.path.expandvars(r"%LOCALAPPDATA%\Programs\NodeJS\node22\node.exe")
    return candidate if Path(candidate).exists() else "node"


def mask(secret: str) -> str:
    text = str(secret or "")
    if not text:
        return ""
    if len(text) <= 8:
        return "***"
    return text[:4] + "***" + text[-2:]


def read_persona_timezone(profile_dir: Path) -> str:
    path = Path(profile_dir) / "persona.json"
    if not path.exists():
        return ""
    try:
        return str(json.loads(path.read_text(encoding="utf-8")).get("timezone") or "")
    except Exception:
        return ""


TZ_REGION = {
    "Asia/Kolkata": "IN", "Asia/Calcutta": "IN",
    "America/Chicago": "US", "America/New_York": "US", "America/Los_Angeles": "US",
    "America/Denver": "US", "America/Phoenix": "US", "America/Anchorage": "US",
    "Europe/London": "GB", "Europe/Berlin": "DE", "Europe/Paris": "FR",
    "Europe/Amsterdam": "NL", "Asia/Tokyo": "JP", "Asia/Singapore": "SG",
    "America/Toronto": "CA", "Australia/Sydney": "AU", "America/Sao_Paulo": "BR",
}


def region_of_timezone(tz: str) -> str:
    tz = str(tz or "")
    if tz in TZ_REGION:
        return TZ_REGION[tz]
    if tz.startswith("America/"):
        return "US"
    if "Kolkata" in tz or "Calcutta" in tz:
        return "IN"
    return ""


def _strip_session(username: str) -> str:
    """Remove any existing Oxylabs session token from a proxy username."""
    return re.sub(
        r"-(?:sessid_oneip|sessid|session|sess)-[A-Za-z0-9._]+(?:-sesstime-\d+)?",
        "",
        username,
        flags=re.I,
    )


def ensure_sticky_proxy(proxy: str, identity_id: str, require_country: str = "AUTO",
                        nonce: int = 0) -> str:
    """Own the Oxylabs geo pin and session so all three platforms share one exit.

    Two things are managed:
      * -cc-<country>: preserved if present, or specified by require_country (unless AUTO).
      * -sessid-<hash>-sesstime-30 derived from the identity (+ nonce).
    """
    if "@" not in proxy:
        return proxy
    auth, _, host_port = proxy.rpartition("@")
    username, sep, password = auth.partition(":")
    if not sep:
        return proxy

    is_oxylabs = "oxylabs.io" in host_port.lower() or username.lower().startswith("customer-")
    if not is_oxylabs:
        return proxy

    # Check for existing -cc-<country>
    cc_match = re.search(r"-cc-([a-z]{2})", username, flags=re.I)
    existing_cc = cc_match.group(1).lower() if cc_match else ""

    # Rebuild from the base username, discarding any pasted geo/session token.
    base = _strip_session(username)
    base = re.sub(r"-(?:cc-[a-z]{2}|st-[a-z_]+|city-[a-z_]+)(?=-|$)", "", base, flags=re.I)

    parts = [base]
    effective_country = ""
    if require_country and str(require_country).upper() not in ("AUTO", "ANY", "NONE"):
        effective_country = str(require_country).lower()
    elif existing_cc:
        effective_country = existing_cc
    else:
        # Fallback to Indian residential proxy to guarantee low-latency domestic exit instead of random countries
        effective_country = "in"

    if effective_country:
        parts.append(f"-cc-{effective_country}")
    session = hashlib.sha256(f"{identity_id}:{effective_country}:{int(nonce)}".encode()).hexdigest()[:10]
    parts.append(f"-sessid-{session}-sesstime-30")

    return f"{''.join(parts)}:{password}@{host_port}"


def split_account(account_string: str) -> Dict[str, str]:
    """email|password|refresh_token|client_id -> parts (missing -> '')."""
    parts = str(account_string or "").split("|")
    parts += [""] * (4 - len(parts))
    return {
        "email": parts[0].strip(),
        "password": parts[1].strip(),
        "refresh_token": parts[2].strip(),
        "client_id": parts[3].strip(),
    }


def resolve_identity(token: str) -> Dict[str, Any]:
    record = store.get(token)
    if record:
        return record
    record = store.find_by_email(token)
    if record:
        return record
    raise KeyError(f"unknown identity: {token}")


def unified_profile_dir(record: Dict[str, Any]) -> Path:
    raw = record.get("profile_dir") or str(store.default_profile_dir(record["identity_id"]))
    path = Path(raw)
    return path if path.is_absolute() else PROJECT_ROOT / path


def adopt_legacy_profile(record: Dict[str, Any], platform: str, target: Path) -> Optional[str]:
    """Copy the best existing per-platform profile into the unified dir, once."""
    if target.exists() and any(target.iterdir()):
        return None
    legacy = record.get("legacy_profile_dirs") or []
    if not legacy:
        return None
    preferred = [d for d in legacy if len(Path(d).parts) >= 2 and platform in Path(d).parts[-2]] + list(legacy)
    source = None
    for candidate in preferred:
        path = Path(candidate)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if path.exists():
            source = path
            break
    if not source:
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(*ADOPT_IGNORE), dirs_exist_ok=True)
    return str(source.relative_to(PROJECT_ROOT)) if source.is_relative_to(PROJECT_ROOT) else str(source)


def build_command(record: Dict[str, Any], platform: str, profile_dir: Path,
                  proxy: str, args: argparse.Namespace, exit_ip: str = "") -> Tuple[List[str], Dict[str, str]]:
    creds = split_account(record.get("account_string") or "")
    email = creds["email"] or record.get("email", "")
    password = creds["password"] or args.password or ""
    refresh_token = creds["refresh_token"] or args.refresh_token or ""
    client_id = creds["client_id"] or args.client_id or ""

    cmd = [node_exe(), "--experimental-sqlite", str(SCRIPTS[platform])]

    if platform in ("metricool", "combo") and password:
        p = password
        if not re.search(r"[A-Z]", p): p = "M" + p
        if not re.search(r"[a-z]", p): p = p + "a"
        if not re.search(r"[0-9]", p): p = p + "1"
        if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]", p): p = p + "!"
        if len(p) > 20: p = p[:19] + "!"
        password = p

    if platform in ("facebook", "instagram", "combo"):
        if record.get("account_string"):
            cmd += ["--account", record["account_string"]]
        else:
            cmd += ["--email", email]
        if password:
            cmd += ["--password", password]
        if refresh_token:
            cmd += ["--refresh-token", refresh_token]
        if client_id:
            cmd += ["--client-id", client_id]
        cmd += ["--profile-dir", str(profile_dir), "--proxy", proxy]
        if platform == "combo":
            cmd += ["--combo"]
        if args.timezone:
            cmd += ["--timezone", args.timezone]
        if exit_ip:
            cmd += ["--exit-ip", exit_ip]
        if args.headless:
            cmd += ["--headless"]
        if args.skip_2fa:
            cmd += ["--skip-2fa"]
        if platform in ("facebook", "combo") and args.skip_page:
            cmd += ["--skip-page"]
        if args.skip_warmup:
            cmd += ["--skip-warmup"]
        if getattr(args, "fast", False):
            cmd += ["--fast"]
    else:  # metricool
        cmd += ["--action", args.metricool_action, "--email", email]
        if password:
            cmd += ["--password", password]
        if refresh_token:
            cmd += ["--refresh-token", refresh_token]
        if client_id:
            cmd += ["--client-id", client_id]
        cmd += ["--profile-dir", str(profile_dir), "--proxy", proxy]
        if args.timezone:
            cmd += ["--timezone", args.timezone]
        if exit_ip:
            cmd += ["--exit-ip", exit_ip]
        if args.headless:
            cmd += ["--headless"]
        if getattr(args, "fast", False):
            cmd += ["--fast"]

    display = {}
    if record.get("account_string"):
        display[record["account_string"]] = "|".join(
            [mask(email), mask(password), mask(refresh_token), mask(client_id)]
        )
    if password:
        display[password] = mask(password)
    return cmd, display


def registry_status(platform: str, email: str) -> Optional[Dict[str, Any]]:
    path = REGISTRY_FILES[platform]
    if not path.exists():
        return None
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(records, list):
        return None
    target = str(email or "").lower()
    for rec in reversed(records):
        if str(rec.get("email", "")).lower() == target:
            return rec
    return None


def classify(platform: str, record: Optional[Dict[str, Any]], exit_code: int) -> Tuple[str, str]:
    """Map a finished run to (identity status, note)."""
    if record:
        raw = str(record.get("status") or "").strip().lower()
        if raw in ("suspended", "disabled", "banned", "checkpoint"):
            return "suspended", f"registry status={raw} url={record.get('suspension_url', '')}"
        if raw in ("confirmed", "active", "ok", "success", "logged_in"):
            return "ok", f"registry status={raw}"
        if raw == "partial":
            return "failed", "registry status=partial (signup did not reach dashboard)"
    if exit_code == 0:
        return "failed", "script exited 0 but wrote no registry record"
    return "failed", f"script exited {exit_code} without a registry record"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one platform inside an identity's shared profile")
    parser.add_argument("--identity", required=True, help="identity_id or email")
    parser.add_argument("--platform", required=True, choices=store.PLATFORMS)
    parser.add_argument("--proxy", default="", help="override the identity proxy")
    parser.add_argument("--password", default="")
    parser.add_argument("--refresh-token", default="")
    parser.add_argument("--client-id", default="")
    parser.add_argument("--metricool-action", default="signup", choices=["signup", "login", "open"])
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--skip-2fa", action="store_true")
    parser.add_argument("--skip-page", action="store_true")
    parser.add_argument("--skip-warmup", action="store_true")
    parser.add_argument("--no-adopt", action="store_true", help="do not copy a legacy profile")
    parser.add_argument("--skip-proxy-check", action="store_true", help="NOT recommended")
    parser.add_argument("--require-country", default=proxy_check.REQUIRE_COUNTRY)
    parser.add_argument("--timezone", default="", help="override; defaults to the verified exit-IP country")
    parser.add_argument("--rotate-session", action="store_true",
                        help="force a new sticky session (new exit IP) for this identity")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--fast", "--skip-delays", dest="fast", action="store_true", help="skip typing delays and cursor trajectories for fast testing")
    args = parser.parse_args()

    try:
        record = resolve_identity(args.identity)
    except KeyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3

    identity_id = record["identity_id"]
    platform = args.platform
    email = record.get("email", "")

    proxy = (args.proxy or record.get("proxy") or "").strip()
    proxy = re.sub(r"^(https?|socks5)://", "", proxy, flags=re.I)
    if not proxy:
        print("ERROR: identity has no proxy and --proxy was not given.", file=sys.stderr)
        print("       Use: python tools/run_identity.py --identity "
              f"{identity_id} --platform {platform} --proxy user:pass@host:port", file=sys.stderr)
        return 3

    if args.rotate_session and not args.dry_run:
        record = store.rotate_session(identity_id)
        print("session    : rotated (new exit IP on this run)")
    nonce = int(record.get("session_nonce") or 0)
    sticky = ensure_sticky_proxy(proxy, identity_id, args.require_country, nonce)
    if sticky != proxy:
        print(f"sticky     : pinned session for {identity_id}")
        proxy = sticky
        if not args.dry_run:
            store.upsert(email, proxy=proxy)

    print("=" * 68)
    print(f"IDENTITY RUN  {identity_id}  ->  {platform.upper()}")
    print("=" * 68)
    print(f"email      : {email}")
    print(f"proxy      : {proxy_check.parse_proxy(proxy)['host']}:{proxy_check.parse_proxy(proxy)['port']}"
          if proxy_check.parse_proxy(proxy) else f"proxy      : {proxy}")

    # 1. Proxy gate.
    gate = None
    gate_country = ""
    if args.skip_proxy_check:
        print("proxy gate : SKIPPED (--skip-proxy-check)")
        cc = re.search(r"-cc-([a-z]{2})", proxy, flags=re.I)
        gate_country = cc.group(1).upper() if cc else (record.get("proxy_country") or "")
        if not args.timezone:
            args.timezone = (
                record.get("proxy_timezone")
                or proxy_check.timezone_for_country(gate_country)["timezone"]
            )
    else:
        gate = proxy_check.check_proxy(proxy, args.require_country)
        print(f"proxy gate : {'PASS' if gate['ok'] else 'REJECT'} "
              f"ip={gate['ip'] or '-'} country={gate['country'] or '-'} "
              f"isp={gate['isp'] or '-'} ({gate['latency_ms']}ms)")
        if not gate["ok"]:
            print("proxy gate : initial check rejected or peer unreachable, auto-rotating to fresh peer...")
            if not args.dry_run:
                record = store.rotate_session(identity_id)
            nonce = int(record.get("session_nonce") or 0) + 1
            proxy = ensure_sticky_proxy(proxy, identity_id, args.require_country, nonce)
            gate = proxy_check.check_proxy(proxy, args.require_country)
            print(f"proxy gate : retry {'PASS' if gate['ok'] else 'REJECT'} "
                  f"ip={gate['ip'] or '-'} country={gate['country'] or '-'} "
                  f"isp={gate['isp'] or '-'} ({gate['latency_ms']}ms)")
        if not gate["ok"]:
            for reason in gate["reasons"]:
                print(f"  - {reason}")
            if not args.dry_run:
                store.set_proxy(identity_id, proxy, gate["ip"], gate["country"], gate["isp"], verified=False)
                store.set_platform(identity_id, platform, "aborted",
                                   note="proxy gate rejected: " + "; ".join(gate["reasons"]))
            print("\nRefusing to launch. Fix the proxy or pass --proxy with a clean residential exit.")
            return 2
        if not args.timezone:
            args.timezone = gate["timezone"]
        gate_country = gate["country"]
        print(f"timezone   : {args.timezone or '-'} (from verified exit IP)")
        if not args.dry_run:
            store.set_proxy(identity_id, proxy, gate["ip"], gate["country"], gate["isp"],
                            verified=True, timezone=gate["timezone"])

    # 2. Shared profile dir.
    target = unified_profile_dir(record)
    print(f"profile dir: {target}")
    if not args.dry_run and not args.no_adopt:
        adopted = adopt_legacy_profile(record, platform, target)
        if adopted:
            print(f"adopted    : copied legacy profile from {adopted}")
    if not args.dry_run:
        target.mkdir(parents=True, exist_ok=True)

    # 2b. Coherence: a frozen persona from another country is the contradiction
    # that got shravyageorgeann433 flagged (IN proxy, America/Chicago browser).
    proxy_country = (gate_country or record.get("proxy_country", "")) or ""
    persona_tz = read_persona_timezone(target)
    if persona_tz and proxy_country:
        persona_region = region_of_timezone(persona_tz)
        if persona_region and persona_region != proxy_country.upper():
            message = (
                f"persona timezone {persona_tz} ({persona_region}) contradicts proxy country "
                f"{proxy_country}; geoip:true aligns the browser to the exit IP, but the frozen "
                f"persona still claims {persona_region}"
            )
            print(f"WARNING    : {message}")
            if not args.dry_run:
                store.upsert(email, note=message)
                if args.timezone:
                    persona_file = target / "persona.json"
                    if persona_file.exists():
                        try:
                            p_data = json.loads(persona_file.read_text(encoding="utf-8"))
                            p_data["timezone"] = args.timezone
                            p_data["locale:region"] = proxy_country.upper()
                            persona_file.write_text(json.dumps(p_data, indent=2), encoding="utf-8")
                            print(f"aligned    : synced persona timezone to {args.timezone} ({proxy_country.upper()})")
                        except Exception:
                            pass

    # 3. Command.
    exit_ip = gate.get("ip", "") if gate else record.get("proxy_ip", "")
    cmd, display = build_command(record, platform, target, proxy, args, exit_ip=exit_ip)
    printable = " ".join(cmd)
    for secret, masked in display.items():
        if secret:
            printable = printable.replace(secret, masked)
    print(f"command    : {printable}")

    if args.dry_run:
        print("\n[dry-run] nothing launched, identity store unchanged")
        return 0

    # 4. Run.
    store.set_platform(identity_id, platform, "running", note="launched by run_identity")
    started = time.time()
    exit_code = 1
    try:
        exit_code = subprocess.call(cmd, cwd=str(PROJECT_ROOT))
    except KeyboardInterrupt:
        exit_code = 130
    except Exception as exc:
        print(f"launch failed: {exc}", file=sys.stderr)
        exit_code = 1
    elapsed = int(time.time() - started)

    # 5. Terminal record, always.
    if platform == "combo":
        fb_reg = registry_status("facebook", email)
        mc_reg = registry_status("metricool", email)
        fb_status, fb_note = classify("facebook", fb_reg, exit_code)
        mc_status, mc_note = classify("metricool", mc_reg, exit_code)
        fb_url = str((fb_reg or {}).get("page_url") or "")
        mc_url = str((mc_reg or {}).get("dashboard_url") or "")
        store.set_platform(identity_id, "facebook", fb_status, url=fb_url, note=f"{fb_note} (combo exit={exit_code})")
        store.set_platform(identity_id, "metricool", mc_status, url=mc_url, note=f"{mc_note} (combo exit={exit_code})")
        status = "ok" if (fb_status == "ok" and mc_status == "ok") else ("ok" if fb_status == "ok" else fb_status)
        note = f"FB:{fb_status} MC:{mc_status}"
        url = fb_url or mc_url
        store.set_platform(identity_id, "combo", status, url=url, note=f"{note} (exit={exit_code}, {elapsed}s)")
        reg = fb_reg or mc_reg
    else:
        reg = registry_status(platform, email)
        status, note = classify(platform, reg, exit_code)
        url = ""
        if reg:
            url = str(reg.get("page_url") or reg.get("instagram_url") or reg.get("dashboard_url") or "")
            if not url and reg.get("suspension_url"):
                url = str(reg["suspension_url"])
        store.set_platform(identity_id, platform, status, url=url, note=f"{note} (exit={exit_code}, {elapsed}s)")

    # 6. Supabase Cloud Sync
    if not args.dry_run:
        try:
            creds = split_account(record.get("account_string") or "")
            supabase_logger.log_to_supabase({
                "platform": platform.upper(),
                "email": email,
                "username": (reg.get("username") or reg.get("name") or identity_id) if reg else identity_id,
                "password": creds.get("password") or args.password or (reg.get("password") if reg else ""),
                "profile_url": url,
                "full_mail_string": record.get("account_string", ""),
                "proxy": proxy,
                "status": "ACTIVE" if status == "ok" else ("SUSPENDED" if status == "suspended" else "FAILED"),
                "details": {"exit_code": exit_code, "note": note, "elapsed_seconds": elapsed, "url": url}
            })
            print("supabase   : synced record to cloud database")
        except Exception as exc:
            print(f"supabase   : sync warning ({exc})")

    print("-" * 68)
    print(f"RESULT     : {platform} -> {status}")
    print(f"note       : {note} (exit={exit_code}, {elapsed}s)")
    print(f"identity   : {identity_id} (state={store.get(identity_id)['state']})")
    print("-" * 68)
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
