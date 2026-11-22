#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dubbing_studio/pipeline.py
==========================
End-to-end automated Dubbing Pipeline orchestrator.
Coordinates:
  [Step 1] Download: Douyin/TikTok video via DownloaderAPI
  [Step 2] Transcribe: Speech-to-SRT via Faster-Whisper GPU
  [Step 2.5] Subtitle Cleaner: Parallel Per-Subtitle Tight RapidOCR Luminance Blur
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
from typing import Optional, Union, Dict, Any, List, Tuple
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
from .key_pool import (
    get_active_gemini_keys,
    get_active_sarvam_keys,
    get_active_elevenlabs_keys,
    reset_exhausted_elevenlabs_keys,
)
from .anti_accent import balance_consecutive_english
from .video_registry import VideoRegistry, drive_relative

configure_runtime_environment()



def normalize_aspect_ratio(ratio: Optional[str]) -> str:
    """Normalize --ratio option to 'reel' (default 9:16) or 'square' (1:1)."""
    val = str(ratio or "reel").strip().lower()
    if val in ("square", "1:1", "1/1", "sq"):
        return "square"
    return "reel"


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


def resolve_google_drive_base() -> Optional[Path]:
    """Find mounted Google Drive base directory across drive letters (e.g., I:/, H:/, G:/)."""
    import string
    candidates = [
        Path("I:/My Drive/douyin"),
        Path("H:/My Drive/douyin"),
        Path("G:/My Drive/douyin"),
    ]
    for d in candidates:
        if d.exists() and d.is_dir():
            return d
    for letter in string.ascii_uppercase:
        p = Path(f"{letter}:/My Drive/douyin")
        if p.exists() and p.is_dir():
            return p
    return None


def _extract_batch_urls(raw_text: str) -> List[str]:
    """Extract and deduplicate Douyin/TikTok HTTP(S) URLs while preserving input order."""
    if not raw_text:
        return []
    candidates = re.findall(r"https?://[^\s\"'<>\\^`{|},，。；！？、【】《》]+", raw_text)
    if not candidates:
        # Also support pasted bare domain URLs without scheme (e.g. v.douyin.com/...)
        for token in re.split(r"[\s,;]+", raw_text.strip()):
            tok = token.strip().strip("'\"")
            if tok and any(host in tok.lower() for host in ("douyin.com", "tiktok.com", "iesdouyin.com")):
                if not tok.lower().startswith(("http://", "https://")):
                    tok = f"https://{tok}"
                candidates.append(tok)

    seen = set()
    urls: List[str] = []
    for raw_url in candidates:
        cleaned = raw_url.strip().rstrip(").,;!?\"'")
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            urls.append(cleaned)
    return urls


