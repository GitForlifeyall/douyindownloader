#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dubbing_studio/tts.py
=====================
Sarvam AI Bulbul v3 Text-to-Speech Engine & Video Dubber.
Delivers ultra-realistic, native-sounding conversational Hindi and Hinglish voiceovers.
Retains Kokoro TTS for offline/multilingual synthesis.
"""

import io
import os
import sys
import json
import time
import base64
import subprocess
import random
import threading
from pathlib import Path
from typing import Optional, Union, List, Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import soundfile as sf
from sarvamai import SarvamAI

from .env_loader import configure_runtime_environment
configure_runtime_environment()

from .key_pool import (
    get_active_sarvam_keys,
    mark_sarvam_key_dead,
    is_sarvam_dead_error,
    mask_key,
)
from .tts_engine import KokoroTTS, load_srt_blocks, parse_time, srt_to_ass, generate_synced_hinglish_ass


def trim_audio_silence(audio: np.ndarray, threshold: float = 0.005, pad_samples: int = 960) -> np.ndarray:
    """Trim digital zero-padding and dead silence from start and end of audio clip."""
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


def get_sarvam_api_keys() -> List[str]:
    """Retrieve all active, non-exhausted Sarvam API keys from the runtime pool."""
    return get_active_sarvam_keys()


def generate_sarvam_tts(
    text: str,
    output_path: str = "output_audio.mp3",
    speaker: str = "shubh",
    pace: float = 1.0,
    speech_sample_rate: int = 48000,
    language_code: str = "hi-IN",
    model: str = "bulbul:v3",
    api_key: Optional[str] = None,
    **kwargs
) -> str:
    """
    Generates ultra-realistic Hindi/Hinglish TTS using Sarvam AI's Bulbul v3 model.
    Optimized for YouTube Shorts & Movie Recaps.
    """
    key = api_key
    if not key:
        keys = get_active_sarvam_keys()
        key = keys[0] if keys else None
    if not key:
        raise ValueError(
            "SARVAM_API_KEY environment variable is missing or all keys exhausted! "
            "Please check SARVAM_API_KEY or SARVAM_API_KEYS in your .env file."
        )

    client = SarvamAI(api_subscription_key=key)
    lang = kwargs.get("target_language_code", language_code)

    response = client.text_to_speech.convert(
        text=text,
        language_code=lang,
        model=model,
        speaker=speaker,
        pace=float(pace),
        speech_sample_rate=speech_sample_rate
    )

    raw_audio = response.audios[0] if hasattr(response, "audios") and response.audios else response

    if isinstance(raw_audio, str):
        try:
            audio_bytes = base64.b64decode(raw_audio)
        except Exception:
            audio_bytes = raw_audio.encode("utf-8")
    elif isinstance(raw_audio, bytes):
        audio_bytes = raw_audio
    else:
        audio_bytes = bytes(raw_audio)

    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "wb") as f:
        f.write(audio_bytes)

    return str(output_path)


class SarvamTTS:
    """
    Production-grade Sarvam AI Dubbing Engine for YouTube Shorts & Movie Recaps.
    Features automated Round-Robin multi-key load balancing and instant failover.
    Eliminates awkward silences between lines using intelligent timeline anchoring,
    dynamic pacing, and seamless narrative streaming.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_keys: Optional[List[str]] = None,
        default_speaker: str = "shubh",
        model: str = "bulbul:v3"
    ):
        active_pool = get_active_sarvam_keys()
        if api_keys:
            self.api_keys = [k.strip() for k in api_keys if k.strip() in active_pool]
            if not self.api_keys:
                self.api_keys = active_pool
        elif api_key:
            self.api_keys = [api_key.strip()]
        else:
            self.api_keys = active_pool

        if not self.api_keys:
            raise ValueError(
                "No active Sarvam API key configured! Please set SARVAM_API_KEY or "
                "SARVAM_API_KEYS in your .env file."
            )
        self.current_key_idx = 0
        self._key_lock = threading.Lock()
        self.default_speaker = default_speaker
        self.model = model

    def get_current_key(self) -> str:
        with self._key_lock:
            active_pool = set(get_active_sarvam_keys())
            self.api_keys = [k for k in self.api_keys if k in active_pool]
            if not self.api_keys:
                self.api_keys = list(active_pool)
            if not self.api_keys:
                raise RuntimeError("All Sarvam API keys in the runtime pool have been exhausted.")
            return self.api_keys[self.current_key_idx % len(self.api_keys)]

    def rotate_key(self, dead_key: Optional[str] = None, reason: str = ""):
        with self._key_lock:
            if dead_key:
                mark_sarvam_key_dead(dead_key, reason=reason)
                if dead_key in self.api_keys:
                    self.api_keys.remove(dead_key)
            if self.api_keys:
                self.current_key_idx = (self.current_key_idx + 1) % len(self.api_keys)
                new_idx = self.current_key_idx
                masked_new = mask_key(self.api_keys[new_idx])
                if reason and not dead_key:
                    print(f"[Sarvam AI] Round-robin rotated to Key #{new_idx + 1} of {len(self.api_keys)} ({masked_new}) - {reason}")
                elif not dead_key:
                    print(f"[Sarvam AI] Round-robin rotated to Key #{new_idx + 1} of {len(self.api_keys)} ({masked_new})")

    def synthesize_and_dub(
        self,
        dubbed_srt: Union[str, Path],
        original_video: Union[str, Path],
        final_video: Optional[Union[str, Path]] = None,
        voice: Optional[str] = None,
        lang: str = "Hindi",
        base_speed: float = 1.0,
        mode: str = "slice",
        bgm_path: Optional[Union[str, Path]] = None,
        sfx_path: Optional[Union[str, Path]] = None,
        bgm_volume: float = 1.0,
        work_dir: Optional[Union[str, Path]] = None,
        **kwargs
    ) -> Path:
        """
        Synthesize audio using Sarvam AI Bulbul v3 with block-by-block precision.
        """
        srt_path = Path(dubbed_srt)
        vid_path = Path(original_video)
        out_vid = Path(final_video) if final_video else srt_path.parent / f"{srt_path.stem}_dubbed.mp4"
        working_dir = Path(work_dir) if work_dir else srt_path.parent
        working_dir.mkdir(parents=True, exist_ok=True)

        speaker = voice if voice and not voice.startswith("am_") and not voice.startswith("hm_") else self.default_speaker

        print(f"\n==========================================")
        print(f"[Sarvam AI] Synthesizing Studio Voiceover Track")
        print(f"Model: {self.model} | Speaker: {speaker} | Mode: batch-by-batch (slice)")
        print(f"Keys Pool: {len(self.api_keys)} Sarvam Key(s) active (Round-Robin enabled)")
        print(f"Subtitles: {srt_path.name}")
        print(f"Target Video: {out_vid.name}")
        print(f"Working Dir: {working_dir.name}")
        print(f"==========================================")

        if mode in ("single_narrator", "narrator", "continuous"):
            from dub_single_narrator import run_single_narrator_pipeline
            result_path = run_single_narrator_pipeline(
                video_path=str(vid_path),
                speaker=speaker,
                pace=base_speed,
                target_end_margin=kwargs.get("margin", 0.35),
                force=kwargs.get("force", False),
                engine="sarvam",
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

        master_wav = working_dir / f"master_sarvam_{srt_path.stem}.wav"
        master_mp3 = working_dir / f"master_sarvam_{srt_path.stem}.mp3"
        sample_rate = 48000
        t_start_total = time.time()

        # Always enforce batch-by-batch (sliced) synthesis to ensure precise timeline alignment
        print(f"[Sarvam AI] Engaging High-Fidelity Sliced Assembly with Dynamic Gap Closing ({len(blocks)} blocks)...")
        temp_audio_dir = working_dir / "temp_sarvam_slices"
        temp_audio_dir.mkdir(parents=True, exist_ok=True)

        probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(vid_path)]
        try:
            vid_dur = float(subprocess.check_output(probe_cmd).decode().strip())
        except Exception:
            vid_dur = max(b["end"] for b in blocks)

        last_end = max(b["end"] for b in blocks)
        buffer_len = int((max(last_end, vid_dur) + 15.0) * sample_rate)
        master_buffer = np.zeros(buffer_len, dtype=np.float32)

        timeline_sample = int(blocks[0]["start"] * sample_rate)
        min_gap_samples = int(0.08 * sample_rate)
        max_gap_samples = int(0.18 * sample_rate)

        successful_blocks = 0

        # ---- Phase 1: Parallel synthesis of all blocks (network-bound) ----
        def _synth_block(i: int, b: Dict[str, Any]):
            text = b["text"].strip()
            if not text:
                return i, b, None, True, ""
            # Natural Sarvam Bulbul v3 Hindi speaking cadence (1.00x - 1.05x)
            pace = 1.05 if i == len(blocks) else 1.00
            slice_mp3 = temp_audio_dir / f"block_{b['index']:03d}.mp3"
            last_err = ""
            max_block_attempts = max(len(self.api_keys) * 2, 4)
            for attempt in range(max_block_attempts):
                if not self.api_keys and not get_active_sarvam_keys():
                    last_err = "All Sarvam API keys in the runtime pool have been exhausted."
                    break
                try:
                    active_key = self.get_current_key()
                except Exception as e:
                    last_err = str(e)
                    break
                try:
                    generate_sarvam_tts(
                        text=text,
                        output_path=str(slice_mp3),
                        speaker=speaker,
                        pace=pace,
                        speech_sample_rate=sample_rate,
                        model=self.model,
                        language_code="hi-IN",
                        api_key=active_key
                    )
                    # Round-robin: advance to next key to evenly balance usage
                    with self._key_lock:
                        if self.api_keys:
                            self.current_key_idx = (self.current_key_idx + 1) % len(self.api_keys)
                    return i, b, slice_mp3, True, ""
                except Exception as e:
                    last_err = str(e)
                    if is_sarvam_dead_error(last_err):
                        # Evict dead key immediately so no other block or worker calls it
                        self.rotate_key(dead_key=active_key, reason=last_err[:80])
                        continue
                    else:
                        self.rotate_key(reason=f"error ({last_err[:60]})")
                        time.sleep(0.4)
            return i, b, slice_mp3, False, last_err

        max_workers = max(1, min(8, len(self.api_keys) * 2))
        print(f"[Sarvam AI] Synthesizing {len(blocks)} blocks in parallel ({max_workers} workers)...")
        synth_results: List[Optional[Tuple[int, Dict[str, Any], Optional[Path], bool, str]]] = [None] * len(blocks)
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = [ex.submit(_synth_block, i, b) for i, b in enumerate(blocks, 1)]
            for fut in as_completed(futures):
                i, b, slice_mp3, ok, err = fut.result()
                synth_results[i - 1] = (i, b, slice_mp3, ok, err)

        # ---- Phase 2: Sequential timeline assembly (order-dependent) ----
        placed_blocks: List[Dict[str, Any]] = []
        for i, b, slice_mp3, success, last_err in synth_results:
            if not b["text"].strip():
                continue

            if not success:
                print(f"[Sarvam TTS] Error on block #{b['index']} after testing all {len(self.api_keys)} keys: {last_err}")
                if any(q in (last_err or "") for q in ["402", "insufficient_quota_error", "No credits available"]):
                    raise RuntimeError(
                        f"\n\n===================================================================\n"
                        f"[Sarvam AI Quota Exhausted] All configured Sarvam API keys ({len(self.api_keys)} keys) ran out of credits!\n"
                        f"Last error: {last_err}\n"
                        f"Please recharge your balance at https://dashboard.sarvam.ai or update SARVAM_API_KEYS in .env\n"
                        f"==================================================================="
                    )
                continue

            audio_data, in_sr = sf.read(str(slice_mp3))
            if len(audio_data.shape) > 1:
                audio_data = np.mean(audio_data, axis=1)

            trimmed = trim_audio_silence(audio_data)
            orig_start_sample = int(b["start"] * sample_rate)

            # Determine available time window until next subtitle block or end of video
            if i < len(blocks):
                avail_dur = max(blocks[i]["start"] - b["start"], 0.8)
            else:
                avail_dur = max(vid_dur - b["start"] - 0.8, 1.5)

            raw_dur = len(trimmed) / sample_rate
            if raw_dur > avail_dur * 0.98:
                speed_factor = min(raw_dur / (avail_dur * 0.95), 1.28)
                trimmed = adjust_audio_speed(trimmed, sample_rate, speed_factor)
                print(f"  [Block #{b['index']:02d}] Compressed {speed_factor:.2f}x to fit {avail_dur:.2f}s scene window")

            # Visual Anchor Sync: speech triggers precisely with the on-screen video cut
            if i == 1:
                act_start = orig_start_sample
            else:
                earliest_start = timeline_sample + min_gap_samples
                act_start = max(earliest_start, orig_start_sample)

            act_end = act_start + len(trimmed)
            if act_end > len(master_buffer):
                master_buffer = np.pad(master_buffer, (0, act_end - len(master_buffer) + sample_rate * 10))

            master_buffer[act_start:act_end] += trimmed
            timeline_sample = act_end
            successful_blocks += 1

            t_s = round(act_start / sample_rate, 3)
            t_e = round(act_end / sample_rate, 3)
            placed_blocks.append({
                "index": b.get("index", i),
                "start": t_s,
                "end": t_e,
                "text": b.get("text", "")
            })

            print(f"  [{i}/{len(blocks)}] Block #{b['index']} placed at {act_start/sample_rate:.2f}s -> {act_end/sample_rate:.2f}s")

        if successful_blocks == 0 or timeline_sample == 0:
            raise RuntimeError(
                "[Sarvam AI Error] No audio blocks were successfully synthesized. Check API key, network, and quota."
            )

        # Normalize peak
        peak_dur_samples = min(len(master_buffer), int(vid_dur * sample_rate))
        audio_slice = master_buffer[:peak_dur_samples]
        if len(audio_slice) > 0:
            peak = float(np.max(np.abs(audio_slice)))
            if peak > 0:
                master_buffer = master_buffer / peak * 0.98

        sf.write(str(master_wav), master_buffer[:int(vid_dur * sample_rate)], sample_rate)
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(master_wav), "-b:a", "192k", str(master_mp3)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        print(f"[Sarvam TTS] Voiceover mastered in {time.time() - t_start_total:.1f}s -> {master_mp3.name}")
        print(f"[Sarvam TTS] Muxing master voiceover into final video...")
        # Check if subtitles should be burned into final video
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

        # Check input video resolution & codec
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
                print(f"[Sarvam TTS] Selected background audio: {bg_audio_file.name} (Volume: 0.20, Looping)")

        # Video Muxing: Prioritize punchy isolated SFX (Foley) over music
        audio_stem = sfx_path or bgm_path
        if audio_stem and Path(audio_stem).exists():
            stem_path = Path(audio_stem)
            stem_gain = max(0.50, min(float(bgm_volume), 1.50))
            is_sfx = "sfx" in stem_path.name.lower()

            extra_inputs = []
            if bg_audio_file:
                extra_inputs = ["-stream_loop", "-1", "-i", str(bg_audio_file)]

            if is_sfx:
                # Substantially boost SFX presence (Foley: kicks, splashes, frying, clinking)
                effective_sfx_gain = max(1.80, float(bgm_volume) * 2.20)
                print(f"[Sarvam TTS] Mastering punchy voiceover with BOOSTED SFX / Foley (Gain: {effective_sfx_gain:.2f}x) into {out_vid.name}...")
                if bg_audio_file:
                    filter_complex = (
                        f"{v_filter_prefix}[1:a]volume={effective_sfx_gain:.2f},highpass=f=40,acompressor=threshold=-20dB:ratio=2.5:attack=5:release=50[sfx];"
                        f"[2:a]volume=1.30,loudnorm=I=-13:TP=-0.5:LRA=7[voice];"
                        f"[3:a]volume=0.20[bgm];"
                        f"[sfx][voice][bgm]amix=inputs=3:weights=1.0 1.0 1.0:normalize=0[mixed];"
                        f"[mixed]alimiter=limit=0.98:attack=5:release=50[aout]"
                    )
                else:
                    filter_complex = (
                        f"{v_filter_prefix}[1:a]volume={effective_sfx_gain:.2f},highpass=f=40,acompressor=threshold=-20dB:ratio=2.5:attack=5:release=50[sfx];"
                        f"[2:a]volume=1.30,loudnorm=I=-13:TP=-0.5:LRA=7[voice];"
                        f"[sfx][voice]amix=inputs=2:weights=1.0 1.0:normalize=0[mixed];"
                        f"[mixed]alimiter=limit=0.98:attack=5:release=50[aout]"
                    )
            else:
                print(f"[Sarvam TTS] Mastering punchy voiceover with audible BGM (Gain: {stem_gain:.2f}x, dynamic ducking) into {out_vid.name}...")
                if bg_audio_file:
                    filter_complex = (
                        f"{v_filter_prefix}[1:a]volume={stem_gain:.2f}[orig_bgm];"
                        f"[3:a]volume=0.20[extra_bgm];"
                        f"[2:a]volume=1.35,loudnorm=I=-13:TP=-0.5:LRA=7,asplit=2[voice_sc][voice_mix];"
                        f"[orig_bgm][extra_bgm]amix=inputs=2:weights=1.0 1.0:normalize=0[combined_bgm];"
                        f"[combined_bgm][voice_sc]sidechaincompress=threshold=0.10:ratio=3.5:attack=15:release=250[ducked_bgm];"
                        f"[ducked_bgm][voice_mix]amix=inputs=2:weights=1.0 1.0:normalize=0[mixed];"
                        f"[mixed]alimiter=limit=0.98:attack=5:release=50[aout]"
                    )
                else:
                    filter_complex = (
                        f"{v_filter_prefix}[1:a]volume={stem_gain:.2f}[bgm];"
                        f"[2:a]volume=1.35,loudnorm=I=-13:TP=-0.5:LRA=7,asplit=2[voice_sc][voice_mix];"
                        f"[bgm][voice_sc]sidechaincompress=threshold=0.10:ratio=3.5:attack=15:release=250[ducked_bgm];"
                        f"[ducked_bgm][voice_mix]amix=inputs=2:weights=1.0 1.0:normalize=0[mixed];"
                        f"[mixed]alimiter=limit=0.98:attack=5:release=50[aout]"
                    )

            cmd_mux = [
                "ffmpeg", "-y",
                "-i", str(vid_path),
                "-i", str(stem_path),
                "-i", str(master_mp3),
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
            print(f"[Sarvam TTS] Mastering loud & clean voiceover into {out_vid.name}...")
            cmd_mux = [
                "ffmpeg", "-y",
                "-i", str(vid_path),
                "-i", str(master_mp3),
                "-filter_complex",
                f"{v_filter_prefix}[1:a]highpass=f=80,treble=g=4:f=3200,acompressor=threshold=-18dB:ratio=4:attack=5:release=50,volume=1.55,loudnorm=I=-11:TP=-0.2:LRA=6,alimiter=limit=0.98:attack=5:release=50[voice]",
                "-map", v_map,
                "-map", "[voice]",
                *v_codec,
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                str(out_vid)
            ]
        res_mux = subprocess.run(cmd_mux, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res_mux.returncode == 0:
            print(f"\n[Sarvam TTS] SUCCESS! Dubbed video created: {out_vid}")
            return out_vid
        else:
            raise RuntimeError(f"FFmpeg error remuxing video: {res_mux.returncode}")
