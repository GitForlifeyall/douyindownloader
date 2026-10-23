import re
import cv2
import numpy as np
import subprocess
from pathlib import Path
from PIL import ImageFont

# Calibrated from actual libass rendering at PlayResX=1080, PlayResY=1920:
# Fontsize 126: 'ke ped par maaro' (16 chars) rendered exact width = 772 px.
# Ratio: ~48.25 px per char average (with outline 9.0)
FONT_PATH = 'assets/fonts/Montserrat-ExtraBold.ttf'
# PIL font size 126
font_pil = ImageFont.truetype(FONT_PATH, 126)

ass_path = Path('output/subtitles/道可道 - 恭喜你成功制作出桂花蜜_hinglish.ass')
with open(ass_path, 'r', encoding='utf-8') as f:
    content = f.read()

lines = content.splitlines()
dialogues = []
header_lines = []
is_events = False

for l in lines:
    if l.startswith('[Events]'):
        is_events = True
        header_lines.append(l)
    elif not is_events:
        if l.startswith('Style: Default'):
            # Update default style to Fontsize 126, Outline 9.0, MarginV 360
            header_lines.append('Style: Default,Montserrat ExtraBold,126,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,9.0,2.0,2,40,40,360,1')
        else:
            header_lines.append(l)
    elif l.startswith('Format:'):
        header_lines.append(l)
    elif l.startswith('Dialogue:'):
        dialogues.append(l)

print(f"Total dialogue events: {len(dialogues)}")

optimized_dialogues = []
BLUR_TARGET = 760  # Must exceed 741px blur
MAX_TARGET = 960   # Safe margins from 1080p borders (>= 60px padding)

for idx, d in enumerate(dialogues):
    parts = d.split(',', 9)
    if len(parts) >= 10:
        raw_text = parts[9]
        clean_text = re.sub(r'\{.*?\}', '', raw_text)
        
        # Measure using PIL font at 126
        bb = font_pil.getbbox(clean_text)
        # In PIL, font size 126 produces width slightly larger than libass (ratio ~0.64)
        # We calibrated: 'ke ped par maaro' in PIL 126 bbox is 1206 px; in libass it renders 772 px.
        # Calibration ratio = 772 / 1206 = 0.6401
        pil_w = bb[2] - bb[0]
        libass_w = int(round(pil_w * 0.6401 + 18)) # +18 for 9px outline on both sides
        
        scale_x = 100
        if libass_w < BLUR_TARGET:
            scale_x = int(round((775 / libass_w) * 100))
        elif libass_w > MAX_TARGET:
            scale_x = int(round((945 / libass_w) * 100))
            
        final_w = int(round(libass_w * (scale_x / 100.0)))
        
        if scale_x != 100:
            tagged_text = f"{{\\fscx{scale_x}}}{clean_text}"
        else:
            tagged_text = clean_text
            
        parts[9] = tagged_text
        opt_line = ','.join(parts)
        optimized_dialogues.append(opt_line)
        print(f"[{idx+1:2d}] {clean_text:28s} | base: {libass_w:4d}px -> scale: {scale_x:3d}% -> final: {final_w:4d}px")

# Reconstruct ASS file
final_ass_content = '\n'.join(header_lines + optimized_dialogues) + '\n'

with open(ass_path, 'w', encoding='utf-8') as f:
    f.write(final_ass_content)

print("\n[+] Wrote fully optimized ASS successfully!")
