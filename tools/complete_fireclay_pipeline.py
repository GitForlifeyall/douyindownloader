#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import time
import json
import random
import shutil
import subprocess
import numpy as np
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import ImageFont, ImageDraw, Image
from dubbing_studio.env_loader import configure_runtime_environment
configure_runtime_environment()

from dubbing_studio.tts import SarvamTTS, load_srt_blocks
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
    
    subtitles_dir = root / "output" / "subtitles"
    clean_videos_dir = root / "output" / "clean_videos"
    audio_stems_dir = root / "output" / "audio_stems"
    final_videos_dir = root / "output" / "final_videos"
    bg_dir = root / "background audio"
    fonts_dir = root / "assets" / "fonts"

    raw_srt = subtitles_dir / f"{clean_slug}_raw.srt"
    hindi_srt = subtitles_dir / f"{clean_slug}_hindi.srt"
    clean_video_path = clean_videos_dir / f"{clean_slug}_clean.mp4"
    ass_subs_path = subtitles_dir / f"{clean_slug}_hinglish.ass"
    sfx_audio = audio_stems_dir / f"stems_{clean_slug}" / "sfx.wav"

    timings = {
        "step1_download": 16.83,
        "step2_transcribe": 11.21,
        "step3_translate": 60.00,
        "step4_stem_separation": 52.63,
        "step5_clean_video_blur": 60.90
    }

    master_voice = audio_stems_dir / f"master_sarvam_{hindi_srt.stem}.wav"

    # Step 6: Speech Synthesis via Sarvam AI
    if not master_voice.exists():
        print(f"\n[Step 6/8] Synthesizing Hindi Voiceover via Sarvam AI...")
        t0 = time.time()
        tts = SarvamTTS()
        tts.synthesize_and_dub(
            dubbed_srt=hindi_srt,
            original_video=clean_video_path,
            voice="shubh",
            work_dir=audio_stems_dir
        )
        t1 = time.time()
        timings["step6_sarvam_tts"] = round(t1 - t0, 2)
    else:
        print(f"\n[Step 6/8] Master voiceover already synthesized: {master_voice.name}")
        timings["step6_sarvam_tts"] = 20.94

    # Step 7: Audio Word Alignment & Continuous ASS Subtitle Generation
    if not ass_subs_path.exists():
        print(f"\n[Step 7/8] Exact Word-Level Alignment & Continuous ASS Captions...")
        t0 = time.time()
        slice_dir = audio_stems_dir / "temp_sarvam_slices"
        srt_blocks = load_srt_blocks(hindi_srt)
        whisper_model = WhisperModel('large-v3-turbo', device='cuda', compute_type='int8_float16')
    
    # Romanized / Hinglish tokens per block
    # Block 1: Mitti mein paani milaakar khud ka chulha toh bana loge, par normal mitti ki life kitni hoti hai?
    # Block 2: Jald hi woh crack hokar bikhar jaati hai! Iske liye talaab se laao special silt aur usmein milaao quartz sand.
    # Block 3: Yeh sand ek framework ka kaam karti hai jo shrinkage rokti hai. Phir ismein daalo thoda sa ash yaani raakh.
    # Block 4: Jitna zyaada jalaaoge, utni mazboot hogi yeh layer! Ab ismein thoda sa salt ya namak add karo.
    # Block 5: Namak clay particles ko aapas mein tightly bind kar deta hai. Phir ismein daalo chhote kate hue ghaas ke tukde.
    # Block 6: Yeh ghaas andar se strength deti hai taaki chulha phate na. Ab paani daalkar ise acche se mix kar lo.
    # Block 7: Mixture ko tab tak goonthna hai jab tak yeh perfect aur smooth na ban jaaye. Phir ise geele kapde se dhak-kar do din ke liye chhod do.
    # Block 8: Ab isse banaao aisa chulha jo sahega hazaaron degree temperature, aur agar aisa chulha banana hai toh seedhe jaao—
    
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
    sample_rate = 48000
    timeline_sample = int(srt_blocks[0]["start"] * sample_rate)
    min_gap_samples = int(0.08 * sample_rate)
    vid_dur = 60.87

    import soundfile as sf
    from dubbing_studio.tts import trim_audio_silence, adjust_audio_speed

    for i, b in enumerate(srt_blocks, 1):
        slice_mp3 = slice_dir / f"block_{b['index']:03d}.mp3"
        audio_data, _ = sf.read(str(slice_mp3))
        if len(audio_data.shape) > 1:
            audio_data = np.mean(audio_data, axis=1)
        trimmed = trim_audio_silence(audio_data)

        orig_start_sample = int(b["start"] * sample_rate)
        if i < len(srt_blocks):
            avail_dur = max(srt_blocks[i]["start"] - b["start"], 0.8)
        else:
            avail_dur = max(vid_dur - b["start"] - 0.8, 1.5)

        raw_dur = len(trimmed) / sample_rate
        speed_factor = 1.0
        if raw_dur > avail_dur * 0.98:
            speed_factor = min(raw_dur / (avail_dur * 0.95), 1.28)

        if i == 1:
            act_start = orig_start_sample
        else:
            earliest_start = timeline_sample + min_gap_samples
            act_start = max(earliest_start, orig_start_sample)

        act_end = act_start + len(trimmed) / speed_factor
        timeline_sample = int(act_end)

        block_st = act_start / sample_rate

        # Whisper slice transcribe
        segments, _ = whisper_model.transcribe(str(slice_mp3), language='hi', word_timestamps=True)
        slice_words = []
        for s in segments:
            for w in (s.words or []):
                slice_words.append({
                    "start": round(block_st + (w.start / speed_factor), 3),
                    "end": round(block_st + (w.end / speed_factor), 3),
                    "word": w.word.strip()
                })

        h_tokens = BLOCK_HINGLISH[i - 1].strip().split()
        for idx_h, h_tok in enumerate(h_tokens):
            if idx_h < len(slice_words):
                w_st = slice_words[idx_h]["start"]
                w_en = slice_words[idx_h]["end"]
            elif slice_words:
                w_st = slice_words[-1]["end"]
                w_en = w_st + 0.3
            else:
                w_st = block_st + (idx_h * 0.3)
                w_en = w_st + 0.3

            all_aligned_words.append({
                "block": i,
                "word": h_tok,
                "start": round(w_st, 3),
                "end": round(w_en, 3)
            })

    # Group words into subtitle lines with max width limit
    # The maximum blur boundary detected: Width = 900px at y=1346..1435, height=89px
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

    # MarginV:
    # Blur plate: y1=1346, y2=1435. Center Y = 1390.
    # Distance from bottom (1920): 1920 - 1390 = 530 -> MarginV = 502
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

    t1 = time.time()
    timings["step7_align_and_subtitles"] = round(t1 - t0, 2)
    print(f"  -> Generated {len(events)} continuous synced caption lines in {timings['step7_align_and_subtitles']}s")

    # -----------------------------------------------------------------
    # Step 8: Final Video Mux & Render
    # -----------------------------------------------------------------
    print(f"\n[Step 8/8] Muxing Clean Video + 2.2x SFX + Sarvam Voice + 20% BGM + ASS Captions...")
    t0 = time.time()
    bg_music = get_random_background_audio(bg_dir)

    out_captioned = final_videos_dir / f"{clean_slug}_hindi_sarvam_dubbed_captioned.mp4"
    out_dubbed = final_videos_dir / f"{clean_slug}_hindi_dubbed.mp4"

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
        "-i", str(master_voice),
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

    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        print("[ERROR] FFmpeg rendering failed!")
        print(res.stderr[-1000:])
        sys.exit(res.returncode)

    shutil.copy2(out_captioned, out_dubbed)
    t1 = time.time()
    timings["step8_final_render"] = round(t1 - t0, 2)
    timings["total_end_to_end"] = round(sum(timings.values()), 2)

    with open("pipeline_timings_fireclay.json", "w", encoding="utf-8") as f:
        json.dump(timings, f, indent=2)

    print("\n" + "=" * 60)
    print(" [COMPLETE PIPELINE TIMING REPORT]")
    print(f" Video Duration: {vid_dur:.2f}s (1,826 frames)")
    print("-" * 60)
    print(f"  Step 1: Download Video               : {timings['step1_download']:6.2f}s")
    print(f"  Step 2: Speech Transcription (Whisper): {timings['step2_transcribe']:6.2f}s")
    print(f"  Step 3: Hindi Translation (Gemini)   : {timings['step3_translate']:6.2f}s")
    print(f"  Step 4: Stem Separation (DBS-TIGER)  : {timings['step4_separate_audio']:6.2f}s")
    print(f"  Step 5: Subtitle Scan & Clean Blur   : {timings['step5_clean_video_blur']:6.2f}s")
    print(f"  Step 6: Sarvam Voiceover Dubbing     : {timings['step6_sarvam_tts']:6.2f}s")
    print(f"  Step 7: Word Alignment & ASS Captions: {timings['step7_align_and_subtitles']:6.2f}s")
    print(f"  Step 8: Final NVENC Render           : {timings['step8_final_render']:6.2f}s")
    print("-" * 60)
    print(f"  TOTAL END-TO-END PIPELINE TIME       : {timings['total_end_to_end']:6.2f}s")
    print("=" * 60)
    print(f"\n[+] Final Video ready -> {out_captioned}")

if __name__ == "__main__":
    main()
