import subprocess
import cv2
import numpy as np

ass_test = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Montserrat ExtraBold,126,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,9.0,2.0,2,40,40,360,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:05.00,Default,,0,0,0,,ke ped par maaro
"""

with open('temp_test.ass', 'w', encoding='utf-8') as f:
    f.write(ass_test)

cmd = ['ffmpeg', '-y', '-i', 'test_new_clean_frame_1s.png', '-vf', "ass='temp_test.ass':fontsdir='assets/fonts'", '-frames:v', '1', 'temp_out_126.png']
subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

clean = cv2.imread('test_new_clean_frame_1s.png')
out = cv2.imread('temp_out_126.png')
diff = np.abs(clean.astype(float) - out.astype(float)).sum(axis=2)
ys, xs = np.where(diff > 5)
w = xs.max() - xs.min()
h = ys.max() - ys.min()
y_cen = (ys.min() + ys.max()) / 2.0
x_cen = (xs.min() + xs.max()) / 2.0
print(f"Rendered text at fs=126 MarginV=360:")
print(f"  Width  : {w} px (X: {xs.min()} to {xs.max()})")
print(f"  Height : {h} px (Y: {ys.min()} to {ys.max()})")
print(f"  Center : ({x_cen:.1f}, {y_cen:.1f})")

# Crop region
crop = out[1380:1620, 80:1000]
cv2.imwrite('proof_126_crop.png', crop)
print("Saved proof_126_crop.png")
