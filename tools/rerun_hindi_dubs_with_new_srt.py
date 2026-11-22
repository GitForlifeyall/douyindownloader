#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rerun_hindi_dubs_with_new_srt.py
================================
Re-generates all 3 Hindi dubbed versions using the user's revised Hindi SRT:
1. Sarvam AI Bulbul v3 (shubh)
2. Google Cloud Chirp 3 HD (hi-IN-Chirp3-HD-Orus)
3. OmniVoice (male_deep)

Preserves background Foley SFX and music with sidechain ducking.
Outputs strictly to output/final_videos/.
"""

import os
import sys
import time
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from dubbing_studio.env_loader import configure_runtime_environment
configure_runtime_environment()

from dubbing_studio.tts import SarvamTTS
from dubbing_studio.tts_omnivoice import OmniVoiceTTS
from dubbing_studio.tts_engine import load_srt_blocks
from generate_multi_voice_dubs import (
    synthesize_google_chirp_block,
    assemble_waterfall_timeline,
    mux_video_with_audio_and_bgm
)


def main():
    root = Path.cwd()
    clean_video = root / "output/clean_videos/道可道 - 恭喜你成功制作出桂花蜜_clean.mp4"
    bgm_stem = root / "output/audio_stems/stems_道可道 - 恭喜你成功制作出桂花蜜/no_vocals.wav"
    hindi_srt = root / "output/subtitles/道可道 - 恭喜你成功制作出桂花蜜_hindi.srt"

    final_dir = root / "output/final_videos"
    stems_dir = root / "output/audio_stems"

    probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(clean_video)]
    vid_dur = float(subprocess.check_output(probe_cmd).decode().strip())
    hindi_blocks = load_srt_blocks(hindi_srt)

    print("\n" + "=" * 65)
    print(" [Hindi Dubs Refresh] GENERATING WITH NEW REVISED HINDI SRT")
    print(f" SRT File         : {hindi_srt.name}")
    print(f" Video Duration   : {vid_dur:.2f}s")
    print(f" Clean Video Base : {clean_video.name}")
    print(f" Foley BGM Stem   : {bgm_stem.name}")
    print("=" * 65 + "\n")

    # -------------------------------------------------------------
    # 1. Sarvam AI (shubh)
    # -------------------------------------------------------------
    print("\n--- [1/3] Generating Sarvam AI Bulbul v3 (shubh) Hindi Dub ---")
    sarvam_tts = SarvamTTS(default_speaker="shubh")
    out_sarvam = final_dir / "道可道 - 恭喜你成功制作出桂花蜜_hindi_dubbed.mp4"
    sarvam_tts.synthesize_and_dub(
        dubbed_srt=hindi_srt,
        original_video=clean_video,
        final_video=out_sarvam,
        voice="shubh",
        lang="hi",
        base_speed=1.0,
        mode="slice",
        bgm_path=bgm_stem,
        bgm_volume=1.05,
        work_dir=stems_dir
    )
    print(f"  ✓ Sarvam Hindi Dub refreshed: {out_sarvam.name}")

    # -------------------------------------------------------------
    # 2. Google Cloud Chirp 3 HD (hi-IN-Chirp3-HD-Orus)
    # -------------------------------------------------------------
    print("\n--- [2/3] Generating Google Cloud Chirp (hi-IN-Chirp3-HD-Orus) Hindi Dub ---")
    gcloud_key = os.getenv("GOOGLE_TTS_API_KEY") or os.getenv("GEMINI_API_KEY")
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

    out_chirp = final_dir / "道可道 - 恭喜你成功制作出桂花蜜_hindi_chirp_dubbed.mp4"
    mux_video_with_audio_and_bgm(clean_video, master_wav, bgm_stem, out_chirp)
    print(f"  ✓ Chirp Hindi Dub refreshed: {out_chirp.name}")

    # -------------------------------------------------------------
    # 3. OmniVoice (male_deep)
    # -------------------------------------------------------------
    print("\n--- [3/3] Generating OmniVoice (male_deep) Hindi Dub ---")
    out_omni = final_dir / "道可道 - 恭喜你成功制作出桂花蜜_hindi_omni_dubbed.mp4"
    omni = OmniVoiceTTS(default_voice="male_deep")
    omni.synthesize_and_dub(
        dubbed_srt=hindi_srt,
        original_video=clean_video,
        final_video=out_omni,
        voice="male_deep",
        lang="Hindi",
        bgm_path=bgm_stem,
        bgm_volume=1.05
    )
    print(f"  ✓ OmniVoice Hindi Dub refreshed: {out_omni.name}")

    print("\n" + "=" * 65)
    print(" [Hindi Dubs Refresh] ALL 3 HINDI DUBS RE-RENDERED WITH NEW SRT!")
    print(f" Output Location: {final_dir}")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
