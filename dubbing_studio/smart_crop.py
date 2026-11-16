#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dubbing_studio/smart_crop.py
============================
Smart Shorts Crop & Center-Top Hook Translator.

Designed for vertical interior design / 3D explainer Shorts where:
1. Burned-in Chinese captions sit in the bottom ~15% of the frame (y >= 0.85).
   By proportionally cropping off the bottom 15% and symmetrically trimming 7.5%
   off left/right width (maintaining exact 9:16 Shorts aspect ratio) and expanding
   back up, all original bottom subtitles are completely removed without blur boxes,
   and no new bottom captions need to be added.
2. Large center-top hook text appears during the opening 0–3.5 seconds.
   This module automatically detects that top hook text, translates it into
   punchy English via Gemini, cleanly inpaints the Chinese characters, and renders
   matching high-contrast English typography (Montserrat-ExtraBold, Yellow/Cyan,
   thick black stroke).
"""

import os
import json
import subprocess
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .env_loader import configure_runtime_environment
configure_runtime_environment()

from .key_pool import get_active_gemini_keys, mark_gemini_key_dead, is_gemini_dead_error
from google import genai


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FONT_PATH = PROJECT_ROOT / "assets" / "fonts" / "Montserrat-ExtraBold.ttf"


def translate_top_hook_to_english(chinese_lines: List[str]) -> Tuple[str, str]:
    """
    Translates 1 or 2 lines of Chinese hook text into punchy, high-CTR uppercase English
    split cleanly into 2 balanced lines for overlay.
    """
    if not chinese_lines:
        return ("", "")

    combined = " | ".join(chinese_lines)
    keys = get_active_gemini_keys()

    prompt = (
        "Translate this short Chinese 3D interior design video hook text into punchy, viral, "
        "high-CTR English suitable for a big two-line video title at the top of a YouTube Short.\n"
        f"Chinese text: {combined}\n\n"
        "Rules:\n"
        "- Return ONLY valid JSON with keys \"line1\" and \"line2\".\n"
        "- Line 1 should be a short 2-3 word punchy opener (e.g. 'BE BOLD!' or 'WATCH THIS!').\n"
        "- Line 2 should be the core action/measurement (e.g. 'RAISE THE BED 150 CM!').\n"
        "- Keep all text UPPERCASE, ultra-concise (max 4-5 words per line), zero Chinese characters."
    )

    for key in keys:
        try:
            client = genai.Client(api_key=key)
            resp = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=prompt
            )
            raw = resp.text.strip()
            if "```" in raw:
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw.strip())
            l1 = str(data.get("line1", "")).strip().upper()
            l2 = str(data.get("line2", "")).strip().upper()
            if l1 or l2:
                return (l1, l2)
        except Exception as e:
            if is_gemini_dead_error(str(e)):
                mark_gemini_key_dead(key, reason=str(e)[:80])
            continue

    # Safe heuristic fallback if Gemini keys fail
    return ("BE BOLD!", "SMART ROOM DESIGN!")


def _fit_text(draw: ImageDraw.ImageDraw, text: str, max_width: int, start_size: int, stroke_w: int, font_path: Path) -> Tuple[ImageFont.FreeTypeFont, int, int]:
    sz = start_size
    while sz > 32:
        f = ImageFont.truetype(str(font_path), sz)
        bbox = draw.textbbox((0, 0), text, font=f, stroke_width=stroke_w)
        tw = bbox[2] - bbox[0]
        if tw <= max_width:
            return f, tw, bbox[3] - bbox[1]
        sz -= 4
    f = ImageFont.truetype(str(font_path), 32)
    bbox = draw.textbbox((0, 0), text, font=f, stroke_width=stroke_w)
    return f, bbox[2] - bbox[0], bbox[3] - bbox[1]


def detect_top_hook_window(video_path: Path, ocr_engine: Any, scan_limit_sec: float = 5.5) -> Tuple[Optional[List[str]], float, float]:
    """
    Scans the opening seconds of a video to detect center-top title text,
    returning (chinese_lines, start_sec, end_sec).
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None, 0.0, 0.0

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))

    detected_times: List[float] = []
    best_texts: List[str] = []

    step_sec = 0.25
    t = 0.0
    while t <= scan_limit_sec:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ret, frame = cap.read()
        if not ret:
            break
        top_region = frame[:int(h * 0.32), :]
        res, _ = ocr_engine(top_region)
        if res:
            texts = [txt.strip() for _, txt, score in res if score > 0.55 and txt.strip()]
            if texts:
                detected_times.append(t)
                if len(texts) >= len(best_texts):
                    best_texts = texts
        t += step_sec

    cap.release()
    if not detected_times or not best_texts:
        return None, 0.0, 0.0

    start_sec = max(0.0, detected_times[0])
    end_sec = detected_times[-1] + step_sec
    return best_texts, start_sec, end_sec


