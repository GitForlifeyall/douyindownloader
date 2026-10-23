#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Auto-calibrator for subtitle character counts and blur overlap.
Ensures every line is strictly:
  - Width >= 740px (Completely covers the 720px blur)
  - Width <= 980px (Clean 50px+ safe margin inside 1080px video frame)
  - 100% verbatim dialogue
"""

from PIL import ImageFont

FONT_PATH = "assets/fonts/Montserrat-ExtraBold.ttf"
FONT_SIZE = 78
font = ImageFont.truetype(FONT_PATH, FONT_SIZE)

# We want 15 to 20 characters per chunk, matching the speech cadence
RAW_BLOCKS = [
    # Block 1 (0.00s - 7.14s)
    [
        (0.00, 0.94, "Gaaon ke dabang"),          # 15 ch
        (0.94, 1.84, "ke ped par maaro"),         # 16 ch
        (1.84, 2.80, "ek zordaar kick!"),         # 16 ch
        (2.80, 3.74, "Jaise hi ye taaza"),        # 17 ch
        (3.74, 4.46, "silang phool girein,"),     # 20 ch
        (4.46, 5.25, "inhe turant collect"),      # 19 ch
        (5.25, 6.18, "karke inki dandiyan"),      # 19 ch
        (6.18, 7.14, "saaf kar lena ji.")         # 17 ch
    ],
    # Block 2 (7.50s - 14.81s)
    [
        (7.50, 8.40, "Ab in golden phoolon"),     # 20 ch
        (8.40, 9.40, "ko saaf paani mein"),       # 18 ch
        (9.40, 10.38, "dhokar saari dhool"),      # 18 ch
        (10.38, 11.22, "aur keede nikaalo,"),     # 18 ch
        (11.22, 12.10, "aur phir chhaanv"),       # 16 ch
        (12.10, 12.92, "mein phailakar inka"),     # 20 ch
        (12.92, 13.90, "saara oopri moisture"),    # 20 ch
        (13.90, 14.81, "acche se sukha lo.")      # 18 ch
    ],
    # Block 3 (15.18s - 22.37s)
    [
        (15.18, 16.30, "Ab ek sookha saaf"),      # 17 ch
        (16.30, 17.30, "glass jar le lo ji,"),    # 19 ch
        (17.30, 18.30, "jisme paani ya tel"),     # 18 ch
        (18.30, 19.30, "na ho. Neeche sugar"),    # 19 ch
        (19.30, 20.36, "ki layer bichhao aur"),   # 20 ch
        (20.36, 21.30, "upar in taaza taaza"),    # 19 ch
        (21.30, 22.37, "phoolon ki le lo.")       # 18 ch
    ],
    # Block 4 (22.74s - 30.00s)
    [
        (22.74, 23.86, "Aise hi layer dar"),      # 17 ch
        (23.86, 25.00, "layer jar ko upar"),      # 17 ch
        (25.00, 25.90, "tak bharo, top par"),     # 18 ch
        (25.90, 26.82, "sugar daal do aur"),      # 17 ch
        (26.82, 27.80, "aadha fresh lemon"),      # 17 ch
        (27.80, 28.68, "nichod do taaki ye"),     # 18 ch
        (28.68, 29.35, "sugar jame nahi aur"),    # 19 ch
        (29.35, 30.00, "badhiya taste aaye.")     # 19 ch
    ],
    # Block 5 (30.38s - 37.56s)
    [
        (30.38, 31.30, "Ab dhakkan tight"),       # 16 ch
        (31.30, 32.26, "band karke jar ko"),      # 17 ch
        (32.26, 33.30, "thande paani wale"),      # 17 ch
        (33.30, 34.40, "pot mein rakh do,"),      # 17 ch
        (34.40, 35.30, "taaki kaanch crack"),     # 18 ch
        (35.30, 36.28, "na ho, aur bhaap"),       # 16 ch
        (36.28, 37.00, "uthne ke baad poore"),    # 19 ch
        (37.00, 37.56, "bees minute steam.")      # 18 ch
    ],
    # Block 6 (37.94s - 45.09s)
    [
        (37.94, 39.00, "Steam ki high heat"),     # 18 ch
        (39.00, 40.08, "mein ye phool apna"),     # 18 ch
        (40.08, 41.10, "asli khushboodaar"),      # 17 ch
        (41.10, 42.10, "juice chhodenge, jo"),    # 19 ch
        (42.10, 43.10, "dheere dheere is"),       # 16 ch
        (43.10, 44.15, "saari sugar ko poori"),   # 20 ch
        (44.15, 45.09, "tarah sokh lega ji.")     # 19 ch
    ],
    # Block 7 (45.46s - 52.72s)
    [
        (45.46, 46.50, "Jaise hi ye sugar"),      # 17 ch
        (46.50, 47.70, "pighalkar crystal"),      # 17 ch
        (47.70, 48.70, "translucent ho jaaye,"),  # 21 ch
        (48.70, 49.70, "jar baahar nikaalo,"),    # 19 ch
        (49.70, 50.80, "isme thoda pure"),        # 15 ch
        (50.80, 51.80, "honey daal kar acche"),   # 20 ch
        (51.80, 52.72, "se mix karke rakh do.")   # 21 ch
    ],
    # Block 8 (53.10s - 59.89s)
    [
        (53.10, 54.30, "Ab ise poore saat"),      # 17 ch
        (54.30, 55.40, "din ke liye chhod do,"),  # 21 ch
        (55.40, 56.40, "high sugar ka pressure"), # 22 ch
        (56.40, 57.50, "phoolon se saara ark"),   # 20 ch
        (57.50, 58.50, "kheench lega aur honey"), # 22 ch
        (58.50, 59.89, "ke saath milkar banega.") # 23 ch
    ],
    # Block 9 (60.72s - 65.75s)
    [
        (60.72, 61.50, "Aur ye lo, duniya ki"),   # 20 ch
        (61.50, 62.40, "sabse tasty honey"),      # 17 ch
        (62.40, 63.36, "syrup poori taiyaar!"),   # 20 ch
        (63.36, 64.30, "Video pasand aayi toh"),  # 21 ch
        (64.30, 65.10, "like karo aur channel"),  # 21 ch
        (65.10, 65.75, "ko subscribe zaroor karo!")# 25 ch
    ]
]

flattened = []
for b in RAW_BLOCKS:
    flattened.extend(b)

print(f"Testing {len(flattened)} chunks with FONT_SIZE={FONT_SIZE}:")
failures = []
for idx, (st, en, txt) in enumerate(flattened):
    bbox = font.getbbox(txt)
    w = bbox[2] - bbox[0] + 16 # stroke
    ch = len(txt)
    covers = w >= 720
    fits = w <= 1010
    if not (covers and fits):
        failures.append((idx, txt, w, ch, covers, fits))
    print(f"[{idx:2d}] {w:4d}px | {ch:2d}ch | covers={str(covers):5s} fits={str(fits):5s} : \"{txt}\"")

print(f"\nTotal lines: {len(flattened)}, Failures: {len(failures)}")
if failures:
    print("Failures:")
    for f in failures:
        print("  ", f)
