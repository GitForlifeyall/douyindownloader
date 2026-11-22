import subprocess
import cv2
import numpy as np

ass_path = 'output/subtitles/道可道 - 恭喜你成功制作出桂花蜜_hinglish.ass'
clean = cv2.imread('test_new_clean_frame_1s.png')

with open(ass_path, 'r', encoding='utf-8') as f:
    lines = [l.strip() for l in f if l.startswith('Dialogue:')]

print(f"Auditing {len(lines)} natural dialogue lines with actual FFmpeg libass rendering:")

failures = []
for idx, l in enumerate(lines):
    parts = l.split(',', 9)
    txt = parts[9]
    t_st = parts[1]
    t_en = parts[2]
    
    # Create single-line test ASS
    single_ass = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Montserrat ExtraBold,120,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,8.5,2.0,2,40,40,360,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:05.00,Default,,0,0,0,,{txt}
"""
    with open('temp_audit.ass', 'w', encoding='utf-8') as tf:
        tf.write(single_ass)
        
    cmd = ['ffmpeg', '-y', '-i', 'test_new_clean_frame_1s.png', '-vf', "ass='temp_audit.ass':fontsdir='assets/fonts'", '-frames:v', '1', 'temp_audit.png']
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out = cv2.imread('temp_audit.png')
    diff = np.abs(clean.astype(float) - out.astype(float)).sum(axis=2)
    ys, xs = np.where(diff > 5)
    w = xs.max() - xs.min()
    covers = w >= 730
    fits = w <= 1000
    status = "OK" if covers and fits else ("SHORT" if not covers else "WIDE")
    if not (covers and fits):
        failures.append((idx+1, txt, w, status))
    print(f"[{idx+1:2d}] {w:4d}px ({len(txt):2d}ch, {len(txt.split()):1d}w) [{status:5s}] : '{txt}'")

print(f"\nAudit completed: {len(lines)} lines, {len(failures)} failures.")
