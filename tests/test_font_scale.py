import subprocess
import cv2
import numpy as np

# In ASS, let's test WrapStyle: 2 (no word wrap) and check exact rendered pixel width for different font sizes
ass_template = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Montserrat ExtraBold,{fs},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,8.0,2.0,2,20,20,360,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:05.00,Default,,0,0,0,,{text}
"""

clean = cv2.imread('test_new_clean_frame_1s.png')

samples = [
    # 3 words
    "Gaaon ke dabang",
    "saaf kar lena",
    "ek zordaar kick!",
    # 4 words
    "ke ped par maaro",
    "phool neeche girte hi,",
    "saaf paani mein dhokar",
    "dhool aur keede nikaalo,",
    # 5 words
    "Gaaon ke dabang ped par",
    "maaro ek zordaar kick!",
    "inhe turant collect karke",
    "inki dandiyan saaf kar lo.",
    "Ab in golden phoolon ko",
]

for fs in [95, 100, 105, 110]:
    print(f"\n================ FONT SIZE {fs} (WrapStyle: 2) ================")
    for text in samples:
        with open('temp_test.ass', 'w', encoding='utf-8') as f:
            f.write(ass_template.format(fs=fs, text=text))
        cmd = ['ffmpeg', '-y', '-i', 'test_new_clean_frame_1s.png', '-vf', "ass='temp_test.ass':fontsdir='assets/fonts'", '-frames:v', '1', 'temp_out.png']
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        out = cv2.imread('temp_out.png')
        diff = np.abs(clean.astype(float) - out.astype(float)).sum(axis=2)
        ys, xs = np.where(diff > 5)
        w = xs.max() - xs.min()
        h = ys.max() - ys.min()
        status = "PERFECT" if (740 <= w <= 980) else ("SHORT" if w < 740 else "WIDE")
        print(f"  {w:4d}px x {h:2d}px ({len(text):2d}ch, {len(text.split()):1d}w) [{status:7s}] : '{text}'")
