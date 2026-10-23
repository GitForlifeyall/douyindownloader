#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dubbing_studio/pipeline.py
==========================
End-to-end automated Dubbing Pipeline orchestrator.
Coordinates:
  [Step 1] Download: Douyin/TikTok video via DownloaderAPI
  [Step 2] Transcribe: Speech-to-SRT via Faster-Whisper GPU
  [Step 2.5] Subtitle Cleaner: Parallel Clause-Sampled RapidOCR Luminance Blur with Euclidean Smoothstep Pill Plate
  [Step 3] Translate: Isochronic viral script transcreation via Gemini SDK with Romanized Hinglish vocabulary
  [Step 4] Stem Separation: Meta HTDemucs Foley/SFX extraction & volume-boosted sidechain ducking
  [Step 5] Dub & Mux: Multi-engine TTS (OmniVoice local GPU / Sarvam AI / Google Gemini / Kokoro)
  [Step 5.5] Subtitles: Dynamic MarginV alignment over blur plate, 120pt Montserrat ExtraBold, <= 3 words/screen
  [Step 6] Social Metadata & Sync: AI title/description/tag generation and Google Drive auto-sync
"""

import os
import sys
import re
import json
import time
import shutil
import subprocess
import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional, Union, Dict, Any, List
from concurrent.futures import ThreadPoolExecutor

from .env_loader import configure_runtime_environment
from .downloader import DownloaderAPI
from .transcriber import Transcriber
from .translator import SRTDubTranslator, DEFAULT_TARGET_LANGUAGE
from .tts_engine import KokoroTTS
from .tts import SarvamTTS, generate_sarvam_tts
from .tts_google import GoogleGeminiTTS
from .tts_elevenlabs import ElevenLabsTTS
from .tts_omnivoice import OmniVoiceTTS
from .separator import AudioStemSeparator
from .key_pool import get_active_gemini_keys, get_active_elevenlabs_keys

configure_runtime_environment()



def sanitize_filename(name: Union[str, Path], max_len: int = 55) -> str:
    """
    Clean cluttered Douyin/TikTok filenames into clean, readable titles.
    - Strips leading date/time prefix (e.g. '2026-10-08 08.14.48-Video-')
    - Strips broken/truncated hashtag fragments (e.g. '...ng非遗计划')
    - Strips all hashtag floods (#桂花蜜 #中国传统文化...)
    - Strips pipeline suffixes (_clean, _dubbed, _hindi, etc.)
    - Removes illegal filesystem chars and excessive punctuation
    - Formats channel and title clearly (e.g. '道可道 - 恭喜你成功制作出桂花蜜')
    - Enforces length limit to prevent Windows path truncation
    """
    # Strip media file extension only (prevent truncation on dots in timestamps like 06.30.00)
    stem = re.sub(r'\.(?:mp4|mkv|mov|avi|webm|srt|json|wav|mp3|m4a)$', '', str(name), flags=re.I)
    # Strip leading date/time prefix
    stem = re.sub(r'^\d{4}-\d{2}-\d{2}[\s_]+\d{2}[.:]\d{2}[.:]\d{2}(?:-Video|-video)?-?', '', stem)
    stem = re.sub(r'^\d{4}-\d{2}-\d{2}-?', '', stem)
    # Strip broken/truncated hashtag fragments like '...ng非遗计划'
    stem = re.sub(r'\.{2,}\S*', '', stem)
    # Strip all hashtags
    stem = re.sub(r'#\S+', '', stem)
    # Strip common suffixes if present
    stem = re.sub(r'_(?:clean|dubbed|raw|hindi|english|metadata)$', '', stem, flags=re.I)

    # Split author and title if hyphen-separated (e.g. '道可道-恭喜你成功制作出桂花蜜')
    parts = [p.strip() for p in re.split(r'[-–—]', stem) if p.strip()]
    if len(parts) >= 2:
        author = parts[0]
        title = " - ".join(parts[1:])
    else:
        author = ""
        title = stem.strip()

    def clean_text(t: str) -> str:
        t = re.sub(r'\.{2,}', '', t)
        for char in ['\\', '/', '*', '?', ':', '"', '<', '>', '|', '!', '！', ',', '，', '#', '$', '%', '^', '&', '\n', '\r', '\t']:
            t = t.replace(char, '')
        t = re.sub(r'\s+', ' ', t).strip()
        return t

    title = clean_text(title)
    author = clean_text(author)
    if author and title:
        combined = f"{author} - {title}"
    else:
        combined = title or author or "video"

    if len(combined) > max_len:
        combined = combined[:max_len].rstrip(" -_.,")
    return combined


def sanitize_title_for_filename(title: str, max_len: int = 150) -> str:
    """
    Sanitize YouTube title into a safe Windows NTFS filename while preserving emojis and basic hashtags.
    Removes characters illegal in Windows filenames: \\ / : * ? " < > |
    """
    safe = re.sub(r'[\\/*?:"<>|]', '', str(title)).strip()
    safe = re.sub(r'\s+', ' ', safe).strip()
    safe = safe.rstrip('. ')
    if len(safe) > max_len:
        safe = safe[:max_len].strip().rstrip('. ')
    return safe


def get_video_duration(video_path: Union[str, Path]) -> float:
    """Return video or audio duration in seconds using ffprobe."""
    if not video_path or not Path(video_path).exists():
        return 0.0
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path)
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
        return float(res.stdout.strip())
    except Exception:
        return 0.0


def has_audio_stream(video_path: Union[str, Path]) -> bool:
    """Check if media file contains an audio stream."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=codec_type",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path)
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
        return bool(res.stdout.strip())
    except Exception:
        return False


def build_atempo_filter(speed_factor: float) -> str:
    """Chain FFmpeg atempo filters (each clamped between 0.5 and 2.0)."""
    factors = []
    rem = speed_factor
    while rem > 2.0:
        factors.append(2.0)
        rem /= 2.0
    while rem < 0.5:
        factors.append(0.5)
        rem /= 0.5
    factors.append(round(rem, 5))
    return ",".join(f"atempo={f}" for f in factors)


def clean_youtube_tags(raw_tags: Any, title: str = "") -> List[str]:
    """
    Format YouTube tags strictly into 3 clean, high-impact tags:
    1. 'Animation'
    2. '3D Explained'
    3. Primary subject (1-2 words, e.g. 'Royal Guards', 'Nutty Putty Cave', 'Flying Car')
    """
    tags = ["Animation", "3D Explained"]
    subject = ""

    # Known subject lookup for precision
    KNOWN_SUBJECTS = {
        "royal guard": "Royal Guards",
        "nutty putty": "Nutty Putty Cave",
        "cave": "Nutty Putty Cave",
        "doberman": "Doberman",
        "letter": "Old Letters",
        "wax seal": "Wax Seal",
        "teleport": "Teleportation",
        "tire": "Buried Tires",
        "dice": "Casino Dice",
        "horse": "Horse Tail",
        "sandal": "Wooden Sandals",
        "vietnam": "Vietnam War",
        "bullet trap": "Bullet Trap",
        "cremation": "Cremation",
        "shaving": "Beard Shaving",
        "beard": "Beard Shaving",
        "water drop": "Water Torture",
        "water torture": "Water Torture",
        "donut": "Donut Hole",
        "flying car": "Flying Car",
        "canned food": "WW1 Food Trick",
        "ww1": "WW1 Food Trick",
        "toilet": "Castle Toilet"
    }

    t_lower = (title or "").lower()
    for k, v in KNOWN_SUBJECTS.items():
        if k in t_lower:
            subject = v
            break

    # If not in lookup, check if raw_tags has a good short subject
    if not subject and isinstance(raw_tags, list):
        for t in raw_tags:
            t_str = str(t).strip()
            if t_str.lower() not in ("animation", "3d animation", "3d explained", "explained", "shorts", "viral", "facts"):
                words = t_str.split()
                if 1 <= len(words) <= 2:
                    subject = t_str.title()
                    break

    # If still not found, extract from title
    if not subject and title:
        clean = re.sub(r'#\S+', '', title)
        clean = re.sub(r'\(.*?\)', '', clean)
        clean = re.sub(r'[^\w\s]', ' ', clean).strip()
        clean = re.sub(r'^\b(Why|How|What|Is|Do|Does|The|Did|A|An)\b\s*', '', clean, flags=re.IGNORECASE).strip()
        words = clean.split()
        if words:
            subject = " ".join(words[:2]).title()

    tags.append(subject or "Mystery Facts")
    return tags


