#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Autonomous Overnight Batch Dubbing Runner
=========================================
Processes Batches 1-4 in English (plus conditional Batch 4 Hindi if ElevenLabs quota remains),
transfers `Curious Cinefile` to `I:\\My Drive\\douyin\\channel pending movies`, monitors GPU temperature,
reclaims local storage after every verified Drive upload, maintains checkpoints across crashes/restarts,
and logs operational decisions in `decisions.md`.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

if sys.platform == "win32":
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

from dubbing_studio.env_loader import configure_runtime_environment

configure_runtime_environment()

from dubbing_studio.downloader import DownloaderAPI
from dubbing_studio.key_pool import (
    get_active_elevenlabs_keys,
    get_active_gemini_keys,
    get_active_sarvam_keys,
)
from dubbing_studio.block_aligner import get_media_duration
from dubbing_studio.pipeline import DubbingPipeline
from dubbing_studio.tts_elevenlabs import ElevenLabsTTS

DRIVE_PENDING_ROOT = Path(r"I:\My Drive\douyin\channel pending movies")
STATE_PATH = ROOT_DIR / "output" / "pending_batches_state.json"
DECISIONS_PATH = ROOT_DIR / "decisions.md"

GLOBAL_MAX_DURATION_SEC = 900.0
BATCH4_MAX_DURATION_SEC = 180.0
GPU_PAUSE_TEMP_C = 82
GPU_RESUME_TEMP_C = 68
MIN_FREE_DISK_GB = 3.5
CRITICAL_FREE_DISK_GB = 2.5

