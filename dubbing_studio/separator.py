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
import json
import time
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Union, Dict, List, Tuple

import numpy as np
import soundfile as sf
import torch

from .env_loader import configure_runtime_environment
configure_runtime_environment()

# In-process singleton model cache to avoid reloading weights repeatedly
_DBS_MODEL_CACHE: Optional[torch.nn.Module] = None
_DBS_MODEL_DEVICE: Optional[str] = None

# Cache schema version so stale pre-5 stems are automatically re-separated
_STEM_CACHE_VERSION = 5
_STEM_BLEED_MODE_V2 = "htdemucs_method1_hybrid_v4"



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


def _align_audio_length(arr: np.ndarray, target_len: int) -> np.ndarray:
    """Trim or zero-pad a 1D float32 array to match target_len samples."""
    flat = np.asarray(arr, dtype=np.float32).reshape(-1)
    if flat.size == target_len:
        return flat
    if flat.size > target_len:
        return flat[:target_len]
    return np.pad(flat, (0, target_len - flat.size), mode="constant")


def _rms_db(arr: np.ndarray) -> float:
    """Compute signal level in dBFS."""
    return float(20.0 * np.log10(float(np.sqrt(np.mean(np.square(arr)))) + 1e-9))


def _apply_stft_wiener_mask(
    target_1d: torch.Tensor,
    bleed_terms: List[Tuple[float, torch.Tensor]],
    power: float = 1.0,
    n_fft: int = 2048,
    hop_len: int = 512,
    min_gain: float = 0.15,
) -> torch.Tensor:
    """Suppress weighted bleed sources in STFT magnitude space via a gentle soft Wiener mask (preserves Foley decay and avoids watery artifacts)."""
    win = torch.hann_window(n_fft, device=target_1d.device)
    s_target = torch.stft(target_1d, n_fft, hop_length=hop_len, window=win, return_complex=True)
    p_target = s_target.abs().square()

    p_bleed = torch.zeros_like(p_target)
    for weight, stem_1d in bleed_terms:
        if weight <= 0.0:
            continue
        s_bleed = torch.stft(stem_1d, n_fft, hop_length=hop_len, window=win, return_complex=True)
        p_bleed = p_bleed + (float(weight) * s_bleed.abs().square())

    wiener_mask = (p_target / (p_target + p_bleed + 1e-10)).pow(power).clamp(min=min_gain, max=1.0)
    return torch.istft(s_target * wiener_mask, n_fft, hop_length=hop_len, window=win, length=target_1d.numel())


def _compute_music_active_mask(mus_1d: torch.Tensor, sample_rate: int = 44100, window_sec: float = 0.35, thresh_db: float = -38.0) -> torch.Tensor:
    """Return 1D smooth 0..1 gate indicating frames where background music is genuinely active (prevents killing Foley impacts in non-music scenes)."""
    win = max(1, int(window_sec * sample_rate))
    sq = mus_1d.square().unsqueeze(0).unsqueeze(0)
    pad = win // 2
    rms_env = torch.nn.functional.avg_pool1d(sq, kernel_size=win, stride=1, padding=pad).squeeze()
    rms_env = rms_env[:mus_1d.numel()].sqrt()
    thresh_amp = float(10.0 ** (thresh_db / 20.0))
    # Smooth soft knee around thresh_db
    gate = torch.sigmoid((rms_env - thresh_amp) / (thresh_amp * 0.35 + 1e-7))
    return gate


