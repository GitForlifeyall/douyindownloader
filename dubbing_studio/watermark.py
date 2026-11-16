#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dubbing_studio/watermark.py
===========================
Channel text watermark generator using translucent SoftLight blend with subtle
dark stroke and offset drop shadow matching bottom-center Shorts/Reels style.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont


_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_FONT = _REPO_ROOT / "assets" / "fonts" / "Montserrat-ExtraBold.ttf"


def _make_even(val: int) -> int:
    return val if val % 2 == 0 else max(2, val - 1)


def _resolve_watermark_font(font_size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        _DEFAULT_FONT,
        Path("C:/Windows/Fonts/Montserrat-ExtraBold.ttf"),
        Path("C:/Windows/Fonts/ariblk.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf"),
    ]
    for p in candidates:
        if p.exists():
            try:
                return ImageFont.truetype(str(p), font_size)
            except Exception:
                pass
    return ImageFont.load_default()


def create_watermark_strip_png(
    watermark_text: str,
    video_w: int,
    video_h: int,
    output_png: Path,
) -> Tuple[Path, Path, int, int]:
    """
    Render an uppercase SoftLight-ready RGB strip (neutral RGB(128, 128, 128) base)
    plus an exact grayscale alpha mask (0 outside text+stroke+shadow) so FFmpeg
    never alters background pixels around the watermark.

    Returns (strip_png_path, mask_png_path, band_height, y_band_top).
    """
    clean_text = " ".join(str(watermark_text or "").strip().upper().split())
    if not clean_text:
        raise ValueError("Watermark text cannot be empty.")

    v_w = _make_even(max(320, int(video_w)))
    v_h = _make_even(max(320, int(video_h)))

    is_square = abs((v_w / max(1.0, float(v_h))) - 1.0) <= 0.10
    if is_square:
        scale_ref = v_h / 1080.0
        font_size = max(18, int(round(38 * scale_ref)))
        # Keep optional watermark unobtrusive below square MarginV=108 captions
        margin_bottom = max(20, int(round(v_h * 0.030)))
    else:
        scale_ref = min(v_w / 1080.0, v_h / 1920.0) if (v_w < v_h) else (v_h / 1080.0)
        font_size = max(22, int(round(52 * scale_ref)))
        # Place watermark just below center video & safely above social-media bottom description zone
        margin_bottom = max(48, int(round(v_h * (345.0 / 1920.0)))) if (v_w < v_h) else max(24, int(round(v_h * 0.065)))
    stroke_w = max(1, int(round(2 * scale_ref)))
    sh_dx = max(2, int(round(3 * scale_ref)))
    sh_dy = max(2, int(round(4 * scale_ref)))

    font = _resolve_watermark_font(font_size)
    # Auto-shrink slightly if a very long channel name would approach side edges
    probe_draw = ImageDraw.Draw(Image.new("RGBA", (v_w, 120)))
    max_text_w = int(v_w * 0.86)
    while font_size > 18:
        bbox = probe_draw.textbbox((0, 0), clean_text, font=font, stroke_width=stroke_w)
        if (bbox[2] - bbox[0]) <= max_text_w:
            break
        font_size -= 2
        font = _resolve_watermark_font(font_size)

    bbox = probe_draw.textbbox((0, 0), clean_text, font=font, stroke_width=stroke_w)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    band_h = _make_even(max(120, th + 64))
    band_h = min(v_h, band_h)
    y_target_bottom = max(th + 20, v_h - margin_bottom)
    y_band_top = _make_even(max(0, min(v_h - band_h, y_target_bottom - th - 28)))

    x_pos = (v_w - tw) // 2 - bbox[0]
    y_in_band = (y_target_bottom - y_band_top) - bbox[3]

    base = Image.new("RGBA", (v_w, band_h), (128, 128, 128, 255))

    # 1. Soft dark offset drop shadow
    sh_layer = Image.new("RGBA", (v_w, band_h), (0, 0, 0, 0))
    ImageDraw.Draw(sh_layer).text(
        (x_pos + sh_dx, y_in_band + sh_dy),
        clean_text,
        font=font,
        fill=(20, 20, 20, 145),
        stroke_width=stroke_w,
        stroke_fill=(20, 20, 20, 130),
    )
    sh_layer = sh_layer.filter(ImageFilter.GaussianBlur(0.8))

    # 2. Translucent light fill + lighter dark stroke
    fg_layer = Image.new("RGBA", (v_w, band_h), (0, 0, 0, 0))
    ImageDraw.Draw(fg_layer).text(
        (x_pos, y_in_band),
        clean_text,
        font=font,
        fill=(245, 245, 245, 225),
        stroke_width=stroke_w,
        stroke_fill=(25, 25, 25, 130),
    )

    alpha_comp = Image.alpha_composite(sh_layer, fg_layer)
    mask_img = alpha_comp.split()[3]
    comp = Image.alpha_composite(base, alpha_comp).convert("RGB")

    output_png = Path(output_png)
    output_png.parent.mkdir(parents=True, exist_ok=True)
    mask_png = output_png.with_name(f"{output_png.stem}_mask{output_png.suffix}")
    comp.save(output_png)
    mask_img.save(mask_png)
    return output_png, mask_png, band_h, y_band_top