BATCHES: List[Dict[str, Any]] = [
    {
        "name": "batch_1",
        "lang": "English",
        "ratio": "square",
        "movie": True,
        "disable_bgm": False,
        "watermark": None,
        "preferred_tts": "elevenlabs",
        "voice": "roger",
        "max_duration_sec": GLOBAL_MAX_DURATION_SEC,
        "allow_tts_fallback": True,
        "urls": [
            "https://www.douyin.com/video/7576560382999842048",
            "https://www.douyin.com/video/7558092762407652668",
            "https://www.douyin.com/video/7552333278879943977",
            "https://www.douyin.com/video/7700506430952000794",
            "https://www.douyin.com/video/7690119603388747054",
            "https://www.douyin.com/video/7687911297102433545",
            "https://www.douyin.com/video/7663400256544967971",
            "https://www.douyin.com/video/7650042787622063410",
            "https://www.douyin.com/video/7638896631034793222",
            "https://www.douyin.com/video/7637426654624664882",
            "https://www.douyin.com/video/7636685216622431515",
            "https://www.douyin.com/video/7633341231874985254",
            "https://www.douyin.com/video/7627411897393990962",
            "https://www.douyin.com/video/7617475615813405995",
            "https://www.douyin.com/video/7614342512794144054",
            "https://www.douyin.com/video/7602506687974493481",
            "https://www.douyin.com/video/7601803473167977747",
            "https://www.douyin.com/video/7601538506451586354",
            "https://www.douyin.com/video/7601513112486939950",
            "https://www.douyin.com/video/7601419240322780459",
            "https://www.douyin.com/video/7597323636726451462",
            "https://www.douyin.com/video/7594021583920909604",
            "https://www.douyin.com/video/7580584886294170906",
            "https://www.douyin.com/video/7580375223619308843",
            "https://www.douyin.com/video/7580195085728501018",
            "https://www.douyin.com/video/7576557959610633512",
            "https://www.douyin.com/video/7575366231428042024",
            "https://www.douyin.com/video/7572412079865384232",
            "https://www.douyin.com/video/7021875636457393415",
        ],
    },
    {
        "name": "batch_2",
        "lang": "English",
        "ratio": "square",
        "movie": True,
        "disable_bgm": True,
        "watermark": None,
        "preferred_tts": "elevenlabs",
        "voice": "roger",
        "max_duration_sec": GLOBAL_MAX_DURATION_SEC,
        "allow_tts_fallback": True,
        "urls": [
            "https://www.douyin.com/video/7583584749948587318",
            "https://www.douyin.com/video/7526907363945762089",
            "https://www.douyin.com/video/7481487006862691596",
            "https://www.douyin.com/video/7703802227953028392",
            "https://www.douyin.com/video/7701276765238398242",
            "https://www.douyin.com/video/7700092361329642806",
            "https://www.douyin.com/video/7698699002044370195",
            "https://www.douyin.com/video/7696471671133228314",
            "https://www.douyin.com/video/7695308731264879926",
            "https://www.douyin.com/video/7693518333043363082",
            "https://www.douyin.com/video/7688526892483218751",
            "https://www.douyin.com/video/7685173283473362230",
            "https://www.douyin.com/video/7683369109643398454",
            "https://www.douyin.com/video/7673048472945216774",
            "https://www.douyin.com/video/7670765996692524326",
            "https://www.douyin.com/video/7668936671752146228",
            "https://www.douyin.com/video/7667568748508859683",
            "https://www.douyin.com/video/7666433316555394354",
            "https://www.douyin.com/video/7664202530867432767",
            "https://www.douyin.com/video/7663814009967168768",
            "https://www.douyin.com/video/7663074481266642211",
            "https://www.douyin.com/video/7661649389630360868",
            "https://www.douyin.com/video/7661240368716909887",
            "https://www.douyin.com/video/7659908768234229034",
            "https://www.douyin.com/video/7654550991211105576",
            "https://www.douyin.com/video/7600664173927894312",
            "https://www.douyin.com/video/7539500292321152299",
            "https://www.douyin.com/video/7533151373181865259",
            "https://www.douyin.com/video/7531660530092690707",
            "https://www.douyin.com/video/7513577464669408548",
            "https://www.douyin.com/video/7467801821835267354",
            "https://www.douyin.com/video/7467029510387436827",
            "https://www.douyin.com/video/7460050084227599656",
        ],
    },
    {
        "name": "batch_3",
        "lang": "English",
        "ratio": "reel",
        "movie": True,
        "disable_bgm": False,
        "watermark": "rewind the scene",
        "preferred_tts": "google",
        "voice": "Ludo",
        "max_duration_sec": GLOBAL_MAX_DURATION_SEC,
        "allow_tts_fallback": True,
        "urls": [
            "https://www.douyin.com/video/7703767456715738383",
            "https://www.douyin.com/video/7703408110462930195",
            "https://www.douyin.com/video/7702358992898624777",
            "https://www.douyin.com/video/7702285251369100386",
            "https://www.douyin.com/video/7700137803027336484",
            "https://www.douyin.com/video/7700134095241661723",
            "https://www.douyin.com/video/7699684580579708214",
            "https://www.douyin.com/video/7696359760068660531",
            "https://www.douyin.com/video/7693713892094781032",
            "https://www.douyin.com/video/7693139739121899362",
            "https://www.douyin.com/video/7692665739706109235",
            "https://www.douyin.com/video/7692631558695570715",
            "https://www.douyin.com/video/7692291389383511305",
            "https://www.douyin.com/video/7692049248078056731",
            "https://www.douyin.com/video/7690029371688246095",
            "https://www.douyin.com/video/7689667253188985443",
            "https://www.douyin.com/video/7689666106118774863",
            "https://www.douyin.com/video/7688930970183708623",
            "https://www.douyin.com/video/7688569324269061539",
            "https://www.douyin.com/video/7688344245144568739",
            "https://www.douyin.com/video/7687503357933896628",
            "https://www.douyin.com/video/7686688800656243171",
            "https://www.douyin.com/video/7683492820372288163",
            "https://www.douyin.com/video/7681885306203972736",
            "https://www.douyin.com/video/7681525798243242466",
            "https://www.douyin.com/video/7656381434956893491",
            "https://www.douyin.com/video/7574358359793470747",
            "https://www.douyin.com/video/7565501992445988132",
            "https://www.douyin.com/video/7562118863102545192",
            "https://www.douyin.com/video/7558757776005106963",
            "https://www.douyin.com/video/7558009917358050595",
            "https://www.douyin.com/video/7557629824366431503",
            "https://www.douyin.com/video/7557293065363410191",
            "https://www.douyin.com/video/7557007734948875560",
            "https://www.douyin.com/video/7556933271393684776",
            "https://www.douyin.com/video/7556155622258019625",
            "https://www.douyin.com/video/7555508609401048363",
            "https://www.douyin.com/video/7548779115441065243",
        ],
    },
    {
        "name": "batch_4",
        "lang": "English",
        "ratio": "reel",
        "movie": True,
        "disable_bgm": False,
        "watermark": "CineCraze Alex",
        "preferred_tts": "google",
        "voice": "Puck",
        "max_duration_sec": BATCH4_MAX_DURATION_SEC,
        "allow_tts_fallback": True,
        "urls": [
            "https://www.douyin.com/video/7700949659867287680",
            "https://www.douyin.com/video/7686461113689538959",
            "https://www.douyin.com/video/7683377800636654912",
            "https://www.douyin.com/video/7676419244507233448",
            "https://www.douyin.com/video/7675663324675098722",
            "https://www.douyin.com/video/7639279024359516294",
            "https://www.douyin.com/video/7635958636409736874",
            "https://www.douyin.com/video/7609896963744040518",
            "https://www.douyin.com/video/7602489816723219190",
            "https://www.douyin.com/video/7549054694031707433",
            "https://www.douyin.com/video/7326476829580217610",
            "https://www.douyin.com/video/7295704044557913395",
            "https://www.douyin.com/video/7217405407197744445",
            "https://www.douyin.com/video/7204041576731987203",
            "https://www.douyin.com/video/7195506002291117368",
            "https://www.douyin.com/video/7167698475075865864",
            "https://www.douyin.com/video/7082662747804044577",
            "https://www.douyin.com/video/7037750889993604383",
            "https://www.douyin.com/video/6992150966510439683",
            "https://www.douyin.com/video/6917535612803370254",
            "https://www.douyin.com/video/6890468791952674063",
            "https://www.douyin.com/video/6883782738768350475",
            "https://www.douyin.com/video/6868556189324610820",
            "https://www.douyin.com/video/6867432469684129024",
            "https://www.douyin.com/video/6860758867635162368",
            "https://www.douyin.com/video/6832952221571796239",
            "https://www.douyin.com/video/6816995082021965056",
            "https://www.douyin.com/video/6815098979001421067",
            "https://www.douyin.com/video/6813296182987738383",
            "https://www.douyin.com/video/6791761994581069056",
            "https://www.douyin.com/video/6785470335933320463",
            "https://www.douyin.com/video/6779883649924893967",
            "https://www.douyin.com/video/6766538332257209604",
            "https://www.douyin.com/video/6765041952938380547",
            "https://www.douyin.com/video/6755765674292841732",
        ],
    },
]


