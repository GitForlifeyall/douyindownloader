#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/dub_elevenlabs.py
=======================
Standalone utility to synthesize speech using ElevenLabs v4 (eleven_v4)
and mux into a synchronized dubbed video with isolated SFX & BGM.
Supports multi-key round-robin rotation and runtime quota eviction.
"""

import sys
import argparse
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dubbing_studio.env_loader import configure_runtime_environment
configure_runtime_environment()

from dubbing_studio.key_pool import get_active_elevenlabs_keys, get_pool_status
from dubbing_studio.block_aligner import align_video_and_audio_blocks


def main():
    parser = argparse.ArgumentParser(description="ElevenLabs v4 Block-Aligned Video Dubber")
    parser.add_argument("--video", "-v", type=str, default="output/clean_videos/知墨探索 - 美国男子洞穴探险被卡住了_clean.mp4", help="Path to clean MP4 video")
    parser.add_argument("--srt", "-s", type=str, default="output/subtitles/知墨探索 - 美国男子洞穴探险被卡住了_hindi_funny.srt", help="Path to Hindi SRT subtitle file")
    parser.add_argument("--sfx", type=str, default="output/audio_stems/知墨探索 - 美国男子洞穴探险被卡住了_sfx.wav", help="Path to isolated Foley SFX stem")
    parser.add_argument("--voice", type=str, default="viraj", help="ElevenLabs voice name or voice ID (default: viraj)")

    parser.add_argument("--output", "-o", type=str, default=None, help="Output MP4 path")
    args = parser.parse_args()

    v_path = Path(args.video)
    s_path = Path(args.srt)
    if not v_path.exists():
        parser.error(f"Video file not found: {v_path}")
    if not s_path.exists():
        parser.error(f"SRT file not found: {s_path}")

    active_keys = get_active_elevenlabs_keys()
    print(f"\n[ElevenLabs Dubber] Initializing ElevenLabs v4...")
    print(f"  Active ElevenLabs Keys in Pool: {len(active_keys)}")
    if not active_keys:
        print("\n[WARNING] No active ELEVENLABS_API_KEY or ELEVENLABS_API_KEYS found in .env!")
        print("Please add your ElevenLabs API keys in .env like:")
        print("  ELEVENLABS_API_KEYS=key1,key2,key3\n")
        return

    out_path = Path(args.output) if args.output else v_path.parent.parent / "final_videos" / f"{v_path.stem.replace('_clean', '')}_elevenlabs_dubbed.mp4"
    sfx_file = Path(args.sfx) if args.sfx and Path(args.sfx).exists() else None

    align_video_and_audio_blocks(
        clean_video_path=v_path,
        srt_path=s_path,
        output_video_path=out_path,
        sfx_path=sfx_file,
        voice=args.voice,
        engine="elevenlabs"
    )
    print(f"\n[DONE] Final video saved: {out_path}\n")


if __name__ == "__main__":
    main()
