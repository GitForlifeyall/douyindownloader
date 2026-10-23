#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dubbing_studio/tts_omnivoice.py
===============================
OmniVoice (k2-fsa/OmniVoice) Studio TTS Engine & Video Dubber.
Features:
  - Local PyTorch CUDA inference (primary) with remote Gradio API fallback
  - Curated voice design profiles optimized for viral YouTube Shorts & TikTok
  - Zero-shot Voice Cloning support via audio reference
  - Waterfall anti-overlap timeline anchoring
  - Preserved background SFX & Foley ducking via Meta Demucs
"""

import os
import sys
import time
import io
import json
import shutil
import subprocess
import random
import threading
from pathlib import Path
from typing import Optional, Union, List, Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import soundfile as sf
import torch

from .env_loader import configure_runtime_environment
configure_runtime_environment()

from .tts_engine import load_srt_blocks, srt_to_ass, generate_synced_hinglish_ass


VOICE_PRESETS: Dict[str, Dict[str, Any]] = {
    "male_deep": {
        "instruct": "male, young adult, low pitch, indian accent",
        "name": "Male Deep Authority (Top Viral Shorts Hook)",
        "speed": 1.05,
        "gender": "Male / 男",
        "age": "Young Adult / 青年",
        "pitch": "Low Pitch / 低音调",
        "accent": "Indian Accent / 印度口音"
    },
    "male_energetic": {
        "instruct": "male, young adult, moderate pitch, indian accent",
        "name": "Male Energetic Creator (High-Pace Craftsmanship / Tutorial)",
        "speed": 1.10,
        "gender": "Male / 男",
        "age": "Young Adult / 青年",
        "pitch": "Moderate Pitch / 中音调",
        "accent": "Indian Accent / 印度口音"
    },
    "female_engaging": {
        "instruct": "female, young adult, moderate pitch, indian accent",
        "name": "Female Engaging Storyteller (Curiosity Hook / Story)",
        "speed": 1.05,
        "gender": "Female / 女",
        "age": "Young Adult / 青年",
        "pitch": "Moderate Pitch / 中音调",
        "accent": "Indian Accent / 印度口音"
    },
    "male_mature": {
        "instruct": "male, middle-aged, low pitch, indian accent",
        "name": "Male Master Craftsman (Industrial / Documentary)",
        "speed": 1.0,
        "gender": "Male / 男",
        "age": "Middle-aged / 中年",
        "pitch": "Low Pitch / 低音调",
        "accent": "Indian Accent / 印度口音"
    },
    "whisper": {
        "instruct": "male, young adult, whisper, indian accent",
        "name": "Dramatic ASMR Whisper",
        "speed": 1.0,
        "gender": "Male / 男",
        "age": "Young Adult / 青年",
        "pitch": "Moderate Pitch / 中音调",
        "accent": "Indian Accent / 印度口音"
    }
}

# Aliases
VOICE_ALIASES = {
    "deep": "male_deep",
    "authority": "male_deep",
    "male": "male_deep",
    "energetic": "male_energetic",
    "fast": "male_energetic",
    "creator": "male_energetic",
    "female": "female_engaging",
    "story": "female_engaging",
    "mature": "male_mature",
    "documentary": "male_mature",
    "asmr": "whisper",
}


def trim_audio_silence(audio: np.ndarray, threshold: float = 0.005, pad_samples: int = 480) -> np.ndarray:
    """Trim dead silence from audio start and end."""
    mask = np.abs(audio) > threshold
    if not np.any(mask):
        return audio
    first = max(0, int(np.argmax(mask) - pad_samples))
    last = min(len(audio), int(len(mask) - np.argmax(mask[::-1]) + pad_samples))
    return audio[first:last]


def adjust_audio_speed(audio: np.ndarray, sample_rate: int, speed: float) -> np.ndarray:
    """Smooth tempo compression using FFmpeg atempo filter."""
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


class OmniVoiceTTS:
    """
    OmniVoice Text-to-Speech Engine with Voice Design presets,
    local PyTorch GPU acceleration, waterfall timeline alignment, and sidechain ducking.
    """

    def __init__(
        self,
        default_voice: str = "male_deep",
        device: str = "cuda:0" if torch.cuda.is_available() else "cpu",
        use_local: bool = True
    ):
        self.default_voice = self._resolve_voice_key(default_voice)
        self.device = device
        self.use_local = use_local
        self.model = None
        self.sample_rate = 24000
        self.anchors = {}
        # Local PyTorch inference is not thread-safe; serialize it while allowing
        # the network-bound Gradio fallback to run concurrently.
        self._gen_lock = threading.Lock()

    def _resolve_voice_key(self, voice_name: str) -> str:
        v = (voice_name or "male_deep").lower().strip()
        return VOICE_ALIASES.get(v, v if v in VOICE_PRESETS else "male_deep")

    def _load_local_model(self):
        if self.model is not None:
            return
        print(f"[OmniVoice] Loading local model on {self.device} (float16)...")
        from omnivoice import OmniVoice
        self.model = OmniVoice.from_pretrained(
            "k2-fsa/OmniVoice",
            device_map=self.device,
            dtype=torch.float16 if "cuda" in self.device else torch.float32
        )
        print("[OmniVoice] Local model loaded successfully!")

    def _get_or_create_anchor(self, voice_key: str):
        if voice_key in self.anchors:
            return self.anchors[voice_key]

        project_root = Path(__file__).resolve().parent.parent
        ref_speaker = project_root / "reference_speaker.wav"

        anchor_map = {
            "male_deep": (
                ref_speaker if ref_speaker.exists() else Path("output/test_local_omnivoice_male_deep.wav"),
                # Audio cuts off after 'पूरी तरह'. If 'खराब हो जाएगी' is included, OmniVoice treats it as unfinished prompt speech and speaks it at the start of every block!
                "अगर सीधे चावल से शराब बनाने की कोशिश की, तो यह बदबूदार, खट्टी और पूरी तरह"
            ),
            "female_engaging": (
                Path("output/test_local_omnivoice_female_engaging.wav"),
                "नमस्ते दोस्तों, आज हम एक बहुत ही खास और अनोखी चीज देखने वाले हैं।"
            )
        }

        if voice_key in anchor_map:
            wav_path, ref_text = anchor_map[voice_key]
            if wav_path.exists():
                try:
                    print(f"[OmniVoice] Locking persistent speaker anchor for '{voice_key}' from {wav_path.name}...")
                    anchor_prompt = self.model.create_voice_clone_prompt(
                        ref_audio=str(wav_path),
                        ref_text=ref_text
                    )
                    self.anchors[voice_key] = anchor_prompt
                    return anchor_prompt
                except Exception as e:
                    print(f"[OmniVoice] Warning: Failed to create anchor prompt ({e}), falling back to instruct mode.")
        return None

    def synthesize_single_block(
        self,
        text: str,
        voice: str = "male_deep",
        lang: str = "Hindi",
        speed: float = 1.0,
        cache_path: Optional[Path] = None
    ) -> Tuple[np.ndarray, int]:
        if cache_path and cache_path.exists() and cache_path.stat().st_size > 500:
            data, sr = sf.read(str(cache_path))
            return data, sr

        voice_key = self._resolve_voice_key(voice)
        preset = VOICE_PRESETS.get(voice_key, VOICE_PRESETS["male_deep"])
        instruct_str = preset["instruct"]
        sp = speed if speed != 1.0 else preset["speed"]

        # Ensure deterministic seed for PyTorch
        torch.manual_seed(42)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(42)

        # Attempt 1: Local GPU model
        if self.use_local:
            try:
                with self._gen_lock:
                    self._load_local_model()
                    anchor_prompt = self._get_or_create_anchor(voice_key)
                    if anchor_prompt is not None:
                        audios = self.model.generate(
                            text=text,
                            voice_clone_prompt=anchor_prompt,
                            speed=sp
                        )
                    else:
                        audios = self.model.generate(
                            text=text,
                            language=lang,
                            instruct=instruct_str,
                            speed=sp
                        )
                if audios and len(audios) > 0:
                    raw_audio = audios[0]
                    if raw_audio.dtype != np.float32:
                        raw_audio = raw_audio.astype(np.float32)
                    if np.max(np.abs(raw_audio)) > 1.0:
                        raw_audio = raw_audio / 32768.0

                    if cache_path:
                        sf.write(str(cache_path), raw_audio, self.sample_rate)
                    return raw_audio, self.sample_rate
            except Exception as e:
                print(f"[OmniVoice] Local synthesis fallback notice ({e}). Trying Gradio client...")

        # Attempt 2: Gradio Client Fallback (Deterministic with fixed seed & random disabled)
        import gradio_client
        spaces = ['k2-fsa/OmniVoice', 'D3vShoaib/OmniVoice', 'archivartaunik/OmniVoice']
        for space in spaces:
            try:
                client = gradio_client.Client(space, httpx_kwargs={'timeout': 120.0})
                res = client.predict(
                    text,
                    lang,
                    32,
                    2.0,
                    True,
                    sp,
                    42,     # Fixed Seed to ensure voice consistency throughout the video
                    False,  # use_random_seed = False
                    True,
                    preset.get("gender", "Male / 男"),
                    preset.get("age", "Young Adult / 青年"),
                    preset.get("pitch", "Low Pitch / 低音调"),
                    "Auto",
                    preset.get("accent", "Indian Accent / 印度口音"),
                    "Auto",
                    api_name="/_design_fn"
                )
                temp_wav, _ = res
                if temp_wav and Path(temp_wav).exists():
                    if cache_path:
                        shutil.copy(temp_wav, str(cache_path))
                        data, sr = sf.read(str(cache_path))
                    else:
                        data, sr = sf.read(temp_wav)
                    return data, sr
            except Exception as ex:
                continue

        raise RuntimeError(f"OmniVoice synthesis failed for block: {text[:40]}")

    def synthesize_and_dub(
        self,
        dubbed_srt: Union[str, Path],
        original_video: Union[str, Path],
        final_video: Union[str, Path],
        voice: Optional[str] = None,
        lang: str = "Hindi",
        base_speed: float = 1.0,
        bgm_path: Optional[Union[str, Path]] = None,
        sfx_path: Optional[Union[str, Path]] = None,
        bgm_volume: float = 1.05,
        **kwargs
    ) -> Path:
        srt_path = Path(dubbed_srt)
        vid_path = Path(original_video)
        out_vid = Path(final_video)
        out_vid.parent.mkdir(parents=True, exist_ok=True)

        voice_key = self._resolve_voice_key(voice or self.default_voice)
        preset = VOICE_PRESETS.get(voice_key, VOICE_PRESETS["male_deep"])

        blocks = load_srt_blocks(srt_path)
        if not blocks:
            raise ValueError(f"No subtitle blocks found in {srt_path}")

        probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(vid_path)]
        vid_dur = float(subprocess.check_output(probe_cmd).decode().strip())

        print(f"\n==========================================")
        print(f"[OmniVoice] Synthesizing Studio Voiceover")
        print(f"Voice Profile: {preset['name']} ({voice_key})")
        print(f"Subtitles: {srt_path.name} ({len(blocks)} blocks)")
        print(f"Target Video: {vid_path.name} ({vid_dur:.2f}s)")
        print(f"Preserved BGM/SFX: {Path(bgm_path).name if bgm_path else 'None'} (Volume: {bgm_volume}x)")
        print(f"==========================================")

        sample_rate = self.sample_rate
        clean_slug = srt_path.stem.replace("_hindi", "").replace("_raw", "").replace("_dubbed", "")
        cache_dir = srt_path.parent / f"cache_omnivoice_{clean_slug}_{voice_key}"
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: Synthesize all blocks
        block_audios: List[Optional[Dict[str, Any]]] = [None] * len(blocks)
        t0_all = time.time()

        def _synth_block(i: int, b: Dict[str, Any]):
            idx = b["index"]
            c_file = cache_dir / f"block_{idx:02d}.wav"
            t0 = time.time()
            if c_file.exists() and c_file.stat().st_size > 500:
                raw_audio, sr = sf.read(str(c_file))
                print(f"  [{i:02d}/{len(blocks):02d}] Loaded from cache: Block #{idx:02d} ({len(raw_audio)/sr:.2f}s)")
            else:
                print(f"  [{i:02d}/{len(blocks):02d}] Synthesizing Block #{idx:02d} ({preset['name']})...")
                raw_audio, sr = self.synthesize_single_block(
                    text=b["text"],
                    voice=voice_key,
                    lang=lang,
                    speed=base_speed,
                    cache_path=c_file
                )
                print(f"        ✓ Block #{idx:02d} synthesized in {time.time() - t0:.2f}s ({len(raw_audio)/sr:.2f}s audio)")

            # Standardize channels
            if raw_audio.ndim > 1:
                raw_audio = np.mean(raw_audio, axis=1)

            return i - 1, {"block": b, "audio": raw_audio, "sr": sr}

        # Synthesize Block #1 first so it can be locked as the persistent speaker anchor
        pos0, item0 = _synth_block(1, blocks[0])
        block_audios[pos0] = item0
        if self.use_local and self.model is not None and voice_key not in self.anchors:
            c_file0 = cache_dir / f"block_{blocks[0]['index']:02d}.wav"
            if c_file0.exists():
                try:
                    b1_prompt = self.model.create_voice_clone_prompt(
                        ref_audio=str(c_file0),
                        ref_text=blocks[0]["text"]
                    )
                    self.anchors[voice_key] = b1_prompt
                    print(f"        ✓ Dynamically locked Block #1 as persistent speaker anchor for entire video consistency!")
                except Exception:
                    pass

        # Synthesize the remaining blocks in parallel (local GPU work is serialized
        # by self._gen_lock; the Gradio fallback runs concurrently).
        remaining = list(enumerate(blocks, 1))[1:]
        if remaining:
            max_workers = max(1, min(3, len(remaining)))
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                futures = [ex.submit(_synth_block, i, b) for i, b in remaining]
                for fut in as_completed(futures):
                    pos, item = fut.result()
                    block_audios[pos] = item

        print(f"[OmniVoice] All {len(blocks)} speech blocks ready in {time.time() - t0_all:.1f}s.")

        # Step 2: Master timeline alignment (Waterfall Anti-Overlap)
        master_buffer = np.zeros(int((vid_dur + 5.0) * sample_rate), dtype=np.float32)
        timeline_sample = int(blocks[0]["start"] * sample_rate)
        placed_blocks: List[Dict[str, Any]] = []

        for i, item in enumerate(block_audios):
            b = item["block"]
            audio = item["audio"]
            trimmed = trim_audio_silence(audio, pad_samples=int(0.02 * sample_rate))
            raw_dur = len(trimmed) / sample_rate
            orig_start_sample = int(b["start"] * sample_rate)

            if i + 1 < len(block_audios):
                next_start = block_audios[i + 1]["block"]["start"]
                avail_dur = max(next_start - b["start"], 0.8)
            else:
                avail_dur = max(vid_dur - b["start"], 1.5)

            if raw_dur > avail_dur * 1.04:
                speed_factor = min(raw_dur / avail_dur, 1.35)
                trimmed = adjust_audio_speed(trimmed, sample_rate, speed_factor)

            raw_gap_samples = orig_start_sample - timeline_sample
            min_pause = int(0.12 * sample_rate)
            max_pause = int(0.28 * sample_rate)

            if raw_gap_samples < min_pause:
                act_start = timeline_sample + min_pause
            elif raw_gap_samples <= max_pause:
                act_start = orig_start_sample
            else:
                prev_orig_end = block_audios[i - 1]["block"]["end"] if i > 0 else 0.0
                if (b["start"] - prev_orig_end) > 2.0:
                    act_start = timeline_sample + min(raw_gap_samples, int(0.45 * sample_rate))
                else:
                    act_start = timeline_sample + int(0.20 * sample_rate)

            act_end = act_start + len(trimmed)
            if act_end > len(master_buffer):
                master_buffer = np.pad(master_buffer, (0, act_end - len(master_buffer) + sample_rate * 5))

            master_buffer[act_start:act_end] += trimmed
            timeline_sample = act_end

            # Capture exact real-world placement [T_start, T_end]
            t_s = round(act_start / sample_rate, 3)
            t_e = round(act_end / sample_rate, 3)
            placed_blocks.append({
                "index": b.get("index", i + 1),
                "start": t_s,
                "end": t_e,
                "text": b.get("text", "")
            })

        # Normalize peak
        peak_dur_samples = min(len(master_buffer), int(vid_dur * sample_rate))
        peak = np.max(np.abs(master_buffer[:peak_dur_samples]))
        if peak > 0:
            master_buffer = master_buffer / peak * 0.98

        master_wav = srt_path.parent / f"master_omnivoice_{voice_key}_{srt_path.stem}.wav"
        sf.write(str(master_wav), master_buffer[:int(vid_dur * sample_rate)], sample_rate)

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

        # Check input video resolution & codec to always enforce max 1080p and HEVC
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
                print(f"[OmniVoice] Selected background audio: {bg_audio_file.name} (Volume: 0.08, Looping)")

        # Step 3: FFmpeg Muxing (with punchy speaker boost and dynamic sidechain ducking)
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
                print(f"\n[OmniVoice] Mastering audio with BOOSTED SFX / Foley (Gain: {effective_sfx_gain:.2f}x) into {out_vid.name}...")
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
                bgm_gain = max(0.18, min(float(bgm_volume) * 0.40, 1.20))
                print(f"\n[OmniVoice] Mastering audio with boosted voice & ducked BGM (Gain: {bgm_gain:.2f}x) into {out_vid.name}...")
                if bg_audio_file:
                    filter_complex = (
                        f"{v_filter_prefix}[1:a]volume={bgm_gain:.2f}[orig_bgm];"
                        f"[3:a]volume=0.20[extra_bgm];"
                        f"[2:a]highpass=f=80,treble=g=4:f=3200,acompressor=threshold=-18dB:ratio=4:attack=5:release=50,volume=1.50,loudnorm=I=-11:TP=-0.2:LRA=6,asplit=2[voice_sc][voice_mix];"
                        f"[orig_bgm][extra_bgm]amix=inputs=2:weights=1.0 1.0:normalize=0[combined_bgm];"
                        f"[combined_bgm][voice_sc]sidechaincompress=threshold=0.03:ratio=9:attack=15:release=220[ducked_bgm];"
                        f"[ducked_bgm][voice_mix]amix=inputs=2:weights=0.35 1.85:normalize=0[mixed];"
                        f"[mixed]alimiter=limit=0.98:attack=5:release=50[aout]"
                    )
                else:
                    filter_complex = (
                        f"{v_filter_prefix}[1:a]volume={bgm_gain:.2f}[bgm];[2:a]highpass=f=80,treble=g=4:f=3200,acompressor=threshold=-18dB:ratio=4:attack=5:release=50,volume=1.50,loudnorm=I=-11:TP=-0.2:LRA=6,asplit=2[voice_sc][voice_mix];[bgm][voice_sc]sidechaincompress=threshold=0.03:ratio=9:attack=15:release=220[ducked_bgm];[ducked_bgm][voice_mix]amix=inputs=2:weights=0.35 1.85:normalize=0[mixed];[mixed]alimiter=limit=0.98:attack=5:release=50[aout]"
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
            print(f"\n[OmniVoice] Mastering clean isolated voiceover into {out_vid.name}...")
            cmd_mux = [
                "ffmpeg", "-y",
                "-i", str(vid_path),
                "-i", str(master_wav),
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

        res = subprocess.run(cmd_mux, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if res.returncode == 0:
            print(f"[OmniVoice] SUCCESS! Dubbed video created: {out_vid}")
            return out_vid
        else:
            raise RuntimeError(f"FFmpeg mux error: {res.stderr.decode('utf-8', errors='replace')}")
