#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dubbing_studio/separator.py
===========================
Next-Generation Cinematic Audio Stem Separation using DBS-TIGER-DnR.
Separates video/audio tracks into:
  - sfx.wav       : Isolated Foley & sound effects (kicks, water, chops, sizzling, ambient sounds)
  - music.wav     : Isolated background score / music
  - speech.wav    : Isolated original dialogue vocals
  - no_vocals.wav : Combined music + SFX (retained for backward compatibility)

Optimized for NVIDIA RTX 3050 GPU (CUDA accelerated, ~1.2 GB VRAM footprint).
"""

from __future__ import annotations

import os
import sys
import time
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Union, Dict

import soundfile as sf
import torch

from .env_loader import configure_runtime_environment
configure_runtime_environment()

# In-process singleton model cache to avoid reloading weights repeatedly
_DBS_MODEL_CACHE: Optional[torch.nn.Module] = None
_DBS_MODEL_DEVICE: Optional[str] = None


def get_dbs_model(device_str: Optional[str] = None) -> Optional[torch.nn.Module]:
    """Retrieve or initialize the cached DBS-TIGER-DnR model on the designated device."""
    global _DBS_MODEL_CACHE, _DBS_MODEL_DEVICE

    target_device = device_str or ("cuda" if torch.cuda.is_available() else "cpu")

    if _DBS_MODEL_CACHE is not None and _DBS_MODEL_DEVICE == target_device:
        return _DBS_MODEL_CACHE

    try:
        from dbs.models import DBSTIGER
    except ImportError:
        return None

    dev = torch.device(target_device)
    print(f"[StemSeparator] Loading DBS-TIGER-DnR model onto {dev}...")
    t0 = time.perf_counter()

    if dev.type == "cuda":
        torch.cuda.empty_cache()

    model = DBSTIGER.from_pretrained("JusperLee/DBS-TIGER-DnR").to(dev).eval()

    if dev.type == "cuda":
        torch.cuda.synchronize()

    t_load = time.perf_counter() - t0
    print(f"[StemSeparator] DBS-TIGER-DnR ready in {t_load:.2f}s (Device: {target_device})")

    _DBS_MODEL_CACHE = model
    _DBS_MODEL_DEVICE = target_device
    return _DBS_MODEL_CACHE


class AudioStemSeparator:
    """
    High-performance audio stem separator powered by DBS-TIGER-DnR.
    Extracts isolated Foley/SFX, background music, and speech.
    """

    def __init__(self, model: str = "DBS-TIGER-DnR", device: Optional[str] = None):
        self.model_name = model
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")

    def separate_audio(
        self,
        video_or_audio_path: Union[str, Path],
        output_dir: Optional[Union[str, Path]] = None,
        clean_name: Optional[str] = None,
        force: bool = False
    ) -> Dict[str, Path]:
        """
        Extracts 'sfx.wav', 'music.wav', 'speech.wav', and 'no_vocals.wav'
        from the input video or audio file.
        """
        in_path = Path(video_or_audio_path).resolve()
        if not in_path.exists():
            raise FileNotFoundError(f"Input file not found: {in_path}")

        base_out = Path(output_dir) if output_dir else in_path.parent
        folder_stem = clean_name if clean_name else in_path.stem
        stem_folder = base_out / f"stems_{folder_stem}"
        stem_folder.mkdir(parents=True, exist_ok=True)

        sfx_file = stem_folder / "sfx.wav"
        music_file = stem_folder / "music.wav"
        speech_file = stem_folder / "speech.wav"
        no_vocals_file = stem_folder / "no_vocals.wav"

        # Check existing cache
        if not force and sfx_file.exists() and sfx_file.stat().st_size > 10000:
            print(f"[StemSeparator] Found cached DBS-TIGER stems in: {stem_folder.name}")
            return {
                "sfx": sfx_file,
                "music": music_file,
                "speech": speech_file,
                "no_vocals": no_vocals_file if no_vocals_file.exists() else sfx_file,
                "stem_dir": stem_folder
            }

        print(f"\n==========================================")
        print(f"[StemSeparator] Engaging DBS-TIGER-DnR Cinematic Separation")
        print(f"Source: {in_path.name}")
        print(f"Model: {self.model_name} | Target Device: {self.device}")
        print(f"Destination: {stem_folder.name}")
        print(f"==========================================")

        # Stage audio extraction in an ASCII-safe path to prevent Windows FFmpeg path errors
        safe_work_dir = base_out / "_dbs_work"
        safe_work_dir.mkdir(parents=True, exist_ok=True)
        mono_wav = safe_work_dir / "input_44k_mono.wav"

        extraction_source = in_path
        staged_source: Optional[Path] = None
        if not str(in_path).isascii():
            staged_source = safe_work_dir / f"input_source{in_path.suffix.lower()}"
            shutil.copy2(in_path, staged_source)
            extraction_source = staged_source

        try:
            print("  [1/3] Extracting 44.1 kHz mono float audio...")
            cmd_extract = [
                "ffmpeg", "-y",
                "-i", str(extraction_source),
                "-vn",
                "-ac", "1",
                "-ar", "44100",
                "-acodec", "pcm_f32le",
                str(mono_wav)
            ]
            subprocess.run(cmd_extract, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
        finally:
            if staged_source is not None and staged_source.exists():
                staged_source.unlink(missing_ok=True)

        # Load audio into PyTorch tensor
        audio_np, sample_rate = sf.read(str(mono_wav), dtype="float32", always_2d=True)
        if sample_rate != 44100:
            raise RuntimeError(f"Expected 44.1 kHz audio, received {sample_rate} Hz")

        dbs_model = get_dbs_model(self.device)
        separated = False

        if dbs_model is not None:
            try:
                from dbs.engine import separate
                dev = torch.device(self.device)
                mixture = torch.from_numpy(audio_np[:, 0]).view(1, 1, -1).to(dev)
                duration_sec = mixture.shape[-1] / sample_rate
                print(f"  [2/3] Separating stems with DBS-TIGER ({duration_sec:.1f}s audio track)...")
                t_start = time.perf_counter()

                with torch.inference_mode():
                    music_t, sfx_t, speech_t = separate(
                        dbs_model,
                        mixture,
                        {"mode": "chunked", "chunk_seconds": 6.0, "hop_seconds": 3.0},
                        sample_rate=sample_rate,
                    )[0]

                if dev.type == "cuda":
                    torch.cuda.synchronize()

                inference_time = time.perf_counter() - t_start
                rtf = duration_sec / max(inference_time, 0.001)
                print(f"  [Separation Complete] {duration_sec:.1f}s processed in {inference_time:.1f}s ({rtf:.1f}x real-time)")

                print("  [3/3] Exporting isolated stems...")
                music_out = music_t.detach().cpu().numpy()
                sfx_out = sfx_t.detach().cpu().numpy()
                speech_out = speech_t.detach().cpu().numpy()

                sf.write(str(sfx_file), sfx_out, sample_rate)
                sf.write(str(music_file), music_out, sample_rate)
                sf.write(str(speech_file), speech_out, sample_rate)
                sf.write(str(no_vocals_file), music_out + sfx_out, sample_rate)
                separated = True
            except Exception as e:
                print(f"  [StemSeparator] DBS-TIGER separation failed ({e}). Falling back to Meta Demucs...")

        if not separated:
            # Meta Demucs (htdemucs) fallback
            demucs_device = "cuda" if (torch.cuda.is_available() and self.device == "cuda") else "cpu"
            print(f"  [2/3] Separating Foley SFX, Music & Speech via Meta Demucs (htdemucs on {demucs_device})...")
            demucs_out_dir = base_out / "_demucs_out"
            demucs_out_dir.mkdir(parents=True, exist_ok=True)
            cmd_demucs = [
                sys.executable, "-m", "demucs.separate",
                "-n", "htdemucs",
                "-d", demucs_device,
                "-o", str(demucs_out_dir),
                str(mono_wav)
            ]
            t_start = time.perf_counter()
            res = subprocess.run(cmd_demucs, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode != 0 and demucs_device == "cuda":
                # Fallback to CPU if CUDA had an issue
                cmd_demucs[cmd_demucs.index("-d") + 1] = "cpu"
                res = subprocess.run(cmd_demucs, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            if res.returncode != 0:
                raise RuntimeError(f"Demucs separation failed: {res.stderr[-400:]}")

            inference_time = time.perf_counter() - t_start
            print(f"  [Separation Complete] Finished in {inference_time:.1f}s via Meta Demucs.")

            stem_dir_found = demucs_out_dir / "htdemucs" / mono_wav.stem
            drums_data, sr = sf.read(str(stem_dir_found / "drums.wav"), dtype="float32", always_2d=True)
            bass_data, _ = sf.read(str(stem_dir_found / "bass.wav"), dtype="float32", always_2d=True)
            other_data, _ = sf.read(str(stem_dir_found / "other.wav"), dtype="float32", always_2d=True)
            vocals_data, _ = sf.read(str(stem_dir_found / "vocals.wav"), dtype="float32", always_2d=True)

            # Foley / SFX is other + drums (clinking, chopping, water, natural sounds)
            sfx_mix = other_data + drums_data
            music_mix = bass_data
            speech_mix = vocals_data
            no_vocals_mix = drums_data + bass_data + other_data

            sf.write(str(sfx_file), sfx_mix, sr)
            sf.write(str(music_file), music_mix, sr)
            sf.write(str(speech_file), speech_mix, sr)
            sf.write(str(no_vocals_file), no_vocals_mix, sr)

            shutil.rmtree(demucs_out_dir, ignore_errors=True)

        # Cleanup temporary audio extraction
        shutil.rmtree(safe_work_dir, ignore_errors=True)

        print(f"[StemSeparator] SUCCESS!")
        print(f"  -> Isolated Sound Effects (SFX/Foley) : {sfx_file.name} ({sfx_file.stat().st_size / 1024 / 1024:.2f} MB)")
        print(f"  -> Isolated Music Track               : {music_file.name} ({music_file.stat().st_size / 1024 / 1024:.2f} MB)")
        print(f"  -> Isolated Dialogue Speech           : {speech_file.name} ({speech_file.stat().st_size / 1024 / 1024:.2f} MB)")

        return {
            "sfx": sfx_file,
            "music": music_file,
            "speech": speech_file,
            "no_vocals": no_vocals_file,
            "stem_dir": stem_folder
        }
