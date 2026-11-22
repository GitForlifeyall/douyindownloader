#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/batch_run_urls.py
=======================
Automated Batch Runner for processing lists of Douyin URLs through the Dubbing Pipeline.
Features:
  - Executes each video in an isolated subprocess to completely release Windows virtual
    memory / GPU VRAM / pagefile commit after every video.
  - Automatically cleans intermediate audio stems & duplicate local files backed up in Drive.
  - Uses Google 3.8 Flash TTS (gemini-3.8-flash-tts) with Ludo speaker by default.
  - Block-aligned 1:1 visual lockstep, anti-copyright horizontal mirroring, randomized BGM.
"""

import sys
import os
import shutil
import json
import time
import subprocess
import argparse
from pathlib import Path
from typing import List, Dict, Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dubbing_studio.env_loader import configure_runtime_environment
configure_runtime_environment()

BATCH_URLS = [
    "https://www.douyin.com/video/7686138102880029952",
    "https://www.douyin.com/video/7685654371308260617",
    "https://www.douyin.com/video/7681190818090077481",
    "https://www.douyin.com/video/7680453546269019446",
    "https://www.douyin.com/video/7680112951403105588",
    "https://www.douyin.com/video/7679013427456593204",
    "https://www.douyin.com/video/7668280830610967848",
    "https://www.douyin.com/video/7663711674964217139",
    "https://www.douyin.com/video/7663708100460875048",
    "https://www.douyin.com/video/7662742512406236416",
    "https://www.douyin.com/video/7657173635093826850",
    "https://www.douyin.com/video/7655709606173347106",
    "https://www.douyin.com/video/7655332201407515942",
    "https://www.douyin.com/video/7653299720630193418",
    "https://www.douyin.com/video/7652949421742640419",
    "https://www.douyin.com/video/7652671961721539890",
    "https://www.douyin.com/video/7652352816832335156",
    "https://www.douyin.com/video/7652269667154709800",
    "https://www.douyin.com/video/7651960736184388916",
    "https://www.douyin.com/video/7650539937552518438",
    "https://www.douyin.com/video/7649614368077778210",
    "https://www.douyin.com/video/7649262725163420982",
    "https://www.douyin.com/video/7647920809041808659",
    "https://www.douyin.com/video/7647805374279503147",
    "https://www.douyin.com/video/7645699664419168165",
    "https://www.douyin.com/video/7645333665124280945",
    "https://www.douyin.com/video/7644607626436775168",
    "https://www.douyin.com/video/7643061082478628096",
    "https://www.douyin.com/video/7642180040519716106",
    "https://www.douyin.com/video/7641434144844680491",
]


def cleanup_temp_files():
    """Purge intermediate audio stems and redundant Drive-synced local outputs."""
    stems_dir = PROJECT_ROOT / "output" / "audio_stems"
    if stems_dir.exists():
        for item in stems_dir.iterdir():
            try:
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                elif item.is_file() and item.suffix.lower() in (".wav", ".mp3", ".ass", ".srt"):
                    item.unlink(missing_ok=True)
            except Exception:
                pass

    # Clean up local root mp4 copies that are already safely backed up in Google Drive
    drive_base = Path("I:/My Drive/douyin")
    if drive_base.exists() and (drive_base / "final_videos").exists():
        drive_fv = drive_base / "final_videos"
        drive_names = {p.name for p in drive_fv.iterdir() if p.is_file()}
        for out_dir in (PROJECT_ROOT / "output", PROJECT_ROOT / "output" / "final_videos"):
            if out_dir.exists():
                for f in out_dir.iterdir():
                    if f.is_file() and f.suffix.lower() == ".mp4" and f.name in drive_names:
                        try:
                            f.unlink()
                        except Exception:
                            pass


def run_batch(
    urls: List[str] = BATCH_URLS,
    tts_engine: str = "google",
    voice: str = "Ludo",
    style: str = "viral",
    mirror: bool = True
) -> None:
    progress_file = PROJECT_ROOT / "output" / "batch_urls_progress.json"
    progress: Dict[str, Any] = {}
    if progress_file.exists():
        try:
            progress = json.loads(progress_file.read_text(encoding="utf-8"))
        except Exception:
            progress = {}

    total = len(urls)
    print("\n" + "=" * 70)
    print(f"🚀 STARTING BATCH DUBBING RUN ({total} Videos - Process Isolated)")
    print(f"   TTS Engine      : {tts_engine.upper()} ({voice})")
    print(f"   Dubbing Mode    : Block-Aligned (1:1 lockstep)")
    print(f"   Prompt Style    : {style.upper()} (No infinite loop bridge)")
    print(f"   Anti-Copyright  : Horizontal Mirror (hflip) + Visual Hash Alteration")
    print(f"   BGM Selection   : Randomized Royalty-Free Audio")
    print("=" * 70 + "\n")

    successful = 0
    failed = 0
    skipped = 0

    for idx, url in enumerate(urls, start=1):
        vid_id = url.rstrip("/").split("/")[-1]

        if progress.get(vid_id, {}).get("status") == "success":
            print(f"⏩ [{idx}/{total}] Skipping Video ID {vid_id} (Already completed successfully)")
            skipped += 1
            successful += 1
            continue

        print("\n" + "#" * 70)
        print(f" >>> [{idx}/{total}] Processing Video ID: {vid_id}")
        print(f"     URL: {url}")
        print("#" * 70)

        t_start = time.time()
        cmd = [
            sys.executable,
            str(PROJECT_ROOT / "main.py"),
            "--url", url,
            "--tts", tts_engine,
            "--voice", voice,
            "--style", style,
            "--block-aligned",
        ]
        if mirror:
            cmd.append("--mirror")

        proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
        elapsed = time.time() - t_start

        if proc.returncode == 0:
            progress[vid_id] = {
                "status": "success",
                "url": url,
                "tts": tts_engine,
                "voice": voice,
                "elapsed_seconds": round(elapsed, 2),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            progress_file.write_text(json.dumps(progress, indent=2, ensure_ascii=False), encoding="utf-8")
            successful += 1
            print(f"✅ [{idx}/{total}] SUCCESS in {elapsed:.1f}s")
        else:
            progress[vid_id] = {
                "status": "failed",
                "url": url,
                "error": f"Subprocess exited with code {proc.returncode}",
                "elapsed_seconds": round(elapsed, 2),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            progress_file.write_text(json.dumps(progress, indent=2, ensure_ascii=False), encoding="utf-8")
            failed += 1
            print(f"❌ [{idx}/{total}] FAILED with exit code {proc.returncode} in {elapsed:.1f}s")

        # Cleanup temp stems and synced duplicates after EVERY video
        cleanup_temp_files()

    print("\n" + "=" * 70)
    print("🏁 BATCH DUBBING RUN COMPLETE!")
    print(f"   Total Videos : {total}")
    print(f"   Successful   : {successful} (including {skipped} previously done)")
    print(f"   Failed       : {failed}")
    print(f"   Progress Log : {progress_file}")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch Runner for Douyin Dubbing")
    parser.add_argument("--tts", type=str, default="google", help="TTS engine (google, sarvam, elevenlabs)")
    parser.add_argument("--voice", type=str, default="Ludo", help="Speaker voice name")
    parser.add_argument("--style", type=str, default="viral", help="Prompt style")
    parser.add_argument("--no-mirror", action="store_true", help="Disable horizontal mirroring")
    args = parser.parse_args()

    run_batch(
        tts_engine=args.tts,
        voice=args.voice,
        style=args.style,
        mirror=not args.no_mirror
    )
