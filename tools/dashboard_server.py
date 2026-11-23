#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/dashboard_server.py
=========================
FastAPI + WebSocket Desktop Server for Automated Account Creation
(Instagram, Facebook, Metricool) with Oxylabs Proxy & Outlook OAuth Integration.
"""

import os
import sys
import re
import json
import time
import asyncio
import secrets
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parent.parent
NODE_EXE = os.path.expandvars(r"%LOCALAPPDATA%\Programs\NodeJS\node22\node.exe")
PYTHON_EXE = str(PROJECT_ROOT / ".venv" / "Scripts" / "python.exe")
ARTIFACTS_DIR = PROJECT_ROOT / "tests" / "test_artifacts"
OUTPUT_DIR = PROJECT_ROOT / "output"

app = FastAPI(title="Multi-Platform Account Creator Dashboard")

# Global active process manager
active_process = None
active_task_name = None
connected_websockets: List[WebSocket] = []


def parse_account_string(raw: str) -> Dict[str, str]:
    parts = raw.strip().split("|")
    return {
        "email": parts[0].strip() if len(parts) > 0 else "",
        "password": parts[1].strip() if len(parts) > 1 else "",
        "refresh_token": parts[2].strip() if len(parts) > 2 else "",
        "client_id": parts[3].strip() if len(parts) > 3 else "9e5f94bc-e8a4-4e73-b8be-63364c29d753",
    }


def normalize_proxy(proxy_str: str) -> str:
    clean = proxy_str.strip().replace("http://", "").replace("https://", "")
    return clean


async def broadcast_log(line: str):
    ts = datetime.now().strftime("%H:%M:%S")
    formatted = f"[{ts}] {line}"
    print(formatted)
    for ws in list(connected_websockets):
        try:
            await ws.send_json({"type": "log", "message": formatted})
        except Exception:
            if ws in connected_websockets:
                connected_websockets.remove(ws)


@app.get("/", response_class=HTMLResponse)
async def get_index():
    html_file = Path(__file__).resolve().parent / "dashboard_ui.html"
    if html_file.exists():
        return HTMLResponse(content=html_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h2>Dashboard UI file not found.</h2>")


@app.get("/api/status")
async def get_system_status():
    return {
        "status": "ready",
        "node_exists": Path(NODE_EXE).exists(),
        "python_exists": Path(PYTHON_EXE).exists(),
        "active_task": active_task_name,
        "is_running": active_process is not None and active_process.returncode is None,
    }


@app.post("/api/test-proxy")
async def test_proxy(payload: Dict[str, Any]):
    proxy_str = payload.get("proxy", "").strip()
    if not proxy_str:
        raise HTTPException(status_code=400, detail="Proxy string is required")

    clean = proxy_str.replace("https://", "").replace("http://", "")
    proxy_url = f"http://{clean}"

    t0 = time.time()
    try:
        req = urllib.request.Request("https://ip.oxylabs.io/location")
        handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
        opener = urllib.request.build_opener(handler)
        with opener.open(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            elapsed = round((time.time() - t0) * 1000)
            
            ip = data.get("ip", "Unknown")
            providers = data.get("providers", {})
            dbip = providers.get("dbip", {})
            country = dbip.get("country", "Unknown")
            isp = dbip.get("org_name", "Unknown")
            city = dbip.get("city", "")

            return {
                "ok": True,
                "latency_ms": elapsed,
                "ip": ip,
                "country": country,
                "isp": isp,
                "city": city,
                "raw": data,
            }
    except Exception as e:
        elapsed = round((time.time() - t0) * 1000)
        return {
            "ok": False,
            "latency_ms": elapsed,
            "error": str(e),
        }


@app.post("/api/test-oauth")
async def test_oauth(payload: Dict[str, Any]):
    client_id = payload.get("client_id", "9e5f94bc-e8a4-4e73-b8be-63364c29d753").strip()
    refresh_token = payload.get("refresh_token", "").strip()

    if not refresh_token:
        raise HTTPException(status_code=400, detail="Refresh token is required")

    clean_cid = client_id[:-1] if (client_id.endswith("b") and len(client_id) == 36) else client_id

    try:
        token_url = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
        data = urllib.parse.urlencode({
            "client_id": clean_cid,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }).encode("utf-8")

        req = urllib.request.Request(token_url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            access_token = res.get("access_token")

        if not access_token:
            return {"ok": False, "error": "No access_token returned by Microsoft"}

        # Query recent inbox messages
        msg_req = urllib.request.Request(
            "https://outlook.office.com/api/v2.0/me/messages?$top=3&$select=Subject,ReceivedDateTime,From",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
        )
        with urllib.request.urlopen(msg_req, timeout=15) as msg_resp:
            msg_data = json.loads(msg_resp.read().decode("utf-8"))
            messages = msg_data.get("value", [])

        subjects = [m.get("Subject", "No Subject") for m in messages]
        return {
            "ok": True,
            "inbox_count": len(messages),
            "recent_subjects": subjects,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/start-task")
async def start_task(payload: Dict[str, Any]):
    global active_process, active_task_name

    if active_process is not None and active_process.returncode is None:
        raise HTTPException(status_code=400, detail="Another task is already running. Please stop it first.")

    platform = payload.get("platform", "instagram").lower()
    account_str = payload.get("account", "").strip()
    proxy_str = payload.get("proxy", "").strip()
    headless = payload.get("headless", False)

    if not account_str:
        raise HTTPException(status_code=400, detail="Account string is required")

    if platform not in ("facebook", "instagram", "metricool", "combo"):
        raise HTTPException(status_code=400, detail=f"Unsupported platform: {platform}")

    # Register or update identity store so the account gets a unified profile & pinned proxy
    store = _identity_store()
    email = account_str.split("|")[0].strip()
    rec = store.upsert(email, account_string=account_str, proxy=proxy_str)
    identity_id = rec["identity_id"]

    active_task_name = f"{platform.upper()} / {identity_id}"

    # Route through canonical run_identity runner with proxy gate and profile isolation
    cmd = [
        PYTHON_EXE,
        str(PROJECT_ROOT / "tools" / "run_identity.py"),
        "--identity", identity_id,
        "--platform", platform,
    ]
    if proxy_str:
        cmd.extend(["--proxy", proxy_str])
    if headless:
        cmd.append("--headless")
    if payload.get("fast"):
        cmd.append("--fast")

    # Start subprocess in background
    asyncio.create_task(run_subprocess_stream(cmd, platform))
    return {"ok": True, "message": f"Started {active_task_name}"}


async def run_subprocess_stream(cmd: List[str], platform: str, identity_id: Optional[str] = None):
    global active_process, active_task_name
    await broadcast_log(f"Starting {platform.upper()} task...")
    await broadcast_log(f"Command: {' '.join(cmd[:3])} ...")

    # Clear stale locks
    for p_dir in [OUTPUT_DIR / "profiles", OUTPUT_DIR / f"profiles {platform}", OUTPUT_DIR / f"profiles_{platform}"]:
        if p_dir.exists():
            for lk in p_dir.glob("**/parent.lock"):
                try: lk.unlink()
                except Exception: pass

    env = os.environ.copy()
    env["PATH"] = f"{PROJECT_ROOT / '.venv' / 'Scripts'};{env.get('PATH', '')}"

    try:
        active_process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(PROJECT_ROOT),
            env=env
        )

        while True:
            line = await active_process.stdout.readline()
            if not line:
                break
            decoded = line.decode("utf-8", errors="replace").rstrip()
            if decoded:
                await broadcast_log(decoded)

        await active_process.wait()
        rc = active_process.returncode
        status_msg = "SUCCESS" if rc == 0 else f"EXITED WITH CODE {rc}"
        await broadcast_log(f"Task finished: {status_msg}")
    except Exception as e:
        await broadcast_log(f"Process error: {e}")
    finally:
        if identity_id:
            try:
                store = _identity_store()
                rec = store.get(identity_id)
                current = ((rec or {}).get("platforms") or {}).get(platform) or {}
                if current.get("status") == "running":
                    store.set_platform(identity_id, platform, "aborted",
                                       note="dashboard: process ended without a terminal record")
            except Exception:
                pass
        active_process = None
        active_task_name = None
        for ws in list(connected_websockets):
            try:
                await ws.send_json({"type": "status", "is_running": False})
            except Exception:
                pass


@app.post("/api/stop-task")
async def stop_task():
    global active_process, active_task_name
    if active_process is not None and active_process.returncode is None:
        try:
            active_process.terminate()
            await asyncio.sleep(0.5)
            if active_process.returncode is None:
                active_process.kill()
        except Exception:
            pass

    # Kill any lingering browser subprocesses
    os.system("taskkill /F /IM camoufox.exe /IM firefox.exe 2>nul")
    
    active_process = None
    active_task_name = None
    await broadcast_log("Task stopped by user. Browser instances and lock files cleared.")
    return {"ok": True, "message": "Stopped task and cleaned locks"}


@app.get("/api/accounts")
async def get_registered_accounts():
    results = {"instagram": [], "facebook": [], "metricool": []}

    ig_file = OUTPUT_DIR / "instagram_registered_accounts.json"
    if ig_file.exists():
        try: results["instagram"] = json.loads(ig_file.read_text(encoding="utf-8"))
        except Exception: pass

    fb_file = OUTPUT_DIR / "facebook_registered_accounts.json"
    if fb_file.exists():
        try: results["facebook"] = json.loads(fb_file.read_text(encoding="utf-8"))
        except Exception: pass

    mc_file = OUTPUT_DIR / "metricool_registered_accounts.json"
    if mc_file.exists():
        try: results["metricool"] = json.loads(mc_file.read_text(encoding="utf-8"))
        except Exception: pass

    # Supabase cloud count
    results["supabase_total"] = None
    try:
        from tools.supabase_logger import get_supabase_config
        cfg = get_supabase_config()
        if cfg.get("enabled") and cfg.get("supabase_url") and cfg.get("supabase_key"):
            import urllib.request
            req = urllib.request.Request(
                f"{cfg['supabase_url']}/rest/v1/{cfg['table_name']}?select=id",
                headers={
                    "apikey": cfg["supabase_key"],
                    "Authorization": f"Bearer {cfg['supabase_key']}",
                    "Prefer": "count=exact"
                }
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                crange = resp.headers.get("Content-Range", "")
                if "/" in crange:
                    results["supabase_total"] = int(crange.split("/")[1])
                else:
                    data = json.loads(resp.read().decode("utf-8"))
                    results["supabase_total"] = len(data)
    except Exception:
        pass

    return results


@app.get("/api/latest-screenshot")
async def get_latest_screenshot():
    for f in ["ig_latest_live.png", "fb_latest_live.png", "ig_registration_success.png"]:
        p = ARTIFACTS_DIR / f
        if p.exists():
            return FileResponse(p, media_type="image/png")
    return Response(status_code=404)


@app.get("/api/supabase/config")
async def get_supabase_config_endpoint():
    try:
        from tools.supabase_logger import get_supabase_config
        return get_supabase_config()
    except Exception as e:
        return {"supabase_url": "", "supabase_key": "", "enabled": False, "error": str(e)}


@app.post("/api/supabase/config")
async def set_supabase_config_endpoint(payload: Dict[str, Any]):
    try:
        from tools.supabase_logger import set_supabase_config
        url = payload.get("supabase_url", "")
        key = payload.get("supabase_key", "")
        table = payload.get("table_name", "social_accounts")
        enabled = payload.get("enabled", True)
        ok = set_supabase_config(url, key, table, enabled)
        return {"ok": ok, "supabase_url": url, "table_name": table, "enabled": enabled}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/supabase/test")
async def test_supabase_endpoint():
    try:
        from tools.supabase_logger import log_to_supabase
        res = log_to_supabase({
            "platform": "TEST PING",
            "email": "test_verification@outlook.com",
            "username": "dashboard_test_agent",
            "password": "SamplePassword123!",
            "profile_url": "https://instagram.com/dashboard_test_agent",
            "full_mail_string": "test_verification@outlook.com|pass|token|clientId",
            "two_factor_secret": "JBSWY3DPEHPK3PXP",
            "backup_codes": ["1234 5678", "8765 4321"],
            "proxy": "http://pr.oxylabs.io:7777",
            "status": "TEST_VERIFIED",
            "details": {"source": "Dashboard Test Button"}
        })
        return res
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/supabase/check-email")
async def check_email_endpoint(email: str = Query(...)):
    """Checks if an email is already present in Supabase email_accounts table."""
    try:
        from tools.supabase_logger import check_email_exists
        res = check_email_exists(email)
        return res
    except Exception as e:
        return {"exists": False, "error": str(e)}


@app.post("/api/supabase/add-email")
async def add_email_endpoint(payload: Dict[str, Any]):
    """Adds or updates an email into Supabase email_accounts table with existence check."""
    try:
        from tools.supabase_logger import log_email_to_supabase
        res = log_email_to_supabase(payload)
        return res
    except Exception as e:
        return {"success": False, "error": str(e)}


# =========================================================================
# IDENTITY LAYER
# One identity = one browser profile = one proxy, shared by Metricool,
# Facebook and Instagram. Every run goes through tools/run_identity.py so
# the proxy is verified before a browser opens and a terminal record is
# always written.
# =========================================================================

def _identity_store():
    tools_dir = str(PROJECT_ROOT / "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    import identity_store  # noqa: E402
    return identity_store


def _proxy_check():
    tools_dir = str(PROJECT_ROOT / "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    import proxy_check  # noqa: E402
    return proxy_check


def _run_identity_module():
    tools_dir = str(PROJECT_ROOT / "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    import run_identity  # noqa: E402
    return run_identity


@app.get("/api/identities")
async def list_identities_endpoint():
    try:
        store = _identity_store()
        reaped = store.reap_stale_running()
        return {"ok": True, "identities": store.list_identities(), "summary": store.summary(),
                "reaped": reaped}
    except Exception as e:
        return {"ok": False, "error": str(e), "identities": [], "summary": {}}


@app.post("/api/identities/new")
async def create_identity_endpoint(payload: Dict[str, Any]):
    try:
        store = _identity_store()
        email = (payload.get("email") or "").strip()
        account = (payload.get("account") or "").strip()
        proxy = (payload.get("proxy") or "").strip()
        if not email and account:
            email = account.split("|")[0].strip()
        if not email:
            raise HTTPException(status_code=400, detail="email or account string is required")
        rec = store.new_identity(email, account, proxy)
        return {"ok": True, "identity": rec}
    except HTTPException:
        raise
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/identities/{identity_id}/proxy")
async def set_identity_proxy_endpoint(identity_id: str, payload: Dict[str, Any]):
    try:
        store = _identity_store()
        gate = _proxy_check()
        runmod = _run_identity_module()
        rec = store.get(identity_id) or store.find_by_email(identity_id)
        if not rec:
            raise HTTPException(status_code=404, detail="identity not found")
        proxy = (payload.get("proxy") or "").strip()
        if not proxy:
            raise HTTPException(status_code=400, detail="proxy is required")
        proxy = re.sub(r"^(https?|socks5)://", "", proxy, flags=re.I)

        require_country = (payload.get("require_country") or gate.REQUIRE_COUNTRY).upper()
        rotate = bool(payload.get("rotate", True))
        nonce = int(rec.get("session_nonce") or 0) + (1 if rotate else 0)
        effective = runmod.ensure_sticky_proxy(proxy, rec["identity_id"], require_country, nonce)

        if payload.get("verify", True):
            result = gate.check_proxy(effective, require_country)
            if not result["ok"]:
                store.set_proxy(rec["identity_id"], effective, result["ip"], result["country"],
                                result["isp"], verified=False)
                return {"ok": False, "rejected": True, "reasons": result["reasons"],
                        "ip": result["ip"], "country": result["country"], "isp": result["isp"]}
            store.set_proxy(rec["identity_id"], effective, result["ip"], result["country"],
                            result["isp"], verified=True, timezone=result["timezone"])
            if rotate:
                store.rotate_session(rec["identity_id"])
            return {"ok": True, "ip": result["ip"], "country": result["country"],
                    "isp": result["isp"], "timezone": result["timezone"],
                    "latency_ms": result["latency_ms"], "proxy": effective}
        store.set_proxy(rec["identity_id"], effective)
        return {"ok": True, "verified": False, "proxy": effective}
    except HTTPException:
        raise
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/identities/{identity_id}/rotate-session")
async def rotate_identity_session_endpoint(identity_id: str):
    try:
        store = _identity_store()
        rec = store.rotate_session(identity_id)
        return {"ok": True, "identity": rec}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/identities/{identity_id}/discard")
async def discard_identity_endpoint(identity_id: str, payload: Dict[str, Any] = None):
    try:
        store = _identity_store()
        payload = payload or {}
        rec = store.discard(identity_id, remove_profile=payload.get("remove_profile", True))
        return {"ok": True, "identity": rec}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/identities/{identity_id}/run")
async def run_identity_endpoint(identity_id: str, payload: Dict[str, Any]):
    global active_process, active_task_name

    if active_process is not None and active_process.returncode is None:
        raise HTTPException(status_code=400, detail="Another task is already running. Please stop it first.")

    platform = (payload.get("platform") or "facebook").lower()
    if platform not in ("facebook", "instagram", "metricool", "combo"):
        raise HTTPException(status_code=400, detail=f"Unsupported platform: {platform}")

    store = _identity_store()
    rec = store.get(identity_id) or store.find_by_email(identity_id)
    if not rec:
        raise HTTPException(status_code=404, detail="identity not found")

    active_task_name = f"{platform.upper()} / {rec['identity_id']}"
    cmd = [
        PYTHON_EXE,
        str(PROJECT_ROOT / "tools" / "run_identity.py"),
        "--identity", rec["identity_id"],
        "--platform", platform,
    ]
    if payload.get("proxy"):
        cmd.extend(["--proxy", str(payload["proxy"]).strip()])
    if payload.get("headless"):
        cmd.append("--headless")
    if payload.get("fast"):
        cmd.append("--fast")
    if payload.get("skip_2fa"):
        cmd.append("--skip-2fa")
    if payload.get("skip_page"):
        cmd.append("--skip-page")
    if payload.get("metricool_action"):
        cmd.extend(["--metricool-action", str(payload["metricool_action"])])
    if payload.get("rotate_session"):
        cmd.append("--rotate-session")

    asyncio.create_task(run_subprocess_stream(cmd, platform, rec["identity_id"]))
    return {"ok": True, "message": f"Started {active_task_name}", "identity_id": rec["identity_id"]}


@app.post("/api/run-fast-test")
async def run_fast_test(payload: Dict[str, Any] = None):
    global active_process, active_task_name
    if active_process is not None and active_process.returncode is None:
        raise HTTPException(status_code=400, detail="Another task is already running. Please stop it first.")

    payload = payload or {}
    proxy_str = payload.get("proxy", "").strip()
    headless = payload.get("headless", False)

    active_task_name = "FAST BENCHMARK (FB + Metricool)"
    node_binary = NODE_EXE if Path(NODE_EXE).exists() else "node"
    cmd = [
        node_binary,
        "--experimental-sqlite",
        str(PROJECT_ROOT / "tools" / "test_fb_metricool_fast.mjs"),
    ]
    if proxy_str:
        cmd.extend(["--proxy", proxy_str])
    elif payload.get("no_proxy"):
        cmd.append("--no-proxy")
    if headless:
        cmd.append("--headless")
    email = (payload.get("email") or "").strip()
    password = payload.get("password") or ""
    if email:
        cmd.extend(["--email", email])
    if password:
        cmd.extend(["--password", password])

    asyncio.create_task(run_subprocess_stream(cmd, "fast-test"))
    return {"ok": True, "message": f"Started {active_task_name}"}


@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    await websocket.accept()
    connected_websockets.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in connected_websockets:
            connected_websockets.remove(websocket)


def launch():
    port = 8950
    print("=" * 65)
    print("  MULTI-PLATFORM ACCOUNT CREATOR NATIVE DASHBOARD")
    print(f"  URL: http://127.0.0.1:{port}")
    print("=" * 65)

    # Launch Chrome as Native App Window if available
    chrome_app = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if Path(chrome_app).exists():
        import subprocess
        subprocess.Popen([
            chrome_app,
            f"--app=http://127.0.0.1:{port}",
            "--window-size=1280,880",
            "--window-position=100,50",
            "--disable-extensions"
        ])
    else:
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{port}")

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    launch()
