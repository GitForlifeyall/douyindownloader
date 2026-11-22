#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_gemini_3.8_flash_lite_dub.py
=====================================
Generates video dubbing using Google Gemini 3.8 Flash Lite TTS (gemini-3.8-flash-lite-tts).
Uses the revised Hindi SRT, clean video visual, and preserved Foley SFX / BGM stem.
Places final output strictly in output/final_videos/.
"""

import sys
from pathlib import Path
from dubbing_studio.env_loader import configure_runtime_environment
configure_runtime_environment()

from dubbing_studio.tts_google import GoogleGeminiTTS


def main():
    root = Path.cwd()
    clean_video = root / "output/clean_videos/道可道 - 恭喜你成功制作出桂花蜜_clean.mp4"
    bgm_stem = root / "output/audio_stems/stems_道可道 - 恭喜你成功制作出桂花蜜/no_vocals.wav"
    hindi_srt = root / "output/subtitles/道可道 - 恭喜你成功制作出桂花蜜_hindi.srt"

    final_dir = root / "output/final_videos"
    stems_dir = root / "output/audio_stems"
    final_video = final_dir / "道可道 - 恭喜你成功制作出桂花蜜_hindi_gemini_3.8_flash_lite_dubbed.mp4"

    print("==================================================")
    print(" [Gemini 3.8 Flash Lite TTS] Starting Video Dubbing")
    print(f" Subtitles      : {hindi_srt.name}")
    print(f" Clean Video    : {clean_video.name}")
    print(f" Foley BGM Stem : {bgm_stem.name}")
    print(f" Target Video   : {final_video.name}")
    print("==================================================")

    gemini_tts = GoogleGeminiTTS(
        model="gemini-3.8-flash-lite-tts",
        default_speaker="Orus"
    )

    out = gemini_tts.synthesize_and_dub(
        dubbed_srt=hindi_srt,
        original_video=clean_video,
        final_video=final_video,
        voice="Orus",
        lang="Hindi",
        base_speed=1.0,
        bgm_path=bgm_stem,
        bgm_volume=1.05,
        work_dir=stems_dir
    )

    print(f"\n✓ SUCCESS! Created final video: {out.name} ({out.stat().st_size / 1024 / 1024:.2f} MB)")


if __name__ == "__main__":
    main()
