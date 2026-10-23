import sys
from pathlib import Path
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).resolve().parent))
import soundfile as sf
import json
from dubbing_studio.env_loader import configure_runtime_environment
configure_runtime_environment()
from faster_whisper import WhisperModel

# Load block placements
master_wav_path = Path("output/audio_stems/master_sarvam_见微知古 - 河中不建桥墩古人靠木头怎么把桥_hindi.wav")
audio_data, sr = sf.read(str(master_wav_path))

# Block placements from check_placements
blocks = [
    {"index": 1, "start": 0.00, "end": 6.25},
    {"index": 2, "start": 7.58, "end": 14.84},
    {"index": 3, "start": 15.22, "end": 22.48},
    {"index": 4, "start": 22.86, "end": 30.04},
    {"index": 5, "start": 30.42, "end": 36.78},
    {"index": 6, "start": 38.04, "end": 44.98},
    {"index": 7, "start": 45.66, "end": 52.12},
    {"index": 8, "start": 53.22, "end": 60.26},
    {"index": 9, "start": 60.82, "end": 66.85},
    {"index": 10, "start": 68.38, "end": 74.58},
    {"index": 11, "start": 76.18, "end": 82.91},
    {"index": 12, "start": 83.70, "end": 86.71},
]

model = WhisperModel('large-v3-turbo', device='cuda', compute_type='int8_float16')

temp_dir = Path("output/audio_stems/temp_master_slices")
temp_dir.mkdir(parents=True, exist_ok=True)

all_master_words = []

for b in blocks:
    idx = b["index"]
    st_sample = int(b["start"] * sr)
    en_sample = min(len(audio_data), int(b["end"] * sr))
    slice_data = audio_data[st_sample:en_sample]
    slice_path = temp_dir / f"master_block_{idx:02d}.wav"
    sf.write(str(slice_path), slice_data, sr)
    
    segments, _ = model.transcribe(str(slice_path), language='hi', word_timestamps=True)
    block_words = []
    for s in segments:
        for w in (s.words or []):
            word_st = round(b["start"] + w.start, 3)
            word_en = round(b["start"] + w.end, 3)
            block_words.append({
                "block": idx,
                "start": word_st,
                "end": word_en,
                "word": w.word.strip(),
                "prob": round(w.probability, 3)
            })
    print(f"Block #{idx:02d} ({b['start']:.2f}s - {b['end']:.2f}s): {len(block_words)} words")
    all_master_words.extend(block_words)

out_json = Path("output/audio_stems/master_exact_words.json")
with open(out_json, "w", encoding="utf-8") as f:
    json.dump(all_master_words, f, ensure_ascii=False, indent=2)

print(f"\n[+] Total words extracted from master wav: {len(all_master_words)}")
for w in all_master_words[:15]:
    print(f"  {w['start']:6.2f} - {w['end']:6.2f} : {w['word']}")