def _sanitize_batch_name(raw_name: str, default_prefix: str = "batch") -> str:
    """Sanitize a batch folder name for safe local & Google Drive folder creation."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", (raw_name or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        return f"{default_prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    return cleaned[:100].strip(" .") or f"{default_prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def _prompt_batch_inputs(default_batch_name: str = "") -> Tuple[str, List[str]]:
    """Interactively prompt the user for an optional batch folder name and a list of URLs."""
    print("\n" + "=" * 65)
    print(" [Dubbing Studio] BATCH URLS PROMPT")
    print("=" * 65)

    if default_batch_name and default_batch_name.strip():
        batch_name = _sanitize_batch_name(default_batch_name)
        print(f" Batch Folder: {batch_name}")
    else:
        default_auto = _sanitize_batch_name("")
        raw_name = input(f" Batch folder name [Enter for '{default_auto}']: ").strip()
        batch_name = _sanitize_batch_name(raw_name) if raw_name else default_auto

    print("\n Paste all video URLs below (one per line or space-separated).")
    print(" Press Enter twice on empty lines, or type 'done', when finished:")

    lines: List[str] = []
    empty_streak = 0
    while True:
        try:
            line = input()
        except EOFError:
            break

        stripped = line.strip()
        if stripped.lower() in ("done", "end", "run", "go"):
            break
        if not stripped:
            empty_streak += 1
            if lines and empty_streak >= 2:
                break
            continue

        empty_streak = 0
        lines.append(line)

    urls = _extract_batch_urls("\n".join(lines))
    print(f"\n [Batch URLs] Captured {len(urls)} unique URL(s) for batch '{batch_name}'.")
    return batch_name, urls


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
        tts_voices_path: Optional[Union[str, Path]] = None,
        debug: bool = False,
        registry_db: Optional[Union[str, Path]] = None,
        enable_registry: bool = True,
    ):
        self.output_dir = Path(output_dir) if output_dir else Path.cwd() / "output"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.input_dir = Path(input_dir) if input_dir else (self.output_dir.parent / "input").resolve()
        self.input_dir.mkdir(parents=True, exist_ok=True)
        self.debug = debug or (os.getenv("DEBUG") in ("1", "true", "True")) or (os.getenv("DUBBING_DEBUG") in ("1", "true", "True"))
        self._setup_output_dirs(self.output_dir)

        self.downloader = DownloaderAPI()
        self.transcriber = Transcriber(model_size=model_size)
        self.translator = SRTDubTranslator(model=gemini_model)
        self.separator = AudioStemSeparator()
        self.tts_engine = (tts_engine or "elevenlabs").lower()
        has_sarvam_keys = bool(os.getenv("SARVAM_API_KEY") or os.getenv("SARVAM_API_KEYS"))
        self.sarvam_tts = SarvamTTS() if has_sarvam_keys else None
        self.omnivoice_tts = OmniVoiceTTS()
        try:
            self.kokoro_tts = KokoroTTS(model_path=tts_model_path, voices_path=tts_voices_path)
        except FileNotFoundError as e:
            if self.tts_engine == "kokoro":
                raise
            print(f"[Pipeline] Optional KokoroTTS unavailable ({e}); skipping.")
            self.kokoro_tts = None
        has_gemini_keys = bool(os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEYS"))
        self.google_tts = GoogleGeminiTTS() if has_gemini_keys else None
        active_elevenlabs_keys = get_active_elevenlabs_keys()
        self.elevenlabs_tts = ElevenLabsTTS() if active_elevenlabs_keys else None

        # Durable video index (local SQLite + JSON/CSV snapshots mirrored to Drive)
        self.registry = None
        if enable_registry:
            try:
                self.registry = VideoRegistry(registry_db)
                print(f"[Registry] Indexing all videos in: {self.registry.db_path}")
            except Exception as registry_err:
                print(f"[Registry] Warning: registry disabled ({registry_err})")


    def _setup_output_dirs(self, base_dir: Path):
        """
        Create dedicated, purpose-specific output folders.
        Final video is placed directly in its own channel folder (base_dir),
        NEVER in a final_videos/ subfolder.
        """
        self.final_dir = base_dir
        self.clean_dir = base_dir / "clean_videos"
        self.subtitles_dir = base_dir / "subtitles"
        self.metadata_dir = base_dir / "metadata"
        self.stems_dir = base_dir / "audio_stems"
        self.thumbnails_dir = base_dir / "thumbnails"

        for d in (self.final_dir, self.subtitles_dir, self.metadata_dir, self.thumbnails_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Video registry helpers (never let indexing break a render)
    # ------------------------------------------------------------------
    def _record_registry_download(
        self,
        source_url: str,
        local_path: Union[str, Path],
        channel: str = "",
        batch: str = "",
    ) -> str:
        if not self.registry:
            return ""
        try:
            row = self.registry.record_download(
                source_url=source_url,
                local_path=local_path,
                channel=channel,
                batch=batch,
            )
            return row.get("video_id", "")
        except Exception as exc:
            print(f"[Registry] Warning: download record failed ({exc})")
            return ""

    def _record_registry_render(
        self,
        final_video: Optional[Union[str, Path]],
        title: str,
        language: str,
        tts_engine: str,
        metadata: Optional[Dict[str, Any]] = None,
        video_id: str = "",
        source_url: str = "",
        channel: str = "",
        batch: str = "",
    ) -> None:
        if not self.registry:
            return
        try:
            self.registry.record_render(
                video_id=video_id or None,
                source_url=source_url or None,
                final_video=final_video,
                title=title,
                language=language,
                tts_engine=tts_engine,
                duration_sec=get_video_duration(final_video) if final_video else None,
                metadata=metadata or {},
                channel=channel,
                batch=batch,
            )
        except Exception as exc:
            print(f"[Registry] Warning: render record failed ({exc})")

    def _record_registry_drive(
        self,
        drive_path: Union[str, Path],
        video_id: str = "",
        final_video: Optional[Union[str, Path]] = None,
        link: str = "",
        file_id: str = "",
        thumbnail_path: Optional[Union[str, Path]] = None,
        thumbnail_link: str = "",
        source_url: str = "",
    ) -> None:
        if not self.registry:
            return
        try:
            drive_path_obj = Path(drive_path)
            self.registry.record_drive(
                video_id=video_id or None,
                final_filename=drive_path_obj.name or (Path(final_video).name if final_video else ""),
                drive_folder=drive_relative(drive_path_obj.parent),
                drive_path=str(drive_path_obj),
                link=link,
                file_id=file_id,
                thumbnail_path=thumbnail_path,
                thumbnail_link=thumbnail_link,
                source_url=source_url or None,
            )
        except Exception as exc:
            print(f"[Registry] Warning: Drive record failed ({exc})")

    def _record_registry_movie(
        self,
        video_title: str,
        metadata: Optional[Dict[str, Any]],
        video_id: str = "",
        source_ref: str = "",
        channel: str = "",
        batch: str = "",
        force_lookup: bool = False,
    ) -> Dict[str, Any]:
        """
        Resolve and persist the movie identity for this video.
        Wikipedia is free; Gemini's metadata fields are used as a fallback.
        """
        if not self.registry:
            return {}

        details: Dict[str, Any] = {}
        if force_lookup:
            try:
                details = self.translator.lookup_movie_details(video_title=video_title) or {}
            except Exception as exc:
                print(f"[Registry] Movie lookup skipped ({exc})")
                details = {}

        meta = metadata or {}
        for key in ("movie_name", "movie_year", "movie_genre", "movie_synopsis"):
            if not details.get(key) and meta.get(key):
                details[key] = meta[key]

        movie_name = str(details.get("movie_name") or "").strip()
        if not movie_name:
            return {}

        try:
            saved = self.registry.record_movie(
                movie_name=movie_name,
                movie_year=details.get("movie_year"),
                movie_genre=str(details.get("movie_genre") or ""),
                movie_synopsis=str(details.get("movie_synopsis") or ""),
                movie_context=str(details.get("movie_context") or ""),
                movie_source=str(details.get("movie_source") or ("gemini" if meta.get("movie_name") else "")),
                movie_source_url=str(details.get("movie_source_url") or ""),
                video_id=video_id or None,
                source_url=source_ref or None,
                channel=channel,
                batch=batch,
            )
        except Exception as exc:
            print(f"[Registry] Warning: movie record failed ({exc})")
            return {}

        # Keep generated metadata files in sync with the resolved movie identity.
        if metadata is not None:
            for key in ("movie_name", "movie_year", "movie_genre", "movie_synopsis", "movie_context", "movie_source", "movie_source_url"):
                if details.get(key):
                    metadata[key] = details[key]

        return saved or details


    def _cleanup_temp_files(
        self,
        clean_slug: str,
        clean_video_target: Optional[Union[str, Path]] = None,
        video_for_dubbing: Optional[Union[str, Path]] = None,
        sfx_track: Optional[Union[str, Path]] = None,
        video_work_dir: Optional[Union[str, Path]] = None,
        work_dir: Optional[Union[str, Path]] = None
    ):
        """
        Delete all intermediate temporary files, audio stems, clean video plates,
        and audio blocks right after video generation.
        STRICT RULE: Never delete any .srt files or final .mp4 videos!
        """
        import shutil
        deleted_count = 0
        freed_bytes = 0

        def _safe_remove_file(fpath: Optional[Union[str, Path]]):
            nonlocal deleted_count, freed_bytes
            if not fpath:
                return
            p = Path(fpath)
            # Never delete .srt files or final video files!
            if p.suffix.lower() == ".srt" or not p.exists():
                return
            if p.is_file():
                try:
                    freed_bytes += p.stat().st_size
                    p.unlink()
                    deleted_count += 1
                except Exception as e:
                    print(f"  [Cleanup Warning] Could not delete {p.name}: {e}")

        def _safe_remove_dir(dpath: Optional[Union[str, Path]]):
            nonlocal deleted_count, freed_bytes
            if not dpath:
                return
            p = Path(dpath)
            if p.exists() and p.is_dir():
                try:
                    # Save any .srt files inside this directory to self.subtitles_dir before deleting!
                    for srt_file in p.rglob("*.srt"):
                        dest_srt = self.subtitles_dir / srt_file.name
                        if not dest_srt.exists():
                            shutil.copy2(str(srt_file), str(dest_srt))
                            print(f"  [Preserved SRT] Saved subtitle before cleanup: {srt_file.name}")
                    for f in p.rglob("*"):
                        if f.is_file() and f.suffix.lower() != ".srt":
                            freed_bytes += f.stat().st_size
                            deleted_count += 1
                    shutil.rmtree(p, ignore_errors=True)
                except Exception as e:
                    print(f"  [Cleanup Warning] Could not remove directory {p.name}: {e}")

        # 1. Clean video intermediate plates and bounding box JSONs
        for cv_path in (clean_video_target, video_for_dubbing):
            if cv_path:
                cv = Path(cv_path)
                if "_clean" in cv.stem or (cv.parent and cv.parent.name == "clean_videos"):
                    _safe_remove_file(cv)
                    _safe_remove_file(cv.with_name(f"{cv.stem}_box.json"))
                    _safe_remove_file(cv.with_name(f"{clean_slug}_clean_box.json"))
                    _safe_remove_file(self.clean_dir / f"{clean_slug}_clean_box.json")
                    _safe_remove_file(self.clean_dir / f"{cv.stem}_box.json")

        if self.clean_dir.exists():
            for f in self.clean_dir.glob(f"{clean_slug}*"):
                if f.suffix.lower() != ".srt":
                    _safe_remove_file(f)

        # 2. Block align work directories and files
        if video_work_dir:
            _safe_remove_dir(video_work_dir)
        if work_dir and Path(work_dir) != self.stems_dir:
            _safe_remove_dir(work_dir)

        _safe_remove_dir(self.stems_dir / f"block_align_{clean_slug}")
        _safe_remove_dir(self.stems_dir / f"single_narrator_{clean_slug}")
        _safe_remove_dir(self.output_dir / f"align_work_{clean_slug}")
        _safe_remove_dir(self.output_dir / f"align_work_{clean_slug}_clean")

        # 3. Demucs / DBS stem separation directories
        _safe_remove_dir(self.stems_dir / f"stems_{clean_slug}")
        _safe_remove_dir(self.output_dir / f"stems_{clean_slug}")
        _safe_remove_dir(self.stems_dir / "_dbs_work")
        if sfx_track and Path(sfx_track).exists():
            _safe_remove_file(sfx_track)

        # 4. Temp TTS slices and cache folders
        _safe_remove_dir(self.stems_dir / "temp_sarvam_slices")
        _safe_remove_dir(self.output_dir / "temp_sarvam_slices")
        _safe_remove_dir(self.stems_dir / f"cache_sarvam_{clean_slug}")
        _safe_remove_dir(self.stems_dir / f"google_flash_cache_{clean_slug}")

        for pattern in (f"temp_dub_{clean_slug}*", f"*{clean_slug}*voice.wav", f"*{clean_slug}*sfx.wav", f"*{clean_slug}*mixed*.wav"):
            for f in self.stems_dir.glob(pattern):
                _safe_remove_file(f)
            for f in self.output_dir.glob(pattern):
                _safe_remove_file(f)

        # 5. Prune empty parent intermediate folders
        for d in (self.clean_dir, self.stems_dir, self.output_dir / "final_videos", self.final_dir / "final_videos"):
            if d.exists() and d.is_dir():
                try:
                    has_files = any(f.is_file() for f in d.rglob("*"))
                    if not has_files:
                        shutil.rmtree(d, ignore_errors=True)
                except Exception:
                    pass

        mb_freed = freed_bytes / (1024 * 1024)
        print(f"[Pipeline Cleanup] Deleted temp files ({deleted_count} files, {mb_freed:.1f} MB freed). Subtitle SRTs preserved.")

    def purge_all_caches_and_temp(self, base_dir: Optional[Path] = None):
        """
        Delete all existing cache folders, stem directories, and intermediate clean video plates
        from the output directory.
        Move existing final videos out of legacy 'final_videos/' folders directly into their channel folders.
        PRESERVES: All .srt files, all final .mp4 videos, and all metadata.json files!
        """
        import shutil
        target_dir = Path(base_dir) if base_dir else self.output_dir
        print(f"\n=======================================================")
        print(f"[Purge & Reorganize] Cleaning caches & reorganizing: {target_dir}")
        print(f"=======================================================")

        total_freed = 0
        total_moved = 0

        # Step 1: In all channel subdirectories, move videos out of final_videos/ into channel folder
        for item in list(target_dir.iterdir()):
            if not item.is_dir():
                continue

            final_sub = item / "final_videos"
            if final_sub.exists() and final_sub.is_dir():
                for vid in list(final_sub.glob("*.mp4")):
                    dest = item / vid.name
                    if not dest.exists():
                        shutil.move(str(vid), str(dest))
                        print(f"  [Moved Video to Channel] {vid.name} -> {item.name}/{dest.name}")
                        total_moved += 1
                    else:
                        vid.unlink()
                for s in list(final_sub.glob("*.srt")):
                    dest_srt = (item / "subtitles" / s.name) if (item / "subtitles").exists() else (item / s.name)
                    if not dest_srt.exists():
                        shutil.move(str(s), str(dest_srt))
                shutil.rmtree(final_sub, ignore_errors=True)

            clean_sub = item / "clean_videos"
            if clean_sub.exists() and clean_sub.is_dir():
                for f in clean_sub.rglob("*"):
                    if f.is_file() and f.suffix.lower() != ".srt":
                        try:
                            total_freed += f.stat().st_size
                            f.unlink()
                        except Exception:
                            pass
                shutil.rmtree(clean_sub, ignore_errors=True)
                print(f"  [Cleaned] Removed intermediate clean_videos in: {item.name}")

            stems_sub = item / "audio_stems"
            if stems_sub.exists() and stems_sub.is_dir():
                for s in stems_sub.rglob("*.srt"):
                    dest_s = item / "subtitles" / s.name
                    dest_s.parent.mkdir(parents=True, exist_ok=True)
                    if not dest_s.exists():
                        shutil.copy2(str(s), str(dest_s))
                for f in stems_sub.rglob("*"):
                    if f.is_file() and f.suffix.lower() != ".srt":
                        try:
                            total_freed += f.stat().st_size
                            f.unlink()
                        except Exception:
                            pass
                shutil.rmtree(stems_sub, ignore_errors=True)
                print(f"  [Cleaned] Removed audio_stems in: {item.name}")

        # Step 2: Handle root output/final_videos/
        root_final = target_dir / "final_videos"
        if root_final.exists() and root_final.is_dir():
            for vid in list(root_final.glob("*.mp4")):
                name = vid.name
                dest_dir = target_dir
                if " - " in name:
                    prefix = name.split(" - ")[0].strip()
                    cand_chan = target_dir / prefix
                    if cand_chan.exists() and cand_chan.is_dir():
                        dest_dir = cand_chan
                dest = dest_dir / name
                if not dest.exists():
                    shutil.move(str(vid), str(dest))
                    print(f"  [Moved Root Final Video] {name} -> {dest_dir.name}/{dest.name}")
                    total_moved += 1
                else:
                    vid.unlink()
            for s in list(root_final.glob("*.srt")):
                dest_srt = target_dir / "subtitles" / s.name
                dest_srt.parent.mkdir(parents=True, exist_ok=True)
                if not dest_srt.exists():
                    shutil.move(str(s), str(dest_srt))
            shutil.rmtree(root_final, ignore_errors=True)

        # Step 3: Handle root output/clean_videos and audio_stems
        for root_temp in (target_dir / "clean_videos", target_dir / "audio_stems", target_dir / "comparison_audio"):
            if root_temp.exists() and root_temp.is_dir():
                for s in root_temp.rglob("*.srt"):
                    dest_s = target_dir / "subtitles" / s.name
                    dest_s.parent.mkdir(parents=True, exist_ok=True)
                    if not dest_s.exists():
                        shutil.copy2(str(s), str(dest_s))
                for f in root_temp.rglob("*"):
                    if f.is_file() and f.suffix.lower() != ".srt":
                        try:
                            total_freed += f.stat().st_size
                            f.unlink()
                        except Exception:
                            pass
                shutil.rmtree(root_temp, ignore_errors=True)
                print(f"  [Cleaned] Removed root intermediate directory: {root_temp.name}")

        # Step 4: Handle cache folders (cache_*, sarvam_*, temp_*)
        for item in list(target_dir.iterdir()):
            if item.is_dir() and (item.name.startswith("cache_") or item.name.startswith("sarvam_") or item.name.startswith("temp_") or item.name.startswith("test_")):
                for f in item.rglob("*"):
                    if f.is_file() and f.suffix.lower() != ".srt":
                        try:
                            total_freed += f.stat().st_size
                        except Exception:
                            pass
                shutil.rmtree(item, ignore_errors=True)
                print(f"  [Cleaned Cache] Removed {item.name}")

        mb_freed = total_freed / (1024 * 1024)
        print(f"\n[Purge Complete] Freed {mb_freed:.1f} MB of temp/cache files. Moved {total_moved} videos to channel folders. SRTs preserved!\n")

    def reorganize_existing_output(self):
        """Reorganize output files into channel folders and purge temporary caches."""
        self.purge_all_caches_and_temp()


    def _resolve_tts(self, target_lang: str) -> Any:
        has_gemini_key = bool(os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEYS"))
        has_elevenlabs_key = bool(os.getenv("ELEVENLABS_API_KEY") or os.getenv("ELEVENLABS_API_KEYS"))
        has_sarvam_key = bool(os.getenv("SARVAM_API_KEY") or os.getenv("SARVAM_API_KEYS"))

        # ElevenLabs v4 (Default & 1st Priority)
        if self.tts_engine in ("elevenlabs", "eleven_labs", "11labs"):
            if get_active_elevenlabs_keys():
                return self.elevenlabs_tts or ElevenLabsTTS()
            print("[Pipeline] Notice: ElevenLabs keys exhausted! Auto-switching engine to Google Gemini Flash 3.8 TTS...")
            self.tts_engine = "google"
            return self.google_tts or GoogleGeminiTTS()

        # Google Flash 3.8 TTS (2nd Priority)
        elif self.tts_engine in ("google", "gemini"):
            if get_active_gemini_keys():
                return self.google_tts or GoogleGeminiTTS()
            if get_active_sarvam_keys():
                print("[Pipeline] Notice: Gemini keys exhausted! Auto-switching engine to Sarvam AI (Bulbul v4)...")
                self.tts_engine = "sarvam"
                return self.sarvam_tts or SarvamTTS()
            print("[Pipeline] WARNING: Gemini and Sarvam keys exhausted/missing! Switching to Chirp/Kokoro.")
            self.tts_engine = "kokoro"
            return self.kokoro_tts

        # Sarvam AI Bulbul v4 (3rd Priority)
        elif self.tts_engine in ("sarvam", "auto") or not self.tts_engine:
            if get_active_sarvam_keys():
                return self.sarvam_tts or SarvamTTS()
            print("[Pipeline] WARNING: SARVAM_API_KEY / SARVAM_API_KEYS missing or exhausted! Switching to Kokoro.")
            self.tts_engine = "kokoro"
            return self.kokoro_tts

        elif self.tts_engine in ("chirp", "google_chat"):
            return self.kokoro_tts

        elif self.tts_engine in ("omnivoice", "omni"):
            return self.omnivoice_tts
        elif self.tts_engine == "kokoro":
            return self.kokoro_tts

        return self.google_tts or self.elevenlabs_tts or self.sarvam_tts or self.omnivoice_tts or self.kokoro_tts

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
        bgm_volume: Optional[float] = None,
        enable_metadata: bool = True,
        style: str = "viral",
        fit_short: bool = False,
        max_duration: float = 58.0,
        channel_name: str = "",
        anti_accent: bool = False,
        debug: Optional[bool] = None,
        loop: bool = False,
        mirror: bool = False,
        smart_crop: bool = False,
        movie: bool = False,
        ratio: str = "reel",
        watermark: Optional[str] = None,
        disable_bgm: bool = False,
        allow_tts_fallback: bool = True,
        move_to_drive: bool = False,
        delete_input: bool = False,
        thumbnail: bool = False,
        capture_movie_details: bool = False,
    ) -> Dict[str, Any]:
        """
        Execute full end-to-end pipeline:
        Download -> Clean Subtitles/Watermarks -> Transcribe -> Translate -> Stem Separation -> Synthesize & Dub.
        """
        is_debug = self.debug if debug is None else debug
        if not is_debug:
            is_debug = bool(os.getenv("DEBUG") in ("1", "true", "True") or os.getenv("DUBBING_DEBUG") in ("1", "true", "True"))

        effective_bgm_volume = float(bgm_volume) if bgm_volume is not None else (1.35 if movie else 1.05)

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
            selected_voice = voice if (voice and voice.lower() not in ("shubh", "arvind", "amartya")) else "Ludo"
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
            sarvam_ver = "Bulbul v4-flash" if any(tag in selected_voice for tag in ("_hi_", "_en_", "_enhi_")) else "Bulbul v3"
            engine_name = f"Sarvam AI {sarvam_ver} ({selected_voice})"
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
        print(f" Preserve BGM/SFX: {preserve_bgm} (Meta HTDemucs v4 + Wiener Bleed Suppression, BGM: {effective_bgm_volume:.2f}x)")
        if movie:
            print(f" Movie Mode      : ENABLED (Fast OCR Crop + Auto-Reels Blurred Canvas + 'movie explanation' BGM + Original Duration Sync + Word-Synced Captions)")
        else:
            print(f" Clean Subtitles : {clean_subtitles} (Per-Subtitle Tight RapidOCR Blur)")
        if anti_accent:
            print(f" Anti-Accent     : {anti_accent} (Syllable-Weighted English Pair Breaker)")
        clean_watermark = " ".join(str(watermark or "").strip().split())
        if clean_watermark:
            print(f" Watermark       : {clean_watermark.upper()} (SoftLight Blend + Stroke/Shadow, Bottom Center)")
        if is_debug:
            print(f" Debug Mode      : ENABLED (Preserving stems, clean plates, box JSONs & logs)")
        print(f" Output Folder   : {self.output_dir}")
        print("=" * 50)

        # -------------------------------------------------------------
        # Step 1: Download Video via Downloader API
        # -------------------------------------------------------------
        video_path = self.downloader.download_video(url_or_file, output_dir=self.input_dir)

        # Configure channel-specific output folder so final videos are in their channel folder
        detected_channel = channel_name or (video_path.parent.name if video_path.parent.name.lower() not in ("input", "clean_videos", "videos", "output", ".") else "")
        if not detected_channel and " - " in video_path.stem:
            parts = [p.strip() for p in video_path.stem.split(" - ") if p.strip()]
            if len(parts) >= 2:
                cand_chan = sanitize_filename(parts[0])
                if cand_chan and len(cand_chan) < 35:
                    detected_channel = cand_chan

        if detected_channel:
            target_out_dir = self.output_dir / detected_channel if self.output_dir.name != detected_channel else self.output_dir
            target_out_dir.mkdir(parents=True, exist_ok=True)
            self._setup_output_dirs(target_out_dir)
        else:
            self._setup_output_dirs(self.output_dir)

        # Register the raw download (batch runners may have pre-registered the URL)
        source_ref = str(url_or_file)
        registry_video_id = self._record_registry_download(
            source_url=source_ref if source_ref.lower().startswith(("http://", "https://")) else "",
            local_path=video_path,
            channel=detected_channel,
        )

        # -------------------------------------------------------------
        # Step 1.5: Fit Short Condenser Check (Preserve original video for Whisper)
        # -------------------------------------------------------------
        orig_dur = get_video_duration(video_path)
        if fit_short:
            print("\n" + "=" * 60)
            print(f" [Short Condenser] 1-Minute Short Mode Active (Target: <= {max_duration:.1f}s)")
            print(f"   Original Video Duration : {orig_dur:.1f}s")
            print(f"   Strategy: Preserving original video for clean Whisper GPU transcription.")
            print(f"             Condensing narration script block-by-block via Gemini.")
            print(f"             Retiming video & SFX via Block Aligner to match condensed speech.")
            print("=" * 60)

        base_stem = video_path.stem
        if base_stem.endswith("_clean"):
            base_stem = base_stem[:-6]
        clean_slug = sanitize_filename(base_stem)
        print(f"[Pipeline] Clean Video Slug: {clean_slug}")

        # Check if already fully processed and final video exists for THIS specific style & mode
        lang_tag = "hindi" if target_lang.lower().startswith("hi") or "hinglish" in target_lang.lower() else target_lang.lower()
        active_style = (style or "viral").lower()
        style_suffix = f"_{active_style}" if active_style != "viral" else ""
        short_suffix = "_short" if fit_short else ""
        loop_suffix = "_loop" if loop else ""
        mirror_suffix = "_mirror" if mirror else ""
        smartcrop_suffix = "_smartcrop" if smart_crop else ""
        movie_suffix = "_movie" if movie else ""
        ratio_norm = normalize_aspect_ratio(ratio)
        ratio_suffix = "_square" if ratio_norm == "square" else ""
        normalized_mode = "block_aligned" if fit_short else (dub_mode or "block_aligned").lower()
        mode_suffix = "_paragraph" if normalized_mode in ("paragraph", "single_narrator", "narrator", "continuous") else ""

        meta_json_file = self.metadata_dir / f"{clean_slug}_{lang_tag}{style_suffix}{short_suffix}{loop_suffix}{mode_suffix}{mirror_suffix}{smartcrop_suffix}{movie_suffix}{ratio_suffix}_metadata.json"
        wm_marker_file = self.metadata_dir / f"{clean_slug}_{lang_tag}{style_suffix}{short_suffix}{loop_suffix}{mode_suffix}{mirror_suffix}{smartcrop_suffix}{movie_suffix}{ratio_suffix}_wm.txt"
        wm_norm = clean_watermark.upper()
        cached_final_vid = None
        cached_meta = None
        if not force:
            if meta_json_file.exists():
                try:
                    cached_meta = json.loads(meta_json_file.read_text(encoding="utf-8"))
                    clean_title_fn = sanitize_title_for_filename(cached_meta.get("title", ""))
                    if clean_title_fn:
                        ratio_tag = " Square" if ratio_norm == "square" else ""
                        movie_tag = " Movie" if movie else ""
                        crop_tag = " Smart Crop" if smart_crop else ""
                        mirror_tag = " Mirrored" if mirror else ""
                        mode_tag = f" {normalized_mode.replace('_', ' ').title()}" if normalized_mode != "block_aligned" else ""
                        var_tag = f" [{active_style.title()}{mode_tag}{mirror_tag}{crop_tag}{movie_tag}{ratio_tag}]" if (active_style != "viral" or normalized_mode != "block_aligned" or mirror or smart_crop or movie or ratio_norm != "reel") else ""
                        candidate = self.final_dir / f"{clean_title_fn}{var_tag}.mp4"
                        if candidate.exists() and candidate.stat().st_size > 100000:
                            cached_final_vid = candidate
                        elif (self.final_dir / "final_videos" / f"{clean_title_fn}{var_tag}.mp4").exists():
                            cached_final_vid = self.final_dir / "final_videos" / f"{clean_title_fn}{var_tag}.mp4"
                except Exception:
                    pass

            if cached_final_vid is None:
                pattern = f"{clean_slug}_{lang_tag}{style_suffix}{short_suffix}{loop_suffix}{mode_suffix}{mirror_suffix}{smartcrop_suffix}{movie_suffix}{ratio_suffix}*.mp4"
                for candidate in self.final_dir.glob(pattern):
                    if candidate.stat().st_size > 100000:
                        cached_final_vid = candidate
                        break
                if cached_final_vid is None and (self.final_dir / "final_videos").exists():
                    for candidate in (self.final_dir / "final_videos").glob(pattern):
                        if candidate.stat().st_size > 100000:
                            cached_final_vid = candidate
                            break

            if cached_final_vid is not None:
                prev_wm = wm_marker_file.read_text(encoding="utf-8").strip() if wm_marker_file.exists() else ""
                if prev_wm != wm_norm:
                    print(f"[Pipeline] Watermark setting changed ('{prev_wm}' -> '{wm_norm}'); rebuilding final video...")
                    cached_final_vid = None

            if cached_final_vid is not None and fit_short:
                cv_dur = get_video_duration(cached_final_vid)
                if cv_dur > max_duration + 1.0:
                    print(f"[Pipeline] Existing dubbed video ({cached_final_vid.name}, {cv_dur:.1f}s) exceeds short max duration ({max_duration:.1f}s). Re-processing...")
                    cached_final_vid = None

            if cached_final_vid is not None:
                print(f"[Pipeline] Existing dubbed video found: {cached_final_vid.name}. Skipping processing.")
                self._record_registry_render(
                    final_video=cached_final_vid,
                    title=(cached_meta or {}).get("title", ""),
                    language=target_lang,
                    tts_engine=self.tts_engine,
                    metadata=cached_meta or {},
                    video_id=registry_video_id,
                    channel=detected_channel,
                )
                self._record_registry_movie(
                    video_title=clean_slug,
                    metadata=cached_meta,
                    video_id=registry_video_id,
                    channel=detected_channel,
                    force_lookup=bool(movie or capture_movie_details),
                )
                clean_vid_cand = self.clean_dir / f"{clean_slug}_clean.mp4"
                return {
                    "video_path": clean_vid_cand if clean_vid_cand.exists() else video_path,
                    "raw_srt": self.subtitles_dir / f"{clean_slug}_raw.srt",
                    "dubbed_srt": self.subtitles_dir / f"{clean_slug}_{lang_tag}{style_suffix}{short_suffix}{loop_suffix}.srt",
                    "sfx_track": None,
                    "final_video": cached_final_vid,
                    "metadata": cached_meta or {},
                    "clean_title": clean_slug,
                    "translation_report": {"cached": True}
                }

        # -------------------------------------------------------------
        # Step 1.5 (1D): Start CPU/NVENC Movie Crop or Smart Crop at t=0 BEFORE Whisper
        # so RapidOCR runs in parallel with sequential PyTorch CUDA (Whisper -> DBS-TIGER)
        # without ever exceeding 4 GB VRAM.
        # -------------------------------------------------------------
        normalized_mode = "block_aligned" if fit_short else (dub_mode or "block_aligned").lower()
        use_single_pass_movie_crop = bool(
            movie and normalized_mode in ("block_aligned", "block", "blocks", "aligned")
        )
        movie_crop_spec_path: Optional[Path] = (
            self.clean_dir / f"{clean_slug}_moviecrop{ratio_suffix}_spec.json"
            if use_single_pass_movie_crop
            else None
        )
        inpaint_future = None
        inpaint_executor = None
        clean_video_target = None
        t_clean_start = time.time()

        if movie:
            movie_crop_video_path = self.clean_dir / f"{clean_slug}_moviecrop{ratio_suffix}.mp4"
            cached_movie_valid = False
            if (
                not force
                and use_single_pass_movie_crop
                and movie_crop_spec_path
                and movie_crop_spec_path.exists()
            ):
                try:
                    spec_d = json.loads(movie_crop_spec_path.read_text(encoding="utf-8"))
                    cached_movie_valid = (
                        spec_d.get("output_ratio") == ratio_norm
                        and str(spec_d.get("source_video", "")) == str(Path(video_path).resolve())
                    )
                except Exception:
                    cached_movie_valid = False

            if cached_movie_valid:
                print(f"[Pipeline] Existing valid movie-crop single-pass spec found: {movie_crop_spec_path.name}")
                clean_video_target = video_path
                timings["4. Movie Edge Caption Crop"] = (0.0, "Cached (Local Disk)")
            elif not use_single_pass_movie_crop and not force and movie_crop_video_path.exists() and movie_crop_video_path.stat().st_size > 50000:
                try:
                    import cv2
                    from .movie_crop import _is_vertical_aspect, _is_square_aspect
                    cap_mc = cv2.VideoCapture(str(movie_crop_video_path))
                    mc_w = int(cap_mc.get(cv2.CAP_PROP_FRAME_WIDTH))
                    mc_h = int(cap_mc.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    cap_mc.release()
                    cached_movie_valid = _is_square_aspect(mc_w, mc_h) if ratio_norm == "square" else _is_vertical_aspect(mc_w, mc_h)
                    if cached_movie_valid:
                        print(f"[Pipeline] Existing valid movie-cropped video found: {movie_crop_video_path.name}")
                        clean_video_target = movie_crop_video_path
                        timings["4. Movie Edge Caption Crop"] = (0.0, "Cached (Local Disk)")
                except Exception:
                    cached_movie_valid = False

            if not cached_movie_valid:
                def _run_movie_crop():
                    try:
                        from .movie_crop import process_movie_crop_video
                        layout_label = "1080x1080 Square" if ratio_norm == "square" else "auto-Reels aspect"
                        print(f"\n[Track 2: Movie Crop] Fast OCR top/bottom caption detection, crop & {layout_label} check...")
                        cropped = process_movie_crop_video(
                            input_video_path=video_path,
                            output_video_path=movie_crop_video_path,
                            sample_frames=10,
                            edge_threshold=0.20,
                            reels_if_non_vertical=(ratio_norm != "square"),
                            output_ratio=ratio_norm,
                            defer_encode=use_single_pass_movie_crop,
                        )
                        return cropped
                    except Exception as e:
                        print(f"[Track 2: Movie Crop] Warning: Movie crop error ({e}), fallback to original.")
                        return video_path

                inpaint_executor = ThreadPoolExecutor(max_workers=1)
                inpaint_future = inpaint_executor.submit(_run_movie_crop)
                clean_video_target = None

        elif smart_crop:
            smart_crop_video_path = self.clean_dir / f"{clean_slug}_smartcrop.mp4"
            if not force and smart_crop_video_path.exists() and smart_crop_video_path.stat().st_size > 50000:
                print(f"[Pipeline] Existing valid smart-cropped video found: {smart_crop_video_path.name}")
                clean_video_target = smart_crop_video_path
                timings["4. Smart Crop & Hook Overlay"] = (0.0, "Cached (Local Disk)")
            else:
                def _run_smart_crop():
                    try:
                        from .smart_crop import process_smart_crop_video
                        print("\n[Track 2: Smart Crop] Cropping bottom captions (9:16 expand) + translating top hook to English...")
                        process_smart_crop_video(
                            input_video_path=video_path,
                            output_video_path=smart_crop_video_path,
                            crop_bottom_ratio=0.15
                        )
                        if smart_crop_video_path.exists():
                            print(f"[Track 2: Smart Crop] Finished smart-cropped video: {smart_crop_video_path.name}")
                            return smart_crop_video_path
                        return video_path
                    except Exception as e:
                        print(f"[Track 2: Smart Crop] Warning: Smart crop error ({e}), fallback to original.")
                        return video_path

                inpaint_executor = ThreadPoolExecutor(max_workers=1)
                inpaint_future = inpaint_executor.submit(_run_smart_crop)
                clean_video_target = None

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
        # Step 2.5: Background Video Cleaner (needs raw_srt, non-movie mode)
        # -------------------------------------------------------------
        if not movie and not smart_crop and clean_subtitles:
            if video_path.stem.endswith("_clean"):
                clean_video_path = video_path
            else:
                clean_video_path = self.clean_dir / f"{clean_slug}_clean.mp4"
                legacy_clean_path = self.output_dir / f"{video_path.stem}_clean.mp4"
                if not force and not clean_video_path.exists() and legacy_clean_path.exists() and legacy_clean_path.stat().st_size > 50000:
                    import shutil
                    shutil.copy2(str(legacy_clean_path), str(clean_video_path))

            is_valid_clean = False
            if not force and clean_video_path.exists() and clean_video_path.stat().st_size > 50000:
                try:
                    probe_c = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(clean_video_path)], capture_output=True, text=True)
                    clean_dur = float(probe_c.stdout.strip())
                    probe_o = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)], capture_output=True, text=True)
                    orig_dur = float(probe_o.stdout.strip())
                    box_json_cand = clean_video_path.with_name(f"{clean_video_path.stem}_box.json")
                    is_tight_mode = False
                    if box_json_cand.exists():
                        try:
                            is_tight_mode = json.loads(box_json_cand.read_text(encoding="utf-8")).get("mode") == "per_subtitle_tight"
                        except Exception:
                            is_tight_mode = False
                    if abs(clean_dur - orig_dur) <= 2.0 and is_tight_mode:
                        is_valid_clean = True
                    elif abs(clean_dur - orig_dur) <= 2.0 and not is_tight_mode:
                        print(f"[Pipeline] Cached clean video uses legacy wide blur ({clean_video_path.name}). Re-cleaning with tight per-subtitle blur...")
                    else:
                        print(f"[Pipeline] Warning: Existing clean video duration ({clean_dur:.2f}s) mismatch with original ({orig_dur:.2f}s)! Re-cleaning...")
                except Exception:
                    is_valid_clean = False

            if is_valid_clean:
                print(f"[Pipeline] Existing valid tight clean video found: {clean_video_path.name}")
                clean_video_target = clean_video_path
                timings["4. Subtitle Removal Blur"] = (0.0, "Cached (Local Disk)")
            else:
                def _run_cleaner():
                    try:
                        try:
                            from tools.remove_subtitles import remove_subtitles
                        except ImportError:
                            from remove_subtitles import remove_subtitles
                        print("\n[Track 2: Video Cleaner] Running Per-Subtitle Tight RapidOCR Blur in parallel...")
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
            if not movie and not smart_crop:
                clean_video_target = video_path

        # -------------------------------------------------------------
        # Track 1: Stem Separation -> Narrator/Dialogue Detection -> Translation -> Metadata
        # -------------------------------------------------------------
        sfx_track = None
        speech_track = None
        t_stem = time.time()
        if preserve_bgm:
            try:
                stems = self.separator.separate_audio(
                    video_path,
                    output_dir=self.stems_dir,
                    clean_name=clean_slug,
                    force=force
                )
                sfx_track = stems.get("sfx")
                speech_track = stems.get("speech")
                if sfx_track:
                    print(f"[Pipeline Audio Sync] Isolated Foley SFX track selected: {sfx_track.name}")
                timings["3. Stem Separation (Meta HTDemucs v4)"] = (time.time() - t_stem, "Local GPU (Meta HTDemucs v4)")
            except Exception as e:
                print(f"[Pipeline] Warning: Stem separation failed ({e}). Proceeding with clean voiceover.")
                timings["3. Stem Separation (Meta HTDemucs v4)"] = (time.time() - t_stem, "Failed/Skipped")

        # Step 2.5: Detect Narrator vs In-Scene Character Dialogue
        translation_source_srt = raw_srt
        if speech_track and Path(speech_track).exists():
            try:
                from .narrator_detector import detect_narrator_and_dialogue
                narrator_raw_srt = self.subtitles_dir / f"{clean_slug}_narrator_raw.srt"
                roles_json = self.subtitles_dir / f"{clean_slug}_speaker_roles.json"
                sfx_diag_out = Path(sfx_track).with_name("sfx_with_dialogue.wav") if sfx_track else None
                det = detect_narrator_and_dialogue(
                    raw_srt=raw_srt,
                    speech_wav=Path(speech_track),
                    sfx_wav=Path(sfx_track) if sfx_track else None,
                    narrator_srt_out=narrator_raw_srt,
                    sfx_with_dialogue_out=sfx_diag_out,
                    roles_json_out=roles_json,
                    force=force,
                )
                translation_source_srt = Path(det["narrator_srt"])
                if det.get("sfx_track") and det.get("dialogue_count", 0) > 0:
                    sfx_track = Path(det["sfx_track"])
                print(
                    f"[Pipeline Speaker Detection] Narrator blocks: {det['narrator_count']} | "
                    f"In-scene Dialogue blocks: {det['dialogue_count']} "
                    f"({'preserved in audio mix, excluded from narrator dub' if det['dialogue_count'] else 'pure narration'})"
                )
            except Exception as det_err:
                print(f"[Pipeline Speaker Detection] Warning: Detection skipped ({det_err}); using full raw SRT.")

        # Step 3: Translate & Transcreate Narrator SRT via Gemini SDK
        t_translat = time.time()
        effective_target_lang = (
            DEFAULT_TARGET_LANGUAGE if target_lang.strip().lower() in ("hindi", "hi", "hinglish") else target_lang
        )
        lang_tag = "hindi" if target_lang.lower().startswith("hi") or "hinglish" in target_lang.lower() else target_lang.lower()
        style_suffix = f"_{active_style}" if active_style != "viral" else ""
        short_suffix = "_short" if fit_short else ""
        loop_suffix = "_loop" if loop else ""
        dubbed_srt = self.subtitles_dir / f"{clean_slug}_{lang_tag}{style_suffix}{short_suffix}{loop_suffix}.srt"
        legacy_dubbed_srt = self.output_dir / f"{base_stem}_{lang_tag}{style_suffix}{short_suffix}{loop_suffix}.srt"
        if not force and not dubbed_srt.exists() and legacy_dubbed_srt.exists():
            import shutil
            shutil.copy2(str(legacy_dubbed_srt), str(dubbed_srt))

        if not force and dubbed_srt.exists() and dubbed_srt.stat().st_size > 100:
            print(f"[Pipeline] Existing dubbed SRT found ({active_style}{', short' if fit_short else ''}{', loop' if loop else ''}{', anti-accent' if anti_accent else ''}): {dubbed_srt.name}. Skipping translation.")
            translated_srt = dubbed_srt.read_text(encoding="utf-8")
            if anti_accent and not str(target_lang or "").strip().lower().startswith("en"):
                translated_srt = balance_consecutive_english(translated_srt)
                dubbed_srt.write_text(translated_srt, encoding="utf-8")
            report = {"skipped": True}
            timings["2. Script Transcreation"] = (time.time() - t_translat, "Cached (Local Disk)")
        else:
            translated_srt, report = self.translator.translate_and_rewrite_srt(
                srt_input=translation_source_srt,
                target_language=effective_target_lang,
                batch_size=batch_size,
                temperature=temperature,
                style=active_style,
                tts_engine=self.tts_engine,
                fit_short=fit_short,
                max_duration=max_duration,
                anti_accent=anti_accent,
                loop=loop,
                movie=movie,
                video_title=clean_slug,
            )
            dubbed_srt.write_text(translated_srt, encoding="utf-8")
            timings["2. Script Transcreation"] = (time.time() - t_translat, f"Cloud API (Gemini - {active_style}{', short' if fit_short else ''}{', loop' if loop else ''})")
            print(f"[Pipeline] Dubbed {target_lang} SRT ({active_style}{', short' if fit_short else ''}{', loop' if loop else ''}{', anti-accent' if anti_accent else ''}) saved to: {dubbed_srt.name}")

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
                    detected_channel = channel_name or (video_path.parent.name if video_path.parent.name.lower() not in ("input", "clean_videos", "videos", "output", ".") else "")
                    meta = self.translator.generate_metadata(
                        script_text=clean_script,
                        target_language=target_lang,
                        original_title=clean_slug,
                        temperature=temperature,
                        channel_name=detected_channel,
                        movie=movie
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
        # Step 4: (Stems & Speaker Role Detection already completed before translation)
        # -------------------------------------------------------------

        # -------------------------------------------------------------
        # Step 5: Wait for Parallel Video Cleaner & Dub Final Video
        # -------------------------------------------------------------
        if inpaint_future is not None:
            stage_label = "4. Movie Edge Caption Crop" if movie else ("4. Smart Crop & Hook Overlay" if smart_crop else "4. Subtitle Removal Blur")
            print(f"\n[Pipeline Track Sync] Waiting for Parallel Video Processor ({stage_label}) to complete...")
            try:
                video_for_dubbing = inpaint_future.result(timeout=900)
                timings[stage_label] = (time.time() - t_clean_start, "Local OCR + FFmpeg Crop" if movie else "Local GPU (Parallel)")
            except Exception as e:
                print(f"[Pipeline Track Sync] Video cleaner future failed ({e}), using original video.")
                video_for_dubbing = video_path
                timings[stage_label] = (time.time() - t_clean_start, "Fallback to Original")
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
                        detected_margin_v = max(80, 1920 - int(b_data["y_center"]) - 65)
                        print(f"[Pipeline Subtitle Alignment] Loaded dynamic placement: MarginV={detected_margin_v} (Center Y: {b_data.get('y_center')}px) from {bc.name}")
                        if is_debug:
                            print(f"[Debug] Box Metadata: {b_data}")
                        break
                    elif "margin_v" in b_data:
                        detected_margin_v = max(80, int(b_data["margin_v"]) - 30)
                        print(f"[Pipeline Subtitle Alignment] Loaded dynamic placement: MarginV={detected_margin_v} (Adjusted down for visual center) from {bc.name}")
                        break
                except Exception:
                    pass

        # Final video placed STRICTLY in final_videos/ with clean filename
        style_suffix = f"_{active_style}" if active_style != "viral" else ""
        short_suffix = "_short" if fit_short else ""
        loop_tag = "_loop" if loop else ""
        mirror_suffix = "_mirror" if mirror else ""
        smartcrop_suffix = "_smartcrop" if smart_crop else ""
        movie_suffix = "_movie" if movie else ""
        normalized_mode = "block_aligned" if fit_short else (dub_mode or "block_aligned").lower()
        mode_suffix = "_paragraph" if normalized_mode in ("paragraph", "single_narrator", "narrator", "continuous") else ""

        if "chirp" in self.tts_engine.lower():
            tts_suffix = "_chirp"
        elif "kokoro" in self.tts_engine.lower():
            tts_suffix = "_kokoro"
        elif "elevenlabs" in self.tts_engine.lower() or "11labs" in self.tts_engine.lower():
            tts_suffix = "_elevenlabs"
        elif "google" in self.tts_engine.lower() or "gemini" in self.tts_engine.lower():
            tts_suffix = "_google"
        elif "sarvam" in self.tts_engine.lower() or "bulbul" in self.tts_engine.lower():
            tts_suffix = "_sarvam"
        else:
            tts_suffix = ""
        final_video = self.final_dir / f"{clean_slug}_{lang_tag}{style_suffix}{short_suffix}{loop_tag}{mode_suffix}{mirror_suffix}{smartcrop_suffix}{movie_suffix}{ratio_suffix}{tts_suffix}_dubbed.mp4"

        # Resolve Copyright-Free Background Music (unless disable_bgm is set — keeps SFX only)
        if disable_bgm:
            bgm_free_track = None
            print("[Pipeline Audio Sync] Background Music disabled (SFX + Voiceover only).")
        else:
            bgm_free_track = self._resolve_royalty_free_bgm(movie=movie)
            if bgm_free_track:
                print(f"[Pipeline Audio Sync] Royalty-Free BGM selected: {bgm_free_track.name} (Volume: {effective_bgm_volume:.2f}x)")

        t_dub = time.time()
        video_work_dir = None

        if normalized_mode in ("block_aligned", "block", "blocks", "aligned"):
            mode_desc = f"{active_style.upper()}{', MIRRORED' if mirror else ''}{', SMART-CROP' if smart_crop else ''}{', MOVIE' if movie else ''}{', SQUARE 1:1' if ratio_norm == 'square' else ''}"
            effective_movie_tts_speed = (base_speed if base_speed != 1.0 else None)
            pause_desc = "original scene timing, zero video compaction" if movie else "Uniform tempo, max 200ms pauses, 0s tail silence"
            print(f"\n[Pipeline Dub Mode] Engaging Block-Aligned Dubbing Engine ({mode_desc}, {pause_desc})...")
            from .block_aligner import align_video_and_audio_blocks
            video_work_dir = self.stems_dir / f"block_align_{clean_slug}_{lang_tag}{movie_suffix}{ratio_suffix}"
            final_video = align_video_and_audio_blocks(
                clean_video_path=Path(video_for_dubbing),
                srt_path=Path(dubbed_srt),
                output_video_path=Path(final_video),
                sfx_path=sfx_track,
                bgm_path=bgm_free_track,
                voice=selected_voice,
                engine=self.tts_engine,
                work_dir=video_work_dir,
                max_silence_sec=0.20,
                bgm_volume=effective_bgm_volume,
                mirror=mirror,
                smart_crop=smart_crop,
                burn_subtitles=True,
                tts_speed=effective_movie_tts_speed,
                target_lang=target_lang,
                movie=movie,
                watermark=clean_watermark or None,
                ratio=ratio_norm,
                disable_bgm=disable_bgm,
                allow_fallback=allow_tts_fallback,
                crop_spec_path=movie_crop_spec_path,
            )
            fv_name = Path(final_video).name
            for tag_eng in ("elevenlabs", "google", "sarvam", "chirp", "kokoro"):
                if f"_{tag_eng}" in fv_name:
                    self.tts_engine = tag_eng
                    break
            timings["5. Voiceover Synthesis & Mux"] = (time.time() - t_dub, f"Block-Aligned {self.tts_engine.capitalize()} + NVENC")


        elif normalized_mode in ("paragraph", "single_narrator", "narrator", "continuous"):
            mode_desc = f"{active_style.upper()}{', MIRRORED' if mirror else ''}{', SMART-CROP' if smart_crop else ''}"
            print(f"\n[Pipeline Dub Mode] Engaging Paragraph Continuous Dubbing Engine ({mode_desc}, 0s tail silence)...")
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
                style=active_style,
                loop=loop,
                mirror=mirror,
                smart_crop=smart_crop
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

        if wm_norm and normalized_mode not in ("block_aligned", "block", "blocks", "aligned") and final_video.exists():
            from .watermark import apply_watermark_to_video
            wm_tmp = final_video.with_name(f"{final_video.stem}_wmtmp.mp4")
            apply_watermark_to_video(final_video, wm_tmp, wm_norm, work_dir=self.stems_dir)
            wm_tmp.replace(final_video)
        try:
            wm_marker_file.write_text(wm_norm, encoding="utf-8")
        except Exception:
            pass

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
                fallback_lang_tag = "3D Animation In English" if str(target_lang or "").strip().lower().startswith("en") else "3D Animation In Hindi"
                metadata = {
                    "title": f"{clean_slug} ({fallback_lang_tag}) #shorts",
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
            fallback_lang_tag = "3D Animation In English" if str(target_lang or "").strip().lower().startswith("en") else "3D Animation In Hindi"
            metadata = {
                "title": f"{clean_slug} ({fallback_lang_tag}) #shorts",
                "description": "",
                "tags": [],
                "hashtags": []
            }
            timings["6. Social Metadata"] = (0.0, "Skipped")

        # Rename final dubbed video to carry the Title in its filename
        if metadata and metadata.get("title") and final_video.exists():
            clean_title_fn = sanitize_title_for_filename(metadata["title"])
            if clean_title_fn:
                ratio_tag = " Square" if ratio_norm == "square" else ""
                movie_tag = " Movie" if movie else ""
                crop_tag = " Smart Crop" if smart_crop else ""
                mirror_tag = " Mirrored" if mirror else ""
                mode_tag = f" {normalized_mode.replace('_', ' ').title()}" if normalized_mode != "block_aligned" else ""
                var_tag = f" [{active_style.title()}{mode_tag}{mirror_tag}{crop_tag}{movie_tag}{ratio_tag}]" if (active_style != "viral" or normalized_mode != "block_aligned" or mirror or smart_crop or movie or ratio_norm != "reel") else ""
                titled_video = final_video.with_name(f"{clean_title_fn}{var_tag}.mp4")
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

        # Persist the render (also covers cached/no-metadata runs)
        self._record_registry_render(
            final_video=final_video,
            title=str((metadata or {}).get("title") or clean_slug),
            language=target_lang,
            tts_engine=self.tts_engine,
            metadata=metadata or {},
            video_id=registry_video_id,
            channel=detected_channel,
        )

        # Identify and link the movie (name/year/genre/synopsis) for this video
        movie_details = self._record_registry_movie(
            video_title=clean_slug,
            metadata=metadata,
            video_id=registry_video_id,
            source_ref=source_ref if source_ref.lower().startswith(("http://", "https://")) else "",
            channel=detected_channel,
            force_lookup=bool(movie or capture_movie_details),
        )
        if movie_details and enable_metadata and meta_json_file and metadata is not None:
            try:
                meta_json_file.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass

        # Clean up per-video intermediate temp files (moviecrop, clean plates, stems, block_align slices)
        if not is_debug:
            self._cleanup_temp_files(
                clean_slug=clean_slug,
                clean_video_target=clean_video_target,
                video_for_dubbing=video_for_dubbing,
                sfx_track=sfx_track,
                video_work_dir=video_work_dir,
            )

        # -------------------------------------------------------------
        # Optional Thumbnail Generation (--thumbnail / -thumb)
        # -------------------------------------------------------------
        generated_thumbnail_path = None
        if thumbnail:
            try:
                from .thumbnail_generator import generate_video_thumbnail
                thumb_target = final_video if (final_video and final_video.exists()) else video_path
                script_sample = ""
                if dubbed_srt and Path(dubbed_srt).exists():
                    script_sample = "\n".join([
                        line.strip()
                        for line in Path(dubbed_srt).read_text(encoding="utf-8").splitlines()
                        if line.strip() and not line.strip().isdigit() and "-->" not in line
                    ][:15])
                generated_thumbnail_path = generate_video_thumbnail(
                    video_path=thumb_target,
                    script_text=script_sample,
                    title=str((metadata or {}).get("title") or clean_slug),
                    output_dir=self.thumbnails_dir,
                    output_name=final_video.stem if final_video else clean_slug,
                )
                if generated_thumbnail_path and generated_thumbnail_path.exists():
                    print(f"[Thumbnail Generator] Thumbnail created at: {generated_thumbnail_path}")
            except Exception as thumb_err:
                print(f"[Thumbnail Generator Warning] Failed to generate thumbnail: {thumb_err}")

        # Mirror final dubbed video to Google Drive final_videos/ only when running standalone (not inside run_folder)
        drive_video_path = None
        if not channel_name:
            drive_base = resolve_google_drive_base()
            if drive_base and drive_base.exists() and final_video.exists():
                drive_final_dir = drive_base / "final_videos"
                drive_final_dir.mkdir(parents=True, exist_ok=True)
                import shutil
                try:
                    dest_drive = drive_final_dir / final_video.name
                    shutil.copy2(str(final_video), str(dest_drive))
                    drive_video_path = dest_drive
                    print(f"[Google Drive Sync] Synced final dubbed video to: {dest_drive}")
                    drive_thumbnail_path = None
                    if generated_thumbnail_path and generated_thumbnail_path.exists():
                        drive_thumb_dest = drive_final_dir / generated_thumbnail_path.name
                        shutil.copy2(str(generated_thumbnail_path), str(drive_thumb_dest))
                        drive_thumbnail_path = drive_thumb_dest
                        print(f"[Google Drive Sync] Synced thumbnail to: {drive_thumb_dest}")
                    self._record_registry_drive(
                        drive_path=dest_drive,
                        video_id=registry_video_id,
                        final_video=final_video,
                        thumbnail_path=drive_thumbnail_path,
                    )
                    if move_to_drive and dest_drive.exists() and dest_drive.stat().st_size == final_video.stat().st_size:
                        freed_mb = final_video.stat().st_size / (1024 * 1024)
                        final_video.unlink()
                        print(f"[Disk Saver] Deleted local final video after Drive transfer ({freed_mb:.1f} MB freed): {final_video.name}")
                        if delete_input and video_path.exists() and str(video_path.resolve()).startswith(str(self.input_dir.resolve())):
                            in_mb = video_path.stat().st_size / (1024 * 1024)
                            video_path.unlink()
                            print(f"[Disk Saver] Deleted local downloaded source video ({in_mb:.1f} MB freed): {video_path.name}")
                except Exception as sync_err:
                    print(f"[Google Drive Sync Warning] Could not sync to Drive ({sync_err}). Local video kept at: {final_video}")

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
            "drive_video": drive_video_path,
            "thumbnail": generated_thumbnail_path,
            "metadata": metadata,
            "clean_title": clean_slug,
            "translation_report": report,
            "tts_engine_used": self.tts_engine,
        }

    def _resolve_royalty_free_bgm(self, movie: bool = False) -> Optional[Path]:
        """Finds a background music track randomly (dedicated 'movie explanation/' folder in --movie mode)."""
        import random
        root_dir = Path(__file__).resolve().parent.parent
        base_dirs = [
            Path("Background Audios"),
            root_dir / "Background Audios",
            Path("assets/background_audio"),
            root_dir / "assets/background_audio",
        ]
        bg_dirs = ([d / "movie explanation" for d in base_dirs] + base_dirs) if movie else base_dirs
        for bd in bg_dirs:
            if bd.exists() and bd.is_dir():
                tracks = sorted([f for f in bd.glob("*.mp3")] + [f for f in bd.glob("*.wav")])
                if tracks:
                    return random.choice(tracks)
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
        bgm_volume: Optional[float] = None,
        enable_metadata: bool = True,
        style: str = "viral",
        fit_short: bool = False,
        max_duration: float = 58.0,
        anti_accent: bool = False,
        loop: bool = False,
        mirror: bool = False,
        smart_crop: bool = False,
        movie: bool = False,
        ratio: str = "reel",
        watermark: Optional[str] = None,
        disable_bgm: bool = False,
        allow_tts_fallback: bool = True,
        move_to_drive: bool = False,
        delete_input: bool = False,
        thumbnail: bool = False,
        capture_movie_details: bool = False,
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
            free_gb = shutil.disk_usage(target_out_dir).free / (1024 ** 3)
            print(f" Local Free Disk Space: {free_gb:.2f} GB")
            if move_to_drive:
                print(f" Auto-Offload Mode: Transfer each video to Google Drive and delete local video files")
            print("#" * 65 + "\n")

            drive_base = resolve_google_drive_base()
            drive_target_dir = (drive_base / cur_folder.name) if (drive_base and drive_base.exists()) else None
            if drive_target_dir is not None:
                drive_target_dir.mkdir(parents=True, exist_ok=True)
            transferred_drive_names = set()

            def _write_master_metadata(results_so_far: List[Dict[str, Any]]):
                master_videos_list = []
                for r in results_so_far:
                    fpath_cand = Path(r["final_video"]) if r.get("final_video") else None
                    has_output = bool(fpath_cand and (fpath_cand.exists() or r.get("drive_video")))
                    if not has_output:
                        continue
                    meta = r.get("metadata", {})
                    if not meta and r.get("clean_title"):
                        cand_meta = self.metadata_dir / f"{r['clean_title']}_hindi_metadata.json"
                        if cand_meta.exists():
                            try:
                                meta = json.loads(cand_meta.read_text(encoding="utf-8"))
                            except Exception:
                                meta = {}

                    video_title = meta.get("title", fpath_cand.stem if fpath_cand else "Video")
                    video_desc = meta.get("description", "")
                    if len(video_desc) >= 5000:
                        video_desc = video_desc[:4950].rsplit(",", 1)[0].rstrip()
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
                return master_videos_list

            folder_results = []
            for idx, vid in enumerate(video_files, start=1):
                print(f"\n=======================================================")
                print(f" >>> [{idx}/{len(video_files)}] Processing Video: {vid.name}")
                print(f"=======================================================")
                self.output_dir = target_out_dir
                # Check key pool before each video:
                # If ElevenLabs was selected but keys ran out of quota, automatically switch to Google Gemini Flash 3.8
                if self.tts_engine in ("elevenlabs", "eleven_labs", "11labs") and allow_tts_fallback:
                    if not get_active_elevenlabs_keys():
                        if get_active_gemini_keys():
                            print("\n[Batch Folder Fallback] ElevenLabs keys exhausted! Switching batch engine to Google Gemini Flash 3.8 TTS...")
                            self.tts_engine = "google"
                        elif get_active_sarvam_keys():
                            print("\n[Batch Folder Fallback] ElevenLabs & Gemini exhausted! Switching batch engine to Sarvam Bulbul V4...")
                            self.tts_engine = "sarvam"
                        else:
                            print("\n[Batch Folder Fallback] Switching batch engine to Local Kokoro TTS...")
                            self.tts_engine = "kokoro"
                elif self.tts_engine in ("google", "gemini") and allow_tts_fallback:
                    if not get_active_gemini_keys():
                        if get_active_sarvam_keys():
                            print("\n[Batch Folder Fallback] Google Gemini keys exhausted! Switching batch engine to Sarvam Bulbul V4...")
                            self.tts_engine = "sarvam"
                        else:
                            print("\n[Batch Folder Fallback] Switching batch engine to Local Kokoro TTS...")
                            self.tts_engine = "kokoro"
                elif self.tts_engine in ("sarvam", "sarvamai") and allow_tts_fallback:
                    if not get_active_sarvam_keys():
                        print("\n[Batch Folder Fallback] Sarvam keys exhausted! Switching batch engine to Local Kokoro TTS...")
                        self.tts_engine = "kokoro"
                registry_video_id = self._record_registry_download(
                    source_url="",
                    local_path=vid,
                    channel=cur_folder.name,
                    batch=cur_folder.name,
                )
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
                        max_duration=max_duration,
                        channel_name=cur_folder.name,
                        anti_accent=anti_accent,
                        loop=loop,
                        mirror=mirror,
                        smart_crop=smart_crop,
                        movie=movie,
                        ratio=ratio,
                        watermark=watermark,
                        disable_bgm=disable_bgm,
                        allow_tts_fallback=allow_tts_fallback,
                        thumbnail=thumbnail,
                        capture_movie_details=capture_movie_details,
                    )

                    self._record_registry_render(
                        final_video=res.get("final_video"),
                        title=str((res.get("metadata") or {}).get("title") or res.get("clean_title") or ""),
                        language=target_lang,
                        tts_engine=str(res.get("tts_engine_used") or self.tts_engine),
                        metadata=res.get("metadata") or {},
                        video_id=registry_video_id,
                        source_url=str(vid),
                        channel=cur_folder.name,
                        batch=cur_folder.name,
                    )
                    self._record_registry_movie(
                        video_title=str(res.get("clean_title") or ""),
                        metadata=res.get("metadata") or {},
                        video_id=registry_video_id,
                        source_ref=str(vid),
                        channel=cur_folder.name,
                        batch=cur_folder.name,
                        force_lookup=bool(movie or capture_movie_details)
                        and not (res.get("metadata") or {}).get("movie_name"),
                    )

                    if move_to_drive and res.get("final_video"):
                        fpath = Path(res["final_video"])
                        if fpath.exists():
                            transferred_ok = False
                            if drive_target_dir is not None:
                                dest_video = drive_target_dir / fpath.name
                                shutil.copy2(str(fpath), str(dest_video))
                                if dest_video.exists() and dest_video.stat().st_size == fpath.stat().st_size:
                                    res["drive_video"] = str(dest_video)
                                    transferred_drive_names.add(fpath.name)
                                    transferred_ok = True
                                    print(f"  [Drive Offload] Transferred to Drive: {dest_video}")
                                    drive_thumb_dest = None
                                    if res.get("thumbnail"):
                                        tpath = Path(res["thumbnail"])
                                        if tpath.exists():
                                            dest_thumb = drive_target_dir / tpath.name
                                            shutil.copy2(str(tpath), str(dest_thumb))
                                            drive_thumb_dest = dest_thumb
                                            print(f"  [Drive Offload] Transferred thumbnail to Drive: {dest_thumb}")
                                    self._record_registry_drive(
                                        drive_path=dest_video,
                                        final_video=fpath,
                                        thumbnail_path=drive_thumb_dest,
                                        video_id=registry_video_id,
                                        source_url=str(vid),
                                    )
                            else:
                                from .gdrive_uploader import GoogleDriveUploader
                                uploader = GoogleDriveUploader()
                                drive_folder = uploader.get_or_create_subfolder(cur_folder.name)
                                uploaded = uploader.upload_file(fpath, folder_id=drive_folder["id"], skip_if_exists=False)
                                file_id = uploaded.get("id", "")
                                link = uploaded.get("webViewLink") or (
                                    f"https://drive.google.com/file/d/{file_id}/view" if file_id else ""
                                )
                                res["drive_video"] = link or file_id
                                transferred_drive_names.add(fpath.name)
                                transferred_ok = True
                                print(f"  [Drive API Offload] Uploaded to Drive: {fpath.name}")
                                self._record_registry_drive(
                                    drive_path=Path("douyin") / cur_folder.name / fpath.name,
                                    final_video=fpath,
                                    link=link,
                                    file_id=file_id,
                                    thumbnail_path=res.get("thumbnail"),
                                    video_id=registry_video_id,
                                    source_url=str(vid),
                                )

                            if transferred_ok:
                                freed_mb = fpath.stat().st_size / (1024 * 1024)
                                fpath.unlink()
                                print(f"  [Disk Saver] Deleted local output video ({freed_mb:.1f} MB freed): {fpath.name}")
                                if delete_input and vid.exists():
                                    in_mb = vid.stat().st_size / (1024 * 1024)
                                    vid.unlink()
                                    print(f"  [Disk Saver] Deleted local source video ({in_mb:.1f} MB freed): {vid.name}")
                                free_gb_now = shutil.disk_usage(target_out_dir).free / (1024 ** 3)
                                print(f"  [Disk Space] Free space remaining: {free_gb_now:.2f} GB")

                    folder_results.append(res)
                    if move_to_drive:
                        _write_master_metadata(folder_results)
                        if drive_target_dir is not None and metadata_path.exists():
                            shutil.copy2(str(metadata_path), str(drive_target_dir / "metadata.json"))
                except Exception as e:
                    print(f"[Pipeline ERROR] Failed processing video '{vid.name}': {e}")
                    import traceback
                    traceback.print_exc()

            # Compile single master metadata JSON carrying:
            # - number_of_videos
            # - titles of the videos
            # - descriptions of the videos
            # - tags (up to 3 high-relevance SEO tags for YouTube)
            master_videos_list = _write_master_metadata(folder_results)
            print(f"\n[Pipeline Master Metadata] Successfully wrote master metadata.json ({len(master_videos_list)} videos with SEO tags) to: {metadata_path}")

            # Google Drive Synchronization:
            # The folder uploaded to Drive only has the final output videos with Title filenames,
            # and strictly one master JSON file carrying number_of_videos, titles, descriptions, and SEO tags.
            if drive_target_dir is not None:
                print(f"\n[Google Drive Folder Sync] Synchronizing folder '{cur_folder.name}' to Drive: {drive_target_dir}")

                allowed_files = set(transferred_drive_names)
                # 1. Sync final output videos not already offloaded
                for r in folder_results:
                    fpath = Path(r["final_video"])
                    if fpath.name in transferred_drive_names:
                        allowed_files.add(fpath.name)
                        continue
                    if fpath.exists():
                        dest_video = drive_target_dir / fpath.name
                        shutil.copy2(str(fpath), str(dest_video))
                        allowed_files.add(fpath.name)
                        print(f"  [Drive Sync Video] Synced final output video: {fpath.name}")
                        thumb_dest = None
                        if r.get("thumbnail"):
                            thumb_src = Path(r["thumbnail"])
                            if thumb_src.exists():
                                thumb_dest = drive_target_dir / thumb_src.name
                                shutil.copy2(str(thumb_src), str(thumb_dest))
                                allowed_files.add(thumb_src.name)
                        self._record_registry_drive(
                            drive_path=dest_video,
                            final_video=fpath,
                            thumbnail_path=thumb_dest,
                        )

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
            else:
                try:
                    from .gdrive_uploader import GoogleDriveUploader
                    print(f"\n[Google Drive API Upload] Mounted Drive folder not found; uploading '{cur_folder.name}' via Google Drive API...")
                    uploader = GoogleDriveUploader()
                    drive_folder = uploader.get_or_create_subfolder(cur_folder.name)
                    folder_id = drive_folder["id"]
                    for r in folder_results:
                        fpath = Path(r["final_video"])
                        if fpath.name not in transferred_drive_names and fpath.exists():
                            uploader.upload_file(fpath, folder_id=folder_id, skip_if_exists=False)
                    if metadata_path.exists():
                        uploader.upload_file(metadata_path, folder_id=folder_id, skip_if_exists=False)
                    print(f"  [Google Drive API Upload] Uploaded batch '{cur_folder.name}' -> {drive_folder.get('webViewLink', folder_id)}")
                except Exception as e:
                    print(f"  [Google Drive Upload Warning] Skipping Drive upload (mounted Drive unavailable and API upload failed: {e})")

            results[cur_folder.name] = {
                "output_dir": target_out_dir,
                "metadata_file": metadata_path,
                "processed_videos": folder_results
            }

        self.output_dir = original_base_output
        self._setup_output_dirs(original_base_output)
        return results

    def run_profile(
        self,
        profile_url: str,
        target_lang: str = "Hindi",
        voice: Optional[str] = None,
        base_speed: float = 1.0,
        batch_size: int = 35,
        force: bool = False,
        dub_mode: str = "block_aligned",
        preserve_bgm: bool = True,
        clean_subtitles: bool = True,
        remove_watermark: bool = False,
        bgm_volume: Optional[float] = None,
        enable_metadata: bool = True,
        style: str = "viral",
        fit_short: bool = False,
        max_duration: float = 58.0,
        max_videos: Optional[int] = None,
        sort_by: str = "popularity",
        max_pages: Optional[int] = None,
        anti_accent: bool = False,
        loop: bool = False,
        mirror: bool = False,
        smart_crop: bool = False,
        movie: bool = False,
        ratio: str = "reel",
        watermark: Optional[str] = None,
        disable_bgm: bool = False,
        allow_tts_fallback: bool = True,
        move_to_drive: bool = False,
        delete_input: bool = False,
        thumbnail: bool = False,
        capture_movie_details: bool = False,
    ) -> Dict[str, Any]:
        """
        Download all videos from a Douyin user profile / channel URL into input/<channel_name>
        and automatically process every video through the full dubbing pipeline.
        """
        print("\n" + "=" * 65)
        print(" [Dubbing Studio] AUTO-DOWNLOADING DOUYIN PROFILE & BATCH PROCESSING")
        print(f" Profile URL : {profile_url}")
        print(f" Max Videos  : {max_videos or 'All'}")
        print(f" Sort By     : {sort_by}")
        if max_pages:
            print(f" Max Pages   : {max_pages}")
        print("=" * 65)

        channel_folder = self.downloader.download_channel(
            channel_url=profile_url,
            output_dir=self.input_dir,
            max_videos=max_videos,
            sort_by=sort_by,
            max_pages=max_pages
        )

        return self.run_folder(
            folder_path=channel_folder,
            target_lang=target_lang,
            voice=voice,
            base_speed=base_speed,
            batch_size=batch_size,
            force=force,
            dub_mode=dub_mode,
            preserve_bgm=preserve_bgm,
            clean_subtitles=clean_subtitles,
            remove_watermark=remove_watermark,
            bgm_volume=bgm_volume,
            enable_metadata=enable_metadata,
            style=style,
            fit_short=fit_short,
            max_duration=max_duration,
            anti_accent=anti_accent,
            loop=loop,
            mirror=mirror,
            smart_crop=smart_crop,
            movie=movie,
            ratio=ratio,
            watermark=watermark,
            disable_bgm=disable_bgm,
            allow_tts_fallback=allow_tts_fallback,
            move_to_drive=move_to_drive,
            delete_input=(delete_input or move_to_drive),
            capture_movie_details=capture_movie_details,
        )

    run_channel = run_profile

    def run_urls(
        self,
        urls: List[str],
        batch_name: Optional[str] = None,
        target_lang: str = "Hindi",
        voice: Optional[str] = None,
        base_speed: float = 1.0,
        batch_size: int = 35,
        force: bool = False,
        dub_mode: str = "block_aligned",
        preserve_bgm: bool = True,
        clean_subtitles: bool = True,
        remove_watermark: bool = False,
        bgm_volume: Optional[float] = None,
        enable_metadata: bool = True,
        style: str = "viral",
        fit_short: bool = False,
        max_duration: float = 58.0,
        anti_accent: bool = False,
        loop: bool = False,
        mirror: bool = False,
        smart_crop: bool = False,
        movie: bool = False,
        ratio: str = "reel",
        watermark: Optional[str] = None,
        disable_bgm: bool = False,
        allow_tts_fallback: bool = True,
        move_to_drive: bool = False,
        delete_input: bool = False,
        thumbnail: bool = False,
        capture_movie_details: bool = True,
    ) -> Dict[str, Any]:
        """
        Download a list of Douyin/TikTok URLs into a single batch input folder
        input/<batch_name>/ and process them together as one batch into
        output/<batch_name>/ with master metadata.json and Google Drive upload.
        """
        clean_urls = _extract_batch_urls("\n".join(str(u) for u in (urls or [])))
        if not clean_urls:
            raise ValueError("No valid Douyin/TikTok URLs provided to run_urls().")

        safe_batch_name = _sanitize_batch_name(batch_name or "")
        batch_input_dir = self.input_dir / safe_batch_name
        batch_input_dir.mkdir(parents=True, exist_ok=True)

        print("\n" + "=" * 65)
        print(" [Dubbing Studio] BATCH URLS DOWNLOAD & PIPELINE")
        print(f" Batch Name  : {safe_batch_name}")
        print(f" Total URLs  : {len(clean_urls)}")
        print(f" Input Dir   : {batch_input_dir}")
        print("=" * 65)

        downloaded_paths: List[Path] = []
        failed_urls: List[Dict[str, str]] = []
        for idx, video_url in enumerate(clean_urls, start=1):
            print(f"\n[Batch URL {idx}/{len(clean_urls)}] Downloading: {video_url}")
            try:
                dl_path = self.downloader.download_video(video_url, output_dir=batch_input_dir)
                downloaded_paths.append(Path(dl_path))
                self._record_registry_download(
                    source_url=video_url,
                    local_path=dl_path,
                    batch=safe_batch_name,
                )
            except Exception as e:
                print(f"  [Batch URL Warning] Failed to download {video_url}: {e}")
                failed_urls.append({"url": video_url, "error": str(e)})
                if self.registry:
                    try:
                        self.registry.record_failure(
                            str(e)[:500],
                            source_url=video_url,
                        )
                    except Exception as registry_err:
                        print(f"  [Registry] Warning: failure record failed ({registry_err})")

        print("\n" + "-" * 65)
        print(f" [Batch Download Summary] Downloaded: {len(downloaded_paths)}/{len(clean_urls)}")
        if failed_urls:
            print(f" [Batch Download Summary] Failed ({len(failed_urls)}):")
            for fail in failed_urls:
                print(f"   - {fail['url']} -> {fail['error']}")
        print("-" * 65)

        video_exts = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
        available_videos = [
            f for f in batch_input_dir.iterdir()
            if f.is_file() and f.suffix.lower() in video_exts
        ]
        if not available_videos:
            raise RuntimeError(f"All {len(clean_urls)} batch URL downloads failed; no videos in {batch_input_dir}.")

        return self.run_folder(
            folder_path=batch_input_dir,
            target_lang=target_lang,
            voice=voice,
            base_speed=base_speed,
            batch_size=batch_size,
            force=force,
            dub_mode=dub_mode,
            preserve_bgm=preserve_bgm,
            clean_subtitles=clean_subtitles,
            remove_watermark=remove_watermark,
            bgm_volume=bgm_volume,
            enable_metadata=enable_metadata,
            style=style,
            fit_short=fit_short,
            max_duration=max_duration,
            anti_accent=anti_accent,
            loop=loop,
            mirror=mirror,
            smart_crop=smart_crop,
            movie=movie,
            ratio=ratio,
            watermark=watermark,
            disable_bgm=disable_bgm,
            allow_tts_fallback=allow_tts_fallback,
            move_to_drive=move_to_drive,
            delete_input=(delete_input or move_to_drive),
            capture_movie_details=capture_movie_details,
        )


def main():
    parser = argparse.ArgumentParser(description="Douyin / TikTok Automated Dubbing Studio Pipeline")
    parser.add_argument("--url", type=str, default="", help="Douyin/TikTok video URL, path to local MP4, or folder")
    parser.add_argument(
        "--profile", "--douyin-profile", "--channel", "--douyin-channel",
        "--profile-url", "--channel-url", "--user", "--user-url",
        type=str, default="",
        help="Douyin user profile or channel URL to auto-download and process all videos through the pipeline"
    )
    parser.add_argument(
        "--max-videos", type=int, default=None,
        help="Maximum number of videos to download from profile (default: None for all available)"
    )
    parser.add_argument(
        "--sort-by", type=str, default="popularity",
        choices=["popularity", "popular", "likes", "date", "latest"],
        help="Sort profile videos by popularity or date (default: popularity)"
    )
    parser.add_argument(
        "--max-pages", "--pages", type=int, default=None,
        help="Maximum pagination pages to fetch when downloading profile (default: None for all)"
    )
    parser.add_argument("--folder", "--input-dir", type=str, default="", help="Directory containing videos or subfolders of videos to batch process")
    parser.add_argument(
        "--batch-urls", "--urls", "--prompt-urls",
        action="store_true", default=False,
        help="Interactive batch mode: prompt for multiple Douyin/TikTok URLs once launched, process them together in one batch folder, and upload to Google Drive"
    )
    parser.add_argument(
        "--batch-name", type=str, default="",
        help="Optional batch folder name for --batch-urls (prompts or auto-generates batch_YYYYMMDD_HHMMSS if omitted)"
    )
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
    parser.add_argument("--model", type=str, default="gemini-3.5-flash-lite", help="Gemini model name for translation waterfall (default: gemini-3.5-flash-lite)")
    parser.add_argument("--batch-size", type=int, default=35, help="Batch size for subtitle chunks")
    parser.add_argument("--no-bgm", action="store_true", help="Disable BGM/SFX preservation (clean voiceover only)")
    parser.add_argument("--no-clean", action="store_true", help="Disable automatic subtitle & watermark inpainting")
    parser.add_argument("--include-watermark", action="store_true", help="Also inpaint corner watermark (takes 2x longer, default: off)")
    parser.add_argument("--force", "--reloop", action="store_true", dest="force", help="Force re-transcription, re-translation, and re-separation")
    parser.add_argument("--metadata", action="store_true", default=True, help="Generate viral social media metadata via Gemini (default: True)")
    parser.add_argument("--bgm-volume", type=float, default=None, help="Background music volume multiplier (default: 1.05, or 1.35 in --movie mode)")
    parser.add_argument("--no-metadata", action="store_true", default=False, help="Disable social metadata generation")
    parser.add_argument("--short", "-s", "--fit-short", action="store_true", help="Condense any video (e.g. 1-2+ mins) into a punchy 1-minute video (<= 58s) via block-by-block Gemini script condensation and Block Aligner")
    parser.add_argument("--max-duration", type=float, default=58.0, help="Target max duration in seconds when --short is enabled (default: 58.0s for YouTube Shorts / Reels)")
    parser.add_argument("--anti-accent", "--deaccent", "--break-english-pairs", action="store_true", help="Anti-accent mode: keep multi-syllable/heavy words in English script, but convert lower-syllable consecutive English words to Devanagari to prevent neural TTS Western accent switching")
    parser.add_argument("--loop", "--infinite-loop", action="store_true", default=False, help="Enable Method 1 Infinite Loop: bridge final block smoothly into block 1 as a single continuous sentence")
    parser.add_argument("--mirror", "--hflip", "--anti-copyright", action="store_true", default=False, help="Anti-copyright mode: horizontally mirror video (hflip) and apply subtle color grade (contrast/saturation) to change visual hash while keeping subtitles readable left-to-right")
    parser.add_argument("--smart-crop", "--crop-expand", "--interior-short", action="store_true", default=False, help="Smart Crop Mode: crops off bottom Chinese subtitles (bottom 15%%) while maintaining 9:16 portrait ratio, translates opening center-top Chinese hook title into English, and disables burned-in bottom subtitles")
    parser.add_argument("--movie", "--movie-explanation", action="store_true", default=False, help="Movie Mode: fast OCR top/bottom edge-caption crop, auto-Reels blurred canvas for non-vertical video, picks BGM from 'assets/background_audio/movie explanation/' (1.35x), preserves original video duration without compaction, and word-synced bold display captions")
    parser.add_argument("--ratio", "--aspect-ratio", type=str, default="reel", help="Output video aspect ratio: 'reel' (default 9:16 portrait) or 'square' (1:1 center-cropped 1080x1080 with condensed bold-italic word captions)")
    parser.add_argument("--watermark", "--channel-watermark", type=str, default="", help="Channel text watermark rendered at bottom center using SoftLight blend with subtle dark stroke and drop shadow (e.g. --watermark 'Wholesome Wendy')")
    parser.add_argument("--move-to-drive", "--delete-local", "--offload-drive", action="store_true", default=False, help="Transfer each finished video to Google Drive and immediately delete local video files to save disk space")
    parser.add_argument("--thumbnail", "-thumb", "--thumb", action="store_true", default=False, help="Generate thumbnail (auto-detects vertical 9:16 for <3min videos or horizontal 16:9 for >=3min videos, pure image, no text)")
    parser.add_argument("--reset-elevenlabs-keys", action="store_true", default=False, help="Clear the local persisted blocklist of exhausted ElevenLabs keys (without modifying .env)")
    parser.add_argument("--registry-db", type=str, default="", help="Custom SQLite video registry path (default: output/video_registry.db)")
    parser.add_argument("--no-registry", action="store_true", default=False, help="Disable the SQLite video registry for this run")
    parser.add_argument("--capture-movie-details", action="store_true", default=False, help="Identify and store movie name/year/genre/synopsis in the registry (automatic for --batch-urls and --movie)")
    parser.add_argument("--debug", action="store_true", help="Debug mode: print detailed OCR/audio/BGM telemetry and preserve all intermediate files")
    args = parser.parse_args()

    if args.reset_elevenlabs_keys:
        cleared = reset_exhausted_elevenlabs_keys()
        print(f"[Key Pool] Cleared {cleared} exhausted ElevenLabs key record(s) from local pool cache.")

    # When --short / -s is enabled, default to Sarvam AI (shubh) unless user explicitly specified another engine
    if args.short and not any(flag in sys.argv for flag in ("--tts", "--tts-engine", "--elevenlabs")):
        args.tts = "sarvam"
        args.voice = "shubh"

    if args.elevenlabs:
        args.tts = "elevenlabs"

    if not args.voice:
        if args.tts in ("elevenlabs", "eleven_labs", "11labs"):
            args.voice = "roger"
        elif args.tts in ("google", "gemini"):
            args.voice = "Ludo"
        elif args.tts in ("sarvam", "bulbul"):
            args.voice = "shubh"

    batch_name_input = ""
    batch_urls: List[str] = []
    if args.batch_urls:
        batch_name_input, batch_urls = _prompt_batch_inputs(default_batch_name=args.batch_name)
        if not batch_urls:
            parser.error("No valid Douyin/TikTok URLs were provided in --batch-urls prompt.")

    out_folder = Path(args.output) if args.output else Path.cwd() / "output"
    in_folder = Path(args.input_dir) if getattr(args, "input_dir", None) else None
    pipeline = DubbingPipeline(
        input_dir=in_folder,
        output_dir=out_folder,
        gemini_model=args.model,
        tts_engine=args.tts,
        debug=args.debug,
        registry_db=args.registry_db or None,
        enable_registry=not args.no_registry,
    )

    if args.reorganize:
        pipeline.reorganize_existing_output()
        print("[Pipeline] Reorganization complete!")
        if not (args.batch_urls or args.profile or args.url or args.folder):
            return

    input_profile = args.profile.strip()
    input_target = input_profile or args.folder or args.url
    if not input_target and not args.batch_urls:
        parser.error("Please provide --batch-urls, --profile (Douyin profile URL), --url (video URL/file), or --folder")

    target_path = Path(input_target)
    is_url = bool(args.url or input_profile) or input_target.lower().startswith("http://") or input_target.lower().startswith("https://")
    
    # Check if input is a Douyin profile URL (ensure modal_id single video URLs are treated as single video)
    has_modal_or_vid = "modal_id=" in input_target.lower() or "vid=" in input_target.lower()
    is_profile_input = (bool(input_profile) and not has_modal_or_vid) or (
        is_url and not has_modal_or_vid and not bool(args.url) and (
            "/user/" in input_target.lower()
            or "sec_user_id" in input_target.lower()
        )
    )

    is_folder_input = (not is_url) and (not is_profile_input) and (
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

    shared_kwargs = dict(
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
        max_duration=max_dur,
        anti_accent=args.anti_accent,
        loop=args.loop,
        mirror=args.mirror,
        smart_crop=args.smart_crop,
        movie=args.movie,
        ratio=normalize_aspect_ratio(args.ratio),
        watermark=args.watermark.strip() or None,
        move_to_drive=args.move_to_drive,
        delete_input=args.move_to_drive,
        thumbnail=args.thumbnail,
        capture_movie_details=bool(args.capture_movie_details or args.batch_urls),
    )

    if args.batch_urls:
        pipeline.run_urls(
            urls=batch_urls,
            batch_name=batch_name_input,
            **shared_kwargs,
        )
    elif is_profile_input:
        profile_url = input_profile or input_target
        pipeline.run_profile(
            profile_url=profile_url,
            max_videos=args.max_videos,
            sort_by=args.sort_by,
            max_pages=args.max_pages,
            **shared_kwargs,
        )
    elif is_folder_input:
        pipeline.run_folder(
            folder_path=target_path,
            **shared_kwargs,
        )
    else:
        pipeline.run(
            url_or_file=input_target,
            **shared_kwargs,
        )


if __name__ == "__main__":
    main()
