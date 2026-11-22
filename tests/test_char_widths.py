from PIL import ImageFont

font_path = 'assets/fonts/Montserrat-ExtraBold.ttf'

test_phrases = [
    # 10 chars
    "ke ped par",
    # 12 chars
    "saaf kar lo.",
    # 13 chars
    "Jaise hi ye",
    "collect karke",
    # 14 chars
    "kick! Jaise hi",
    "neeche girein,",
    # 15 chars
    "Gaaon ke dabang",
    "silang ke phool",
    # 16 chars
    "maaro ek zordaar",
    "ke ped par maaro",
    "ek zordaar kick!",
    # 17 chars
    "ye khushboodaar",
    "inhe turant saaf",
    # 18 chars
    "khushboodaar phool",
    "inka saara oopri",
    # 19 chars
    "inhe turant collect",
    # 20 chars
    "collect karke inki",
    # 21 chars
    "inki dandiyan saaf kar"
]

for size in [80, 85, 90, 95]:
    font = ImageFont.truetype(font_path, size)
    print(f"\n=================== FONT SIZE {size} ===================")
    for p in test_phrases:
        bbox = font.getbbox(p)
        w = bbox[2] - bbox[0] + 16 # with outline stroke
        fits_screen = "OK" if w <= 1000 else "EXCEEDS SCREEN!"
        covers_blur = "COVERS (>=720px)" if w >= 720 else f"TOO SHORT ({w} < 720px)"
        print(f"{len(p):2d} chars | {w:4d} px | {covers_blur:18s} | {fits_screen:15s} : \"{p}\"")
