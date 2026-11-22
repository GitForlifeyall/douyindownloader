from PIL import ImageFont

font = ImageFont.truetype('assets/fonts/Montserrat-ExtraBold.ttf', 92)

# Candidate chunks for all 9 blocks
CANDIDATES = [
    # Block 1 (0.00 - 7.14)
    (0.00, 0.85, "Gaaon ke dabang"),
    (0.85, 1.84, "ke ped par maaro"),
    (1.84, 2.80, "ek zordaar kick!"),
    (2.80, 3.74, "Jaise hi ye taaza"),
    (3.74, 4.46, "silang ke phool"),
    (4.46, 5.25, "neeche girte hi,"),
    (5.25, 6.18, "inhe turant collect"),
    (6.18, 6.70, "karke inki dandiyan"),
    (6.70, 7.14, "saaf kar lena."),

    # Block 2 (7.50 - 14.81)
    (7.50, 8.40, "Ab in golden phoolon"),
    (8.40, 9.40, "ko saaf paani mein"),
    (9.40, 10.38, "dhokar saari dhool"),
    (10.38, 11.22, "aur keede nikaalo,"),
    (11.22, 12.10, "aur phir chhaanv mein"),
    (12.10, 12.92, "phailakar inka"),
    (12.92, 13.90, "saara oopri moisture"),
    (13.90, 14.81, "acche se sukha lo."),

    # Block 3 (15.18 - 22.37)
    (15.18, 16.30, "Ab ek sookha saaf"),
    (16.30, 17.30, "glass jar le lo"),
    (17.30, 18.30, "jisme paani ya tel"),
    (18.30, 19.30, "na ho. Neeche sugar"),
    (19.30, 20.36, "ki ek layer bichhao"),
    (20.36, 21.30, "aur uske upar in"),
    (21.30, 22.37, "khushboodaar phoolon ki."),

    # Block 4 (22.74 - 30.00)
    (22.74, 23.86, "Aise hi layer dar"),
    (23.86, 25.00, "layer jar ko upar"),
    (25.00, 25.90, "tak bharo, top par"),
    (25.90, 26.82, "sugar daal kar"),
    (26.82, 27.80, "aadha fresh lemon"),
    (27.80, 28.68, "nichod do taaki"),
    (28.68, 29.35, "sugar jame nahi aur"),
    (29.35, 30.00, "badhiya taste aaye."),

    # Block 5 (30.38 - 37.56)
    (30.38, 31.30, "Ab dhakkan tight"),
    (31.30, 32.26, "band karke jar ko"),
    (32.26, 33.30, "thande paani wale"),
    (33.30, 34.40, "pot mein rakh do,"),
    (34.40, 35.30, "taaki kaanch crack"),
    (35.30, 36.28, "na ho, aur bhaap"),
    (36.28, 37.00, "uthne ke baad poore"),
    (37.00, 37.56, "bees minute steam karo."),

    # Block 6 (37.94 - 45.09)
    (37.94, 39.00, "Steam ki high heat"),
    (39.00, 40.08, "mein ye phool apna"),
    (40.08, 41.10, "asli khushboodaar"),
    (41.10, 42.10, "juice chhodenge, jo"),
    (42.10, 43.10, "dheere dheere is"),
    (43.10, 44.15, "saari sugar ko poori"),
    (44.15, 45.09, "tarah sokh lega."),

    # Block 7 (45.46 - 52.72)
    (45.46, 46.50, "Jaise hi sugar"),
    (46.50, 47.70, "pighalkar crystal jaisi"),
    (47.70, 48.70, "translucent ho jaaye,"),
    (48.70, 49.70, "jar baahar nikaalo,"),
    (49.70, 50.80, "isme thoda pure"),
    (50.80, 51.80, "honey daalkar acche"),
    (51.80, 52.72, "se mix karke rakh do."),

    # Block 8 (53.10 - 59.89)
    (53.10, 54.30, "Ab ise poore saat"),
    (54.30, 55.40, "din ke liye chhod do,"),
    (55.40, 56.40, "high sugar ka pressure"),
    (56.40, 57.50, "phoolon se saara ark"),
    (57.50, 58.50, "kheench lega aur honey"),
    (58.50, 59.89, "ke saath milkar banega."),

    # Block 9 (60.72 - 65.75)
    (60.72, 61.50, "Aur ye lo, duniya ki"),
    (61.50, 62.40, "sabse tasty honey syrup"),
    (62.40, 63.36, "poori taiyaar hai!"),
    (63.36, 64.30, "Video pasand aayi toh"),
    (64.30, 65.10, "like karo aur channel"),
    (65.10, 65.75, "ko subscribe zaroor karo!")
]

print("=== CANDIDATE CHUNK WIDTH VERIFICATION (Target: 720px - 980px) ===")
too_short = []
too_long = []
for idx, (st, en, txt) in enumerate(CANDIDATES):
    bbox = font.getbbox(txt)
    w = bbox[2] - bbox[0] + 16 # stroke
    chars = len(txt)
    status = "OK"
    if w < 720:
        status = "SHORT"
        too_short.append((idx, txt, w, chars))
    elif w > 990:
        status = "LONG"
        too_long.append((idx, txt, w, chars))
    print(f"[{idx:2d}] {w:4d} px | {chars:2d} ch | {status:5s} : \"{txt}\"")

print(f"\nSummary: Total={len(CANDIDATES)}, Too Short={len(too_short)}, Too Long={len(too_long)}")
