#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_google_flash_dub.py
=========================
Generates the complete dubbed video using Google Gemini Flash TTS (gemini-3.8-flash-tts).
- Tight, natural conversational speech flow (no 3-second gaps)
- Isolated 2.2x Foley SFX from DBS-TIGER
- 20% looping background music
- Exact Faster-Whisper word-level audio alignment
- Continuous ASS subtitles within 900px permanent blur boundary
"""

import os
import sys
import time
import json
import random
import shutil
import subprocess
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import soundfile as sf
from PIL import ImageFont, ImageDraw, Image

from dubbing_studio.env_loader import configure_runtime_environment
configure_runtime_environment()

from dubbing_studio.tts_google import GoogleGeminiTTS
from dubbing_studio.tts import load_srt_blocks
from faster_whisper import WhisperModel

def to_ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

def get_random_background_audio(bg_dir: Path) -> Path:
    exts = ('.mp3', '.wav', '.aac', '.m4a', '.ogg', '.flac')
    audio_files = [p for p in bg_dir.iterdir() if p.is_file() and p.suffix.lower() in exts]
    if not audio_files:
        raise FileNotFoundError(f"No audio files found in {bg_dir}")
    return random.choice(audio_files)

def main():
    root = Path.cwd()
    clean_slug = "旭日 - 恭喜你成功复刻出古法耐火泥"
    
    clean_video_path = root / "output" / "clean_videos" / f"{clean_slug}_clean.mp4"
    hindi_srt = root / "output" / "subtitles" / f"{clean_slug}_hindi.srt"
    sfx_audio = root / "output" / "audio_stems" / f"stems_{clean_slug}" / "sfx.wav"
    stems_dir = root / "output" / "audio_stems"
    final_dir = root / "output" / "final_videos"
    subtitles_dir = root / "output" / "subtitles"
    bg_dir = root / "background audio"
    fonts_dir = root / "assets" / "fonts"

    out_captioned = final_dir / f"{clean_slug}_hindi_google_flash_dubbed.mp4"
    out_canonical = final_dir / f"{clean_slug}_hindi_dubbed.mp4"
    ass_subs_path = subtitles_dir / f"{clean_slug}_google_flash_hinglish.ass"
    master_voice_path = stems_dir / f"master_google_flash_{clean_slug}_hindi.wav"

    vid_dur = 60.87
    sample_rate = 24000

    print("==================================================")
    print(" [Google Flash TTS Pipeline] Starting End-to-End Dub")
    print(f" Video        : {clean_slug}")
    print(f" Subtitles    : {hindi_srt.name}")
    print(f" Clean Video  : {clean_video_path.name}")
    print(f" SFX Track    : {sfx_audio.name}")
    print("==================================================")

    # 1. Synthesize all blocks with Google Gemini Flash TTS
    tts = GoogleGeminiTTS(model="gemini-3.1-flash-tts-preview", default_speaker="Orus")
    blocks = load_srt_blocks(hindi_srt)
    print(f"\n[1/4] Synthesizing {len(blocks)} blocks using Gemini Flash TTS...")

    block_audios = []
    cache_dir = stems_dir / f"google_flash_cache_{clean_slug}"
    if cache_dir.exists():
        shutil.rmtree(cache_dir, ignore_errors=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    t_tts_start = time.time()
    for b in blocks:
        text = b["text"].strip()
        cache_file = cache_dir / f"block_{b['index']:03d}.wav"
        # Pass ONLY the clean Hindi text to synthesize, zero prompt words!
        audio, sr = tts.synthesize_single_block(text, voice="Orus", cache_path=cache_file)
        block_audios.append({
            "block": b,
            "audio": audio,
            "text": text
        })
        print(f"  Block #{b['index']:02d}: {len(audio)/sr:.2f}s of pure speech generated")

    print(f"[+] All blocks synthesized in {time.time() - t_tts_start:.2f}s")

    # 2. Master Voiceover Assembly with Natural Conversational Flow (Tight Gaps)
    print("\n[2/4] Assembling master voiceover with tight conversational flow...")
    buffer_len = int((vid_dur + 10.0) * sample_rate)
    master_buffer = np.zeros(buffer_len, dtype=np.float32)

    from dubbing_studio.tts_google import trim_audio_silence, adjust_audio_speed

    timeline_sample = int(0.02 * sample_rate)
    min_gap_samples = int(0.12 * sample_rate)  # 120ms natural breath pause
    max_gap_samples = int(0.25 * sample_rate)  # 250ms max gap (no dead pauses)

    block_placements = []

    for i, item in enumerate(block_audios):
        b = item["block"]
        audio = item["audio"]
        trimmed = trim_audio_silence(audio, pad_samples=int(0.015 * sample_rate))
        raw_dur = len(trimmed) / sample_rate

        orig_start_sample = int(b["start"] * sample_rate)
        if i + 1 < len(block_audios):
            avail_dur = max(block_audios[i + 1]["block"]["start"] - b["start"], 1.0)
        else:
            avail_dur = max(vid_dur - b["start"], 1.5)

        # If speech naturally exceeds slot, compress slightly
        if raw_dur > avail_dur * 1.05:
            speed = min(raw_dur / avail_dur, 1.25)
            trimmed = adjust_audio_speed(trimmed, sample_rate, speed)

        if i == 0:
            act_start = int(0.02 * sample_rate)
        else:
            earliest_start = timeline_sample + min_gap_samples
            latest_start = timeline_sample + max_gap_samples
            # If the original scene is far ahead, pull forward so speech flows naturally without dead pause!
            if orig_start_sample > latest_start:
                act_start = latest_start
            else:
                act_start = max(earliest_start, orig_start_sample)

        act_end = act_start + len(trimmed)
        if act_end > len(master_buffer):
            master_buffer = np.pad(master_buffer, (0, act_end - len(master_buffer) + sample_rate * 5))

        master_buffer[act_start:act_end] += trimmed
        timeline_sample = act_end

        st_sec = act_start / sample_rate
        en_sec = act_end / sample_rate
        block_placements.append({
            "block": b["index"],
            "start": st_sec,
            "end": en_sec,
            "trimmed_audio": trimmed
        })
        print(f"  Block #{b['index']:02d} placed at {st_sec:.2f}s -> {en_sec:.2f}s (Gap: {(st_sec - (block_placements[-2]['end'] if i > 0 else 0)):.2f}s)")

    # Peak normalization
    peak_dur_samples = min(len(master_buffer), int(vid_dur * sample_rate))
    peak = np.max(np.abs(master_buffer[:peak_dur_samples]))
    if peak > 0:
        master_buffer = master_buffer / peak * 0.95

    sf.write(str(master_voice_path), master_buffer[:int(vid_dur * sample_rate)], sample_rate)
    print(f"[+] Master voice written to {master_voice_path.name}")

    # 3. Exact Word Alignment & Continuous ASS Subtitle Generation
    print("\n[3/4] Aligning spoken words with Faster-Whisper on Google Flash Voice...")
    whisper_model = WhisperModel('large-v3-turbo', device='cuda', compute_type='int8_float16')

    BLOCK_HINGLISH = [
        "Mitti mein paani milaakar khud ka chulha toh bana loge, par normal mitti ki life kitni hoti hai?",
        "Jald hi woh crack hokar bikhar jaati hai! Iske liye talaab se laao special silt aur usmein milaao quartz sand.",
        "Yeh sand ek framework ka kaam karti hai jo shrinkage rokti hai. Phir ismein daalo thoda sa ash yaani raakh.",
        "Jitna zyaada jalaaoge, utni mazboot hogi yeh layer! Ab ismein thoda sa salt ya namak add karo.",
        "Namak clay particles ko aapas mein tightly bind kar deta hai. Phir ismein daalo chhote kate hue ghaas ke tukde.",
        "Yeh ghaas andar se strength deti hai taaki chulha phate na. Ab paani daalkar ise acche se mix kar lo.",
        "Mixture ko tab tak goonthna hai jab tak yeh perfect aur smooth na ban jaaye. Phir ise geele kapde se dhak-kar do din ke liye chhod do.",
        "Ab isse banaao aisa chulha jo sahega hazaaron degree temperature, aur agar aisa chulha banana hai toh seedhe jaao—"
    ]

    all_aligned_words = []
    temp_dir = stems_dir / "temp_google_slices"
    temp_dir.mkdir(parents=True, exist_ok=True)

    for i, bp in enumerate(block_placements):
        slice_wav = temp_dir / f"slice_b{bp['block']:02d}.wav"
        sf.write(str(slice_wav), bp["trimmed_audio"], sample_rate)

        segments, _ = whisper_model.transcribe(str(slice_wav), language='hi', word_timestamps=True)
        slice_words = []
        for s in segments:
            for w in (s.words or []):
                slice_words.append({
                    "start": round(bp["start"] + w.start, 3),
                    "end": round(bp["start"] + w.end, 3),
                    "word": w.word.strip()
                })

        h_tokens = BLOCK_HINGLISH[i].strip().split()
        for idx_h, h_tok in enumerate(h_tokens):
            if idx_h < len(slice_words):
                w_st = slice_words[idx_h]["start"]
                w_en = slice_words[idx_h]["end"]
            elif slice_words:
                w_st = slice_words[-1]["end"]
                w_en = w_st + 0.3
            else:
                w_st = bp["start"] + (idx_h * 0.3)
                w_en = w_st + 0.3

            all_aligned_words.append({
                "block": bp["block"],
                "word": h_tok,
                "start": round(w_st, 3),
                "end": round(w_en, 3)
            })

    # Group words into lines within 900px blur width (<= 860px)
    MAX_BORDER_W = 860
    FONT_SIZE = 68
    font = ImageFont.truetype(str(fonts_dir / "Montserrat-ExtraBold.ttf"), FONT_SIZE)
    img_tmp = Image.new("RGB", (10, 10))
    draw_tmp = ImageDraw.Draw(img_tmp)

    def get_w(text: str) -> int:
        bbox = draw_tmp.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]

    chunks = []
    curr = []
    for w in all_aligned_words:
        cand = curr + [w]
        cand_text = " ".join([cw["word"] for cw in cand])
        seal = False
        if curr:
            if w["block"] != curr[0]["block"]:
                seal = True
            elif get_w(cand_text) > MAX_BORDER_W:
                seal = True
            elif any(curr[-1]["word"].endswith(p) for p in [".", "!"]):
                seal = True
            elif len(curr) >= 3 and any(curr[-1]["word"].endswith(p) for p in [",", "?"]):
                seal = True
        if seal:
            chunks.append(curr)
            curr = [w]
        else:
            curr.append(w)
    if curr:
        chunks.append(curr)

    events = []
    for i, ch in enumerate(chunks):
        ch_text = " ".join([cw["word"] for cw in ch])
        st_t = 0.00 if i == 0 else ch[0]["start"]
        events.append({
            "start": st_t,
            "text": ch_text,
            "width": get_w(ch_text)
        })

    for i in range(len(events) - 1):
        events[i]["end"] = events[i+1]["start"]
    events[-1]["end"] = vid_dur

    ass_header = f"""[Script Info]
