#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dubbing_studio/movie_crop.py
============================
Fast frame-skipped OCR edge-caption detector and top/bottom cropper for Movie mode.
Detects dynamic captions (and optional top letterbox title bars) within the outer
edge band (default <= 20%) and crops them off cleanly without slow video blurring.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
from rapidocr_onnxruntime import RapidOCR

_NVENC_AVAIL_CACHE: Optional[bool] = None


def ffmpeg_has_nvenc() -> bool:
    """Return True if local FFmpeg exposes working h264_nvenc hardware encoding."""
    global _NVENC_AVAIL_CACHE
    if _NVENC_AVAIL_CACHE is not None:
        return _NVENC_AVAIL_CACHE
    try:
        res = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=5,
        )
        _NVENC_AVAIL_CACHE = "h264_nvenc" in (res.stdout or "")
    except Exception:
        _NVENC_AVAIL_CACHE = False
    return _NVENC_AVAIL_CACHE


def _run_ffmpeg_video_encode(cmd_base: List[str], out_path: Path, cq: int = 18) -> None:
    """Encode using GPU h264_nvenc when available, automatically falling back to CPU libx264."""
    if ffmpeg_has_nvenc():
        nv_cmd = cmd_base + [
            "-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr",
            "-cq", str(cq), "-b:v", "0", "-pix_fmt", "yuv420p",
            str(out_path),
        ]
        res = subprocess.run(nv_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode == 0 and out_path.exists() and out_path.stat().st_size > 10000:
            return
    cpu_cmd = cmd_base + [
        "-c:v", "libx264", "-preset", "fast", "-crf", str(max(17, cq - 1)), "-pix_fmt", "yuv420p",
        str(out_path),
    ]
    subprocess.run(cpu_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _make_even(val: int) -> int:
    return val if val % 2 == 0 else max(2, val - 1)


def detect_caption_edge_fast(
    video_path: Path,
    sample_frames: int = 10,
    ocr_width: int = 640,
    edge_threshold: float = 0.20,
    min_score: float = 0.55,
) -> Dict[str, Any]:
    """
    Fast frame-skipped OCR detector for edge-located subtitles.
    Resizes sampled frames to `ocr_width` for speed and distinguishes changing
    centered captions from static titles or floating corner watermarks.
    Crops top only when needed (dynamic top captions or persistent top-bar text).
    """
    t0 = time.time()
    ocr = RapidOCR()

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    count = max(3, sample_frames)
    ratios = [0.05 + (0.90 * i / (count - 1)) for i in range(count)]

    bottom_hits: List[Tuple[float, float, str]] = []
    top_caption_hits: List[Tuple[float, float, str]] = []
    top_banner_hits: List[Tuple[float, float, str]] = []
    top_dark_end_ratios: List[float] = []

    scale = min(1.0, ocr_width / max(1, orig_w))
    scaled_w = int(round(orig_w * scale))
    scaled_h = int(round(orig_h * scale))

    sampled_count = 0
    for r in ratios:
        frame_idx = min(max(0, total_frames - 1), int(total_frames * r))
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            continue
        sampled_count += 1

        probe = (
            cv2.resize(frame, (scaled_w, scaled_h), interpolation=cv2.INTER_AREA)
            if scale < 1.0
            else frame
        )
        gray_top = cv2.cvtColor(probe[: max(1, int(probe.shape[0] * edge_threshold)), :], cv2.COLOR_BGR2GRAY)
        row_luma = gray_top.mean(axis=1)
        dark_end = 0
        if row_luma.size > 4 and float(row_luma[:3].mean()) < 22.0:
            for y_i in range(len(row_luma)):
                if row_luma[y_i] > 28.0:
                    dark_end = y_i
                    break
        if dark_end > 0:
            top_dark_end_ratios.append(dark_end / probe.shape[0])

        res, _ = ocr(probe)
        if not res:
            continue

        cur_h, cur_w = probe.shape[:2]
        for box, text, score in res:
            if score < min_score or not text.strip():
                continue
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            x1_n, x2_n = min(xs) / cur_w, max(xs) / cur_w
            y1_n, y2_n = min(ys) / cur_h, max(ys) / cur_h
            x_mid = 0.5 * (x1_n + x2_n)
            box_w = x2_n - x1_n

            is_centered_or_wide = 0.22 <= x_mid <= 0.78 or box_w >= 0.25

            if y1_n >= (1.0 - edge_threshold) and is_centered_or_wide:
                bottom_hits.append((y1_n, y2_n, text.strip()))
            elif y2_n <= edge_threshold:
                if is_centered_or_wide:
                    top_caption_hits.append((y1_n, y2_n, text.strip()))
                if y2_n <= min(0.15, edge_threshold):
                    top_banner_hits.append((y1_n, y2_n, text.strip()))

    cap.release()
    elapsed = time.time() - t0

    def _is_dynamic_caption_band(hits: List[Tuple[float, float, str]]) -> bool:
        return len(hits) >= 2 and len({t for _, _, t in hits}) >= 2

    need_bottom = _is_dynamic_caption_band(bottom_hits)
    need_top_dynamic = _is_dynamic_caption_band(top_caption_hits)
    need_top_banner = (
        sampled_count > 0
        and len(top_banner_hits) >= max(2, int(sampled_count * 0.5))
        and len(top_dark_end_ratios) >= max(2, int(sampled_count * 0.5))
    )

    crop_x = 0
    crop_y = 0
    crop_w = _make_even(orig_w)
    crop_bottom = _make_even(orig_h)

    if need_bottom:
        min_y1 = min(y1 for y1, _, _ in bottom_hits)
        safe_bottom_ratio = max(1.0 - edge_threshold - 0.02, min_y1 - 0.012)
        crop_bottom = _make_even(int(orig_h * safe_bottom_ratio))

    if need_top_dynamic:
        max_y2 = max(y2 for _, y2, _ in top_caption_hits)
        safe_top_ratio = min(edge_threshold + 0.02, max_y2 + 0.012)
        crop_y = _make_even(int(orig_h * safe_top_ratio))
    elif need_top_banner:
        max_y2 = max(y2 for _, y2, _ in top_banner_hits)
        sorted_bars = sorted(top_dark_end_ratios)
        median_bar_end = sorted_bars[len(sorted_bars) // 2]
        # Bound bar cutoff near banner text so dark scenes never over-crop video content
        bounded_bar_end = min(median_bar_end, max_y2 + 0.025)
        safe_top_ratio = min(edge_threshold, max(max_y2, bounded_bar_end) + 0.004)
        crop_y = _make_even(int(orig_h * safe_top_ratio))

    crop_h = _make_even(max(2, crop_bottom - crop_y))

    sides = []
    if crop_y > 0:
        sides.append("top")
    if crop_bottom < orig_h:
        sides.append("bottom")
    position = "+".join(sides) if sides else "none"

    return {
        "position": position,
        "orig_w": orig_w,
        "orig_h": orig_h,
        "crop_x": crop_x,
        "crop_y": crop_y,
        "crop_w": crop_w,
        "crop_h": crop_h,
        "bottom_hits": len(bottom_hits),
        "top_hits": len(top_caption_hits) + len(top_banner_hits),
        "distinct_bottom": len({t for _, _, t in bottom_hits}),
        "distinct_top": len({t for _, _, t in (top_caption_hits or top_banner_hits)}),
        "elapsed_sec": elapsed,
        "duration_sec": total_frames / fps,
    }


def _is_vertical_aspect(width: int, height: int) -> bool:
    """Return True when dimensions represent a portrait/vertical frame (height noticeably > width)."""
    if width <= 0 or height <= 0:
        return True
    return (width / float(height)) < 0.90


def _is_square_aspect(width: int, height: int) -> bool:
    """Return True if dimensions match square (1:1) framing within tight tolerance."""
    if width <= 0 or height <= 0:
        return False
    return abs((width / float(height)) - 1.0) <= 0.05


def build_movie_crop_plan(
    info: Dict[str, Any],
    max_width: int = 1080,
    reels_if_non_vertical: bool = True,
    output_ratio: str = "reel",
) -> Dict[str, Any]:
    """
    Compute exact single-pass FFmpeg crop/layout filter parameters without encoding yet.
    Supports square (1080x1080), blurred Reels (1080x1920), simple edge crop/scale, or passthrough.
    """
    crop_w, crop_h = info["crop_w"], info["crop_h"]
    crop_x, crop_y = info["crop_x"], info["crop_y"]

    has_edge_crop = info["position"] != "none"
    aspect = crop_w / max(1.0, float(crop_h))
    is_vertical = _is_vertical_aspect(crop_w, crop_h)
    norm_ratio = "square" if str(output_ratio or "reel").strip().lower() in ("square", "1:1", "1/1", "sq") else "reel"
    crop_prefix = f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}," if has_edge_crop else ""

    if norm_ratio == "square":
        target_sq = _make_even(min(1080, max_width)) if max_width < 1080 else 1080
        vf_sq = (
            f"{crop_prefix}"
            f"scale={target_sq}:{target_sq}:force_original_aspect_ratio=increase:flags=bicubic,"
            f"crop={target_sq}:{target_sq}"
        )
        return {
            "crop_mode": "square",
            "is_filter_complex": False,
            "vf": vf_sq,
            "fc_body": None,
            "target_w": target_sq,
            "target_h": target_sq,
            "crop_w": crop_w,
            "crop_h": crop_h,
            "aspect": aspect,
            "output_ratio": norm_ratio,
        }

    if reels_if_non_vertical and not is_vertical:
        zoom = 1.40 if aspect >= 1.20 else 1.15
        scale_w = _make_even(int(round(1080 * zoom)))
        fg_scaled_h = _make_even(int(round(crop_h * (scale_w / max(1, crop_w)))))
        fg_crop_h = min(1920, fg_scaled_h)
        fg_crop_x = max(0, (scale_w - 1080) // 2)
        fg_crop_y = max(0, (fg_scaled_h - fg_crop_h) // 2)
        return {
            "crop_mode": "reels_blur",
            "is_filter_complex": True,
            "vf": None,
            "crop_prefix": crop_prefix,
            "scale_w": scale_w,
            "fg_scaled_h": fg_scaled_h,
            "fg_crop_h": fg_crop_h,
            "fg_crop_x": fg_crop_x,
            "fg_crop_y": fg_crop_y,
            "zoom": zoom,
            "target_w": 1080,
            "target_h": 1920,
            "crop_w": crop_w,
            "crop_h": crop_h,
            "aspect": aspect,
            "output_ratio": norm_ratio,
        }

    out_w = _make_even(min(max_width, crop_w))
    out_h = _make_even(int(round(crop_h * (out_w / crop_w))))
    vf_parts = []
    if has_edge_crop:
        vf_parts.append(f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}")
    if out_w != crop_w or out_h != crop_h:
        vf_parts.append(f"scale={out_w}:{out_h}")

    return {
        "crop_mode": "simple_vf" if vf_parts else "passthrough",
        "is_filter_complex": False,
        "vf": ",".join(vf_parts) if vf_parts else None,
        "fc_body": None,
        "target_w": out_w,
        "target_h": out_h,
        "crop_w": crop_w,
        "crop_h": crop_h,
        "aspect": aspect,
        "is_vertical": is_vertical,
        "reels_if_non_vertical": reels_if_non_vertical,
        "output_ratio": norm_ratio,
    }


def crop_video_fast(
    input_video: Path,
    cropped_video: Path,
    info: Dict[str, Any],
    max_width: int = 1080,
    reels_if_non_vertical: bool = True,
    output_ratio: str = "reel",
) -> Tuple[Path, int, int]:
    """
    Crop detected edge strip and format output ratio using GPU NVENC (libx264 fallback):
    - output_ratio == "square": full-bleed center-cropped 1080x1080 (no blurred/black bars).
    - output_ratio == "reel" (default): if non-vertical in Movie mode, format to 1080x1920 Reels
      (zoomed center foreground over blurred top/bottom canvas); skips padding if already vertical.
    """
    plan = build_movie_crop_plan(
        info=info,
        max_width=max_width,
        reels_if_non_vertical=reels_if_non_vertical,
        output_ratio=output_ratio,
    )
    mode = plan["crop_mode"]
    out_w, out_h = plan["target_w"], plan["target_h"]

    if mode == "square":
        print(
            f"[Movie Crop Square] Aspect ({plan['crop_w']}x{plan['crop_h']}, ratio={plan['aspect']:.2f}) -> "
            f"full-bleed {out_w}x{out_h} center crop (1:1 square)"
        )
        cropped_video.parent.mkdir(parents=True, exist_ok=True)
        _run_ffmpeg_video_encode(
            ["ffmpeg", "-y", "-i", str(input_video), "-vf", plan["vf"], "-an"],
            cropped_video,
            cq=18,
        )
        return cropped_video, out_w, out_h

    if mode == "reels_blur":
        print(
            f"[Movie Crop Reels] Non-vertical aspect ({plan['crop_w']}x{plan['crop_h']}, ratio={plan['aspect']:.2f}) -> "
            f"formatting to 1080x1920 Reels ({plan['zoom']:.2f}x center zoom -> 1080x{plan['fg_crop_h']} + blurred top/bottom)"
        )
        fc = (
            f"[0:v]{plan['crop_prefix']}split=2[fg][bg];"
            f"[bg]scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,boxblur=30:3[bg_blur];"
            f"[fg]scale={plan['scale_w']}:{plan['fg_scaled_h']}:flags=bicubic,"
            f"crop=1080:{plan['fg_crop_h']}:{plan['fg_crop_x']}:{plan['fg_crop_y']}[fg_zoomed];"
            f"[bg_blur][fg_zoomed]overlay=(W-w)/2:(H-h)/2[vout]"
        )
        cropped_video.parent.mkdir(parents=True, exist_ok=True)
        _run_ffmpeg_video_encode(
            ["ffmpeg", "-y", "-i", str(input_video), "-filter_complex", fc, "-map", "[vout]", "-an"],
            cropped_video,
            cq=18,
        )
        return cropped_video, 1080, 1920

    if plan.get("reels_if_non_vertical") and plan.get("is_vertical"):
        print(
            f"[Movie Crop Reels] Vertical aspect detected ({plan['crop_w']}x{plan['crop_h']}, ratio={plan['aspect']:.2f}) -> "
            f"skipping blurred Reels layout."
        )

    if mode == "passthrough" or not plan.get("vf"):
        return input_video, out_w, out_h

    cropped_video.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg_video_encode(
        ["ffmpeg", "-y", "-i", str(input_video), "-vf", plan["vf"], "-an"],
        cropped_video,
        cq=18,
    )
    return cropped_video, out_w, out_h


def process_movie_crop_video(
    input_video_path: Path,
    output_video_path: Path,
    sample_frames: int = 10,
    edge_threshold: float = 0.20,
    max_width: int = 1080,
    reels_if_non_vertical: bool = True,
    output_ratio: str = "reel",
    defer_encode: bool = False,
) -> Path:
    """
    Detect top/bottom edge captions with fast OCR and crop cleanly.
    When defer_encode=True, writes a sidecar `_spec.json` and skips intermediate encoding
    so `block_aligner` folds the crop/layout directly into its single final NVENC pass.
    """
    info = detect_caption_edge_fast(
        Path(input_video_path),
        sample_frames=sample_frames,
        edge_threshold=edge_threshold,
    )
    print(
        f"[Movie Crop OCR] Position={info['position'].upper()} in {info['elapsed_sec']:.2f}s | "
        f"bottom_hits={info['bottom_hits']} (distinct={info['distinct_bottom']}) | "
        f"top_hits={info['top_hits']} (distinct={info['distinct_top']}) | "
        f"crop={info['crop_w']}x{info['crop_h']}@{info['crop_x']},{info['crop_y']}"
    )
    if defer_encode:
        plan = build_movie_crop_plan(
            info=info,
            max_width=max_width,
            reels_if_non_vertical=reels_if_non_vertical,
            output_ratio=output_ratio,
        )
        plan["source_video"] = str(Path(input_video_path).resolve())
        spec_path = Path(output_video_path).with_name(f"{Path(output_video_path).stem}_spec.json")
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        print(
            f"[Movie Crop Single-Pass] Deferred crop/layout ({plan['crop_mode']} -> "
            f"{plan['target_w']}x{plan['target_h']}) to final NVENC mux ({spec_path.name})."
        )
        return Path(input_video_path)

    t_crop = time.time()
    out_vid, out_w, out_h = crop_video_fast(
        Path(input_video_path),
        Path(output_video_path),
        info,
        max_width=max_width,
        reels_if_non_vertical=reels_if_non_vertical,
        output_ratio=output_ratio,
    )
    if out_vid == Path(input_video_path):
        print(f"[Movie Crop] No edge captions detected; keeping original framing ({out_w}x{out_h}).")
    else:
        print(f"[Movie Crop] Saved {out_w}x{out_h} video in {time.time() - t_crop:.2f}s")
    return out_vid

