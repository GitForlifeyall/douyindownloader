#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/proxy_check.py
====================
Gate every account-creation run behind a real proxy check.

What it rejects:
  * Oxylabs Web Unblocker endpoints (unblock.oxylabs.io, wu_ usernames) - those
    IPs are built for scraping and are burned for Meta signups.
  * Any exit country other than the required one (default US).
  * A proxy that cannot reach the geo endpoint at all.

Usage:
  python tools/proxy_check.py --proxy "user:pass@pr.oxylabs.io:7777"
  python tools/proxy_check.py --proxy "..." --json
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

BLOCKED_HOSTS = ("unblock.oxylabs.io",)
BLOCKED_USER_PREFIXES = ("wu_",)
REQUIRE_COUNTRY = "AUTO"

COUNTRY_ALIASES = {
    "united states": "US",
    "united states of america": "US",
    "usa": "US",
    "india": "IN",
    "united kingdom": "GB",
    "great britain": "GB",
    "germany": "DE",
    "canada": "CA",
    "australia": "AU",
    "japan": "JP",
    "brazil": "BR",
    "france": "FR",
    "netherlands": "NL",
    "singapore": "SG",
}

DATACENTER_HINTS = (
    "amazon", "aws", "google", "digitalocean", "hetzner", "ovh",
    "linode", "vultr", "contabo", "azure", "microsoft", "cloudflare",
    "oxylabs", "datacenter", "hosting", "server",
)

# Country -> the browser identity that country implies. Keeping the browser
# timezone and the exit IP in the same country is what the coherence audit checks.
TIMEZONE_BY_COUNTRY = {
    "US": ("America/Chicago", "US", "en"),
    "IN": ("Asia/Kolkata", "IN", "en"),
    "GB": ("Europe/London", "GB", "en"),
    "DE": ("Europe/Berlin", "DE", "en"),
    "CA": ("America/Toronto", "CA", "en"),
    "AU": ("Australia/Sydney", "AU", "en"),
    "JP": ("Asia/Tokyo", "JP", "en"),
    "BR": ("America/Sao_Paulo", "BR", "pt"),
    "FR": ("Europe/Paris", "FR", "fr"),
    "NL": ("Europe/Amsterdam", "NL", "nl"),
    "SG": ("Asia/Singapore", "SG", "en"),
}


def timezone_for_country(country: str) -> Dict[str, str]:
    tz, region, lang = TIMEZONE_BY_COUNTRY.get(str(country or "").upper(), ("America/Chicago", "US", "en"))
    return {"timezone": tz, "region": region, "language": lang}


def parse_proxy(proxy: str) -> Optional[Dict[str, str]]:
    """user:pass@host:port (or bare host:port) -> parts. None when unparseable."""
    if not proxy:
        return None
    clean = str(proxy).strip()
    clean = clean.replace("http://", "").replace("https://", "")
    if "@" not in clean:
        host, _, port = clean.rpartition(":")
        if not host or not port.isdigit():
            return None
        return {"host": host, "port": port, "username": "", "password": ""}
    auth, _, host_port = clean.rpartition("@")
    if ":" not in auth:
        return None
    username, _, password = auth.partition(":")
    host, _, port = host_port.rpartition(":")
    if not host or not port.isdigit():
        return None
    return {"host": host, "port": port, "username": username, "password": password}


def normalize_country(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) == 2:
        return text.upper()
    return COUNTRY_ALIASES.get(text.lower(), text.upper())


