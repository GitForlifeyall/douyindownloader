"""
Thumbnail Generator Module for Dubbing Studio.

Generates pure AI visual thumbnails without text overlay:
- Auto-detects video duration:
  * Duration < 3 minutes (< 180s) -> Vertical format (9:16 aspect ratio, 1080x1920)
  * Duration >= 3 minutes (>= 180s) -> Horizontal format (16:9 aspect ratio, 1920x1080)
- Primary engine: Google Flow (Nano Banana 2.1) via headless client
- Fallback engine: Laplacian-variance sharp frame extraction cropped to target aspect ratio
"""

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import cv2
from PIL import Image

logger = logging.getLogger(__name__)


def get_video_duration(video_path: Path) -> float:
    """
    Returns duration of video in seconds using OpenCV, with fallback to ffprobe.
    Returns 0.0 if unable to determine duration.
    """
    if not video_path.exists():
        return 0.0

    # 1. Primary: OpenCV VideoCapture
    try:
        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
        cap.release()
        if fps > 0 and frame_count > 0:
            return float(frame_count / fps)
    except Exception as e:
        logger.debug(f"[ThumbnailGenerator] OpenCV duration probe failed: {e}")

    # 2. Secondary: ffprobe CLI
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
        if res.returncode == 0 and res.stdout.strip():
            return float(res.stdout.strip())
    except Exception as e:
        logger.debug(f"[ThumbnailGenerator] ffprobe duration probe failed: {e}")

    return 0.0


def _extract_best_frame(
    video_path: Path,
    output_frame_path: Path,
    is_vertical: bool = True,
) -> bool:
    """
    Extracts the highest-variance sharp frame from the video,
    cropped and resized to the target aspect ratio (9:16 vertical or 16:9 horizontal).
    """
    if not video_path.exists():
        return False
    try:
        cap = cv2.VideoCapture(str(video_path))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            cap.release()
            return False

        # Sample candidate frames across the video and pick the one with highest visual variance
        sample_fractions = [0.20, 0.35, 0.50, 0.65, 0.80]
        best_frame = None
        best_score = -1.0

        for frac in sample_fractions:
            target_idx = int(total_frames * frac)
            cap.set(cv2.CAP_PROP_POS_FRAMES, target_idx)
            ret, frame = cap.read()
            if not ret or frame is None:
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            score = cv2.Laplacian(gray, cv2.CV_64F).var()
            if score > best_score:
                best_score = score
                best_frame = frame

        cap.release()
        if best_frame is None:
            return False

        # Convert OpenCV BGR to PIL Image for aspect-ratio cropping/resizing
        rgb = cv2.cvtColor(best_frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)
        w, h = img.size

        if is_vertical:
            # Target 9:16 (1080x1920)
            target_ratio = 9.0 / 16.0
            cur_ratio = w / h
            if cur_ratio > target_ratio:
                # Wider than 9:16: crop sides
                crop_w = int(h * target_ratio)
                left = (w - crop_w) // 2
                img = img.crop((left, 0, left + crop_w, h))
            elif cur_ratio < target_ratio:
                # Taller than 9:16: crop top/bottom
                crop_h = int(w / target_ratio)
                top = (h - crop_h) // 2
                img = img.crop((0, top, w, top + crop_h))
            img = img.resize((1080, 1920), Image.Resampling.LANCZOS)
        else:
            # Target 16:9 (1920x1080)
            target_ratio = 16.0 / 9.0
            cur_ratio = w / h
            if cur_ratio > target_ratio:
                # Wider than 16:9: crop sides
                crop_w = int(h * target_ratio)
                left = (w - crop_w) // 2
                img = img.crop((left, 0, left + crop_w, h))
            elif cur_ratio < target_ratio:
                # Taller than 16:9: crop top/bottom
                crop_h = int(w / target_ratio)
                top = (h - crop_h) // 2
                img = img.crop((0, top, w, top + crop_h))
            img = img.resize((1920, 1080), Image.Resampling.LANCZOS)

        output_frame_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(output_frame_path), "JPEG", quality=95)
        return True
    except Exception as e:
        logger.warning(f"[ThumbnailGenerator] Failed to extract best video frame: {e}")
        return False


def craft_cinematic_prompt(
    title: str = "",
    script_text: str = "",
    is_vertical: bool = True,
) -> str:
    """
    Formulates an ultra-cinematic, photorealistic prompt for Google Flow (Nano Banana 2.1).
    Extracts high-action premise from title and script while strictly forbidding text overlays.
    """
    clean_title = re.sub(r"[#\[\(].*?[#\]\)]", "", title).strip() if title else ""
    # Strip common clutter words
    for noise in ["3D Animation", "In Hindi", "In English", "Full Movie", "Viral"]:
        clean_title = clean_title.replace(noise, "").strip()

    # Extract first strong narrative line from script if available
    script_hook = ""
    if script_text:
        lines = [ln.strip() for ln in script_text.splitlines() if len(ln.strip()) > 15]
        if lines:
            script_hook = lines[0][:100]

    visual_scene = clean_title or script_hook or "Dramatic cinematic thriller climax"

    if is_vertical:
        return (
            f"Cinematic 9:16 vertical portrait aspect ratio, 35mm film still. {visual_scene}. "
            f"Dramatic atmospheric lighting, shallow depth of field, photorealistic textures, "
            f"intense facial expression, centered vertical composition, 8k resolution, no text, no subtitles, no watermarks, no borders."
        )
    else:
        return (
            f"Cinematic 16:9 widescreen shot, 35mm film still. {visual_scene}. "
            f"Dramatic cinematic lighting, shallow depth of field, photorealistic textures, "
            f"intense facial expression, wide panoramic composition, 8k resolution, no text, no subtitles, no watermarks, no borders."
        )


