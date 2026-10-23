import re
import cv2
import numpy as np
import subprocess
from pathlib import Path
from PIL import ImageFont

# Candidate natural chunking for all 9 blocks (no squeezing, no stretching, natural 3-6 words, 20-27 chars per line)
NATURAL_BLOCKS = [
    # Block 1 (0.00 - 7.14)
    # Hindi: गाँव के दबंग के पेड़ पर मारो एक ज़ोरदार किक! जैसे ही ये खुशबूदार सिलंग के फूल नीचे गिरें, इन्हें तुरंत कलेक्ट करके इनकी डंडियाँ साफ़ कर लो।
    (0.00, 7.14, [
        ("Gaaon ke dabang ped par", 0.00, 1.40),       # 23 ch, 5 w
        ("maaro ek zordaar kick!", 1.40, 2.80),        # 22 ch, 4 w
        ("Jaise hi ye khushboodaar", 2.80, 4.10),      # 24 ch, 4 w
        ("phool neeche girte hi,", 4.10, 5.25),        # 22 ch, 4 w
        ("inhe turant collect karke", 5.25, 6.20),     # 25 ch, 4 w
        ("inki dandiyan saaf kar lo.", 6.20, 7.14),    # 26 ch, 5 w
    ]),

    # Block 2 (7.50 - 14.81)
    # Hindi: अब इन गोल्डन फूलों को साफ़ पानी में धोकर धूल और कीड़े निकाल दो, और फिर छाँव में फैलाकर इनका सारा ऊपरी moisture अच्छे से सुखा लो।
    (7.50, 14.81, [
        ("Ab in golden phoolon ko", 7.50, 8.80),       # 23 ch, 5 w
        ("saaf paani mein dhokar", 8.80, 10.10),       # 22 ch, 4 w
        ("dhool aur keede nikaalo,", 10.10, 11.40),    # 24 ch, 4 w
        ("aur phir chhaanv mein", 11.40, 12.50),       # 21 ch, 4 w
        ("phailakar inka saara", 12.50, 13.60),        # 20 ch, 3 w
        ("oopri moisture sukha lo.", 13.60, 14.81),    # 24 ch, 4 w
    ]),

    # Block 3 (15.18 - 22.37)
    # Hindi: अब एक सूखा साफ़ ग्लास जार लो जिसमें पानी या तेल ना हो। नीचे शुगर की एक लेयर बिछाओ और उसके ऊपर इन खुशबूदार ताज़ा फूलों की।
    (15.18, 22.37, [
        ("Ab ek sookha saaf glass", 15.18, 16.60),     # 23 ch, 5 w
        ("jar le lo jisme paani", 16.60, 18.00),       # 21 ch, 5 w
        ("ya tel na ho, neeche", 18.00, 19.40),        # 20 ch, 5 w
        ("sugar ki ek layer bichhao", 19.40, 20.80),   # 25 ch, 5 w
        ("aur upar taaza phoolon ki.", 20.80, 22.37),  # 26 ch, 5 w
    ]),

    # Block 4 (22.74 - 30.00)
    # Hindi: ऐसे ही लेयर दर लेयर जार को ऊपर तक भरो, टॉप पर शुगर डालो और आधा फ्रेश लेमन निचोड़ दो ताकि शुगर जमे नहीं और बढ़िया टेस्ट आए।
    (22.74, 30.00, [
        ("Aise hi layer dar layer", 22.74, 24.10),     # 23 ch, 5 w
        ("jar ko upar tak bharo,", 24.10, 25.30),      # 22 ch, 5 w
        ("top par sugar daal kar", 25.30, 26.60),      # 22 ch, 5 w
        ("aadha fresh lemon nichodo", 26.60, 28.00),   # 25 ch, 4 w
        ("taaki sugar jame nahi aur", 28.00, 29.00),   # 25 ch, 5 w
        ("badhiya sa taste aaye.", 29.00, 30.00),      # 22 ch, 4 w
    ]),

    # Block 5 (30.38 - 37.56)
    # Hindi: अब ढक्कन टाइट बंद करके जार को ठंडे पानी वाले पॉट में रखो ताकि कांच क्रैक ना हो, और भाप उठने के बाद पूरे बीस मिनट तक स्टीम करो।
    (30.38, 37.56, [
        ("Ab dhakkan tight band karke", 30.38, 31.80), # 27 ch, 5 w
        ("jar ko thande paani wale", 31.80, 33.20),    # 24 ch, 5 w
        ("pot mein rakh do taaki", 33.20, 34.60),      # 22 ch, 5 w
        ("kaanch crack na ho, aur", 34.60, 36.00),     # 23 ch, 5 w
        ("bees minute steam karo.", 36.00, 37.56),     # 23 ch, 4 w
    ]),

    # Block 6 (37.94 - 45.09)
    # Hindi: स्टीम की हाई हीट में ये फूल अपना असली खुशबूदार जूस छोड़ेंगे, जो धीरे-धीरे इस सारी शुगर को पूरी तरह पिघलाकर अपने अंदर सोख लेगा।
    (37.94, 45.09, [
        ("Steam ki high heat mein", 37.94, 39.40),     # 23 ch, 5 w
        ("ye phool asli khushboodaar", 39.40, 40.90),  # 26 ch, 4 w
        ("juice chhodenge, jo dheere", 40.90, 42.40),  # 26 ch, 4 w
        ("dheere is saari sugar ko", 42.40, 43.80),    # 24 ch, 5 w
        ("poori tarah sokh lega ji.", 43.80, 45.09),   # 26 ch, 5 w
    ]),

    # Block 7 (45.46 - 52.72)
    # Hindi: जैसे ही शुगर पिघलकर क्रिस्टल जैसी ट्रांसलूसेंट हो जाए, जार बाहर निकालो, इसमें थोड़ा प्योर हनी डालकर अच्छे से मिक्स करो और छाँव में रख दो।
    (45.46, 52.72, [
        ("Jaise hi sugar pighalkar", 45.46, 46.90),    # 24 ch, 4 w
        ("crystal jaisi translucent", 46.90, 48.30),   # 25 ch, 3 w
        ("ho jaaye, jar nikaalo,", 48.30, 49.70),      # 23 ch, 4 w
        ("isme thoda pure honey daalo", 49.70, 51.20), # 27 ch, 5 w
        ("aur acche se mix kar do.", 51.20, 52.72),    # 24 ch, 6 w
    ]),

    # Block 8 (53.10 - 59.89)
    # Hindi: अब इसे पूरे सात दिन के लिए छोड़ दो, हाई शुगर का प्रेशर फूलों से सारा अर्क खींच लेगा और हनी के साथ मिलकर गाढ़ा सिरप बना देगा।
    (53.10, 59.89, [
        ("Ab ise poore saat din ke", 53.10, 54.50),    # 24 ch, 6 w
        ("liye chhod do, high sugar", 54.50, 55.90),   # 25 ch, 5 w
        ("ka pressure phoolon se", 55.90, 57.20),      # 22 ch, 4 w
        ("saara ark kheench lega aur", 57.20, 58.50),  # 26 ch, 5 w
        ("honey ka syrup banega.", 58.50, 59.89),      # 22 ch, 4 w
    ]),

    # Block 9 (60.72 - 65.75)
    # Hindi: और ये लो, दुनिया की सबसे टेस्टी हनी सिरप तैयार है! वीडियो पसंद आई तो लाइक करो और चैनल को सब्सक्राइब ज़रूर कर लेना!
    (60.72, 65.75, [
        ("Aur ye lo, duniya ki sabse", 60.72, 62.00),  # 26 ch, 6 w
        ("tasty honey syrup taiyaar!", 62.00, 63.30),  # 26 ch, 4 w
        ("Video pasand aayi toh like", 63.30, 64.50),  # 26 ch, 5 w
        ("karo aur subscribe zaroor karo!", 64.50, 65.75) # 31 ch, 5 w
    ])
]

