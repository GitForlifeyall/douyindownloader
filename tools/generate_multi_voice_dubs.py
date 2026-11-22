#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_multi_voice_dubs.py
============================
Generates 7 distinct voiceover comparisons for the Osmanthus Honey video:
1. Hindi - Google Cloud Chirp (hi-IN-Chirp3-HD-Orus)
2. Hindi - OmniVoice (male_deep)
3. English - Sarvam AI Bulbul v3 (shubh)
4. English - Sarvam AI Bulbul v3 (arvind)
5. English - Sarvam AI Bulbul v3 (amartya)
6. English - OmniVoice (male_deep)
7. English - Google Cloud Chirp (en-US-Chirp3-HD-Fenrir)

All placed strictly in output/final_videos/ with clean names.
Preserves Foley SFX and BGM stems with balanced sidechain ducking.
"""

import os
import sys
import time
import io
import json
import base64
import requests
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import numpy as np
import soundfile as sf
import torch

from dubbing_studio.env_loader import configure_runtime_environment
configure_runtime_environment()

from dubbing_studio.tts import SarvamTTS, generate_sarvam_tts
from dubbing_studio.tts_omnivoice import OmniVoiceTTS
from dubbing_studio.tts_engine import load_srt_blocks


def trim_audio_silence(audio: np.ndarray, threshold: float = 0.005, pad_samples: int = 480) -> np.ndarray:
    mask = np.abs(audio) > threshold
    if not np.any(mask):
        return audio
    first = max(0, int(np.argmax(mask) - pad_samples))
    last = min(len(audio), int(len(mask) - np.argmax(mask[::-1]) + pad_samples))
    return audio[first:last]


def adjust_audio_speed(audio: np.ndarray, sample_rate: int, speed: float) -> np.ndarray:
    if abs(speed - 1.0) < 0.03:
        return audio

    temp_in = io.BytesIO()
    sf.write(temp_in, audio, sample_rate, format="WAV")
    wav_bytes = temp_in.getvalue()

    safe_speed = max(0.80, min(speed, 1.45))
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


def synthesize_google_chirp_block(
    text: str,
    api_key: str,
    voice_name: str,
    lang_code: str,
    speaking_rate: float = 1.10
) -> bytes:
    url = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={api_key}"
    payload = {
        "input": {"text": text},
        "voice": {"languageCode": lang_code, "name": voice_name},
        "audioConfig": {"audioEncoding": "MP3", "speakingRate": speaking_rate}
    }
    resp = requests.post(url, json=payload, timeout=20)
    if resp.status_code == 200:
        return base64.b64decode(resp.json()["audioContent"])
    raise RuntimeError(f"Google Cloud Chirp Error ({resp.status_code}): {resp.text[:200]}")


def assemble_waterfall_timeline(
    blocks: List[Dict[str, Any]],
    block_audios: List[np.ndarray],
    sample_rate: int,
    total_duration: float
) -> np.ndarray:
    master_buffer = np.zeros(int((total_duration + 5.0) * sample_rate), dtype=np.float32)
    timeline_sample = int(blocks[0]["start"] * sample_rate)

    for i, (b, raw_audio) in enumerate(zip(blocks, block_audios)):
        trimmed = trim_audio_silence(raw_audio, pad_samples=int(0.02 * sample_rate))
        raw_dur = len(trimmed) / sample_rate

        orig_start_sample = int(b["start"] * sample_rate)

        if i + 1 < len(blocks):
            next_start = blocks[i + 1]["start"]
            avail_dur = max(next_start - b["start"], 0.8)
        else:
            avail_dur = max(total_duration - b["start"], 1.5)

        if raw_dur > avail_dur * 1.05:
            speed_factor = min(raw_dur / avail_dur, 1.35)
            trimmed = adjust_audio_speed(trimmed, sample_rate, speed_factor)

        gap_sec = b["start"] - (timeline_sample / sample_rate)
        if gap_sec < 0.04:
            act_start = max(timeline_sample + int(0.04 * sample_rate), orig_start_sample - int(0.10 * sample_rate))
        else:
            act_start = max(orig_start_sample, timeline_sample + int(0.02 * sample_rate))

        act_end = act_start + len(trimmed)
        if act_end > len(master_buffer):
            master_buffer = np.pad(master_buffer, (0, act_end - len(master_buffer) + sample_rate * 5))

        master_buffer[act_start:act_end] += trimmed
        timeline_sample = act_end

    peak = np.max(np.abs(master_buffer))
    if peak > 0:
        master_buffer = master_buffer / peak * 0.95

    return master_buffer[:int(total_duration * sample_rate)]


def mux_video_with_audio_and_bgm(
    video_path: Path,
    voice_wav_path: Path,
    bgm_path: Path,
    output_video_path: Path,
    bgm_gain: float = 1.05
):
    print(f"[FFmpeg Muxing] Assembling final video into {output_video_path.name}...")
    output_video_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(bgm_path),
        "-i", str(voice_wav_path),
        "-filter_complex",
        f"[1:a]volume={bgm_gain:.2f}[bgm];[2:a]volume=1.35,loudnorm=I=-13:TP=-0.5:LRA=7,asplit=2[voice_sc][voice_mix];[bgm][voice_sc]sidechaincompress=threshold=0.10:ratio=3.5:attack=15:release=250[ducked_bgm];[ducked_bgm][voice_mix]amix=inputs=2:weights=1.0 1.0:normalize=0[mixed];[mixed]alimiter=limit=0.98:attack=5:release=50[aout]",
        "-map", "0:v:0",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "256k",
        "-shortest",
        str(output_video_path)
    ]
    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg muxing failed with code {res.returncode}")
    print(f"  ✓ Created: {output_video_path.name} ({output_video_path.stat().st_size / 1024 / 1024:.2f} MB)")


def main():
    root = Path.cwd()
    clean_video = root / "output/clean_videos/道可道 - 恭喜你成功制作出桂花蜜_clean.mp4"
    bgm_stem = root / "output/audio_stems/stems_道可道 - 恭喜你成功制作出桂花蜜/no_vocals.wav"
    hindi_srt = root / "output/subtitles/道可道 - 恭喜你成功制作出桂花蜜_hindi.srt"
    english_srt = root / "output/subtitles/道可道 - 恭喜你成功制作出桂花蜜_english.srt"

    final_dir = root / "output/final_videos"
    stems_dir = root / "output/audio_stems"
    final_dir.mkdir(parents=True, exist_ok=True)
    stems_dir.mkdir(parents=True, exist_ok=True)

    if not clean_video.exists():
        raise FileNotFoundError(f"Clean video missing: {clean_video}")
    if not bgm_stem.exists():
        raise FileNotFoundError(f"BGM stem missing: {bgm_stem}")
    if not hindi_srt.exists():
        raise FileNotFoundError(f"Hindi SRT missing: {hindi_srt}")
    if not english_srt.exists():
        raise FileNotFoundError(f"English SRT missing: {english_srt}")

    probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(clean_video)]
    vid_dur = float(subprocess.check_output(probe_cmd).decode().strip())

    hindi_blocks = load_srt_blocks(hindi_srt)
    english_blocks = load_srt_blocks(english_srt)

    gcloud_key = os.getenv("GOOGLE_TTS_API_KEY") or os.getenv("GEMINI_API_KEY")
    sarvam_keys = [k.strip() for k in os.getenv("SARVAM_API_KEYS", "").split(",") if k.strip()]
    if not sarvam_keys and os.getenv("SARVAM_API_KEY"):
        sarvam_keys = [os.getenv("SARVAM_API_KEY").strip()]

    print("\n" + "=" * 65)
    print(" [Multi-Voice Studio] GENERATING 7 COMPARISON DUBS")
    print(f" Video Duration   : {vid_dur:.2f}s")
    print(f" Clean Video Source: {clean_video.name}")
    print(f" Background SFX    : {bgm_stem.name}")
    print(f" Output Directory  : {final_dir}")
    print("=" * 65 + "\n")

    # -------------------------------------------------------------
    # 1. Hindi - Google Cloud Chirp (hi-IN-Chirp3-HD-Orus)
    # -------------------------------------------------------------
    out_hindi_chirp = final_dir / "道可道 - 恭喜你成功制作出桂花蜜_hindi_chirp_dubbed.mp4"
    if not out_hindi_chirp.exists() or out_hindi_chirp.stat().st_size < 100000:
        print("\n--- [1/7] Dubbing Hindi: Google Cloud Chirp (hi-IN-Chirp3-HD-Orus) ---")
        cache_dir = stems_dir / "cache_chirp_hindi"
        cache_dir.mkdir(parents=True, exist_ok=True)
        block_audios = []
        sample_rate = 24000
        for i, b in enumerate(hindi_blocks, 1):
            w_file = cache_dir / f"block_{b['index']:02d}.wav"
            if not w_file.exists():
                audio_bytes = synthesize_google_chirp_block(
                    b["text"], gcloud_key, "hi-IN-Chirp3-HD-Orus", "hi-IN", speaking_rate=1.12
                )
                mp3_f = cache_dir / f"block_{b['index']:02d}.mp3"
                mp3_f.write_bytes(audio_bytes)
                subprocess.run(["ffmpeg", "-y", "-i", str(mp3_f), "-ar", str(sample_rate), "-ac", "1", str(w_file)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                mp3_f.unlink(missing_ok=True)
            arr, sr = sf.read(str(w_file))
            block_audios.append(arr)
            print(f"  [Chirp Hindi] Block #{b['index']:02d} ready: {len(arr)/sample_rate:.2f}s")

        master_wav = stems_dir / "master_hindi_chirp.wav"
        master_buffer = assemble_waterfall_timeline(hindi_blocks, block_audios, sample_rate, vid_dur)
        sf.write(str(master_wav), master_buffer, sample_rate)
        mux_video_with_audio_and_bgm(clean_video, master_wav, bgm_stem, out_hindi_chirp)
    else:
        print(f"[1/7] Existing Hindi Chirp video found: {out_hindi_chirp.name}")

    # -------------------------------------------------------------
    # 2. Hindi - OmniVoice (male_deep)
    # -------------------------------------------------------------
    out_hindi_omni = final_dir / "道可道 - 恭喜你成功制作出桂花蜜_hindi_omni_dubbed.mp4"
    if not out_hindi_omni.exists() or out_hindi_omni.stat().st_size < 100000:
        print("\n--- [2/7] Dubbing Hindi: OmniVoice (male_deep) ---")
        omni = OmniVoiceTTS(default_voice="male_deep")
        omni.synthesize_and_dub(
            dubbed_srt=hindi_srt,
            original_video=clean_video,
            final_video=out_hindi_omni,
            voice="male_deep",
            lang="Hindi",
            bgm_path=bgm_stem,
            bgm_volume=1.05
        )
    else:
        print(f"[2/7] Existing Hindi Omni video found: {out_hindi_omni.name}")

    # -------------------------------------------------------------
    # 3. English - Sarvam AI (shubh)
    # -------------------------------------------------------------
    sarvam_speakers = ["shubh", "aditya", "kabir"]
    for idx_spk, spk in enumerate(sarvam_speakers, start=3):
        out_eng_sarvam = final_dir / f"道可道 - 恭喜你成功制作出桂花蜜_english_sarvam_{spk}_dubbed.mp4"
        if not out_eng_sarvam.exists() or out_eng_sarvam.stat().st_size < 100000:
            print(f"\n--- [{idx_spk}/7] Dubbing English: Sarvam AI Bulbul v3 (speaker: {spk}) ---")
            cache_dir = stems_dir / f"cache_sarvam_en_{spk}"
            cache_dir.mkdir(parents=True, exist_ok=True)
            block_audios = []
            sample_rate = 48000
            for i, b in enumerate(english_blocks, 1):
                w_file = cache_dir / f"block_{b['index']:02d}.wav"
                if not w_file.exists():
                    mp3_f = cache_dir / f"block_{b['index']:02d}.mp3"
                    success = False
                    last_err = ""
                    for k in sarvam_keys:
                        try:
                            generate_sarvam_tts(
                                text=b["text"],
                                output_path=str(mp3_f),
                                speaker=spk,
                                language_code="en-IN",
                                pace=1.05,
                                api_key=k
                            )
                            success = True
                            break
                        except Exception as e:
                            last_err = str(e)
                            continue
                    if not success:
                        raise RuntimeError(f"Sarvam AI failed for block #{b['index']}: {last_err}")
                    subprocess.run(["ffmpeg", "-y", "-i", str(mp3_f), "-ar", str(sample_rate), "-ac", "1", str(w_file)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    mp3_f.unlink(missing_ok=True)
                arr, sr = sf.read(str(w_file))
                block_audios.append(arr)
                print(f"  [Sarvam English {spk}] Block #{b['index']:02d} ready: {len(arr)/sample_rate:.2f}s")

            master_wav = stems_dir / f"master_english_sarvam_{spk}.wav"
            master_buffer = assemble_waterfall_timeline(english_blocks, block_audios, sample_rate, vid_dur)
            sf.write(str(master_wav), master_buffer, sample_rate)
            mux_video_with_audio_and_bgm(clean_video, master_wav, bgm_stem, out_eng_sarvam)
        else:
            print(f"[{idx_spk}/7] Existing English Sarvam ({spk}) video found: {out_eng_sarvam.name}")

    # -------------------------------------------------------------
    # 6. English - OmniVoice (male_deep)
    # -------------------------------------------------------------
    out_eng_omni = final_dir / "道可道 - 恭喜你成功制作出桂花蜜_english_omni_dubbed.mp4"
    if not out_eng_omni.exists() or out_eng_omni.stat().st_size < 100000:
        print("\n--- [6/7] Dubbing English: OmniVoice (male_deep) ---")
        omni = OmniVoiceTTS(default_voice="male_deep")
        omni.synthesize_and_dub(
            dubbed_srt=english_srt,
            original_video=clean_video,
            final_video=out_eng_omni,
            voice="male_deep",
            lang="English",
            bgm_path=bgm_stem,
            bgm_volume=1.05
        )
    else:
        print(f"[6/7] Existing English Omni video found: {out_eng_omni.name}")

    # -------------------------------------------------------------
    # 7. English - Google Cloud Chirp (en-US-Chirp3-HD-Fenrir)
    # -------------------------------------------------------------
    out_eng_chirp = final_dir / "道可道 - 恭喜你成功制作出桂花蜜_english_chirp_dubbed.mp4"
    if not out_eng_chirp.exists() or out_eng_chirp.stat().st_size < 100000:
        print("\n--- [7/7] Dubbing English: Google Cloud Chirp (en-US-Chirp3-HD-Fenrir) ---")
        cache_dir = stems_dir / "cache_chirp_english"
        cache_dir.mkdir(parents=True, exist_ok=True)
        block_audios = []
        sample_rate = 24000
        for i, b in enumerate(english_blocks, 1):
            w_file = cache_dir / f"block_{b['index']:02d}.wav"
            if not w_file.exists():
                audio_bytes = synthesize_google_chirp_block(
                    b["text"], gcloud_key, "en-US-Chirp3-HD-Fenrir", "en-US", speaking_rate=1.10
                )
                mp3_f = cache_dir / f"block_{b['index']:02d}.mp3"
                mp3_f.write_bytes(audio_bytes)
                subprocess.run(["ffmpeg", "-y", "-i", str(mp3_f), "-ar", str(sample_rate), "-ac", "1", str(w_file)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                mp3_f.unlink(missing_ok=True)
            arr, sr = sf.read(str(w_file))
            block_audios.append(arr)
            print(f"  [Chirp English] Block #{b['index']:02d} ready: {len(arr)/sample_rate:.2f}s")

        master_wav = stems_dir / "master_english_chirp.wav"
        master_buffer = assemble_waterfall_timeline(english_blocks, block_audios, sample_rate, vid_dur)
        sf.write(str(master_wav), master_buffer, sample_rate)
        mux_video_with_audio_and_bgm(clean_video, master_wav, bgm_stem, out_eng_chirp)
    else:
        print(f"[7/7] Existing English Chirp video found: {out_eng_chirp.name}")

    print("\n" + "=" * 65)
    print(" [Multi-Voice Studio] ALL 7 DUBS COMPLETED SUCCESSFULLY!")
    print(f" Final Videos Directory: {final_dir}")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
