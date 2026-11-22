import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import json
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
MAX_BORDER_W = 485  # Fits comfortably within 498px blur plate
FONT_SIZE = 68

font = ImageFont.truetype(font_path, FONT_SIZE)
img = Image.new("RGB", (10, 10))
draw = ImageDraw.Draw(img)

def get_text_width(text: str) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]

with open("output/audio_stems/cantilever_exact_synced_words.json", "r", encoding="utf-8") as f:
    words = json.load(f)

chunks = []
current_chunk_words = []

for idx, w in enumerate(words):
    cand_words = current_chunk_words + [w]
    cand_text = " ".join([cw["word"] for cw in cand_words])
    
    seal = False
    if current_chunk_words:
        # Condition 1: Block boundary (scene cut)
        if w["block"] != current_chunk_words[0]["block"]:
            seal = True
        # Condition 2: Max width overflow
        elif get_text_width(cand_text) > MAX_BORDER_W:
            seal = True
        # Condition 3: Sentence boundary in previous word (. or !)
        elif any(current_chunk_words[-1]["word"].endswith(p) for p in [".", "!"]):
            seal = True
        # Condition 4: Clause boundary in previous word (,) if chunk already has >= 2 words
        elif len(current_chunk_words) >= 2 and any(current_chunk_words[-1]["word"].endswith(p) for p in [",", "?"]):
            seal = True
            
    if seal:
        chunks.append(current_chunk_words)
        current_chunk_words = [w]
    else:
        current_chunk_words.append(w)

if current_chunk_words:
    chunks.append(current_chunk_words)

# Build continuous events with real audio start times
events = []
video_duration = 87.47

for i, ch in enumerate(chunks):
    ch_text = " ".join([w["word"] for w in ch])
    st_time = ch[0]["start"]
    if i == 0:
        st_time = 0.00
        
    events.append({
        "chunk_index": i + 1,
        "block": ch[0]["block"],
        "start": st_time,
        "text": ch_text,
        "width": get_text_width(ch_text),
        "word_count": len(ch)
    })

# Chain ends seamlessly to the next chunk's start
for i in range(len(events) - 1):
    events[i]["end"] = events[i+1]["start"]
events[-1]["end"] = video_duration

# Validation
for i in range(len(events) - 1):
    assert events[i]["end"] == events[i+1]["start"], f"Gap detected at chunk {i}!"
assert all(e["width"] <= MAX_BORDER_W for e in events), "Width overflow detected!"

print(f"Generated {len(events)} perfectly synced continuous dialogue lines.")
print(f"Timeline: {events[0]['start']:.2f}s -> {events[-1]['end']:.2f}s (zero gaps, zero drops)")
print(f"Max width: {max(e['width'] for e in events)}px <= {MAX_BORDER_W}px (Blur plate: 498px)")
print(f"Average width: {sum(e['width'] for e in events)/len(events):.1f}px")

ass_header = f"""[Script Info]
; Script generated with Audio-Synced Continuous Presence & Maximum Boundary Fit
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

print(f"[+] Successfully wrote finalized ASS to {out_path}")
