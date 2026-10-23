from faster_whisper import WhisperModel
import json
from pathlib import Path

model = WhisperModel('tiny', device='cpu', compute_type='int8')
slices_dir = Path('output/audio_stems/temp_sarvam_slices')

prompts = {
    7: 'जैसे ही शुगर पिघलकर क्रिस्टल जैसी ट्रांसलूसेंट हो जाए, जार बाहर निकालो, इसमें थोड़ा प्योर हनी डालकर अच्छे से मिक्स करो और छाँव में रख दो।',
    8: 'अब इसे पूरे सात दिन के लिए छोड़ दो, हाई शुगर का प्रेशर फूलों से सारा अर्क खींच लेगा और हनी के साथ मिलकर गाढ़ा सिरप बना देगा।',
    9: 'और ये लो, दुनिया की सबसे टेस्टी हनी सिरप तैयार है! वीडियो पसंद आई तो लाइक करो और चैनल को सब्सक्राइब ज़रूर कर लेना!'
}

blocks_transcription = {}
for b_idx in [7, 8, 9]:
    f = slices_dir / f'block_{b_idx:03d}.mp3'
    prompt = prompts[b_idx]
    segments, _ = model.transcribe(str(f), word_timestamps=True, initial_prompt=prompt, language='hi')
    words = []
    for s in segments:
        for w in (s.words or []):
            words.append({
                'start': round(w.start, 2),
                'end': round(w.end, 2),
                'word': w.word.strip()
            })
    blocks_transcription[b_idx] = words
    print(f"Block {b_idx}: {len(words)} words transcribed")

with open('blocks_789_words.json', 'w', encoding='utf-8') as out:
    json.dump(blocks_transcription, out, indent=2, ensure_ascii=False)

print("Saved blocks_789_words.json successfully")
