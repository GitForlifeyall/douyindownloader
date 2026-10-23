import cv2
import numpy as np
import subprocess
from PIL import ImageFont

FONT_PATH = 'assets/fonts/Montserrat-ExtraBold.ttf'

# Let's test actual FFmpeg libass rendering at fs=115 and fs=118
ass_template = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Montserrat ExtraBold,{fs},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,8.0,2.0,2,40,40,360,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:05.00,Default,,0,0,0,,{text}
"""

clean = cv2.imread('test_new_clean_frame_1s.png')

test_phrases = [
    # Block 1
    ('Gaaon ke dabang ke ped', 'par maaro zordaar kick!'),
    ('Gaaon ke dabang', 'ke ped par maaro ek zordaar kick!'),
    ('Jaise hi ye khushboodaar', 'phool neeche girte hi,'),
    ('inhe turant collect karke', 'inki dandiyan saaf kar lena ji.'),
    
    # Block 2
    ('Ab in golden phoolon ko', 'saaf paani mein dhokar'),
    ('dhool aur keede nikaalo,', 'aur phir chhaanv mein'),
    ('phailakar inka saara', 'oopri moisture sukha lo.')
]

for fs in [112, 116, 120]:
    print(f"\n================ FONT SIZE {fs} ================")
    for pair in test_phrases:
        for text in pair:
            with open('temp_fs.ass', 'w', encoding='utf-8') as f:
                f.write(ass_template.format(fs=fs, text=text))
            cmd = ['ffmpeg', '-y', '-i', 'test_new_clean_frame_1s.png', '-vf', "ass='temp_fs.ass':fontsdir='assets/fonts'", '-frames:v', '1', 'temp_fs.png']
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            out = cv2.imread('temp_fs.png')
            diff = np.abs(clean.astype(float) - out.astype(float)).sum(axis=2)
            ys, xs = np.where(diff > 5)
            w = xs.max() - xs.min()
            covers = w >= 740
            fits = w <= 980
            status = "PERFECT" if (covers and fits) else ("SHORT" if not covers else "WIDE")
            print(f"  {w:4d}px ({len(text):2d}ch, {len(text.split()):1d}w) [{status:7s}] : '{text}'")
