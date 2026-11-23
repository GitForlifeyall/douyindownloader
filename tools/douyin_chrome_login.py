#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/douyin_chrome_login.py
============================
Launches native Google Chrome with a persistent profile for Douyin,
opens Douyin (and your target video URL), lets you log in,
and automatically extracts and saves the cookies into
TikTokDownloader/Volume/settings.json.
"""

import argparse
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = PROJECT_ROOT / "output" / "profiles" / "douyin_chrome"
SETTINGS_JSON = PROJECT_ROOT / "TikTokDownloader" / "Volume" / "settings.json"


def main():
    parser = argparse.ArgumentParser(description="Douyin Real Chrome Login & Cookie Sync")
    parser.add_argument(
        "--url",
        type=str,
        default="https://www.douyin.com/",
        help="Optional Douyin video or page URL to open directly"
    )
    args = parser.parse_args()

    print("=" * 65)
    print("      DOUYIN GOOGLE CHROME LOGIN & COOKIE SYNC TOOL")
    print("=" * 65)
    print(f"[Chrome Profile] Storing session in: {PROFILE_DIR}")
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    target_url = args.url.strip() or "https://www.douyin.com/"

    print("[Browser] Launching Google Chrome...")
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",
            headless=False,
            viewport={"width": 1280, "height": 850},
            args=[
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        page = context.pages[0] if context.pages else context.new_page()

        print(f"[Browser] Navigating to: {target_url} ...")
        try:
            page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            print(f"[Navigation Note]: {e}")

        print("\n" + "=" * 65)
        print(">> GOOGLE CHROME IS NOW OPEN <<")
        print("   1. Log in to Douyin (via QR code, phone SMS, or password).")
        print("   2. Solve any slider/captcha if prompted.")
        print("   3. Once logged in and videos play, switch back here and")
        print("      PRESS ENTER to automatically save your cookies!")
        print("=" * 65 + "\n")

        try:
            input("Press ENTER once you are logged in (or Ctrl+C to abort)... ")
        except (KeyboardInterrupt, EOFError):
            print("\nAborted by user.")
            context.close()
            return

        print("\n[Cookies] Extracting cookies from Chrome session...")
        all_cookies = context.cookies([
            "https://www.douyin.com",
            "https://douyin.com",
            "https://live.douyin.com",
            "https://sso.douyin.com",
            "https://iesdouyin.com",
        ])

        douyin_cookies = [c for c in all_cookies if "douyin.com" in c.get("domain", "")]
        if not douyin_cookies:
            # Fallback to all cookies if domain matching was too strict
            douyin_cookies = all_cookies

        if not douyin_cookies:
            print("[Error] No cookies found. Please make sure Douyin was loaded in Chrome.")
            context.close()
            return

        # Deduplicate and build standard cookie string
        cookie_dict = {}
        for c in douyin_cookies:
            cookie_dict[c["name"]] = c["value"]

        cookie_str = "; ".join(f"{k}={v}" for k, v in cookie_dict.items())
        print(f"[Cookies] Successfully captured {len(cookie_dict)} unique cookie tokens.")

        key_tokens = ["passport_csrf_token", "ttwid", "sessionid", "sessionid_ss", "msToken", "odin_tt", "sid_guard"]
        found = [k for k in key_tokens if k in cookie_dict]
        print(f"[Cookies] Key security tokens present: {', '.join(found) if found else 'Basic tokens'}")

        # Backup to cookies.json
        backup_file = PROFILE_DIR / "cookies.json"
        backup_file.write_text(json.dumps(douyin_cookies, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[Backup] Saved full cookie list to: {backup_file}")

        # Update settings.json
        if SETTINGS_JSON.exists():
            try:
                # Read with utf-8-sig to tolerate BOM
                content = SETTINGS_JSON.read_text(encoding="utf-8-sig")
                settings_data = json.loads(content)
                settings_data["cookie"] = cookie_str
                SETTINGS_JSON.write_text(json.dumps(settings_data, indent=4, ensure_ascii=False), encoding="utf-8")
                print(f"[Settings] SUCCESS: Updated 'cookie' in {SETTINGS_JSON}")
            except Exception as err:
                print(f"[Settings Error]: {err}")
        else:
            print(f"[Settings Warning]: {SETTINGS_JSON} not found.")

        print("\n" + "=" * 65)
        print("✅ Douyin Chrome session saved and synchronized!")
        print("   You can now run:")
        print("   .\\.venv\\Scripts\\python.exe pipeline.py --url \"https://v.douyin.com/krWueVL7Uho/\" --tts elevenlabs")
        print("=" * 65 + "\n")

        context.close()


if __name__ == "__main__":
    main()