def _fetch_json(url: str, proxy: str, timeout: int) -> Dict[str, Any]:
    proxy_url = f"http://{proxy.strip().replace('http://', '').replace('https://', '')}"
    handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
    opener = urllib.request.build_opener(handler)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with opener.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def check_proxy(proxy: str, require_country: str = REQUIRE_COUNTRY,
                timeout: int = 20, skip_blocklist: bool = False) -> Dict[str, Any]:
    """Run the gate. `ok` is False if the proxy must not be used for signup."""
    started = time.time()
    result: Dict[str, Any] = {
        "ok": False,
        "proxy_host": "",
        "ip": "",
        "country": "",
        "isp": "",
        "city": "",
        "timezone": "",
        "region": "",
        "language": "",
        "latency_ms": 0,
        "reasons": [],
        "raw": {},
    }
    parsed = parse_proxy(proxy)
    if not parsed:
        result["reasons"].append("Proxy string is not user:pass@host:port or host:port")
        return result
    result["proxy_host"] = f"{parsed['host']}:{parsed['port']}"

    if not skip_blocklist:
        if any(blocked in parsed["host"].lower() for blocked in BLOCKED_HOSTS):
            result["reasons"].append(
                "Oxylabs Web Unblocker endpoint (unblock.oxylabs.io) - scraping IPs, "
                "not allowed for Meta signups"
            )
        if parsed["username"].lower().startswith(BLOCKED_USER_PREFIXES):
            result["reasons"].append(
                "Web Unblocker username (wu_...) - scraping product, not a residential exit"
            )

    # Primary: Oxylabs geo endpoint (same one the dashboard uses).
    try:
        data = _fetch_json("https://ip.oxylabs.io/location", proxy, timeout)
        result["raw"] = data
        result["ip"] = str(data.get("ip", "") or "")
        providers = data.get("providers") or {}
        dbip = providers.get("dbip") or {}
        result["country"] = normalize_country(dbip.get("country") or data.get("country"))
        result["isp"] = str(dbip.get("org_name") or data.get("isp") or "")
        result["city"] = str(dbip.get("city") or "")
    except Exception as exc:
        result["reasons"].append(f"Geo endpoint unreachable through proxy: {exc}")

    # Fallback: ipapi.co (also gives country_code).
    if not result["ip"] or not result["country"]:
        try:
            data = _fetch_json("https://ipapi.co/json/", proxy, timeout)
            result["raw"] = result["raw"] or data
            result["ip"] = result["ip"] or str(data.get("ip", "") or "")
            result["country"] = result["country"] or normalize_country(data.get("country_code"))
            result["isp"] = result["isp"] or str(data.get("org", "") or "")
            result["city"] = result["city"] or str(data.get("city", "") or "")
        except Exception as exc:
            result["reasons"].append(f"Fallback geo endpoint unreachable: {exc}")

    result["latency_ms"] = int((time.time() - started) * 1000)

    if result["country"]:
        derived = timezone_for_country(result["country"])
        result["timezone"] = derived["timezone"]
        result["region"] = derived["region"]
        result["language"] = derived["language"]

    if not result["ip"]:
        result["reasons"].append("No exit IP could be resolved through the proxy")
    
    # Country validation: if AUTO, extract from -cc-<country> in proxy username if present
    expected_country = require_country
    if str(expected_country or "").upper() in ("AUTO", "ANY", "NONE"):
        parsed_user = parsed.get("username", "") if parsed else ""
        cc_m = re.search(r"-cc-([a-z]{2})", parsed_user, flags=re.I)
        expected_country = cc_m.group(1).upper() if cc_m else None

    if expected_country and result["country"] and result["country"] != expected_country.upper():
        result["reasons"].append(
            f"Exit country is {result['country']}, expected {expected_country.upper()}"
        )
    if result["isp"] and any(h in result["isp"].lower() for h in DATACENTER_HINTS):
        result["reasons"].append(
            f"ISP looks like a datacenter/hosting network ({result['isp']})"
        )

    result["ok"] = not result["reasons"] and bool(result["ip"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Proxy gate for account creation")
    parser.add_argument("--proxy", required=True, help="user:pass@host:port")
    parser.add_argument("--require-country", default=REQUIRE_COUNTRY)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--skip-blocklist", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print raw JSON")
    args = parser.parse_args()

    result = check_proxy(args.proxy, args.require_country, args.timeout, args.skip_blocklist)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"proxy : {result['proxy_host']}")
        print(f"ip    : {result['ip'] or '-'}")
        print(f"country: {result['country'] or '-'}")
        print(f"isp   : {result['isp'] or '-'}")
        print(f"latency: {result['latency_ms']}ms")
        print(f"result: {'PASS' if result['ok'] else 'REJECT'}")
        for reason in result["reasons"]:
            print(f"  - {reason}")
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