def log_decision(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"- **[{ts}]** {msg}"
    print(f"[DECISION] {msg}", flush=True)
    with open(DECISIONS_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_state() -> Dict[str, Any]:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"batches": {}}


def save_state(state: Dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATE_PATH)


def extract_video_id(url: str) -> str:
    m = re.search(r"/video/(\d+)", url)
    return m.group(1) if m else url.rstrip("/").split("/")[-1]


def query_gpu_temp() -> Optional[int]:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).decode("utf-8", errors="ignore").strip().splitlines()
        if out:
            return int(out[0].strip())
    except Exception:
        pass
    return None


def gpu_thermal_guard() -> None:
    temp = query_gpu_temp()
    if temp is None or temp < GPU_PAUSE_TEMP_C:
        return
    log_decision(f"GPU Thermal Pause: temperature reached {temp}C (>= {GPU_PAUSE_TEMP_C}C). Waiting until < {GPU_RESUME_TEMP_C}C.")
    for _ in range(30):
        time.sleep(20)
        cur = query_gpu_temp()
        print(f"  [Thermal Guard] Current GPU temp: {cur}C", flush=True)
        if cur is None or cur < GPU_RESUME_TEMP_C:
            log_decision(f"GPU Thermal Resume: temperature cooled to {cur}C.")
            return
    log_decision("GPU Thermal Guard timeout (10m elapsed); resuming cautious execution.")


def cleanup_temp_artifacts(extra_paths: Optional[List[Path]] = None) -> float:
    freed = 0
    out_dir = ROOT_DIR / "output"
    temp_dirs = [
        out_dir / "clean_videos",
        out_dir / "audio_stems",
        out_dir / "extracted_music",
        out_dir / "frame_analysis",
        out_dir / "test_short_out",
        out_dir / "experimental",
    ]
    for bdir in out_dir.glob("batch_*"):
        if bdir.is_dir():
            for sub in ("clean_videos", "audio_stems", "extracted_music", "frame_analysis"):
                temp_dirs.append(bdir / sub)
    for d in temp_dirs:
        if d.exists():
            for p in list(d.rglob("*")):
                if p.is_file():
                    try:
                        sz = p.stat().st_size
                        p.unlink()
                        freed += sz
                    except Exception:
                        pass
            for p in sorted(d.rglob("*"), reverse=True):
                if p.is_dir():
                    try:
                        p.rmdir()
                    except Exception:
                        pass

    for pattern in ("block_align_*", "stems_*"):
        for p in out_dir.glob(pattern):
            try:
                if p.is_dir():
                    sz = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
                    shutil.rmtree(p, ignore_errors=True)
                    freed += sz
            except Exception:
                pass

    if extra_paths:
        for p in extra_paths:
            if p and p.exists() and p.is_file():
                try:
                    sz = p.stat().st_size
                    p.unlink()
                    freed += sz
                except Exception:
                    pass

    return freed / (1024 * 1024)


def storage_guard() -> None:
    c_free_gb = shutil.disk_usage("C:\\").free / (1024 ** 3)
    if c_free_gb >= MIN_FREE_DISK_GB:
        return

    reclaimed_mb = cleanup_temp_artifacts()
    c_free_gb = shutil.disk_usage("C:\\").free / (1024 ** 3)
    msg = f"Storage Guard triggered (low space). Cleaned temp artifacts ({reclaimed_mb:.1f} MB). Free C: = {c_free_gb:.2f} GB."

    if c_free_gb < CRITICAL_FREE_DISK_GB:
        out_dir = ROOT_DIR / "output"
        # Emergency: remove stale standalone root test MP4s in output/ (keep input/ & metadata)
        extra_freed = 0
        for mp4 in out_dir.glob("*.mp4"):
            try:
                sz = mp4.stat().st_size
                mp4.unlink()
                extra_freed += sz
            except Exception:
                pass
        for stale_dir in (out_dir / "老树怪谈", out_dir / "input"):
            if stale_dir.exists():
                for f in stale_dir.rglob("*"):
                    if f.is_file() and f.suffix.lower() in (".mp4", ".wav", ".mp3"):
                        try:
                            sz = f.stat().st_size
                            f.unlink()
                            extra_freed += sz
                        except Exception:
                            pass
        c_free_gb = shutil.disk_usage("C:\\").free / (1024 ** 3)
        msg += f" Emergency root-output cleanup freed {extra_freed/(1024**2):.1f} MB -> Free C: = {c_free_gb:.2f} GB."

    log_decision(msg)

    # Give DriveFS brief breathing room to drain queued uploads if still tight
    if c_free_gb < MIN_FREE_DISK_GB:
        print(f"  [Storage Guard] Waiting up to 60s for Google Drive cache drain (free={c_free_gb:.2f} GB)...", flush=True)
        for _ in range(4):
            time.sleep(15)
            if shutil.disk_usage("C:\\").free / (1024 ** 3) >= MIN_FREE_DISK_GB:
                break


