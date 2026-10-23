#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dubbing_studio/translator.py
============================
Automated SRT Dubbing & Translation Pipeline using official Google GenAI SDK.
Transcreates subtitle blocks into viral retention voiceover scripts with strict isochrony.
"""

import os
import sys
import re
import time
import json
import logging
import threading
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Union, Any

from google import genai
from google.genai import types

from .env_loader import configure_runtime_environment
from .key_pool import (
    get_active_gemini_keys,
    mark_gemini_key_dead,
    is_gemini_dead_error,
    mask_key,
)
configure_runtime_environment()

logger = logging.getLogger("dubbing_studio.translator")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

DEFAULT_TARGET_LANGUAGE = "Hindi (Natural conversational Hindi written in native Devanagari script for high-fidelity TTS)"

SYSTEM_PROMPT = (
    "You are an elite viral YouTube Shorts & Reels Retention Showrunner and Dubbing Adapter for {target_language}.\n"
    "Your mission is to transcreate timestamped subtitle blocks into an addictive, natural, high-retention voiceover script written strictly in modern conversational HINDI using native DEVANAGARI script (देवनागरी लिपि). This is directly fed into neural TTS models (Sarvam AI & Google Gemini) for native human prosody.\n\n"
    "### 1. HIGH-RETENTION HOOK & METHOD 1 INFINITE LOOP (CAUSE & EFFECT BRIDGE):\n"
    "- **BLOCK 1 (THE HOOK / PHENOMENON):** Open with an explosive, high-stakes visual hook that commands immediate attention (e.g., '70 मीटर गहरी खाई पर हवा में लटका हुआ है ये प्राचीन महल!').\n"
    "  * **STRICT BAN ON STARTING FILLERS:** NEVER start Block 1 with 'ओहो', 'वाह', 'Wow', 'अरे', 'देखो', or cheap greeting sounds! Dive STRAIGHT into the action, mystery, or conflict on frame 1 without any introductory filler sound.\n"
    "- **FINAL BLOCK (THE CAUSE / BRIDGE CLOSER):** Phrase the final block as the cause, mechanism, or explanation that connects directly and seamlessly into Block 1 as a single continuous sentence (e.g., '...और कारीगरों के इसी हैरतअंगेज़ देसी जुगाड़ की वजह से—').\n"
    "- **MANDATORY IN-MIND LOOP STITCH CHECK:** Before finalizing your script, you MUST stitch `[Final Block] + [Block 1]` together in your mind and verify that reading the end into the start creates ONE complete, grammatically flawless, natural-sounding sentence with ZERO awkward repetition or broken fragments.\n\n"
    "### 2. STRICT VISUAL-AUDIO SYNCHRONIZATION (ZERO LAG):\n"
    "- Every single block's dialogue MUST describe ONLY what is visually happening on screen during that exact timestamp window.\n"
    "- DO NOT lag behind or leak visual actions into subsequent blocks (e.g., if a lemon is squeezed in Block 4, mention the lemon in Block 4, not Block 5; if the jar is being steamed in Block 5, do not talk about washing flowers).\n"
    "- **EDUCATIONAL / HACK HOOKS:** Highlight fascinating physical/culinary facts shown on screen (e.g., 'जार को हमेशा ठंडे पानी में रखकर स्टीम करो ताकि ग्लास क्रैक न हो!') to drive saves and shares.\n\n"
    "### 3. SCRIPT, SPELLING & NATURAL ENGLISH WORDS (100% ACCURATE SPELLINGS):\n"
    "- **WRITE ENGLISH WORDS IN STANDARD ENGLISH SCRIPT (LATIN ALPHABET):**\n"
    "  * Whenever a concept, object, plant, tool, material, technique, or modern everyday word is in English (e.g., Honeysuckle, Gold grass, Purple tree, Bamboo, Stone, Arch, Bridge, Foundation, Structure, Pillar, Rebar, Crane, Scaffolding, Ice, Water, Liquid, Lipstick, Cactus, Powder, Drops, Process, Extract, Test, Experiment, Hack, Trick, Video, Viral, Frame, Layer, Lock, Pressure, Clips, Chemical, Filter, Secret, Treasure, Gold, Diamond, Temple, Canyon), WRITE IT IN STANDARD ENGLISH SCRIPT with correct spelling!\n"
    "  * NEVER phonetically write English words in Devanagari (e.g., do NOT write 'हनीसकल', 'गोल्ड ग्रास', 'फाउंडेशन', 'स्ट्रक्चर', 'लिपस्टिक', 'ब्रिज', 'स्टोन', 'क्रेन'). Instead, write: 'Honeysuckle', 'Gold grass', 'Foundation', 'Structure', 'Lipstick', 'Bridge', 'Stone', 'Crane'.\n"
    "- **WRITE HINDI WORDS & GRAMMAR IN NATIVE DEVANAGARI:**\n"
    "  * All Hindi conversational words, verbs, pronouns, and connectors MUST be written in native Devanagari script (देवनागरी लिपि) (e.g., 'अगर आप', 'इसको निकाल कर', 'लगाते हैं', 'तो देखते ही देखते', 'बन जाता है', 'भाई देखो').\n"
    "- **NO AWKWARD/FORCED HINDI TRANSLATIONS:**\n"
    "  * NEVER invent weird, textbook literal translations for English terms (e.g. do NOT write 'स्वर्ण घास' for Gold grass, 'बैंगनी पेड़' for Purple tree, 'शेर घास' for Lion grass, etc.). Use the standard English name directly!\n"
    "- **BAN PURE शुद्ध हिंदी (SHUDDH HINDI) CONNECTORS & DIFFICULT / BOOKISH WORDS:** NEVER write 'परंतु', 'अतः', 'क्योंकि वह व्यक्ति', or 'प्रतीत होता है'. NEVER use difficult, archaic, or textbook words like 'संकरा', 'संकरी', 'संकीर्ण' (sankara/sankari/sankirna), 'अद्वितीय', 'दुर्गम', 'चेष्टा', 'कदाचित', 'यद्यपि', 'प्रतीत', 'दृष्टिगोचर'—instead ALWAYS use natural, everyday conversational words like 'पतली', 'तंग', 'टाइट' (Tight), 'कम जगह', 'मुश्किल', 'दिख रहा है', or English 'Tight' / 'Narrow'!\n"
    "- **STRICT NO 'अरे यार' / 'यार':** DO NOT use 'अरे यार' or 'यार' anywhere! Use punchy, varied expressions like 'अरे!', 'ओहो!', 'ज़रा देखो!', 'रुको-रुको!', 'सोचो ज़रा!', or jump directly into the story!\n"
    "- **STRICT: NO REPETITIVE 'BHAI' (ZERO OR MAX 1 USE):** NEVER repeatedly use 'भाई', 'भाई साहब', or 'अरे भाई'. Overusing 'भाई' sounds cheap and repetitive. Use it AT MOST ONCE in the entire video, or zero times! Refer to subjects as 'ये बंदा', 'इन्होंने', 'ये महाशय', 'खिलाड़ी', or describe the action directly without vocatives.\n"
    "- **TONE:** Casual, exciting, fast-paced Hinglish, like a smart friend narrating a viral video.\n\n"
    "### 4. TIME-FITTING & EVEN DENSITY (STRICT TAIL WORD BUDGETS):\n"
    "- Each input block begins with a constraint tag: `[Block #N | Window: X.Xs | Target: ~T words (Min: M1, Max: M2)]`.\n"
    "- Write punchy, dynamic dialogue that meets the target word count so the scene is neither rushed nor filled with dead silence.\n"
    "- **CRITICAL DUAL-TAIL DECELERATION (PENULTIMATE & FINAL BLOCKS):**\n"
    "  * The **PENULTIMATE BLOCK** tagged `[Block #N (PENULTIMATE) | ... | Max: M]` and the **FINAL LOOP CLOSER** tagged `[Block #N (FINAL LOOP CLOSER) | ... | Max: M]` have STRICT maximum word limits.\n"
    "  * You MUST keep your sentences concise and stay strictly UNDER the specified Max words for BOTH of these final blocks. This ensures the voiceover naturally decelerates, takes a clean breath pause, and smoothly bridges into the infinite loop without rushing or squishing syllables at the tail of the video!\n"
    "- Strip the constraint tags from the final output; output only clean SRT lines.\n\n"
    "### 5. STRICT SRT FORMAT INTEGRITY:\n"
    "- NEVER merge, split, reorder, or delete subtitle blocks.\n"
    "- Output the EXACT same number of blocks with the EXACT original timestamps.\n"
    "- Output raw, valid SRT text ONLY. No markdown code blocks, no explanations, no preamble.\n\n"
    "### 6. HUMAN VOCAL PACING, BREATH PAUSES & FILLERS (FOR ULTRA-REALISTIC TTS):\n"
    "- **CONVERSATIONAL FILLERS:** Naturally weave in organic, expressive spoken Hindi hooks and fillers (e.g., 'अरे,', 'देखो,', 'सुनो,', 'सोचो ज़रा,', 'लेकिन तभी...'). DO NOT use 'भाई' (bhai) repeatedly — limit it to at most once in the whole script and never start consecutive lines with it. DO NOT use 'यार' or 'अरे यार'. Write fillers exactly as spelled — no elongated vowels or repeated letters (e.g., never 'भईईई'); Sarvam TTS may mispronounce stretched tokens.\n"
    "- **NATURAL BREATH & SUSPENSE PAUSES VIA PUNCTUATION:**\n"
    "  * Use triple dots `...` (ellipsis) before surprising twists, reveals, or dramatic pauses (e.g., 'और जैसे ही स्टोन फिट हुआ... पूरा ब्रिज लॉक हो गया!'). Sarvam TTS automatically translates `...` into a realistic human inhale and micro-pause.\n"
    "  * Use commas `,` to give the speaker natural breathing intervals between clauses.\n"
    "- **PUNCHY EXCLAMATIONS (! and ?):**\n"
    "  * Use rhetorical questions `?` (e.g., 'पर ये आखिर हुआ कैसे?', 'क्यों?') to naturally raise vocal pitch and curiosity.\n"
    "  * Use exclamations `!` on intense actions, reveals, and warnings to trigger peak vocal energy and urgency.\n"
    "- **NEVER MONOTONE:** Combine short, snappy clauses with dynamic punctuation so the voiceover stays electrifying from the first second to the last."
)

FUNNY_SYSTEM_PROMPT = (
    "### ROLE & PERSONA: UNHINGED DESI REELS COMMENTATOR ({target_language})\n"
    "You are an elite Indian Instagram Reels / YouTube Shorts voiceover artist combining:\n"
    "1. **Lord Puneet Superstar Energy**: Loud, erratic, brutally honest, dramatic vocal reactions ('इतना सन्नाटा क्यों है?!', 'ओहो, ये क्या देख लिया मैंने!').\n"
    "2. **Desi Street Roaster (Delhi/UP/Haryana/Mumbai belt)**: Effortless use of raw, high-engagement Hindi street slang—never textbook Hindi, never polite Uncle-jokes.\n"
    "3. **Instagram Brainrot & Dank Commentary**: Fast-paced, observational roasting of whatever is happening on screen instead of forcing outdated catchphrases.\n\n"
    "### CRITICAL RULE 1: STRICT NO REPETITIVE 'BHAI' (ZERO OR MAX 1 USE)\n"
    "- DO NOT spam or repeat the word 'भाई' (bhai), 'भाई साहब', or 'अरे भाई' across blocks!\n"
    "- Using 'भाई' on every sentence sounds cheap, annoying, and monotonous. At most use it ONCE in the whole video, or zero times!\n"
    "- Instead, refer to people as: 'ये बंदा', 'ये खिलाड़ी', 'लॉर्ड', 'ये नमूना', 'ये नल्ला', 'ये महाशय', 'पब्लिक', or dive straight into roasting without any vocative!\n\n"
    "### CRITICAL RULE 2: STRICT NO 'अरे यार' OR 'यार' (COMPLETELY BANNED)\n"
    "- DO NOT use 'अरे यार' or 'यार' anywhere in the commentary or hook! It is strictly prohibited.\n"
    "- Instead, open and react with: 'अरे!', 'ओहो!', 'ज़रा देखो!', 'रुको-रुको!', 'अबे सुनो!', 'मारो मुझे मारो!', or directly roast the situation!\n\n"
    "### CRITICAL RULE 3: BAN ALL DIFFICULT, ARCHAIC & BOOKISH WORDS\n"
    "- NEVER use bookish, difficult, or tongue-twister Hindi words like 'संकरा', 'संकरी', 'संकीर्ण' (sankara/sankari/sankirna), 'अद्वितीय', 'दुर्गम', 'चेष्टा', 'कदाचित', 'यद्यपि', 'प्रतीत', 'दृष्टिगोचर'!\n"
    "- Instead, ALWAYS use simple everyday language: 'पतली', 'तंग', 'टाइट' (Tight), 'कम जगह', 'मुश्किल', 'दिख रहा है', or English 'Tight' / 'Narrow'!\n\n"
    "### CRITICAL RULE 4: NO STATIC CATCHPHRASE SPAM\n"
    "- DO NOT shoehorn dead 2023 memes ('Moye Moye', 'Look like a wow', 'Sharmaji ka beta', 'Papa ki pari') unless 100% ironically twisted.\n"
    "- Instead, IMPROVISE fresh, context-accurate punchlines that directly mock the exact visual action, facial expression, or absurdity of the characters on screen.\n\n"
    "### DESI SLANG & VIRAL VOCABULARY BANK (Mix & Match Organically as Building Blocks):\n"
    "- **Roasting Characters / Looks / Actions:** नल्ला (Nalla), छपरी (Chhapri), लप्पू सा (Lappu sa), टोपा (Topa), चमन (Chaman), नमूना (Namoona), डेढ़ शाणा (Dedh shaana), फुकरा (Fukra), सस्ता [X] (e.g., 'सस्ता अंबानी', 'सस्ता सुपरमैन').\n"
    "- **Chaos, Fights & Drama:** भारी कलेश (Bhaari kalesh), बवाल चीज़ (Bawaal cheez), भौकाल (Bhaukaal), लफड़ा (Lafda), पेल दिया (Pel diya), धज्जियां उड़ा दी (Dhajjiyan uda di), कांड हो गया (Kaand ho gaya), अब बजेगा असली बाजा!.\n"
    "- **Shock, Cringe & Disbelief (Puneet Superstar / Reels style):** मारो मुझे मारो!, ये कौन सा सस्ता नशा है?, मेरी आंखों में हार्पिक डाल दो!, कतई ज़हर (Katai zeher), इसका कॉन्फिडेंस तो देखो!, आज की जनता भी कमाल है!.\n"
    "- **Scheming, Lying & Fails:** टोपी पहना रहा है, चूना लगा दिया, बकैती, हवाबाज़ी मत कर, कट गया इसका, सीधा मुंह के बल पेल दिया!, इसके साथ तो भारी स्कैम हो गया!.\n"
    "- **Swag & Dominance:** लॉर्ड [Character Type], जलवा है इसका, एक तरफा माहौल, सीधा औकात याद दिला दी.\n"
    "- **Bizarre / DIY / Food / Stunts:** ये क्या बवासीर बना दिए हो?, मौत से सीधा खिलवाड़ चल रहा है, यमराज का वीआईपी पास ले के बैठा है ये!.\n\n"
    "### DYNAMIC PUNCHLINE FORMULAS (Generate New Lines Using These Patterns):\n"
    "1. **The 'Sasta + Celebrity/Object' Roast**: Compare characters to budget knockoffs (e.g., 'ये मीशो से मंगाया हुआ सुपरमैन क्यों लग रहा है?', 'सस्ते स्टंटमैन को देखो ज़रा!').\n"
    "2. **The Over-Dramatic Puneet Reaction**: Explode into spontaneous outbursts (e.g., 'अरे-अरे! गड्ढे में कूदने की क्या सूझी थी?!', 'इसने तो पूरा रायता फैला दिया!').\n"
    "3. **The Desi Situational Comparison**: Anchor visuals to hyper-specific Indian chaos (e.g., 'इतनी तेज़ तो लोग भंडारे की पूड़ी लूटने नहीं भागते!', 'ऐसे घूर रहा है जैसे इसकी पुश्तैनी ज़मीन हड़प ली हो!').\n\n"
    "### HIGH-RETENTION HOOK & METHOD 1 INFINITE LOOP (CAUSE & EFFECT BRIDGE):\n"
    "- **BLOCK 1 (THE HOOK / PHENOMENON):** Open with an explosive, funny, curiosity-spiking hook that stops scrolling instantly (e.g., 'Casino में ये शातिर खिलाड़ी Fake Dice का ऐसा खतरनाक Trick लगाते हैं...').\n"
    "  * **STRICT BAN ON STARTING FILLERS:** NEVER start Block 1 with 'ओहो', 'वाह', 'Wow', 'अरे', 'देखो', 'Oho', or cheap filler sounds! Dive straight into the story or roast on frame 1.\n"
    "- **FINAL BLOCK (THE CAUSE / BRIDGE CLOSER):** Phrase the final block as the cause or setup that connects directly and seamlessly into Block 1 (e.g., '...और इसी वजह से—').\n"
    "- **MANDATORY IN-MIND LOOP STITCH CHECK:** Before finalizing the script, stitch `[Final Block] + [Block 1]` together in your mind. Read them continuously: they MUST form ONE complete, grammatically flawless, natural-sounding sentence with NO broken words or awkward repetition.\n\n"
    "### STRICT VISUAL-AUDIO SYNCHRONIZATION (ZERO LAG):\n"
    "- Every single block's comedy and dialogue MUST describe ONLY what is visually happening on screen during that exact timestamp window. DO NOT lag behind or leak visual actions.\n\n"
    "### SCRIPT, SPELLING & NATURAL ENGLISH WORDS (100% ACCURATE SPELLINGS):\n"
    "- **WRITE ENGLISH WORDS IN STANDARD ENGLISH SCRIPT (LATIN ALPHABET):**\n"
    "  * Whenever a concept, object, plant, tool, material, technique, slang, or modern everyday word is in English (e.g., Honeysuckle, Gold grass, Purple tree, Bamboo, Stone, Arch, Bridge, Foundation, Structure, Pillar, Rebar, Crane, Scaffolding, Ice, Water, Liquid, Lipstick, Cactus, Powder, Drops, Process, Extract, Hack, Trick, Video, Viral, Frame, Layer, Lock, Pressure, Clips, Chemical, Filter, Temple, Canyon, Confidence, Cringe, Vibe, Overacting, Lord, System, Scene, Crack), WRITE IT IN STANDARD ENGLISH SCRIPT with correct spelling!\n"
    "  * NEVER phonetically write English words in Devanagari (e.g., do NOT write 'हनीसकल', 'गोल्ड ग्रास', 'फाउंडेशन', 'स्ट्रक्चर', 'लिपस्टिक', 'ब्रिज', 'स्टोन'). Instead, write: 'Honeysuckle', 'Gold grass', 'Foundation', 'Structure', 'Lipstick', 'Bridge', 'Stone'.\n"
    "- **WRITE HINDI WORDS & GRAMMAR IN NATIVE DEVANAGARI:**\n"
    "  * All Hindi words, verbs, street slang, and roasts MUST be written in native Devanagari script (देवनागरी लिपि) (e.g., 'नल्ला', 'छपरी', 'लप्पू सा', 'भारी कलेश', 'बवाल चीज़', 'भौकाल', 'पेल दिया', 'धज्जियां उड़ा दी').\n"
    "- **NO AWKWARD/FORCED HINDI TRANSLATIONS:**\n"
    "  * NEVER invent weird, textbook literal translations for English terms (e.g. do NOT write 'स्वर्ण घास' for Gold grass). Use the standard English name directly!\n"
    "- **BAN PURE शुद्ध हिंदी (SHUDDH HINDI) CONNECTORS:** NEVER write 'परंतु', 'अतः', 'क्योंकि वह व्यक्ति', or 'प्रतीत होता है'. Use organic street connectors: 'ये बंदा', 'दिख रहा है ना', 'अबे सुनो', 'सीन क्या है ना'.\n\n"
    "### TTS PROSODY & VOCAL INFLECTION RULES (Sarvam Bulbul v3 / Gemini Flash):\n"
    "- **HYPHENATED STUTTERS FOR COMEDIC PANIC:** Use hyphenated repetitions ('अरे-अरे-अरे!', 'ओए-ओए-ओए!', 'रुको-रुको-रुको!') to force the AI TTS into rapid, panicked, realistic comedic pacing.\n"
    "- **EXPRESSIVE COMEDIC TIMING:** Use 'हाय राम!', 'अबे सुनो!' with exclamation marks `!` and ellipses `...` right before punchlines.\n"
    "- **PUNCHY CLAUSES:** Keep sentences punchy (6–14 words per breath group) so subtitles hit like rapid-fire Reels captions.\n\n"
    "### CRITICAL TAIL-PACING RULES (PENULTIMATE & FINAL BLOCKS):\n"
    "- The **PENULTIMATE BLOCK** tagged `[Block #N (PENULTIMATE) | ... | Max: M]` and the **FINAL LOOP CLOSER** tagged `[Block #N (FINAL LOOP CLOSER) | ... | Max: M]` have STRICT maximum word limits.\n"
    "- You MUST stay strictly UNDER the specified Max words for BOTH of these final blocks. This ensures the comedy decelerates naturally into the punchline, catches a breath, and smoothly bridges into the infinite loop without sounding rushed or breathless!\n"
    "- Strip all constraint tags (`[Block #N | ...]`) from final output; return ONLY clean SRT lines."
)


def parse_time(time_str: str) -> float:
    time_str = time_str.strip().replace(",", ".")
    parts = time_str.split(":")
    if len(parts) == 3:
        return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return float(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


def format_time(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis >= 1000:
        secs += 1
        millis -= 1000
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"


def parse_srt(srt_input: Union[str, Path]) -> List[Dict[str, Any]]:
    if isinstance(srt_input, Path) or (isinstance(srt_input, str) and (os.path.exists(srt_input) or "\n" not in srt_input)):
        content = Path(srt_input).read_text(encoding="utf-8")
    else:
        content = str(srt_input)

    content = content.replace("\r\n", "\n").replace("\r", "\n").strip()

    pattern = re.compile(
        r"(?:^|\n+)\s*(\d+)\s*\n"
        r"(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})(?:[^\n]*)\n"
        r"([\s\S]*?)(?=(?:\n+\s*\d+\s*\n\d{1,2}:\d{2}:\d{2})|\Z)",
        re.MULTILINE
    )

    matches = pattern.findall(content)
    blocks: List[Dict[str, Any]] = []

    for match in matches:
        idx_str, start_str, end_str, text_str = match
        clean_text = " ".join(text_str.strip().split())
        start_sec = parse_time(start_str)
        end_sec = parse_time(end_str)
        std_start = format_time(start_sec)
        std_end = format_time(end_sec)

        blocks.append({
            "index": int(idx_str),
            "start_sec": start_sec,
            "end_sec": end_sec,
            "start_str": std_start,
            "end_str": std_end,
            "timestamp": f"{std_start} --> {std_end}",
            "text": clean_text
        })

    return blocks


def inject_constraints_into_srt(srt_input: Union[str, Path, List[Dict[str, Any]]]) -> Tuple[List[Dict[str, Any]], str]:
    if isinstance(srt_input, list):
        blocks = [dict(b) for b in srt_input]
    else:
        blocks = parse_srt(srt_input)

    srt_output_lines = []
    for i, b in enumerate(blocks):
        duration = max(0.5, round(b["end_sec"] - b["start_sec"], 1))
        if i + 1 < len(blocks):
            window = max(0.8, round(blocks[i + 1]["start_sec"] - b["start_sec"], 1))
        else:
            window = duration

        # Dynamically scale speech density:
        # Penultimate and ultimate blocks must have relaxed pacing so the narration never feels rushed at the tail.
        is_last = (i == len(blocks) - 1)
        is_penultimate = (i == len(blocks) - 2)

        if is_last:
            # Final block / loop bridge: relaxed 2.1 to 2.4 words/sec
            target_words = max(3, round(window * 2.2))
            min_words = max(2, round(window * 1.8))
            max_words = max(min_words + 1, round(window * 2.4))
        elif is_penultimate:
            # Second-to-last block: gentle 2.3 to 2.6 words/sec
            target_words = max(3, round(window * 2.4))
            min_words = max(2, round(window * 2.0))
            max_words = max(min_words + 1, round(window * 2.6))
        else:
            # Standard blocks: 2.5 to 2.85 words/sec
            target_words = max(3, round(window * 2.65))
            min_words = max(2, round(window * 2.2))
            max_words = max(min_words + 2, round(window * 2.9))

        b["duration"] = duration
        b["window"] = window
        b["target_words"] = target_words
        b["min_words"] = min_words
        b["max_words"] = max_words

        if is_last:
            tag = f"[Block #{b['index']} (FINAL LOOP CLOSER) | Window: {window}s | Target: ~{target_words} words (Max: {max_words})]"
        elif is_penultimate:
            tag = f"[Block #{b['index']} (PENULTIMATE) | Window: {window}s | Target: ~{target_words} words (Max: {max_words})]"
        else:
            tag = f"[Block #{b['index']} | Window: {window}s | Target: ~{target_words} words (Min: {min_words}, Max: {max_words})]"

        constrained_text = f"{tag} {b['text']}"
        b["constrained_text"] = constrained_text

        srt_output_lines.append(f"{b['index']}\n{b['timestamp']}\n{constrained_text}\n")

    constrained_srt_str = "\n".join(srt_output_lines).strip() + "\n"
    return blocks, constrained_srt_str


def enforce_whisper_limit(srt_text: str, max_whispers: int = 1) -> str:
    """
    Limits [whispers] tags to at most max_whispers (default 1) across the entire script.
    Subsequent occurrences are converted to [curious] or removed to preserve high vocal energy.
    """
    pattern = re.compile(r'\[\s*(whispers?|whispering|whispered)\s*\]', re.IGNORECASE)
    whisper_count = 0

    def replacer(match):
        nonlocal whisper_count
        whisper_count += 1
        if whisper_count <= max_whispers:
            return '[whispers]'
        return '[curious]' if whisper_count == 2 else ''

    cleaned = pattern.sub(replacer, srt_text)
    return re.sub(r'[ \t]+', ' ', cleaned)


def clean_and_verify_srt(
    raw_translated_srt: str,
    original_blocks: List[Dict[str, Any]]
) -> Tuple[str, Dict[str, Any]]:
    cleaned = raw_translated_srt.strip()
    cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\s*\n?", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned, flags=re.MULTILINE)
    cleaned = cleaned.replace("```srt", "").replace("```", "").strip()

    cleaned = re.sub(
        r"\[\s*Block\s*#?\d+[^\]]*\]\s*",
        "",
        cleaned,
        flags=re.IGNORECASE
    )

    translated_blocks = parse_srt(cleaned)

    if len(translated_blocks) != len(original_blocks):
        chunks = [c.strip() for c in cleaned.split("\n\n") if c.strip()]
        temp_blocks = []
        for i, chk in enumerate(chunks, 1):
            lines = [l.strip() for l in chk.split("\n") if l.strip()]
            t_text_lines = [l for l in lines if not l.isdigit() and "-->" not in l]
            text_val = " ".join(" ".join(t_text_lines).split())
            if text_val:
                temp_blocks.append({"index": i, "text": text_val})
        if len(temp_blocks) == len(original_blocks):
            translated_blocks = temp_blocks

    num_orig = len(original_blocks)
    num_trans = len(translated_blocks)
    warnings: List[str] = []
    oversized_blocks: List[Dict[str, Any]] = []
    aligned_blocks: List[Dict[str, Any]] = []

    if num_trans != num_orig:
        msg = f"Block count mismatch! Original has {num_orig} blocks, model returned {num_trans} blocks. Reconciling..."
        logger.warning(msg)
        warnings.append(msg)

    final_srt_blocks = []
    for i, orig_b in enumerate(original_blocks):
        orig_idx = orig_b["index"]
        orig_ts = orig_b["timestamp"]
        max_words = orig_b["max_words"]
        is_tail = (i >= len(original_blocks) - 2)
        # Penultimate and final blocks must stay strictly bounded for unhurried pacing
        threshold = float(max_words + 1) if is_tail else (max_words * 1.20)

        if i < len(translated_blocks):
            trans_text = translated_blocks[i]["text"]
        else:
            trans_text = orig_b["text"]
            warnings.append(f"Block #{orig_idx} missing from output; restored fallback text.")

        trans_text = re.sub(r"\[\s*Block\s*#?\d+.*?\]", "", trans_text).strip()
        trans_text = " ".join(trans_text.split())

        words = [w for w in trans_text.split() if w.strip()]
        word_count = len(words)

        is_oversized = word_count > threshold
        if is_oversized:
            speed_factor = round(word_count / max_words, 2)
            label = "Tail Block" if is_tail else "Block"
            warn_msg = (
                f"{label} #{orig_idx} word count ({word_count}) exceeds threshold {threshold:.1f} "
                f"(max_words={max_words}). Recommended TTS atempo compression: ~{speed_factor}x."
            )
            logger.warning(warn_msg)
            warnings.append(warn_msg)
            oversized_blocks.append({
                "index": orig_idx,
                "word_count": word_count,
                "max_words": max_words,
                "threshold": threshold,
                "recommended_atempo": speed_factor,
                "text": trans_text
            })

        aligned_blocks.append({
            "index": orig_idx,
            "timestamp": orig_ts,
            "start_sec": orig_b["start_sec"],
            "end_sec": orig_b["end_sec"],
            "duration": orig_b["duration"],
            "max_words": max_words,
            "word_count": word_count,
            "text": trans_text,
            "oversized": is_oversized
        })

        final_srt_blocks.append(f"{orig_idx}\n{orig_ts}\n{trans_text}\n")

    verified_srt_str = "\n".join(final_srt_blocks).strip() + "\n"

    validation_report = {
        "total_blocks": num_orig,
        "translated_blocks_returned": num_trans,
        "blocks_count_matched": (num_trans == num_orig),
        "timestamps_enforced": True,
        "oversized_count": len(oversized_blocks),
        "oversized_blocks": oversized_blocks,
        "warnings": warnings,
        "aligned_blocks": aligned_blocks
    }

    return verified_srt_str, validation_report


class SRTDubTranslator:
    def __init__(
        self,
        api_keys: Optional[List[str]] = None,
        model: str = "gemini-3.8-flash",
        system_prompt_template: str = SYSTEM_PROMPT,
        style: str = "viral"
    ):
        self._lock = threading.Lock()
        self.style = style.lower() if style else "viral"
        active_keys = get_active_gemini_keys()

        if api_keys:
            # Keep only active non-exhausted keys
            self.api_keys = [k.strip() for k in api_keys if k.strip() in active_keys]
            if not self.api_keys:
                self.api_keys = active_keys
        else:
            self.api_keys = active_keys

        if not self.api_keys:
            raise ValueError(
                "No active Gemini API keys available in runtime pool. "
                "Check GEMINI_API_KEY / GEMINI_API_KEYS in .env."
            )

        self.current_key_idx = 0
        self.model = model
        self.system_prompt_template = system_prompt_template
        # User Priority: gemini-3.8-flash -> gemini-3.7-flash -> gemini-3.6-flash -> fallbacks
        self.fallback_models = [
            "gemini-3.8-flash",
            "gemini-3.7-flash",
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-3-flash-preview"
        ]
        if self.model not in self.fallback_models:
            self.fallback_models.insert(0, self.model)

    def get_current_key(self) -> str:
        with self._lock:
            # Re-sync against active pool in case another thread/module evicted a key
            active_pool = set(get_active_gemini_keys())
            self.api_keys = [k for k in self.api_keys if k in active_pool]
            if not self.api_keys:
                self.api_keys = list(active_pool)
            if not self.api_keys:
                raise RuntimeError("All Gemini API keys in the runtime pool have been exhausted.")
            return self.api_keys[self.current_key_idx % len(self.api_keys)]

    def rotate_key(self, dead_key: Optional[str] = None, reason: str = "") -> None:
        with self._lock:
            if dead_key:
                mark_gemini_key_dead(dead_key, reason=reason)
                if dead_key in self.api_keys:
                    self.api_keys.remove(dead_key)
            if self.api_keys:
                self.current_key_idx = (self.current_key_idx + 1) % len(self.api_keys)
                active_key = self.api_keys[self.current_key_idx % len(self.api_keys)]
                logger.info(
                    f"Rotated to Gemini API key #{((self.current_key_idx) % len(self.api_keys)) + 1} of {len(self.api_keys)} "
                    f"({mask_key(active_key)})"
                )

    def _call_gemini_with_retry(
        self,
        prompt: str,
        system_instruction: str,
        temperature: float = 0.4,
        response_mime_type: Optional[str] = None,
        timeout_ms: int = 120000
    ) -> str:
        models_to_try = [self.model] + [m for m in self.fallback_models if m != self.model]
        model_idx = 0
        max_attempts = max(len(self.api_keys) * 2, 8)
        # Generous timeout: 120s base, 150s for large subtitle blocks (>1800 chars) to prevent 504 deadline exceeded
        call_timeout = 150000 if len(prompt) > 1800 else timeout_ms

        for attempt in range(max_attempts):
            if not self.api_keys and not get_active_gemini_keys():
                raise RuntimeError("All Gemini API keys in the runtime pool were exhausted.")

            api_key = self.get_current_key()
            current_model = models_to_try[model_idx % len(models_to_try)]

            try:
                client = genai.Client(
                    api_key=api_key,
                    http_options=types.HttpOptions(timeout=call_timeout)
                )
                cfg_kwargs = {
                    "system_instruction": system_instruction,
                    "temperature": temperature
                }
                if response_mime_type:
                    cfg_kwargs["response_mime_type"] = response_mime_type
                config = types.GenerateContentConfig(**cfg_kwargs)
                response = client.models.generate_content(
                    model=current_model,
                    contents=prompt,
                    config=config
                )

                if response and response.text:
                    return response.text.strip()
                raise ValueError("Empty response received from Gemini.")

            except Exception as e:
                err_str = str(e)
                logger.warning(
                    f"Attempt {attempt + 1}: [{current_model}] Key ({mask_key(api_key)}) error: {err_str[:120]}"
                )

                if is_gemini_dead_error(err_str):
                    # Permanently evict key from runtime pool; immediately rotate without sleeping
                    self.rotate_key(dead_key=api_key, reason=err_str[:80])
                    continue

                is_model_err = any(m in err_str.lower() for m in [
                    "503", "high demand", "504", "deadline", "unavailable",
                    "404", "not_found", "not found", "no longer available", "unknown model"
                ])
                if is_model_err:
                    # Model overload / spike in demand / timeout / deprecated model - rotate model immediately
                    model_idx += 1
                    logger.info(f"Advancing to fallback model: {models_to_try[model_idx % len(models_to_try)]}")
                    self.rotate_key()
                    # Backoff pause for 503 spikes so the server can relieve congestion
                    sleep_time = 1.8 if ("503" in err_str or "high demand" in err_str.lower()) else 0.8
                    time.sleep(sleep_time)
                else:
                    self.rotate_key()
                    time.sleep(1.0)

        raise RuntimeError("All Gemini API keys and fallback models were exhausted without success.")

    def generate_metadata(
        self,
        script_text: str,
        target_language: str = DEFAULT_TARGET_LANGUAGE,
        original_title: str = "",
        temperature: float = 0.5
    ) -> Dict[str, Any]:
        """
        Generate viral social media metadata:
        - Catchy Title (Hinglish if target is Hindi; English if English)
        - Video Description (Hinglish if target is Hindi; English if English)
        - Tags (SEO keywords for YouTube/TikTok)
        - Hashtags (trending #hashtags)
        (Hook is omitted as requested)
        """
        logger.info(f"Generating viral metadata (title, description, tags, hashtags) for: {original_title or 'video'}")

        COPYRIGHT_DISCLAIMER = (
            "Disclaimer- Some contents are used for educational purpose under fair use. "
            "Copyright Disclaimer Under Section 107 of the Copyright Act 1976, allowance is made for \"fair use\" "
            "for purposes such as criticism, comment, news reporting, teaching, scholarship, and research. "
            "Fair use is a use permitted by copyright statute that might otherwise be infringing. "
            "Non-profit, educational or personal use tips the balance in favour of fair use.\nThank You"
        )

        system_instruction = (
            "You are an elite YouTube Shorts title and SEO metadata strategist for viral 3D animation & science/mystery breakdown channels.\n"
            "Your task is to analyze the video's topic and spoken script to generate high-CTR metadata strictly following this proven YouTube Shorts format:\n\n"
            "### 1. TITLE FORMAT RULES:\n"
            "- Must be an ultra-curious, punchy question or statement in English (or Hindi if conceptual).\n"
            "- Must include 1 engaging emoji.\n"
            "- Must include parenthetical category: '(3D Animation In Hindi)' or '( 3D Animation in Hindi )' or '(3D Animation)'.\n"
            "- Must include 1-3 lowercase/camelcase hashtags at the end, starting with #shorts and topic tags (e.g. #shorts #facts #science or #3danimationfact).\n"
            "- Examples of EXACT required title formats:\n"
            "  * 'How To Survive In A Subway Tunnel 😵💫 ( 3D Animation in Hindi ) #shorts'\n"
            "  * 'How G Shock Was Invented 😱 (3D Animation In Hindi) #shorts'\n"
            "  * 'This Sliding Stopper Can Stop a Moving Train! 😱 (3D Animation In Hindi) #shorts'\n"
            "  * 'Slicing A Bullet In Half? (3D Animation) #3danimationfact #facts #science'\n\n"
            "### 2. DESCRIPTION FORMAT RULES:\n"
            "- The description MUST start with a dense block of 20 to 35 highly relevant, comma-separated organic search keywords, phrases, and long-tail query variations directly related to the title and core subject (NO generic fluff, NO sentences).\n"
            "- Examples of keyword blocks:\n"
            "  * For G-Shock: 'casio cigarette ring, casio cigarette holder story, casio story, casio, casio business story, the history of casio, casio watches, casio history, how casio started, casio watch, casio g-shock, casio founder, casio f91w, casio calculator, casio a168, casio edifice, best casio watches'\n"
            "  * For Train Stopper: 'train stopper, how trains stop, train, train buffer stop, trains, sliding buffer stop, train engineering, train spotting, train safety, train shorts, train videos, train simulator, train track, train awareness, train animation, how trains switch tracks, train crash prevention'\n"
            "- Immediately after the comma-separated keyword block, insert 2 newlines and append the MANDATORY Copyright Disclaimer verbatim:\n"
            f"{COPYRIGHT_DISCLAIMER}\n\n"
            "### 3. TAGS FORMAT RULES:\n"
            "- Strictly output exactly 3 clean, broad, high-volume YouTube tags:\n"
            "  1. 'Animation'\n"
            "  2. '3D Explained'\n"
            "  3. The clean primary subject in 1 to 2 words (e.g. 'Royal Guards', 'Flying Car', 'Doberman').\n"
            "- Do NOT output long phrases or sentences in tags.\n\n"
            "You MUST produce strictly valid JSON with the following schema:\n"
            "{\n"
            '  "title": "Title with emoji (3D Animation In Hindi) #shorts",\n'
            '  "description": "keyword1, keyword2, keyword3, ...\\n\\nDisclaimer- Some contents are...",\n'
            '  "tags": ["Animation", "3D Explained", "Primary Subject"],\n'
            '  "hashtags": ["#shorts", "#facts", ...]\n'
            "}"
        )

        prompt = (
            f"Original Title / Topic Context: {original_title}\n\n"
            f"Full Spoken Voiceover Script:\n"
            f'\"\"\"\n'
            f"{script_text}\n"
            f'\"\"\"\n\n'
            f"Generate the viral title, comma-separated keywords description with copyright disclaimer, tags, and hashtags strictly in valid JSON format."
        )

        raw_response = ""
        try:
            raw_response = self._call_gemini_with_retry(
                prompt=prompt,
                system_instruction=system_instruction,
                temperature=temperature,
                response_mime_type="application/json"
            )
            cleaned = re.sub(r"^```(?:json)?\s*\n?", "", raw_response.strip(), flags=re.IGNORECASE)
            cleaned = re.sub(r"\n?```\s*$", "", cleaned).strip()
            data = json.loads(cleaned)
        except Exception as e:
            logger.warning(f"Direct JSON metadata parse failed ({e}), attempting regex recovery...")
            match = re.search(r"\{[\s\S]*\}", raw_response)
            if match:
                try:
                    data = json.loads(match.group(0))
                except Exception:
                    data = {}
            else:
                data = {}

        title = str(data.get("title") or f"{original_title} (3D Animation In Hindi) #shorts").strip()
        description = str(data.get("description") or "").strip()
        if COPYRIGHT_DISCLAIMER not in description:
            description = (description + "\n\n" + COPYRIGHT_DISCLAIMER).strip()

        raw_tags = data.get("tags") or []
        if isinstance(raw_tags, str):
            tags = [t.strip().lstrip("#") for t in raw_tags.split(",") if t.strip()]
        elif isinstance(raw_tags, list):
            tags = [str(t).strip().lstrip("#") for t in raw_tags if str(t).strip()]
        else:
            tags = ["shorts", "viral", "facts"]

        raw_hashtags = data.get("hashtags") or []
        if isinstance(raw_hashtags, str):
            hashtags = [("#" + h.strip().lstrip("#")) for h in raw_hashtags.split() if h.strip()]
        elif isinstance(raw_hashtags, list):
            hashtags = [("#" + str(h).strip().lstrip("#")) for h in raw_hashtags if str(h).strip()]
        else:
            hashtags = ["#shorts", "#facts", "#3danimation"]

        return {
            "title": title,
            "description": description,
            "tags": tags,
            "hashtags": hashtags
        }

    def translate_and_rewrite_srt(
        self,
        srt_input: Union[str, Path, List[Dict[str, Any]]],
        target_language: str = DEFAULT_TARGET_LANGUAGE,
        batch_size: int = 35,
        temperature: float = 0.4,
        style: Optional[str] = None,
        tts_engine: Optional[str] = None
    ) -> Tuple[str, Dict[str, Any]]:
        original_blocks, _ = inject_constraints_into_srt(srt_input)
        total_blocks = len(original_blocks)

        active_style = (style or getattr(self, "style", "viral") or "viral").lower()
        if active_style in ("funny", "comedy", "roast"):
            prompt_template = FUNNY_SYSTEM_PROMPT
            logger.info(f"Translating & transcreating {total_blocks} blocks into '{target_language}' using FUNNY comedy style.")
        else:
            prompt_template = self.system_prompt_template
            logger.info(f"Translating & transcreating {total_blocks} blocks into '{target_language}' using standard viral style.")

        system_instruction = prompt_template.format(target_language=target_language)

        is_elevenlabs = bool(tts_engine and tts_engine.lower() in ("elevenlabs", "eleven_labs", "11labs"))
        if is_elevenlabs:
            logger.info("[Translator] ElevenLabs engine detected: Injecting expressive audio tag directives ([excited], [shocked], [laughs], [gasps]).")
            tag_instructions = (
                "\n\n### MANDATORY ELEVENLABS AUDIO TAGGING DIRECTIVE:\n"
                "The target voice engine is ElevenLabs v4. Naturally weave expressive inline audio performance tags in square brackets "
                "such as [excited], [shocked], [laughs], [gasps], [curious], [chuckles], [sighs], or [pause] where appropriate to match "
                "the comedy, drama, and human reactions in each scene.\n"
                "- STRICT LIMIT ON [whispers]: DO NOT overuse [whispers]! Constant whispering ruins speech audibility and kills video retention. "
                "Use [whispers] AT MOST ONCE in the entire video (only for an extreme, confidential secret reveal) or ZERO times! "
                "NEVER use [whispers] across multiple blocks. Prioritize high-energy cues: [excited], [shocked], [laughs], [gasps], [curious]!\n"
                "- Do NOT use HTML/XML tags. Use ONLY standard square brackets [tag]."
            )
            system_instruction += tag_instructions

        translated_blocks_accumulator: List[str] = []
        translated_objects_history: List[Dict[str, Any]] = []

        if total_blocks <= batch_size:
            logger.info(f"Short-form video ({total_blocks} <= {batch_size} blocks): Single-pass transcreation.")
            _, constrained_srt = inject_constraints_into_srt(original_blocks)
            prompt = (
                f"Transcreate the following {total_blocks} timestamped subtitle blocks strictly into {target_language}.\n"
                f"CRITICAL REQUIREMENTS:\n"
                f"1. NEVER start Block 1 with 'ओहो', 'वाह', 'Wow', 'अरे', or filler sounds! Dive straight into the story on frame 1.\n"
                f"2. MANDATORY INFINITE LOOP STITCH: Before outputting, stitch [Final Block] + [Block 1] together in your mind. "
                f"They MUST read continuously as ONE single, natural, complete, grammatically flawless sentence.\n"
                f"3. Strictly adhere to visual synchronization, word count limits, and valid SRT format:\n\n"
                f"{constrained_srt}"
            )
            raw_response = self._call_gemini_with_retry(prompt, system_instruction, temperature=temperature)
            translated_blocks_accumulator.append(raw_response)

        else:
            logger.info(f"Long-form video ({total_blocks} blocks): Batching into {batch_size}-block chunks with context continuity.")
            for start_idx in range(0, total_blocks, batch_size):
                chunk = original_blocks[start_idx : start_idx + batch_size]
                chunk_range_str = f"Blocks {chunk[0]['index']} to {chunk[-1]['index']}"
                logger.info(f"Translating chunk: {chunk_range_str} ({len(chunk)} blocks)...")

                _, chunk_constrained_srt = inject_constraints_into_srt(chunk)

                context_prompt = ""
                if translated_objects_history:
                    last_two = translated_objects_history[-2:]
                    context_lines = [
                        "[READ-ONLY CONTEXT FROM PREVIOUS SCENE FOR NARRATIVE & CHARACTER GENDER CONTINUITY - DO NOT RE-OUTPUT THESE]:"
                    ]
                    for prev_b in last_two:
                        context_lines.append(f"Block #{prev_b['index']}: {prev_b['text']}")
                    context_prompt = "\n".join(context_lines) + "\n\n"

                prompt = (
                    f"{context_prompt}"
                    f"[BLOCKS TO TRANSLATE & ADAPT NOW - STRICTLY OUTPUT ONLY THESE BLOCKS IN VALID SRT FORMAT]:\n"
                    f"{chunk_constrained_srt}"
                )

                chunk_raw_resp = self._call_gemini_with_retry(prompt, system_instruction, temperature=temperature)

                cleaned_chunk = re.sub(r"^```(?:srt)?\s*\n?", "", chunk_raw_resp.strip(), flags=re.IGNORECASE)
                cleaned_chunk = re.sub(r"\n?```\s*$", "", cleaned_chunk).strip()
                cleaned_chunk = re.sub(r"\[\s*Block\s*#?\d+.*?\]\s*", "", cleaned_chunk, flags=re.IGNORECASE)

                parsed_chunk_blocks = parse_srt(cleaned_chunk)
                if parsed_chunk_blocks:
                    translated_objects_history.extend(parsed_chunk_blocks)
                else:
                    for b_orig in chunk:
                        translated_objects_history.append({"index": b_orig["index"], "text": b_orig["text"]})

                translated_blocks_accumulator.append(chunk_raw_resp)

        combined_raw_translated = "\n\n".join(translated_blocks_accumulator)
        verified_srt, validation_report = clean_and_verify_srt(combined_raw_translated, original_blocks)
        if is_elevenlabs:
            verified_srt = enforce_whisper_limit(verified_srt, max_whispers=1)

        logger.info(
            f"Transcreation complete! {validation_report['total_blocks']} blocks processed. "
            f"Oversized warnings: {validation_report['oversized_count']}."
        )

        return verified_srt, validation_report

    def transliterate_srt_to_hinglish(
        self,
        hindi_srt: Union[str, Path],
        temperature: float = 0.2
    ) -> str:
        """
        Converts a Hindi Devanagari SRT file into clean, modern colloquial Hinglish (Latin alphabet)
        using Gemini LLM. All English words (e.g. lipstick, liquid, cactus, okhli, drops, powder,
        extract, natural, lemon, etc.) are written in standard English spelling, and Hindi words
        are written in natural colloquial Romanized Hindi. Timestamps and block IDs are preserved exactly.
        """
        if isinstance(hindi_srt, Path) or (isinstance(hindi_srt, str) and (os.path.exists(hindi_srt) or "\n" not in hindi_srt)):
            srt_content = Path(hindi_srt).read_text(encoding="utf-8")
        else:
            srt_content = str(hindi_srt)

        blocks = parse_srt(srt_content)
        if not blocks:
            return srt_content

        system_instruction = (
            "You are an expert bilingual subtitle adapter for Indian social media (YouTube Shorts, Instagram Reels).\n"
            "Your job is to convert a Hindi Devanagari SRT subtitle file into clean, modern colloquial Hinglish (Latin alphabet).\n\n"
            "### STRICT RULES:\n"
            "1. Keep the EXACT same SRT structure, block numbers, and timestamps unchanged.\n"
            "2. For all English loanwords (e.g., lipstick, liquid, cactus, powder, drops, natural, color, bright, process, extract, test, experiment, hack, trick, video, viral, etc.), write them in standard, correct English spelling. NEVER write phonetic bastardizations like 'lipastik', 'likvid', 'kaiktas', 'paaudar'.\n"
            "3. For Hindi words, use natural colloquial Romanized Hindi as used on Indian social media (e.g., 'Agar tum in keedon ko okhli mein daalkar pakaao, toh ekdam pure red color milega').\n"
            "4. Keep it punchy, conversational, and easy to read quickly.\n"
            "5. Return ONLY the raw valid SRT content. No markdown code fences, no explanations, no commentary."
        )

        prompt = (
            "Convert the following Hindi Devanagari SRT subtitles into natural colloquial Hinglish (Latin script). "
            "Ensure ALL English words are spelled in standard English, and Hindi words are in standard Romanized conversational Hindi:\n\n"
            f"{srt_content}"
        )

        raw_resp = self._call_gemini_with_retry(prompt, system_instruction, temperature=temperature)
        cleaned = re.sub(r"^```(?:srt)?\s*\n?", "", raw_resp.strip(), flags=re.IGNORECASE)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned).strip()

        parsed = parse_srt(cleaned)
        if len(parsed) == len(blocks):
            out_lines = []
            for orig, trans in zip(blocks, parsed):
                out_lines.append(f"{orig['index']}\n{orig['timestamp']}\n{trans['text']}\n")
            return "\n".join(out_lines).strip() + "\n"

        return cleaned + "\n"


def translate_and_rewrite_srt(
    srt_input: Union[str, Path, List[Dict[str, Any]]],
    target_language: str = DEFAULT_TARGET_LANGUAGE,
    api_key: Optional[str] = None,
    model: str = "gemini-3.8-flash",
    batch_size: int = 35,
    temperature: float = 0.4
) -> str:
    keys = [api_key] if api_key else None
    translator = SRTDubTranslator(api_keys=keys, model=model)
    verified_srt, _ = translator.translate_and_rewrite_srt(
        srt_input=srt_input,
        target_language=target_language,
        batch_size=batch_size,
        temperature=temperature
    )
    return verified_srt
