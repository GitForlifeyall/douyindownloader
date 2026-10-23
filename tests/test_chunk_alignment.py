import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import json
from pathlib import Path
from PIL import ImageFont, ImageDraw, Image

font_path = "assets/fonts/Montserrat-ExtraBold.ttf"
MAX_BORDER_W = 485
FONT_SIZE = 68

font = ImageFont.truetype(font_path, FONT_SIZE)
img = Image.new("RGB", (10, 10))
draw = ImageDraw.Draw(img)

def get_text_width(text: str) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]

def to_ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

with open("output/audio_stems/cantilever_exact_synced_words.json", "r", encoding="utf-8") as f:
    words = json.load(f)

chunks = []
current_chunk_words = []

for idx, w in enumerate(words):
    cand_words = current_chunk_words + [w]
    cand_text = " ".join([cw["word"] for cw in cand_words])
    
    seal = False
    if current_chunk_words:
        # Condition 1: Block boundary
        if w["block"] != current_chunk_words[0]["block"]:
            seal = True
        # Condition 2: Width limit
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

print(f"Total chunks created: {len(events)}")
print(f"Max width: {max(e['width'] for e in events)}px (Limit: {MAX_BORDER_W}px)")
print(f"Min width: {min(e['width'] for e in events)}px")
print(f"Avg width: {sum(e['width'] for e in events)/len(events):.1f}px")

print("\nFirst 15 chunks:")
for e in events[:15]:
    dur = e["end"] - e["start"]
    print(f"[{to_ass_time(e['start'])} --> {to_ass_time(e['end'])}] ({dur:4.2f}s, w={e['width']}px): {e['text']}")

print("\nLast 8 chunks:")
for e in events[-8:]:
    dur = e["end"] - e["start"]
    print(f"[{to_ass_time(e['start'])} --> {to_ass_time(e['end'])}] ({dur:4.2f}s, w={e['width']}px): {e['text']}")
