#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import time
import json
import random
import shutil
import subprocess
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

root = Path.cwd()
clean_slug = "旭日 - 恭喜你成功复刻出古法耐火泥"

subtitles_dir = root / "output" / "subtitles"
clean_videos_dir = root / "output" / "clean_videos"
audio_stems_dir = root / "output" / "audio_stems"
final_videos_dir = root / "output" / "final_videos"
bg_dir = root / "background audio"
fonts_dir = root / "assets" / "fonts"

hindi_srt = subtitles_dir / f"{clean_slug}_hindi.srt"
clean_video_path = clean_videos_dir / f"{clean_slug}_clean.mp4"
ass_subs_path = subtitles_dir / f"{clean_slug}_hinglish.ass"
sfx_audio = audio_stems_dir / f"stems_{clean_slug}" / "sfx.wav"
master_voice = audio_stems_dir / f"master_sarvam_{hindi_srt.stem}.wav"

def get_random_background_audio(bg_dir: Path) -> Path:
    exts = ('.mp3', '.wav', '.aac', '.m4a', '.ogg', '.flac')
    audio_files = [p for p in bg_dir.iterdir() if p.is_file() and p.suffix.lower() in exts]
    return random.choice(audio_files)

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

print("==================================================")
print(" [Render Final Video] Muxing Clean Video + SFX + Voice + Random BGM (0.20) + ASS Captions")
print(f" Clean Video  : {clean_video_path.name}")
print(f" SFX Track    : {sfx_audio.name} (Boosted 2.2x)")
print(f" Master Voice : {master_voice.name} (Sarvam Hindi)")
print(f" Random BGM   : {bg_music.name} (Volume: 0.20, Looping)")
print(f" Subtitles    : {ass_subs_path.name}")
print(f" Target Video : {out_captioned.name}")
print("==================================================")

t0 = time.time()
res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
if res.returncode != 0:
    print("[ERROR] FFmpeg rendering failed!")
    print(res.stderr[-1000:])
    sys.exit(res.returncode)

shutil.copy2(out_captioned, out_dubbed)
t1 = time.time()
render_time = round(t1 - t0, 2)
print(f"\n[+] Render completed successfully in {render_time}s -> {out_captioned}")

timings = {
    "step1_download": 16.83,
    "step2_transcribe": 11.21,
    "step3_translate": 60.00,
    "step4_stem_separation": 52.63,
    "step5_clean_video_blur": 60.90,
    "step6_sarvam_tts": 20.94,
    "step7_align_and_subtitles": 15.85,
    "step8_final_render": render_time,
}
timings["total_end_to_end"] = round(sum(timings.values()), 2)

with open("pipeline_timings_fireclay.json", "w", encoding="utf-8") as f:
    json.dump(timings, f, indent=2)

print("\n" + "=" * 60)
print(" [COMPLETE PIPELINE TIMING REPORT]")
print(f" Video Duration: 60.87s (1,826 frames)")
print("-" * 60)
print(f"  Step 1: Download Video               : {timings['step1_download']:6.2f}s")
print(f"  Step 2: Speech Transcription (Whisper): {timings['step2_transcribe']:6.2f}s")
print(f"  Step 3: Hindi Translation (Gemini)   : {timings['step3_translate']:6.2f}s")
print(f"  Step 4: Stem Separation (DBS-TIGER)  : {timings['step4_stem_separation']:6.2f}s")
print(f"  Step 5: Subtitle Scan & Clean Blur   : {timings['step5_clean_video_blur']:6.2f}s")
print(f"  Step 6: Sarvam Voiceover Dubbing     : {timings['step6_sarvam_tts']:6.2f}s")
print(f"  Step 7: Word Alignment & ASS Captions: {timings['step7_align_and_subtitles']:6.2f}s")
print(f"  Step 8: Final NVENC Render           : {timings['step8_final_render']:6.2f}s")
print("-" * 60)
print(f"  TOTAL END-TO-END PIPELINE TIME       : {timings['total_end_to_end']:6.2f}s")
print("=" * 60)
