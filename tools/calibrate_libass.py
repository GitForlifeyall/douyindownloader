import subprocess
import cv2
import numpy as np

ass_template = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Montserrat ExtraBold,{fs},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,10.0,2.0,2,40,40,375,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:05.00,Default,,0,0,0,,ke ped par maaro
"""

clean = cv2.imread('test_new_clean_frame_1s.png')

print("Testing libass rendered width for 'ke ped par maaro' across font sizes:")
for fs in [90, 105, 115, 125, 130, 135]:
    with open('temp_test.ass', 'w', encoding='utf-8') as f:
        f.write(ass_template.format(fs=fs))
    
    cmd = ['ffmpeg', '-y', '-i', 'test_new_clean_frame_1s.png', '-vf', "ass='temp_test.ass':fontsdir='assets/fonts'", '-frames:v', '1', 'temp_out.png']
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out = cv2.imread('temp_out.png')
    diff = np.abs(clean.astype(float) - out.astype(float)).sum(axis=2)
    ys, xs = np.where(diff > 5)
    w = xs.max() - xs.min()
    h = ys.max() - ys.min()
    y_cen = (ys.min() + ys.max()) / 2.0
    x_min = xs.min()
    x_max = xs.max()
    print(f"Fontsize {fs:3d}: width = {w:4d} px (X: {x_min}..{x_max}), height = {h:3d} px, Y center = {y_cen:.1f}")
