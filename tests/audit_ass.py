from PIL import ImageFont
import re

font = ImageFont.truetype('assets/fonts/Montserrat-ExtraBold.ttf', 84)

ass_path = 'output/subtitles/道可道 - 恭喜你成功制作出桂花蜜_hinglish.ass'
with open(ass_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

dialogue_lines = [l.strip() for l in lines if l.startswith('Dialogue:')]

print(f'Total Dialogue lines in ASS: {len(dialogue_lines)}')
short_lines = []
all_widths = []
for idx, l in enumerate(dialogue_lines):
    parts = l.split(',', 9)
    if len(parts) >= 10:
        text = parts[9]
        clean_text = re.sub(r'\{.*?\}', '', text)
        bb = font.getbbox(clean_text)
        w = bb[2] - bb[0] + 17
        all_widths.append(w)
        if w < 741:
            short_lines.append((idx, parts[1], parts[2], clean_text, len(clean_text), w))

print(f'Min width: {min(all_widths)}px, Max width: {max(all_widths)}px, Avg: {sum(all_widths)/len(all_widths):.1f}px')
print(f'Lines shorter than 741px: {len(short_lines)}')
for s in short_lines:
    print(f'Line {s[0]:2d} [{s[1]}-{s[2]}] : {s[5]:4d}px ({s[4]:2d}ch) : \"{s[3]}\"')