def build_watermark_filter_complex(
    base_vf: str,
    video_w: int,
    band_h: int,
    y_band_top: int,
    wm_input_idx: int = 2,
    mask_input_idx: int = 3,
    opacity: float = 0.88,
    pre_fc: str = "",
    pre_out_pad: str = "[0:v]",
) -> Tuple[str, str]:
    """
    Build an FFmpeg filter_complex string chaining optional `pre_fc` + `base_vf` filters and
    SoftLight-blending ONLY the masked watermark pixels (0 background alteration / zero seam).

    Returns (filter_complex_str, output_video_pad).
    """
    prefix = f"{pre_fc};{pre_out_pad}{base_vf}[vbase];[vbase]" if (pre_fc and base_vf) else (
        f"{pre_fc};{pre_out_pad}" if pre_fc else (f"{pre_out_pad}{base_vf}[vbase];[vbase]" if base_vf else f"{pre_out_pad}")
    )
    pad_w = ((int(video_w) + 15) // 16) * 16
    if pad_w != int(video_w):
        pad_in = f"pad={pad_w}:{band_h}:0:0,format=gbrp"
        pad_out = f"format=yuv420p,crop={video_w}:{band_h}:0:0"
        bg_chain = f"crop={video_w}:{band_h}:0:{y_band_top},{pad_in}"
        wm_chain = f"{pad_in}"
    else:
        bg_chain = f"crop={video_w}:{band_h}:0:{y_band_top},format=gbrp"
        wm_chain = "format=gbrp"
        pad_out = "format=yuv420p"

    fc = (
        f"{prefix}split=2[wm_main][wm_tmp];"
        f"[wm_tmp]{bg_chain}[bg_strip];"
        f"[{wm_input_idx}:v]{wm_chain}[wm_strip];"
        f"[bg_strip][wm_strip]blend=all_mode=softlight:all_opacity={opacity:.2f}:shortest=1,{pad_out}[wm_blended];"
        f"[{mask_input_idx}:v]format=gray[wm_alpha];"
        f"[wm_blended][wm_alpha]alphamerge[wm_masked];"
        f"[wm_main][wm_masked]overlay=0:{y_band_top}:shortest=1[vout]"
    )
    return fc, "[vout]"


def apply_watermark_to_video(
    input_video: Path,
    output_video: Path,
    watermark_text: str,
    work_dir: Optional[Path] = None,
) -> Path:
    """Apply SoftLight channel watermark cleanly to an already-rendered video."""
    input_video = Path(input_video)
    output_video = Path(output_video)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(input_video)],
        capture_output=True, text=True
    )
    v_w, v_h = 1080, 1920
    try:
        parts = probe.stdout.strip().splitlines()[0].split("x")
        v_w, v_h = int(parts[0]), int(parts[1])
    except Exception:
        pass

    strip_dir = Path(work_dir) if work_dir else output_video.parent
    strip_png, mask_png, band_h, y_band_top = create_watermark_strip_png(
        watermark_text=watermark_text,
        video_w=v_w,
        video_h=v_h,
        output_png=strip_dir / "channel_watermark_strip.png",
    )
    fc, vpad = build_watermark_filter_complex("", v_w, band_h, y_band_top, wm_input_idx=1, mask_input_idx=2)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_video),
        "-loop", "1", "-i", str(strip_png),
        "-loop", "1", "-i", str(mask_png),
        "-filter_complex", fc,
        "-map", vpad,
        "-map", "0:a?",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "copy",
        "-shortest",
        str(output_video),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return output_video

