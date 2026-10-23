from PIL import ImageFont

FONT_PATH = 'assets/fonts/Montserrat-ExtraBold.ttf'
font = ImageFont.truetype(FONT_PATH, 106)

# Calibrated: in libass, width = pil_w * 0.6401 + 16 (for 8px stroke)
def get_rendered_width(text):
    bb = font.getbbox(text)
    pil_w = bb[2] - bb[0]
    return int(round(pil_w * 0.725 + 16)) # calibrated for fs=106

# Let's test lines and verify
lines = [
    # Block 1
    ("Gaaon ke dabang ped par", 0.00, 1.40),
    ("maaro ek zordaar kick!", 1.40, 2.80),
    ("Jaise hi ye khushboodaar", 2.80, 4.10),
    ("phool neeche girte hi,", 4.10, 5.25),
    ("inhe turant collect karke", 5.25, 6.20),
    ("dandiyan saaf kar lena ji.", 6.20, 7.14),

    # Block 2
    ("Ab in golden phoolon ko", 7.50, 8.80),
    ("saaf paani mein dhokar", 8.80, 10.10),
    ("dhool aur keede nikaalo,", 10.10, 11.40),
    ("aur phir chhaanv mein", 11.40, 12.50),
    ("phailakar inka saara", 12.50, 13.60),
    ("oopri moisture sukha lo.", 13.60, 14.81),

    # Block 3
    ("Ab ek sookha saaf glass", 15.18, 16.70),
    ("jar le lo jisme paani", 16.70, 18.10),
    ("ya tel na ho, neeche", 18.10, 19.50),
    ("sugar ki ek layer bichhao", 19.50, 20.90),
    ("aur upar taaza phoolon ki.", 20.90, 22.37),

    # Block 4
    ("Aise hi layer dar layer", 22.74, 24.10),
    ("jar ko upar tak bharo,", 24.10, 25.30),
    ("top par sugar daal kar", 25.30, 26.60),
    ("aadha fresh lemon nichodo", 26.60, 28.00),
    ("taaki sugar jame nahi aur", 28.00, 29.00),
    ("badhiya sa taste aaye.", 29.00, 30.00),

    # Block 5
    ("Ab dhakkan tight band karo,", 30.38, 31.80),
    ("jar ko thande paani wale", 31.80, 33.20),
    ("pot mein rakh do taaki", 33.20, 34.60),
    ("kaanch crack na ho, aur", 34.60, 36.00),
    ("bees minute steam karo.", 36.00, 37.56),

    # Block 6
    ("Steam ki high heat mein", 37.94, 39.40),
    ("ye phool apna asli juice", 39.40, 40.90),
    ("chhodenge, jo dheere", 40.90, 42.40),
    ("dheere is saari sugar ko", 42.40, 43.80),
    ("poori tarah sokh lega.", 43.80, 45.09),

    # Block 7
    ("Jaise hi sugar pighalkar", 45.46, 46.90),
    ("crystal jaisi translucent", 46.90, 48.30),
    ("ho jaaye, jar nikaalo,", 48.30, 49.70),
    ("isme thoda pure honey daalo", 49.70, 51.20),
    ("aur acche se mix kar do.", 51.20, 52.72),

    # Block 8
    ("Ab ise poore saat din ke", 53.10, 54.50),
    ("liye chhod do, high sugar", 54.50, 55.90),
    ("ka pressure phoolon se", 55.90, 57.20),
    ("saara ark kheench lega aur", 57.20, 58.50),
    ("honey ka syrup banega.", 58.50, 59.89),

    # Block 9
    ("Aur ye lo, duniya ki sabse", 60.72, 62.00),
    ("tasty honey syrup taiyaar!", 62.00, 63.30),
    ("Video pasand aayi toh like", 63.30, 64.50),
    ("karo aur subscribe karo!", 64.50, 65.75)
]

print(f"Total lines: {len(lines)}")
for idx, (txt, st, en) in enumerate(lines):
    w = get_rendered_width(txt)
    print(f"[{idx+1:2d}] {w:4d}px ({len(txt):2d}ch) : '{txt}'")
