#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/experimental_crop_captions.py
===================================
Experimental standalone processor for fast OCR edge-caption detection + cropping.
Isolated from the main pipeline (`dubbing_studio/pipeline.py` is untouched).

Features:
  - `--crop-captions` / `--no-crop-captions` flag
  - Fast frame-skipped RapidOCR scan (downscaled frames, seek-only keyframes)
  - Detects dynamic captions within `< 20%` (`--edge-threshold 0.20`) of bottom or top edge
  - Crops the caption strip cleanly via FFmpeg instead of slow multi-pass blur
  - Runs Google Gemini TTS (`--tts google`) via existing `align_video_and_audio_blocks`
  - Burns resolution-matched Hinglish ASS captions onto the newly cropped video
"""

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
import soundfile as sf
from rapidocr_onnxruntime import RapidOCR

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dubbing_studio.block_aligner import (
    align_video_and_audio_blocks,
    get_media_duration,
    load_srt_blocks,
    synthesize_all_blocks,
)
from dubbing_studio.movie_crop import _make_even, crop_video_fast, detect_caption_edge_fast
from dubbing_studio.tts_engine import srt_to_ass


def burn_subtitles_on_cropped(
    dubbed_no_sub_video: Path,
    aligned_srt: Path,
    final_output: Path,
    vid_w: int,
    vid_h: int,
) -> Path:
    """Generate ASS matched to exact cropped dimensions and burn in one pass."""
    font_size = max(44, int(round(vid_h * 0.082)))
    margin_v = max(36, int(round(vid_h * 0.068)))
    ass_path = dubbed_no_sub_video.with_name(f"{dubbed_no_sub_video.stem}_cropped.ass")

    srt_to_ass(
        srt_path=aligned_srt,
        ass_path=ass_path,
        target_w=vid_w,
        target_h=vid_h,
        font_size=font_size,
        margin_v=margin_v,
        font_name="Montserrat ExtraBold",
        to_hinglish=True,
    )

    escaped_ass = str(ass_path.resolve()).replace("\\", "/").replace(":", "\\:")
    cmd = [
        "ffmpeg", "-y",
        "-i", str(dubbed_no_sub_video),
        "-vf", f"subtitles='{escaped_ass}'",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "copy",
        str(final_output),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return final_output


def _build_atempo_filter(speed_factor: float) -> str:
    """Chain FFmpeg atempo filters clamped between 0.5 and 2.0 per stage."""
    factors = []
    rem = float(speed_factor)
    while rem > 2.0:
        factors.append(2.0)
        rem /= 2.0
    while rem < 0.5:
        factors.append(0.5)
        rem /= 0.5
    factors.append(round(rem, 5))
    return ",".join(f"atempo={f}" for f in factors)


def _format_srt_timestamp(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def align_fast_paced(
    clean_video_path: Path,
    srt_path: Path,
    output_video_path: Path,
    sfx_path: Optional[Path] = None,
    bgm_path: Optional[Path] = None,
    voice: str = "Ludo",
    engine: str = "google",
    work_dir: Path = Path("work"),
    tts_speed: float = 1.20,
    max_silence_sec: float = 0.06,
    tts_cache_dir: Optional[Path] = None,
    bgm_volume: float = 1.05,
) -> Tuple[Path, Optional[Path]]:
    """
    Fast-paced uniform alignment for experimental runs:
    - Tightens inter-block pauses to `max_silence_sec`
    - Speeds up the raw TTS narration uniformly by `tts_speed` (1.0 = natural)
    - Speeds up cropped video + SFX uniformly to match the brisk narration duration
    - Keeps BGM at natural 1.0x tempo and masters with sidechain ducking
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = tts_cache_dir if tts_cache_dir else (work_dir / "temp_audio_blocks")
    cache_dir.mkdir(parents=True, exist_ok=True)

    blocks = load_srt_blocks(srt_path)
    if not blocks:
        raise ValueError(f"No subtitle blocks found in {srt_path}")

    vid_dur = get_media_duration(clean_video_path)
    block_items = synthesize_all_blocks(blocks=blocks, cache_dir=cache_dir, voice=voice, engine=engine)

    # Trim trailing dead air on final line for seamless ending
    last_audio = block_items[-1]["audio"]
    nz = np.where(np.abs(last_audio) > 0.010)[0]
    if len(nz) > 0:
        block_items[-1]["audio"] = last_audio[: int(nz[-1]) + 1]
        block_items[-1]["duration"] = len(block_items[-1]["audio"]) / block_items[-1]["sr"]

    # Sequence voice blocks tightly with capped inter-block silences
    aligned_plan: List[Dict[str, Any]] = []
    cur_t = 0.015
    for idx, item in enumerate(block_items, 1):
        b = item["block"]
        if idx > 1:
            prev_end = block_items[idx - 2]["block"]["end"]
            orig_gap = max(0.0, b["start"] - prev_end)
            gap = min(orig_gap, max_silence_sec) if orig_gap > 0 else min(0.03, max_silence_sec)
            cur_t += gap
        dur = max(0.1, float(item["duration"]))
        aligned_plan.append({
            "index": idx,
            "raw_start": cur_t,
            "raw_end": cur_t + dur,
            "text": b.get("text", ""),
            "audio": item["audio"],
            "sr": item["sr"],
        })
        cur_t += dur

    sr_master = block_items[0]["sr"]
    voice_buf = np.zeros(int((cur_t + 1.0) * sr_master), dtype=np.float32)
    for p in aligned_plan:
        s_idx = int(p["raw_start"] * sr_master)
        aud = p["audio"]
        if p["sr"] != sr_master:
            aud = np.interp(
                np.linspace(0, len(aud), int(len(aud) * (sr_master / p["sr"]))),
                np.arange(len(aud)),
                aud,
            )
        e_idx = s_idx + len(aud)
        if e_idx > len(voice_buf):
            voice_buf = np.pad(voice_buf, (0, e_idx - len(voice_buf) + sr_master))
        voice_buf[s_idx:e_idx] += aud

    raw_voice_wav = work_dir / "raw_unscaled_voice.wav"
    sf.write(str(raw_voice_wav), voice_buf[: int(cur_t * sr_master)], sr_master)

    timed_voice_wav = work_dir / "timed_uniform_voice.wav"
    if abs(tts_speed - 1.0) > 0.005:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(raw_voice_wav), "-filter:a", _build_atempo_filter(tts_speed), str(timed_voice_wav)],
            capture_output=True, check=True,
        )
    else:
        timed_voice_wav = raw_voice_wav

    target_dur = get_media_duration(timed_voice_wav)
    video_speedup = vid_dur / target_dur
    print(
        f"[Experimental Fast-Paced] Unscaled={cur_t:.2f}s @ {tts_speed:.2f}x TTS "
        f"-> Final={target_dur:.2f}s (Orig={vid_dur:.2f}s, Video speedup={video_speedup:.3f}x)"
    )

    # Align SFX uniformly with sped-up video
    aligned_sfx_wav = None
    if sfx_path and Path(sfx_path).exists():
        aligned_sfx_wav = work_dir / "aligned_sfx.wav"
        sfx_cmd = ["ffmpeg", "-y", "-i", str(sfx_path)]
        if abs(video_speedup - 1.0) > 0.01:
            sfx_cmd.extend(["-filter:a", _build_atempo_filter(video_speedup)])
        else:
            sfx_cmd.extend(["-c:a", "copy"])
        sfx_cmd.append(str(aligned_sfx_wav))
        subprocess.run(sfx_cmd, capture_output=True, check=True)

    # Broadcast mastering + sidechain-ducked SFX/BGM mix
    voice_master_af = (
        "highpass=f=85:p=2,"
        "equalizer=f=180:width_type=q:w=1.2:g=1.8,"
        "equalizer=f=420:width_type=q:w=1.8:g=-3.8,"
        "equalizer=f=3100:width_type=q:w=2.0:g=-2.2,"
        "equalizer=f=7200:width_type=q:w=1.6:g=-2.8,"
        "asoftclip=type=atan:threshold=0.88,"
        "acompressor=threshold=-18dB:ratio=2.8:attack=12:release=140:makeup=1.5,"
        "loudnorm=I=-14:TP=-1.5:LRA=7,"
        "aresample=44100"
    )
    resolved_bgm = Path(bgm_path) if (bgm_path and Path(bgm_path).exists()) else None
    bgm_lufs_scale = max(0.35, min(2.0, float(bgm_volume) * 0.85))
    sfx_clean_af = "aresample=44100,highpass=f=220:p=2,agate=threshold=0.030:range=0.02:attack=8:release=90,volume=0.75"
    mixed_audio = work_dir / "aligned_mixed_audio.wav"

    if aligned_sfx_wav and aligned_sfx_wav.exists() and resolved_bgm:
        filter_mix = (
            f"[0:a]{voice_master_af},asplit=3[voice_main][voice_key_sfx][voice_key_bgm];"
            f"[1:a]{sfx_clean_af}[sfx_clean];"
            "[sfx_clean][voice_key_sfx]sidechaincompress=threshold=0.04:ratio=4:attack=5:release=200[sfx_ducked];"
            f"[2:a]atrim=0:{target_dur + 0.5:.3f},asetpts=PTS-STARTPTS,loudnorm=I=-26:TP=-3:LRA=8,aresample=44100,volume={bgm_lufs_scale:.3f}[music_raw];"
            "[music_raw][voice_key_bgm]sidechaincompress=threshold=0.045:ratio=2.8:attack=25:release=350[music];"
            "[voice_main][sfx_ducked][music]amix=inputs=3:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.89[aout]"
        )
        cmd_mix = [
            "ffmpeg", "-y", "-i", str(timed_voice_wav), "-i", str(aligned_sfx_wav),
            "-stream_loop", "-1", "-i", str(resolved_bgm),
            "-filter_complex", filter_mix, "-map", "[aout]", "-c:a", "pcm_s16le",
            "-t", f"{target_dur:.3f}", str(mixed_audio),
        ]
    elif resolved_bgm:
        filter_mix = (
            f"[0:a]{voice_master_af},asplit=2[voice_main][voice_key_bgm];"
            f"[1:a]atrim=0:{target_dur + 0.5:.3f},asetpts=PTS-STARTPTS,loudnorm=I=-26:TP=-3:LRA=8,aresample=44100,volume={bgm_lufs_scale:.3f}[music_raw];"
            "[music_raw][voice_key_bgm]sidechaincompress=threshold=0.045:ratio=2.8:attack=25:release=350[music];"
            "[voice_main][music]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.89[aout]"
        )
        cmd_mix = [
            "ffmpeg", "-y", "-i", str(timed_voice_wav), "-stream_loop", "-1", "-i", str(resolved_bgm),
            "-filter_complex", filter_mix, "-map", "[aout]", "-c:a", "pcm_s16le",
            "-t", f"{target_dur:.3f}", str(mixed_audio),
        ]
    elif aligned_sfx_wav and aligned_sfx_wav.exists():
        filter_mix = (
            f"[0:a]{voice_master_af},asplit=2[voice_main][voice_key];"
            f"[1:a]{sfx_clean_af}[sfx_clean];"
            "[sfx_clean][voice_key]sidechaincompress=threshold=0.04:ratio=4:attack=5:release=200[sfx_ducked];"
            "[voice_main][sfx_ducked]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.89[aout]"
        )
        cmd_mix = [
            "ffmpeg", "-y", "-i", str(timed_voice_wav), "-i", str(aligned_sfx_wav),
            "-filter_complex", filter_mix, "-map", "[aout]", "-c:a", "pcm_s16le",
            "-t", f"{target_dur:.3f}", str(mixed_audio),
        ]
    else:
        cmd_mix = [
            "ffmpeg", "-y", "-i", str(timed_voice_wav), "-af", voice_master_af,
            "-c:a", "pcm_s16le", "-t", f"{target_dur:.3f}", str(mixed_audio),
        ]
    subprocess.run(cmd_mix, capture_output=True, check=True)

    # Save aligned Hinglish SRT (only burned if --captions is enabled)
    aligned_srt = work_dir / f"{clean_video_path.stem}_aligned.srt"
    with open(aligned_srt, "w", encoding="utf-8") as f:
        for p in aligned_plan:
            clean_txt = " ".join(re.sub(r"\[[a-zA-Z\s]+\]", "", p["text"]).split())
            f.write(
                f"{p['index']}\n"
                f"{_format_srt_timestamp(p['raw_start'] / tts_speed)} --> "
                f"{_format_srt_timestamp(p['raw_end'] / tts_speed)}\n"
                f"{clean_txt}\n\n"
            )
    try:
        from dubbing_studio.hinglish import srt_to_hinglish
        aligned_hinglish_srt = work_dir / f"{clean_video_path.stem}_aligned_hinglish.srt"
        aligned_hinglish_srt.write_text(srt_to_hinglish(aligned_srt.read_text(encoding="utf-8")), encoding="utf-8")
    except Exception:
        aligned_hinglish_srt = aligned_srt

    output_video_path.parent.mkdir(parents=True, exist_ok=True)
    cmd_mux = ["ffmpeg", "-y", "-i", str(clean_video_path), "-i", str(mixed_audio)]
    if abs(video_speedup - 1.0) > 0.01:
        cmd_mux.extend(["-vf", f"setpts=PTS/{video_speedup:.5f}"])
    cmd_mux.extend([
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-t", f"{target_dur:.3f}", "-shortest", str(output_video_path),
    ])
    subprocess.run(cmd_mux, capture_output=True, check=True)
    return output_video_path, aligned_hinglish_srt


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Experimental fast OCR edge-caption cropper + fast-paced Google TTS dubber"
    )
    parser.add_argument("--video", "-v", type=str, required=True, help="Raw input video path")
    parser.add_argument("--srt", "-s", type=str, required=True, help="Hindi/target SRT path")
    parser.add_argument("--sfx", type=str, default=None, help="Optional isolated sfx.wav")
    parser.add_argument("--bgm", type=str, default=None, help="Optional BGM mp3 path")
    parser.add_argument(
        "--crop-captions",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run fast frame-skipped OCR and crop top/bottom captions if within edge threshold",
    )
    parser.add_argument(
        "--captions",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Burn Hinglish subtitles onto the cropped video (default: False / no captions)",
    )
    parser.add_argument(
        "--edge-threshold",
        type=float,
        default=0.20,
        help="Max vertical edge band ratio (default: 0.20 = 20%%)",
    )
    parser.add_argument(
        "--sample-frames",
        type=int,
        default=10,
        help="Number of evenly skipped frames to OCR (default: 10)",
    )
    parser.add_argument("--tts", type=str, default="google", help="TTS engine (default: google)")
    parser.add_argument("--voice", type=str, default="Ludo", help="TTS voice (default: Ludo)")
    parser.add_argument(
        "--tts-speed",
        type=float,
        default=1.20,
        help="Uniform TTS pace multiplier (default: 1.20x fast-paced narration)",
    )
    parser.add_argument(
        "--max-silence",
        type=float,
        default=0.06,
        help="Max pause between voiceover blocks in seconds (default: 0.06)",
    )
    parser.add_argument("--tts-cache", type=str, default=None, help="Optional cached temp_audio_blocks dir")
    parser.add_argument("--output", "-o", type=str, required=True, help="Final experimental MP4")
    args = parser.parse_args()

    t_start = time.time()
    raw_video = Path(args.video)
    srt_path = Path(args.srt)
    out_path = Path(args.output)
    work_dir = out_path.parent / f"exp_work_{out_path.stem}"
    work_dir.mkdir(parents=True, exist_ok=True)

    if args.crop_captions:
        print(f"[Experimental OCR] Scanning {args.sample_frames} skipped frames (<={args.edge_threshold*100:.0f}% edge)...")
        info = detect_caption_edge_fast(
            raw_video,
            sample_frames=args.sample_frames,
            edge_threshold=args.edge_threshold,
        )
        print(
            f"[Experimental OCR] Position={info['position'].upper()} in {info['elapsed_sec']:.2f}s | "
            f"bottom_hits={info['bottom_hits']} (distinct={info['distinct_bottom']}) | "
            f"top_hits={info['top_hits']} (distinct={info['distinct_top']}) | "
            f"crop={info['crop_w']}x{info['crop_h']}@{info['crop_x']},{info['crop_y']}"
        )
        cropped_path = work_dir / f"{raw_video.stem}_cropped.mp4"
        t_crop = time.time()
        clean_video, vid_w, vid_h = crop_video_fast(raw_video, cropped_path, info)
        print(f"[Experimental Crop] Saved {vid_w}x{vid_h} cropped video in {time.time() - t_crop:.2f}s")
    else:
        clean_video = raw_video
        cap = cv2.VideoCapture(str(raw_video))
        vid_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        vid_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    dub_target = (work_dir / f"{out_path.stem}_nosub.mp4") if args.captions else out_path

    if abs(args.tts_speed - 1.0) > 0.005 or args.max_silence != 0.20 or args.tts_cache:
        actual_nosub, aligned_hinglish_srt = align_fast_paced(
            clean_video_path=clean_video,
            srt_path=srt_path,
            output_video_path=dub_target,
            sfx_path=Path(args.sfx) if args.sfx else None,
            bgm_path=Path(args.bgm) if args.bgm else None,
            voice=args.voice,
            engine=args.tts,
            work_dir=work_dir / "align_blocks",
            tts_speed=args.tts_speed,
            max_silence_sec=args.max_silence,
            tts_cache_dir=Path(args.tts_cache) if args.tts_cache else None,
        )
    else:
        align_video_and_audio_blocks(
            clean_video_path=clean_video,
            srt_path=srt_path,
            output_video_path=dub_target,
            sfx_path=Path(args.sfx) if args.sfx else None,
            bgm_path=Path(args.bgm) if args.bgm else None,
            voice=args.voice,
            engine=args.tts,
            work_dir=work_dir / "align_blocks",
            burn_subtitles=False,
        )
        actual_nosub = dub_target
        if not actual_nosub.exists():
            cands = sorted(work_dir.glob(f"{out_path.stem.replace('_google', '')}*_nosub.mp4"))
            if cands:
                actual_nosub = cands[0]
        aligned_hinglish_srt = work_dir / "align_blocks" / f"{clean_video.stem}_aligned_hinglish.srt"
        if not aligned_hinglish_srt.exists():
            aligned_hinglish_srt = next((work_dir / "align_blocks").glob("*_aligned_hinglish.srt"))

    if args.captions:
        burn_subtitles_on_cropped(
            dubbed_no_sub_video=actual_nosub,
            aligned_srt=aligned_hinglish_srt,
            final_output=out_path,
            vid_w=vid_w,
            vid_h=vid_h,
        )
    else:
        print("[Experimental Subtitles] Skipped subtitle burn (--no-captions active).")

    print(f"\n[Experimental Done] {out_path} ({vid_w}x{vid_h}) in {time.time() - t_start:.2f}s total!")


if __name__ == "__main__":
    main()

