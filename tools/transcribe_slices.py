from faster_whisper import WhisperModel
import json
from pathlib import Path

model = WhisperModel('tiny', device='cpu', compute_type='int8')
slices_dir = Path('output/audio_stems/temp_sarvam_slices')

slice_words = {}
for b_idx in range(1, 10):
    f = slices_dir / f'block_{b_idx:03d}.mp3'
    segments, _ = model.transcribe(str(f), word_timestamps=True, language='hi')
    words = []
    for s in segments:
        for w in (s.words or []):
            words.append({
                'start': round(w.start, 2),
                'end': round(w.end, 2),
                'word': w.word.strip()
            })
    slice_words[b_idx] = words
    print(f"Block {b_idx}: {len(words)} words transcribed")

with open('slice_words.json', 'w', encoding='utf-8') as out:
    json.dump(slice_words, out, indent=2, ensure_ascii=False)
print("Saved slice_words.json successfully")
