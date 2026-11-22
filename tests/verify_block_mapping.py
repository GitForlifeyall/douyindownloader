import json
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

with open("output/audio_stems/master_exact_words.json", "r", encoding="utf-8") as f:
    master_words = json.load(f)

BLOCKS = [
    (1, "Tez ufnati nadi paar karne ke liye patli lakdi par pair rakha aur seedhe dhadam se paani mein gir gaye! Ab akele ek lakdi se"),
    (2, "baat nahi banegi! Toh dher saari lakdiyan bichhakar planks aur safety railing thonk di. Lo ban gaya shaandar bridge! Lekin agar nadi chaudi hui toh"),
    (3, "asli museebat shuru hogi. Lakdi jitni lambi hogi, beech mein wazan padte hi mudne lagegi! Isliye neeche pillar lagakar raaste ko chhote hisson mein baanto."),
    (4, "Pillar se bridge toh sambhal gaya, par boats ka raasta band ho gaya! Upar se gehre aur tez paani mein pillar banana koi khel nahi hai!"),
    (5, "Toh kyon na dono kinaron se beam baahar nikaalein? Beech mein ek chhoti lakdi jod do, jisse cross karne wala distance ekdum aadha reh jaayega."),
    (6, "Lekin jaise hi koi upar chalega, beam see-saw ki tarah jhuk jaayegi! Aage ka hissa neeche aur peeche ka sira hawa mein uchhal jaayega."),
    (7, "Is tamaashe ko rokne ke liye peeche ka sira fix karna padega! Toh dono kinaron par lakdi ke cage banakar unme bhaari patthar bhar do."),
    (8, "Pattharon ke tagde wazan se peeche ka sira daba rahega. Ab lakdiyon ko line se bichhakar upar-neeche se cross beam se poori tarah lock kar do."),
    (9, "Lakdi ki khoontiyon se jod itne pakke ho jaayenge ki hilenge bhi nahi! Ab agar beech mein gap bache, toh ek aur layer chadha do."),
    (10, "Ise thoda aur aage badhao aur peeche ka sira majbooti se daba do. Ek ke upar ek layer aise badhegi jaise do haath aapas mein mil rahe hon!"),
    (11, "Jab beech mein zara sa gap bache, toh chhoti beam rakhkar dono haathon ko jod do! Upar lakdi ke takhte aur safety railing fit kar do."),
    (12, "Mubaarak ho! Praacheen cantilever bridge taiyaar hai, lekin bina soche")
]

for b_idx, h_text in BLOCKS:
    h_tokens = h_text.strip().split()
    b_words = [w for w in master_words if w["block"] == b_idx]
    print(f"Block #{b_idx:02d}: {len(b_words):2d} audio words vs {len(h_tokens):2d} Hinglish tokens")
    if len(b_words) != len(h_tokens):
        print(f"   Audio: {[w['word'] for w in b_words]}")
        print(f"   Hinglish: {h_tokens}")