def standardize_thumbnail_dimensions(image_path: Path, is_vertical: bool) -> Path:
    """
    Ensures standard resolution: 1080x1920 for 9:16 vertical or 1920x1080 for 16:9 horizontal.
    """
    try:
        img = Image.open(str(image_path)).convert("RGB")
        target_w, target_h = (1080, 1920) if is_vertical else (1920, 1080)
        target_ratio = target_w / target_h
        cur_w, cur_h = img.size
        cur_ratio = cur_w / cur_h

        # If ratio slightly differs, crop center
        if abs(cur_ratio - target_ratio) > 0.02:
            if cur_ratio > target_ratio:
                new_w = int(cur_h * target_ratio)
                left = (cur_w - new_w) // 2
                img = img.crop((left, 0, left + new_w, cur_h))
            else:
                new_h = int(cur_w / target_ratio)
                top = (cur_h - new_h) // 2
                img = img.crop((0, top, cur_w, top + new_h))

        img = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
        img.save(str(image_path), "JPEG", quality=95)
    except Exception as e:
        logger.warning(f"[ThumbnailGenerator] Dimension standardization error: {e}")
    return image_path


def generate_video_thumbnail(
    video_path: Path,
    script_text: str = "",
    title: str = "",
    output_dir: Optional[Path] = None,
    output_name: Optional[str] = None,
) -> Optional[Path]:
    """
    Main entrypoint:
    1. Detects video duration:
       - < 180 seconds (< 3 minutes) -> 9:16 Vertical format (1080x1920)
       - >= 180 seconds (>= 3 minutes) -> 16:9 Horizontal format (1920x1080)
    2. Generates pure AI image via Google Flow (Nano Banana 2.1).
    3. If Flow fails or times out, falls back to highest-variance video frame extraction.
    4. NO text overlay is rendered onto the thumbnail (pure image plate only).
    """
    video_path = Path(video_path)
    if not video_path.exists():
        logger.warning(f"[ThumbnailGenerator] Video file not found: {video_path}")
        return None

    # Step 1: Detect video duration and dispatch aspect ratio
    duration = get_video_duration(video_path)
    if duration > 0:
        is_vertical = (duration < 180.0)
        format_label = f"Vertical 9:16 (< 3 min, duration={duration:.1f}s)" if is_vertical else f"Horizontal 16:9 (>= 3 min, duration={duration:.1f}s)"
    else:
        # Fallback if duration is undetectable: inspect video frame dimensions
        try:
            cap = cv2.VideoCapture(str(video_path))
            vw = cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1080
            vh = cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1920
            cap.release()
            is_vertical = (vh > vw)
        except Exception:
            is_vertical = True
        format_label = f"Vertical 9:16 (fallback dimension check)" if is_vertical else f"Horizontal 16:9 (fallback dimension check)"

    print(f"[Thumbnail Generator] Auto-detected video format: {format_label}")

    out_dir = output_dir or video_path.parent
    stem = output_name or video_path.stem
    if stem.endswith(".mp4"):
        stem = stem[:-4]

    final_thumb = out_dir / f"{stem}_thumbnail.jpg"
    final_thumb.parent.mkdir(parents=True, exist_ok=True)

    # Step 2: Formulate cinematic prompt tailored to aspect ratio
    flow_prompt = craft_cinematic_prompt(
        title=title or stem,
        script_text=script_text,
        is_vertical=is_vertical,
    )

    # Step 3: Attempt true AI generation via Google Flow Headless Client
    flow_success = False
    try:
        from .flow_client import generate_flow_image
        print(f"[Thumbnail Generator] Querying Google Flow AI plate ({('9:16 Vertical' if is_vertical else '16:9 Horizontal')})...")
        flow_img = generate_flow_image(prompt=flow_prompt, output_path=final_thumb, timeout_seconds=40)
        if flow_img and flow_img.exists() and flow_img.stat().st_size > 15000:
            flow_success = True
            standardize_thumbnail_dimensions(final_thumb, is_vertical=is_vertical)
            print(f"[Thumbnail Generator] Generated Google Flow visual plate: {final_thumb.name} ({'1080x1920' if is_vertical else '1920x1080'})")
    except Exception as e:
        logger.warning(f"[ThumbnailGenerator] Google Flow generation skipped/failed ({e}), falling back to video frame.")

    # Step 4: Fallback to sharp video frame extraction if Google Flow is unavailable
    if not flow_success or not final_thumb.exists():
        print(f"[Thumbnail Generator] Extracting high-entropy video frame fallback ({'9:16' if is_vertical else '16:9'})...")
        if not _extract_best_frame(video_path, final_thumb, is_vertical=is_vertical):
            logger.error("[ThumbnailGenerator] Frame extraction failed.")
            return None
        print(f"[Thumbnail Generator] Fallback frame extracted: {final_thumb.name}")

    return final_thumb
