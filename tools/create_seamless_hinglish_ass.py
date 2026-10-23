import json
from pathlib import Path

# Clean natural Hinglish dialogue events with natural word groupings (1 to 4 words per event)
# All words verbatim from our master translation, fitting comfortably inside the 776px permanent blur plate.
RAW_EVENTS = [
    # Block 1
    (0.00, 0.94, "Gaaon ke dabang"),
    (0.94, 1.84, "ke ped par maaro"),
    (1.84, 2.80, "ek zordaar kick!"),
    (2.80, 3.74, "Jaise hi ye taaza"),
    (3.74, 4.46, "khushboo wale phool"),
    (4.46, 5.25, "neeche girte hi,"),
    (5.25, 6.18, "inhe turant collect"),
    (6.18, 6.66, "karke inki dandiyan"),
    (6.66, 7.50, "saaf kar lena ji."),

    # Block 2
    (7.50, 8.40, "Ab in golden phoolon"),
    (8.40, 9.40, "ko saaf paani mein"),
    (9.40, 10.38, "dhokar saari dhool"),
    (10.38, 11.22, "aur keede nikaalo,"),
    (11.22, 12.10, "aur phir chhaanv mein"),
    (12.10, 12.92, "phailakar inka saara"),
    (12.92, 13.90, "oopri moisture"),
    (13.90, 15.18, "acche se sukha lo."),

    # Block 3
    (15.18, 16.30, "Ab ek sookha saaf"),
    (16.30, 17.30, "glass jar le lo"),
    (17.30, 18.30, "jisme paani ya tel"),
    (18.30, 19.30, "na ho, neeche sugar"),
    (19.30, 20.36, "ki ek layer bichhao"),
    (20.36, 21.30, "aur uske upar in"),
    (21.30, 22.74, "taaza phoolon ki."),

    # Block 4
    (22.74, 23.86, "Aise hi layer dar"),
    (23.86, 25.00, "layer jar ko upar"),
    (25.00, 25.90, "tak bharo, top par"),
    (25.90, 26.82, "sugar daal kar"),
    (26.82, 27.80, "aadha fresh lemon"),
    (27.80, 28.68, "nichod do taaki"),
    (28.68, 29.35, "sugar jame nahi aur"),
    (29.35, 30.38, "badhiya taste aaye."),

    # Block 5
    (30.38, 31.30, "Ab dhakkan tight"),
    (31.30, 32.26, "band karke jar ko"),
    (32.26, 33.30, "thande paani wale"),
    (33.30, 34.40, "pot mein rakh do,"),
    (34.40, 35.30, "taaki kaanch crack"),
    (35.30, 36.28, "na ho, aur bhaap"),
    (36.28, 37.00, "uthne ke baad poore"),
    (37.00, 37.94, "bees minute steam karo."),

    # Block 6
    (37.94, 39.00, "Steam ki high heat"),
    (39.00, 40.08, "mein ye phool apna"),
    (40.08, 41.10, "asli khushboodaar"),
    (41.10, 42.10, "juice chhodenge, jo"),
    (42.10, 43.10, "dheere dheere is"),
    (43.10, 44.15, "saari sugar ko poori"),
    (44.15, 45.46, "tarah sokh lega."),

    # Block 7
    (45.46, 46.50, "Jaise hi ye sugar"),
    (46.50, 47.70, "pighalkar crystal jaisi"),
    (47.70, 48.70, "translucent ho jaaye,"),
    (48.70, 49.70, "jar baahar nikaalo,"),
    (49.70, 50.80, "isme thoda pure"),
    (50.80, 51.80, "honey daalkar acche"),
    (51.80, 53.10, "se mix karke rakh do."),

    # Block 8
    (53.10, 54.30, "Ab ise poore saat"),
    (54.30, 55.40, "din ke liye chhod do,"),
    (55.40, 56.40, "high sugar ka pressure"),
    (56.40, 57.50, "phoolon se saara ark"),
    (57.50, 58.50, "kheench lega aur honey"),
    (58.50, 60.72, "ke saath milkar banega."),

    # Block 9
    (60.72, 61.50, "Aur ye lo, duniya ki"),
    (61.50, 62.40, "sabse tasty honey syrup"),
    (62.40, 63.36, "poori taiyaar hai!"),
    (63.36, 64.30, "Video pasand aayi toh"),
    (64.30, 65.10, "like karo aur channel"),
    (65.10, 66.70, "ko subscribe zaroor karo!")
]

def to_ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

# Build continuous timeline: event[i].end = event[i+1].start
# Last event.end = 66.70 (exact video duration)
seamless_events = []
video_end = 66.70

for i in range(len(RAW_EVENTS)):
    st, en, txt = RAW_EVENTS[i]
    if i < len(RAW_EVENTS) - 1:
        next_st = RAW_EVENTS[i+1][0]
        # End exactly when the next begins, leaving ZERO blank frames
        real_end = next_st
    else:
        real_end = video_end
    seamless_events.append((st, real_end, txt))

# Write ASS file
ass_header = """[Script Info]
; Script generated with Continuous Presence & Maximum Boundary Blur
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Montserrat ExtraBold,96,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,8.0,2.0,2,40,40,385,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

ass_lines = [ass_header.strip()]
for st, en, txt in seamless_events:
    t_st = to_ass_time(st)
    t_en = to_ass_time(en)
    # 100% natural typography: NO fscx, NO squeeze, NO stretch!
    ass_lines.append(f"Dialogue: 0,{t_st},{t_en},Default,,0,0,0,,{txt}")

final_ass = '\n'.join(ass_lines) + '\n'

out_path = Path('output/subtitles/道可道 - 恭喜你成功制作出桂花蜜_hinglish.ass')
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(final_ass)

print(f"[+] Wrote {len(seamless_events)} seamless continuous dialogue lines to hinglish.ass")
print(f"[+] First event start: {seamless_events[0][0]}s, Last event end: {seamless_events[-1][1]}s")
print(f"[+] Gap between any consecutive events: EXACTLY 0.00s (subtitles always remain on screen)")
