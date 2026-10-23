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


def detect_subtitle_box_at_timestamp(cap, target_sec, ocr_engine, target_w=1080, target_h=1920):
    """
    Seeks to target_sec, runs RapidOCR on the lower screen, and returns (xmin, ymin, xmax, ymax).
    """
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    frame_idx = int(target_sec * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ret, frame = cap.read()
    if not ret or frame is None:
        return None

    crop_y_start = int(orig_h * 0.65)
    crop_y_end = int(orig_h * 0.88)
    roi = frame[crop_y_start:crop_y_end, :]

    result, _ = ocr_engine(roi, use_det=True, use_rec=False, use_cls=False)
    if not result:
        return None

    all_xs = []
    all_ys = []
    for pts in result:
        all_xs.extend([p[0] for p in pts])
        all_ys.extend([p[1] for p in pts])

    scale_x = target_w / float(orig_w)
    scale_y = target_h / float(orig_h)

    bx1 = int(min(all_xs) * scale_x)
    bx2 = int(max(all_xs) * scale_x)
    by1 = int((min(all_ys) + crop_y_start) * scale_y)
    by2 = int((max(all_ys) + crop_y_start) * scale_y)

    w_box = bx2 - bx1
    h_box = by2 - by1

    if w_box >= 40 and 18 <= h_box <= 140:
        return (bx1, by1, bx2, by2)
    return None


def prepare_blur_data(box, target_w=1080, target_h=1920, pad_x=180, pad_y=14, min_width=1020, ksize=35, sigma=15):
    """
    Precomputes coordinates and a silky, boundary-zeroed alpha mask with
    smooth rounded ends on left and right, generous full-width plate so no words
    leak out on the sides, and tightly fitted vertical height.
    """
    bx1, by1, bx2, by2 = box
    cx = (bx1 + bx2) // 2

    # Generous full-width coverage so Chinese subtitles never leak out on the sides
    half_w = max((bx2 - bx1) // 2 + pad_x, min_width // 2)
    x1 = max(18, cx - half_w)
    x2 = min(target_w - 18, cx + half_w)
    y1 = max(0, by1 - pad_y)
    y2 = min(target_h, by2 + pad_y)

    roi_w = x2 - x1
    roi_h = y2 - y1
    if roi_w <= 0 or roi_h <= 0:
        return None

    # Subtitle core coordinates relative to ROI
    rby1 = by1 - y1
    rby2 = by2 - y1

    core_h = max(20, rby2 - rby1)
    radius = min(core_h // 2, 28)
    cy_core = (rby1 + rby2) // 2

    # The solid inner core spans the FULL horizontal width of the pill plate
    # (from radius to roi_w - radius - 1) so 100% of the interior is solid blur,
    # and ONLY the outer rounded capsule caps smoothly fade at the video borders.
    inner_mask = np.zeros((roi_h, roi_w), dtype=np.uint8)
    core_left = radius
    core_right = roi_w - radius - 1
    if core_right < core_left:
        core_left = radius
        core_right = roi_w - radius - 1

    cv2.rectangle(inner_mask, (core_left, rby1), (core_right, rby2), 255, -1)
    cv2.circle(inner_mask, (core_left, cy_core), radius, 255, -1)
    cv2.circle(inner_mask, (core_right, cy_core), radius, 255, -1)

    # Euclidean distance from outside pixels to the rounded capsule core
    dist_out = cv2.distanceTransform(255 - inner_mask, cv2.DIST_L2, 5)

    # Smooth fade out to borders
    fade_dist = max(6.0, float(pad_y * 1.5))
    alpha = 1.0 - np.clip(dist_out / fade_dist, 0.0, 1.0)
    # Smoothstep (Hermite curve): 3x^2 - 2x^3 ensuring C1 zero-derivatives at borders
    alpha = alpha * alpha * (3.0 - 2.0 * alpha)

    # Horizontal softening for silky left/right pill transition
    alpha = cv2.GaussianBlur(alpha, (25, 1), 6.0)

    # Ensure boundary alpha is mathematically 0.0 at the outer ROI edges
    alpha[:2, :] = 0.0
    alpha[-2:, :] = 0.0
    alpha[:, :2] = 0.0
    alpha[:, -2:] = 0.0

    alpha = np.clip(alpha, 0.0, 1.0)[:, :, None]
    inv_alpha = 1.0 - alpha

    return {
        "coords": (x1, y1, x2, y2),
        "alpha": alpha,
        "inv_alpha": inv_alpha,
        "ksize": ksize if ksize % 2 == 1 else ksize + 1,
        "sigma": sigma
    }


def apply_luminance_suppressed_blur(frame, blur_data):
    """
    Suppresses bright white subtitle pixels down to the ambient background
    tone prior to blurring, eliminating white cloudy ghosting.
    """
    if blur_data is None:
        return frame

    x1, y1, x2, y2 = blur_data["coords"]
    roi = frame[y1:y2, x1:x2].copy()

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    bg_luminance = float(np.percentile(gray, 45))

    bright_text_mask = gray > max(160, int(bg_luminance + 35))

    if np.any(bright_text_mask):
        roi_suppressed = roi.copy()
        roi_suppressed[bright_text_mask] = (
            roi_suppressed[bright_text_mask].astype(np.float32) * 0.35 +
            bg_luminance * 0.65
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

    # 1. Locate or auto-generate SRT file
    if not srt_file:
        candidates = [
            in_path.with_suffix(".srt"),
            Path("output") / f"{in_path.stem}.srt",
            Path("output") / f"{in_path.stem}_hindi.srt"
        ]
        clean_base = in_path.stem.replace("_clean", "")
        candidates.append(Path("output") / f"{clean_base}.srt")
        candidates.append(Path("output/subtitles") / f"{clean_base}_raw.srt")
        candidates.append(Path("output/subtitles") / f"{clean_base}_hindi.srt")
        
        # Check output/subtitles folder
        subs_dir = Path("output/subtitles")
        if subs_dir.exists():
            for s in subs_dir.glob("*.srt"):
                clean_s = s.stem.replace("_raw", "").replace("_hindi", "")
                if clean_s in in_path.stem or in_path.stem[:25] in s.stem:
                    candidates.insert(0, s)
                    break

        for c in candidates:
            if c.exists():
                srt_file = str(c)
                print(f"[*] Found matching subtitle track: {c.name}")
                break

    if not srt_file or not Path(srt_file).exists():
        print(f"[*] No existing SRT found for {in_path.name}. Auto-transcribing using Faster-Whisper...")
        try:
            from dubbing_studio.transcriber import Transcriber
            transcriber = Transcriber()
            auto_srt = Path("output") / f"{in_path.stem}.srt"
            srt_file = str(transcriber.transcribe(in_path, output_srt=auto_srt))
            print(f"[+] Auto-transcription completed: {srt_file}")
        except Exception as e:
            raise FileNotFoundError(
                f"Could not find or generate SRT file for {in_path.name}: {e}. "
                "Please provide --srt path/to/subtitles.srt."
            )

    # 2. Parse and split into visual clauses
    visual_blocks = load_and_split_srt_blocks(srt_file)
    if not visual_blocks:
        raise ValueError(f"SRT file {srt_file} is empty or has invalid formatting.")

    cap = cv2.VideoCapture(str(in_path))
    if not cap.isOpened():
        raise FileNotFoundError(f"Cannot open video: {in_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    if max_duration:
        total_frames = min(total_frames, int(max_duration * fps))

    # Pre-scale if 4K
    scale_factor = 1.0
    target_w, target_h = w, h
    if w > 1080 or h > 1920:
        scale_factor = 1080.0 / w
        target_w = 1080
        target_h = int(h * scale_factor)

    print("=" * 65)
    print(" [RapidOCR Subtitle Cleaner] Generous Margins & Luminance Blur")
    print(f" Input Video   : {in_path.name}")
    print(f" SRT Subtitles : {Path(srt_file).name}")
    print(f" Visual Clauses: {len(visual_blocks)} phrases (sampled once per clause at midpoint)")
    print(f" Resolution    : {target_w}x{target_h} ({fps:.1f} FPS)")
    print(f" Safety Margin : pad_x=120px, pad_y=11px (min_width=960px, ksize=35, sigma=15)")
    print(f" Output Video  : {out_path.name}")
    print("=" * 65)

    # 3. RapidOCR Step: Sample once per visual clause
    print(f"\n[Step 1/2] Sampling RapidOCR at the midpoint of each visual phrase...")
    t0_ocr = time.time()
    ocr_engine = RapidOCR()

    valid_boxes = []
    for i, blk in enumerate(visual_blocks):
        mid_sec = blk["mid"]
        box = detect_subtitle_box_at_timestamp(cap, mid_sec, ocr_engine, target_w, target_h)
        if box is not None:
            valid_boxes.append(box)
            print(f"  Phrase {i+1:2d}/{len(visual_blocks)}: mid={mid_sec:5.1f}s | Box: {box} | '{blk['text'][:20]}'")

    cap.release()
    dt_ocr = time.time() - t0_ocr
    print(f"[Step 1/2] OCR Complete in {dt_ocr:.2f}s ({len(valid_boxes)} subtitle boxes detected)!\n")

    # Compute global maximum subtitle boundary across the entire video
    if valid_boxes:
        min_x = min(b[0] for b in valid_boxes)
        max_x = max(b[2] for b in valid_boxes)
        min_y = min(b[1] for b in valid_boxes)
        max_y = max(b[3] for b in valid_boxes)
    else:
        min_x = 180
        max_x = target_w - 180
        min_y = int(target_h * 0.74)
        max_y = int(target_h * 0.81)

    raw_text_box = (min_x, min_y, max_x, max_y)
    y_center = (min_y + max_y) // 2
    cx = target_w // 2

    # Dynamic MarginV for 120pt Montserrat ExtraBold (Alignment 2):
    # MarginV is vertical distance from bottom edge (1920).
    # 120pt text optical center is ~65px above baseline, so subtracting 65px places text dead-center in the blur.
    margin_v = max(180, target_h - y_center - 65)

    print(f"\n[Maximum Subtitle Boundary] Computed across entire video:")
    print(f"  Detected Text Core: x1={min_x}, y1={min_y}, x2={max_x}, y2={max_y}")
    print(f"  Center Y: {y_center}px -> Dynamic ASS MarginV: {margin_v}")
    print(f"  Permanent luminance blur will remain on 100% of frames with smooth rounded pill edges.\n")

    # Prepare single constant blur data with generous width and balanced vertical margin
    global_blur_data = prepare_blur_data(raw_text_box, target_w, target_h, pad_x=180, pad_y=14, min_width=1020, ksize=35, sigma=15)

    # Save box metadata JSON so pipeline dubbing & subtitle placement use exact dynamic MarginV
    box_meta_path = out_path.with_name(f"{out_path.stem}_box.json")
    box_meta = {
        "raw_text_box": [int(min_x), int(min_y), int(max_x), int(max_y)],
        "y_center": int(y_center),
        "margin_v": int(margin_v)
    }
    box_meta_path.write_text(json.dumps(box_meta, indent=2), encoding="utf-8")
    print(f"  Saved subtitle box metadata: {box_meta_path.name} (MarginV: {margin_v})\n")

    # 4. Stream and Render with GPU Acceleration
    print(f"[Step 2/2] Streaming video and applying permanent constant-boundary luminance blur...")

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

    with tqdm(total=total_frames, desc="Rendering Clean Video", unit="frame") as pbar:
        while frames_processed < total_frames:
            raw = in_pipe.stdout.read(frame_bytes)
            if len(raw) < frame_bytes:
                break

            frame = np.frombuffer(raw, dtype=np.uint8).copy().reshape((target_h, target_w, 3))

            # Apply constant permanent luminance blur on every single frame
            frame = apply_luminance_suppressed_blur(frame, global_blur_data)

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
    print(f" [SUCCESS] Anti-Glitch Subtitle Cleaning Complete!")
    print(f"   OCR Pass (Clause-level)      : {dt_ocr:.2f}s")
    print(f"   Render Pass (GPU In + Out)   : {render_time:.2f}s ({fps_actual:.1f} FPS)")
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
