#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dubbing_studio/tts_google.py
============================
Production Google Gemini Text-to-Speech Engine & Video Dubber.
Features:
  - Per-block high-fidelity synthesis with disk caching
  - Multi-key round-robin rotation across GEMINI_API_KEYS to prevent 429 rate limits
  - Waterfall timeline anchoring (ZERO voice overlap, natural conversational pacing)
  - Preserved BGM/SFX sidechain ducking via Meta Demucs
"""

import os
import sys
import time
import io
import json
import subprocess
import random
import threading
from pathlib import Path
from typing import Optional, Union, List, Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import soundfile as sf
from google import genai
from google.genai import types
from google.genai.errors import ClientError

from .env_loader import configure_runtime_environment
configure_runtime_environment()

from .key_pool import (
    get_active_gemini_keys,
    mark_gemini_key_dead,
    is_gemini_dead_error,
    mask_key,
)
from .tts_engine import load_srt_blocks, srt_to_ass, generate_synced_hinglish_ass


def parse_gemini_audio_response(raw_bytes: bytes, mime_type: str = "audio/L16", sample_rate: int = 24000) -> Tuple[np.ndarray, int]:
    """Decodes audio bytes from Gemini API into float32 numpy array and sample rate."""
    if "L16" in mime_type or "pcm" in mime_type.lower():
        audio_array = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        return audio_array, sample_rate
    try:
        data, sr = sf.read(io.BytesIO(raw_bytes))
        return data, sr
    except Exception:
        audio_array = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        return audio_array, sample_rate


def trim_audio_silence(audio: np.ndarray, threshold: float = 0.005, pad_samples: int = 480) -> np.ndarray:
    """Trim digital zero-padding and dead silence from start and end."""
    mask = np.abs(audio) > threshold
    if not np.any(mask):
        return audio
    first = max(0, int(np.argmax(mask) - pad_samples))
    last = min(len(audio), int(len(mask) - np.argmax(mask[::-1]) + pad_samples))
    return audio[first:last]


def adjust_audio_speed(audio: np.ndarray, sample_rate: int, speed: float) -> np.ndarray:
    """Smooth tempo compression using ffmpeg rubberband/atempo filter."""
    if abs(speed - 1.0) < 0.03:
        return audio

    temp_in = io.BytesIO()
    sf.write(temp_in, audio, sample_rate, format="WAV")
    wav_bytes = temp_in.getvalue()

    safe_speed = max(0.8, min(speed, 1.40))
    cmd = [
        "ffmpeg", "-y",
        "-f", "wav", "-i", "pipe:0",
        "-filter:a", f"atempo={safe_speed:.3f}",
        "-f", "wav", "pipe:1"
    ]
    proc = subprocess.run(cmd, input=wav_bytes, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if proc.returncode == 0 and len(proc.stdout) > 44:
        adj_audio, _ = sf.read(io.BytesIO(proc.stdout))
        return adj_audio
    return audio


class GoogleGeminiTTS:
    """
    Google Gemini TTS Engine with Multi-Key Rotation and Frame-Synchronized Alignment.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_speaker: str = "Ludo",
        model: str = "gemini-3.8-flash-tts",
        style: str = "narration",
        system_instruction: Optional[str] = None
    ):
        active_pool = get_active_gemini_keys()
        if api_key:
            self.api_keys = [api_key.strip()]
        else:
            self.api_keys = active_pool

        if not self.api_keys:
            raise ValueError("No active GEMINI_API_KEY or GEMINI_API_KEYS found in environment.")

        self.key_idx = 0
        self._key_lock = threading.Lock()
        self.default_speaker = default_speaker
        self.model = model
        self.style = style
        if system_instruction:
            self.system_instruction = system_instruction
        elif style.lower() in ("narration", "narrator", "documentary"):
            self.system_instruction = (
                "You are an expert video narrator. Deliver the narration with a deep, steady, captivating storytelling tone. "
                "Pronounce words clearly and naturally. Never recite prompt instructions, only read the given text."
            )
        elif style.lower() in ("energetic", "funny", "roast"):
            self.system_instruction = (
                "You are an energetic, witty viral video commentator. Deliver the narration with high energy, expressive comedic timing, and dynamic pitch. "
                "Never recite prompt instructions, only read the given text."
            )
        else:
            self.system_instruction = None

        self.fallback_models = [
            "gemini-3.8-flash-tts",
        ]

    def get_client(self) -> Tuple[genai.Client, str]:
        with self._key_lock:
            active_pool = set(get_active_gemini_keys())
            self.api_keys = [k for k in self.api_keys if k in active_pool]
            if not self.api_keys:
                self.api_keys = list(active_pool)
            if not self.api_keys:
                raise RuntimeError("All Gemini API keys in the runtime pool have been exhausted.")
            key = self.api_keys[self.key_idx % len(self.api_keys)]
        return genai.Client(api_key=key), key

    def rotate_key(self, dead_key: Optional[str] = None, reason: str = ""):
        with self._key_lock:
            if dead_key:
                mark_gemini_key_dead(dead_key, reason=reason)
                if dead_key in self.api_keys:
                    self.api_keys.remove(dead_key)
            if self.api_keys:
                self.key_idx = (self.key_idx + 1) % len(self.api_keys)
                new_idx = self.key_idx
                masked = mask_key(self.api_keys[new_idx])
                if not dead_key:
                    print(f"      [Key Rotation] Switched to Key #{new_idx + 1}/{len(self.api_keys)} ({masked})")

    def synthesize_single_block(
        self,
        contents: Union[str, types.Part],
        voice: Optional[str] = None,
        cache_path: Optional[Path] = None,
        max_retries: int = 10
    ) -> Tuple[np.ndarray, int]:
        """Synthesize a single subtitle line with automatic retry and key rotation."""
        if cache_path and cache_path.exists() and cache_path.stat().st_size > 500:
            audio, sr = sf.read(str(cache_path))
            return audio, sr

        speaker_name = voice or self.default_speaker
        config = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config={"voice_config": {"prebuilt_voice_config": {"voice_name": speaker_name}}}
        )

        prompt_str = str(contents).strip()
        c_input = prompt_str

        models_to_try = [self.model] + [m for m in self.fallback_models if m != self.model]

        for attempt in range(max_retries):
            if not self.api_keys and not get_active_gemini_keys():
                raise RuntimeError("All Gemini API keys in the runtime pool have been exhausted.")
            current_model = models_to_try[attempt % len(models_to_try)]
            client, active_key = self.get_client()
            try:
                res = client.models.generate_content(
                    model=current_model,
                    contents=c_input,
                    config=config
                )
                part = res.candidates[0].content.parts[0]
                raw_bytes = part.inline_data.data
                mime_type = getattr(part.inline_data, "mime_type", "audio/L16")
                audio, sr = parse_gemini_audio_response(raw_bytes, mime_type=mime_type, sample_rate=24000)

                # Rotate key round-robin to evenly spread request load
                self.rotate_key()

                if cache_path:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    sf.write(str(cache_path), audio, sr)
                return audio, sr
            except ClientError as e:
                err_str = str(e)
                if is_gemini_dead_error(err_str):
                    self.rotate_key(dead_key=active_key, reason=err_str[:80])
                    time.sleep(0.5)
                else:
                    self.rotate_key(reason=err_str[:60])
                    time.sleep(1.0)
            except Exception as e:
                err_str = str(e)
                if is_gemini_dead_error(err_str):
                    self.rotate_key(dead_key=active_key, reason=err_str[:80])
                    time.sleep(0.5)
                else:
                    print(f"      [Notice on {current_model}] {e}. Retrying in 1s...")
                    self.rotate_key()
                    time.sleep(1.0)

        raise RuntimeError(f"Google Gemini TTS failed to synthesize: {str(contents)[:40]}...")

    def synthesize_and_dub(
        self,
        dubbed_srt: Union[str, Path],
        original_video: Union[str, Path],
        final_video: Optional[Union[str, Path]] = None,
        voice: Optional[str] = None,
        lang: str = "Hindi",
        base_speed: float = 1.0,
        mode: str = "synced",
        bgm_path: Optional[Union[str, Path]] = None,
        sfx_path: Optional[Union[str, Path]] = None,
        bgm_volume: float = 1.05,
        work_dir: Optional[Union[str, Path]] = None,
        enable_autotag: bool = True,
        **kwargs
    ) -> Path:
        """
        Synthesizes per-block audio and aligns onto timeline with anti-overlap anchoring.
        """
        srt_path = Path(dubbed_srt)
        vid_path = Path(original_video)
        out_vid = Path(final_video) if final_video else srt_path.parent / f"{srt_path.stem}_google_dubbed.mp4"
        working_dir = Path(work_dir) if work_dir else srt_path.parent
        working_dir.mkdir(parents=True, exist_ok=True)

        speaker = voice or self.default_speaker
        if mode in ("single_narrator", "narrator", "continuous"):
            from dub_single_narrator import run_single_narrator_pipeline
            result_path = run_single_narrator_pipeline(
                video_path=str(vid_path),
                speaker=speaker,
                engine="google",
                voice=speaker,
                pace=base_speed,
                target_end_margin=kwargs.get("margin", 0.35),
                force=kwargs.get("force", False),
                enable_autotag=enable_autotag,
                dubbed_srt=srt_path,
                output_video_path=out_vid,
                bg_music_path=kwargs.get("sfx_path") or kwargs.get("bgm_path"),
                work_dir=working_dir,
                margin_v=kwargs.get("margin_v")
            )
            return Path(result_path)

        blocks = load_srt_blocks(srt_path)
        if not blocks:
            raise RuntimeError(f"No subtitle blocks found in {srt_path}")

        if enable_autotag:
            from .autotagger import autotag_srt_blocks
            blocks = autotag_srt_blocks(blocks)
            print(f"[Google TTS] Autotag: Injected vocal emotion tags & speech metadata across {len(blocks)} blocks.")

        # Probe video runtime
        probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(vid_path)]
        vid_dur = float(subprocess.check_output(probe_cmd).decode().strip())

        print(f"\n==========================================")
        print(f"[Google TTS] Synthesizing Studio Voiceover (Per-Block Mode)")
        print(f"Model: {self.model} | Speaker: {speaker}")
        print(f"Key Pool: {len(self.api_keys)} API keys active")
        print(f"Subtitles: {srt_path.name} ({len(blocks)} blocks)")
        print(f"Target Video: {vid_path.name} ({vid_dur:.2f}s)")
        print(f"Work Dir: {working_dir.name}")
        if bgm_path and Path(bgm_path).exists():
            print(f"Preserved BGM & SFX: {Path(bgm_path).name} (Dynamic Ducking Enabled)")
        else:
            print("Preserved BGM & SFX: None (Clean voiceover only)")
        print(f"==========================================")

        sample_rate = 24000
        clean_model = self.model.replace("/", "_").replace(":", "_").replace("-", "_")
        cache_dir = working_dir / f"google_tts_cache_{srt_path.stem}_{speaker.lower()}_{clean_model}"
        cache_dir.mkdir(parents=True, exist_ok=True)

        # -------------------------------------------------------------
        # Step 1: Synthesize each block with disk caching & key rotation
        # -------------------------------------------------------------
        block_audios: List[Optional[Dict[str, Any]]] = [None] * len(blocks)
        t_start_synth = time.time()
        # Parallelize independent per-block synthesis calls. The multi-key round-robin
        # (guarded by self._key_lock) makes concurrent requests safe and spreads load.
        max_workers = max(1, min(8, len(self.api_keys) * 2))
        print(f"\n[Google TTS] Synthesizing / loading speech blocks (parallel, {max_workers} workers)...")

        def _synth_block(i: int, b: Dict[str, Any]):
            idx = b["index"]
            c_file = cache_dir / f"block_{idx:02d}.wav"
            t0 = time.time()
            if c_file.exists() and c_file.stat().st_size > 500:
                raw_audio, sr = sf.read(str(c_file))
                print(f"  [{i:02d}/{len(blocks):02d}] Loaded from cache: Block #{idx:02d} ({len(raw_audio)/sr:.2f}s)")
            else:
                tag_preview = f" [{b['style']}]" if 'style' in b and b['style'] else ""
                print(f"  [{i:02d}/{len(blocks):02d}] Synthesizing Block #{idx:02d}{tag_preview}...")
                content_to_synth = b.get("part", b["text"])
                raw_audio, sr = self.synthesize_single_block(content_to_synth, voice=speaker, cache_path=c_file)
                print(f"        ✓ Block #{idx:02d} synthesized in {time.time() - t0:.2f}s ({len(raw_audio)/sr:.2f}s audio)")
            return i - 1, {"block": b, "audio": raw_audio, "sr": sr}

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = [ex.submit(_synth_block, i, b) for i, b in enumerate(blocks, 1)]
            for fut in as_completed(futures):
                pos, item = fut.result()
                block_audios[pos] = item

        print(f"[Google TTS] All {len(blocks)} speech blocks ready in {time.time() - t_start_synth:.1f}s.")

        # -------------------------------------------------------------
        # Step 2: Assemble master timeline with Waterfall Anti-Overlap
        # -------------------------------------------------------------
        master_buffer = np.zeros(int((vid_dur + 5.0) * sample_rate), dtype=np.float32)
        timeline_sample = int(blocks[0]["start"] * sample_rate)
        placed_blocks: List[Dict[str, Any]] = []

        print("\n[Google TTS] Aligning speech blocks with anti-overlap anchoring...")
        min_gap_samples = int(0.08 * sample_rate)
        max_gap_samples = int(0.18 * sample_rate)

        for i, item in enumerate(block_audios):
            b = item["block"]
            audio = item["audio"]
            trimmed = trim_audio_silence(audio, pad_samples=int(0.02 * sample_rate))
            raw_dur = len(trimmed) / sample_rate

            orig_start_sample = int(b["start"] * sample_rate)

            # Determine available time window until next subtitle block
            if i + 1 < len(block_audios):
                next_start = block_audios[i + 1]["block"]["start"]
                avail_dur = max(next_start - b["start"], 0.8)
            else:
                avail_dur = max(vid_dur - b["start"], 1.5)

            # Compress tempo smoothly if narration naturally exceeds scene window
            if raw_dur > avail_dur * 1.05:
                speed_factor = min(raw_dur / avail_dur, 1.30)
                trimmed = adjust_audio_speed(trimmed, sample_rate, speed_factor)
                print(f"  [Block #{b['index']:02d}] Compressed {speed_factor:.2f}x to fit {avail_dur:.2f}s scene window")

            # Zero-silence continuous flow: clamp gap between blocks to maximum 0.18s
            if i == 0:
                act_start = int(0.02 * sample_rate)
            else:
                earliest_start = timeline_sample + min_gap_samples
                latest_start = timeline_sample + max_gap_samples
                if orig_start_sample > latest_start:
                    act_start = latest_start  # Pull forward to eliminate dead silence!
                else:
                    act_start = max(earliest_start, orig_start_sample)

            act_end = act_start + len(trimmed)
            if act_end > len(master_buffer):
                master_buffer = np.pad(master_buffer, (0, act_end - len(master_buffer) + sample_rate * 5))

            master_buffer[act_start:act_end] += trimmed
            timeline_sample = act_end

            t_s = round(act_start / sample_rate, 3)
            t_e = round(act_end / sample_rate, 3)
            placed_blocks.append({
                "index": b.get("index", i + 1),
                "start": t_s,
                "end": t_e,
                "text": b.get("text", "")
            })
            print(f"  [Block #{b['index']:02d}] Placed at {act_start/sample_rate:.2f}s -> {act_end/sample_rate:.2f}s (Target slot: {b['start']:.2f}s - {b['end']:.2f}s)")

        # Normalize audio peak
        peak_dur_samples = min(len(master_buffer), int(vid_dur * sample_rate))
        peak = np.max(np.abs(master_buffer[:peak_dur_samples]))
        if peak > 0:
            master_buffer = master_buffer / peak * 0.95

        master_wav = working_dir / f"master_google_{speaker.lower()}_{clean_model}_{srt_path.stem}.wav"
        sf.write(str(master_wav), master_buffer[:int(vid_dur * sample_rate)], sample_rate)

        # -------------------------------------------------------------
        # Step 3: Video Muxing (with BGM Sidechain Ducking)
        # -------------------------------------------------------------
        burn_subs = dubbed_srt and Path(dubbed_srt).exists()
        ass_path = None
        if burn_subs:
            ass_path = Path(dubbed_srt).with_suffix(".ass")
            try:
                margin_v = kwargs.get("margin_v")
                generate_synced_hinglish_ass(
                    master_wav=master_wav,
                    placed_blocks=placed_blocks,
                    output_ass=ass_path,
                    margin_v=margin_v,
                    run_whisper=True
                )
            except Exception as e:
                print(f"[Subtitles] Notice: Could not build synced ASS ({e}), burning direct ASS.")
                srt_to_ass(Path(dubbed_srt), ass_path, margin_v=margin_v, to_hinglish=True)

        needs_transcode = False
        try:
            probe_p = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,codec_name", "-of", "json", str(vid_path)],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5
            )
            probe_data = json.loads(probe_p.stdout.decode("utf-8"))
            vstream = probe_data.get("streams", [{}])[0]
            vw, vh = int(vstream.get("width", 0)), int(vstream.get("height", 0))
            vcodec = vstream.get("codec_name", "")
            if vw > 1080 or vh > 1920 or vcodec != "hevc":
                needs_transcode = True
        except Exception:
            needs_transcode = False

        v_filters = []
        if needs_transcode:
            v_filters.append("scale='if(gt(iw,ih),-2,min(1080,iw))':'if(gt(iw,ih),min(1080,ih),-2)':flags=lanczos")

        if burn_subs and ass_path.exists():
            try:
                rel_sub = str(ass_path.relative_to(Path.cwd())).replace("\\", "/")
            except ValueError:
                rel_sub = str(ass_path).replace("\\", "/").replace(":", "\\:")
            fonts_dir = Path.cwd() / "assets" / "fonts"
            rel_fonts = str(fonts_dir.relative_to(Path.cwd())).replace("\\", "/") if fonts_dir.exists() else ""
            if str(ass_path).endswith(".ass"):
                fonts_param = f":fontsdir='{rel_fonts}'" if rel_fonts else ""
                v_filters.append(f"ass='{rel_sub}'{fonts_param}")
            else:
                v_filters.append(f"subtitles='{rel_sub}'")
            print(f"[Subtitles] Burning subtitles into final video using libass filter...")

        if v_filters:
            v_filter_prefix = f"[0:v]{','.join(v_filters)}[vout];"
            v_map = "[vout]"
            v_codec = ["-c:v", "hevc_nvenc", "-preset", "p4", "-b:v", "3600k", "-maxrate", "5000k", "-bufsize", "8000k", "-tag:v", "hvc1"]
        else:
            v_filter_prefix = ""
            v_map = "0:v:0"
            v_codec = ["-c:v", "copy"]

        # Check for user-provided background audio directory
        assets_bg_dir = Path(__file__).resolve().parent.parent / "assets" / "background_audio"
        bg_audio_dir = assets_bg_dir if assets_bg_dir.exists() else (Path.cwd() / "background audio")
        bg_audio_file = None
        if bg_audio_dir.exists():
            exts = ('.mp3', '.wav', '.aac', '.m4a', '.ogg', '.flac')
            bg_files = [p for p in bg_audio_dir.iterdir() if p.is_file() and p.suffix.lower() in exts]
            if bg_files:
                bg_audio_file = random.choice(bg_files)
                print(f"[Google TTS] Selected background audio: {bg_audio_file.name} (Volume: 0.08, Looping)")

        audio_stem = sfx_path or bgm_path
        if audio_stem and Path(audio_stem).exists():
            stem_path = Path(audio_stem)
            stem_gain = max(0.50, min(float(bgm_volume), 1.50))
            is_sfx = "sfx" in stem_path.name.lower()

            extra_inputs = []
            if bg_audio_file:
                extra_inputs = ["-stream_loop", "-1", "-i", str(bg_audio_file)]

            if is_sfx:
                effective_sfx_gain = max(1.80, float(bgm_volume) * 2.20)
                print(f"\n[Google TTS] Mastering audio with BOOSTED SFX / Foley (Gain: {effective_sfx_gain:.2f}x) into {out_vid.name}...")
                if bg_audio_file:
                    filter_complex = (
                        f"{v_filter_prefix}[1:a]volume={effective_sfx_gain:.2f},highpass=f=40,acompressor=threshold=-20dB:ratio=2.5:attack=5:release=50[sfx];"
                        f"[2:a]volume=1.35,loudnorm=I=-13:TP=-0.5:LRA=7[voice];"
                        f"[3:a]volume=0.20[bgm];"
                        f"[sfx][voice][bgm]amix=inputs=3:weights=1.0 1.0 1.0:normalize=0[mixed];"
                        f"[mixed]alimiter=limit=0.98:attack=5:release=50[aout]"
                    )
                else:
                    filter_complex = (
                        f"{v_filter_prefix}[1:a]volume={effective_sfx_gain:.2f},highpass=f=40,alimiter=limit=0.95[sfx];"
                        f"[2:a]volume=1.35,loudnorm=I=-13:TP=-0.5:LRA=7[voice];"
                        f"[sfx][voice]amix=inputs=2:weights=1.0 1.0:normalize=0[mixed];"
                        f"[mixed]alimiter=limit=0.98:attack=5:release=50[aout]"
                    )
            else:
                print(f"\n[Google TTS] Mastering audio with preserved BGM & sidechain ducking into {out_vid.name}...")
                if bg_audio_file:
                    filter_complex = (
                        f"{v_filter_prefix}[1:a]volume={stem_gain:.2f}[orig_bgm];"
                        f"[3:a]volume=0.20[extra_bgm];"
                        f"[2:a]highpass=f=80,treble=g=3:f=3000,acompressor=threshold=-18dB:ratio=3.5:attack=5:release=60,loudnorm=I=-12:TP=-0.5:LRA=6,asplit=2[voice_sc][voice_mix];"
                        f"[orig_bgm][extra_bgm]amix=inputs=2:weights=1.0 1.0:normalize=0[combined_bgm];"
                        f"[combined_bgm][voice_sc]sidechaincompress=threshold=0.08:ratio=5:attack=20:release=250[ducked_bgm];"
                        f"[ducked_bgm][voice_mix]amix=inputs=2:weights=0.85 1.35:normalize=0[mixed];"
                        f"[mixed]alimiter=limit=0.99:attack=5:release=50[aout]"
                    )
                else:
                    filter_complex = (
                        f"{v_filter_prefix}[1:a]volume={stem_gain:.2f}[bgm];"
                        f"[2:a]highpass=f=80,treble=g=3:f=3000,acompressor=threshold=-18dB:ratio=3.5:attack=5:release=60,loudnorm=I=-12:TP=-0.5:LRA=6,asplit=2[voice_sc][voice_mix];"
                        f"[bgm][voice_sc]sidechaincompress=threshold=0.08:ratio=5:attack=20:release=250[ducked_bgm];"
                        f"[ducked_bgm][voice_mix]amix=inputs=2:weights=0.85 1.35:normalize=0[mixed];"
                        f"[mixed]alimiter=limit=0.99:attack=5:release=50[aout]"
                    )

            cmd_mux = [
                "ffmpeg", "-y",
                "-i", str(vid_path),
                "-i", str(stem_path),
                "-i", str(master_wav),
                *extra_inputs,
                "-filter_complex", filter_complex,
                "-map", v_map,
                "-map", "[aout]",
                *v_codec,
                "-c:a", "aac",
                "-b:a", "256k",
                "-shortest",
                str(out_vid)
            ]
        else:
            print(f"\n[Google TTS] Mastering clean isolated voiceover into {out_vid.name}...")
            cmd_mux = [
                "ffmpeg", "-y",
                "-i", str(vid_path),
                "-i", str(master_wav),
                "-filter_complex",
                f"{v_filter_prefix}[1:a]highpass=f=80,treble=g=3:f=3000,acompressor=threshold=-18dB:ratio=3.5:attack=5:release=60,loudnorm=I=-12:TP=-0.5:LRA=6,alimiter=limit=0.99:attack=5:release=50[voice]",
                "-map", v_map,
                "-map", "[voice]",
                *v_codec,
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                str(out_vid)
            ]

        res = subprocess.run(cmd_mux, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if res.returncode == 0:
            print(f"[Google TTS] SUCCESS! Dubbed video created: {out_vid}")
            return out_vid
        else:
            raise RuntimeError(f"FFmpeg mux error: {res.stderr.decode('utf-8', errors='replace')}")