def apply_smart_crop_and_hook_overlay_to_frame(
    frame_bgr: np.ndarray,
    ocr_engine: Any,
    line1: str,
    line2: str,
    crop_bottom_ratio: float = 0.15,
    replace_top_text: bool = True
) -> np.ndarray:
    """
    Crops bottom captions (keeping 9:16 ratio), expands back to original size,
    and optionally replaces center-top Chinese hook text with translated English.
    """
    H, W = frame_bgr.shape[:2]
    keep_ratio = 1.0 - crop_bottom_ratio
    H_crop = int(H * keep_ratio)
    W_crop = int(H_crop * (W / H))
    x_start = max(0, (W - W_crop) // 2)
    y_start = 0

    cropped = frame_bgr[y_start:y_start + H_crop, x_start:x_start + W_crop]
    resized = cv2.resize(cropped, (W, H), interpolation=cv2.INTER_LANCZOS4)

    if not replace_top_text or (not line1 and not line2):
        return resized

    # Detect Chinese text in top 35% of the cropped/resized frame
    top_crop = resized[:int(H * 0.35), :]
    res, _ = ocr_engine(top_crop)

    if res:
        mask = np.zeros((H, W), dtype=np.uint8)
        for box, text, score in res:
            pts = np.array(box, dtype=np.int32)
            xmin = max(0, int(np.min(pts[:, 0])) - 15)
            xmax = min(W, int(np.max(pts[:, 0])) + 15)
            ymin = max(0, int(np.min(pts[:, 1])) - 15)
            ymax = min(H, int(np.max(pts[:, 1])) + 15)

            roi = resized[ymin:ymax, xmin:xmax]
            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            v = hsv[:, :, 2]
            s = hsv[:, :, 1]
            text_pixels = ((v < 60) | ((s > 90) & (v > 100))).astype(np.uint8) * 255
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
            dilated = cv2.dilate(text_pixels, kernel, iterations=1)
            mask[ymin:ymax, xmin:xmax] = np.maximum(mask[ymin:ymax, xmin:xmax], dilated)

        resized = cv2.inpaint(resized, mask, inpaintRadius=7, flags=cv2.INPAINT_NS)

    # Render English Typography Overlay
    font_p = FONT_PATH if FONT_PATH.exists() else Path("C:/Windows/Fonts/impact.ttf")
    pil_img = Image.fromarray(cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)).convert("RGBA")
    draw = ImageDraw.Draw(pil_img)

    stroke = max(4, int(H * 0.0042))
    max_w = int(W * 0.86)

    y_cursor = int(H * 0.095)
    if line1:
        f1, w1, h1 = _fit_text(draw, line1, max_w, int(H * 0.044), stroke, font_p)
        x1 = (W - w1) // 2
        draw.text((x1, y_cursor), line1, font=f1, fill=(255, 230, 0, 255), stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
        y_cursor += h1 + int(H * 0.018)

    if line2:
        f2, w2, h2 = _fit_text(draw, line2, max_w, int(H * 0.044), stroke, font_p)
        x2 = (W - w2) // 2
        draw.text((x2, y_cursor), line2, font=f2, fill=(0, 235, 255, 255), stroke_width=stroke, stroke_fill=(0, 0, 0, 255))

    out_rgb = np.array(pil_img.convert("RGB"))
    return cv2.cvtColor(out_rgb, cv2.COLOR_RGB2BGR)


def process_smart_crop_video(
    input_video_path: Path,
    output_video_path: Path,
    crop_bottom_ratio: float = 0.15
) -> Path:
    """
    Full video processor for --smart-crop:
      - Detects top-center Chinese hook window in opening seconds
      - Translates hook to English via Gemini
      - Crops bottom 15% (preserving 9:16 portrait ratio) & expands back to native resolution
      - Replaces opening Chinese hook text with styled English text
    """
    from rapidocr_onnxruntime import RapidOCR
    ocr = RapidOCR()

    chinese_lines, start_sec, end_sec = detect_top_hook_window(input_video_path, ocr)
    if chinese_lines:
        print(f"[Smart Crop] Detected top-center hook text ({start_sec:.2f}s - {end_sec:.2f}s): {chinese_lines}")
        line1, line2 = translate_top_hook_to_english(chinese_lines)
        print(f"[Smart Crop] Translated English Hook: '{line1}' / '{line2}'")
    else:
        print("[Smart Crop] No top-center opening hook detected. Applying clean 9:16 bottom crop...")
        line1, line2 = "", ""

    cap = cv2.VideoCapture(str(input_video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    temp_raw = output_video_path.with_name(f"{output_video_path.stem}_smartcrop_temp.mp4")
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(temp_raw), fourcc, fps, (W, H))

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        cur_sec = frame_idx / fps
        in_hook_window = bool(chinese_lines and (start_sec - 0.1 <= cur_sec <= end_sec + 0.1))

        processed = apply_smart_crop_and_hook_overlay_to_frame(
            frame_bgr=frame,
            ocr_engine=ocr,
            line1=line1,
            line2=line2,
            crop_bottom_ratio=crop_bottom_ratio,
            replace_top_text=in_hook_window
        )
        writer.write(processed)
        frame_idx += 1

    cap.release()
    writer.release()

    # Re-encode with H.264/AAC copying original audio stream cleanly
    cmd = [
        "ffmpeg", "-y",
        "-i", str(temp_raw),
        "-i", str(input_video_path),
        "-map", "0:v:0",
        "-map", "1:a:0?",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "copy",
        str(output_video_path)
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if temp_raw.exists():
        temp_raw.unlink()

    return output_video_path

