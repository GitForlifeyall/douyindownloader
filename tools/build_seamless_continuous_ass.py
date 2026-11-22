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
FONT_SIZE = 92
MAX_BORDER_W = 745  # Fits comfortably within 776px blur plate with safety margin

font = ImageFont.truetype(font_path, FONT_SIZE)
img = Image.new("RGB", (10, 10))
draw = ImageDraw.Draw(img)

def get_text_width(text: str) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]

# All 9 speech blocks in natural Hinglish verbatim matching the Sarvam voiceover
BLOCKS = [
    # Block 1: 0.00s to 7.50s
    (0.00, 7.50, "Gaaon ke dabang ke ped par maaro ek zordaar kick! Jaise hi ye taaza khushboo wale phool neeche girte hi, inhe turant collect karke inki dandiyan saaf kar lena ji."),
    
    # Block 2: 7.50s to 15.18s
    (7.50, 15.18, "Ab in golden phoolon ko saaf paani mein dhokar saari dhool aur keede nikaalo, aur phir chhaanv mein phailakar inka saara oopri moisture acche se sukha lo."),

    # Block 3: 15.18s to 22.74s
    (15.18, 22.74, "Ab ek sookha saaf glass jar le lo jisme paani ya tel na ho, neeche sugar ki ek layer bichhao aur uske upar in taaza phoolon ki."),

    # Block 4: 22.74s to 30.38s
    (22.74, 30.38, "Aise hi layer dar layer jar ko upar tak bharo, top par sugar daal kar aadha fresh lemon nichod do taaki sugar jame nahi aur badhiya taste aaye."),

    # Block 5: 30.38s to 37.94s
    (30.38, 37.94, "Ab dhakkan tight band karke jar ko thande paani wale pot mein rakh do, taaki kaanch crack na ho, aur bhaap uthne ke baad poore bees minute steam karo."),

    # Block 6: 37.94s to 45.46s
    (37.94, 45.46, "Steam ki high heat mein ye phool apna asli khushboodaar juice chhodenge, jo dheere dheere is saari sugar ko poori tarah sokh lega."),

    # Block 7: 45.46s to 53.10s
    (45.46, 53.10, "Jaise hi ye sugar pighalkar crystal jaisi translucent ho jaaye, jar baahar nikaalo, isme thoda pure honey daalkar acche se mix karke rakh do."),

    # Block 8: 53.10s to 60.72s
    (53.10, 60.72, "Ab ise poore saat din ke liye chhod do, high sugar ka pressure phoolon se saara ark kheench lega aur honey ke saath milkar banega."),

    # Block 9: 60.72s to 66.70s
    (60.72, 66.70, "Aur ye lo, duniya ki sabse tasty honey syrup poori taiyaar hai! Video pasand aayi toh like karo aur channel ko subscribe zaroor karo!")
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
# Last event ends at exact video length: 66.70s
video_duration = 66.70
for i in range(len(events) - 1):
    events[i]["end"] = events[i+1]["start"]
events[-1]["end"] = video_duration

# Validate
for i in range(len(events) - 1):
    assert events[i]["end"] == events[i+1]["start"], f"Gap detected at event {i}!"
assert all(e["width"] <= MAX_BORDER_W for e in events), "Width overflow detected!"

print(f"Generated {len(events)} continuous dialogue lines.")
print(f"Start: {events[0]['start']:.2f}s, End: {events[-1]['end']:.2f}s")
print(f"Max width: {max(e['width'] for e in events)}px <= {MAX_BORDER_W}px (Blur plate: 776px)")
print(f"Average width: {sum(e['width'] for e in events)/len(events):.1f}px")

# Generate ASS file
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
Style: Default,Montserrat ExtraBold,{FONT_SIZE},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,8.0,2.0,2,40,40,385,1

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

out_path = Path("output/subtitles/道可道 - 恭喜你成功制作出桂花蜜_hinglish.ass")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(final_ass)

print(f"[+] Wrote finalized ASS to {out_path}")
