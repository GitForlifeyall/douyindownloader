import cv2
import numpy as np
import subprocess
from pathlib import Path
from PIL import ImageFont

# Candidate blocks with naturally balanced word counts (3 to 5 words, 18-24 chars per line)
BLOCKS = [
    # Block 1 (0.00 - 7.14)
    (0.00, 7.14, [
        "Gaaon ke dabang ke ped",        # 22 ch, 5 w
        "par maaro zordaar kick!",       # 23 ch, 4 w
        "Jaise hi ye khushboodaar",      # 24 ch, 4 w
        "phool neeche girte hi,",        # 22 ch, 4 w
        "inhe turant collect karke",     # 25 ch, 4 w
        "dandiyan saaf kar lena ji."     # 26 ch, 5 w
    ]),
    
    # Block 2 (7.50 - 14.81)
    (7.50, 14.81, [
        "Ab in golden phoolon ko",       # 23 ch, 5 w
        "saaf paani mein dhokar",        # 22 ch, 4 w
        "dhool aur keede nikaalo,",      # 24 ch, 4 w
        "aur phir chhaanv mein",         # 21 ch, 4 w
        "phailakar inka saara",          # 20 ch, 3 w
        "oopri moisture sukha lo."       # 24 ch, 4 w
    ]),

    # Block 3 (15.18 - 22.37)
    (15.18, 22.37, [
        "Ab ek sookha saaf glass",       # 23 ch, 5 w
        "jar le lo jisme paani",         # 21 ch, 5 w
        "ya tel na ho, neeche",          # 20 ch, 5 w
        "sugar ki ek layer bichhao",     # 25 ch, 5 w
        "aur uske upar in phoolon ki."   # 27 ch, 6 w
    ]),

    # Block 4 (22.74 - 30.00)
    (22.74, 30.00, [
        "Aise hi layer dar layer",       # 23 ch, 5 w
        "jar ko upar tak bharo,",        # 22 ch, 5 w
        "top par sugar daal kar",        # 22 ch, 5 w
        "aadha fresh lemon nichodo",     # 25 ch, 4 w
        "taaki sugar jame nahi aur",     # 25 ch, 5 w
        "ekdum badhiya taste aaye."      # 25 ch, 4 w
    ]),

    # Block 5 (30.38 - 37.56)
    (30.38, 37.56, [
        "Ab dhakkan tight band karke",   # 27 ch, 5 w
        "jar ko thande paani wale",      # 24 ch, 5 w
        "pot mein rakh do taaki",        # 22 ch, 5 w
        "kaanch crack na ho, aur",       # 23 ch, 5 w
        "bees minute steam karo."        # 23 ch, 4 w
    ]),

    # Block 6 (37.94 - 45.09)
    (37.94, 45.09, [
        "Steam ki high heat mein",       # 23 ch, 5 w
        "ye phool apna asli juice",      # 24 ch, 5 w
        "chhodenge, jo dheere dheere",   # 27 ch, 4 w
        "is saari sugar ko poori",       # 23 ch, 5 w
        "tarah sokh lega."               # 16 ch -> let's test or make: "tarah apne andar sokh lega." (29 ch)
    ]),

    # Block 7 (45.46 - 52.72)
    (45.46, 52.72, [
        "Jaise hi ye sugar pighalkar",   # 27 ch, 5 w
        "crystal jaisi translucent",     # 25 ch, 3 w
        "ho jaaye, jar baahar nikaalo,", # 29 ch, 5 w
        "isme thoda pure honey daalo",   # 27 ch, 5 w
        "aur acche se mix karke rakho."  # 29 ch, 6 w
    ]),

    # Block 8 (53.10 - 59.89)
    (53.10, 59.89, [
        "Ab ise poore saat din ke",      # 24 ch, 6 w
        "liye chhod do, high sugar",     # 25 ch, 5 w
        "ka pressure saara ark",         # 21 ch, 4 w
        "phoolon se kheench lega aur",   # 27 ch, 5 w
        "honey ke saath milkar banega."  # 29 ch, 5 w
    ]),

    # Block 9 (60.72 - 65.75)
    (60.72, 65.75, [
        "Aur ye lo, duniya ki sabse",    # 26 ch, 6 w
        "tasty honey syrup taiyaar!",    # 26 ch, 4 w
        "Video pasand aayi toh like",    # 26 ch, 5 w
        "karo aur subscribe zaroor karo!"# 31 ch, 5 w
    ])
]

print("Measuring all candidates at Fontsize 110, 112, 114 with PIL + libass calibration...")
font = ImageFont.truetype('assets/fonts/Montserrat-ExtraBold.ttf', 112)

# At fs=112:
# We know from test_natural_widths:
# 'Gaaon ke dabang ke ped' (22ch) rendered 963px
# 'phool neeche girte hi,' (22ch) rendered 848px
# 'phailakar inka saara' (20ch) rendered 783px
# Blur width is 741px! Target range: 750px to 970px!

all_lines = []
for b_idx, (st, en, lines) in enumerate(BLOCKS):
    for l in lines:
        all_lines.append(l)

print(f"Total lines: {len(all_lines)}")
