#!/usr/bin/env python3
"""Benchmark DBS-TIGER-DnR on a representative video-audio clip.

The separator produces phase-coherent mono ``music.wav``, ``sfx.wav`` and
``speech.wav`` stems. It follows the upstream DBS-TIGER-DnR inference recipe:
44.1 kHz audio, 6-second windows and 3-second overlap.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import time
from pathlib import Path

import soundfile as sf
import torch
from dbs.engine import separate
from dbs.models import DBSTIGER


def extract_mono_clip(video_path: Path, output_path: Path, start_sec: float, duration_sec: float) -> None:
    """Extract a float WAV that matches the model's 44.1 kHz mono input."""
    command = [
        "ffmpeg", "-y",
        "-ss", str(start_sec),
        "-t", str(duration_sec),
        "-i", str(video_path),
        "-vn",
        "-ac", "1",
        "-ar", "44100",
        "-acodec", "pcm_f32le",
        str(output_path),
    ]
    completed = subprocess.run(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode:
        raise RuntimeError(f"FFmpeg audio extraction failed:\n{completed.stderr[-2000:]}")


def benchmark_dbs_tiger(
    video_path: str | Path,
    output_dir: str | Path = "benchmark_out",
    start_sec: float = 0,
    duration_sec: float = 40,
) -> None:
    """Separate a clip and report model-load, inference, and GPU-memory usage."""
    source = Path(video_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Input video not found: {source}")
    if duration_sec <= 0:
        raise ValueError("duration_sec must be greater than zero")

    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    mono_wav = destination / "input_44k_mono.wav"

    print(f"[1/4] Extracting {duration_sec:g}s clip to 44.1 kHz mono...")
    # The Windows FFmpeg build may fail to open paths containing Chinese or
    # other non-ASCII characters. Stage such inputs under an ASCII filename.
    extraction_source = source
    staged_source: Path | None = None
    if not str(source).isascii():
        staged_source = destination / f"input_source{source.suffix.lower()}"
        shutil.copy2(source, staged_source)
        extraction_source = staged_source
    try:
        extract_mono_clip(extraction_source, mono_wav, start_sec, duration_sec)
    finally:
        if staged_source is not None:
            staged_source.unlink(missing_ok=True)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    gpu_label = f" ({torch.cuda.get_device_name(0)})" if device.type == "cuda" else ""
    print(f"[2/4] Using device: {device}{gpu_label}")
    if device.type == "cuda":
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()

    print("      Loading DBS-TIGER-DnR model...")
    started = time.perf_counter()
    model = DBSTIGER.from_pretrained("JusperLee/DBS-TIGER-DnR").to(device).eval()
    if device.type == "cuda":
        torch.cuda.synchronize()
    load_time = time.perf_counter() - started
    print(f"      Model loaded in {load_time:.2f}s")

    audio, sample_rate = sf.read(mono_wav, dtype="float32", always_2d=True)
    if sample_rate != 44100:
        raise RuntimeError(f"Expected 44.1 kHz extracted audio, got {sample_rate} Hz")
    # The upstream API expects [batch, channels, samples]. The extraction is mono.
    mixture = torch.from_numpy(audio[:, 0]).view(1, 1, -1).to(device)
    clip_duration = mixture.shape[-1] / sample_rate

    print("[3/4] Running DBS-TIGER-DnR separation...")
    started = time.perf_counter()
    with torch.inference_mode():
        music, sfx, speech = separate(
            model,
            mixture,
            {"mode": "chunked", "chunk_seconds": 6.0, "hop_seconds": 3.0},
            sample_rate=sample_rate,
        )[0]
    if device.type == "cuda":
        torch.cuda.synchronize()
    inference_time = time.perf_counter() - started

    print("[4/4] Saving separated stems...")
    music_np = music.detach().cpu().numpy()
    sfx_np = sfx.detach().cpu().numpy()
    speech_np = speech.detach().cpu().numpy()
    sf.write(destination / "music.wav", music_np, sample_rate)
    sf.write(destination / "sfx.wav", sfx_np, sample_rate)
    sf.write(destination / "speech.wav", speech_np, sample_rate)
    sf.write(destination / "me_combined.wav", music_np + sfx_np, sample_rate)

    print("\n--- Benchmark Summary ---")
    print(f"Clip Duration   : {clip_duration:.2f}s")
    print(f"Model Load Time : {load_time:.2f}s")
    print(f"Inference Time  : {inference_time:.2f}s ({clip_duration / inference_time:.1f}x real-time)")
    print(f"Total Run Time  : {load_time + inference_time:.2f}s")
    if device.type == "cuda":
        peak_vram_mb = torch.cuda.max_memory_allocated() / (1024 ** 2)
        print(f"Peak GPU VRAM   : {peak_vram_mb:.1f} MB")
    print(f"Output directory: {destination}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", help="Source video/audio file")
    parser.add_argument("--output-dir", default="benchmark_out", help="Directory for the WAV stems")
    parser.add_argument("--start", type=float, default=0, help="Clip start offset in seconds")
    parser.add_argument("--duration", type=float, default=40, help="Clip duration in seconds")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    benchmark_dbs_tiger(args.video, args.output_dir, args.start, args.duration)
