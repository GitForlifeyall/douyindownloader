#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dubbing_studio/hinglish.py
==========================
Automatic, highly accurate Hindi Devanagari to Colloquial Hinglish (Latin) transliterator.
Produces clean, modern social-media style Romanized Hindi captions for YouTube Shorts and Reels.
"""

import re
from typing import Dict, List, Tuple

# Comprehensive conversational dictionary for Indian Shorts/Reels Hinglish
COMMON_WORDS: Dict[str, str] = {
    # Pronouns & Conjunctions
    "अगर": "Agar", "आप": "aap", "आपको": "aapko", "आपने": "aapne", "आपका": "aapka",
    "तुम": "tum", "तुम्हें": "tumhein", "तुम्हारे": "tumhaare", "तुम्हारा": "tumhaara", "तुम्हारी": "tumhaari",
    "हम": "hum", "हमने": "humne", "हमारा": "hamaara", "ये": "ye", "यह": "yeh",
    "वो": "woh", "वह": "woh", "इन": "in", "इनके": "inke", "इनको": "inko", "इनसे": "inse",
    "उन": "un", "उनके": "unke", "उनको": "unko", "उनसे": "unse",
    "तो": "toh", "और": "aur", "लेकिन": "lekin", "मगर": "magar", "परंतु": "lekin",
    "क्योंकि": "kyunki", "ताकि": "taaki", "जिससे": "jisse", "जब": "jab", "तब": "tab",
    "तभी": "tabhi", "कहाँ": "kahan", "कहा": "kaha", "यहाँ": "yahan", "वहाँ": "wahan",
    "कि": "ki", "की": "ki", "के": "ke", "का": "ka", "को": "ko", "से": "se", "में": "mein",
    "पर": "par", "पे": "pe", "तक": "tak", "द्वारा": "dwara", "लिए": "liye",
    "जो": "jo", "जिस": "jis", "किसे": "kise", "किस": "kis", "क्या": "kya", "क्यूँ": "kyun", "क्यों": "kyun",
    "कैसे": "kaise", "कौन": "kaun", "कब": "kab", "कहाँ": "kahan", "कितना": "kitna", "कितने": "kitne",
    "ना": "na", "नहीं": "nahi", "भी": "bhi", "ही": "hi", "अब": "Ab", "सब": "sab",
    "इसी": "isi", "उसी": "usi", "इन्हीं": "inhin", "उन्हीं": "unhin", "यही": "yahi", "वही": "wahi",

    # Verbs & States
    "है": "hai", "हैं": "hain", "था": "tha", "थी": "thi", "थे": "the", "हो": "ho", "होगा": "hoga",
    "होगी": "hogi", "होंगे": "honge", "होता": "hota", "होती": "hoti", "होते": "hote",
    "करना": "karna", "कर": "kar", "करके": "karke", "करें": "karein", "करो": "karo", "करते": "karte",
    "किया": "kiya", "किए": "kiye", "कीजिए": "kijiye", "दोगे": "doge", "दें": "dein", "दो": "do",
    "दिया": "diya", "दिए": "diye", "लेना": "lena", "लें": "lein", "लो": "lo", "लिया": "liya",
    "डालना": "daalna", "डाल": "daal", "डाला": "daala", "डाली": "daali", "डाले": "daale",
    "डालोगे": "daaloge", "डालें": "daalein", "डालो": "daalo", "डालकर": "daalkar", "डालने": "daalne",
    "जाना": "jaana", "जा": "jaa", "जाए": "jaaye", "जाएगा": "jaayega", "जाएगी": "jaayegi",
    "जाएंगे": "jaayenge", "जाता": "jaata", "जाती": "jaati", "जाते": "jaate", "गया": "gaya",
    "गई": "gayi", "गए": "gaye", "जाओ": "jaao", "सकें": "sakein", "सके": "sake", "सकता": "sakta",
    "सकती": "sakti", "सकते": "sakte", "पाएगा": "paayega", "पाएगी": "paayegi", "पाएंगे": "paayenge",
    "बनना": "banna", "बन": "ban", "बना": "bana", "बनी": "bani", "बने": "bane", "बनता": "banta",
    "बनती": "banti", "बनते": "bante", "बनाना": "banaana", "बनाएं": "banaayein", "बनाओ": "banaao",
    "बनानी": "banaani", "बनाया": "banaaya", "बनाई": "banaayi",
    "मिलना": "milna", "मिल": "mil", "मिला": "mila", "मिली": "mili", "मिले": "mile",
    "मिलेगा": "milega", "मिलेगी": "milegi", "मिलेंगे": "milenge", "मिलता": "milta",
    "रखना": "rakhna", "रख": "rakh", "रखा": "rakha", "रखी": "rakhi", "रखे": "rakhe",
    "रखें": "rakhein", "रखो": "rakho", "रखने": "rakhne", "रखती": "rakhti", "रखता": "rakhta",
    "देखना": "dekhna", "देख": "dekh", "देखा": "dekha", "देखी": "dekhi", "देखें": "dekhein",
    "देखो": "dekho", "देखिए": "dekhiye", "दिखता": "dikhta", "दिखती": "dikhti",
    "सुखाना": "sukhaana", "सुखा": "sukha", "सुखाकर": "sukhakar", "सूख": "sookh", "सूखने": "sookhne",
    "पीसना": "peesna", "पीस": "pees", "पीसकर": "peeskar", "पीसा": "peesa",
    "काटना": "kaatna", "काट": "kaat", "काटा": "kaata", "काटकर": "kaatkar", "काटो": "kaato",
    "छोड़ना": "chhodna", "छोड़": "chhod", "छोड़ा": "chhoda", "छोड़ें": "chhodein",
    "घुलना": "ghulna", "घुल": "ghul", "घुलता": "ghulta", "घुलते": "ghulte",
    "उड़ना": "udna", "उड़": "ud", "उड़ता": "udta", "उड़ती": "udti",
    "सोखना": "sokhna", "सोख": "sokh", "सोखता": "sokhta", "सोखते": "sokhte",
    "सील": "seal", "हील": "heal", "स्टीम": "steam", "पैक": "pack",
    "पकाना": "pakaana", "पकाओ": "pakaao", "पकाएं": "pakaayein", "पके": "pake",
    "चलाना": "chalaana", "चलाते": "chalaate", "चलाओ": "chalaao",
    "मिलाना": "milaana", "मिलाओ": "milaao", "मिलाकर": "milaakar", "मिलाएं": "milaayein",
    "छानना": "chhaanna", "छानकर": "chhaankar", "छान": "chhaan",
    "उबालना": "ubaalna", "उबाल": "ubaal", "उबालकर": "ubaalkar",
    "मेल्ट": "melt", "पिघलना": "pighalna", "पिघला": "pighla", "पिघलाकर": "pighlaakar",
    "निकालना": "nikalna", "निकाल": "nikaal", "निकालकर": "nikaalkar", "निकली": "nikli", "निकले": "nikle",
    "फंसा": "phansa", "फंस": "phans", "फंसी": "phansi", "फंसे": "phanse", "अटक": "atak", "अटका": "atka", "अटकी": "atki",
    "खिलाड़ी": "khiladi", "नमूना": "namoona", "घंटे": "ghante", "घंटा": "ghanta",
    "मुमकिन": "mumkin", "नामुमकिन": "namumkin", "अंदाज़ा": "andaza", "अंदाजा": "andaza",
    "चमन": "chaman", "पेल": "pel", "कब्र": "kabr", "इसकी": "iski", "उसकी": "uski", "इनकी": "inki", "उनकी": "unki",

    # Common Nouns & Adjectives
    "सच": "sach", "झूठ": "jhooth", "असली": "asli", "नकली": "nakli", "शुद्ध": "shuddh",
    "परफेक्ट": "perfect", "बेहतरीन": "behtareen", "शानदार": "shaandaar", "बढ़िया": "badhiya",
    "खूबसूरत": "khoobsurat", "सुंदर": "sundar", "खराब": "kharab", "गलत": "galat", "सही": "sahi",
    "पानी": "paani", "शराब": "sharab", "वाइन": "wine", "अल्कोहल": "alcohol", "स्ट्रॉन्ग": "strong",
    "हल्का": "halka", "हल्की": "halki", "हल्के": "halke", "गाढ़ा": "gaadha", "गाढ़ी": "gaadhi",
    "पतला": "patla", "पतली": "patli", "पतले": "patle", "बारीक": "baareek", "एकदम": "ekdam",
    "लाल": "laal", "पीला": "peela", "हरा": "hara", "हरे": "hare", "नीला": "neela", "सफेद": "safed",
    "काला": "kaala", "एम्बर": "amber", "कलर": "color", "रंग": "rang", "ब्राइट": "bright",
    "बांस": "baans", "पेड़": "ped", "लकड़ी": "lakdi", "पत्ता": "patta", "पत्ते": "patte",
    "फूल": "phool", "फल": "phal", "जड़": "jad", "तीली": "teeli", "सुई": "sooi", "सिरिंज": "syringe",
    "छेद": "chhed", "होल": "hole", "पिनहोल": "pinhole", "दरार": "daraar",
    "कैकट्स": "cactus", "कैक्टस": "cactus", "仙人掌": "cactus",
    "कीड़ा": "keeda", "कीड़े": "keede", "कीड़ों": "keedon",
    "पाउडर": "powder", "धूल": "dhool", "कचरा": "kachra", "अशुद्धि": "ashuddhi", "अशुद्धियों": "ashuddhiyon",
    "खुशबू": "khushboo", "खुश्बू": "khushboo", "बदबू": "badboo", "महक": "mahak", "स्वाद": "swaad", "टेस्ट": "taste",
    "तीखा": "teekha", "तीखापन": "teekhapan", "मीठा": "meetha", "खट्टा": "khatta", "कड़वा": "kadwa",
    "स्मूथ": "smooth", "सॉफ्ट": "soft", "कड़क": "kadak",
    "दिन": "din", "दिनों": "dinon", "महीना": "mahina", "महीने": "mahine", "साल": "saal", "वक्त": "waqt", "समय": "samay", "टाइम": "time",
    "एक": "ek", "दो": "do", "तीन": "teen", "चार": "chaar", "पाँच": "paanch", "पांच": "paanch",
    "छह": "chheh", "सात": "saat", "आठ": "aath", "नौ": "nau", "दस": "das",
    "चालीस": "chaalis", "पचपन": "pachpan", "डिग्री": "degree", "पर्सेंट": "percent",
    "अप्रैल": "April", "मई": "May", "जून": "June", "जुलाई": "July",
    "जार": "jar", "ग्लास": "glass", "बोतल": "bottle", "कंटेनर": "container", "पॉट": "pot",
    "लिपस्टिक": "lipstick", "मेकअप": "makeup", "रॉयल्टी": "royalty", "राजा": "raja", "रानी": "rani",
    "पुराना": "purana", "पुरानी": "purani", "पुराने": "purane", "ज़माना": "zamana", "जमाने": "zamane", "ज़माने": "zamane",
    "प्राचीन": "ancient", "एंटिएंट": "ancient", "एंशियंट": "ancient", "ट्रेडिशनल": "traditional",
    "नेचुरल": "natural", "प्योर": "pure", "ऑर्गेनिक": "organic", "क्लियर": "clear",
    "ओखली": "okhli", "पैन": "pan", "फ्लेम": "flame", "लेमन": "lemon", "जूस": "juice", "पीएच": "pH", "लेवल": "level",
    "बैलेंस": "balance", "ऑक्सिडाइज": "oxidize", "लिक्विड": "liquid", "फाइन": "fine", "कपड़ा": "kapda", "कपड़े": "kapde",
    "सारे": "saare", "एक्स्ट्रा": "extra", "पार्टिकल्स": "particles", "छांव": "chhaanv", "धूप": "dhoop",
    "सॉलिड": "solid", "फॉर्म": "form", "ब्लॉक": "block", "शीया": "shea", "बटर": "butter", "वैक्स": "wax",
    "हीट": "heat", "मिक्सचर": "mixture", "आपस": "aapas", "पूरी": "poori", "पूरा": "poora", "तरह": "tarah",
    "पेस्ट": "paste", "मोलड": "mold", "मोल्ड": "mold", "डीमोल्ड": "demold", "इंग्रीडिएंट्स": "ingredients",
    "स्किन": "skin", "काफी": "kaafi", "सेफ": "safe", "प्रोसेस": "process", "एडवांस": "advance",
    "आज": "aaj", "सिर्फ": "sirf", "लुक": "look", "बल्कि": "balki", "होंठों": "honthon", "होंठ": "honth",
    "मॉइस्ट": "moist", "हुए": "hue", "इसके": "iske", "इसमें": "ismein", "फिर": "phir", "थोड़ा": "thoda",
    "थोड़ी": "thodi", "थोड़े": "thode", "वाले": "waale", "वाली": "waali", "वाला": "waala",
    "胭脂": "rouge", "口红": "lipstick",
    "वीडियो": "video", "लाइक": "like", "शेयर": "share", "सब्सक्राइब": "subscribe", "कमेंट": "comment",
    "चैनल": "channel", "फॉलो": "follow", "दोस्तों": "doston", "यारों": "yaaron", "मुबारक": "mubarak",
    "तैयार": "taiyaar", "सीधे": "seedhe", "बिल्कुल": "bilkul", "बिलकुल": "bilkul",
    "बारिश": "baarish", "गर्मी": "garmi", "सर्दी": "sardi",
    "बैक्टीरिया": "bacteria", "ऑस्मोसिस": "osmosis", "फाइबर": "fiber", "फाइबर्स": "fibers",
    "स्ट्रक्चर": "structure", "सेल": "cell", "सेल्स": "cells",
    "पोरस": "porous", "लिविंग": "living", "मिनरल्स": "minerals", "फ्लेवोनोइड्स": "flavonoids", "पॉलीसैक्राइड्स": "polysaccharides",

    # Architecture, Engineering & Viral Shorts/Reels Hooks
    "मीटर": "meter", "किलोमीटर": "kilometer", "सेंटीमीटर": "centimeter", "एमएम": "mm",
    "गहरी": "gehri", "गहरा": "gehra", "गहरे": "gehre", "खाई": "khai",
    "हवा": "hawa", "लटका": "latka", "लटक": "latak", "लटकती": "latakti", "लटकते": "latakte",
    "महल": "mahal", "मंदिर": "mandir", "किला": "kila", "इमारत": "imaarat",
    "पहाड़": "pahaad", "पहाड़ों": "pahaadon", "चट्टान": "chattaan", "चट्टानों": "chattaanon",
    "ब्रिज": "bridge", "पुल": "pul", "आर्च": "arch", "पिलर": "pillar", "खंभा": "khamba",
    "स्टोन": "stone", "पत्थर": "patthar", "पत्थरों": "pattharon", "नींव": "neev", "फाउंडेशन": "foundation",
    "स्टील": "steel", "लोहा": "loha", "क्रेन": "crane", "रोप": "rope", "रस्सी": "rassi",
    "स्कैफोल्डिंग": "scaffolding", "स्ट्रक्चर": "structure", "टेंपल": "temple", "कैनियन": "canyon",
    "हनीसकल": "honeysuckle", "गोल्ड": "gold", "ग्रास": "grass", "सिल्वर": "silver",
    "सरिया": "sariya", "रेबार": "rebar", "कंक्रीट": "concrete", "बर्फ": "ice", "बर्फ़": "ice",
    "शेप": "shape", "वेज़": "wedge",
    "प्लेटफॉर्म": "platform", "लेयर": "layer", "लेयर्स": "layers", "क्लिप": "clip", "क्लिप्स": "clips",
    "लॉक": "lock", "प्रेशर": "pressure", "बैलेंस": "balance", "सपोर्ट": "support",
    "हैक": "hack", "ट्रिक": "trick", "जुगाड़": "jugaad", "देसी": "desi",
    "हैरतअंगेज़": "hairatangez", "हैरान": "hairaan", "चमत्कार": "chamatkaar", "रहस्य": "rahasya",
    "कारीगर": "kaarigar", "कारीगरों": "kaarigaron", "इंजीनियर": "engineer", "इंजीनियरिंग": "engineering",
    "मजदूर": "majdoor", "वजह": "vajah", "कारण": "kaaran",
    "ऊंचाई": "oonchai", "ऊंचा": "ooncha", "ऊंची": "oonchi", "ऊंचे": "oonche",
    "नीचे": "neeche", "ऊपर": "upar", "अंदर": "andar", "बाहर": "baahar",
    "बीच": "beech", "सामने": "saamne", "पीछे": "peeche", "पास": "paas", "दूर": "door",
    "जल्दी": "jaldi", "धीरे": "dheere", "तेज": "tez", "मजबूत": "majboot", "कमजोर": "kamzor",
    "खतरनाक": "khatarnaak", "अजीब": "ajeeb", "सीक्रेट": "secret", "सचमुच": "sachmuch", "वाकई": "waaqai",
    "पहला": "pehla", "पहली": "pehli", "पहले": "pehle", "आखिरी": "aakhiri", "अंतिम": "antim",
    "शुरू": "shuru", "खत्म": "khatam", "सीधा": "seedha", "उल्टा": "ulta", "भारी": "bhaari",
    "अरे": "Arey", "भाई": "bhai", "यार": "yaar", "सुनो": "suno", "सोचो": "socho", "ज़रा": "zara", "जरा": "zara",

    # Loanwords & Nukta-rich common terms
    "एथलीट": "athlete", "एथलीट्स": "athletes",
    "कीचड़": "keechad", "कीचड़": "keechad",
    "सड़क": "sadak", "सड़कें": "sadakein", "सड़क": "sadak", "सड़कें": "sadakein",
    "बढ़ाने": "badhaane", "बढ़ा": "badha", "बढ़": "badh", "बढ़ती": "badhti", "बढ़ते": "badhte",
    "बढ़ाने": "badhaane", "बढ़ा": "badha", "बढ़": "badh", "बढ़ती": "badhti", "बढ़ते": "badhte",
    "दौड़": "daud", "दौड़ा": "dauda", "दौड़ने": "daudne",
    "दौड़": "daud", "दौड़ा": "dauda", "दौड़ने": "daudne",
    "चप्पल": "slippers", "चप्पलें": "slippers", "सैंडल": "sandals", "सैंडल्स": "sandals"
}

# Phonetic character maps for words not covered in the dictionary
VOWEL_MAP = {
    'अ': 'a', 'आ': 'aa', 'इ': 'i', 'ई': 'ee', 'उ': 'u', 'ऊ': 'oo', 'ऋ': 'ri',
    'ए': 'e', 'ऐ': 'ai', 'ओ': 'o', 'औ': 'au', 'अं': 'an', 'अः': 'ah'
}

MATRA_MAP = {
    'ा': 'a', 'ि': 'i', 'ी': 'i', 'ु': 'u', 'ू': 'oo', 'ृ': 'ri',
    'े': 'e', 'ै': 'ai', 'ो': 'o', 'ौ': 'au', 'ं': 'n', 'ँ': 'n', 'ः': 'h',
    'ॅ': 'e', 'ॉ': 'o', '्': ''
}

CONSONANT_MAP = {
    'क': 'k', 'ख': 'kh', 'ग': 'g', 'घ': 'gh', 'ङ': 'ng',
    'च': 'ch', 'छ': 'chh', 'ज': 'j', 'झ': 'jh', 'ञ': 'ny',
    'ट': 't', 'ठ': 'th', 'ड': 'd', 'ढ': 'dh', 'ण': 'n',
    'त': 't', 'थ': 'th', 'द': 'd', 'ध': 'dh', 'न': 'n',
    'प': 'p', 'फ': 'ph', 'ब': 'b', 'भ': 'bh', 'म': 'm',
    'य': 'y', 'र': 'r', 'ल': 'l', 'व': 'v',
    'श': 'sh', 'ष': 'sh', 'स': 's', 'ह': 'h',
    'क्ष': 'ksh', 'त्र': 'tr', 'ज्ञ': 'gy',
    # Single precomposed Devanagari nukta consonants
    '\u0958': 'q',   # क़
    '\u0959': 'kh',  # ख़
    '\u095a': 'gh',  # ग़
    '\u095b': 'z',   # ज़
    '\u095c': 'd',   # ड़
    '\u095d': 'dh',  # ढ़
    '\u095e': 'f',   # फ़
    '\u095f': 'y',   # य़
    # Decomposed Devanagari nukta consonants (char + \u093c)
    'क\u093c': 'q', 'ख\u093c': 'kh', 'ग\u093c': 'gh', 'ज\u093c': 'z',
    'ड\u093c': 'd', 'ढ\u093c': 'dh', 'फ\u093c': 'f', 'य\u093c': 'y',
    'ड़': 'd', 'ढ़': 'dh', 'फ़': 'f', 'ज़': 'z', 'क़': 'q', 'ख़': 'kh', 'ग़': 'gh'
}


# Zero-tolerance fallback mapping: ensures ANY stray Devanagari character is converted to Latin
FALLBACK_DEVANAGARI_TO_LATIN = {
    '\u0904': 'e', '\u0905': 'a', '\u0906': 'aa', '\u0907': 'i', '\u0908': 'ee',
    '\u0909': 'u', '\u090a': 'oo', '\u090b': 'ri', '\u090e': 'e', '\u090f': 'e',
    '\u0910': 'ai', '\u0911': 'o', '\u0912': 'o', '\u0913': 'o', '\u0914': 'au',
    '\u0915': 'k', '\u0916': 'kh', '\u0917': 'g', '\u0918': 'gh', '\u0919': 'ng',
    '\u091a': 'ch', '\u091b': 'chh', '\u091c': 'j', '\u091d': 'jh', '\u091e': 'ny',
    '\u091f': 't', '\u0920': 'th', '\u0921': 'd', '\u0922': 'dh', '\u0923': 'n',
    '\u0924': 't', '\u0925': 'th', '\u0926': 'd', '\u0927': 'dh', '\u0928': 'n',
    '\u092a': 'p', '\u092b': 'ph', '\u092c': 'b', '\u092d': 'bh', '\u092e': 'm',
    '\u092f': 'y', '\u0930': 'r', '\u0931': 'r', '\u0932': 'l', '\u0933': 'l',
    '\u0935': 'v', '\u0936': 'sh', '\u0937': 'sh', '\u0938': 's', '\u0939': 'h',
    '\u0958': 'q', '\u0959': 'kh', '\u095a': 'gh', '\u095b': 'z',
    '\u095c': 'd', '\u095d': 'dh', '\u095e': 'f', '\u095f': 'y',
    '\u093e': 'a', '\u093f': 'i', '\u0940': 'i', '\u0941': 'u', '\u0942': 'u',
    '\u0943': 'ri', '\u0947': 'e', '\u0948': 'ai', '\u094b': 'o', '\u094c': 'au',
    '\u094d': '', '\u0901': 'n', '\u0902': 'n', '\u0903': 'h', '\u093c': ''
}


def _split_punctuation(token: str) -> Tuple[str, str, str]:
    """Separates punctuation, symbols, and Devanagari danda from the core word."""
    # Match leading non-letters
    m_lead = re.match(r'^([^a-zA-Z0-9\u0900-\u097F\u4E00-\u9FFF]+)', token)
    p_lead = m_lead.group(1) if m_lead else ''
    core = token[len(p_lead):]

    # Match trailing non-letters (dandas, em-dashes, commas, periods, etc.)
    m_trail = re.search(r'([^a-zA-Z0-9\u0900-\u097F\u4E00-\u9FFF]+)$', core)
    p_trail = m_trail.group(1) if m_trail else ''
    if p_trail:
        core = core[:-len(p_trail)]
    return p_lead, core, p_trail


def _phonetic_fallback(word: str) -> str:
    """Accurate phonetic Devanagari to Latin converter with natural Hindi vowels."""
    if not word or all(ord(c) < 128 for c in word):
        return word

    out = []
    i = 0
    chars = list(word)
    n = len(chars)

    while i < n:
        c = chars[i]
        # Ignore standalone nukta
        if c == '\u093c':
            i += 1
            continue

        # Check composite with nukta (e.g. क + ़ = क़)
        if i + 1 < n and chars[i+1] == '़':
            comp = c + '़'
            if comp in CONSONANT_MAP:
                c = comp
                i += 1

        if c in VOWEL_MAP:
            out.append(VOWEL_MAP[c])
        elif c in CONSONANT_MAP:
            base = CONSONANT_MAP[c]
            if i + 1 < n and chars[i+1] == '्':
                out.append(base)
                i += 1  # consume halant
            elif i + 1 < n and chars[i+1] in MATRA_MAP:
                matra_char = chars[i+1]
                if matra_char in ('ं', 'ँ'):
                    # Nasal dot: keep inherent 'a' sound (e.g. फ + ं = phan)
                    out.append(base + 'an')
                else:
                    out.append(base + MATRA_MAP[matra_char])
                i += 1  # consume matra
            else:
                # Schwa deletion: omit implicit 'a' at end of word
                if i == n - 1:
                    out.append(base)
                else:
                    out.append(base + 'a')
        elif c in MATRA_MAP:
            out.append(MATRA_MAP[c])
        elif c in FALLBACK_DEVANAGARI_TO_LATIN:
            out.append(FALLBACK_DEVANAGARI_TO_LATIN[c])
        else:
            out.append(c)
        i += 1

    res = ''.join(out)
    # Tidy up common orthography for natural social media Hinglish
    res = re.sub(r'a+', 'a', res)
    res = re.sub(r'ee+', 'i', res)
    res = re.sub(r'oo+', 'u', res)
    return res


def word_to_hinglish(word: str) -> str:
    """Translates a single word from Hindi Devanagari to modern colloquial Hinglish."""
    if not word:
        return ""
    p_lead, core, p_trail = _split_punctuation(word)
    if not core:
        return word

    # Map punctuation: replace Devanagari danda with period or exclamation
    p_trail = p_trail.replace('।', '.').replace('॥', '.')

    # 0. If already English / Latin script, preserve exact spelling and casing!
    if all(ord(c) < 128 for c in core):
        return f"{p_lead}{core}{p_trail}"

    # 1. Exact match in dictionary
    if core in COMMON_WORDS:
        translated = COMMON_WORDS[core]
    elif core.lower() in COMMON_WORDS:
        translated = COMMON_WORDS[core.lower()]
    else:
        # 2. Check hyphenated compounds (e.g. अप्रैल-मई, एक-दो)
        if '-' in core:
            parts = [COMMON_WORDS.get(p, _phonetic_fallback(p)) for p in core.split('-')]
            translated = '-'.join(parts)
        else:
            # 3. Phonetic fallback
            translated = _phonetic_fallback(core)

    return f"{p_lead}{translated}{p_trail}"


def text_to_hinglish(text: str) -> str:
    """Translates a full sentence or paragraph from Hindi Devanagari to natural Hinglish."""
    if not text:
        return ""
    # Replace Devanagari dandas with standard punctuation
    text = text.replace('।', '. ').replace('॥', '. ')
    # Separate adjacent scripts between Chinese and Hindi (e.g. "तुम仙人掌" -> "तुम 仙人掌")
    text = re.sub(r'([\u0900-\u097F]+)([\u4E00-\u9FFF]+)', r'\1 \2', text)
    text = re.sub(r'([\u4E00-\u9FFF]+)([\u0900-\u097F]+)', r'\1 \2', text)

    # Process line by line
    lines = []
    for line in text.splitlines():
        words = line.split()
        converted = [word_to_hinglish(w) for w in words]
        processed_line = " ".join(converted)

        # Zero-Tolerance Guarantee: Eliminate any residual Devanagari codepoints
        if re.search(r'[\u0900-\u097F]', processed_line):
            cleaned = []
            for ch in processed_line:
                if '\u0900' <= ch <= '\u097F':
                    cleaned.append(FALLBACK_DEVANAGARI_TO_LATIN.get(ch, ''))
                else:
                    cleaned.append(ch)
            processed_line = re.sub(r' +', ' ', ''.join(cleaned))

        lines.append(processed_line)
    return "\n".join(lines)


def srt_to_hinglish(srt_content: str) -> str:
    """Converts a complete SRT subtitle file content from Devanagari to Hinglish."""
    output_lines = []
    for line in srt_content.splitlines():
        s_line = line.strip()
        if not s_line or s_line.isdigit() or "-->" in s_line:
            output_lines.append(line)
        else:
            output_lines.append(text_to_hinglish(line))
    return "\n".join(output_lines)
