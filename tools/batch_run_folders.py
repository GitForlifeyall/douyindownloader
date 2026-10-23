#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
batch_run_folders.py
====================
Autonomous overnight batch processor for Douyin/TikTok video folders.
Uses OmniVoice TTS (Male Deep authority preset) instead of Sarvam AI.
Saves all dubbed videos, SRTs, and SEO metadata JSON into ./output/
"""

import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime

# Inject project root
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dubbing_studio.env_loader import configure_runtime_environment
configure_runtime_environment()

from dubbing_studio.pipeline import DubbingPipeline

FOLDERS_TO_PROCESS = [
    Path(r"c:\Users\rudra\PycharmProjects\douyindownloader\TikTokDownloader\Volume\UID1712357377850227_匠人行_Posts"),
    Path(r"c:\Users\rudra\PycharmProjects\douyindownloader\TikTokDownloader\Volume\UID4139006435006263_好奇君_Posts"),
]

BASE_OUTPUT = Path.cwd() / "output"
BASE_OUTPUT.mkdir(parents=True, exist_ok=True)
LOG_FILE = BASE_OUTPUT / "overnight_batch.log"


def log(msg: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] {msg}"
    print(formatted)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(formatted + "\n")
    except Exception:
        pass


def main():
    log("=" * 60)
    log(" [Overnight Studio] Starting Batch Video Rendering with OmniVoice")
    log(f" Target Language : Hindi")
    log(f" TTS Engine      : Sarvam AI (Bulbul v3, shubh voice)")
    log(f" Output Root     : {BASE_OUTPUT}")
    log("=" * 60)

    # Initialize Pipeline with Sarvam AI
    pipeline = DubbingPipeline(
        output_dir=BASE_OUTPUT,
        tts_engine="sarvam",
        gemini_model="gemini-3.8-flash"
    )

    total_success = 0
    total_failed = 0

    for folder in FOLDERS_TO_PROCESS:
        if not folder.exists():
            log(f"[WARNING] Target folder does not exist: {folder}")
            continue

        folder_name = folder.name
        target_out_dir = BASE_OUTPUT / folder_name
        target_out_dir.mkdir(parents=True, exist_ok=True)

        videos = sorted([p for p in folder.glob("*.mp4") if not p.name.startswith("temp_")])
        log(f"\n>>> Processing Folder: {folder_name} ({len(videos)} videos found)")

        metadata_file = target_out_dir / "folder_metadata.json"
        folder_meta = {}
        if metadata_file.exists():
            try:
                folder_meta = json.loads(metadata_file.read_text(encoding="utf-8"))
            except Exception:
                folder_meta = {}

        for idx, vid_path in enumerate(videos, start=1):
            log(f"\n--- [{idx}/{len(videos)}] Processing: {vid_path.name} ---")

            # Check if output already exists to avoid re-rendering
            base_stem = vid_path.stem
            expected_out = target_out_dir / f"{base_stem}_hindi_dubbed.mp4"
            if expected_out.exists() and expected_out.stat().st_size > 100000:
                log(f"[SKIP] Already dubbed and verified: {expected_out.name}")
                total_success += 1
                continue

            # Switch pipeline output dir to current subfolder
            pipeline.output_dir = target_out_dir

            start_t = time.time()
            try:
                res = pipeline.run(
                    url_or_file=str(vid_path),
                    target_lang="Hindi",
                    voice="male_deep",
                    base_speed=1.05,
                    dub_mode="flow",
                    preserve_bgm=True,
                    clean_subtitles=True,
                    remove_watermark=False,
                    bgm_volume=1.05
                )

                elapsed = round(time.time() - start_t, 1)
                final_mp4 = res.get("final_video") or res.get("video")
                final_name = Path(final_mp4).name if final_mp4 else expected_out.name
                meta = res.get("metadata") or {}

                folder_meta[final_name] = {
                    "original_file": vid_path.name,
                    "dubbed_file": final_name,
                    "title": meta.get("title", ""),
                    "description": meta.get("description", ""),
                    "tags": meta.get("tags", []),
                    "hashtags": meta.get("hashtags", []),
                    "tts_engine": "Sarvam AI",
                    "voice": "shubh",
                    "processed_at": datetime.now().isoformat(),
                    "render_duration_sec": elapsed
                }
                metadata_file.write_text(json.dumps(folder_meta, ensure_ascii=False, indent=2), encoding="utf-8")
                log(f"[SUCCESS] Finished in {elapsed}s: {final_name}")
                total_success += 1

            except Exception as e:
                log(f"[ERROR] Failed processing '{vid_path.name}': {e}")
                import traceback
                traceback.print_exc()
                total_failed += 1

    log("\n" + "=" * 60)
    log(f" [Overnight Studio] ALL BATCHES COMPLETE!")
    log(f" Total Dubbed Successfully: {total_success}")
    log(f" Total Failed            : {total_failed}")
    log("=" * 60)


if __name__ == "__main__":
    main()
