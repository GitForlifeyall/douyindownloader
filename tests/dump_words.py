import json

with open('master_whisper_words.json', 'r', encoding='utf-8') as f:
    words = json.load(f)

with open('whisper_words_clean.txt', 'w', encoding='utf-8') as out:
    for idx, w in enumerate(words):
        out.write(f"{idx:3d}: {w['start']:6.2f} - {w['end']:6.2f} : {w['word']}\n")

print("Wrote whisper_words_clean.txt successfully, total words:", len(words))
