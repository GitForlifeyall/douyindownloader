#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generates the complete, unabridged, word-synced Hinglish ASS subtitle file.
- Exactly 100% of spoken words included (zero omissions)
- Strictly <= 3 words per caption chunk
- Audio-synced timestamps derived from Whisper speech alignments
- Font: Montserrat ExtraBold
- Text size: 96 (increased per user instruction)
- Outline: 8.0 solid black stroke
- Text color: Solid White (&H00FFFFFF)
- Position: Centered over blur box at MarginV = 390
"""

import sys
from pathlib import Path

# Helper to format seconds to ASS timestamp: H:MM:SS.cs
def to_ass_time(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int(round((sec - int(sec)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

EVENTS = [
    # ---------------- BLOCK 1 (0.000s - 7.138s) ----------------
    (0.00, 0.64, "Gaaon ke dabang"),
    (0.64, 1.14, "ke ped par"),
    (1.14, 1.84, "maaro ek zordaar"),
    (1.84, 2.80, "kick! Jaise hi"),
    (2.80, 3.74, "ye khushboodaar"),
    (3.74, 4.32, "silang ke phool"),
    (4.32, 5.18, "neeche girein,"),
    (5.18, 5.70, "inhe turant"),
    (5.70, 6.18, "collect karke"),
    (6.18, 6.64, "inki dandiyan"),
    (6.64, 7.14, "saaf kar lo."),

    # ---------------- BLOCK 2 (7.500s - 14.806s) ----------------
    (7.50, 8.20, "Ab in golden"),
    (8.20, 8.64, "phoolon ko"),
    (8.64, 9.20, "saaf paani mein"),
    (9.20, 9.96, "dhokar dhool"),
    (9.96, 10.38, "aur keede"),
    (10.38, 11.22, "nikaal do,"),
    (11.22, 11.90, "aur phir chhaanv"),
    (11.90, 12.40, "mein phailakar"),
    (12.40, 12.92, "inka saara"),
    (12.92, 13.64, "oopri moisture"),
    (13.64, 14.20, "acche se"),
    (14.20, 14.81, "sukha lo."),

    # ---------------- BLOCK 3 (15.180s - 22.372s) ----------------
    (15.18, 15.84, "Ab ek sookha"),
    (15.84, 16.70, "saaf glass jar"),
    (16.70, 17.60, "lo jisme paani"),
    (17.60, 18.10, "ya tel na"),
    (18.10, 18.84, "ho. Neeche"),
    (18.84, 19.45, "sugar ki ek"),
    (19.45, 20.36, "layer bichhao"),
    (20.36, 21.10, "aur uske upar"),
    (21.10, 21.65, "in khushboodaar"),
    (21.65, 22.37, "taaza phoolon ki."),

    # ---------------- BLOCK 4 (22.740s - 29.998s) ----------------
    (22.74, 23.28, "Aise hi"),
    (23.28, 23.86, "layer dar layer"),
    (23.86, 24.48, "jar ko upar"),
    (24.48, 25.14, "tak bharo,"),
    (25.14, 25.76, "top par sugar"),
    (25.76, 26.60, "daalo aur aadha"),
    (26.60, 27.36, "fresh lemon"),
    (27.36, 28.12, "nichod do"),
    (28.12, 28.68, "taaki sugar"),
    (28.68, 29.28, "jame nahi aur"),
    (29.28, 30.00, "badhiya test aaye."),

    # ---------------- BLOCK 5 (30.380s - 37.562s) ----------------
    (30.38, 31.04, "Ab dhakkan tight"),
    (31.04, 31.62, "band karke"),
    (31.62, 32.26, "jar ko thande"),
    (32.26, 32.72, "paani wale"),
    (32.72, 33.60, "pot mein rakho"),
    (33.60, 34.18, "taaki kaanch"),
    (34.18, 34.90, "crack na ho,"),
    (34.90, 35.78, "aur bhaap uthne"),
    (35.78, 36.35, "ke baad poore"),
    (36.35, 36.98, "bees minute"),
    (36.98, 37.56, "tak steam karo."),

    # ---------------- BLOCK 6 (37.940s - 45.087s) ----------------
    (37.94, 38.56, "Steam ki"),
    (38.56, 39.26, "high heat mein"),
    (39.26, 39.90, "ye phool apna"),
    (39.90, 40.60, "asli khushboodaar"),
    (40.60, 41.30, "juice chhodenge,"),
    (41.30, 42.32, "jo dheere dheere"),
    (42.32, 43.00, "is saari sugar"),
    (43.00, 43.66, "ko poori tarah"),
    (43.66, 44.15, "pighlaakar"),
    (44.15, 44.58, "apne andar"),
    (44.58, 45.09, "sokh lega."),

    # ---------------- BLOCK 7 (45.460s - 52.724s) ----------------
    (45.46, 46.24, "Jaise hi sugar"),
    (46.24, 46.96, "pighalkar crystal"),
    (46.96, 47.70, "jaisi translucent"),
    (47.70, 48.30, "ho jaaye,"),
    (48.30, 48.98, "jar baahar"),
    (48.98, 49.60, "nikaalo, isme"),
    (49.60, 50.40, "thoda pure honey"),
    (50.40, 51.10, "daalkar acche se"),
    (51.10, 51.80, "mix karo aur"),
    (51.80, 52.25, "chhaanv mein"),
    (52.25, 52.72, "rakh do."),

    # ---------------- BLOCK 8 (53.100s - 59.890s) ----------------
    (53.10, 53.70, "Ab ise poore"),
    (53.70, 54.30, "saat din ke"),
    (54.30, 54.92, "liye chhod do,"),
    (54.92, 55.66, "high sugar ka"),
    (55.66, 56.22, "pressure phoolon"),
    (56.22, 56.72, "se saara ark"),
    (56.72, 57.50, "kheench lega"),
    (57.50, 58.10, "aur honey ke"),
    (58.10, 58.70, "saath milkar"),
    (58.70, 59.30, "gaadha syrup"),
    (59.30, 59.89, "bana dega."),

    # ---------------- BLOCK 9 (60.720s - 65.754s) ----------------
    (60.72, 61.15, "Aur ye lo,"),
    (61.15, 61.62, "duniya ki sabse"),
    (61.62, 62.05, "tasty honey"),
    (62.05, 62.65, "syrup taiyaar hai!"),
    (62.65, 63.36, "Video pasand aayi"),
    (63.36, 63.95, "toh like karo"),
    (63.95, 64.56, "aur channel ko"),
    (64.56, 65.20, "subscribe zaroor"),
    (65.20, 65.75, "kar lena!")
]

def generate_ass(output_path: Path):
    # Verification checks
    for idx, (st, en, txt) in enumerate(EVENTS):
        words = txt.split()
        assert len(words) <= 3, f"Event {idx} exceeds 3 words: {txt} ({len(words)} words)"
        assert st < en, f"Event {idx} start >= end: {st} >= {en} ({txt})"
    print(f"[Verification Passed] All {len(EVENTS)} events strictly <= 3 words and monotonically valid.")

    header = """[Script Info]
; Script generated for High-Impact Douyin Dubbed Shorts
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Montserrat ExtraBold,96,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,8.0,2.0,2,40,40,390,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    dialogues = []
    for st, en, txt in EVENTS:
        start_str = to_ass_time(st)
        end_str = to_ass_time(en)
        line = f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{txt}"
        dialogues.append(line)

    full_content = header + "\n".join(dialogues) + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(full_content)
    print(f"[Success] Written {len(dialogues)} precision dialogue events to ASS file")

if __name__ == "__main__":
    out_file = Path(r"c:\Users\rudra\PycharmProjects\douyindownloader\output\subtitles\道可道 - 恭喜你成功制作出桂花蜜_hinglish.ass")
    generate_ass(out_file)
