#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dubbing_studio/anti_accent.py
=============================
Anti-Accent English Pairing & Syllable-Weighted Balancing Engine.

Solves the neural TTS Western accent switching problem:
When two or more English words appear consecutively in Latin script
(e.g., "Digital scale", "Wood beam", "Ancient caves"), neural TTS engines
(ElevenLabs, Gemini Flash TTS) detect an English phrase and switch into
a heavy Western/American accent.

Rules:
1. Multi-syllable / heavy English words stay in English script (Latin alphabet).
2. Non-multi-syllable words (single-syllable) can be written in Hindi Devanagari.
3. Isolated English words (surrounded by Hindi) STAY in English script.
4. When two English words appear together, the word with fewer syllables is
   converted into Devanagari itself (e.g. "Digital scale" -> "Digital स्केल").
   If syllables are equal, the pair is broken so no consecutive English words remain.
"""

import sys
import os
import re
import warnings
import argparse
from pathlib import Path
from typing import Dict, List, Tuple, Optional

warnings.filterwarnings("ignore", category=RuntimeWarning)

# Comprehensive dictionary of English loanwords mapped to Hindi Devanagari
ENGLISH_TO_DEVANAGARI: Dict[str, str] = {
    # Tools, Parts & Hardware
    "scale": "स्केल", "scales": "स्केल्स",
    "beam": "बीम", "beams": "बीम्स",
    "wood": "वुड", "wooden": "वुडन",
    "stone": "स्टोन", "stones": "स्टोन्स",
    "joint": "जॉइंट", "joints": "जॉइंट्स",
    "lock": "लॉक", "locks": "लॉक्स",
    "key": "की", "keys": "कीज़",
    "trick": "ट्रिक", "tricks": "ट्रिक्स",
    "hack": "हैक", "hacks": "हैक्स",
    "tool": "टूल", "tools": "टूल्स",
    "box": "बॉक्स", "boxes": "बॉक्सेस",
    "rope": "रोप", "ropes": "रोप्स",
    "door": "डोर", "doors": "डोर्स",
    "wall": "वाल", "walls": "वाल्स",
    "tree": "ट्री", "trees": "ट्रीज़",
    "grass": "ग्रास", "gold": "गोल्ड",
    "ice": "आइस", "cut": "कट", "cuts": "कट्स",
    "cave": "केव", "caves": "केव्स",
    "bridge": "ब्रिज", "bridges": "ब्रिजेस",
    "block": "ब्लॉक", "blocks": "ब्लॉक्स",
    "frame": "फ्रेम", "frames": "फ्रेम्स",
    "pipe": "पाइप", "pipes": "पाइप्स",
    "wire": "वायर", "wires": "वायर",
    "plug": "प्लग", "plugs": "पलग्स",
    "pin": "पिन", "pins": "पिन्स",
    "board": "बोर्ड", "boards": "बोर्ड्स",
    "ring": "रिंग", "rings": "रिंग्स",
    "gear": "गियर", "gears": "गियर्स",
    "switch": "स्विच", "switches": "स्विचेस",
    "tap": "टैप", "taps": "टैप्स",
    "clip": "क्लिप", "clips": "क्लिप्स",
    "net": "नेट", "nets": "नेट्स",
    "bag": "बैग", "bags": "बैग्स",
    "cap": "कैप", "caps": "कैप्स",
    "fan": "फैन", "fans": "फैन्स",
    "tape": "टेप", "tapes": "टेप्स",
    "base": "बेस", "roof": "रूफ", "floor": "फ्लोर",
    "chain": "चेन", "chains": "चेन्स",
    "bar": "बार", "bars": "बार्न्स",
    "rod": "रॉड", "rods": "रॉड्स",
    "bolt": "बोल्ट", "bolts": "बोल्ट्स",
    "nut": "नट", "nuts": "नट्स",
    "screw": "स्क्रू", "screws": "स्क्रूज़",
    "drill": "ड्रिल", "drills": "ड्रिल्स",
    "saw": "सॉ", "saws": "सॉज़",
    "glue": "ग्लू", "wax": "वैक्स", "oil": "ऑयल",
    "gas": "गैस", "steam": "स्टीम", "smoke": "स्मोक",
    "fire": "फायर", "light": "लाइट", "lights": "लाइट्स",
    "dark": "डार्क", "soft": "सॉफ्ट", "hard": "हार्ड",
    "hot": "हॉट", "cold": "कोल्ड", "clean": "क्लीन",
    "safe": "सेफ", "fast": "फास्ट", "slow": "स्लो",
    "fit": "फिट", "fits": "फिट्स",
    "set": "सेट", "sets": "सेट्स",
    "mix": "मिक्स", "press": "प्रेस",
    "push": "पुश", "pull": "पुल",
    "lift": "लिफ्ट", "drop": "ड्रॉप", "drops": "ड्रॉप्स",
    "turn": "टर्न", "turns": "टर्न्स",
    "test": "टेस्ट", "tests": "टेस्ट्स",
    "check": "चेक", "checks": "चेक्स",
    "mark": "मार्क", "marks": "मार्क्स",
    "shape": "शेप", "shapes": "शेप्स",
    "size": "साइज", "sizes": "साइजेस",
    "weight": "वेट", "speed": "स्पीड", "sound": "साउंड",
    "view": "व्यू", "look": "लुक", "looks": "लुक्स",
    "show": "शो", "shows": "शोज़",
    "part": "पार्ट", "parts": "पार्ट्स",
    "piece": "पीस", "pieces": "पीसेस",
    "end": "एंड", "ends": "एंड्स",
    "and": "और",
    "side": "साइड", "sides": "साइड्स",
    "top": "टॉप", "step": "स्टेप", "steps": "स्टेप्स",
    "type": "टाइप", "types": "टाइप्स",
    "smart": "स्मार्ट",
    "line": "लाइन", "lines": "लाइन्स",
    "point": "पॉइंट", "points": "पॉइंट्स",
    "hand": "हैंड", "hands": "हैंड्स",
    "head": "हेड", "foot": "फुट", "feet": "फीट",
    "face": "फेस", "eye": "आई", "eyes": "आइज",
    "ball": "बॉल", "balls": "बॉल्स",
    "card": "कार्ड", "cards": "कार्ड्स",
    "plate": "प्लेट", "plates": "प्लेट्स",
    "cup": "कप", "cups": "कप्स",
    "glass": "ग्लास", "glasses": "ग्लासेस",
    "pot": "पॉट", "pots": "पॉट्स",
    "pan": "पैन", "pans": "पैन्स",
    "bowl": "बाउल", "bowls": "बाउल्स",
    "spoon": "स्पून", "spoons": "स्पून",
    "knife": "नाइफ", "knives": "नाइव्ज़",
    "blade": "ब्लेड", "blades": "ब्लेड्स",
    "sheet": "शीट", "sheets": "शीट्स",
    "film": "फिल्म", "strip": "स्ट्रिप", "strips": "स्ट्रिप्स",
    "wheel": "व्हील", "wheels": "व्हील्स",
    "car": "कार", "cars": "कार्स",
    "bike": "बाइक", "bikes": "बाइक्स",
    "truck": "ट्रक", "trucks": "ट्रक्स",
    "boat": "बोट", "boats": "बोट्स",
    "ship": "शिप", "ships": "शिप्स",
    "plane": "प्लेन", "planes": "प्लेन्स",
    "road": "रोड", "roads": "रोड्स",
    "track": "ट्रैक", "tracks": "ट्रैक्स",
    "pole": "पोल", "poles": "पोल्स",
    "post": "पोस्ट", "posts": "पोस्ट्स",
    "sign": "साइन", "signs": "साइन्स",
    "gate": "गेट", "gates": "गेट्स",
    "hole": "होल", "holes": "होल्स",
    "tube": "ट्यूब", "tubes": "ट्यूब्स",
    "hose": "होज़", "tank": "टैंक", "tanks": "टैंक्स",
    "pump": "पंप", "pumps": "पंप्स",
    "valve": "वाल्व", "valves": "वाल्व्स",
    "cord": "कॉर्ड", "cords": "कॉर्ड्स",
    "cell": "सेल", "cells": "सेल्स",
    "chip": "चिप", "chips": "चिप्स",
    "screen": "स्क्रीन", "screens": "स्क्रीन्स",
    "port": "पोर्ट", "ports": "पोर्ट्स",
    "slot": "स्लॉट", "slots": "स्लॉट्स",
    "jack": "जैक", "code": "कोड",
    "link": "लिंक", "links": "लिंक्स",
    "site": "साइट", "sites": "साइट्स",
    "page": "पेज", "pages": "पेजेस",
    "file": "फाइल", "files": "फाइल्स",
    "app": "ऐप", "apps": "ऐप्स",
    "game": "गेम", "games": "गेम्स",
    "play": "प्ले", "start": "स्टार्ट", "stop": "स्टॉप",
    "hold": "होल्ड", "run": "रन", "walk": "वॉक",
    "jump": "जंप", "fall": "फॉल", "stand": "स्टैंड",
    "sit": "सिट", "rest": "रेस्ट", "pack": "पैक",
    "seal": "सील", "wrap": "रैप", "fold": "फोल्ड",
    "bend": "बेंड", "twist": "ट्विस्ट", "break": "ब्रेक",
    "snap": "स्नैप", "crack": "क्रैक", "split": "स्प्लिट",
    "tear": "टियर", "stick": "स्टिक", "paste": "पेस्ट",
    "weld": "वेल्ड", "melt": "मेल्ट", "cool": "कूल",
    "heat": "हीट", "dry": "ड्राई", "wet": "वेट",
    "wash": "वॉश", "wipe": "वाइप", "brush": "ब्रश",
    "scrub": "स्क्रब", "pour": "पोर", "fill": "फिल",
    "drain": "ड्रेन", "blow": "ब्लो", "burn": "बर्न",
    "spark": "स्पार्क", "glow": "ग्लो", "shine": "शाइन",
    "flash": "फ्लैश", "fade": "फेड", "hide": "हाइड",
    "find": "फाइंड", "lose": "लूज़", "keep": "कीप",
    "take": "टेक", "give": "गिव", "put": "पुट",
    "bring": "ब्रिंग", "send": "सेंड", "catch": "कैच",
    "hit": "हिट", "strike": "स्ट्राइक", "touch": "टच",
    "pat": "पैट", "rub": "रब", "crush": "क्रश",
    "grind": "ग्राइंड", "mill": "मिल", "shave": "शेव",
    "trim": "ट्रिम", "slice": "स्लाइस", "chop": "चॉप",
    "dice": "डाइस", "peel": "पील", "core": "कोर",
    "pit": "पिट", "seed": "सीड", "seeds": "सीड्स",
    "root": "रूट", "roots": "रूट्स", "stem": "स्टेम", "stems": "स्टेम्स",
    "leaf": "लीफ", "leaves": "लीव्स", "bark": "बार्क",
    "clay": "क्ले", "sand": "सैंड", "dust": "डस्ट",
    "mud": "मड", "rust": "रस्ट", "iron": "आयरन",
    "steel": "स्टील", "zinc": "जिंक", "brass": "ब्रास",
    "bronze": "ब्रॉन्ज", "tin": "टिन", "chrome": "क्रोम",
    "brick": "ब्रिक", "bricks": "ब्रिक्स",
    "tile": "टाइल", "tiles": "टाइल्स",
    "chalk": "चॉक", "lime": "लाइम", "coal": "कोल",
    "coke": "कोक", "tar": "टार", "pitch": "पिच",
    "resin": "रेजिन", "gum": "गम", "sap": "सैप",
    "foam": "फोम", "sponge": "स्पंज", "wool": "वूल",
    "silk": "सिल्क", "flax": "फ्लैक्स", "hemp": "हेम्प",
    "jute": "जूट", "yarn": "यार्न", "thread": "थ्रेड",
    "string": "स्ट्रिंग", "mesh": "मेश", "gauze": "गॉज़",
    "felt": "फेल्ट", "cloth": "क्लॉथ", "rag": "रैग",
    "skin": "स्किन", "fur": "फर", "bone": "बोन", "bones": "बोन्स",
    "horn": "हॉर्न", "shell": "शेल", "fin": "फिन",
    "claw": "क्लॉ", "beak": "बीक", "wing": "विंग", "wings": "विंग्स",
    "tail": "टेल", "tusk": "टस्क", "fang": "फैंग",
    "web": "वेब", "nest": "नेस्ट", "shed": "शेड",
    "barn": "बार्न", "shop": "शॉप", "store": "स्टोर",
    "vault": "वॉल्ट", "arch": "आर्च", "dock": "डॉक",
    "dam": "डैम", "well": "वेल", "shaft": "शाफ्ट",
    "quarry": "क्वेरी", "mine": "माइन", "ramp": "रैंप",
    "slide": "स्लाइड", "rail": "रेल", "cable": "केबल",
    "hook": "हुक", "loop": "लूप", "knot": "नॉट",
    "strap": "स्ट्रैप", "band": "बैंड", "belt": "बेल्ट",
    "stake": "स्टेक", "peg": "पेग", "nail": "नेल", "nails": "नेल्स",
    "spike": "स्पाइक", "clamp": "क्लैंप", "vice": "वाइस",

    # Architectural & Carpentry Terms
    "tenon": "टेनन", "mortise": "मॉर्टिस", "dowel": "डावेल",
    "cantilever": "कैंटिलीवर", "truss": "ट्रस",

    # Everyday Modern & Common 2-Syllable Words
    "camera": "कैमरा", "water": "वाटर", "purple": "पर्पल",
    "magic": "मैजिक", "layer": "लेयर", "layers": "लेयर्स",
    "level": "लेवल", "levels": "लेवल्स", "power": "पावर",
    "super": "सुपर", "mega": "मेगा", "ultra": "अल्ट्रा",
    "mini": "मिनी", "micro": "माइक्रो", "pocket": "पॉकेट",
    "solar": "सोलर", "laser": "लेज़र", "motor": "मोटर",
    "engine": "इंजन", "sensor": "सेंसर", "metal": "मेटल",
    "plastic": "प्लास्टिक", "rubber": "रबर", "silver": "सिल्वर",
    "copper": "कॉपर", "carbon": "कार्बन", "liquid": "लिक्विड",
    "powder": "पाउडर", "crystal": "क्रिस्टल", "diamond": "डायमंड",
    "pattern": "पैटर्न", "system": "सिस्टम", "unit": "यूनिट",
    "model": "मॉडल", "design": "डिजाइन", "style": "स्टाइल",
    "simple": "सिंपल", "single": "सिंगल", "double": "डबल",
    "master": "मास्टर", "expert": "एक्सपर्ट", "normal": "नॉर्मल",
    "special": "स्पेशल", "perfect": "परफेक्ट", "total": "टोटल",
    "final": "फाइनल", "extra": "एक्स्ट्रा", "zero": "ज़ीरो",
    "tunnel": "टनल", "tunnels": "टनल्स", "entry": "एंट्री", "entries": "एंट्रीज़",
    "secret": "सीक्रेट", "secrets": "सीक्रेट्स", "bunker": "बंकर", "bunkers": "बंकर्स",
    "alert": "अलर्ट", "alerts": "अलर्ट्स", "alarm": "अलार्म", "alarms": "अलार्म्स",
    "exit": "एग्जिट", "exits": "एग्जिट्स", "trap": "ट्रैप", "traps": "ट्रैप्स",
    "signal": "सिग्नल", "signals": "सिग्नल्स", "target": "टारगेट", "targets": "टारगेट्स",
    "giant": "जाइंट", "giants": "जाइंट्स", "pagoda": "पगोडा", "pagodas": "पगोडा",
    "tower": "टावर", "towers": "टावर्स", "building": "बिल्डिंग", "buildings": "बिल्डिंग्स",
    "temple": "टेंपल", "temples": "टेंपल्स", "holy": "होली", "book": "बुक", "books": "बुक्स"
}

# Explicit Syllable Exceptions for 100% precision on common video terms
SYLLABLE_EXCEPTIONS: Dict[str, int] = {
    # 1 Syllable (monosyllabic) words
    "scale": 1, "scales": 1, "caves": 1, "cave": 1, "stone": 1, "stones": 1,
    "beam": 1, "beams": 1, "wood": 1, "woods": 1, "joint": 1, "joints": 1,
    "bridge": 1, "lock": 1, "locks": 1, "trick": 1, "tricks": 1,
    "hack": 1, "hacks": 1, "tool": 1, "tools": 1, "box": 1,
    "rope": 1, "ropes": 1, "door": 1, "doors": 1, "wall": 1, "walls": 1,
    "tree": 1, "trees": 1, "grass": 1, "gold": 1, "ice": 1, "cut": 1,
    "smart": 1, "fire": 1, "wire": 1, "tire": 1, "safe": 1, "test": 1,
    "pipe": 1, "wire": 1, "plug": 1, "clamp": 1, "gear": 1, "ring": 1,
    "net": 1, "cap": 1, "bag": 1, "tape": 1, "base": 1, "roof": 1, "floor": 1,
    "chain": 1, "rod": 1, "bar": 1, "bolt": 1, "nut": 1, "screw": 1,
    "drill": 1, "saw": 1, "glue": 1, "wax": 1, "oil": 1, "gas": 1, "steam": 1,
    "smoke": 1, "light": 1, "dark": 1, "soft": 1, "hard": 1, "hot": 1, "cold": 1,
    "clean": 1, "fast": 1, "slow": 1, "fit": 1, "set": 1, "mix": 1, "press": 1,
    "push": 1, "pull": 1, "lift": 1, "drop": 1, "turn": 1, "check": 1, "mark": 1,
    "shape": 1, "size": 1, "weight": 1, "speed": 1, "sound": 1, "view": 1,
    "part": 1, "piece": 1, "end": 1, "and": 1, "side": 1, "top": 1, "step": 1,
    "type": 1, "line": 1, "point": 1, "key": 1, "hand": 1, "head": 1, "foot": 1,
    "card": 1, "plate": 1, "cup": 1, "glass": 1, "pot": 1, "pan": 1, "blade": 1,
    "sheet": 1, "film": 1, "strip": 1, "wheel": 1, "car": 1, "bike": 1, "truck": 1,
    "boat": 1, "ship": 1, "plane": 1, "road": 1, "track": 1, "pole": 1, "post": 1,
    "gate": 1, "hole": 1, "tube": 1, "tank": 1, "pump": 1, "cell": 1, "chip": 1,
    "port": 1, "slot": 1, "code": 1, "link": 1, "site": 1, "page": 1, "file": 1,
    "app": 1, "game": 1, "play": 1, "start": 1, "stop": 1, "hold": 1, "run": 1,
    "walk": 1, "jump": 1, "fall": 1, "stand": 1, "sit": 1, "rest": 1, "pack": 1,
    "seal": 1, "wrap": 1, "fold": 1, "bend": 1, "twist": 1, "break": 1, "snap": 1,
    "crack": 1, "split": 1, "tear": 1, "stick": 1, "paste": 1, "weld": 1, "melt": 1,
    "cool": 1, "heat": 1, "dry": 1, "wet": 1, "wash": 1, "wipe": 1, "brush": 1,
    "pour": 1, "fill": 1, "drain": 1, "blow": 1, "burn": 1, "spark": 1, "glow": 1,
    "shine": 1, "flash": 1, "fade": 1, "hide": 1, "find": 1, "lose": 1, "keep": 1,
    "take": 1, "give": 1, "put": 1, "bring": 1, "send": 1, "catch": 1, "hit": 1,
    "touch": 1, "rub": 1, "crush": 1, "grind": 1, "mill": 1, "slice": 1, "chop": 1,
    "peel": 1, "core": 1, "pit": 1, "seed": 1, "root": 1, "stem": 1, "leaf": 1,
    "bark": 1, "clay": 1, "sand": 1, "dust": 1, "mud": 1, "rust": 1, "steel": 1,
    "tin": 1, "brick": 1, "tile": 1, "chalk": 1, "lime": 1, "coal": 1, "wool": 1,
    "silk": 1, "jute": 1, "yarn": 1, "thread": 1, "string": 1, "cloth": 1, "skin": 1,
    "bone": 1, "horn": 1, "shell": 1, "fin": 1, "claw": 1, "beak": 1, "wing": 1,
    "tail": 1, "shed": 1, "barn": 1, "shop": 1, "store": 1, "arch": 1, "dock": 1,
    "dam": 1, "well": 1, "ramp": 1, "rail": 1, "hook": 1, "loop": 1, "knot": 1,
    "belt": 1, "peg": 1, "nail": 1, "spike": 1,

    # 2 Syllables
    "giant": 2, "giants": 2, "client": 2, "clients": 2, "ancient": 2, "tenon": 2, "mortise": 2, "layer": 2, "water": 2, "purple": 2,
    "magic": 2, "structure": 2, "process": 2, "camera": 2, "power": 2, "super": 2,
    "solar": 2, "laser": 2, "motor": 2, "engine": 2, "sensor": 2, "metal": 2,
    "plastic": 2, "rubber": 2, "silver": 2, "copper": 2, "carbon": 2, "liquid": 2,
    "powder": 2, "crystal": 2, "diamond": 2, "pattern": 2, "system": 2, "unit": 2,
    "model": 2, "design": 2, "style": 2, "simple": 2, "single": 2, "double": 2,
    "master": 2, "expert": 2, "normal": 2, "special": 2, "perfect": 2, "total": 2,
    "final": 2, "extra": 2, "zero": 2, "boxes": 2, "bridges": 2, "pagoda": 3, "pagodas": 3,

    # Multi-syllable (3+ syllables)
    "digital": 3, "hydraulic": 3, "explosion": 3, "chemical": 3, "experiment": 4,
    "architecture": 4, "cantilever": 4, "mechanism": 4, "traditional": 4
}


def count_syllables(word: str) -> int:
    """
    Accurately counts syllables in an English word.
    Uses exception cache first, then rule-based vowel cluster analysis with
    silent 'e', diphthongs, and consonant-le handling.
    """
    w = word.lower().strip()
    w = re.sub(r"[^a-z]", "", w)
    if not w:
        return 0
    if len(w) <= 3:
        return 1

    if w in SYLLABLE_EXCEPTIONS:
        return SYLLABLE_EXCEPTIONS[w]

    # Handle standard English silent trailing 'e'
    w_sub = re.sub(r"(?:[^laeiouy]|ed|es)e$", "", w)

    # Specific vowel combinations that form 2 syllables (dia, io, ia, etc.)
    w_sub = re.sub(r"(ia|io|eo|ua|uo)", r"-\1-", w_sub)

    # Count vowel groups
    vowel_groups = re.findall(r"[aeiouy]+", w_sub)
    count = len(vowel_groups)

    # If word ends in 'le' preceded by consonant, add 1 (e.g. bottle, table)
    if re.search(r"[^aeiouy]le$", w) and not w.endswith(("ale", "ole", "ule", "ile")):
        count += 1

    return max(1, count)


def phonetic_transliterate_fallback(word: str) -> str:
    """
    Fallback phonetic converter for rare English words not present in the dictionary.
    """
    w = word.lower()
    if w.endswith("y") and len(w) > 1 and w[-2] not in "aeiouy":
        w = w[:-1] + "ee"
    subs = [
        ("tion", "शन"), ("sion", "शन"), ("ture", "चर"),
        ("ck", "क"), ("ch", "च"), ("sh", "श"), ("th", "थ"),
        ("ph", "फ"), ("wh", "व्ह"), ("qu", "क्व"), ("ng", "ंग"),
        ("ee", "ी"), ("oo", "ू"), ("ea", "ी"), ("ai", "े"),
        ("ay", "े"), ("oa", "ो"), ("ou", "ाउ"), ("ow", "ो"),
        ("st", "स्ट"), ("sp", "स्प"), ("sk", "स्क"), ("sc", "स्क"),
        ("tr", "ट्र"), ("dr", "ड्र"), ("pr", "प्र"), ("br", "ब्र"),
        ("cr", "क्र"), ("gr", "ग्र"), ("fr", "फ्र"), ("pl", "प्ल"),
        ("bl", "ब्ल"), ("cl", "क्ल"), ("gl", "ग्ल"), ("fl", "फ्ल"),
        ("sm", "स्म"), ("sn", "स्न"), ("sw", "स्व")
    ]
    c_map = {
        "b": "ब", "c": "क", "d": "ड", "f": "फ", "g": "ग",
        "h": "ह", "j": "ज", "k": "क", "l": "ल", "m": "म",
        "n": "न", "p": "प", "q": "क", "r": "र", "s": "स",
        "t": "ट", "v": "व", "w": "व", "x": "क्स", "y": "य", "z": "ज़"
    }
    v_map = {
        "a": "ा", "e": "े", "i": "ि", "o": "ो", "u": "ु"
    }

    res = w
    for pat, rep in subs:
        res = res.replace(pat, rep)

    out = []
    for char in res:
        if "\u0900" <= char <= "\u097F":
            out.append(char)
        elif char in c_map:
            out.append(c_map[char])
        elif char in v_map:
            if not out or out[-1] in ("ा", "े", "ि", "ो", "ु", "ी", "ू"):
                indep = {"a": "आ", "e": "ए", "i": "इ", "o": "ओ", "u": "उ"}
                out.append(indep.get(char, ""))
            else:
                out.append(v_map[char])
        else:
            out.append(char)

    return "".join(out)


def english_to_devanagari(word: str) -> str:
    """
    Translates an English word into Devanagari using the curated dictionary,
    falling back to phonetic transliteration if not found.
    """
    clean = word.lower().strip()
    if clean in ENGLISH_TO_DEVANAGARI:
        return ENGLISH_TO_DEVANAGARI[clean]
    # Check if plural form minus 's' is in dict
    if clean.endswith("s") and len(clean) > 3 and clean[:-1] in ENGLISH_TO_DEVANAGARI:
        return ENGLISH_TO_DEVANAGARI[clean[:-1]] + "्स"
    return phonetic_transliterate_fallback(clean)


def mask_audio_tags(text: str) -> Tuple[str, Dict[str, str]]:
    """
    Protects inline ElevenLabs audio tags like [excited], [shocked], [gasps]
    so they are never treated as spoken English words or transliterated.
    """
    tag_map: Dict[str, str] = {}

    def repl(m):
        placeholder = f"§{len(tag_map)}§"
        tag_map[placeholder] = m.group(0)
        return placeholder

    masked = re.sub(r"\[[a-zA-Z_ ]+\]", repl, text)
    return masked, tag_map


def unmask_audio_tags(text: str, tag_map: Dict[str, str]) -> str:
    """Restores masked audio tags into the final text."""
    for placeholder, original in tag_map.items():
        text = text.replace(placeholder, original)
    return text


def balance_line_text(line: str) -> str:
    """
    Applies the Anti-Accent English Pairing rule to a single line of text:
    - Multi-syllable words stay in English script.
    - Non-multi-syllable words can be in Devanagari.
    - A word is ONLY converted to Devanagari when NEXT TO another English word!
    - If two English words are together, the one with fewer syllables is written in Devanagari.
    - If syllables are equal, converts the second word to break consecutive Latin script.
    """
    # 1. Protect inline audio performance tags
    masked_line, tag_map = mask_audio_tags(line)

    # 2. Tokenize by English words [a-zA-Z]+
    tokens = re.split(r"([a-zA-Z]+)", masked_line)

    # 3. Locate indices of English word tokens
    word_indices = [i for i, t in enumerate(tokens) if t.isalpha()]

    # 4. Group adjacent English words into clusters
    # Words are in the same cluster if the separator between them contains NO Devanagari letters or newlines
    clusters: List[List[int]] = []
    curr_cluster: List[int] = []

    for idx in word_indices:
        if not curr_cluster:
            curr_cluster.append(idx)
        else:
            prev_idx = curr_cluster[-1]
            sep = "".join(tokens[prev_idx + 1 : idx])
            has_devanagari = bool(re.search(r"[\u0900-\u097F]", sep))
            if not has_devanagari and "\n" not in sep:
                curr_cluster.append(idx)
            else:
                clusters.append(curr_cluster)
                curr_cluster = [idx]

    if curr_cluster:
        clusters.append(curr_cluster)

    # 5. Process each cluster
    for cluster in clusters:
        # Isolated single English word: LEAVE UNTOUCHED IN ENGLISH SCRIPT!
        if len(cluster) <= 1:
            continue

        # Two or more consecutive English words:
        # We must break the consecutive run so no 2 Latin words are adjacent.
        while len(cluster) >= 2:
            # Calculate syllable counts for tokens in cluster
            sylls = [(i, count_syllables(tokens[i])) for i in cluster]

            # Choose the token with FEWER syllables to convert into Devanagari
            # If tie, prefer the rightmost/second word (e.g. 'Wood beam' -> 'Wood बीम')
            min_token_idx, _ = min(sylls, key=lambda x: (x[1], -x[0]))

            # Convert selected word to Devanagari
            orig_word = tokens[min_token_idx]
            tokens[min_token_idx] = english_to_devanagari(orig_word)

            # Split cluster at the converted token and continue balancing if any subcluster has >= 2 words
            c_pos = cluster.index(min_token_idx)
            left_sub = cluster[:c_pos]
            right_sub = cluster[c_pos + 1 :]
            cluster = left_sub if len(left_sub) >= 2 else (right_sub if len(right_sub) >= 2 else [])

    reconstructed = "".join(tokens)
    return unmask_audio_tags(reconstructed, tag_map)


def balance_consecutive_english(text_or_srt: str) -> str:
    """
    Applies the Anti-Accent English balancing rule across any string,
    whether raw text, multi-line paragraph, or full SRT format.
    Preserves all SRT timestamps, line indices, and formatting.
    """
    # Map common leaked Chinese terms first
    cjk_map = {
        "独木桥": "Log bridge",
        "榫卯": "Mortise tenon",
        "滚木": "Wood Rollers",
        "机关": "Mechanism",
        "桥梁": "Bridge",
        "大雁塔": "Giant Wild Goose Pagoda",
        "重生": "Rebuild",
        "古法": "Ancient",
    }
    for cjk_term, eng_term in cjk_map.items():
        if cjk_term in text_or_srt:
            text_or_srt = text_or_srt.replace(cjk_term, eng_term)

    # Strip any remaining raw CJK characters
    text_or_srt = re.sub(r'[\u4E00-\u9FFF\u3400-\u4DBF]+', '', text_or_srt)

    lines = text_or_srt.splitlines(keepends=True)
    out_lines = []

    for line in lines:
        # Skip SRT index lines (pure digits) and timestamp lines (-->)
        stripped = line.strip()
        if stripped.isdigit() or "-->" in stripped:
            out_lines.append(line)
        else:
            out_lines.append(balance_line_text(line))

    return "".join(out_lines)


# Prompt Directive to inject into Gemini System Prompt when --anti-accent is active
ANTI_ACCENT_SYSTEM_PROMPT_DIRECTIVE = (
    "\n\n### MANDATORY ANTI-ACCENT & CONSECUTIVE ENGLISH WORD BALANCING RULE:\n"
    "Neural TTS engines (ElevenLabs & Gemini) switch into an unnatural, heavy Western/American accent "
    "whenever two or more English words appear consecutively in Latin script (e.g., 'Digital scale', 'Wood beam', 'Ancient caves').\n"
    "To guarantee 100% native Indian Hindi intonation and eliminate Western accent jumps, follow these STRICT rules:\n"
    "1. **MULTI-SYLLABLE & HEAVY ENGLISH WORDS:** All complex, heavy, or multi-syllable English words (e.g., Digital, Architecture, "
    "Cantilever, Structure, Experiment, Mechanism, Hydraulic, Chemical, Foundation, Ancient, Process, Explosion) MUST be written in ENGLISH SCRIPT (Latin alphabet).\n"
    "2. **STANDALONE ENGLISH WORDS STAY IN ENGLISH:** If an English word appears isolated (surrounded by Hindi words), KEEP IT IN ENGLISH SCRIPT! "
    "(e.g., 'काफ़ी safe तरीक़ा...', 'इस lock को ऐसे खोलो...', 'stone को उठाओ...'). NEVER convert isolated words to Devanagari!\n"
    "3. **CONSECUTIVE ENGLISH PAIR BREAKER (MANDATORY):** Whenever TWO or more English words appear together, NEVER leave both in Latin script! "
    "Choose the word with FEWER syllables (single-syllable words like scale, beam, joint, cave, stone, wood, trick, lock, hack, tree, grass, cup) "
    "and write that specific word in HINDI DEVANAGARI:\n"
    "   * 'Digital scale' -> 'Digital' (3 syllables) stays English, 'scale' (1 syllable) becomes 'स्केल' -> 'Digital स्केल'.\n"
    "   * 'Ancient caves' -> 'Ancient' (2 syllables) stays English, 'caves' (1 syllable) becomes 'केव्स' -> 'Ancient केव्स'.\n"
    "   * 'Wood beam'     -> Syllables equal -> convert second word -> 'Wood बीम'.\n"
    "   * 'Mortise tenon joint' -> 'Mortise टेनन जॉइंट'.\n"
    "   * 'Magic trick'   -> 'Magic' (2 syllables) stays English, 'trick' (1 syllable) becomes 'ट्रिक' -> 'Magic ट्रिक'.\n"
    "This ensures the voiceover keeps crisp English pronunciation for technical terms without triggering jarring Western accents!"
)


def main():
    if sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        description="Anti-Accent English Pairing & Syllable-Weighted Balancing CLI"
    )
    parser.add_argument(
        "--text", type=str, default="",
        help="Input text string to balance"
    )
    parser.add_argument(
        "--srt", type=str, default="",
        help="Path to input SRT file to balance"
    )
    parser.add_argument(
        "--output", "-o", type=str, default="",
        help="Path to save balanced SRT output"
    )
    parser.add_argument(
        "--test", action="store_true",
        help="Run built-in validation test suite"
    )
    args = parser.parse_args()

    if args.test or (not args.text and not args.srt):
        print("=" * 60)
        print(" [Anti-Accent] RUNNING VERIFICATION TEST SUITE")
        print("=" * 60)
        test_cases = [
            ("इस Digital scale पर वज़न देखो", "इस Digital स्केल पर वज़न देखो"),
            ("कारीगर ने Ancient caves में बारूद बनाया", "कारीगर ने Ancient केव्स में बारूद बनाया"),
            ("Wood beam को Mortise tenon joint से लॉक किया गया", "Wood बीम को Mortise टेनन जॉइंट से लॉक किया गया"),
            ("ये Magic trick देखो", "ये Magic ट्रिक देखो"),
            ("Gold grass और Purple tree का रस निकाला", "Gold ग्रास और Purple ट्री का रस निकाला"),
            ("Ice water में डुबोकर प्रोसेस शुरू करो", "आइस water में डुबोकर प्रोसेस शुरू करो"),
            ("काफ़ी safe तरीक़ा है इस lock को खोलने का", "काफ़ी safe तरीक़ा है इस lock को खोलने का"),
            ("[excited] इस Digital scale पर [shocked] Wood beam टेस्ट करो!", "[excited] इस Digital स्केल पर [shocked] Wood बीम टेस्ट करो!")
        ]

        all_passed = True
        for original, expected in test_cases:
            result = balance_consecutive_english(original)
            passed = result.strip() == expected.strip()
            status = "PASS [OK]" if passed else "FAIL [X]"
            if not passed:
                all_passed = False
            print(f"\n{status}")
            print(f"  Input   : {original}")
            print(f"  Result  : {result.strip()}")
            if not passed:
                print(f"  Expected: {expected}")

        print("\n" + "=" * 60)
        print(f" TEST RESULT: {'ALL TESTS PASSED SUCCESSFULLY!' if all_passed else 'SOME TESTS FAILED'}")
        print("=" * 60)
        return

    if args.text:
        balanced = balance_consecutive_english(args.text)
        print("\n--- BALANCED OUTPUT ---")
        print(balanced)

    if args.srt:
        srt_path = Path(args.srt)
        if not srt_path.exists():
            print(f"Error: SRT file not found: {srt_path}")
            sys.exit(1)
        raw_srt = srt_path.read_text(encoding="utf-8")
        balanced_srt = balance_consecutive_english(raw_srt)
        if args.output:
            out_p = Path(args.output)
            out_p.write_text(balanced_srt, encoding="utf-8")
            print(f"[Anti-Accent] Balanced SRT saved to: {out_p}")
        else:
            print("\n--- BALANCED SRT CONTENT ---")
            print(balanced_srt)


if __name__ == "__main__":
    main()
