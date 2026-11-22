import re
from PIL import ImageFont

FONT_PATH = 'assets/fonts/Montserrat-ExtraBold.ttf'
FONT_SIZE = 84
STROKE_WIDTH = 8.5
BLUR_WIDTH_TARGET = 750  # Overlap 741px blur with safety margin
MAX_WIDTH_TARGET = 960   # Safe margin from 1080p video border (at least 60px padding on each side)

font = ImageFont.truetype(FONT_PATH, FONT_SIZE)

ass_path = 'output/subtitles/道可道 - 恭喜你成功制作出桂花蜜_hinglish.ass'
with open(ass_path, 'r', encoding='utf-8') as f:
    content = f.read()

lines = content.splitlines()
out_lines = []

stats = {'modified': 0, 'total': 0, 'min_w': 9999, 'max_w': 0}

for line in lines:
    if line.startswith('Dialogue:'):
        stats['total'] += 1
        parts = line.split(',', 9)
        if len(parts) >= 10:
            raw_text = parts[9]
            clean_text = re.sub(r'\{.*?\}', '', raw_text)
            
            bbox = font.getbbox(clean_text)
            base_w = (bbox[2] - bbox[0]) + int(STROKE_WIDTH * 2)
            
            # Determine if horizontal scaling is required
            scale_x = 100
            if base_w < BLUR_WIDTH_TARGET:
                # Need to expand to fully cover blur
                target_w = 770
                scale_x = int(round((target_w / base_w) * 100))
            elif base_w > MAX_WIDTH_TARGET:
                # Scale down slightly so it doesn't touch video borders
                target_w = 940
                scale_x = int(round((target_w / base_w) * 100))
            
            final_w = int(base_w * (scale_x / 100.0))
            stats['min_w'] = min(stats['min_w'], final_w)
            stats['max_w'] = max(stats['max_w'], final_w)
            
            if scale_x != 100:
                stats['modified'] += 1
                tagged_text = f"{{\\fscx{scale_x}}}{clean_text}"
                parts[9] = tagged_text
                line = ','.join(parts)
                print(f"Line {stats['total']:2d} scaled to {scale_x}%: base={base_w}px -> final={final_w}px | '{clean_text}'")
            else:
                parts[9] = clean_text
                line = ','.join(parts)
                print(f"Line {stats['total']:2d} optimal   : {base_w}px | '{clean_text}'")

    out_lines.append(line)

print("\n================ STATS ================")
print(f"Total lines: {stats['total']}")
print(f"Modified with fscx: {stats['modified']}")
print(f"New Min Width: {stats['min_w']}px (Requirement: >= 741px blur)")
print(f"New Max Width: {stats['max_w']}px (Requirement: <= 980px 1080p margin)")
print("=======================================")

with open('output/subtitles/道可道 - 恭喜你成功制作出桂花蜜_hinglish.ass', 'w', encoding='utf-8') as f:
    f.write('\n'.join(out_lines) + '\n')

print("Saved optimized ASS successfully!")
