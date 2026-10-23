#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import time
import json
import random
import shutil
import subprocess
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import ImageFont, ImageDraw, Image
from dubbing_studio.env_loader import configure_runtime_environment
configure_runtime_environment()

from dubbing_studio.pipeline import sanitize_filename
from dubbing_studio.transcriber import Transcriber
from dubbing_studio.translator import SRTDubTranslator
from dubbing_studio.separator import AudioStemSeparator
from dubbing_studio.tts import SarvamTTS, load_srt_blocks
from blur_subtitles_rapidocr import process_video_srt_rapidocr

def to_ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

def get_random_background_audio(bg_dir: Path) -> Path:
    exts = ('.mp3', '.wav', '.aac', '.m4a', '.ogg', '.flac')
    audio_files = [p for p in bg_dir.iterdir() if p.is_file() and p.suffix.lower() in exts]
    if not audio_files:
        raise FileNotFoundError(f"No audio files found in {bg_dir}")
    return random.choice(audio_files)

def main():
    root = Path.cwd()
    video_path = Path(r"C:\Users\rudra\PycharmProjects\douyindownloader\TikTokDownloader\Volume\Download\2026-09-17 14.56.44-Video-旭日-恭喜你，成功复刻出古法耐火泥 #耐...#百young非遗计划 #传统工艺 #科普.mp4")
    
    clean_slug = sanitize_filename(video_path.stem)
    print("=" * 60)
    print(f" [Master Pipeline Runner with Detailed Timings]")
    print(f" Target Video: {video_path.name}")
    print(f" Clean Slug  : {clean_slug}")
    print("=" * 60)

    timings = {}
    timings["step1_download"] = 16.83  # Recorded from step 1

    # Setup directories
    subtitles_dir = root / "output" / "subtitles"
    clean_videos_dir = root / "output" / "clean_videos"
    audio_stems_dir = root / "output" / "audio_stems"
    final_videos_dir = root / "output" / "final_videos"
    for d in [subtitles_dir, clean_videos_dir, audio_stems_dir, final_videos_dir]:
        d.mkdir(parents=True, exist_ok=True)

    raw_srt = subtitles_dir / f"{clean_slug}_raw.srt"
    hindi_srt = subtitles_dir / f"{clean_slug}_hindi.srt"
    clean_video_path = clean_videos_dir / f"{clean_slug}_clean.mp4"
    ass_subs_path = subtitles_dir / f"{clean_slug}_hinglish.ass"

    # -----------------------------------------------------------------
    # Step 2: Transcribe Speech to Raw SRT
    # -----------------------------------------------------------------
    print(f"\n[Step 2/7] Transcribing Speech to Raw Chinese SRT via Faster-Whisper...")
    t0 = time.time()
    transcriber = Transcriber(model_size="large-v3-turbo")
    transcriber.transcribe(video_path, output_srt=raw_srt, force=True)
    t1 = time.time()
    timings["step2_transcribe"] = round(t1 - t0, 2)
    print(f"  -> Transcribe completed in {timings['step2_transcribe']}s")

    # -----------------------------------------------------------------
    # Step 3: Translate to Hindi via Gemini SDK
    # -----------------------------------------------------------------
    print(f"\n[Step 3/7] Translating & Transcreating to Conversational Hindi/Hinglish...")
    t0 = time.time()
    translator = SRTDubTranslator()
    translated_srt, report = translator.translate_and_rewrite_srt(
        srt_input=raw_srt,
        target_language="Hindi (Natural Spoken Hinglish in Devanagari script)",
        batch_size=8,
        temperature=0.4
    )
    hindi_srt.write_text(translated_srt, encoding="utf-8")
    t1 = time.time()
    timings["step3_translate"] = round(t1 - t0, 2)
    print(f"  -> Translation completed in {timings['step3_translate']}s")

    # -----------------------------------------------------------------
    # Step 4: Audio Stem Separation via DBS-TIGER-DnR
    # -----------------------------------------------------------------
    print(f"\n[Step 4/7] Audio Stem Separation via DBS-TIGER-DnR (Isolating SFX)...")
    t0 = time.time()
    separator = AudioStemSeparator(model="DBS-TIGER-DnR")
    stems = separator.separate_audio(
        video_path,
        output_dir=audio_stems_dir,
        clean_name=clean_slug,
        force=True
    )
    sfx_audio = stems.get("sfx")
    t1 = time.time()
    timings["step4_separate_audio"] = round(t1 - t0, 2)
    print(f"  -> Stem separation completed in {timings['step4_separate_audio']}s (SFX: {sfx_audio.name})")

    # -----------------------------------------------------------------
    # Step 5: Subtitle Boundary Scan & Permanent Luminance Blur
    # -----------------------------------------------------------------
    print(f"\n[Step 5/7] RapidOCR Scanning Maximum Boundary & Rendering Permanent Clean Video...")
    t0 = time.time()
    res_clean = process_video_srt_rapidocr(
        input_video=str(video_path),
        output_video=str(clean_video_path),
        srt_file=str(raw_srt)
    )
    t1 = time.time()
    timings["step5_clean_video"] = round(t1 - t0, 2)
    print(f"  -> Permanent clean video completed in {timings['step5_clean_video']}s")

    # -----------------------------------------------------------------
    # Step 6: Speech Synthesis via Sarvam AI
    # -----------------------------------------------------------------
    print(f"\n[Step 6/7] Synthesizing Hindi Voiceover via Sarvam AI...")
    t0 = time.time()
    tts = SarvamTTS()
    tts.synthesize(
        srt_path=hindi_srt,
        video_path=clean_video_path,
        target_language="hindi",
        speaker="meera",
        preserve_bgm=False,
        output_dir=final_videos_dir,
        clean_subtitles=False
    )
    t1 = time.time()
    timings["step6_sarvam_tts"] = round(t1 - t0, 2)
    print(f"  -> Sarvam TTS voiceover mastered in {timings['step6_sarvam_tts']}s")

    master_voice = audio_stems_dir / f"master_sarvam_{hindi_srt.stem}.wav"

    # Save timings checkpoint
    with open("pipeline_timings_fireclay.json", "w", encoding="utf-8") as f:
        json.dump(timings, f, indent=2)

    print("\n[+] Steps 1-6 completed successfully!")
    print(json.dumps(timings, indent=2))

if __name__ == "__main__":
    main()