def clamp_youtube_metadata(meta: Dict[str, Any], fallback_title: str, target_lang: str, movie: bool = False) -> Dict[str, Any]:
    title = str((meta or {}).get("title") or "").strip()
    if movie:
        title = re.sub(r"\s*\(\s*3d\s+animation[^\)]*\)", "", title, flags=re.IGNORECASE).strip()
        if not title:
            title = f"{fallback_title} #shorts"
    else:
        if not title:
            tag = "3D Animation In English" if target_lang.lower().startswith("en") else "3D Animation In Hindi"
            title = f"{fallback_title} ({tag}) #shorts"

    desc = str((meta or {}).get("description") or "").strip()
    if movie and not desc.lower().startswith("comment"):
        desc = f'Comment "MOVIE" for the movie name! 🍿🎬\n\n{desc}'.strip()

    # Strictly < 5000 chars per AGENTS.md (target cap 4940)
    if len(desc) >= 4940:
        parts = desc.split("\n\nDisclaimer", 1)
        kw_block = parts[0]
        disclaimer = ("\n\nDisclaimer" + parts[1]) if len(parts) > 1 else ""
        budget = 4900 - len(disclaimer)
        if budget > 100 and len(kw_block) > budget:
            kws = [k.strip() for k in kw_block.split(",") if k.strip()]
            trimmed: List[str] = []
            cur_len = 0
            for k in kws:
                add_len = len(k) + (2 if trimmed else 0)
                if cur_len + add_len > budget:
                    break
                trimmed.append(k)
                cur_len += add_len
            desc = ", ".join(trimmed) + disclaimer
        if len(desc) >= 4940:
            desc = desc[:4935].rstrip(", ")

    raw_tags = list((meta or {}).get("tags") or [])
    clean_tags = [str(t).strip() for t in raw_tags if str(t).strip()]
    if movie:
        defaults = ["movie", "movie explanation", "movie recap", "movies", "ending explained"]
        for d in defaults:
            if len(clean_tags) >= 5:
                break
            if d not in clean_tags:
                clean_tags.append(d)
        clean_tags = clean_tags[:5]
    else:
        defaults = ["Animation", "3D Explained", "Movie Recap"] if target_lang.lower().startswith("en") else ["Animation", "3D Explained", "Hindi Story"]
        for d in defaults:
            if len(clean_tags) >= 3:
                break
            if d not in clean_tags:
                clean_tags.append(d)
        clean_tags = clean_tags[:3]

    return {
        "title": title,
        "description": desc,
        "tags": clean_tags,
    }


def write_sorted_batch_metadata(batch_name: str, batch_state: Dict[str, Any], drive_folder: Path) -> None:
    videos_out: List[Dict[str, Any]] = []
    entries = list((batch_state.get("items") or {}).values())
    completed = [e for e in entries if e.get("status") == "completed" and e.get("metadata")]
    # Sort deterministically by Title so metadata.json & Drive explorer alphabetical listing match cleanly
    completed.sort(key=lambda e: (e["metadata"].get("title", "").lower(), e.get("video_id", "")))

    for e in completed:
        videos_out.append(e["metadata"])

    payload = {
        "number_of_videos": len(videos_out),
        "videos": videos_out,
    }
    json_text = json.dumps(payload, indent=2, ensure_ascii=False)

    local_meta = ROOT_DIR / "output" / batch_name / "metadata.json"
    local_meta.parent.mkdir(parents=True, exist_ok=True)
    local_meta.write_text(json_text, encoding="utf-8")

    drive_meta = drive_folder / "metadata.json"
    drive_folder.mkdir(parents=True, exist_ok=True)
    drive_meta.write_text(json_text, encoding="utf-8")


def pick_current_tts_engine(preferred: str = "elevenlabs", allow_fallback: bool = True) -> Optional[str]:
    pref = str(preferred or "elevenlabs").lower()
    if pref in ("google", "gemini", "flash"):
        if get_active_gemini_keys():
            return "google"
        # User requirement: If Google Flash finishes, fall back to ElevenLabs
        if get_active_elevenlabs_keys():
            return "elevenlabs"
        if not allow_fallback:
            return None
        if get_active_sarvam_keys():
            return "sarvam"
        return "kokoro"
    else:  # elevenlabs preferred
        if get_active_elevenlabs_keys():
            return "elevenlabs"
        if not allow_fallback:
            return None
        if get_active_gemini_keys():
            return "google"
        if get_active_sarvam_keys():
            return "sarvam"
        return "kokoro"


