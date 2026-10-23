import json
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

with open("output/audio_stems/master_exact_words.json", "r", encoding="utf-8") as f:
    master_words = json.load(f)

# Aligned Hinglish token lists per block:
BLOCK_HINGLISH = {
    1: "Tez ufnati nadi paar karne ke liye patli lakdi par pair rakha aur seedhe dhadam se paani mein gir gaye! Ab akele ek lakdi se".split(),
    2: "baat nahi banegi! Toh dher saari lakdiyan bichha kar planks aur safety railing thonk di. Lo ban gaya shaandar bridge! Lekin agar nadi chaudi hui toh".split(),
    3: "asli museebat shuru hogi. Lakdi jitni lambi hogi, beech mein wazan padte hi mudne lagegi! Isliye neeche pillar lagakar raaste ko chhote hisson mein baanto.".split(),
    4: "Pillar se bridge toh sambhal gaya, par boats ka raasta band ho gaya! Upar se gehre aur tez paani mein pillar banana koi khel nahi hai!".split(),
    5: "Toh kyon na dono kinaron se beam baahar nikaalein? Beech mein ek chhoti lakdi jod do, jisse cross karne wala distance ekdum aadha reh jaayega.".split(),
    6: "Lekin jaise hi koi upar chalega, beam see saw ki tarah jhuk jaayegi! Aage ka hissa neeche aur peeche ka sira hawa mein uchhal jaayega.".split(),
    7: "Is tamaashe ko rokne ke liye peeche ka sira fix karna padega! Toh dono kinaron par lakdi cage banakar unme bhaari patthar bhar do.".split(),
    8: "Pattharon ke tagde wazan se peeche ka sira daba rahega. Ab lakdiyon ko line se bichha kar upar neeche se cross beam se poori tarah lock kar do.".split(),
    9: "Lakdi ki khoontiyon se jod itne pakke ho jaayenge ki hilenge bhi nahi! Ab agar beech mein gap bache, toh ek aur layer chadha do.".split(),
    10: "Ise thoda aur aage badhao aur peeche ka sira majbooti se daba do. Ek ke upar ek layer aise badhegi jaise do haath aapas mein mil rahe hon!".split(),
    11: "Jab beech mein zara sa gap bache toh chhoti beam rakhkar dono haathon ko jod do! Upar lakdi takhte aur safety railing fit kar do.".split(),
    12: "Mubaarak ho! Praacheen cantilever bridge taiyaar hai, lekin bina soche".split()
}

aligned_words = []
for b_idx in range(1, 13):
    b_words = [w for w in master_words if w["block"] == b_idx]
    h_tokens = BLOCK_HINGLISH[b_idx]
    print(f"Block #{b_idx:02d}: audio={len(b_words)} vs hinglish={len(h_tokens)}")
    assert len(b_words) == len(h_tokens), f"Mismatch in block {b_idx}!"
    for w_obj, h_tok in zip(b_words, h_tokens):
        aligned_words.append({
            "block": b_idx,
            "word": h_tok,
            "start": w_obj["start"],
            "end": w_obj["end"],
            "hi_word": w_obj["word"]
        })

print(f"\n[+] PERFECT 1-to-1 match across all {len(aligned_words)} words in the video!")
with open("output/audio_stems/cantilever_exact_synced_words.json", "w", encoding="utf-8") as f:
    json.dump(aligned_words, f, ensure_ascii=False, indent=2)

