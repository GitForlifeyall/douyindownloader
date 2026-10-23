import subprocess
import cv2
import numpy as np

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

samples = [
    'ke ped par maaro',
    'Gaaon ke dabang',
    'ek zordaar kick maaro!',
    'inhe turant collect',
    'karke inki dandiyan',
    'saaf kar lena ji.',
    'neeche girte hi turant',
    'saara oopri moisture'
]

for fs in [110, 115, 120, 125]:
    print(f"\n=== FONT SIZE {fs} (NATURAL, NO SQUEEZE/STRETCH) ===")
    for text in samples:
        with open('temp_fs.ass', 'w', encoding='utf-8') as f:
            f.write(ass_template.format(fs=fs, text=text))
        cmd = ['ffmpeg', '-y', '-i', 'test_new_clean_frame_1s.png', '-vf', "ass='temp_fs.ass':fontsdir='assets/fonts'", '-frames:v', '1', 'temp_fs.png']
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        out = cv2.imread('temp_fs.png')
        diff = np.abs(clean.astype(float) - out.astype(float)).sum(axis=2)
        ys, xs = np.where(diff > 5)
        w = xs.max() - xs.min()
        print(f"  {w:4d}px ({len(text):2d}ch, {len(text.split()):1d}w) : '{text}'")
