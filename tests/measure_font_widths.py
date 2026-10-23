from PIL import ImageFont, ImageDraw, Image
from pathlib import Path

font_path = 'assets/fonts/Montserrat-ExtraBold.ttf'

sample_texts = [
    'ke ped par',
    'Gaaon ke dabang',
    'Gaaon ke dabang ke ped par',
    'maaro ek zordaar kick!',
    'ye khushboodaar phool',
    'silang ke phool neeche',
    'inhe turant collect karke',
    'inki dandiyan saaf kar lo',
    'Ab in golden phoolon ko',
    'saaf paani mein dhokar',
    'dhool aur keede nikaal do'
]

for size in [85, 92, 96, 100, 105, 110]:
    font = ImageFont.truetype(font_path, size)
    print(f"\n=== Fontsize {size} ===")
    for text in sample_texts:
        bbox = font.getbbox(text)
        w = bbox[2] - bbox[0]
        # Include outline stroke (e.g. 8px on each side = +16px)
        total_w = w + 16
        print(f"  {total_w:4d} px ({len(text):2d} chars, {len(text.split()):2d} words): \"{text}\"")