; Script generated with Audio-Synced Continuous Presence & Maximum Boundary Fit
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Montserrat ExtraBold,{FONT_SIZE},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,7.0,2.0,2,40,40,502,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ass_lines = [ass_header.strip()]
    for e in events:
        ass_lines.append(f"Dialogue: 0,{to_ass_time(e['start'])},{to_ass_time(e['end'])},Default,,0,0,0,,{e['text']}")

    with open(ass_subs_path, "w", encoding="utf-8") as f:
        f.write("\n".join(ass_lines) + "\n")
    print(f"[+] Wrote {len(events)} continuous captions to {ass_subs_path.name}")

    # 4. Final Video Render
    print("\n[4/4] Muxing Clean Video + SFX + Google Flash Voice + 20% BGM + ASS Captions...")
    bg_music = get_random_background_audio(bg_dir)

    rel_ass = str(ass_subs_path.relative_to(root)).replace("\\", "/")
    rel_fonts = str(fonts_dir.relative_to(root)).replace("\\", "/")

    filter_complex = (
        f"[0:v]ass='{rel_ass}':fontsdir='{rel_fonts}'[vout];"
        f"[1:a]volume=2.20,highpass=f=40,acompressor=threshold=-20dB:ratio=2.5:attack=5:release=50[sfx];"
        f"[2:a]volume=1.30,loudnorm=I=-13:TP=-0.5:LRA=7[voice];"
        f"[3:a]volume=0.20[bgm];"
        f"[sfx][voice][bgm]amix=inputs=3:weights=1.0 1.0 1.0:normalize=0[mixed];"
        f"[mixed]alimiter=limit=0.98:attack=5:release=50[aout]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", str(clean_video_path),
        "-i", str(sfx_audio),
        "-i", str(master_voice_path),
        "-stream_loop", "-1",
        "-i", str(bg_music),
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", "[aout]",
        "-c:v", "hevc_nvenc",
        "-preset", "p4",
        "-b:v", "3600k",
        "-maxrate", "5000k",
        "-bufsize", "8000k",
        "-tag:v", "hvc1",
        "-c:a", "aac",
        "-b:a", "256k",
        "-shortest",
        str(out_captioned)
    ]

    t0 = time.time()
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        print("[ERROR] FFmpeg rendering failed!")
        print(res.stderr[-1000:])
        sys.exit(res.returncode)

    shutil.copy2(out_captioned, out_canonical)
    render_dur = time.time() - t0
    print(f"\n[+] Render completed successfully in {render_dur:.2f}s -> {out_captioned}")
    print(f"[+] Canonical dubbed target updated -> {out_canonical}")

if __name__ == "__main__":
    main()