def check_live_elevenlabs_quota() -> Dict[str, Any]:
    """Query live subscription quota for every active non-blocked ElevenLabs key."""
    import requests

    keys = get_active_elevenlabs_keys()
    total_remaining = 0
    working_keys = 0
    details: List[Dict[str, Any]] = []
    for k in keys:
        try:
            r = requests.get(
                "https://api.elevenlabs.io/v1/user/subscription",
                headers={"xi-api-key": k},
                timeout=10,
            )
            if r.status_code == 200:
                d = r.json()
                used = int(d.get("character_count", 0))
                limit = int(d.get("character_limit", 0))
                rem = max(0, limit - used)
                total_remaining += rem
                if rem > 0:
                    working_keys += 1
                details.append({"key_prefix": k[:8], "remaining": rem, "limit": limit})
            else:
                details.append({"key_prefix": k[:8], "status": r.status_code})
        except Exception as e:
            details.append({"key_prefix": k[:8], "error": str(e)[:80]})
    return {
        "active_keys_count": len(keys),
        "working_keys_with_chars": working_keys,
        "total_remaining_chars": total_remaining,
        "details": details,
    }


def find_cached_local_mp4(batch_input_dir: Path, vid_id: str) -> Optional[Path]:
    if vid_id == "7576560382999842048":
        mp4s = sorted(batch_input_dir.glob("2025-11-25 16.30.00-Video-*.mp4"))
        if mp4s:
            return mp4s[0]
    matches = sorted(batch_input_dir.glob(f"*{vid_id}*.mp4"))
    return matches[0] if matches else None