class DubbingPipeline:
    """Master Dubbing Pipeline orchestrating all 5 stages."""

    def __init__(
        self,
        input_dir: Optional[Union[str, Path]] = None,
        output_dir: Optional[Union[str, Path]] = None,
        model_size: str = "large-v3-turbo",
        gemini_model: str = "gemini-3.8-flash",
        tts_engine: str = "elevenlabs",
        tts_model_path: Optional[Union[str, Path]] = None,
        tts_voices_path: Optional[Union[str, Path]] = None
    ):
        self.output_dir = Path(output_dir) if output_dir else Path.cwd() / "output"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.input_dir = Path(input_dir) if input_dir else (self.output_dir.parent / "input").resolve()
        self.input_dir.mkdir(parents=True, exist_ok=True)
        self._setup_output_dirs(self.output_dir)

        self.downloader = DownloaderAPI()
        self.transcriber = Transcriber(model_size=model_size)
        self.translator = SRTDubTranslator(model=gemini_model)
        self.separator = AudioStemSeparator()
        self.tts_engine = (tts_engine or "elevenlabs").lower()
        has_sarvam_keys = bool(os.getenv("SARVAM_API_KEY") or os.getenv("SARVAM_API_KEYS"))
        self.sarvam_tts = SarvamTTS() if has_sarvam_keys else None
        self.omnivoice_tts = OmniVoiceTTS()
        self.kokoro_tts = KokoroTTS(model_path=tts_model_path, voices_path=tts_voices_path)
        has_gemini_keys = bool(os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEYS"))
        self.google_tts = GoogleGeminiTTS() if has_gemini_keys else None
        has_elevenlabs_keys = bool(os.getenv("ELEVENLABS_API_KEY") or os.getenv("ELEVENLABS_API_KEYS"))
        self.elevenlabs_tts = ElevenLabsTTS() if has_elevenlabs_keys else None


    def _setup_output_dirs(self, base_dir: Path):
        """Create dedicated, purpose-specific output folders."""
        self.final_dir = base_dir / "final_videos"
        self.clean_dir = base_dir / "clean_videos"
        self.subtitles_dir = base_dir / "subtitles"
        self.metadata_dir = base_dir / "metadata"
        self.stems_dir = base_dir / "audio_stems"

        for d in (self.final_dir, self.clean_dir, self.subtitles_dir, self.metadata_dir, self.stems_dir):
            d.mkdir(parents=True, exist_ok=True)

    def reorganize_existing_output(self):
        """
        Scan output directory and reorganize existing cluttered files into their respective subfolders:
          - final_videos/  : Strictly final dubbed MP4s (voiceover + SFX/BGM mixed)
          - clean_videos/  : Inpaint-cleaned MP4s
          - subtitles/     : Raw and dubbed SRT files
          - metadata/      : Metadata JSON files
          - audio_stems/   : Stems and intermediate master audio files
        """
        import shutil
        print(f"[Dubbing Studio] Reorganizing existing files in: {self.output_dir}")
        self._setup_output_dirs(self.output_dir)

        for item in list(self.output_dir.iterdir()):
            if item.is_dir():
                if item.name in ["final_videos", "clean_videos", "subtitles", "metadata", "audio_stems"]:
                    continue
                if item.name.startswith("stems_") or item.name == "temp_sarvam_slices" or item.name.startswith("cache_"):
                    clean_name = f"stems_{sanitize_filename(item.name[6:])}" if item.name.startswith("stems_") else item.name
                    dest = self.stems_dir / clean_name
                    if not dest.exists():
                        shutil.move(str(item), str(dest))
                        print(f"  [Moved Stem Folder] {item.name} -> audio_stems/{dest.name}")
                    else:
                        for sub_f in item.iterdir():
                            target_f = dest / sub_f.name
                            if not target_f.exists():
                                shutil.copy2(str(sub_f), str(target_f))
                        shutil.rmtree(str(item), ignore_errors=True)
                continue

            if not item.is_file():
                continue

            name = item.name
            stem = item.stem
            suffix = item.suffix.lower()

            if suffix == ".mp4":
                if stem.endswith("_dubbed") or "_dubbed" in stem:
                    clean_name = sanitize_filename(stem)
                    dest = self.final_dir / f"{clean_name}_hindi_dubbed.mp4"
                    shutil.move(str(item), str(dest))
                    print(f"  [Final Video] {name} -> final_videos/{dest.name}")
                    # Also mirror to Google Drive if mounted
                    drive_final = Path("H:/My Drive/douyin/final_videos")
                    if Path("H:/My Drive/douyin").exists():
                        drive_final.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(str(dest), str(drive_final / dest.name))
                        print(f"  [Google Drive Sync] Synced {dest.name} to {drive_final}")
                elif stem.endswith("_clean"):
                    clean_name = sanitize_filename(stem)
                    dest = self.clean_dir / f"{clean_name}_clean.mp4"
                    shutil.move(str(item), str(dest))
                    print(f"  [Clean Video] {name} -> clean_videos/{dest.name}")
            elif suffix == ".srt":
                clean_name = sanitize_filename(stem)
                if "hindi" in stem.lower():
                    dest = self.subtitles_dir / f"{clean_name}_hindi.srt"
                else:
                    dest = self.subtitles_dir / f"{clean_name}_raw.srt"
                shutil.move(str(item), str(dest))
                print(f"  [Subtitle] {name} -> subtitles/{dest.name}")
            elif suffix == ".json":
                clean_name = sanitize_filename(stem)
                dest = self.metadata_dir / f"{clean_name}_metadata.json"
                shutil.move(str(item), str(dest))
                print(f"  [Metadata] {name} -> metadata/{dest.name}")
            elif suffix in [".wav", ".mp3"] or "master" in stem or "slice" in stem:
                dest = self.stems_dir / item.name
                shutil.move(str(item), str(dest))
                print(f"  [Audio Intermediate] {name} -> audio_stems/{dest.name}")


    def _resolve_tts(self, target_lang: str) -> Any:
        has_gemini_key = bool(os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEYS"))
        has_elevenlabs_key = bool(os.getenv("ELEVENLABS_API_KEY") or os.getenv("ELEVENLABS_API_KEYS"))
        has_sarvam_key = bool(os.getenv("SARVAM_API_KEY") or os.getenv("SARVAM_API_KEYS"))

        # ElevenLabs v4 (Default & 1st Priority)
        if self.tts_engine in ("elevenlabs", "eleven_labs", "11labs"):
            # If ElevenLabs keys are exhausted, cleanly switch to Google Gemini Flash 3.8 TTS
            if not get_active_elevenlabs_keys() and get_active_gemini_keys():
                print("[Pipeline] Notice: ElevenLabs keys exhausted! Auto-switching engine to Google Gemini Flash 3.8 TTS...")
                self.tts_engine = "google"
                return self.google_tts or GoogleGeminiTTS()
            if self.elevenlabs_tts:
                return self.elevenlabs_tts
            if has_elevenlabs_key:
                return ElevenLabsTTS()
            print("[Pipeline] WARNING: ELEVENLABS_API_KEY / ELEVENLABS_API_KEYS missing! Falling back to Google Gemini Flash 3.8 TTS.")
            return self.google_tts or self.sarvam_tts or self.omnivoice_tts

        # Google Flash 3.8 TTS (Fallback)
        elif self.tts_engine in ("google", "gemini"):
            # Check if Gemini keys are out of quota; if so, switch to Sarvam or ElevenLabs
            if not get_active_gemini_keys() and get_active_sarvam_keys():
                print("[Pipeline] Notice: Gemini keys exhausted! Auto-switching engine to Sarvam AI (Bulbul v3)...")
                self.tts_engine = "sarvam"
                return self.sarvam_tts or SarvamTTS()
            if self.google_tts:
                return self.google_tts
            if has_gemini_key:
                return GoogleGeminiTTS()
            print("[Pipeline] WARNING: GEMINI_API_KEY / GEMINI_API_KEYS missing! Falling back to ElevenLabs/Sarvam.")
            return self.elevenlabs_tts or self.sarvam_tts or self.omnivoice_tts

        # Sarvam AI (Bulbul v3)
        elif self.tts_engine in ("sarvam", "auto") or not self.tts_engine:
            if self.sarvam_tts:
                return self.sarvam_tts
            if has_sarvam_key:
                return SarvamTTS()
            print("[Pipeline] WARNING: SARVAM_API_KEY / SARVAM_API_KEYS missing! Falling back to Google.")
            return self.google_tts or self.elevenlabs_tts or self.omnivoice_tts

        elif self.tts_engine in ("omnivoice", "omni"):
            return self.omnivoice_tts
        elif self.tts_engine == "kokoro":
            return self.kokoro_tts

        return self.google_tts or self.elevenlabs_tts or self.sarvam_tts or self.omnivoice_tts

    def _condense_to_short(
        self,
        video_path: Path,
        max_duration: float = 58.0,
        force: bool = False
    ) -> Path:
        """
        Fast-forward video and audio if duration exceeds max_duration (e.g. 58s).
        Enables longer videos to cleanly fit within YouTube Shorts & Reels (< 60s).
        """
        if not video_path.exists():
            return video_path

        dur = get_video_duration(video_path)
        if dur <= 0:
            return video_path

        if dur <= max_duration:
            print(f"[Short Condenser] Video duration ({dur:.1f}s) is already under {max_duration:.1f}s limit. No fast-forward needed.")
            return video_path

        speed_factor = dur / max_duration
        print("\n" + "=" * 60)
        print(f" [Short Condenser] Fast-Forwarding Video to Fit Under 1 Min (< {max_duration:.1f}s)")
        print(f"   Original Duration : {dur:.1f}s")
        print(f"   Target Duration   : {max_duration:.1f}s")
        print(f"   Speedup Factor    : {speed_factor:.3f}x")
        print("=" * 60)

        condensed_dir = self.input_dir / "short_condensed"
        condensed_dir.mkdir(parents=True, exist_ok=True)
        dest_file = condensed_dir / f"{video_path.stem}_short_{int(max_duration)}s.mp4"

        if not force and dest_file.exists() and dest_file.stat().st_size > 50000:
            existing_dur = get_video_duration(dest_file)
            if 0 < existing_dur <= max_duration + 1.0:
                print(f"[Short Condenser] Existing fast-forwarded video found: {dest_file.name} ({existing_dur:.1f}s). Reusing.")
                return dest_file

        vf_filter = f"setpts=PTS/{speed_factor:.5f}"
        has_audio = has_audio_stream(video_path)

        cmd_nvenc = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-filter:v", vf_filter,
            "-c:v", "hevc_nvenc", "-preset", "p4", "-b:v", "5000k",
            "-t", f"{max_duration:.2f}"
        ]
        if has_audio:
            cmd_nvenc.extend(["-filter:a", build_atempo_filter(speed_factor), "-c:a", "aac", "-b:a", "192k"])
        else:
            cmd_nvenc.append("-an")
        cmd_nvenc.append(str(dest_file))

        print(f"[Short Condenser] Running FFmpeg GPU fast-forward ({speed_factor:.2f}x)...")
        t0 = time.time()
        try:
            res = subprocess.run(cmd_nvenc, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if res.returncode != 0:
                raise RuntimeError(res.stderr[-500:] if res.stderr else "NVENC failed")
        except Exception as e:
            print(f"[Short Condenser] NVENC failed ({e}), falling back to libx264...")
            cmd_cpu = [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-filter:v", vf_filter,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-t", f"{max_duration:.2f}"
            ]
            if has_audio:
                cmd_cpu.extend(["-filter:a", build_atempo_filter(speed_factor), "-c:a", "aac", "-b:a", "192k"])
            else:
                cmd_cpu.append("-an")
            cmd_cpu.append(str(dest_file))
            subprocess.run(cmd_cpu, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)

        elapsed = time.time() - t0
        final_dur = get_video_duration(dest_file)
        print(f"[Short Condenser] SUCCESS! Fast-forwarded video ready: {dest_file.name} ({final_dur:.1f}s in {elapsed:.1f}s)")
        return dest_file

    def run(
        self,
        url_or_file: str,
        target_lang: str = "Hindi",
        voice: Optional[str] = None,
        base_speed: float = 1.0,
        batch_size: int = 35,
        temperature: float = 0.4,
        force: bool = False,
        dub_mode: str = "block_aligned",
        preserve_bgm: bool = True,
        clean_subtitles: bool = True,
        remove_watermark: bool = False,
        bgm_volume: float = 1.05,
        enable_metadata: bool = True,
        style: str = "viral",
        fit_short: bool = False,
        max_duration: float = 58.0
    ) -> Dict[str, Any]:
        """
        Execute full end-to-end pipeline:
        Download -> Clean Subtitles/Watermarks -> Transcribe -> Translate -> Stem Separation -> Synthesize & Dub.
        """
        active_style = (style or "viral").lower()
        active_tts = self._resolve_tts(target_lang)
        is_omni = isinstance(active_tts, OmniVoiceTTS)
        is_google = isinstance(active_tts, GoogleGeminiTTS)
        is_elevenlabs = isinstance(active_tts, ElevenLabsTTS) or self.tts_engine in ("elevenlabs", "eleven_labs", "11labs")
        is_sarvam = isinstance(active_tts, SarvamTTS)

        # Determine voice according to target language and active TTS engine
        if is_elevenlabs:
            selected_voice = voice if (voice and voice.lower() not in ("shubh", "arvind", "amartya", "puck", "ludo", "enzo")) else "roger"

        elif is_google:
            selected_voice = voice if (voice and voice.lower() not in ("shubh", "arvind", "amartya", "puck")) else "Ludo"
        elif is_omni:
            selected_voice = voice or "male_deep"
        elif is_sarvam:
            selected_voice = voice or "shubh"
        else:
            selected_voice = voice or "shubh"

        if is_omni:
            engine_name = f"OmniVoice (k2-fsa, {selected_voice})"
        elif is_elevenlabs:
            engine_name = f"ElevenLabs v4 ({selected_voice})"
        elif is_google:
            engine_name = f"Google Gemini TTS ({selected_voice})"
        elif is_sarvam:
            engine_name = f"Sarvam AI Bulbul v3 ({selected_voice})"
        else:
            engine_name = f"Kokoro ({selected_voice})"


        speed = 1.15 if is_sarvam and base_speed == 1.28 else base_speed

        pipeline_t0 = time.time()
        timings = {}

        print("\n" + "=" * 50)
        print(" [Dubbing Studio] STARTING END-TO-END PIPELINE")
        print(f" Source URL/File : {url_or_file}")
        print(f" Target Language : {target_lang}")
        print(f" TTS Engine      : {engine_name}")
        print(f" Voice & Speed   : {selected_voice} @ {speed}x")
        print(f" Preserve BGM/SFX: {preserve_bgm} (Meta Demucs)")
        print(f" Clean Subtitles : {clean_subtitles} (Luminance-Suppressed Blur)")
        print(f" Output Folder   : {self.output_dir}")
        print("=" * 50)

        # -------------------------------------------------------------
        # Step 1: Download Video via Downloader API
        # -------------------------------------------------------------
        video_path = self.downloader.download_video(url_or_file, output_dir=self.input_dir)

        # -------------------------------------------------------------
        # Step 1.5: Fit Short Condenser (Fast-forward if duration > max_duration)
        # -------------------------------------------------------------
        if fit_short:
            video_path = self._condense_to_short(video_path, max_duration=max_duration, force=force)

        base_stem = video_path.stem
        if base_stem.endswith("_clean"):
            base_stem = base_stem[:-6]
        clean_slug = sanitize_filename(base_stem)
        print(f"[Pipeline] Clean Video Slug: {clean_slug}")

        # Check if already fully processed and final video exists
        lang_tag = "hindi" if target_lang.lower().startswith("hi") or "hinglish" in target_lang.lower() else target_lang.lower()
        meta_json_file = self.metadata_dir / f"{clean_slug}_{lang_tag}_metadata.json"
        cached_final_vid = None
        cached_meta = None
        if not force:
            if meta_json_file.exists():
                try:
                    cached_meta = json.loads(meta_json_file.read_text(encoding="utf-8"))
                    clean_title_fn = sanitize_title_for_filename(cached_meta.get("title", ""))
                    if clean_title_fn:
                        candidate = self.final_dir / f"{clean_title_fn}.mp4"
                        if candidate.exists() and candidate.stat().st_size > 100000:
                            cached_final_vid = candidate
                except Exception:
                    pass

            if cached_final_vid is None:
                for candidate in self.final_dir.glob(f"{clean_slug}*.mp4"):
                    if candidate.stat().st_size > 100000:
                        cached_final_vid = candidate
                        break

            if cached_final_vid is not None and fit_short:
                cv_dur = get_video_duration(cached_final_vid)
                if cv_dur > max_duration + 1.0:
                    print(f"[Pipeline] Existing dubbed video ({cached_final_vid.name}, {cv_dur:.1f}s) exceeds short max duration ({max_duration:.1f}s). Re-processing...")
                    cached_final_vid = None

            if cached_final_vid is not None:
                print(f"[Pipeline] Existing dubbed video found: {cached_final_vid.name}. Skipping processing.")
                clean_vid_cand = self.clean_dir / f"{clean_slug}_clean.mp4"
                return {
                    "video_path": clean_vid_cand if clean_vid_cand.exists() else video_path,
                    "raw_srt": self.subtitles_dir / f"{clean_slug}_raw.srt",
                    "dubbed_srt": self.subtitles_dir / f"{clean_slug}_{lang_tag}.srt",
                    "sfx_track": None,
                    "final_video": cached_final_vid,
                    "metadata": cached_meta or {},
                    "clean_title": clean_slug,
                    "translation_report": {"cached": True}
                }

        # -------------------------------------------------------------
        # Step 2: Transcribe Video Audio via Faster-Whisper GPU
        # -------------------------------------------------------------
        # Step 2: Transcribe Video Audio via Faster-Whisper GPU
        # -------------------------------------------------------------
        raw_srt = self.subtitles_dir / f"{clean_slug}_raw.srt"
        legacy_raw_srt = self.output_dir / f"{base_stem}.srt"
        if not force and not raw_srt.exists() and legacy_raw_srt.exists():
            import shutil
            shutil.copy2(str(legacy_raw_srt), str(raw_srt))

        t_trans = time.time()
        self.transcriber.transcribe(video_path, output_srt=raw_srt, force=force)
        timings["1. Audio Transcription"] = (time.time() - t_trans, "Local GPU (Faster-Whisper)")

        # -------------------------------------------------------------
        # Step 2.5: Start Background Video Cleaner (Luminance Blur)
        # -------------------------------------------------------------
        inpaint_future = None
        inpaint_executor = None
        t_clean_start = time.time()

        if clean_subtitles:
            if video_path.stem.endswith("_clean"):
                clean_video_path = video_path
            else:
                clean_video_path = self.clean_dir / f"{clean_slug}_clean.mp4"
                legacy_clean_path = self.output_dir / f"{video_path.stem}_clean.mp4"
                if not force and not clean_video_path.exists() and legacy_clean_path.exists() and legacy_clean_path.stat().st_size > 50000:
                    import shutil
                    shutil.copy2(str(legacy_clean_path), str(clean_video_path))

            if not force and clean_video_path.exists() and clean_video_path.stat().st_size > 50000:
                print(f"[Pipeline] Existing clean video found: {clean_video_path.name}")
                clean_video_target = clean_video_path
                timings["4. Subtitle Removal Blur"] = (0.0, "Cached (Local Disk)")
            else:
                def _run_cleaner():
                    try:
                        try:
                            from tools.remove_subtitles import remove_subtitles
                        except ImportError:
                            from remove_subtitles import remove_subtitles
                        print("\n[Track 2: Video Cleaner] Running Clause-Sampled Luminance-Suppressed Subtitle Blur in parallel...")
                        success = remove_subtitles(
                            input_video=str(video_path),
                            output_video=str(clean_video_path),
                            srt_file=str(raw_srt)
                        )
                        if success and clean_video_path.exists():
                            print(f"[Track 2: Video Cleaner] Finished clean video: {clean_video_path.name}")
                            return clean_video_path
                        else:
                            print("[Track 2: Video Cleaner] Warning: Subtitle blur did not finish, fallback to original.")
                            return video_path
                    except Exception as e:
                        print(f"[Track 2: Video Cleaner] Warning: Subtitle cleaner error ({e}), fallback to original.")
                        return video_path

                inpaint_executor = ThreadPoolExecutor(max_workers=1)
                inpaint_future = inpaint_executor.submit(_run_cleaner)
                clean_video_target = None
        else:
            clean_video_target = video_path

        # -------------------------------------------------------------
        # Track 1: Audio / Translation / Metadata / TTS
        # -------------------------------------------------------------

        # Step 3: Translate & Transcreate via Gemini SDK
        t_translat = time.time()
        effective_target_lang = (
            DEFAULT_TARGET_LANGUAGE if target_lang.strip().lower() in ("hindi", "hi", "hinglish") else target_lang
        )
        lang_tag = "hindi" if target_lang.lower().startswith("hi") or "hinglish" in target_lang.lower() else target_lang.lower()
        style_suffix = f"_{active_style}" if active_style != "viral" else ""
        dubbed_srt = self.subtitles_dir / f"{clean_slug}_{lang_tag}{style_suffix}.srt"
        legacy_dubbed_srt = self.output_dir / f"{base_stem}_{lang_tag}{style_suffix}.srt"
        if not force and not dubbed_srt.exists() and legacy_dubbed_srt.exists():
            import shutil
            shutil.copy2(str(legacy_dubbed_srt), str(dubbed_srt))

        if not force and dubbed_srt.exists() and dubbed_srt.stat().st_size > 100:
            print(f"[Pipeline] Existing dubbed SRT found ({active_style}): {dubbed_srt.name}. Skipping translation.")
            translated_srt = dubbed_srt.read_text(encoding="utf-8")
            report = {"skipped": True}
            timings["2. Script Transcreation"] = (time.time() - t_translat, "Cached (Local Disk)")
        else:
            translated_srt, report = self.translator.translate_and_rewrite_srt(
                srt_input=raw_srt,
                target_language=effective_target_lang,
                batch_size=batch_size,
                temperature=temperature,
                style=active_style,
                tts_engine=self.tts_engine
            )
            dubbed_srt.write_text(translated_srt, encoding="utf-8")
            timings["2. Script Transcreation"] = (time.time() - t_translat, f"Cloud API (Gemini - {active_style})")
            print(f"[Pipeline] Dubbed Devanagari SRT ({active_style}) saved to: {dubbed_srt.name}")

        # Step 3.5: Generate Catchy Hook, Title, Description, Tags & Hashtags via Gemini (Disabled by default)
        meta_json_file = self.metadata_dir / f"{clean_slug}_{lang_tag}_metadata.json"
        legacy_meta_file = self.output_dir / f"{base_stem}_{lang_tag}_metadata.json"
        if not force and not meta_json_file.exists() and legacy_meta_file.exists():
            import shutil
            shutil.copy2(str(legacy_meta_file), str(meta_json_file))

        def _fetch_metadata():
            meta = None
            if not enable_metadata:
                return {
                    "title": clean_slug,
                    "description": "",
                    "tags": [],
                    "hashtags": []
                }
            if not force and meta_json_file.exists() and meta_json_file.stat().st_size > 50:
                try:
                    meta = json.loads(meta_json_file.read_text(encoding="utf-8"))
                except Exception:
                    meta = None

            if not meta:
                clean_script = "\n".join([
                    line.strip() for line in translated_srt.splitlines()
                    if line.strip() and not line.strip().isdigit() and "-->" not in line
                ])
                try:
                    meta = self.translator.generate_metadata(
                        script_text=clean_script,
                        target_language=target_lang,
                        original_title=clean_slug,
                        temperature=temperature
                    )
                except Exception as e:
                    print(f"[Pipeline] Warning: Metadata generation error ({e}). Using fallback metadata.")
                    meta = {
                        "title": clean_slug,
                        "description": clean_script[:200] + "...",
                        "tags": ["shorts", "viral", "video"],
                        "hashtags": ["#Shorts", "#Viral"]
                    }
                meta_json_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            return meta

        if enable_metadata:
            meta_executor = ThreadPoolExecutor(max_workers=1)
            meta_future = meta_executor.submit(_fetch_metadata)
            print("[Pipeline Track Sync] Fired Metadata Generation in parallel with audio/TTS pipeline...")
        else:
            meta_executor = None
            meta_future = None
            print("[Pipeline] Metadata generation skipped.")

        # -------------------------------------------------------------
        # Step 4: Extract Stems via DBS-TIGER (Preserve Isolated Foley SFX, Exclude BGM)
        # -------------------------------------------------------------
        sfx_track = None
        t_stem = time.time()
        if preserve_bgm:
            try:
                stems = self.separator.separate_audio(
                    video_path,
                    output_dir=self.stems_dir,
                    clean_name=clean_slug,
                    force=force
                )
                # Strictly use isolated Foley SFX (sfx.wav) from DBS-TIGER-DnR so original Chinese music is excluded
                sfx_track = stems.get("sfx")
                if sfx_track:
                    print(f"[Pipeline Audio Sync] Isolated Foley SFX track selected: {sfx_track.name}")
                timings["3. Stem Separation (DBS-TIGER-DnR)"] = (time.time() - t_stem, "Local GPU (DBS-TIGER-DnR)")
            except Exception as e:
                print(f"[Pipeline] Warning: Stem separation failed ({e}). Proceeding with clean voiceover.")
                timings["3. Stem Separation (DBS-TIGER-DnR)"] = (time.time() - t_stem, "Failed/Skipped")

        # -------------------------------------------------------------
        # Step 5: Wait for Parallel Video Cleaner & Dub Final Video
        # -------------------------------------------------------------
        if inpaint_future is not None:
            print("\n[Pipeline Track Sync] Waiting for Parallel Video Cleaner (Luminance Blur) track to complete...")
            try:
                video_for_dubbing = inpaint_future.result(timeout=600)
                timings["4. Subtitle Removal Blur"] = (time.time() - t_clean_start, "Local GPU (RapidOCR, Parallel)")
            except Exception as e:
                print(f"[Pipeline Track Sync] Video cleaner future failed ({e}), using original video.")
                video_for_dubbing = video_path
                timings["4. Subtitle Removal Blur"] = (time.time() - t_clean_start, "Fallback to Original")
            finally:
                if inpaint_executor:
                    inpaint_executor.shutdown(wait=False)
        else:
            video_for_dubbing = clean_video_target or video_path

        # Dynamic Subtitle Placement: Center captions exactly over the RapidOCR detected plate
        detected_margin_v = 405
        box_candidates = [
            Path(video_for_dubbing).with_name(f"{Path(video_for_dubbing).stem}_box.json"),
            self.clean_dir / f"{clean_slug}_clean_box.json",
            self.clean_dir / f"{Path(video_for_dubbing).stem}_box.json"
        ]
        for bc in box_candidates:
            if bc.exists():
                try:
                    b_data = json.loads(bc.read_text(encoding="utf-8"))
                    if "y_center" in b_data:
                        detected_margin_v = max(180, 1920 - int(b_data["y_center"]) - 65)
                        print(f"[Pipeline Subtitle Alignment] Loaded dynamic placement: MarginV={detected_margin_v} (Center Y: {b_data.get('y_center')}px) from {bc.name}")
                        break
                    elif "margin_v" in b_data:
                        detected_margin_v = max(180, int(b_data["margin_v"]) - 30)
                        print(f"[Pipeline Subtitle Alignment] Loaded dynamic placement: MarginV={detected_margin_v} (Adjusted down for visual center) from {bc.name}")
                        break
                except Exception:
                    pass

        # Final video placed STRICTLY in final_videos/ with clean filename
        style_suffix = f"_{active_style}" if active_style != "viral" else ""
        if "chirp" in self.tts_engine.lower():
            tts_suffix = "_chirp"
        elif "elevenlabs" in self.tts_engine.lower() or "11labs" in self.tts_engine.lower():
            tts_suffix = "_elevenlabs"
        elif "google" in self.tts_engine.lower() or "gemini" in self.tts_engine.lower():
            tts_suffix = "_google"
        else:
            tts_suffix = ""
        final_video = self.final_dir / f"{clean_slug}_{lang_tag}{style_suffix}{tts_suffix}_dubbed.mp4"

        # Resolve Copyright-Free Background Music from assets/background_audio/
        bgm_free_track = self._resolve_royalty_free_bgm()
        if bgm_free_track:
            print(f"[Pipeline Audio Sync] Royalty-Free BGM selected: {bgm_free_track.name}")

        normalized_mode = (dub_mode or "block_aligned").lower()
        t_dub = time.time()

        if normalized_mode in ("block_aligned", "block", "blocks", "aligned"):
            print(f"\n[Pipeline Dub Mode] Engaging Block-Aligned Dubbing Engine ({active_style.upper()}, Uniform tempo, max 200ms pauses, 0s tail silence)...")
            from .block_aligner import align_video_and_audio_blocks
            video_work_dir = self.stems_dir / f"block_align_{clean_slug}"
            final_video = align_video_and_audio_blocks(
                clean_video_path=Path(video_for_dubbing),
                srt_path=Path(dubbed_srt),
                output_video_path=Path(final_video),
                sfx_path=sfx_track,
                bgm_path=bgm_free_track,
                voice=selected_voice,
                engine=self.tts_engine,
                work_dir=video_work_dir,
                max_silence_sec=0.20
            )
            if "_elevenlabs" in Path(final_video).name:
                self.tts_engine = "elevenlabs"
            timings["5. Voiceover Synthesis & Mux"] = (time.time() - t_dub, f"Block-Aligned {self.tts_engine.capitalize()} + NVENC")


        elif normalized_mode in ("paragraph", "single_narrator", "narrator", "continuous"):
            print(f"\n[Pipeline Dub Mode] Engaging Paragraph Continuous Dubbing Engine ({active_style.upper()}, Method 1 Infinite Loop, 0s tail silence)...")
            from dub_single_narrator import run_single_narrator_pipeline
            run_single_narrator_pipeline(
                video_path=str(video_for_dubbing),
                speaker=selected_voice or "shubh",
                pace=speed,
                target_end_margin=0.00,  # Zero dead air on the final line!
                force=force,
                engine=self.tts_engine,
                voice=selected_voice,
                dubbed_srt=dubbed_srt,
                output_video_path=final_video,
                sfx_path=sfx_track,
                bg_music_path=bgm_free_track,
                work_dir=self.stems_dir,
                margin_v=detected_margin_v,
                style=active_style
            )
            timings["5. Voiceover Synthesis & Mux"] = (time.time() - t_dub, f"Paragraph Single-Narrator + NVENC")

        else:
            # Fallback for slice / legacy modes
            dub_kwargs = {"work_dir": self.stems_dir, "margin_v": detected_margin_v}
            dub_kwargs["mode"] = normalized_mode
            dub_kwargs["enable_autotag"] = True
            if sfx_track:
                dub_kwargs["sfx_path"] = sfx_track
            if bgm_free_track:
                dub_kwargs["bgm_path"] = bgm_free_track
                dub_kwargs["bgm_volume"] = bgm_volume

            try:
                active_tts.synthesize_and_dub(
                    dubbed_srt=dubbed_srt,
                    original_video=video_for_dubbing,
                    final_video=final_video,
                    voice=selected_voice,
                    lang=target_lang,
                    base_speed=speed,
                    **dub_kwargs
                )
                timings["5. Voiceover Synthesis & Mux"] = (time.time() - t_dub, f"Cloud TTS + Local NVENC ({engine_name})")
            except Exception as e:
                err_str = str(e)
                if is_google and ("429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower() or "failed to synthesize" in err_str.lower()):
                    print(f"\n[Pipeline Warning] Google Gemini TTS Free Tier daily quota limit reached!")
                    print(f"[Pipeline Failover] Seamlessly failing over to Sarvam AI (Bulbul v3, voice: shubh) for native Hindi dubbing...")
                    sarvam_voice = "shubh" if target_lang.lower().startswith("hi") else "shubh"
                    sarvam_tts = SarvamTTS()
                    sarvam_tts.synthesize_and_dub(
                        dubbed_srt=dubbed_srt,
                        original_video=video_for_dubbing,
                        final_video=final_video,
                        voice=sarvam_voice,
                        lang=target_lang,
                        base_speed=speed,
                        mode="slice",
                        sfx_path=sfx_track,
                        bgm_path=bgm_free_track,
                        work_dir=self.stems_dir,
                        margin_v=detected_margin_v
                    )
                    timings["5. Voiceover Synthesis & Mux"] = (time.time() - t_dub, "Cloud TTS (Sarvam Failover) + NVENC")
                else:
                    raise

        # -------------------------------------------------------------
        # Step 6: Collect Concurrent Metadata Result & Rename Final Video
        # -------------------------------------------------------------
        metadata = None
        if enable_metadata and meta_future:
            t_meta_wait = time.time()
            try:
                metadata = meta_future.result(timeout=180)
                timings["6. Social Metadata"] = (time.time() - t_meta_wait, "Cloud API (Gemini, Parallel)")
            except Exception as e:
                print(f"[Pipeline] Warning: Metadata background task failed or timed out ({e}). Using fallback.")
                metadata = {
                    "title": f"{clean_slug} (3D Animation In Hindi) #shorts",
                    "description": "",
                    "tags": ["shorts", "viral", "video"],
                    "hashtags": ["#Shorts", "#Viral"]
                }
                timings["6. Social Metadata"] = (0.0, "Fallback Default")
            finally:
                if meta_executor:
                    meta_executor.shutdown(wait=False)

            print("\n" + "-" * 55)
            print(" [Social Metadata Generated (Concurrent)]")
            print(f" Title       : {metadata.get('title')}")
            print(f" Description : {metadata.get('description')}")
            print(f" Tags        : {', '.join(metadata.get('tags', [])[:8])}")
            print(f" Hashtags    : {' '.join(metadata.get('hashtags', [])[:6])}")
            print("-" * 55 + "\n")
        else:
            metadata = {
                "title": f"{clean_slug} (3D Animation In Hindi) #shorts",
                "description": "",
                "tags": [],
                "hashtags": []
            }
            timings["6. Social Metadata"] = (0.0, "Skipped")

        # Rename final dubbed video to carry the Title in its filename
        if metadata and metadata.get("title") and final_video.exists():
            clean_title_fn = sanitize_title_for_filename(metadata["title"])
            if clean_title_fn:
                titled_video = final_video.with_name(f"{clean_title_fn}.mp4")
                if final_video != titled_video:
                    if titled_video.exists():
                        try:
                            titled_video.unlink()
                        except Exception:
                            pass
                    try:
                        final_video.rename(titled_video)
                        final_video = titled_video
                        print(f"[Pipeline Final Video] Renamed to Title filename: {final_video.name}")
                    except Exception as e:
                        print(f"[Pipeline] Warning: Could not rename final video to title ({e})")

        # Mirror final dubbed video to Google Drive final_videos/ if mounted
        drive_base = Path("H:/My Drive/douyin")
        if drive_base.exists() and final_video.exists():
            drive_final_dir = drive_base / "final_videos"
            drive_final_dir.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(str(final_video), str(drive_final_dir / final_video.name))
            print(f"[Google Drive Sync] Synced final dubbed video to: {drive_final_dir / final_video.name}")

        total_elapsed = time.time() - pipeline_t0
        print("\n" + "=" * 70)
        print(" [Dubbing Studio] PIPELINE COMPLETED SUCCESSFULLY!")
        print(f" Final Dubbed Video: {final_video}")
        print("=" * 70)
        print(" [Pipeline Execution Profiling & Telemetry Report]")
        print(f" Video Slug : {clean_slug}")
        print(f" Total Wall-Clock Time: {total_elapsed:.1f}s ({total_elapsed/60:.2f} min)")
        print("-" * 70)
        print(f" {'#':<3} {'Pipeline Stage':<32} {'Environment':<24} {'Elapsed':>8}")
        print("-" * 70)
        for idx, (stg, (dur, env)) in enumerate(timings.items(), 1):
            dur_str = f"{dur:.1f}s" if dur > 0 else "0.0s (cached)"
            print(f" {idx:<3} {stg:<32} {env:<24} {dur_str:>8}")
        print("=" * 70 + "\n")

        return {
            "video_path": video_for_dubbing,
            "raw_srt": raw_srt,
            "dubbed_srt": dubbed_srt,
            "sfx_track": sfx_track,
            "final_video": final_video,
            "metadata": metadata,
            "clean_title": clean_slug,
            "translation_report": report
        }

    def _resolve_royalty_free_bgm(self) -> Optional[Path]:
        """Finds a royalty-free background music track from assets/background_audio/."""
        bg_dirs = [
            Path("assets/background_audio"),
            Path(__file__).resolve().parent.parent / "assets/background_audio",
        ]
        for bd in bg_dirs:
            if bd.exists():
                tracks = sorted([f for f in bd.glob("*.mp3")] + [f for f in bd.glob("*.wav")])
                if tracks:
                    return tracks[0]
        return None

    def run_folder(
        self,
        folder_path: Union[str, Path],
        target_lang: str = "Hindi",
        voice: Optional[str] = "shubh",
        base_speed: float = 1.0,
        batch_size: int = 35,
        temperature: float = 0.4,
        force: bool = False,
        dub_mode: str = "block_aligned",
        preserve_bgm: bool = True,
        clean_subtitles: bool = True,
        remove_watermark: bool = False,
        bgm_volume: float = 1.05,
        enable_metadata: bool = True,
        style: str = "viral",
        fit_short: bool = False,
        max_duration: float = 58.0
    ) -> Dict[str, Any]:
        """
        Batch-process an entire folder of videos:
        - If the folder directly contains videos, processes them into output/<folder_name>/
        - If the folder contains subdirectories with videos, processes each subfolder into output/<subfolder_name>/
        - In each output folder, maintains a central metadata.json linking each output video filename
          to its title, catchy hook, description, tags, hashtags, and source info.
        """
        in_path = Path(folder_path).resolve()
        if not in_path.exists():
            parent = in_path.parent
            if parent.exists():
                search_pat = re.sub(r"\?+", "*", in_path.name)
                matches = [d for d in parent.glob(search_pat) if d.is_dir()]
                if matches:
                    print(f"[Pipeline] Auto-matched directory '{matches[0].name}' for pattern '{in_path.name}'")
                    in_path = matches[0]
                else:
                    prefix = re.split(r"[\?*]", in_path.name)[0].rstrip("-_")
                    if prefix:
                        prefix_matches = [d for d in parent.glob(f"{prefix}*") if d.is_dir()]
                        if prefix_matches:
                            print(f"[Pipeline] Auto-matched directory '{prefix_matches[0].name}' for prefix '{prefix}'")
                            in_path = prefix_matches[0]

        if not in_path.exists():
            raise FileNotFoundError(f"Input directory does not exist: {in_path}")

        video_exts = {".mp4", ".mov", ".mkv", ".webm"}

        direct_videos = [
            f for f in in_path.iterdir()
            if f.is_file() and f.suffix.lower() in video_exts
            and not f.stem.endswith("_dubbed")
            and not f.stem.endswith("_clean")
        ]

        if direct_videos:
            folders_to_process = [in_path]
        else:
            subdirs = [d for d in in_path.iterdir() if d.is_dir()]
            folders_to_process = [
                d for d in subdirs
                if any(
                    f.is_file() and f.suffix.lower() in video_exts
                    and not f.stem.endswith("_dubbed")
                    and not f.stem.endswith("_clean")
                    for f in d.iterdir()
                )
            ]

        if not folders_to_process:
            print(f"[Pipeline] No video files found in {in_path} or its immediate subfolders.")
            return {}

        results = {}
        original_base_output = self.output_dir

        for cur_folder in folders_to_process:
            if cur_folder.resolve() == self.input_dir.resolve() or cur_folder.name.lower() in ["input", "."]:
                target_out_dir = original_base_output
            else:
                folder_clean_name = cur_folder.name
                target_out_dir = original_base_output / folder_clean_name
            target_out_dir.mkdir(parents=True, exist_ok=True)
            self._setup_output_dirs(target_out_dir)

            metadata_path = self.metadata_dir / "metadata.json"
            folder_metadata = {}
            if metadata_path.exists():
                try:
                    folder_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                except Exception:
                    folder_metadata = {}

            video_files = sorted([
                f for f in cur_folder.iterdir()
                if f.is_file() and f.suffix.lower() in video_exts
                and not f.stem.endswith("_dubbed")
                and not f.stem.endswith("_clean")
            ])

            print("\n" + "#" * 65)
            print(f" [Batch Folder Processing] Folder: {cur_folder.name}")
            print(f" Total Videos to Process: {len(video_files)}")
            print(f" Output Folder: {target_out_dir}")
            print(f" Master Metadata JSON: {metadata_path}")
            print("#" * 65 + "\n")

            folder_results = []
            for idx, vid in enumerate(video_files, start=1):
                print(f"\n=======================================================")
                print(f" >>> [{idx}/{len(video_files)}] Processing Video: {vid.name}")
                print(f"=======================================================")
                self.output_dir = target_out_dir
                # Check key pool before each video:
                # If ElevenLabs was selected but keys ran out of quota, automatically switch to Google Gemini Flash 3.8
                if self.tts_engine in ("elevenlabs", "eleven_labs", "11labs"):
                    if not get_active_elevenlabs_keys() and get_active_gemini_keys():
                        print(f"\n[Batch Folder Fallback] ElevenLabs keys exhausted! Switching batch engine to Google Gemini Flash 3.8 TTS...")
                        self.tts_engine = "google"
                elif self.tts_engine in ("google", "gemini"):
                    if not get_active_gemini_keys() and get_active_elevenlabs_keys():
                        print(f"\n[Batch Folder Fallback] Google Gemini keys exhausted! Switching batch engine to ElevenLabs (eleven_v4)...")
                        self.tts_engine = "elevenlabs"
                try:
                    res = self.run(

                        url_or_file=str(vid),
                        target_lang=target_lang,
                        voice=voice,
                        base_speed=base_speed,
                        batch_size=batch_size,
                        temperature=temperature,
                        force=force,
                        dub_mode=dub_mode,
                        preserve_bgm=preserve_bgm,
                        clean_subtitles=clean_subtitles,
                        remove_watermark=remove_watermark,
                        bgm_volume=bgm_volume,
                        enable_metadata=enable_metadata,
                        style=style,
                        fit_short=fit_short,
                        max_duration=max_duration
                    )

                    folder_results.append(res)
                except Exception as e:
                    print(f"[Pipeline ERROR] Failed processing video '{vid.name}': {e}")
                    import traceback
                    traceback.print_exc()

            # Compile single master metadata JSON carrying:
            # - number_of_videos
            # - titles of the videos
            # - descriptions of the videos
            # - tags (up to 3 high-relevance SEO tags for YouTube)
            master_videos_list = []
            for r in folder_results:
                if not (r.get("final_video") and Path(r["final_video"]).exists()):
                    continue
                meta = r.get("metadata", {})
                if not meta and r.get("clean_title"):
                    cand_meta = self.metadata_dir / f"{r['clean_title']}_hindi_metadata.json"
                    if cand_meta.exists():
                        try:
                            meta = json.loads(cand_meta.read_text(encoding="utf-8"))
                        except Exception:
                            meta = {}

                video_title = meta.get("title", Path(r["final_video"]).stem)
                video_desc = meta.get("description", "")
                seo_tags = clean_youtube_tags(meta.get("tags"), title=video_title)

                master_videos_list.append({
                    "title": video_title,
                    "description": video_desc,
                    "tags": seo_tags
                })

            master_json_data = {
                "number_of_videos": len(master_videos_list),
                "videos": master_videos_list
            }
            metadata_path.write_text(json.dumps(master_json_data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"\n[Pipeline Master Metadata] Successfully wrote master metadata.json ({len(master_videos_list)} videos with SEO tags) to: {metadata_path}")

            # Google Drive Synchronization:
            # The folder uploaded to Drive only has the final output videos with Title filenames,
            # and strictly one master JSON file carrying number_of_videos, titles, descriptions, and SEO tags.
            drive_base = Path("H:/My Drive/douyin")
            if drive_base.exists():
                drive_target_dir = drive_base / cur_folder.name
                drive_target_dir.mkdir(parents=True, exist_ok=True)
                print(f"\n[Google Drive Folder Sync] Synchronizing folder '{cur_folder.name}' to Drive: {drive_target_dir}")

                allowed_files = set()
                # 1. Sync final output videos
                for r in folder_results:
                    fpath = Path(r["final_video"])
                    if fpath.exists():
                        dest_video = drive_target_dir / fpath.name
                        shutil.copy2(str(fpath), str(dest_video))
                        allowed_files.add(fpath.name)
                        print(f"  [Drive Sync Video] Synced final output video: {fpath.name}")

                # 2. Sync single master metadata.json
                if metadata_path.exists():
                    shutil.copy2(str(metadata_path), str(drive_target_dir / "metadata.json"))
                    allowed_files.add("metadata.json")
                    print(f"  [Drive Sync Metadata] Synced single master metadata.json")

                # 3. Clean up non-final files to guarantee the folder uploaded to Drive ONLY has final output videos + metadata.json
                for item in list(drive_target_dir.iterdir()):
                    if item.name not in allowed_files:
                        try:
                            if item.is_file():
                                item.unlink()
                                print(f"  [Drive Cleanup] Removed non-final file: {item.name}")
                            elif item.is_dir():
                                shutil.rmtree(item)
                                print(f"  [Drive Cleanup] Removed extraneous subfolder: {item.name}")
                        except Exception as e:
                            print(f"  [Drive Cleanup Warning] Could not remove {item.name}: {e}")

            results[cur_folder.name] = {
                "output_dir": target_out_dir,
                "metadata_file": metadata_path,
                "processed_videos": folder_results
            }

        self.output_dir = original_base_output
        self._setup_output_dirs(original_base_output)
        return results


def main():
    parser = argparse.ArgumentParser(description="Douyin / TikTok Automated Dubbing Studio Pipeline")
    parser.add_argument("--url", type=str, default="", help="Douyin/TikTok video URL, path to local MP4, or folder")
    parser.add_argument("--folder", "--input-dir", type=str, default="", help="Directory containing videos or subfolders of videos to batch process")
    parser.add_argument("--reorganize", action="store_true", help="Reorganize and de-clutter existing output files into dedicated subfolders")
    parser.add_argument("--lang", type=str, default="Hindi", help="Target language (default: Hindi in native Devanagari for TTS, mapped to Roman Hinglish captions)")
    parser.add_argument("--voice", type=str, default="", help="Voice narrator (Google: Ludo (default) / Enzo / Charon | ElevenLabs: brian (default) / adam | Sarvam: shubh)")
    parser.add_argument("--block-aligned", action="store_true", help="Dub using block-aligned engine (SRT blocks, uniform audio pacing, max 200ms silences, 0s tail silence, 3-stem mixing)")
    parser.add_argument("--paragraph", action="store_true", help="Dub using paragraph continuous narrative engine (Method 1 Infinite Loop, silence compressor, uniform tempo, 0s tail silence)")
    parser.add_argument("--mode", type=str, choices=["block_aligned", "paragraph", "single_narrator", "slice", "flow", "auto"], default="block_aligned", help="Dubbing mode: 'block_aligned' (default: 1:1 visual lockstep, uniform pacing, 0s tail), 'paragraph' (continuous narrative), or 'slice'")
    parser.add_argument("--funny", action="store_true", help="Shortcut: Use hilarious desi street humor, cheap local Hindi jokes, and funny roast prompt")
    parser.add_argument("--style", type=str, default="viral", choices=["viral", "funny", "roast", "comedy"], help="Prompt style for Gemini ('viral' showrunner or 'funny' comedy roast)")
    parser.add_argument("--tts", "--tts-engine", type=str, default="elevenlabs", help="TTS Engine: 'elevenlabs' (default, ElevenLabs v4), 'google' (Google Flash 3.8 TTS fallback), 'sarvam', 'chirp', or 'omnivoice'")
    parser.add_argument("--elevenlabs", action="store_true", help="Shortcut: Use ElevenLabs v4 TTS engine")
    parser.add_argument("--speed", type=float, default=1.0, help="Speech speed multiplier (default: 1.0 for Sarvam, 1.28 for Kokoro)")
    parser.add_argument("--output", type=str, default="", help="Output directory (default: ./output)")
    parser.add_argument("--model", type=str, default="gemini-3.8-flash", help="Gemini model name for translation waterfall (default: gemini-3.8-flash)")
    parser.add_argument("--batch-size", type=int, default=35, help="Batch size for subtitle chunks")
    parser.add_argument("--no-bgm", action="store_true", help="Disable BGM/SFX preservation (clean voiceover only)")
    parser.add_argument("--no-clean", action="store_true", help="Disable automatic subtitle & watermark inpainting")
    parser.add_argument("--include-watermark", action="store_true", help="Also inpaint corner watermark (takes 2x longer, default: off)")
    parser.add_argument("--force", "--reloop", action="store_true", dest="force", help="Force re-transcription, re-translation, and re-separation")
    parser.add_argument("--metadata", action="store_true", default=True, help="Generate viral social media metadata via Gemini (default: True)")
    parser.add_argument("--bgm-volume", type=float, default=1.05, help="Background music volume multiplier")
    parser.add_argument("--no-metadata", action="store_true", default=False, help="Disable social metadata generation")
    parser.add_argument("--short", "-s", "--fit-short", action="store_true", help="Fast-forward video to fit strictly under 1 minute (<= 58s) before sending through pipeline")
    parser.add_argument("--max-duration", type=float, default=58.0, help="Target max duration in seconds when --short is enabled (default: 58.0s for YouTube Shorts / Reels)")
    args = parser.parse_args()

    if args.elevenlabs:
        args.tts = "elevenlabs"

    if not args.voice:
        if args.tts in ("elevenlabs", "eleven_labs", "11labs"):
            args.voice = "roger"
        elif args.tts in ("google", "gemini"):
            args.voice = "Ludo"

        elif args.tts in ("sarvam", "bulbul"):
            args.voice = "shubh"

    out_folder = Path(args.output) if args.output else Path.cwd() / "output"
    in_folder = Path(args.input_dir) if getattr(args, "input_dir", None) else None
    pipeline = DubbingPipeline(input_dir=in_folder, output_dir=out_folder, gemini_model=args.model, tts_engine=args.tts)


    if args.reorganize:
        pipeline.reorganize_existing_output()
        print("[Pipeline] Reorganization complete!")
        if not (args.url or args.folder):
            return

    input_target = args.folder or args.url
    if not input_target:
        parser.error("Please provide either --url or --folder")

    target_path = Path(input_target)
    is_url = bool(args.url) or input_target.lower().startswith("http://") or input_target.lower().startswith("https://")
    is_folder_input = (not is_url) and (
        bool(args.folder)
        or ("?" in input_target)
        or ("*" in input_target)
        or (target_path.exists() and target_path.is_dir())
        or (not target_path.suffix)
    )
    should_gen_meta = not args.no_metadata
    if args.block_aligned:
        selected_dub_mode = "block_aligned"
    elif args.paragraph:
        selected_dub_mode = "paragraph"
    else:
        selected_dub_mode = args.mode or "block_aligned"

    selected_style = "funny" if args.funny else args.style
    is_short = bool(args.short)
    max_dur = float(args.max_duration)

    if is_folder_input:
        pipeline.run_folder(
            folder_path=target_path,
            target_lang=args.lang,
            voice=args.voice if args.voice else None,
            base_speed=args.speed,
            batch_size=args.batch_size,
            force=args.force,
            dub_mode=selected_dub_mode,
            preserve_bgm=not args.no_bgm,
            clean_subtitles=not args.no_clean,
            remove_watermark=args.include_watermark,
            bgm_volume=args.bgm_volume,
            enable_metadata=should_gen_meta,
            style=selected_style,
            fit_short=is_short,
            max_duration=max_dur
        )
    else:
        pipeline.run(
            url_or_file=input_target,
            target_lang=args.lang,
            voice=args.voice if args.voice else None,
            base_speed=args.speed,
            batch_size=args.batch_size,
            force=args.force,
            dub_mode=selected_dub_mode,
            preserve_bgm=not args.no_bgm,
            clean_subtitles=not args.no_clean,
            remove_watermark=args.include_watermark,
            bgm_volume=args.bgm_volume,
            enable_metadata=should_gen_meta,
            style=selected_style,
            fit_short=is_short,
            max_duration=max_dur
        )


if __name__ == "__main__":
    main()
