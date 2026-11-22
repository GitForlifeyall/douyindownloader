from PIL import ImageFont

FONT_PATH = 'assets/fonts/Montserrat-ExtraBold.ttf'

# Let's adjust words to keep every phrase around 16-20 characters:
test_chunks = [
    # Block 1 (0.00 - 7.14)
    'Gaaon ke dabang',           # 15ch
    'ke ped par maaro',          # 16ch
    'ek zordaar kick maaro!',    # 22ch -> let's check
    'Jaise hi ye taaza',         # 17ch
    'khushboodaar phool',        # 18ch
    'neeche girte hi,',          # 16ch
    'inhe turant collect',       # 19ch
    'karke inki dandiyan',       # 19ch
    'saaf kar lena ji.',         # 17ch
]

for fs in [84, 86, 88]:
    font = ImageFont.truetype(FONT_PATH, fs)
    print(f"\n=== FONT SIZE {fs} ===")
    for c in test_chunks:
        bb = font.getbbox(c)
        w = bb[2] - bb[0] + 17
        print(f"{w:4d}px ({len(c):2d}ch) : '{c}'")
