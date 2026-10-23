import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from PIL import ImageFont, ImageDraw, Image

def to_ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

font_path = "assets/fonts/Montserrat-ExtraBold.ttf"
# For a 498px maximum blur width:
MAX_BORDER_W = 485  # Fits comfortably within 498px blur plate
FONT_SIZE = 68

font = ImageFont.truetype(font_path, FONT_SIZE)
img = Image.new("RGB", (10, 10))
draw = ImageDraw.Draw(img)

def get_text_width(text: str) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]

# All 12 blocks verbatim from the Hindi dubbing in Hinglish:
BLOCKS = [
    # Block 1: 0.00s to 7.58s
    (0.00, 7.58, "Tez ufnati nadi paar karne ke liye patli lakdi par pair rakha aur seedhe dhadam se paani mein gir gaye! Ab akele ek lakdi se"),

    # Block 2: 7.58s to 15.22s
    (7.58, 15.22, "baat nahi banegi! Toh dher saari lakdiyan bichhakar planks aur safety railing thonk di. Lo ban gaya shaandar bridge! Lekin agar nadi chaudi hui toh"),

    # Block 3: 15.22s to 22.86s
    (15.22, 22.86, "asli museebat shuru hogi. Lakdi jitni lambi hogi, beech mein wazan padte hi mudne lagegi! Isliye neeche pillar lagakar raaste ko chhote hisson mein baanto."),

    # Block 4: 22.86s to 30.42s
    (22.86, 30.42, "Pillar se bridge toh sambhal gaya, par boats ka raasta band ho gaya! Upar se gehre aur tez paani mein pillar banana koi khel nahi hai!"),

    # Block 5: 30.42s to 38.04s
    (30.42, 38.04, "Toh kyon na dono kinaron se beam baahar nikaalein? Beech mein ek chhoti lakdi jod do, jisse cross karne wala distance ekdum aadha reh jaayega."),

    # Block 6: 38.04s to 45.66s
    (38.04, 45.66, "Lekin jaise hi koi upar chalega, beam see-saw ki tarah jhuk jaayegi! Aage ka hissa neeche aur peeche ka sira hawa mein uchhal jaayega."),

    # Block 7: 45.66s to 53.22s
    (45.66, 53.22, "Is tamaashe ko rokne ke liye peeche ka sira fix karna padega! Toh dono kinaron par lakdi ke cage banakar unme bhaari patthar bhar do."),

    # Block 8: 53.22s to 60.82s
    (53.22, 60.82, "Pattharon ke tagde wazan se peeche ka sira daba rahega. Ab lakdiyon ko line se bichhakar upar-neeche se cross beam se poori tarah lock kar do."),

    # Block 9: 60.82s to 68.38s
    (60.82, 68.38, "Lakdi ki khoontiyon se jod itne pakke ho jaayenge ki hilenge bhi nahi! Ab agar beech mein gap bache, toh ek aur layer chadha do."),

    # Block 10: 68.38s to 76.18s
    (68.38, 76.18, "Ise thoda aur aage badhao aur peeche ka sira majbooti se daba do. Ek ke upar ek layer aise badhegi jaise do haath aapas mein mil rahe hon!"),

    # Block 11: 76.18s to 83.70s
    (76.18, 83.70, "Jab beech mein zara sa gap bache, toh chhoti beam rakhkar dono haathon ko jod do! Upar lakdi ke takhte aur safety railing fit kar do."),

    # Block 12: 83.70s to 87.47s
    (83.70, 87.47, "Mubaarak ho! Praacheen cantilever bridge taiyaar hai, video pasand aayi toh like aur subscribe zaroor karein!")
]

events = []

for b_start, b_end, b_text in BLOCKS:
    words = b_text.strip().split()
    b_dur = b_end - b_start
    
    # Greedily group words into lines that fit within MAX_BORDER_W
    block_lines = []
    curr = []
    for w in words:
        cand = " ".join(curr + [w]) if curr else w
        if curr and get_text_width(cand) > MAX_BORDER_W:
            block_lines.append(" ".join(curr))
            curr = [w]
        else:
            curr.append(w)
    if curr:
        block_lines.append(" ".join(curr))

    # Calculate proportional duration for each line
    total_chars = max(1, sum(len(line) for line in block_lines))
    curr_t = b_start
    for line in block_lines:
        dur = b_dur * (len(line) / float(total_chars))
        events.append({
            "start": curr_t,
            "end": curr_t + dur,
            "text": line,
            "width": get_text_width(line)
        })
        curr_t += dur

# Enforce strict seamless continuous timeline:
# event[i].end = event[i+1].start
# Last event ends at exact video length: 87.47s
video_duration = 87.47
for i in range(len(events) - 1):
    events[i]["end"] = events[i+1]["start"]
events[-1]["end"] = video_duration

# Validate
for i in range(len(events) - 1):
    assert events[i]["end"] == events[i+1]["start"], f"Gap detected at event {i}!"
assert all(e["width"] <= MAX_BORDER_W for e in events), "Width overflow detected!"

print(f"Generated {len(events)} continuous dialogue lines.")
print(f"Start: {events[0]['start']:.2f}s, End: {events[-1]['end']:.2f}s")
print(f"Max width: {max(e['width'] for e in events)}px <= {MAX_BORDER_W}px (Blur plate: 498px)")
print(f"Average width: {sum(e['width'] for e in events)/len(events):.1f}px")

# Position:
# Blur plate Y center: (1367 + 1467) / 2 = 1417
# MarginV from bottom (1920): 1920 - 1417 = 503 -> MarginV = 475 centers baseline directly in the blur
ass_header = f"""[Script Info]
; Script generated with Continuous Presence & Maximum Boundary Fit
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Montserrat ExtraBold,{FONT_SIZE},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,7.0,2.0,2,40,40,475,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

ass_lines = [ass_header.strip()]
for e in events:
    t_st = to_ass_time(e["start"])
    t_en = to_ass_time(e["end"])
    # 100% natural rendering, ScaleX=100, ScaleY=100, zero distortion
    ass_lines.append(f"Dialogue: 0,{t_st},{t_en},Default,,0,0,0,,{e['text']}")

final_ass = "\n".join(ass_lines) + "\n"

out_path = Path("output/subtitles/见微知古 - 河中不建桥墩古人靠木头怎么把桥_hinglish.ass")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(final_ass)

print(f"[+] Wrote finalized ASS to {out_path}")
