#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
blur_subtitles_rapidocr.py
==========================
Anti-Glitch Subtitle Cleaner with Generous Margin & Luminance Suppression.

Solves:
1. "Split-Second Subtitle Visibility":
   - Subtitle graphics in video editors often appear 0.2s before speech or stay after.
   - We enforce a minimum safety width of 760px (expanding up to 960px+ for long text)
     and a generous horizontal padding of pad_x=75px.
   - Any phrase—no matter how short or long, and regardless of audio/visual timing jitter—
     is 100% covered with zero split-second flashes.

2. "Missing Edges":
   - pad_x=75px, pad_y=16px with a 100% solid core covers all drop shadows, thick black
     outlines, and outer punctuation marks.

3. "White Fog / Silhouettes":
   - Luminance-Suppression pulls bright white text strokes down to the ambient background
     luminance prior to blurring, eliminating foggy vertical bars.

4. "High Speed":
   - FFmpeg NVDEC (-hwaccel cuda) input decoding and NVENC HEVC encoding.
"""

import os
import sys
import re
import json
import time
import argparse
import subprocess
from pathlib import Path

# Add project root to sys.path
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import cv2
import numpy as np
from tqdm import tqdm
from rapidocr_onnxruntime import RapidOCR


def parse_srt_time(ts_str: str) -> float:
    """Converts '00:01:23,456' to total seconds."""
    ts_str = ts_str.strip().replace(",", ".")
    parts = ts_str.split(":")
    hrs = float(parts[0])
    mins = float(parts[1])
    secs = float(parts[2])
    return hrs * 3600 + mins * 60 + secs


def load_and_split_srt_blocks(srt_path: str):
    """
    Parses standard SRT file, then splits multi-clause lines by punctuation
    so that every visual subtitle phrase on screen gets its own midpoint sample.
    """
    path = Path(srt_path)
    if not path.exists():
        return []

    content = path.read_text(encoding="utf-8", errors="replace")
    raw_blocks = re.split(r"\n\s*\n", content.strip())
    raw_entries = []

    for block in raw_blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) >= 2:
            time_line = lines[1] if lines[0].isdigit() else lines[0]
            if "-->" in time_line:
                parts = time_line.split("-->")
                start_sec = parse_srt_time(parts[0])
                end_sec = parse_srt_time(parts[1])
                text = " ".join(lines[2:]) if lines[0].isdigit() else " ".join(lines[1:])
                raw_entries.append({
                    "start": start_sec,
                    "end": end_sec,
                    "text": text
                })

    # Break multi-clause sentences into visual sub-phrases
    visual_blocks = []
    for entry in raw_entries:
        clauses = [c.strip() for c in re.split(r"[,，。！？!?;；]+", entry["text"]) if c.strip()]
        if len(clauses) <= 1:
            dur = entry["end"] - entry["start"]
            visual_blocks.append({
                "start": entry["start"],
                "end": entry["end"],
                "mid": entry["start"] + dur / 2.0,
                "text": entry["text"]
            })
        else:
            total_chars = max(1, sum(len(c) for c in clauses))
            cur_t = entry["start"]
            dur = entry["end"] - entry["start"]
            for c in clauses:
                c_dur = dur * (len(c) / float(total_chars))
                visual_blocks.append({
                    "start": cur_t,
                    "end": cur_t + c_dur,
                    "mid": cur_t + c_dur / 2.0,
                    "text": c
                })
                cur_t += c_dur

    return visual_blocks


def _extract_line_boxes(result, crop_y_start, scale_x, scale_y, min_score=0.45):
    """
    Extracts verified per-line subtitle boxes from a RapidOCR (det+rec) result,
    keeping only lines belonging to the dominant lower subtitle cluster.
    Returns list of (lx1, ly1, lx2, ly2) tuples sorted top-to-bottom.
    """
    if not result:
        return []

    line_boxes = []
    for item in result:
        pts, txt, score = item[0], item[1], float(item[2])
        if score < min_score or not str(txt).strip():
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        lx1 = int(min(xs) * scale_x)
        lx2 = int(max(xs) * scale_x)
        ly1 = int((min(ys) + crop_y_start) * scale_y)
        ly2 = int((max(ys) + crop_y_start) * scale_y)
        lh = ly2 - ly1
        lw = lx2 - lx1
        if lw >= 24 and 16 <= lh <= 140:
            line_boxes.append((lx1, ly1, lx2, ly2, (ly1 + ly2) / 2.0, str(txt).strip()))

    if not line_boxes:
        return []

    # Keep lines belonging to the main lower subtitle cluster (supports 2-line stacked subtitles)
    if len(line_boxes) > 1:
        anchor_y = max(b[4] for b in line_boxes)
        clustered = [b for b in line_boxes if abs(b[4] - anchor_y) <= 135]
        if clustered:
            line_boxes = clustered

    line_boxes.sort(key=lambda b: b[1])
    return [(b[0], b[1], b[2], b[3]) for b in line_boxes]


def detect_subtitle_box_at_timestamp(cap, target_sec, ocr_engine, target_w=1080, target_h=1920):
    """
    Seeks to target_sec, runs RapidOCR (detection + recognition) on the lower screen,
    and returns (xmin, ymin, xmax, ymax) for verified subtitle text.
    """
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    frame_idx = int(target_sec * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ret, frame = cap.read()
    if not ret or frame is None:
        return None

    # Scan 60% to 94% vertically so low-set or 2-line Douyin subtitles are never clipped
    crop_y_start = int(orig_h * 0.60)
    crop_y_end = int(orig_h * 0.94)
    roi = frame[crop_y_start:crop_y_end, :]

    result, _ = ocr_engine(roi, use_det=True, use_rec=True, use_cls=False)
    lines = _extract_line_boxes(result, crop_y_start, target_w / float(orig_w), target_h / float(orig_h))
    if not lines:
        return None

    bx1 = min(b[0] for b in lines)
    by1 = min(b[1] for b in lines)
    bx2 = max(b[2] for b in lines)
    by2 = max(b[3] for b in lines)

    w_box = bx2 - bx1
    h_box = by2 - by1

    if w_box >= 30 and 16 <= h_box <= 240:
        return (bx1, by1, bx2, by2)
    return None


def _compute_stroke_mask(bgr_roi):
    """Fast binary mask highlighting bright white and saturated colored subtitle strokes."""
    gray = cv2.cvtColor(bgr_roi, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(bgr_roi, cv2.COLOR_BGR2HSV)
    return ((gray > 200) | ((hsv[:, :, 1] > 110) & (hsv[:, :, 2] > 120))).astype(np.uint8)


def scan_subtitle_timeline(
    in_path: Path,
    ocr_engine,
    target_w: int,
    target_h: int,
    duration: float,
    sample_fps: float = 4.0,
    max_heartbeat_active: float = 0.75,
    max_heartbeat_empty: float = 0.50,
):
    """
    Streams the lower subtitle strip sequentially at `sample_fps` via FFmpeg and runs
    RapidOCR only on change-triggered / heartbeat frames to build an accurate per-subtitle
    bounding-box timeline at 0.25s granularity without scanning static frames redundantly.
    Returns (timeline_samples, ocr_calls, total_samples).
    """
    crop_y_start = int(target_h * 0.60)
    crop_y_end = int(target_h * 0.94)
    crop_h = crop_y_end - crop_y_start

    in_cmd = [
        "ffmpeg", "-v", "error", "-hwaccel", "cuda",
        "-i", str(in_path),
    ]
    if duration > 0:
        in_cmd.extend(["-t", f"{duration:.3f}"])
    in_cmd.extend([
        "-vf", f"fps={sample_fps},scale={target_w}:{target_h},crop={target_w}:{crop_h}:0:{crop_y_start}",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-"
    ])

    pipe = subprocess.Popen(in_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    frame_bytes = target_w * crop_h * 3

    samples = []
    idx = 0
    ocr_calls = 0
    last_ocr_t = -999.0
    active_lines = []
    ref_band_mask = None
    ref_outside_sum = 0

    try:
        while True:
            raw = pipe.stdout.read(frame_bytes)
            if len(raw) < frame_bytes:
                break
            roi = np.frombuffer(raw, dtype=np.uint8).reshape((crop_h, target_w, 3))
            t = idx / float(sample_fps)

            cur_mask = _compute_stroke_mask(roi)
            trigger_ocr = False

            if idx == 0:
                trigger_ocr = True
            elif active_lines:
                if (t - last_ocr_t) >= max_heartbeat_active:
                    trigger_ocr = True
                elif ref_band_mask is not None:
                    # Compare stroke IoU inside active subtitle boxes (downscaled 2x in memory slice)
                    box_union_x1 = max(0, min(b[0] for b in active_lines) - 12)
                    box_union_x2 = min(target_w, max(b[2] for b in active_lines) + 12)
                    box_union_y1 = max(0, min(b[1] for b in active_lines) - crop_y_start - 10)
                    box_union_y2 = min(crop_h, max(b[3] for b in active_lines) - crop_y_start + 10)

                    m_cur = cur_mask[box_union_y1:box_union_y2, box_union_x1:box_union_x2]
                    m_ref = ref_band_mask[box_union_y1:box_union_y2, box_union_x1:box_union_x2]
                    inter = int(np.count_nonzero(m_cur & m_ref))
                    union = int(np.count_nonzero(m_cur | m_ref))
                    iou = (inter / float(union)) if union > 0 else 1.0
                    cur_sum = int(np.count_nonzero(m_cur))
                    ref_sum = int(np.count_nonzero(m_ref))

                    # Check if a wider or extra stacked line suddenly appeared horizontally adjacent
                    band_y1 = max(0, box_union_y1 - 75)
                    band_y2 = min(crop_h, box_union_y2 + 75)
                    band_cur_sum = int(np.count_nonzero(cur_mask[band_y1:band_y2, :]))
                    outside_cur = max(0, band_cur_sum - cur_sum)
                    outside_delta = abs(outside_cur - ref_outside_sum)

                    if iou < 0.62 or cur_sum < ref_sum * 0.45 or outside_delta > max(400, int(0.30 * max(1, ref_sum))):
                        trigger_ocr = True
            else:
                if (t - last_ocr_t) >= max_heartbeat_empty:
                    trigger_ocr = True
                elif ref_band_mask is not None:
                    diff_cnt = int(np.count_nonzero(cur_mask ^ ref_band_mask))
                    if diff_cnt > 1200:
                        trigger_ocr = True

            if trigger_ocr:
                result, _ = ocr_engine(roi, use_det=True, use_rec=True, use_cls=False)
                ocr_calls += 1
                last_ocr_t = t
                active_lines = _extract_line_boxes(result, crop_y_start, 1.0, 1.0)
                ref_band_mask = cur_mask.copy()
                if active_lines:
                    ux1 = max(0, min(b[0] for b in active_lines) - 12)
                    ux2 = min(target_w, max(b[2] for b in active_lines) + 12)
                    uy1 = max(0, min(b[1] for b in active_lines) - crop_y_start - 10)
                    uy2 = min(crop_h, max(b[3] for b in active_lines) - crop_y_start + 10)
                    by1 = max(0, uy1 - 75)
                    by2 = min(crop_h, uy2 + 75)
                    in_s = int(np.count_nonzero(ref_band_mask[uy1:uy2, ux1:ux2]))
                    ref_outside_sum = max(0, int(np.count_nonzero(ref_band_mask[by1:by2, :])) - in_s)
                else:
                    ref_outside_sum = 0

            samples.append({"t": t, "lines": list(active_lines)})
            idx += 1
    finally:
        try:
            pipe.stdout.close()
        except Exception:
            pass
        pipe.wait()

    return samples, ocr_calls, idx


def build_subtitle_segments(samples, sample_fps=4.0, lead_sec=0.20, trail_sec=0.20):
    """
    Filters vertical outlier detections against median subtitle band, bridges single
    missed samples inside stable captions, merges matching consecutive frames into
    per-subtitle segments, and returns (segments, median_yc, global_raw_box).
    Each segment: {'start': float, 'end': float, 'lines': [(x1, y1, x2, y2), ...]}
    """
    dt = 1.0 / float(sample_fps)

    # 1. Compute dominant subtitle Y-center across all non-empty detections
    all_ycs = []
    for s in samples:
        if s["lines"]:
            y1 = min(b[1] for b in s["lines"])
            y2 = max(b[3] for b in s["lines"])
            all_ycs.append((y1 + y2) / 2.0)

    if not all_ycs:
        return [], None, None

    median_yc = float(np.median(all_ycs))
    cleaned = []
    rejected_cnt = 0
    for s in samples:
        valid_lines = [b for b in s["lines"] if abs(((b[1] + b[3]) / 2.0) - median_yc) <= 120.0]
        if s["lines"] and not valid_lines:
            rejected_cnt += 1
        cleaned.append({"t": s["t"], "lines": valid_lines})

    if rejected_cnt:
        print(f"[Subtitle Band Filter] Median Y={median_yc:.0f}px -> Rejected {rejected_cnt} off-band sample(s)")

    # 2. Bridge 1-step empty hiccup when both adjacent frames have matching line counts & close boxes
    def _boxes_match(la, lb, tol=30):
        if len(la) != len(lb) or not la:
            return False
        for a, b in zip(la, lb):
            if max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]), abs(a[3] - b[3])) > tol:
                return False
        return True

    for i in range(1, len(cleaned) - 1):
        if not cleaned[i]["lines"] and cleaned[i - 1]["lines"] and _boxes_match(cleaned[i - 1]["lines"], cleaned[i + 1]["lines"], tol=36):
            cleaned[i]["lines"] = [
                (
                    min(a[0], b[0]),
                    min(a[1], b[1]),
                    max(a[2], b[2]),
                    max(a[3], b[3]),
                )
                for a, b in zip(cleaned[i - 1]["lines"], cleaned[i + 1]["lines"])
            ]

    # 3. Group consecutive samples with matching line structure into tight per-subtitle segments
    segments = []
    cur = None
    for s in cleaned:
        lines = s["lines"]
        t = s["t"]
        if not lines:
            if cur is not None:
                segments.append(cur)
                cur = None
            continue

        if cur is None:
            cur = {"raw_start": t, "raw_end": t + dt, "lines": list(lines)}
        elif _boxes_match(cur["lines"], lines, tol=28):
            cur["raw_end"] = t + dt
            cur["lines"] = [
                (
                    min(a[0], b[0]),
                    min(a[1], b[1]),
                    max(a[2], b[2]),
                    max(a[3], b[3]),
                )
                for a, b in zip(cur["lines"], lines)
            ]
        else:
            segments.append(cur)
            cur = {"raw_start": t, "raw_end": t + dt, "lines": list(lines)}

    if cur is not None:
        segments.append(cur)

    # Apply entry/exit guard windows to eliminate split-second caption flashes
    final_segments = []
    for seg in segments:
        final_segments.append({
            "start": max(0.0, seg["raw_start"] - lead_sec),
            "end": seg["raw_end"] + trail_sec,
            "raw_start": seg["raw_start"],
            "raw_end": seg["raw_end"],
            "lines": seg["lines"],
        })

    # Compute overall raw bounding box solely for MarginV metadata compatibility
    all_lines = [b for seg in final_segments for b in seg["lines"]]
    global_raw_box = (
        min(b[0] for b in all_lines),
        min(b[1] for b in all_lines),
        max(b[2] for b in all_lines),
        max(b[3] for b in all_lines),
    )
    return final_segments, int(round(median_yc)), global_raw_box


def prepare_blur_data(boxes, target_w=1080, target_h=1920, pad_x=28, pad_y=12, min_width=0, ksize=39, sigma=19):
    """
    Precomputes tight coordinates and a silky, boundary-zeroed alpha mask with
    per-line rounded capsules (preserving L/T silhouettes on multi-line text)
    and minimal horizontal/vertical margins strictly around the detected glyphs.
    `boxes` may be a single (x1, y1, x2, y2) tuple or a sequence of line boxes.
    """
    if not boxes:
        return None
    if isinstance(boxes[0], (int, float, np.integer, np.floating)):
        line_list = [tuple(int(v) for v in boxes)]
    else:
        line_list = [tuple(int(v) for v in b) for b in boxes if b]
    if not line_list:
        return None

    bx1 = min(b[0] for b in line_list)
    by1 = min(b[1] for b in line_list)
    bx2 = max(b[2] for b in line_list)
    by2 = max(b[3] for b in line_list)

    fade_dist = 14.0
    core_pad_x = max(8, min(14, pad_x // 2))
    core_pad_y = max(3, min(6, pad_y // 3))
    roi_pad_x = max(pad_x, int(np.ceil(core_pad_x + fade_dist + 4)))
    roi_pad_y = max(pad_y, int(np.ceil(core_pad_y + fade_dist + 2)))

    cx = (bx1 + bx2) // 2
    half_w = max((bx2 - bx1) // 2 + roi_pad_x, (min_width // 2) if min_width > 0 else 0)
    x1 = max(0, cx - half_w)
    x2 = min(target_w, cx + half_w)
    y1 = max(0, by1 - roi_pad_y)
    y2 = min(target_h, by2 + roi_pad_y)

    roi_w = x2 - x1
    roi_h = y2 - y1
    if roi_w <= 4 or roi_h <= 4:
        return None

    # Draw tight rounded pill core for EACH detected text line individually
    inner_mask = np.zeros((roi_h, roi_w), dtype=np.uint8)
    core_rects = []
    for (lx1, ly1, lx2, ly2) in line_list:
        if min_width > 0 and (lx2 - lx1) + 2 * core_pad_x < min_width - int(2 * fade_dist):
            lcx = (lx1 + lx2) // 2
            lhalf = max((lx2 - lx1) // 2 + core_pad_x, (min_width // 2) - int(fade_dist))
            rx1 = max(2, (lcx - lhalf) - x1)
            rx2 = min(roi_w - 3, (lcx + lhalf) - x1)
        else:
            rx1 = max(2, (lx1 - core_pad_x) - x1)
            rx2 = min(roi_w - 3, (lx2 + core_pad_x) - x1)
        ry1 = max(2, (ly1 - core_pad_y) - y1)
        ry2 = min(roi_h - 3, (ly2 + core_pad_y) - y1)
        if rx2 <= rx1 or ry2 <= ry1:
            continue

        core_h = max(12, ry2 - ry1)
        radius = min(core_h // 2, max(6, (rx2 - rx1) // 2), 20)
        cy_core = (ry1 + ry2) // 2
        left_c = rx1 + radius
        right_c = max(left_c, rx2 - radius)

        cv2.rectangle(inner_mask, (left_c, ry1), (right_c, ry2), 255, -1)
        cv2.circle(inner_mask, (left_c, cy_core), radius, 255, -1)
        cv2.circle(inner_mask, (right_c, cy_core), radius, 255, -1)
        core_rects.append((rx1, ry1, rx2, ry2))

    if not core_rects:
        return None

    # Euclidean distance from outside pixels to the tight per-line capsule core
    dist_out = cv2.distanceTransform(255 - inner_mask, cv2.DIST_L2, 5)

    # Smooth Hermite fade out to borders
    alpha = 1.0 - np.clip(dist_out / fade_dist, 0.0, 1.0)
    alpha = alpha * alpha * (3.0 - 2.0 * alpha)
    alpha = cv2.GaussianBlur(alpha, (15, 5), 3.0)

    # Ensure boundary alpha is mathematically 0.0 at outer ROI edges
    alpha[:2, :] = 0.0
    alpha[-2:, :] = 0.0
    alpha[:, :2] = 0.0
    alpha[:, -2:] = 0.0

    alpha = np.clip(alpha, 0.0, 1.0)[:, :, None]
    inv_alpha = 1.0 - alpha

    return {
        "coords": (x1, y1, x2, y2),
        "core_y": (min(r[1] for r in core_rects), max(r[3] for r in core_rects)),
        "core_rects": core_rects,
        "alpha": alpha,
        "inv_alpha": inv_alpha,
        "ksize": ksize if ksize % 2 == 1 else ksize + 1,
        "sigma": sigma,
    }


def apply_luminance_suppressed_blur(frame, blur_data):
    """
    Suppresses bright white and saturated colored subtitle strokes (plus dark borders)
    toward the local ambient background via fast downscaled Telea estimation, then
    applies Gaussian blur strictly inside the tight per-line capsule mask.
    """
    if blur_data is None:
        return frame

    x1, y1, x2, y2 = blur_data["coords"]
    roi = frame[y1:y2, x1:x2].copy()
    roi_h, roi_w = roi.shape[:2]

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    bg_luminance = float(np.percentile(gray[::2, ::2], 45))

    bright_text_mask = gray > max(155, int(bg_luminance + 30))
    color_text_mask = (hsv[:, :, 1] > 100) & (hsv[:, :, 2] > 110)
    text_mask = bright_text_mask | color_text_mask

    # Include heavy black outlines strictly inside the detected line rectangles
    if np.any(text_mask):
        band_mask = np.zeros_like(text_mask)
        core_rects = blur_data.get("core_rects")
        if core_rects:
            for (rx1, ry1, rx2, ry2) in core_rects:
                band_mask[max(0, ry1):min(roi_h, ry2), max(0, rx1):min(roi_w, rx2)] = True
        else:
            rby1, rby2 = blur_data.get("core_y", (0, roi_h))
            band_mask[max(0, rby1):min(roi_h, rby2), :] = True

        dark_outline_mask = (gray < min(45, max(15, int(bg_luminance - 45)))) & band_mask
        combined_mask = (text_mask & band_mask) | dark_outline_mask
        if not np.any(combined_mask):
            combined_mask = text_mask

        k_dil = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        mask_u8 = cv2.dilate(combined_mask.astype(np.uint8) * 255, k_dil)

        small_w = max(16, roi_w // 4)
        small_h = max(8, roi_h // 4)
        small_roi = cv2.resize(roi, (small_w, small_h), interpolation=cv2.INTER_AREA)
        small_mask = cv2.resize(mask_u8, (small_w, small_h), interpolation=cv2.INTER_NEAREST)
        inpainted_small = cv2.inpaint(small_roi, small_mask, 5, cv2.INPAINT_TELEA)
        local_bg = cv2.resize(inpainted_small, (roi_w, roi_h), interpolation=cv2.INTER_LINEAR)

        roi_suppressed = roi.copy()
        m_bool = mask_u8 > 0
        roi_suppressed[m_bool] = (
            roi_suppressed[m_bool].astype(np.float32) * 0.20 +
            local_bg[m_bool].astype(np.float32) * 0.80
        ).astype(np.uint8)
    else:
        roi_suppressed = roi

    k = blur_data["ksize"]
    s = blur_data["sigma"]
    blurred_roi = cv2.GaussianBlur(roi_suppressed, (k, k), s).astype(np.float32)

    roi_float = roi.astype(np.float32)
    blended = (blurred_roi * blur_data["alpha"] + roi_float * blur_data["inv_alpha"]).astype(np.uint8)
    frame[y1:y2, x1:x2] = blended
    return frame


def process_video_srt_rapidocr(input_video: str, output_video: str, srt_file: str = None, max_duration: float = None):
    in_path = Path(input_video).resolve()
    out_path = Path(output_video).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(in_path))
    if not cap.isOpened():
        raise FileNotFoundError(f"Cannot open video: {in_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    if max_duration:
        total_frames = min(total_frames, int(max_duration * fps))
    duration_sec = total_frames / float(fps)

    # Pre-scale if >1080p
    scale_factor = 1.0
    target_w, target_h = w, h
    if w > 1080 or h > 1920:
        scale_factor = 1080.0 / w
        target_w = 1080
        target_h = int(h * scale_factor)

    print("=" * 65)
    print(" [RapidOCR Subtitle Cleaner] Tight Per-Subtitle Luminance Blur")
    print(f" Input Video   : {in_path.name}")
    print(f" Duration      : {duration_sec:.2f}s ({total_frames} frames @ {fps:.1f} FPS)")
    print(f" Resolution    : {target_w}x{target_h}")
    print(" Strategy      : Change-triggered 4fps RapidOCR + tight per-line capsules")
    print(" Tight Margins : pad_x=28px, pad_y=12px, min_width=0 (ksize=39, sigma=19)")
    print(f" Output Video  : {out_path.name}")
    print("=" * 65)

    # 1. Adaptive Dense RapidOCR Timeline Scan
    print("\n[Step 1/2] Scanning subtitle timeline with change-triggered RapidOCR (4.0 fps)...")
    t0_ocr = time.time()
    ocr_engine = RapidOCR(det_limit_side_len=480)

    sample_fps = 4.0
    samples, ocr_calls, total_samples = scan_subtitle_timeline(
        in_path=in_path,
        ocr_engine=ocr_engine,
        target_w=target_w,
        target_h=target_h,
        duration=duration_sec,
        sample_fps=sample_fps,
        max_heartbeat_active=0.75,
        max_heartbeat_empty=0.50,
    )
    dt_ocr = time.time() - t0_ocr
    print(f"[Step 1/2] Timeline OCR complete in {dt_ocr:.2f}s ({ocr_calls} OCR passes over {total_samples} sampled frames)!")

    segments, median_yc, global_raw_box = build_subtitle_segments(
        samples, sample_fps=sample_fps, lead_sec=0.20, trail_sec=0.20
    )

    if segments and global_raw_box is not None:
        min_x, min_y, max_x, max_y = global_raw_box
        y_center = median_yc
        print(f"\n[Per-Subtitle Segments] Built {len(segments)} tight intervals:")
        for idx_s, seg in enumerate(segments[:25], 1):
            dims = ", ".join(f"{b[2]-b[0]}x{b[3]-b[1]}@[{b[0]}..{b[2]},{b[1]}..{b[3]}]" for b in seg["lines"])
            print(f"  Seg {idx_s:2d}: [{seg['start']:5.2f}s -> {seg['end']:5.2f}s] | {dims}")
        if len(segments) > 25:
            print(f"  ... ({len(segments) - 25} more segments)")
    else:
        min_x, max_x = 180, target_w - 180
        min_y, max_y = int(target_h * 0.74), int(target_h * 0.81)
        y_center = (min_y + max_y) // 2
        print("\n[Per-Subtitle Segments] No subtitle text detected; clean pass will copy video without blur.")

    # Dynamic MarginV based on median subtitle Y-center so ASS captions remain vertically steady
    margin_v = max(80, target_h - y_center - 65)

    print(f"\n[Subtitle Placement Metadata]")
    print(f"  Median Center Y: {y_center}px -> Dynamic ASS MarginV: {margin_v}")
    print(f"  Blur Mode      : Strict per-subtitle tight mask (off during empty frames).\n")

    # Save box metadata JSON so pipeline dubbing & subtitle placement use exact dynamic MarginV
    box_meta_path = out_path.with_name(f"{out_path.stem}_box.json")
    box_meta = {
        "raw_text_box": [int(min_x), int(min_y), int(max_x), int(max_y)],
        "y_center": int(y_center),
        "margin_v": int(margin_v),
        "mode": "per_subtitle_tight",
        "num_segments": len(segments),
    }
    box_meta_path.write_text(json.dumps(box_meta, indent=2), encoding="utf-8")
    print(f"  Saved subtitle box metadata: {box_meta_path.name} (MarginV: {margin_v})\n")

    # Precompute blur masks lazily/per-state so rendering has zero distanceTransform overhead
    blur_cache = {}
    frame_blur_plan = [None] * total_frames
    if segments:
        # Collect active lines per frame via segment start/end indices
        frame_lines = [[] for _ in range(total_frames)]
        for seg in segments:
            sf_idx = max(0, int(np.floor(seg["start"] * fps)))
            ef_idx = min(total_frames, int(np.ceil(seg["end"] * fps)))
            for f_i in range(sf_idx, ef_idx):
                frame_lines[f_i].extend(seg["lines"])

        for f_i in range(total_frames):
            lines_here = frame_lines[f_i]
            if not lines_here:
                continue
            # Deduplicate identical boxes when guard windows overlap
            unique_key = tuple(sorted(set(lines_here)))
            if unique_key not in blur_cache:
                blur_cache[unique_key] = prepare_blur_data(
                    list(unique_key), target_w, target_h,
                    pad_x=28, pad_y=12, min_width=0, ksize=39, sigma=19
                )
            frame_blur_plan[f_i] = blur_cache[unique_key]

    # 2. Stream and Render with GPU Acceleration
    print(f"[Step 2/2] Streaming video and applying tight per-subtitle luminance blur ({len(blur_cache)} cached states)...")

    in_cmd = [
        "ffmpeg", "-hwaccel", "cuda",
        "-i", str(in_path),
        "-vf", f"scale={target_w}:{target_h}",
        "-f", "rawvideo", "-pix_fmt", "bgr24",
        "-"
    ]
    if max_duration:
        in_cmd.insert(1, "-t")
        in_cmd.insert(2, str(max_duration))

    out_cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-s", f"{target_w}x{target_h}",
        "-pix_fmt", "bgr24",
        "-r", str(fps),
        "-i", "-",
        "-c:v", "hevc_nvenc",
        "-preset", "p4",
        "-b:v", "3600k",
        "-maxrate", "5000k",
        "-bufsize", "8000k",
        "-tag:v", "hvc1",
        str(out_path)
    ]

    in_pipe = subprocess.Popen(in_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    out_pipe = subprocess.Popen(out_cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    t_render = time.time()
    frame_bytes = target_w * target_h * 3
    frames_processed = 0
    blurred_frames = 0

    with tqdm(total=total_frames, desc="Rendering Clean Video", unit="frame") as pbar:
        while frames_processed < total_frames:
            raw = in_pipe.stdout.read(frame_bytes)
            if len(raw) < frame_bytes:
                break

            frame = np.frombuffer(raw, dtype=np.uint8).copy().reshape((target_h, target_w, 3))
            blur_data = frame_blur_plan[frames_processed]
            if blur_data is not None:
                frame = apply_luminance_suppressed_blur(frame, blur_data)
                blurred_frames += 1

            out_pipe.stdin.write(frame.tobytes())
            frames_processed += 1
            pbar.update(1)

    in_pipe.stdout.close()
    in_pipe.wait()
    out_pipe.stdin.close()
    out_pipe.wait()

    render_time = time.time() - t_render
    total_time = dt_ocr + render_time
    fps_actual = frames_processed / render_time if render_time > 0 else 0

    print(f"\n=======================================================")
    print(f" [SUCCESS] Tight Per-Subtitle Cleaning Complete!")
    print(f"   OCR Pass (Timeline-level)    : {dt_ocr:.2f}s ({ocr_calls} OCR calls)")
    print(f"   Render Pass (GPU In + Out)   : {render_time:.2f}s ({fps_actual:.1f} FPS, {blurred_frames}/{frames_processed} frames blurred)")
    print(f"   Total End-to-End Time        : {total_time:.2f}s for {frames_processed/fps:.1f}s video")
    print(f"   Output Clean Video           : {out_path} ({os.path.getsize(out_path)/(1024*1024):.1f} MB)")
    print(f"=======================================================\n")
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clause-Sampled RapidOCR Luminance-Suppressed Cleaner.")
    parser.add_argument("-i", "--input", required=True, help="Input video path")
    parser.add_argument("-o", "--output", default=None, help="Output video path")
    parser.add_argument("-s", "--srt", default=None, help="SRT file path (optional, auto-detected)")
    parser.add_argument("-t", "--duration", type=float, default=None, help="Max duration in seconds")
    args = parser.parse_args()

    out_file = args.output or f"output/{Path(args.input).stem}_flawless_clean.mp4"
    process_video_srt_rapidocr(args.input, out_file, srt_file=args.srt, max_duration=args.duration)