def _run_demucs_htdemucs(
    mono_wav: Path,
    demucs_out_dir: Path,
    prefer_device: str,
) -> Dict[str, np.ndarray]:
    """Run Meta Demucs htdemucs on mono_wav and return 1D mono stems (drums, bass, other, vocals)."""
    demucs_device = "cuda" if (torch.cuda.is_available() and prefer_device == "cuda") else "cpu"
    demucs_out_dir.mkdir(parents=True, exist_ok=True)
    cmd_demucs = [
        sys.executable, "-m", "demucs.separate",
        "-n", "htdemucs",
        "-d", demucs_device,
        "-o", str(demucs_out_dir),
        str(mono_wav),
    ]
    try:
        res = subprocess.run(cmd_demucs, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0 and demucs_device == "cuda":
            cmd_demucs[cmd_demucs.index("-d") + 1] = "cpu"
            res = subprocess.run(cmd_demucs, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"Demucs separation failed: {res.stderr[-400:]}")

        stem_dir_found = demucs_out_dir / "htdemucs" / mono_wav.stem
        stems: Dict[str, np.ndarray] = {}
        for stem_name in ("drums", "bass", "other", "vocals"):
            data, _sr = sf.read(str(stem_dir_found / f"{stem_name}.wav"), dtype="float32", always_2d=True)
            stems[stem_name] = data.mean(axis=1).astype(np.float32)
        return stems
    finally:
        shutil.rmtree(demucs_out_dir, ignore_errors=True)


class AudioStemSeparator:
    """
    High-performance audio stem separator powered by Meta HTDemucs v4.
    Extracts isolated Foley/SFX, background music, and speech.
    """

    def __init__(self, model: str = "htdemucs", device: Optional[str] = None):
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
        meta_file = stem_folder / "stems_meta.json"

        # Check existing cache (require v2 bleed-suppression metadata so stale stems auto-rebuild)
        if not force and sfx_file.exists() and sfx_file.stat().st_size > 10000 and meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                if (
                    int(meta.get("schema_version", 0)) >= _STEM_CACHE_VERSION
                    and meta.get("bleed_suppression") == _STEM_BLEED_MODE_V2
                ):
                    print(f"[StemSeparator] Found cached v2 bleed-scrubbed stems in: {stem_folder.name}")
                    return {
                        "sfx": sfx_file,
                        "music": music_file,
                        "speech": speech_file,
                        "no_vocals": no_vocals_file if no_vocals_file.exists() else sfx_file,
                        "stem_dir": stem_folder
                    }
            except (json.JSONDecodeError, OSError, ValueError):
                pass
            print(f"[StemSeparator] Stale stem cache in {stem_folder.name}; re-separating with Fix 2B...")
        elif not force and sfx_file.exists() and sfx_file.stat().st_size > 10000:
            print(f"[StemSeparator] Pre-v2 un-scrubbed cache in {stem_folder.name}; re-separating with Fix 2B...")

        model_display = "Meta HTDemucs v4" if self.model_name.lower() in ("htdemucs", "demucs") else self.model_name
        print(f"\n==========================================")
        print(f"[StemSeparator] Engaging {model_display} Cinematic Separation")
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

        separated = False

        if self.model_name.lower() in ("htdemucs", "demucs"):
            print(f"  [2/3] Separating Foley SFX, Music & Speech via Meta Demucs (htdemucs v4)...")
            t_start = time.perf_counter()
            demucs_stems = _run_demucs_htdemucs(mono_wav, base_out / "_demucs_out", self.device)
            inference_time = time.perf_counter() - t_start
            print(f"  [Separation Complete] Finished in {inference_time:.1f}s via Meta Demucs.")

            target_len = audio_np.shape[0]
            drums_np = _align_audio_length(demucs_stems["drums"], target_len)
            bass_np = _align_audio_length(demucs_stems["bass"], target_len)
            other_np = _align_audio_length(demucs_stems["other"], target_len)
            vocals_np = _align_audio_length(demucs_stems["vocals"], target_len)

            # Method 1: Hybrid Music Scrubbing
            # Scrub background music score out of HTDemucs 'other' to isolate pure Foley
            dev = torch.device(self.device)
            other_t = torch.from_numpy(other_np).float().to(dev)
            vocals_t = torch.from_numpy(vocals_np).float().to(dev)
            drums_t = torch.from_numpy(drums_np).float().to(dev)
            bass_t = torch.from_numpy(bass_np).float().to(dev)

            # Pure HTDemucs Wiener Bleed Suppression (vocals, drums, bass scrubbed from 'other' -> clean Foley)
            bleed_terms = [
                (0.50, vocals_t),
                (0.85, drums_t),
                (0.85, bass_t),
            ]
            sfx_clean_1d = _apply_stft_wiener_mask(other_t, bleed_terms, power=1.5, min_gain=0.03)

            sfx_mix = sfx_clean_1d.cpu().numpy().reshape(-1, 1)
            music_mix = (drums_np + bass_np).reshape(-1, 1)
            speech_mix = vocals_np.reshape(-1, 1)
            no_vocals_mix = (drums_np + bass_np + other_np).reshape(-1, 1)

            sf.write(str(sfx_file), sfx_mix, sample_rate)
            sf.write(str(music_file), music_mix, sample_rate)
            sf.write(str(speech_file), speech_mix, sample_rate)
            sf.write(str(no_vocals_file), no_vocals_mix, sample_rate)
            meta_file.write_text(
                json.dumps(
                    {
                        "schema_version": _STEM_CACHE_VERSION,
                        "bleed_suppression": "htdemucs_method1_hybrid_v4",
                        "sample_rate": sample_rate,
                        "model": "htdemucs_v4_method1",
                        "sfx_rms_db": round(_rms_db(sfx_mix), 2),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            separated = True
        else:
            dbs_model = get_dbs_model(self.device)
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

                    if dev.type == "cuda":
                        torch.cuda.empty_cache()

                    print("  [3/3] Exporting isolated stems (DBS-TIGER gentle Wiener scrub + conditional Demucs)...")
                    orig_shape = sfx_t.shape
                    sfx_1d = sfx_t.detach().float().reshape(-1)
                    spc_1d = speech_t.detach().float().reshape(-1)
                    mus_1d = music_t.detach().float().reshape(-1)

                    bleed_terms: List[Tuple[float, torch.Tensor]] = [
                        (0.85, spc_1d),
                        (0.75, mus_1d),
                    ]
                    bleed_mode = "dbs_wiener_v4"
                    music_rms_db = float(
                        20.0 * torch.log10(torch.clamp(torch.sqrt(torch.mean(mus_1d ** 2)), min=1e-7)).item()
                    )
                    if music_rms_db > -22.0:
                        try:
                            t_demucs = time.perf_counter()
                            demucs_stems = _run_demucs_htdemucs(mono_wav, base_out / "_demucs_out", self.device)
                            music_gate = _compute_music_active_mask(mus_1d, sample_rate=sample_rate)
                            drums_1d = torch.from_numpy(_align_audio_length(demucs_stems["drums"], sfx_1d.numel())).to(dev) * music_gate
                            bass_1d = torch.from_numpy(_align_audio_length(demucs_stems["bass"], sfx_1d.numel())).to(dev) * music_gate
                            bleed_terms.extend([
                                (0.50, drums_1d),
                                (0.60, bass_1d),
                            ])
                            bleed_mode = _STEM_BLEED_MODE_V2
                        except Exception as demucs_err:
                            print(f"  [Fix 2B] Warning: Demucs bleed reference skipped ({demucs_err}); falling back to DBS Wiener mask.")

                    sfx_clean_1d = _apply_stft_wiener_mask(sfx_1d, bleed_terms, power=1.0, min_gain=0.15)

                    music_out = music_t.detach().cpu().numpy()
                    sfx_out = sfx_clean_1d.reshape(orig_shape).cpu().numpy()
                    speech_out = speech_t.detach().cpu().numpy()

                    print(f"  [Stem Levels] SFX: {_rms_db(sfx_out):.1f} dBFS | Music: {_rms_db(music_out):.1f} dBFS | Speech: {_rms_db(speech_out):.1f} dBFS")

                    sf.write(str(sfx_file), sfx_out, sample_rate)
                    sf.write(str(music_file), music_out, sample_rate)
                    sf.write(str(speech_file), speech_out, sample_rate)
                    sf.write(str(no_vocals_file), music_out + sfx_out, sample_rate)
                    meta_file.write_text(
                        json.dumps(
                            {
                                "schema_version": _STEM_CACHE_VERSION,
                                "bleed_suppression": bleed_mode,
                                "sample_rate": sample_rate,
                                "sfx_rms_db": round(_rms_db(sfx_out), 2),
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    separated = True
                except Exception as e:
                    print(f"  [StemSeparator] DBS-TIGER separation failed ({e}). Falling back to Meta Demucs...")

        if not separated:
            # Meta Demucs (htdemucs) fallback (never mix raw drums/bass into SFX)
            print(f"  [2/3] Separating Foley SFX, Music & Speech via Meta Demucs (htdemucs fallback)...")
            t_start = time.perf_counter()
            demucs_stems = _run_demucs_htdemucs(mono_wav, base_out / "_demucs_out", self.device)
            inference_time = time.perf_counter() - t_start
            print(f"  [Separation Complete] Finished in {inference_time:.1f}s via Meta Demucs.")

            target_len = audio_np.shape[0]
            drums_np = _align_audio_length(demucs_stems["drums"], target_len)
            bass_np = _align_audio_length(demucs_stems["bass"], target_len)
            other_np = _align_audio_length(demucs_stems["other"], target_len)
            vocals_np = _align_audio_length(demucs_stems["vocals"], target_len)

            demucs_dev = torch.device("cuda" if (torch.cuda.is_available() and self.device == "cuda") else "cpu")
            sfx_clean_1d = _apply_stft_wiener_mask(
                torch.from_numpy(other_np).to(demucs_dev),
                [
                    (0.50, torch.from_numpy(vocals_np).to(demucs_dev)),
                    (0.85, torch.from_numpy(drums_np).to(demucs_dev)),
                    (0.85, torch.from_numpy(bass_np).to(demucs_dev)),
                ],
                power=2.0,
            )
            sfx_mix = sfx_clean_1d.cpu().numpy().reshape(-1, 1)
            music_mix = (drums_np + bass_np).reshape(-1, 1)
            speech_mix = vocals_np.reshape(-1, 1)
            no_vocals_mix = (drums_np + bass_np + other_np).reshape(-1, 1)

            sf.write(str(sfx_file), sfx_mix, sample_rate)
            sf.write(str(music_file), music_mix, sample_rate)
            sf.write(str(speech_file), speech_mix, sample_rate)
            sf.write(str(no_vocals_file), no_vocals_mix, sample_rate)
            meta_file.write_text(
                json.dumps(
                    {
                        "schema_version": _STEM_CACHE_VERSION,
                        "bleed_suppression": _STEM_BLEED_MODE_V2,
                        "sample_rate": sample_rate,
                        "fallback_demucs_only": True,
                        "sfx_rms_db": round(_rms_db(sfx_mix), 2),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

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
