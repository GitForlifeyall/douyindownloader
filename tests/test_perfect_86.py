from PIL import ImageFont

font = ImageFont.truetype('assets/fonts/Montserrat-ExtraBold.ttf', 86)

# Test phrases tuned to 15-20 chars:
phrases = [
    # Block 1
    ("Gaaon ke dabang", 0.00, 0.94),
    ("ke ped par maaro", 0.94, 1.84),
    ("ek zordaar kick maaro!", 1.84, 2.80),
    ("Jaise hi ye khushboodaar", 2.80, 3.80),
    ("silang phool neeche girein,", 3.80, 4.80),
    ("inhe turant collect karke", 4.80, 5.90),
    ("inki dandiyan saaf kar lo.", 5.90, 7.14),

    # Block 2
    ("Ab in golden phoolon ko", 7.50, 8.60),
    ("saaf paani mein dhokar", 8.60, 9.80),
    ("dhool aur keede nikaal do,", 9.80, 11.00),
    ("aur phir chhaanv mein", 11.00, 12.10),
    ("phailakar inka saara", 12.10, 13.20),
    ("oopri moisture sukha lo.", 13.20, 14.81),

    # Block 3
    ("Ab ek sookha saaf glass", 15.18, 16.50),
    ("jar le lo jisme paani", 16.50, 17.80),
    ("ya tel na ho. Neeche", 17.80, 19.10),
    ("sugar ki ek layer bichhao", 19.10, 20.60),
    ("aur uske upar taaza phool.", 20.60, 22.37),

    # Block 4
    ("Aise hi layer dar layer", 22.74, 24.20),
    ("jar ko upar tak bharo,", 24.20, 25.60),
    ("top par sugar daal kar", 25.60, 27.00),
    ("aadha fresh lemon nichodo", 27.00, 28.50),
    ("taaki sugar jame nahi aur", 28.50, 30.00),

    # Block 5
    ("Ab dhakkan tight band karo,", 30.38, 31.80),
    ("jar ko thande paani wale", 31.80, 33.20),
    ("pot mein rakh do taaki", 33.20, 34.60),
    ("kaanch crack na ho, aur", 34.60, 36.00),
    ("bees minute tak steam karo.", 36.00, 37.56),

    # Block 6
    ("Steam ki high heat mein ye", 37.94, 39.50),
    ("phool apna asli khushboodaar", 39.50, 41.20),
    ("juice chhodenge, jo dheere", 41.20, 42.80),
    ("dheere is saari sugar ko", 42.80, 44.00),
    ("poori tarah sokh lega.", 44.00, 45.09),

    # Block 7
    ("Jaise hi sugar pighalkar", 45.46, 46.90),
    ("crystal jaisi translucent", 46.90, 48.40),
    ("ho jaaye, jar baahar nikaalo,", 48.40, 49.90),
    ("isme thoda pure honey daalo", 49.90, 51.30),
    ("aur chhaanv mein rakh do.", 51.30, 52.72),

    # Block 8
    ("Ab ise poore saat din ke", 53.10, 54.80),
    ("liye chhod do, high sugar", 54.80, 56.40),
    ("ka pressure phoolon se", 56.40, 57.80),
    ("saara ark kheench lega aur", 57.80, 59.00),
    ("gaadha syrup bana dega.", 59.00, 59.89),

    # Block 9
    ("Aur ye lo, duniya ki sabse", 60.72, 62.00),
    ("tasty honey syrup taiyaar!", 62.00, 63.30),
    ("Video pasand aayi toh like", 63.30, 64.50),
    ("karo aur subscribe zaroor karo!", 64.50, 65.75)
]

print("=== VERIFYING TUNED CHUNKS AT FONT SIZE 86 ===")
failures = []
for idx, (txt, st, en) in enumerate(phrases):
    bbox = font.getbbox(txt)
    w = bbox[2] - bbox[0] + 18
    ch = len(txt)
    covers = w >= 730
    fits = w <= 1020
    if not (covers and fits):
        failures.append((idx, txt, w, ch, covers, fits))
    status = "OK" if covers and fits else "FAIL"
    print(f"[{idx:2d}] {w:4d}px | {ch:2d}ch | {status:4s} : \"{txt}\"")

print(f"\nTotal: {len(phrases)}, Failures: {len(failures)}")
