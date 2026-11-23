#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/flow_profile_manager.py
==============================
Multi-Profile Manager for Google Flow & FlowKit.

Capabilities:
- Spawns isolated Chrome profiles for multiple Google Flow accounts.
- Automatically mounts the FlowKit Chrome extension via --load-extension
  (ZERO manual extension loading or developer mode clicks required).
- Persists all cookies, tokens, and active Google sessions per profile.
- Manages dedicated API/WebSocket ports for parallel multi-account execution.
- Integrates seamlessly with dubbing_studio/flow_client.py for thumbnail generation.

Usage:
  # Create or launch profile 'account_1' and log in:
  python tools/flow_profile_manager.py launch account_1

  # Create a second profile for parallel account:
  python tools/flow_profile_manager.py launch account_2

  # List all configured profiles:
  python tools/flow_profile_manager.py list

  # Start FlowKit Python agent for a specific profile:
  python tools/flow_profile_manager.py agent account_1
"""

import sys
import os
import json
import argparse
import subprocess
import shutil
from pathlib import Path
from typing import Dict, Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FLOWKIT_DIR = PROJECT_ROOT / "tools" / "flowkit"
EXTENSION_DIR = FLOWKIT_DIR / "extension"
PROFILES_BASE = PROJECT_ROOT / "output" / "flow_profiles"
REGISTRY_FILE = PROFILES_BASE / "profiles_registry.json"

DEFAULT_CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]


def find_chrome() -> str:
    """Locate Google Chrome executable on Windows."""
    for p in DEFAULT_CHROME_PATHS:
        if os.path.exists(p):
            return p
    # Fallback to PATH lookup
    chrome_in_path = shutil.which("chrome")
    if chrome_in_path:
        return chrome_in_path
    raise FileNotFoundError("Google Chrome was not found in standard installation paths.")


def load_registry() -> Dict[str, Any]:
    """Load profiles registry."""
    if REGISTRY_FILE.exists():
        try:
            with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"profiles": {}, "default_profile": "account_1"}


def save_registry(registry: Dict[str, Any]) -> None:
    """Save profiles registry."""
    PROFILES_BASE.mkdir(parents=True, exist_ok=True)
    with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)


def prepare_extension_for_profile(profile_name: str, ws_port: int) -> Path:
    """
    Ensure the extension connects to the specific WebSocket port for this profile.
    If default 9333, use original extension directory.
    If custom port (multi-account parallel), create a tailored extension copy.
    """
    if ws_port == 9333:
        return EXTENSION_DIR

    # Isolated extension copy for parallel profile
    profile_ext_dir = PROFILES_BASE / profile_name / "extension"
    if not profile_ext_dir.exists():
        shutil.copytree(EXTENSION_DIR, profile_ext_dir)

    # Patch AGENT_WS_URL in background.js
    bg_js = profile_ext_dir / "background.js"
    if bg_js.exists():
        content = bg_js.read_text(encoding="utf-8")
        import re
        content = re.sub(
            r"const AGENT_WS_URL = 'ws://127\.0\.0\.1:\d+';",
            f"const AGENT_WS_URL = 'ws://127.0.0.1:{ws_port}';",
            content
        )
        bg_js.write_text(content, encoding="utf-8")

    return profile_ext_dir


def launch_profile(profile_name: str, url: str = "https://flow.google.com/") -> None:
    """Launch Chrome headed with the specified profile and auto-loaded FlowKit extension."""
    chrome_path = find_chrome()
    registry = load_registry()

    profile_dir = PROFILES_BASE / profile_name
    profile_dir.mkdir(parents=True, exist_ok=True)

    # Allocate ports
    profiles = registry.get("profiles", {})
    if profile_name not in profiles:
        index = len(profiles)
        ws_port = 9333 + index
        api_port = 8100 + index
        profiles[profile_name] = {
            "name": profile_name,
            "path": str(profile_dir),
            "ws_port": ws_port,
            "api_port": api_port,
            "flow_project_id": "",
        }
        registry["profiles"] = profiles
        save_registry(registry)
    else:
        ws_port = profiles[profile_name].get("ws_port", 9333)
        api_port = profiles[profile_name].get("api_port", 8100)

    ext_path = prepare_extension_for_profile(profile_name, ws_port)

    cmd = [
        chrome_path,
        f"--user-data-dir={profile_dir}",
        f"--load-extension={ext_path}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
        url,
    ]

    print("=" * 65)
    print(f"  Launching Google Flow Chrome Browser — Profile: [{profile_name}]")
    print(f"  Profile Directory: {profile_dir}")
    print(f"  FlowKit Extension: {ext_path} (Auto-Mounted)")
    print(f"  Agent WS Port: {ws_port} | API Port: {api_port}")
    print("=" * 65)
    print("Action Required:")
    print("1. Log in to your Google Account on the opened Chrome window.")
    print("2. Google Flow session, cookies, and extension state will be saved permanently.")
    print("3. You can close or leave the browser open anytime; your profile is fully preserved.")
    print("=" * 65)

    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)

    subprocess.Popen(cmd, creationflags=creation_flags, close_fds=True)


def list_profiles() -> None:
    """List all registered FlowKit profiles."""
    registry = load_registry()
    profiles = registry.get("profiles", {})
    print("=" * 65)
    print("  Configured Google Flow / FlowKit Profiles")
    print("=" * 65)
    if not profiles:
        print("  No profiles created yet. Run: python tools/flow_profile_manager.py launch account_1")
    for name, data in profiles.items():
        print(f"  - [{name}]")
        print(f"      Path: {data.get('path')}")
        print(f"      WS Port: {data.get('ws_port')} | API Port: {data.get('api_port')}")
        if data.get("flow_project_id"):
            print(f"      Project ID: {data.get('flow_project_id')}")
    print("=" * 65)


def run_agent(profile_name: str) -> None:
    """Run the FlowKit Python agent for this specific profile."""
    registry = load_registry()
    profiles = registry.get("profiles", {})
    if profile_name not in profiles:
        print(f"[Error] Profile '{profile_name}' not found. Create it first with 'launch {profile_name}'.")
        return

    data = profiles[profile_name]
    env = os.environ.copy()
    env["WS_PORT"] = str(data.get("ws_port", 9333))
    env["API_PORT"] = str(data.get("api_port", 8100))
    if data.get("flow_project_id"):
        env["FLOW_PROJECT_ID"] = data.get("flow_project_id")

    venv_py = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    py_exe = str(venv_py) if venv_py.exists() else sys.executable

    print(f"Starting FlowKit Agent for profile [{profile_name}] on port {env['API_PORT']}...")
    subprocess.run([py_exe, "-m", "agent.main"], cwd=str(FLOWKIT_DIR), env=env)


def main():
    parser = argparse.ArgumentParser(description="Google Flow Multi-Profile Manager")
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Launch command
    launch_parser = subparsers.add_parser("launch", help="Launch a Chrome profile with FlowKit extension")
    launch_parser.add_argument("name", nargs="?", default="account_1", help="Profile name (e.g. account_1, account_2)")
    launch_parser.add_argument("--url", default="https://flow.google.com/", help="Initial URL")

    # List command
    subparsers.add_parser("list", help="List all configured profiles")

    # Agent command
    agent_parser = subparsers.add_parser("agent", help="Run FlowKit backend agent for a profile")
    agent_parser.add_argument("name", nargs="?", default="account_1", help="Profile name")

    args = parser.parse_args()

    if args.command == "launch" or not args.command:
        profile_name = getattr(args, "name", "account_1") or "account_1"
        launch_profile(profile_name, getattr(args, "url", "https://flow.google.com/"))
    elif args.command == "list":
        list_profiles()
    elif args.command == "agent":
        run_agent(args.name)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
