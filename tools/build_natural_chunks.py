import subprocess
import cv2
import numpy as np

# We tune every line across all 9 blocks to have the best number of words (21-26 characters)
# so that at Fontsize 105, every line naturally renders between 750px and 960px!

ALL_CHUNKS = [
    # Block 1 (0.00 - 7.14)
    # Spoken: "Gaaon ke dabang ke ped par maaro ek zordaar kick! Jaise hi ye taaza khushboo wale phool neeche girte hi, inhe turant collect karke inki dandiyan saaf kar lena ji."
    ("Gaaon ke dabang ped par", 0.00, 1.40),
    ("maaro ek zordaar kick!", 1.40, 2.80),
    ("Jaise hi ye khushboodaar", 2.80, 4.10),
    ("phool neeche girte hi,", 4.10, 5.25),
    ("inhe turant collect karke", 5.25, 6.20),
    ("dandiyan saaf kar lena ji.", 6.20, 7.14),

    # Block 2 (7.50 - 14.81)
    # Spoken: "Ab in golden phoolon ko saaf paani mein dhokar saari dhool aur keede nikaalo, aur phir chhaanv mein phailakar inka saara oopri moisture acche se sukha lo."
    ("Ab in golden phoolon ko", 7.50, 8.80),
    ("saaf paani mein dhokar", 8.80, 10.10),
    ("dhool aur keede nikaalo,", 10.10, 11.40),
    ("aur phir chhaanv mein", 11.40, 12.50),
    ("phailakar inka saara oopri", 12.50, 13.60),
    ("moisture acche se sukha lo.", 13.60, 14.81),

    # Block 3 (15.18 - 22.37)
    # Spoken: "Ab ek sookha saaf glass jar le lo jisme paani ya tel na ho, neeche sugar ki ek layer bichhao aur uske upar in taaza phoolon ki."
    ("Ab ek sookha saaf glass jar", 15.18, 16.70),
    ("le lo jisme paani ya tel", 16.70, 18.10),
    ("na ho, neeche sugar ki", 18.10, 19.50),
    ("ek layer acche se bichhao", 19.50, 20.90),
    ("aur uske upar taaza phool.", 20.90, 22.37),

    # Block 4 (22.74 - 30.00)
    # Spoken: "Aise hi layer dar layer jar ko upar tak bharo, top par sugar daal kar aadha fresh lemon nichod do taaki sugar jame nahi aur badhiya taste aaye."
    ("Aise hi layer dar layer jar", 22.74, 24.20),
    ("ko upar tak bharo, top par", 24.20, 25.60),
    ("sugar daal kar aadha fresh", 25.60, 27.00),
    ("lemon nichod do taaki", 27.00, 28.50),
    ("sugar jame nahi aur swaad aaye.", 28.50, 30.00),

    # Block 5 (30.38 - 37.56)
    # Spoken: "Ab dhakkan tight band karke jar ko thande paani wale pot mein rakh do, taaki kaanch crack na ho, aur bhaap uthne ke baad poore bees minute steam karo."
    ("Ab dhakkan tight band karke", 30.38, 31.80),
    ("jar ko thande paani wale", 31.80, 33.20),
    ("pot mein rakh do taaki", 33.20, 34.60),
    ("kaanch crack na ho, aur", 34.60, 36.00),
    ("poore bees minute steam karo.", 36.00, 37.56),

    # Block 6 (37.94 - 45.09)
    # Spoken: "Steam ki high heat mein ye phool apna asli khushboodaar juice chhodenge, jo dheere dheere is saari sugar ko poori tarah sokh lega."
    ("Steam ki high heat mein ye", 37.94, 39.40),
    ("phool apna asli khushboodaar", 39.40, 40.90),
    ("juice chhodenge, jo dheere", 40.90, 42.40),
    ("dheere is saari sugar ko", 42.40, 43.80),
    ("poori tarah apne andar sokhega.", 43.80, 45.09),

    # Block 7 (45.46 - 52.72)
    # Spoken: "Jaise hi ye sugar pighalkar crystal jaisi translucent ho jaaye, jar baahar nikaalo, isme thoda pure honey daalkar acche se mix karke rakh do."
    ("Jaise hi ye sugar pighalkar", 45.46, 46.90),
    ("crystal jaisi translucent", 46.90, 48.30),
    ("ho jaaye, jar baahar nikaalo,", 48.30, 49.70),
    ("isme thoda pure honey daalo", 49.70, 51.20),
    ("aur acche se mix karke rakho.", 51.20, 52.72),

    # Block 8 (53.10 - 59.89)
    # Spoken: "Ab ise poore saat din ke liye chhod do, high sugar ka pressure phoolon se saara ark kheench lega aur honey ke saath milkar banega."
    ("Ab ise poore saat din ke", 53.10, 54.50),
    ("liye chhod do, high sugar", 54.50, 55.90),
    ("ka pressure phoolon se saara", 55.90, 57.20),
    ("ark kheench lega aur honey", 57.20, 58.50),
    ("ke saath milkar banega syrup.", 58.50, 59.89),

    # Block 9 (60.72 - 65.75)
    # Spoken: "Aur ye lo, duniya ki sabse tasty honey syrup poori taiyaar hai! Video pasand aayi toh like karo aur channel ko subscribe zaroor karo!"
    ("Aur ye lo, duniya ki sabse", 60.72, 62.00),
    ("tasty honey syrup taiyaar!", 62.00, 63.30),
    ("Video pasand aayi toh like", 63.30, 64.50),
    ("karo aur subscribe zaroor karo!", 64.50, 65.75)
]

print(f"Total proposed natural lines: {len(ALL_CHUNKS)}")

ass_template = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Montserrat ExtraBold,106,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,8.0,2.0,2,20,20,360,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:05.00,Default,,0,0,0,,{text}
"""

clean = cv2.imread('test_new_clean_frame_1s.png')

failures = []
for idx, (txt, st, en) in enumerate(ALL_CHUNKS):
    with open('temp_chunk.ass', 'w', encoding='utf-8') as tf:
        tf.write(ass_template.format(text=txt))
    cmd = ['ffmpeg', '-y', '-i', 'test_new_clean_frame_1s.png', '-vf', "ass='temp_chunk.ass':fontsdir='assets/fonts'", '-frames:v', '1', 'temp_chunk.png']
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out = cv2.imread('temp_chunk.png')
    diff = np.abs(clean.astype(float) - out.astype(float)).sum(axis=2)
    ys, xs = np.where(diff > 5)
    w = xs.max() - xs.min()
    covers = w >= 740
    fits = w <= 980
    status = "PERFECT" if (covers and fits) else ("SHORT" if not covers else "WIDE")
    if not (covers and fits):
        failures.append((idx+1, txt, w, status))
    print(f"[{idx+1:2d}] {w:4d}px ({len(txt):2d}ch, {len(txt.split()):1d}w) [{status:7s}] : '{txt}'")

print(f"\nCompleted: {len(ALL_CHUNKS)} lines, Failures: {len(failures)}")