def run_batch(
    batch: Dict[str, Any],
    state: Dict[str, Any],
    downloader: DownloaderAPI,
    pipeline: DubbingPipeline,
) -> bool:
    """Process all URLs in one batch. Returns False only if strict-ElevenLabs batch stopped on exhaustion."""
    bname = batch["name"]
    drive_folder = DRIVE_PENDING_ROOT / bname
    drive_folder.mkdir(parents=True, exist_ok=True)
    batch_input_dir = ROOT_DIR / "input" / f"pending_{bname}"
    batch_input_dir.mkdir(parents=True, exist_ok=True)

    bstate = state["batches"].setdefault(bname, {"items": {}})
    items = bstate["items"]

    urls = batch["urls"]
    max_dur = float(batch["max_duration_sec"])
    last_logged_engine = None
    state_lock = threading.Lock()

    prefetch_executor = ThreadPoolExecutor(max_workers=1)
    upload_executor = ThreadPoolExecutor(max_workers=1)
    prefetch_cache: Dict[str, Future] = {}
    upload_future: Optional[Future] = None

    def _is_already_done(u: str) -> bool:
        v_id = extract_video_id(u)
        with state_lock:
            ex = items.get(v_id)
        if not ex:
            return False
        if ex.get("status") == "skipped_duration":
            return True
        if ex.get("status") == "completed":
            df = drive_folder / str(ex.get("drive_filename") or "")
            return df.exists() and df.stat().st_size > 10000
        return False

    def _prefetch_job(target_url: str, target_vid_id: str):
        p_dur: Optional[float] = None
        try:
            p_dur = downloader.probe_video_duration(target_url)
        except Exception as pe:
            print(f"  [Prefetch Probe Warning] {target_vid_id}: {pe}", flush=True)
        if p_dur is not None and p_dur > max_dur:
            return ("skipped_duration", p_dur, None, None)

        dl_p = find_cached_local_mp4(batch_input_dir, target_vid_id)
        dl_err = None
        if not dl_p:
            for dl_try in range(3):
                try:
                    dl_p = downloader.download_video(target_url, output_dir=batch_input_dir)
                    if dl_p and dl_p.exists():
                        break
                except Exception as e:
                    dl_err = e
                    print(f"  [Prefetch Retry {dl_try+1}/3] {target_vid_id}: {e}", flush=True)
                    time.sleep(3 * (dl_try + 1))

        if dl_p and dl_p.exists():
            try:
                from dubbing_studio.pipeline import sanitize_filename as clean_video_filename
                from dubbing_studio.movie_crop import process_movie_crop_video
                clean_s = clean_video_filename(dl_p.stem)
                clean_dir = ROOT_DIR / "output" / bname / "clean_videos"
                clean_dir.mkdir(parents=True, exist_ok=True)
                ratio_norm = str(batch.get("ratio") or "reel").lower()
                ratio_sfx = f"_{ratio_norm}" if ratio_norm != "reel" else ""
                spec_cand = clean_dir / f"{clean_s}_moviecrop{ratio_sfx}_spec.json"
                if not spec_cand.exists() and batch.get("movie"):
                    print(f"  [Prefetch Pre-process] Running background OCR crop detection for {target_vid_id}...", flush=True)
                    process_movie_crop_video(
                        input_video_path=dl_p,
                        output_video_path=spec_cand.with_suffix(".mp4"),
                        output_ratio=ratio_norm,
                        defer_encode=True
                    )
            except Exception as pe:
                print(f"  [Prefetch Pre-process Warning] {target_vid_id}: {pe}", flush=True)

        return ("ok" if (dl_p and dl_p.exists()) else "failed", p_dur, dl_p, dl_err)

    def _schedule_next_prefetch(from_idx: int) -> None:
        for nxt_u in urls[from_idx:]:
            nxt_id = extract_video_id(nxt_u)
            if nxt_id not in prefetch_cache and not _is_already_done(nxt_u):
                print(f"  [Prefetch Async] Queueing background download for next clip: {nxt_id}", flush=True)
                prefetch_cache[nxt_id] = prefetch_executor.submit(_prefetch_job, nxt_u, nxt_id)
                break

    def _upload_and_record(
        u_vid_id: str,
        u_url: str,
        u_actual_dur: float,
        u_final_local: Path,
        u_out_dur: float,
        u_clamped_meta: Dict[str, Any],
        u_used_eng: str,
        u_dest_name: str,
        u_dest_drive: Path,
    ) -> None:
        copied_ok = False
        copy_err = None
        for cp_try in range(3):
            try:
                drive_folder.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(u_final_local), str(u_dest_drive))
                if (
                    u_dest_drive.exists()
                    and u_dest_drive.stat().st_size == u_final_local.stat().st_size
                    and u_dest_drive.stat().st_size > 10000
                ):
                    copied_ok = True
                    break
            except OSError as oe:
                copy_err = oe
                log_decision(f"{bname}: Drive copy OSError on {u_vid_id} ({oe}); running storage guard & retrying ({cp_try+1}/3).")
                storage_guard()
                time.sleep(15)
            except Exception as ce:
                copy_err = ce
                time.sleep(5)

        if not copied_ok:
            log_decision(f"{bname} FAILED Drive copy {u_vid_id}: {copy_err}. Keeping local file: {u_final_local}")
            with state_lock:
                items[u_vid_id] = {
                    "url": u_url,
                    "video_id": u_vid_id,
                    "status": "failed_drive_copy",
                    "local_final": str(u_final_local),
                    "error": str(copy_err)[:300],
                }
                save_state(state)
            return

        with state_lock:
            items[u_vid_id] = {
                "url": u_url,
                "video_id": u_vid_id,
                "status": "completed",
                "orig_duration_sec": round(u_actual_dur, 2),
                "final_duration_sec": round(u_out_dur, 2),
                "tts_engine": u_used_eng,
                "drive_filename": u_dest_name,
                "metadata": u_clamped_meta,
            }
            save_state(state)
            write_sorted_batch_metadata(bname, bstate, drive_folder)

        freed_local = 0.0
        try:
            if u_final_local.exists():
                freed_local = u_final_local.stat().st_size / (1024 * 1024)
                u_final_local.unlink()
        except Exception:
            pass
        print(
            f"  [OK Async Upload] -> {u_dest_drive.name} (orig={u_actual_dur:.1f}s -> out={u_out_dur:.1f}s, "
            f"engine={u_used_eng}, freed={freed_local:.1f} MB)",
            flush=True,
        )

    print(f"\n{'='*72}", flush=True)
    print(f" STARTING {bname.upper()} | {len(urls)} URLs | lang={batch['lang']} | ratio={batch['ratio']} | "
          f"bgm={'OFF' if batch['disable_bgm'] else 'ON'} | watermark={batch['watermark']!r} | max_dur={max_dur:.0f}s", flush=True)
    print(f" Drive Target: {drive_folder}", flush=True)
    print(f"{'='*72}\n", flush=True)

    try:
      for idx, url in enumerate(urls, 1):
        vid_id = extract_video_id(url)
        with state_lock:
            existing = items.get(vid_id)
        if existing:
            st = existing.get("status")
            if st == "skipped_duration":
                print(f"[{bname} {idx}/{len(urls)}] Skip (already filtered duration={existing.get('orig_duration_sec')}s): {vid_id}", flush=True)
                continue
            if st == "completed":
                df = drive_folder / str(existing.get("drive_filename") or "")
                if df.exists() and df.stat().st_size > 10000:
                    print(f"[{bname} {idx}/{len(urls)}] Skip (already completed in Drive: {df.name}): {vid_id}", flush=True)
                    continue

        gpu_thermal_guard()
        storage_guard()

        chosen_engine = pick_current_tts_engine(preferred=batch.get("preferred_tts", "elevenlabs"), allow_fallback=batch["allow_tts_fallback"])
        if chosen_engine is None:
            log_decision(f"{bname}: {batch.get('preferred_tts', 'elevenlabs')} quota exhausted and no fallback available; stopping {bname} at {idx}/{len(urls)}.")
            return False

        if chosen_engine != last_logged_engine:
            log_decision(f"{bname} item {idx}/{len(urls)} ({vid_id}): active TTS engine set to `{chosen_engine}`.")
            last_logged_engine = chosen_engine
        pipeline.tts_engine = chosen_engine

        # Step A + B: Use prefetched probe & download if already running in background, else fetch now
        probed_dur: Optional[float] = None
        downloaded_path: Optional[Path] = None
        if vid_id in prefetch_cache:
            pf_status, probed_dur, downloaded_path, dl_err = prefetch_cache.pop(vid_id).result()
            if pf_status == "skipped_duration":
                log_decision(f"{bname} [{idx}/{len(urls)}] SKIPPED (prefetch probe) {vid_id}: duration {probed_dur:.1f}s > {max_dur:.0f}s.")
                with state_lock:
                    items[vid_id] = {
                        "url": url,
                        "video_id": vid_id,
                        "status": "skipped_duration",
                        "orig_duration_sec": round(probed_dur, 2),
                        "reason": f"duration>{int(max_dur)}s",
                    }
                    save_state(state)
                continue
            if pf_status != "ok" or not downloaded_path or not downloaded_path.exists():
                log_decision(f"{bname} [{idx}/{len(urls)}] FAILED download {vid_id}: {dl_err}")
                with state_lock:
                    items[vid_id] = {"url": url, "video_id": vid_id, "status": "failed_download", "error": str(dl_err)[:300]}
                    save_state(state)
                continue
        else:
            try:
                probed_dur = downloader.probe_video_duration(url)
            except Exception as pe:
                print(f"  [Probe Warning] {vid_id}: {pe}", flush=True)

            if probed_dur is not None and probed_dur > max_dur:
                log_decision(f"{bname} [{idx}/{len(urls)}] SKIPPED (pre-download probe) {vid_id}: duration {probed_dur:.1f}s > {max_dur:.0f}s.")
                with state_lock:
                    items[vid_id] = {
                        "url": url,
                        "video_id": vid_id,
                        "status": "skipped_duration",
                        "orig_duration_sec": round(probed_dur, 2),
                        "reason": f"duration>{int(max_dur)}s",
                    }
                    save_state(state)
                continue

            downloaded_path = find_cached_local_mp4(batch_input_dir, vid_id)
            if not downloaded_path:
                dl_err = None
                for dl_try in range(3):
                    try:
                        downloaded_path = downloader.download_video(url, output_dir=batch_input_dir)
                        if downloaded_path and downloaded_path.exists():
                            break
                    except Exception as e:
                        dl_err = e
                        print(f"  [Download Retry {dl_try+1}/3] {vid_id}: {e}", flush=True)
                        time.sleep(3 * (dl_try + 1))
                if not downloaded_path or not downloaded_path.exists():
                    log_decision(f"{bname} [{idx}/{len(urls)}] FAILED download {vid_id}: {dl_err}")
                    with state_lock:
                        items[vid_id] = {"url": url, "video_id": vid_id, "status": "failed_download", "error": str(dl_err)[:300]}
                        save_state(state)
                    continue

        # Step C: Exact ffprobe duration check (handles cases where metadata probe failed)
        actual_dur = get_media_duration(downloaded_path)
        if actual_dur <= 0:
            log_decision(f"{bname} [{idx}/{len(urls)}] FAILED invalid/corrupt media {vid_id} (dur={actual_dur}). Deleted.")
            try:
                downloaded_path.unlink()
            except Exception:
                pass
            with state_lock:
                items[vid_id] = {"url": url, "video_id": vid_id, "status": "failed_invalid_media"}
                save_state(state)
            continue

        if actual_dur > max_dur:
            log_decision(f"{bname} [{idx}/{len(urls)}] SKIPPED (post-download ffprobe) {vid_id}: {actual_dur:.1f}s > {max_dur:.0f}s. Deleted source.")
            try:
                downloaded_path.unlink()
            except Exception:
                pass
            with state_lock:
                items[vid_id] = {
                    "url": url,
                    "video_id": vid_id,
                    "status": "skipped_duration",
                    "orig_duration_sec": round(actual_dur, 2),
                    "reason": f"duration>{int(max_dur)}s",
                }
                save_state(state)
            continue

        # Queue background prefetch for Video N+1 while Video N runs GPU/TTS
        _schedule_next_prefetch(idx)

        # Step D: Run DubbingPipeline with retry & self-healing cleanup
        print(f"\n[{bname} {idx}/{len(urls)}] Processing {vid_id} ({actual_dur:.1f}s, probed={probed_dur}) via {pipeline.tts_engine}...", flush=True)
        res = None
        run_err = None
        for attempt in range(2):
            try:
                gpu_thermal_guard()
                storage_guard()
                # Refresh active engine before retry in case keys got exhausted on first attempt
                refreshed = pick_current_tts_engine(preferred=batch.get("preferred_tts", "elevenlabs"), allow_fallback=batch["allow_tts_fallback"])
                if refreshed is None:
                    raise RuntimeError(f"TTS engine exhausted ({batch.get('preferred_tts')}).")
                pipeline.tts_engine = refreshed

                res = pipeline.run(
                    url_or_file=str(downloaded_path),
                    target_lang=batch["lang"],
                    voice=batch.get("voice"),
                    force=(attempt > 0),
                    clean_subtitles=False,
                    preserve_bgm=True,
                    disable_bgm=batch["disable_bgm"],
                    allow_tts_fallback=batch["allow_tts_fallback"],
                    enable_metadata=True,
                    style="viral",
                    fit_short=False,
                    channel_name=bname,
                    movie=batch["movie"],
                    ratio=batch["ratio"],
                    watermark=batch["watermark"],
                )
                break
            except Exception as e:
                run_err = e
                tb_short = "".join(traceback.format_exception(type(e), e, e.__traceback__)[-3:])
                print(f"  [Pipeline Error Attempt {attempt+1}/2] {vid_id}: {e}\n{tb_short}", flush=True)
                if not batch["allow_tts_fallback"] and "exhausted" in str(e).lower():
                    log_decision(f"{bname}: ElevenLabs exhausted mid-video {vid_id}; stopping {bname} cleanly.")
                    cleanup_temp_artifacts([downloaded_path])
                    return False
                cleanup_temp_artifacts()
                time.sleep(3)

        if not res or not res.get("final_video") or not Path(res["final_video"]).exists():
            log_decision(f"{bname} [{idx}/{len(urls)}] FAILED pipeline {vid_id}: {run_err}")
            with state_lock:
                items[vid_id] = {
                    "url": url,
                    "video_id": vid_id,
                    "status": "failed_pipeline",
                    "orig_duration_sec": round(actual_dur, 2),
                    "error": str(run_err)[:400],
                }
                save_state(state)
            cleanup_temp_artifacts([downloaded_path])
            continue

        final_local = Path(res["final_video"])
        out_dur = get_media_duration(final_local)
        clamped_meta = clamp_youtube_metadata(res.get("metadata") or {}, vid_id, batch["lang"], movie=batch.get("movie", False))

        # Wait for any previous background Drive upload before launching the next upload & temp cleanup
        if upload_future is not None:
            upload_future.result()
            upload_future = None

        # Build clean collision-free Drive filename (safe under state_lock)
        dest_name = final_local.name
        dest_drive = drive_folder / dest_name
        with state_lock:
            existing_fname = str((items.get(vid_id) or {}).get("drive_filename") or "")
        if dest_drive.exists() and vid_id not in existing_fname:
            dest_name = f"{final_local.stem} [{vid_id[-6:]}]{final_local.suffix}"
            dest_drive = drive_folder / dest_name

        used_eng = res.get("tts_engine_used") or pipeline.tts_engine
        if used_eng == "elevenlabs" and not get_active_elevenlabs_keys():
            used_eng = pick_current_tts_engine(preferred=batch.get("preferred_tts", "elevenlabs"), allow_fallback=batch["allow_tts_fallback"]) or used_eng

        # Immediately reclaim source & intermediate artifacts, then upload final MP4 asynchronously
        freed_mb = cleanup_temp_artifacts([downloaded_path])
        print(f"  [Async Drive Upload Queued] {dest_name} (interm freed={freed_mb:.1f} MB)", flush=True)
        upload_future = upload_executor.submit(
            _upload_and_record,
            vid_id,
            url,
            actual_dur,
            final_local,
            out_dur,
            clamped_meta,
            used_eng,
            dest_name,
            dest_drive,
        )
    finally:
        if upload_future is not None:
            upload_future.result()
        prefetch_executor.shutdown(wait=False, cancel_futures=True)
        upload_executor.shutdown(wait=True)

    write_sorted_batch_metadata(bname, bstate, drive_folder)
    completed_cnt = sum(1 for v in items.values() if v.get("status") == "completed")
    skipped_cnt = sum(1 for v in items.values() if v.get("status") == "skipped_duration")
    failed_cnt = sum(1 for v in items.values() if str(v.get("status", "")).startswith("failed"))
    log_decision(f"Completed {bname}: {completed_cnt} rendered & sorted in Drive, {skipped_cnt} duration-skipped, {failed_cnt} failed.")
    return True