# Formatted timestamp for ASS: H:MM:SS.cs
def to_ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

print("=== TESTING ALL CANDIDATE NATURAL LINES (NO FSCX, SCALE 100%) ===")
# We test with Fontsize 120, MarginV 360
FONT_SIZE = 120
ass_lines = []
ass_lines.append("[Script Info]")
ass_lines.append("; Script generated with Pure Natural Overlap (No squeeze, no stretch)")
ass_lines.append("ScriptType: v4.00+")
ass_lines.append("PlayResX: 1080")
ass_lines.append("PlayResY: 1920")
ass_lines.append("ScaledBorderAndShadow: yes")
ass_lines.append("YCbCr Matrix: TV.709")
ass_lines.append("")
ass_lines.append("[V4+ Styles]")
ass_lines.append("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding")
ass_lines.append(f"Style: Default,Montserrat ExtraBold,{FONT_SIZE},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,8.5,2.0,2,40,40,360,1")
ass_lines.append("")
ass_lines.append("[Events]")
ass_lines.append("Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text")

dialogue_count = 0
for b_idx, (b_st, b_en, lines) in enumerate(NATURAL_BLOCKS):
    for txt, st, en in lines:
        dialogue_count += 1
        t_st = to_ass_time(st)
        t_en = to_ass_time(en)
        # Note: Absolutely NO override tags, pure clean text!
        ass_lines.append(f"Dialogue: 0,{t_st},{t_en},Default,,0,0,0,,{txt}")

ass_content = '\n'.join(ass_lines) + '\n'

with open('output/subtitles/道可道 - 恭喜你成功制作出桂花蜜_hinglish.ass', 'w', encoding='utf-8') as f:
    f.write(ass_content)

print(f"[+] Wrote {dialogue_count} pure natural dialogue lines to hinglish.ass")
