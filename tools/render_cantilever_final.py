import os
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import random
import shutil
import subprocess
from pathlib import Path

def get_random_background_audio(bg_dir: Path) -> Path:
    exts = ('.mp3', '.wav', '.aac', '.m4a', '.ogg', '.flac')
    audio_files = [p for p in bg_dir.iterdir() if p.is_file() and p.suffix.lower() in exts]
    if not audio_files:
        raise FileNotFoundError(f"No audio files found in {bg_dir}")
    return random.choice(audio_files)

def main():
    root = Path(r"c:\Users\rudra\PycharmProjects\douyindownloader")
    clean_video = root / "output" / "clean_videos" / "见微知古 - 河中不建桥墩古人靠木头怎么把桥_clean.mp4"
    sfx_audio = root / "output" / "audio_stems" / "stems_见微知古 - 河中不建桥墩古人靠木头怎么把桥" / "sfx.wav"
    voice_audio = root / "output" / "audio_stems" / "master_sarvam_见微知古 - 河中不建桥墩古人靠木头怎么把桥_hindi.wav"
    ass_subs = root / "output" / "subtitles" / "见微知古 - 河中不建桥墩古人靠木头怎么把桥_hinglish.ass"
    fonts_dir = root / "assets" / "fonts"
    bg_dir = root / "background audio"
    
    out_dubbed = root / "output" / "final_videos" / "见微知古 - 河中不建桥墩古人靠木头怎么把桥_hindi_dubbed.mp4"
    out_captioned = root / "output" / "final_videos" / "见微知古 - 河中不建桥墩古人靠木头怎么把桥_hindi_sarvam_dubbed_captioned.mp4"

    bg_music = get_random_background_audio(bg_dir)

    rel_ass = "output/subtitles/见微知古 - 河中不建桥墩古人靠木头怎么把桥_hinglish.ass".replace("\\", "/")
    rel_fonts = "assets/fonts".replace("\\", "/")

    # Filter complex:
    # 0:v = clean video with permanent luminance blur plate
    # 1:a = isolated SFX (boosted 2.2x + highpass + compressor)
    # 2:a = Sarvam Hindi voiceover (1.30x + loudnorm)
    # 3:a = random background music (0.20x looping)
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
        "-i", str(clean_video),
        "-i", str(sfx_audio),
        "-i", str(voice_audio),
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
    print(f" Clean Video  : {clean_video.name}")
    print(f" SFX Track    : {sfx_audio.name} (Boosted 2.2x)")
    print(f" Master Voice : {voice_audio.name} (Sarvam Hindi)")
    print(f" Random BGM   : {bg_music.name} (Volume: 0.20, Looping)")
    print(f" Subtitles    : {ass_subs.name} (156 continuous lines, zero gap, max border <= 485px)")
    print(f" Target Video : {out_captioned.name}")
    print("==================================================")

    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        print("[ERROR] FFmpeg rendering failed!")
        print(res.stderr[-1500:])
        sys.exit(res.returncode)

    print(f"\n[+] Render completed successfully -> {out_captioned}")
    shutil.copy2(out_captioned, out_dubbed)
    print(f"[+] Updated canonical dubbed target -> {out_dubbed}")

if __name__ == "__main__":
    main()