def _set_windows_keep_awake(enable: bool) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        flags = 0x80000001 if enable else 0x80000000  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
    except Exception:
        pass


def main() -> None:
    _set_windows_keep_awake(True)
    try:
        _main_impl()
    finally:
        _set_windows_keep_awake(False)


def _main_impl() -> None:
    DRIVE_PENDING_ROOT.mkdir(parents=True, exist_ok=True)
    state = load_state()

    downloader = DownloaderAPI()
    pipeline = DubbingPipeline(
        input_dir=ROOT_DIR / "input",
        output_dir=ROOT_DIR / "output",
        tts_engine=pick_current_tts_engine(allow_fallback=True) or "elevenlabs",
    )

    log_decision("Overnight autonomous runner started (English Batches 1-4 -> live ElevenLabs check -> conditional Batch 4 Hindi).")

    for batch in BATCHES:
        run_batch(batch, state, downloader, pipeline)

    # Check live remaining ElevenLabs quota for conditional Batch 4 Hindi
    el_status = check_live_elevenlabs_quota()
    rem_chars = int(el_status.get("total_remaining_chars", 0))
    log_decision(
        f"Post-English ElevenLabs quota check: {el_status.get('working_keys_with_chars', 0)} working keys, "
        f"{rem_chars} remaining characters."
    )

    if rem_chars > 0:
        b4_hindi = dict(BATCHES[3])
        b4_hindi.update({
            "name": "batch_4_hindi",
            "lang": "Hindi",
            "allow_tts_fallback": False,
        })
        log_decision(f"Starting conditional `batch_4_hindi` (ElevenLabs only, {rem_chars} chars available).")
        run_batch(b4_hindi, state, downloader, pipeline)
    else:
        log_decision("Skipping `batch_4_hindi`: 0 ElevenLabs characters remaining after English Batches 1-4.")

    cleanup_temp_artifacts()
    log_decision("All overnight batches finished cleanly!")
    print("\n=== ALL OVERNIGHT BATCHES COMPLETE ===", flush=True)


if __name__ == "__main__":
    main()
