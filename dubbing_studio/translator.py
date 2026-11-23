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
from .anti_accent import (
    balance_consecutive_english,
    ANTI_ACCENT_SYSTEM_PROMPT_DIRECTIVE,
)
configure_runtime_environment()

logger = logging.getLogger("dubbing_studio.translator")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

DEFAULT_TARGET_LANGUAGE = "Hindi (Natural conversational Hindi written in native Devanagari script for high-fidelity TTS)"

# Master System Prompt for Conversational Hindi Devanagari Voiceover (Default Natural Ending)
SYSTEM_PROMPT = (
    "You are an elite viral YouTube Shorts & Reels Retention Showrunner and Dubbing Adapter for {target_language}.\n"
    "Your mission is to transcreate timestamped subtitle blocks into an addictive, natural, high-retention voiceover script written strictly in modern conversational HINDI using native DEVANAGARI script (देवनागरी लिपि). This is directly fed into neural TTS models (Sarvam AI & Google Gemini) for native human prosody.\n\n"
    "### 1. HIGH-RETENTION HOOK & NATURAL STORY PACING:\n"
    "- **BLOCK 1 (THE HOOK / PHENOMENON):** Open with an explosive, high-stakes visual hook describing ONLY what is shown on screen in THIS video's first block. NEVER copy prompt examples or sentences from other videos!\n"
    "  * **STRICT BAN ON STARTING FILLERS:** NEVER start Block 1 with 'ओहो', 'वाह', 'Wow', 'अरे', 'देखो', or cheap greeting sounds! Dive STRAIGHT into the action, mystery, or conflict on frame 1 without any introductory filler sound.\n"
    "- **FINAL BLOCK (NATURAL STORY CONCLUSION):**\n"
    "  * Deliver a punchy, satisfying, and natural conclusion to the story or process shown on screen.\n"
    "  * NEVER end abruptly with incomplete dangling clauses or connector words like '...और इसी वजह से—' unless explicitly requested.\n"
    "  * Conclude with a strong memorable takeaway, final reveal, or punchy callout that neatly wraps up the video.\n\n"
    "### 2. STRICT VISUAL-AUDIO SYNCHRONIZATION (ZERO LAG):\n"
    "- Every single block's dialogue MUST describe ONLY what is visually happening on screen during that exact timestamp window.\n"
    "- DO NOT lag behind or leak visual actions into subsequent blocks.\n"
    "- **EDUCATIONAL / HACK HOOKS:** Highlight fascinating physical/culinary facts shown on screen (e.g., 'जार को हमेशा ठंडे पानी में रखकर स्टीम करो ताकि ग्लास क्रैक न हो!') to drive saves and shares.\n\n"
    "### 3. SCRIPT, SPELLING & NATURAL VOCABULARY RULES:\n"
    "- **SPECIFIC TERMINOLOGY RULES (MANDATORY):**\n"
    "  * NEVER use 'wild boar' or 'जंगली सूअर'. ALWAYS use 'काला सूअर' (kala suar) in Hindi.\n"
    "  * NEVER use 'evaporate' or 'वाष्पीकरण'. ALWAYS use 'उबालना' or 'उबालकर' (ubalna / ubaalkar) in Hindi.\n"
    "  * NEVER use Arabic/Perso-Arabic letters (e.g. ي, د, ز). Write Hindi in pure native Devanagari script.\n"
    "  * ABSOLUTE BAN ON CHINESE / CJK CHARACTERS (零汉字): NEVER leak ANY Chinese characters (e.g. 独木桥, 榫卯, 滚木, 机关, 重生) into the Hindi voiceover script! Every Chinese term, concept, or object MUST be translated into natural conversational Hindi (देवनागरी) or standard English (Latin alphabet) terms!\n"
    "- **WRITE ENGLISH WORDS IN STANDARD ENGLISH SCRIPT (LATIN ALPHABET):**\n"
    "  * Whenever a concept, object, plant, tool, material, technique, or modern everyday word is in English (e.g., Honeysuckle, Gold grass, Purple tree, Bamboo, Stone, Arch, Bridge, Foundation, Structure, Pillar, Rebar, Crane, Scaffolding, Ice, Water, Liquid, Lipstick, Cactus, Powder, Drops, Process, Extract, Test, Experiment, Hack, Trick, Video, Viral, Frame, Layer, Lock, Pressure, Clips, Chemical, Filter, Secret, Treasure, Gold, Diamond, Temple, Canyon), WRITE IT IN STANDARD ENGLISH SCRIPT with correct spelling!\n"
    "  * NEVER phonetically write English words in Devanagari (e.g., do NOT write 'हनीसकल', 'गोल्ड ग्रास', 'फाउंडेशन', 'स्ट्रक्चर', 'लिपस्टिक', 'ब्रिज', 'स्टोन', 'क्रेन'). Instead, write: 'Honeysuckle', 'Gold grass', 'Foundation', 'Structure', 'Lipstick', 'Bridge', 'Stone', 'Crane'.\n"
    "- **WRITE HINDI WORDS & GRAMMAR IN NATIVE DEVANAGARI:**\n"
    "  * All Hindi conversational words, verbs, pronouns, and connectors MUST be written in native Devanagari script (देवनागरी लिपि).\n"
    "- **NO AWKWARD/FORCED HINDI TRANSLATIONS:**\n"
    "  * NEVER invent weird, textbook literal translations for English terms. Use standard English names directly!\n"
    "- **BAN PURE शुद्ध हिंदी (SHUDDH HINDI) CONNECTORS & DIFFICULT / BOOKISH WORDS:** NEVER write 'परंतु', 'अतः', 'क्योंकि वह व्यक्ति', or 'प्रतीत होता है'. NEVER use difficult, archaic, or textbook words like 'संकरा', 'संकरी', 'संकीर्ण' (sankara/sankari/sankirna), 'अद्वितीय', 'दुर्गम', 'चेष्टा', 'कदाचित', 'यद्यपि', 'प्रतीत', 'दृष्टिगोचर'—instead ALWAYS use natural, everyday conversational words like 'पतली', 'तंग', 'टाइट' (Tight), 'कम जगह', 'मुश्किल', 'दिख रहा है', or English 'Tight' / 'Narrow'!\n"
    "- **STRICT NO 'अरे यार' / 'यार':** DO NOT use 'अरे यार' or 'यार' anywhere! Use punchy, varied expressions like 'अरे!', 'ओहो!', 'ज़रा देखो!', 'रुको-रुको!', 'सोचो ज़रा!', or jump directly into the story!\n"
    "- **STRICT: NO REPETITIVE 'BHAI' (ZERO OR MAX 1 USE):** NEVER repeatedly use 'भाई', 'भाई साहब', or 'अरे भाई'. At most use it ONCE in the entire video, or zero times!\n"
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

ENGLISH_SYSTEM_PROMPT = (
    "You are an elite viral YouTube Shorts & Reels Retention Showrunner and Movie Storyteller for {target_language}.\n"
    "Your mission is to transcreate timestamped subtitle blocks into an addictive, hypnotic, high-retention voiceover script written strictly in punchy, natural spoken ENGLISH (zero Hindi, zero Devanagari, zero Chinese characters). This is directly fed into ElevenLabs / Gemini neural TTS.\n\n"
    "### 1. SPEED-TO-VALUE HOOK & STORY FLOW (ZERO TANGENTS):\n"
    "- **BLOCK 1 (IMMEDIATE ACTION + ANOMALY IN 2-3 SECONDS):** Jump STRAIGHT into concrete physical action and the central conflict/mystery in sentence 1 (e.g., 'The woman touched her head. The monster in Korea copied her.' or 'The moment she lay down, the door twisted shut.').\n"
    "  * **STRICT BAN ON INTRO FLUFF:** NEVER start with 'In this movie...', 'Today we see...', 'Wow', 'Oh', 'Hey', 'Look', or 'So'!\n"
    "- **CLEAR CAUSE-AND-EFFECT THROUGH-LINE ('THEREFORE / BUT'):** Every block must advance the main plot logically ('this happened... SO he did this... BUT suddenly that happened'). Cut irrelevant tangents or filler details that break immersion.\n"
    "- **RE-HOOK ESCALATIONS EVERY ~20 SECONDS:** Naturally weave sharp momentum shifts ('But the next second...', 'Suddenly...', 'Just then...', 'Little did he know...') whenever tension escalates so the viewer stays locked in.\n"
    "- **CRISP PAYOFF ENDING:** Deliver a decisive, satisfying resolution or twist payoff in the final block without rambling.\n\n"
    "### 2. ATOMIC MESSAGING & 6TH-GRADE COMPREHENSION:\n"
    "- **SHORT, PUNCHY SENTENCES (~8-12 WORDS AVG):** Write crisp, staccato, active-voice sentences ('He grabbed the key.' NOT 'The key was grabbed by him.'). Minimize working-memory load—no run-on clauses.\n"
    "- **SIMPLE EVERYDAY VOCABULARY (6TH-GRADE LEVEL):** Use vivid, plain everyday words instead of fancy, bookish, or stiff phrasing.\n"
    "- **STRICT VISUAL-AUDIO SYNC (ZERO LAG):** Each block MUST describe ONLY what is happening on screen during that exact timestamp window.\n"
    "- **ABSOLUTE BAN ON CJK / DEVANAGARI:** Every concept, name, or object MUST be written in standard English.\n\n"
    "### 3. TIME-FITTING & EVEN DENSITY (STRICT WORD BUDGETS):\n"
    "- Each input block begins with a constraint tag: `[Block #N | Window: X.Xs | Target: ~T words (Min: M1, Max: M2)]`.\n"
    "- Stay close to the target word budget so the voiceover flows at a crisp ~190 WPM storytelling pace without rushed syllables or dead silence.\n"
    "- Strip the constraint tags from the final output; output only clean SRT lines.\n\n"
    "### 4. STRICT SRT FORMAT INTEGRITY:\n"
    "- NEVER merge, split, reorder, or delete subtitle blocks.\n"
    "- Output the EXACT same number of blocks with the EXACT original timestamps.\n"
    "- Output raw, valid SRT text ONLY. No markdown code blocks, no explanations, no preamble.\n\n"
    "### 5. HUMAN VOCAL PACING & PUNCTUATION (FOR ULTRA-REALISTIC TTS):\n"
    "- Use triple dots `...` before shocking turns or reveals for a natural dramatic inhale.\n"
    "- Use commas `,`, exclamations `!`, and sharp questions `?` to keep vocal energy gripping from start to finish."
)

MOVIE_PILLAR_DIRECTIVE = (
    "\n\n### MOVIE MODE PILLAR SCRIPT BLUEPRINT (CALLAWAY + CINESCOPE TOP-100 VIRAL SYSTEM)\n"
    "You are writing a high-retention movie-recap script designed to hold viewers in a hypnotic story state from second 1 to the final frame.\n"
    "Strictly enforce all 4 Pillars and the Line-by-Line Audit below:\n\n"
    "#### PILLAR 1: SPEED TO VALUE (HOOK -> BODY 1 -> RE-HOOK -> BODY 2 -> OUTRO)\n"
    "- **BLOCK 1 — THE 2-SECOND ANOMALY HOOK:**\n"
    "  * Establish WHO + WHAT IS HAPPENING + THE WEIRD TWIST/THREAT in the very first 1-2 short sentences.\n"
    "  * Proven Hook Templates (adapt strictly to THIS video's frame 1 visuals):\n"
    "    1) Action + Mirror Anomaly: 'The woman touched her head. The monster in Korea copied her move.'\n"
    "    2) Instant Trap / Threat: 'The moment the girl lay down, the heavy door twisted shut.'\n"
    "    3) Strange High-Stakes Rule: 'There was one deadly rule on this island. Anyone over a pound...' \n"
    "    4) Clever/Extreme Action: 'He hid a live bomb inside a chewing gum wrapper.'\n"
    "  * BANNED OPENERS: Never start Block 1 with 'In this movie', 'Today we see', 'Wow', 'Oh', 'Hey', 'Look', or 'So'.\n"
    "- **BODY SECTIONS (CAUSE-AND-EFFECT ESCALATION):**\n"
    "  * Advance the plot in clean beats: Action -> Reaction -> Complication -> Escalation.\n"
    "- **RE-HOOKS EVERY ~20-25 SECONDS (CURIOSITY RESETS):**\n"
    "  * Whenever one mini-conflict resolves or tension dips, immediately open a NEW loop before the viewer can swipe away.\n"
    "  * Re-hook triggers: 'But the next second...', 'Little did he know...', 'Suddenly...', 'Just when she thought she was safe...', 'What came next was even worse...'.\n"
    "- **CRISP PAYOFF OUTRO (FINAL BLOCK):**\n"
    "  * Close the main loop with a sharp resolution, poetic karma, or twist payoff ('...ending the chaos.', '...and he finally escaped.', 'Sometimes brute force really works.'). Never ramble or trail off.\n\n"
    "#### PILLAR 2: STORY FLOW (SINGLE THROUGH-LINE — ZERO TANGENTS)\n"
    "- **THE 'BUT / SO / THEN' RULE:** Every block MUST connect logically to the previous block ('this happened... SO he did X... BUT suddenly Y blocked him... THEN he tried Z').\n"
    "- **NO 'BARRELS ON THE SIDEWALK':** Ruthlessly cut irrelevant backstory, minor side-character trivia, or filler descriptions that force the viewer's brain to hop storylines and break immersion.\n"
    "- **STRICT VISUAL-AUDIO SYNC (ZERO LAG):** Narrate ONLY what is visually happening in THAT block's exact `[start -> end]` window. Never lag one scene behind.\n\n"
    "#### PILLAR 3: ATOMIC MESSAGING (6TH-GRADE COMPREHENSION & STACCATO CLARITY)\n"
    "- **8 TO 12 WORDS PER SENTENCE (~10.5 AVG):** Write short, punchy, single-idea sentences. Never stack 3-4 clauses into run-on sentences.\n"
    "- **ACTIVE VOICE ONLY:** Say 'The soldier grabbed the stamp.' NOT 'The stamp was grabbed by the soldier.'\n"
    "- **6TH-GRADE VOCABULARY:** Use vivid, simple everyday words ('hid', 'ran', 'crushed', 'trapped', 'spotted', 'panicked') instead of stiff, bookish, or academic phrasing.\n"
    "- **INSTANT DISTILLATION & STICKY LABELS:** Refer to characters cleanly by clear visual roles ('the man', 'the guard', 'the sniper', 'the boy') and name key objects/rules simply so zero working memory is wasted.\n\n"
    "#### PILLAR 4: VIRAL NARRATION CADENCE (~195 WPM) & SELF-AUDIT\n"
    "- **PACING:** Target a crisp, urgent ~190-200 WPM storytelling rhythm while staying strictly inside each block's `[Target: ~T words]` budget.\n"
    "- **INTERNAL LINE-BY-LINE AUDIT (BEFORE OUTPUTTING):**\n"
    "  1) Does Block 1 hook with immediate action + conflict in 2-3 seconds?\n"
    "  2) Does every line advance the main plot via clear cause-and-effect without tangents?\n"
    "  3) Are sentences short, active-voice, and effortless to understand on first listen?\n"
    "  4) Are re-hooks placed roughly every 20-25 seconds to keep retention locked?\n\n"
    "#### PILLAR 5: ANTI-AI-SLOP CRAFT & TRUST THE VIEWER (CREATIVE-WRITING-SKILLS)\n"
    "- **SHOW BEHAVIOR, DON'T LABEL EMOTIONS OR INFO-DUMP:** Let physical actions carry fear, anger, or panic ('He bolted the door and backed away.' NOT 'A deep sense of dread washed over him.'). Never pause the scene to explain backstory.\n"
    "- **HOLD TENSION (NO PREMATURE RESOLUTION):** Do NOT add soft moralizing silver linings or resolve suspense early. Let danger and mystery stay unresolved until the payoff.\n"
    "- **ZERO LLM CLICHES & AI PUNCTUATION TELLS:**\n"
    "  * NEVER use em-dashes (`—`). Use crisp periods `.`, commas `,`, or `...` pauses.\n"
    "  * BANNED AI FILLER: Never write 'Moreover', 'Furthermore', 'Additionally', 'It's worth noting', 'Little did they realize the true horror', 'It's not X, it's Y', or preachy morals.\n"
    "  * ONE CLEAR MEANING PER LINE: Every 'he', 'she', 'it', or 'this' must point clearly to one concrete noun."
)

FUNNY_SYSTEM_PROMPT = (
    "### ROLE & PERSONA: THE ULTIMATE UNHINGED DESI ROASTMASTER ({target_language})\n"
    "You are India's funniest, sharpest Instagram Reels / YouTube Shorts roaster and voiceover showrunner.\n"
    "Your style is an electrifying fusion of:\n"
    "1. **CarryMinati & Tanmay Bhat Sarcasm**: Savage, observational roasting that points out the utter absurdity of what is happening on screen.\n"
    "2. **Baburao Apte (Hera Pheri) & Majnu Bhai (Welcome) Chaos**: Hilarious confusion, over-the-top panic, and dramatic Indian comedy.\n"
    "3. **Lord Puneet & Viral Indian Reel Brainrot**: Unfiltered shock, loud dramatic reactions ('इतना सन्नाटा क्यों है?!', 'मेरी आंखों में हार्पिक डाल दो!').\n"
    "4. **Iconic Bollywood & Panchayat Pop Culture**: Effortlessly dropping legendary dialogues, memes, and desi references that make the audience burst out laughing every 5 seconds!\n\n"

    "### 🏆 THE GOLDEN ARSENAL OF INDIAN MEMES & VIRAL DIALOGUES (WEAVE THESE IN NATURALLY):\n"
    "You MUST actively weave famous Indian meme references and iconic Bollywood punchlines into your lines:\n"
    "- **HERA PHERI / BABURAO / RAJU:**\n"
    "  * 'अरे देवा रे देवा! उठा ले रे बाबा!' (On catastrophic fails, disasters, or shock)\n"
    "  * 'ज़ोर-ज़ोर से बोलके सबको स्कीम बता दे!' (When a secret technique, hack, or trick is shown)\n"
    "  * '21 दिन में पैसा डबल!' (When showing crazy DIY production, wealth, or multiplying things)\n"
    "  * 'खोपड़ी तोड़ साले का!' (On annoying characters, villains, or frustrating mistakes)\n"
    "  * 'पैसा ही पैसा होगा!' (On expensive treasures, gold, or profitable crafts)\n"
    "- **PANCHAYAT & DESI WEB SERIES:**\n"
    "  * 'देख रहा है ना बिनोद? कैसे आँखों के सामने चूना लगाया जा रहा है!' (Pointing out sly tricks, hacks, or shortcuts)\n"
    "  * 'गजब बेइज्जती है यार!' (When someone fails miserably or gets embarrassed)\n"
    "  * 'जलवा है हमारा!' (When a craft looks super badass, grand, or untouchable)\n"
    "- **VIRAL INSTAGRAM REELS SOUNDBITES & TRENDS:**\n"
    "  * 'आयें?! बैंगन!' (Utter confusion when an absurd mechanism or weird object appears)\n"
    "  * 'लप्पू सा दिमाग है, झींगुर सी अकल... और चले हैं दुनिया हिलाने!' (Roasting a character's foolish attempt)\n"
    "  * 'भाई क्या कर रहा है तू?! ये सब दोगलापन है!' (Ashneer Grover style callout on hypocrisy or bad choices)\n"
    "  * 'चिन टपाक डम डम!' (Dropping random comic suspense or magical sudden reveals)\n"
    "  * 'सिस्टम हैंग कर दिया भाई ने!' (When something unexpectedly powerful or overpowered works)\n"
    "  * 'छोटी बच्ची हो क्या?!' (When an obvious mistake is made on screen)\n"
    "  * 'गद्दारी करबे?!' (When a mechanism, tool, or person backstabs or breaks down)\n"
    "  * 'ये सारे मिलके हमको पागल बना रहे हैं!' (Gormint aunty style on ridiculous setups)\n"
    "- **WELCOME & BOLLYWOOD GOLD:**\n"
    "  * 'सह लेंगे थोड़ा सा...' (When someone has to bear pain, heat, or struggle)\n"
    "  * 'कंट्रोल उदय, कंट्रोल!' (When the scene gets too intense or frantic)\n"
    "  * 'हम कोई मंदिर का घंटा हैं कि कोई भी आके बजा जाता है?!' (When characters get pushed around)\n"
    "  * 'तुमसे ना हो पाएगा!' (Gangs of Wasseypur dismissal of failed efforts)\n"
    "  * 'साला ये दुख काहे खत्म नहीं होता बे?!' (Masaan style when things keep getting worse)\n"
    "  * 'अरे कहना क्या चाहते हो?!' (3 Idiots reaction to overcomplicated junk)\n\n"

    "### 🎯 SAVAGE INDIAN RELATABLE ROASTING FORMULAS:\n"
    "Anchor visual observations to hyper-relatable Indian everyday chaos:\n"
    "1. **The PWD / Sasta Engineer Roast**: 'इसकी मजबूती देख के PWD के ठेकेदार भी शर्म से पानी-पानी हो जाएं!' / 'मीशो से मंगाया हुआ सस्ता इंजीनियर!'\n"
    "2. **The Rishtedaar / Sharma Ji Roast**: 'इतना कॉन्फिडेंस तो शादी में आए फूफा जी में भी नहीं होता!' / 'शर्मा जी के लड़के को भी पीछे छोड़ दिया!'\n"
    "3. **The Local Food / Bazaar Comparison**: 'इतनी जल्दी तो मोहल्ले के भंडारे में पूड़ी भी नहीं बंटती!' / 'सरोजिनी नगर वाली सेल जैसा हाल कर दिया!'\n"
    "4. **The Dramatic Puneet Meltdown**: 'मेरी दोनों आंखों में तुरंत हार्पिक डाल दो, ये क्या बवासीर देख लिया मैंने!'\n\n"

    "### 🚫 CRITICAL RESTRICTION RULES:\n"
    "- **STRICT NO 'BHAI' SPAM (ZERO OR MAX 1 USE IN ENTIRE VIDEO):** NEVER start consecutive sentences with 'भाई' or 'अरे भाई'. Refer to subjects dynamically: 'ये खिलाड़ी', 'लॉर्ड महाशय', 'ये नमूना', 'सस्ता टोनी स्टार्क', 'कारीगर बाबू'!\n"
    "- **COMPLETELY BANNED: 'अरे यार' / 'यार':** Never use 'अरे यार' or 'यार' anywhere! Use punchy exclamations: 'अरे देवा!', 'ओहो!', 'अबे सुनो!', 'मारो मुझे मारो!'\n"
    "- **BAN DIFFICULT BOOKISH HINDI WORDS:** Never use textbook words like 'संकरा', 'संकरी', 'संकीर्ण', 'अद्वितीय', 'दुर्गम', 'चेष्टा', 'कदाचित'. ALWAYS use casual everyday words: 'पतली', 'तंग', 'टाइट', 'कम जगह', 'मुश्किल', 'दिख रहा है'!\n"
    "- **ABSOLUTE BAN ON CHINESE / CJK CHARACTERS (零汉字):** NEVER leak ANY Chinese characters (e.g. 独木桥, 重生, 榫卯) into the script! Translate every concept into Hindi or standard English terms!\n"
    "- **NEVER BE BORING OR LITERAL:** DO NOT just narrate what happens (e.g., 'तूने लकड़ी लगाने की सोची'). ALWAYS inject a joke, sarcastic commentary, or meme punchline into every single scene!\n\n"

    "### 🎯 HIGH-RETENTION HOOK & NATURAL COMEDIC ENDING:\n"
    "- **BLOCK 1 (THE VIRAL HOOK):** Open with an explosive, funny, curiosity-spiking comedic question or roast (e.g., 'अगर इस Giant Tower को एक ज़ोरदार थप्पड़ मारो तो...').\n"
    "  * STRICT NO STARTING FILLERS: NEVER start Block 1 with 'ओहो', 'वाह', 'Wow', 'अरे', 'देखो'! Dive STRAIGHT into the action on frame 1!\n"
    "- **FINAL BLOCK (PUNCHY MEME CLIMAX):** Deliver the funniest, hardest-hitting final roast or meme punchline that delivers a satisfying climax to the video.\n"
    "  * Do NOT leave a dangling connector clause like '...और इसी वजह से—' unless explicitly looping.\n\n"

    "### 🔤 SCRIPT, SPELLING & NATURAL ENGLISH WORDS (LATIN ALPHABET):\n"
    "- All technical, modern, everyday, and loan words in English (e.g. Giant, Tower, Structure, Engineer, Design, Temple, Pagoda, Fire, Earthquake, Layer, Floor, Secret, Hack, Trick, Video, Brick, Wood, Balance, Level) MUST be written in STANDARD ENGLISH SCRIPT (Latin alphabet) with correct spelling!\n"
    "- NEVER phonetically write English words in Devanagari (e.g., do NOT write 'गिआनट', 'स्टरुकचर', 'टावर', 'डिज़ाइन', 'इंजीनियर'). Instead, write: 'Giant', 'Structure', 'Tower', 'Design', 'Engineer'.\n"
    "- All Hindi words, roasts, memes, and punchlines MUST be written in native Devanagari script (देवनागरी लिपि).\n\n"

    "### 🎙️ TTS PROSODY & VOCAL TIMING (Sarvam / ElevenLabs / Gemini):\n"
    "- Use hyphenated comedic panics (`अरे-अरे-अरे!`, `ओए-ओए-ओए!`, `रुको-रुको!`) to trigger dynamic speech inflections.\n"
    "- Use ellipses `...` right before funny reveals to force a micro-breath pause.\n"
    "- Strip all constraint tags from final output; return ONLY raw, valid SRT lines."
)

INFINITE_LOOP_DIRECTIVE = (
    "\n\n### 🔄 MANDATORY METHOD 1 INFINITE LOOP BRIDGE (ENABLED BY --loop):\n"
    "- **FINAL BLOCK (THE CAUSE / BRIDGE CLOSER):** Phrase the final block as the cause or setup that connects directly and seamlessly back into Block 1 as a single continuous sentence (e.g., '...और इसी वजह से—').\n"
    "- **MANDATORY IN-MIND LOOP CHECK:** Stitch `[Final Block] + [Block 1]` together in your mind: they MUST form ONE complete, grammatically flawless, natural-sounding sentence without broken fragments.\n"
)

CONDENSED_SHORT_DIRECTIVE = (
    "\n\n### CRITICAL 1-MINUTE SHORT CONDENSATION DIRECTIVE (MANDATORY):\n"
    "This video MUST be condensed into a punchy, viral YouTube Short / Reel fitting strictly under {max_duration:.1f}s!\n"
    "1. **EXTREME CONCISENESS**: You MUST aggressively condense each block into the fewest, punchiest Hindi words possible!\n"
    "   - Cut out ALL descriptive fluff, repetitive filler, and slow background details.\n"
    "   - Stick strictly to each block's target words budget: [Target: ~X words (Max: Y words)]!\n"
    "   - Never exceed the Max words per block so that the voiceover actor fits comfortably within the scene window!\n"
    "2. **PUNCHY VIRAL HOOK & METHOD 1 INFINITE LOOP CLOSER**:\n"
    "   - Block 1: Explosive viral hook without greetings or filler sounds.\n"
    "   - Final Block: Phrase the last block as the cause or setup that connects directly and seamlessly back into Block 1 as a single continuous sentence.\n"
    "3. **OUTPUT FORMAT**:\n"
    "   - Output valid SRT blocks ONLY with the exact original block indices and timestamps.\n"
    "   - Do NOT merge or skip blocks.\n"
    "   - No markdown formatting, no explanations, no code block markers."
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


def inject_constraints_into_srt(
    srt_input: Union[str, Path, List[Dict[str, Any]]],
    condense_target_duration: Optional[float] = None,
    loop: bool = False
) -> Tuple[List[Dict[str, Any]], str]:
    if isinstance(srt_input, list):
        blocks = [dict(b) for b in srt_input]
    else:
        blocks = parse_srt(srt_input)

    total_video_dur = blocks[-1]["end_sec"] if blocks else 0.0
    is_condensing = bool(condense_target_duration and total_video_dur > condense_target_duration)

    if is_condensing:
        # Budget speech to ~88-92% of target short duration (e.g. 50-53s for a 58s short)
        target_speech_total = max(25.0, min(condense_target_duration - 4.0, condense_target_duration * 0.90))
        scale = target_speech_total / max(1.0, total_video_dur)
    else:
        scale = 1.0

    srt_output_lines = []
    for i, b in enumerate(blocks):
        duration = max(0.5, round(b["end_sec"] - b["start_sec"], 1))
        if i + 1 < len(blocks):
            window = max(0.8, round(blocks[i + 1]["start_sec"] - b["start_sec"], 1))
        else:
            window = duration

        is_last = (i == len(blocks) - 1)
        is_penultimate = (i == len(blocks) - 2)

        if is_condensing:
            scaled_window = max(1.2, window * scale)
            target_words = max(3, round(scaled_window * 2.35))
            min_words = max(2, target_words - 2)
            max_words = max(min_words + 1, target_words + 2)
        elif is_last:
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

        if is_condensing:
            if is_last:
                tag = f"[Block #{b['index']} {'(FINAL LOOP CLOSER)' if loop else '(FINAL BLOCK)'} | Target: ~{target_words} words (Max: {max_words})]"
            elif is_penultimate:
                tag = f"[Block #{b['index']} (PENULTIMATE) | Target: ~{target_words} words (Max: {max_words})]"
            else:
                tag = f"[Block #{b['index']} | Target: ~{target_words} words (Max: {max_words})]"
        elif is_last:
            tag = f"[Block #{b['index']} {'(FINAL LOOP CLOSER)' if loop else '(FINAL BLOCK)'} | Window: {window}s | Target: ~{target_words} words (Max: {max_words})]"
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
    # Strip stray parenthetical tags like (FINAL LOOP CLOSER), (PENULTIMATE), (LOOP CLOSER), etc.
    cleaned = re.sub(
        r"\(\s*(?:FINAL LOOP CLOSER|PENULTIMATE|LOOP CLOSER|FINAL BLOCK|HOOK)\s*\)\s*",
        "",
        cleaned,
        flags=re.IGNORECASE
    )
    # Sanitize any stray Arabic/Perso-Arabic unicode characters
    cleaned = re.sub(r'[\u0600-\u06FF]', '', cleaned)

    # Sanitize and translate any stray Chinese/CJK characters leaked by LLM
    cjk_replacements = {
        "独木桥": "Log Bridge",
        "榫卯": "Mortise tenon",
        "滚木": "Wood Rollers",
        "机关": "Mechanism",
        "桥梁": "Bridge",
        "大雁塔": "Giant Wild Goose Pagoda",
        "重生": "Rebuild",
        "古法": "Ancient",
        "火炕": "Kang",
        "机关盒": "Puzzle Box",
        "伸臂桥": "Cantilever Bridge",
        "叠梁式": "Woven Timber",
        "马车": "Horse Carriage",
        "井盐": "Well Salt",
        "堆肥": "Compost",
        "洗发水": "Shampoo",
        "肥皂": "Soap",
        "地火炉": "Stove",
        "弓鱼术": "Bow Fish",
        "悬空寺": "Hanging Temple",
        "暗锁": "Secret Lock",
        "白砂糖": "White Sugar",
        "精制盐": "Refined Salt",
        "地坑院": "Pit Yard",
        "高转筒车": "Water Wheel",
        "鲁班锁": "Luban Lock",
    }
    for cjk_term, repl in cjk_replacements.items():
        if cjk_term in cleaned:
            cleaned = cleaned.replace(cjk_term, repl)

    if re.search(r'[\u4E00-\u9FFF\u3400-\u4DBF]', cleaned):
        logger.warning("Stray Chinese/CJK characters detected in translated SRT! Sanitizing...")
        cleaned = re.sub(r'[\u4E00-\u9FFF\u3400-\u4DBF]+', '', cleaned)

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
        self.model = model or "gemini-3.8-flash"
        self.system_prompt_template = system_prompt_template
        descending_models = [
            "gemini-3.8-flash",
            "gemini-3.7-flash",
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-3-flash-preview",
            "gemini-3.5-flash-lite",
            "gemini-flash-latest",
        ]
        self.fallback_models = [self.model] + [m for m in descending_models if m != self.model]

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
        timeout_ms: int = 35000
    ) -> str:
        models_to_try = [self.model] + [m for m in self.fallback_models if m != self.model]
        model_idx = 0
        max_attempts = max(len(self.api_keys) * 2, 8)
        # Fast fail per attempt so descending model cascade steps down immediately on 503/504
        call_timeout = 45000 if len(prompt) > 1800 else timeout_ms

        # Parallel race in waves with early return as soon as highest surviving model succeeds:
        # Prioritize self.model first, followed by proven reliable 3.5-flash, 3.5-flash-lite, 3.6-flash
        primary_model = self.model or "gemini-3.5-flash"
        wave1 = [primary_model]
        for m in ["gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.8-flash"]:
            if m not in wave1:
                wave1.append(m)
        wave1 = wave1[:4]

        race_waves = [
            wave1,
            ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.6-flash"],
        ]
        if len(self.api_keys) >= 3:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            cfg_kwargs = {
                "system_instruction": system_instruction,
                "temperature": temperature,
                "max_output_tokens": 8192,
            }
            if response_mime_type:
                cfg_kwargs["response_mime_type"] = response_mime_type
            race_config = types.GenerateContentConfig(**cfg_kwargs)

            def _call_one(model_name: str, key: str) -> Tuple[str, Optional[str]]:
                try:
                    c = genai.Client(
                        api_key=key,
                        http_options=types.HttpOptions(
                            timeout=call_timeout,
                            retry_options=types.HttpRetryOptions(attempts=1),
                        ),
                    )
                    resp = c.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=race_config,
                    )
                    if resp and resp.text:
                        return model_name, resp.text.strip()
                except Exception as e:
                    err_str = str(e)
                    logger.warning(f"Parallel race [{model_name}] Key ({mask_key(key)}) error: {err_str[:120]}")
                    if is_gemini_dead_error(err_str):
                        self.rotate_key(dead_key=key, reason=err_str[:80])
                return model_name, None

            raced_all: List[str] = []
            for wave_idx, wave_models in enumerate(race_waves, start=1):
                active_snapshot = list(self.api_keys)
                if len(active_snapshot) < min(3, len(wave_models)):
                    break
                # Cap wave to number of available active keys if fewer than models
                models_in_wave = wave_models[:len(active_snapshot)]
                start_i = self.current_key_idx % len(active_snapshot)
                race_keys = [active_snapshot[(start_i + i) % len(active_snapshot)] for i in range(len(models_in_wave))]
                self.current_key_idx = (start_i + len(models_in_wave)) % len(active_snapshot)

                logger.info(f"Parallel wave {wave_idx}: racing {models_in_wave} across {len(race_keys)} distinct API keys...")
                pool = ThreadPoolExecutor(max_workers=len(models_in_wave))
                try:
                    future_to_model = {
                        pool.submit(_call_one, m, k): m for m, k in zip(models_in_wave, race_keys)
                    }
                    finished: Dict[str, Optional[str]] = {}
                    # Early exit as soon as the highest priority model in this wave succeeds,
                    # or if any model succeeds and all higher-priority ones have already errored!
                    for fut in as_completed(future_to_model):
                        m_name, m_text = fut.result()
                        finished[m_name] = m_text
                        for p in models_in_wave:
                            if p not in finished:
                                break  # Still waiting on a higher-priority model
                            if finished[p]:  # Highest surviving model succeeded!
                                logger.info(f"Parallel wave {wave_idx} early return [{p}] (priority {' > '.join(models_in_wave)}).")
                                return finished[p]

                    # Fallback within wave: if any model succeeded, return the highest-priority successful result
                    for p in models_in_wave:
                        if finished.get(p):
                            logger.info(f"Parallel wave {wave_idx} completed with [{p}] (priority {' > '.join(models_in_wave)}).")
                            return finished[p]
                finally:
                    pool.shutdown(wait=False, cancel_futures=True)

                raced_all.extend(models_in_wave)

            # None of Wave 1 or Wave 2 succeeded -> continue normal loop from remaining models
            remaining = [m for m in models_to_try if m not in raced_all]
            if remaining:
                models_to_try = remaining

        for attempt in range(max_attempts):
            if not self.api_keys and not get_active_gemini_keys():
                raise RuntimeError("All Gemini API keys in the runtime pool were exhausted.")

            api_key = self.get_current_key()
            current_model = models_to_try[model_idx % len(models_to_try)]

            try:
                client = genai.Client(
                    api_key=api_key,
                    http_options=types.HttpOptions(
                        timeout=call_timeout,
                        retry_options=types.HttpRetryOptions(attempts=1),
                    ),
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
        temperature: float = 0.5,
        channel_name: str = "",
        metadata_style: Optional[str] = None,
        movie: bool = False
    ) -> Dict[str, Any]:
        """
        Generate viral social media metadata:
        - Catchy Title (Curiosity-driven English question/statement with emojis)
        - Video Description (Movie recap format, 3D Eye Engineering format, or Viral keyword block)
        - Tags (Broad, high-volume SEO search tags)
        - Hashtags (trending #hashtags)
        """
        logger.info(f"Generating metadata for: {original_title or 'video'} (Channel: '{channel_name or 'default'}', Movie={movie})")

        COPYRIGHT_DISCLAIMER = (
            "Disclaimer- Some contents are used for educational purpose under fair use. "
            "Copyright Disclaimer Under Section 107 of the Copyright Act 1976, allowance is made for \"fair use\" "
            "for purposes such as criticism, comment, news reporting, teaching, scholarship, and research. "
            "Fair use is a use permitted by copyright statute that might otherwise be infringing. "
            "Non-profit, educational or personal use tips the balance in favour of fair use.\nThank You"
        )

        is_movie_style = bool(
            movie
            or (metadata_style and metadata_style.lower() in ("movie", "film", "cinema", "movierecap"))
            or any(w in (channel_name or "").lower() for w in ("movie", "cinema", "cinefile", "curious cinefile", "film"))
        )

        is_engineering_style = not is_movie_style and (
            (metadata_style and metadata_style.lower() in ("engineering", "jugaad", "architecture", "construction", "3deye"))
            or any(w in (channel_name or "").lower() for w in ("jugaad", "chinese", "architecture", "engineering", "ancient", "bridge", "pillar", "fence"))
        )

        if is_movie_style:
            system_instruction = (
                "You are an elite YouTube Shorts title and SEO metadata strategist for viral movie recaps, cinema stories, and thriller film breakdown channels.\n"
                "Your task is to analyze the movie recap video's topic and spoken script to generate high-CTR metadata strictly following these rules:\n\n"
                "### 1. TITLE FORMAT RULES:\n"
                "- Must be an ultra-curious, punchy question or statement in English about the movie's plot hook or twist.\n"
                "- Must include 1 engaging emoji.\n"
                "- CRITICAL RULE: DO NOT write '(3D Animation In English)', '(3D Animation In Hindi)', or '(3D Animation)'. Never include '3D animation' in movie titles!\n"
                "- Must include #shorts at the end.\n"
                "- Example: 'When A Psycho Female Assassin Kidnaps You 😱 #shorts'\n\n"
                "### 2. DESCRIPTION FORMAT RULES:\n"
                "- The description MUST start with the exact viewer engagement line:\n"
                '  Comment "MOVIE" for the movie name! 🍿🎬\n\n'
                "- Followed by a dense block of 25 to 35 high-traffic, comma-separated MOVIE-related search keywords and phrases (e.g. movie recap, movie explanation, movie explained, thriller movie recap, mystery movie recap, action movie breakdown, movie summary, movies recap, full movie recap, thriller movies, best movie recaps, movie breakdown, ending explained, cinema recap, suspense movie recap, film recap, hollywood movie recap, movie review, story recapped, crime thriller movie, plot summary, box office movies, movie clips, top thriller movies, film explanation).\n"
                "- Immediately after the keyword block, insert 2 newlines and append the MANDATORY Copyright Disclaimer verbatim:\n"
                f"{COPYRIGHT_DISCLAIMER}\n\n"
                "### 3. TAGS FORMAT RULES:\n"
                "- Strictly output 4 to 5 broad, high-volume movie search tags:\n"
                "  [\"movie\", \"movie explanation\", \"movie recap\", \"movies\", \"ending explained\"]\n"
                "- DO NOT use over-niche tags that kill discovery and decrease search volume.\n\n"
                "### 4. MOVIE IDENTITY RULES:\n"
                "- Identify the exact movie/show being recapped from the title context and script.\n"
                "- If you are not confident, leave movie_name empty instead of guessing.\n"
                "- movie_year must be a 4-digit integer or null.\n"
                "- movie_synopsis must be 2-3 factual sentences about the movie's actual premise.\n\n"
                "You MUST produce strictly valid JSON with the following schema:\n"
                "{\n"
                '  "title": "Engaging Movie Title 😱 #shorts",\n'
                '  "description": "Comment \\"MOVIE\\" for the movie name! 🍿🎬\\n\\nmovie recap, movie explanation, movie explained, ...\\n\\nDisclaimer- Some contents are...",\n'
                '  "tags": ["movie", "movie explanation", "movie recap", "movies", "ending explained"],\n'
                '  "hashtags": ["#shorts", "#movierecap", "#movieexplained"],\n'
                '  "movie_name": "Exact Movie Title",\n'
                '  "movie_year": 2024,\n'
                '  "movie_genre": "action thriller",\n'
                '  "movie_synopsis": "Factual 2-3 sentence synopsis."\n'
                "}"
            )
            prompt = (
                f"Original Title / Topic Context: {original_title}\n"
                f"Category: Movie Recap / Cinema Breakdown\n\n"
                f"Full Spoken Voiceover Script:\n"
                f'\"\"\"\n'
                f"{script_text}\n"
                f'\"\"\"\n\n'
                f"Generate the high-CTR movie title (without '3D Animation'), 'Comment MOVIE' description with movie keywords & disclaimer, "
                f"4-5 broad movie tags, and the movie identity fields (movie_name, movie_year, movie_genre, movie_synopsis) strictly in valid JSON format."
            )
        elif is_engineering_style:
            system_instruction = (
                "You are an elite YouTube Shorts & Video title and description strategist for a top viral 3D animation, "
                "engineering, ancient architecture, and construction breakdown channel called '3D Eye YouTube Channel'.\n"
                "Your task is to analyze the video's topic and spoken script to generate high-CTR metadata strictly following this proven format:\n\n"
                "### 1. TITLE FORMAT RULES:\n"
                "- Must be an ultra-curious, punchy question or statement in English about how the structure/mechanism was built or how it works.\n"
                "- Must include 1-2 engaging, relevant emojis (e.g. 🏰, 🌉, 🌈🪵, 🤔, 🌊, 🪵, 🔨, 🏛️).\n"
                "- Use one of these proven high-CTR formats:\n"
                "  * 'How [Structure/Mechanism] Was Built [Emoji] | 3D Animation'\n"
                "  * 'How Famous [Structure] Base Was Built [Emoji] ( 3D Animation In Hindi ) #short'\n"
                "  * 'Why [Engineering Phenomenon Happens] [Emoji] | 3D Animation'\n"
                "  * 'How a [Object] Becomes a [Structure] [Emoji] #animation #explanation #engineering #architecture #howitworks'\n"
                "- Target Title Examples:\n"
                "  * 'How a Fence Becomes a Castle 🏰 #animation #explanation #engineering #architecture #howitworks'\n"
                "  * 'How Famous Taj Mahal of India Base Was Built 🤔 ( 3D Animation In Hindi ) #short'\n"
                "  * 'How Bridge Pillars Are Built Underwater | 3D Animation'\n"
                "  * 'How Was the Rainbow Bridge Built? 🌈🪵 3D Animation'\n"
                "  * 'Why bridges don’t fall even when they bend | 3D Animation'\n\n"
                "### 2. DESCRIPTION FORMAT RULES:\n"
                "The description MUST strictly follow this exact structured layout:\n\n"
                "[Hook / Title with Emoji]\n\n"
                "3D Eye YouTube Channel Explained in Hindi\n\n"
                "[2-3 engaging, informative paragraphs breaking down the engineering process, ancient ingenuity, physics, "
                "materials (e.g., cofferdams, sheet piles, mortise and tenon, bearings, stone arches), and mechanics step by step in clear, captivating English/Hinglish]\n\n"
                "📌 Topics Covered:\n"
                "• [Topic 1]\n"
                "• [Topic 2]\n"
                "• [Topic 3]\n"
                "• [Topic 4]\n"
                "• [Topic 5]\n"
                "• [Topic 6]\n\n"
                "👍 Like, Share & Subscribe for more simple engineering videos!\n\n"
                "[10-15 highly relevant SEO hashtags, e.g. #BridgeEngineering #CivilEngineering #EngineeringExplained #HowBridgesWork #StructuralEngineering #ConstructionFacts #3DAnimation #EngineeringBasics #ScienceExplained #IndianYouTuber #LearnEngineering]\n\n"
                f"{COPYRIGHT_DISCLAIMER}\n\n"
                "### 3. TAGS FORMAT RULES:\n"
                "- Strictly output exactly 3 clean, broad, high-volume YouTube tags:\n"
                "  1. 'Animation'\n"
                "  2. '3D Explained'\n"
                "  3. The clean primary subject in 1 to 2 words (e.g. 'Rainbow Bridge', 'Bridge Pillars', 'Ancient Castle')\n\n"
                "You MUST produce strictly valid JSON with the following schema:\n"
                "{\n"
                '  "title": "Title with emoji | 3D Animation",\n'
                '  "description": "Full formatted description with topics, hashtags, and disclaimer",\n'
                '  "tags": ["Animation", "3D Explained", "Primary Subject"],\n'
                '  "hashtags": ["#BridgeEngineering", "#CivilEngineering", "#3DAnimation", ...]\n'
                "}"
            )
            prompt = (
                f"Original Title / Topic Context: {original_title}\n"
                f"Channel / Domain: 3D Eye YouTube Channel (Engineering & Architecture)\n\n"
                f"Full Spoken Voiceover Script:\n"
                f'\"\"\"\n'
                f"{script_text}\n"
                f'\"\"\"\n\n'
                f"Generate the engineering explainer title, structured description with '3D Eye YouTube Channel Explained in Hindi', "
                f"topics covered, hashtags, and 3 clean tags strictly in valid JSON format."
            )
        else:
            is_english_meta = str(target_language or "").strip().lower().startswith("en")
            lang_label = "3D Animation In English" if is_english_meta else "3D Animation In Hindi"
            system_instruction = (
                "You are an elite YouTube Shorts title and SEO metadata strategist for viral 3D animation & science/mystery breakdown channels.\n"
                "Your task is to analyze the video's topic and spoken script to generate high-CTR metadata strictly following this proven YouTube Shorts format:\n\n"
                "### 1. TITLE FORMAT RULES:\n"
                "- Must be an ultra-curious, punchy question or statement in English.\n"
                "- Must include 1 engaging emoji.\n"
                f"- Must include parenthetical category: '({lang_label})' or '(3D Animation)'.\n"
                "- Must include 1-3 lowercase/camelcase hashtags at the end, starting with #shorts and topic tags (e.g. #shorts #facts #science or #3danimationfact).\n"
                "- Examples of EXACT required title formats:\n"
                f"  * 'How To Survive In A Subway Tunnel 😵💫 ( {lang_label} ) #shorts'\n"
                f"  * 'How G Shock Was Invented 😱 ({lang_label}) #shorts'\n"
                f"  * 'This Sliding Stopper Can Stop a Moving Train! 😱 ({lang_label}) #shorts'\n"
                "  * 'Slicing A Bullet In Half? (3D Animation) #3danimationfact #facts #science'\n\n"
                "### 2. DESCRIPTION FORMAT RULES:\n"
                "- The description MUST start with a dense block of 20 to 35 highly relevant, comma-separated organic search keywords, phrases, and long-tail query variations directly related to the title and core subject (NO generic fluff, NO sentences).\n"
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
                f'  "title": "Title with emoji ({lang_label}) #shorts",\n'
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

        title = str(data.get("title") or "").strip()
        # If title is empty or contains Chinese characters, guarantee it is translated to English
        if not title or re.search(r'[\u4E00-\u9FFF]', title):
            try:
                en_prompt = (
                    f"Translate and adapt this Chinese video topic into an exciting, high-CTR English YouTube title with emojis in '3D Eye / 3D Animation' style "
                    f"(e.g. 'How Was X Built? 3D Animation' or 'How X Works 3D Animation'). Output ONLY the final title in English:\n"
                    f"Topic: {original_title}\n"
                    f"Script snippet: {script_text[:300]}"
                )
                en_resp = self._call_gemini_with_retry(en_prompt, "You are a YouTube Title expert. Output ONLY the English title, nothing else.", temperature=0.3)
                clean_en = re.sub(r'[\r\n"]+', '', en_resp).strip()
                if clean_en and not re.search(r'[\u4E00-\u9FFF]', clean_en):
                    title = clean_en
            except Exception as e:
                logger.warning(f"Fallback title translation error: {e}")
        if not title:
            fallback_lang_tag = "3D Animation In English" if str(target_language or "").strip().lower().startswith("en") else "3D Animation In Hindi"
            title = f"{original_title} ({fallback_lang_tag}) #shorts"
        description = str(data.get("description") or "").strip()
        if COPYRIGHT_DISCLAIMER not in description:
            description = (description + "\n\n" + COPYRIGHT_DISCLAIMER).strip()

        if len(description) >= 5000:
            if COPYRIGHT_DISCLAIMER in description:
                kw_part = description.replace(COPYRIGHT_DISCLAIMER, "").rstrip()
                avail = max(100, 4950 - len(COPYRIGHT_DISCLAIMER) - 4)
                kw_part = kw_part[:avail].rsplit(",", 1)[0].rstrip()
                description = f"{kw_part}\n\n{COPYRIGHT_DISCLAIMER}".strip()
            else:
                description = description[:4950].rsplit(",", 1)[0].rstrip()

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
            "hashtags": hashtags,
            "movie_name": str(data.get("movie_name") or "").strip() if is_movie_style else "",
            "movie_year": data.get("movie_year") if is_movie_style else None,
            "movie_genre": str(data.get("movie_genre") or "").strip() if is_movie_style else "",
            "movie_synopsis": str(data.get("movie_synopsis") or "").strip() if is_movie_style else "",
        }

    _movie_ctx_cache: Dict[str, str] = {}

    def _lookup_wikipedia_movie_context(self, title_query: str) -> str:
        """Free, zero-Gemini movie summary lookup via English & Chinese Wikipedia REST API."""
        q = (title_query or "").strip()
        if not q or q.lower() in {"unknown", "none", "untitled"}:
            return ""
        try:
            import requests
            import urllib.parse
            headers = {"User-Agent": "DouyinDubbingStudio/1.0 (https://localhost)"}
            has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in q)
            en_title = ""
            if has_cjk:
                s = requests.get(
                    "https://zh.wikipedia.org/w/api.php",
                    params={"action": "query", "list": "search", "srsearch": q, "format": "json", "srlimit": 2},
                    headers=headers,
                    timeout=6,
                ).json()
                hits = s.get("query", {}).get("search", [])
                if hits:
                    zh_title = hits[0]["title"]
                    p = requests.get(
                        "https://zh.wikipedia.org/w/api.php",
                        params={"action": "query", "titles": zh_title, "prop": "langlinks", "lllang": "en", "format": "json"},
                        headers=headers,
                        timeout=6,
                    ).json()
                    pages = list(p.get("query", {}).get("pages", {}).values())
                    if pages and pages[0].get("langlinks"):
                        en_title = pages[0]["langlinks"][0].get("*", "")
            else:
                s = requests.get(
                    "https://en.wikipedia.org/w/api.php",
                    params={"action": "query", "list": "search", "srsearch": f"{q} film", "format": "json", "srlimit": 3},
                    headers=headers,
                    timeout=6,
                ).json()
                hits = s.get("query", {}).get("search", [])
                if hits:
                    en_title = hits[0]["title"]

            if not en_title:
                return ""
            summary_url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(en_title.replace(" ", "_"))
            r = requests.get(summary_url, headers=headers, timeout=6).json()
            desc = (r.get("description") or "").lower()
            extract = (r.get("extract") or "").strip()
            if not extract or not any(k in desc + " " + extract.lower()[:120] for k in ("film", "movie", "series", "drama", "anime", "animation", "thriller", "horror", "comedy", "sci-fi")):
                return ""

            ctx_parts = [f"{r.get('title', en_title)} ({r.get('description', 'film')}): {extract}"]
            # Also pull the full Plot/Premise/Synopsis section so Gemini gets character names, rules & twists
            try:
                secs_resp = requests.get(
                    "https://en.wikipedia.org/w/api.php",
                    params={"action": "parse", "page": en_title, "prop": "sections", "format": "json"},
                    headers=headers,
                    timeout=6,
                ).json()
                secs = secs_resp.get("parse", {}).get("sections", [])
                plot_idx = next(
                    (s["index"] for s in secs if s.get("line", "").strip().lower() in {"plot", "premise", "synopsis", "story", "plot summary"}),
                    None,
                )
                if plot_idx is not None:
                    html_resp = requests.get(
                        "https://en.wikipedia.org/w/api.php",
                        params={"action": "parse", "page": en_title, "section": plot_idx, "prop": "text", "format": "json"},
                        headers=headers,
                        timeout=6,
                    ).json()
                    html_str = html_resp.get("parse", {}).get("text", {}).get("*", "")
                    if html_str:
                        plot_txt = re.sub(r"\[\d+\]", "", re.sub(r"<[^>]+>", " ", html_str))
                        plot_txt = re.sub(r"^(?:Plot|Premise|Synopsis|Story|Plot summary)\s*\[\s*edit[^\]]*\]\s*", "", plot_txt, flags=re.I)
                        plot_txt = re.sub(r"\s+", " ", plot_txt).strip()
                        if plot_txt:
                            ctx_parts.append(f"Plot: {plot_txt}")
            except Exception:
                pass
            return "\n".join(ctx_parts)[:2500]
        except Exception:
            pass
        return ""

    def lookup_movie_context(
        self,
        blocks: List[Dict[str, Any]],
        video_title: Optional[str] = None,
    ) -> str:
        """
        Identifies the movie/show via free Wikipedia REST API first (0 Gemini quota),
        falling back to Gemini only when Wikipedia has no match.
        """
        if not blocks:
            return ""
        cache_key = (video_title or "").strip().lower()
        if cache_key and cache_key in self._movie_ctx_cache:
            return self._movie_ctx_cache[cache_key]

        wiki_ctx = self._lookup_wikipedia_movie_context(video_title or "")
        if wiki_ctx:
            logger.info(f"Movie context (Wikipedia): {wiki_ctx[:100]}...")
            if cache_key:
                self._movie_ctx_cache[cache_key] = wiki_ctx
            return wiki_ctx

        sample_lines = "\n".join(
            f"- {b.get('text', '').strip()}" for b in blocks[:25] if b.get("text", "").strip()
        )
        if not sample_lines:
            return ""

        query_prompt = (
            "You are a movie-identification assistant.\n"
            f"Video slug/title: {video_title or 'Unknown'}\n"
            f"Transcript excerpt:\n{sample_lines}\n\n"
            "Using your film knowledge, identify what movie, TV series, or short film this recap is about (if identifiable).\n"
            "Return ONLY a concise 3-4 sentence plain-text note covering:\n"
            "1) Movie/Show title & genre (or 'Unknown' if not certain)\n"
            "2) Core premise, key rule/threat, and character roles/names.\n"
            "Keep it factual and under 90 words."
        )
        for idx in range(min(3, len(self.api_keys))):
            k = self.get_current_key()
            client = genai.Client(api_key=k, http_options={"timeout": 20000})
            try:
                resp = client.models.generate_content(
                    model="gemini-3.5-flash",
                    contents=query_prompt,
                    config=types.GenerateContentConfig(temperature=0.1),
                )
                txt = (resp.text or "").strip()
                if txt and "unknown" not in txt.lower()[:30]:
                    res = txt[:600]
                    if cache_key:
                        self._movie_ctx_cache[cache_key] = res
                    return res
                return ""
            except Exception as e:
                if is_gemini_dead_error(str(e)):
                    mark_gemini_key_dead(k, reason=str(e)[:120])
                else:
                    logger.warning(f"Movie context lookup attempt {idx + 1} failed: {str(e)[:120]}")
                self.rotate_key()
                time.sleep(0.5)
        return ""

    def lookup_movie_details(
        self,
        video_title: Optional[str] = None,
        blocks: Optional[List[Dict[str, Any]]] = None,
        allow_gemini: bool = False,
    ) -> Dict[str, Any]:
        """
        Return structured movie identity (name/year/genre/synopsis/source URL).
        Uses free Wikipedia context first; Gemini identification is opt-in.
        """
        query = (video_title or "").strip()
        cache_key = query.lower()
        context = self._movie_ctx_cache.get(cache_key, "") if cache_key else ""

        # Numeric IDs / empty strings never identify a movie; skip network calls.
        letters_only = re.sub(r"[^A-Za-z\u4e00-\u9fff]", "", query)
        if len(letters_only) < 3:
            return {}

        if not context and query:
            context = self._lookup_wikipedia_movie_context(query)
            if context and cache_key:
                self._movie_ctx_cache[cache_key] = context

        if not context and allow_gemini and blocks:
            context = self.lookup_movie_context(blocks, video_title=query)

        if not context:
            return {}

        first_line = context.split("\n", 1)[0].strip()
        match = re.match(
            r"^(?P<name>.+?)\s*\((?P<meta>[^)]*)\)\s*:\s*(?P<summary>.*)$",
            first_line,
        )
        if match:
            movie_name = match.group("name").strip()
            meta = match.group("meta").strip()
            synopsis = match.group("summary").strip()
        else:
            movie_name = first_line.split(":", 1)[0].strip()
            meta = ""
            synopsis = first_line

        if not movie_name:
            return {}

        year_match = re.search(r"\b(19\d{2}|20\d{2})\b", f"{movie_name} {meta}")
        year = int(year_match.group(1)) if year_match else None
        genre = re.sub(r"\b(19\d{2}|20\d{2})\b", "", meta).strip(" ,-")

        plot_match = re.search(r"\nPlot:\s*(.+)", context, flags=re.DOTALL)
        full_synopsis = ((synopsis + " " + (plot_match.group(1) if plot_match else "")).strip())[:1200]
        full_synopsis = re.sub(r"\[\s*edit\s*\|\s*edit source\s*\]", "", full_synopsis)
        full_synopsis = re.sub(r"\[\d+\]", "", full_synopsis)
        full_synopsis = re.sub(r"\s+", " ", full_synopsis).strip()

        try:
            import urllib.parse
            source_url = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(movie_name.replace(" ", "_"))
        except Exception:
            source_url = ""

        return {
            "movie_name": movie_name,
            "movie_year": year,
            "movie_genre": genre,
            "movie_synopsis": full_synopsis,
            "movie_context": context[:2500],
            "movie_source": "wikipedia",
            "movie_source_url": source_url,
        }

    def translate_and_rewrite_srt(
        self,
        srt_input: Union[str, Path, List[Dict[str, Any]]],
        target_language: str = DEFAULT_TARGET_LANGUAGE,
        batch_size: int = 120,
        temperature: float = 0.35,
        style: Optional[str] = None,
        tts_engine: Optional[str] = None,
        fit_short: bool = False,
        max_duration: float = 58.0,
        anti_accent: bool = False,
        loop: bool = False,
        movie: bool = False,
        video_title: Optional[str] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        condense_dur = max_duration if fit_short else None
        original_blocks, _ = inject_constraints_into_srt(srt_input, condense_target_duration=condense_dur, loop=loop)
        total_blocks = len(original_blocks)

        is_english = bool(target_language and str(target_language).strip().lower().startswith("en"))
        active_style = (style or getattr(self, "style", "viral") or "viral").lower()
        if active_style in ("funny", "comedy", "roast"):
            prompt_template = FUNNY_SYSTEM_PROMPT
            logger.info(f"Translating & transcreating {total_blocks} blocks into '{target_language}' using FUNNY comedy style{' (Infinite Loop Bridge active)' if loop else ''}.")
        else:
            prompt_template = ENGLISH_SYSTEM_PROMPT if is_english else self.system_prompt_template
            logger.info(f"Translating & transcreating {total_blocks} blocks into '{target_language}' using standard viral style{' (Infinite Loop Bridge active)' if loop else ''}.")

        system_instruction = prompt_template.format(target_language=target_language)

        if loop:
            system_instruction += INFINITE_LOOP_DIRECTIVE

        if movie:
            logger.info("[Translator] Movie Mode Pillar Script active (Callaway Story Flow/Atomic Messaging/Speed-to-Value + CineScope pacing).")
            system_instruction += MOVIE_PILLAR_DIRECTIVE
            movie_ctx = self.lookup_movie_context(original_blocks, video_title=video_title)
            if movie_ctx:
                logger.info(f"[Translator] Movie context retrieved via Google Search: {movie_ctx[:120]}...")
                system_instruction += (
                    "\n\n### BACKGROUND MOVIE CONTEXT (REFERENCE ONLY — NO OFF-SCREEN SPOILERS):\n"
                    f"{movie_ctx}\n"
                    "Use this context ONLY to understand motives, fix mistranscribed terms/rules, and keep character roles consistent. "
                    "Narrate ONLY what is visually happening in each block's exact timestamp window."
                )

        if fit_short:
            logger.info(f"[Translator] 1-Minute Short Condensation active: Budgeting words to fit strictly under {max_duration:.1f}s.")
            system_instruction += CONDENSED_SHORT_DIRECTIVE.format(max_duration=max_duration)

        is_elevenlabs = bool(tts_engine and tts_engine.lower() in ("elevenlabs", "eleven_labs", "11labs"))
        if is_elevenlabs:
            logger.info("[Translator] ElevenLabs engine detected: Injecting expressive audio tag directives ([excited], [shocked], [laughs], [gasps]).")
            tag_instructions = (
                "\n\n### MANDATORY ELEVENLABS AUDIO TAGGING DIRECTIVE:\n"
                "The target voice engine is ElevenLabs v4. Naturally weave expressive inline audio performance tags in square brackets "
                "such as [excited], [shocked], [gasps], [curious], [sighs], or [pause] where appropriate to match "
                "the drama, curiosity, and human reactions in each scene.\n"
                "- STRICT LIMIT ON [laughs] / [chuckles]: Use laughing tags ONLY when there is actual, genuine humor or a funny moment in that specific scene. DO NOT inject [laughs] or [chuckles] randomly in serious, technical, or educational craft explanations!\n"
                "- STRICT LIMIT ON [whispers]: DO NOT overuse [whispers]! Constant whispering ruins speech audibility and kills video retention. "
                "Use [whispers] AT MOST ONCE in the entire video (only for an extreme, confidential secret reveal) or ZERO times! "
                "NEVER use [whispers] across multiple blocks. Prioritize high-energy cues: [excited], [shocked], [gasps], [curious]!\n"
                "- Do NOT use HTML/XML tags. Use ONLY standard square brackets [tag]."
            )
            system_instruction += tag_instructions

        if anti_accent and not is_english:
            logger.info("[Translator] Anti-Accent mode active: Injecting consecutive English syllable-balancing directives.")
            system_instruction += ANTI_ACCENT_SYSTEM_PROMPT_DIRECTIVE

        translated_blocks_accumulator: List[str] = []
        translated_objects_history: List[Dict[str, Any]] = []

        if total_blocks <= batch_size:
            logger.info(f"Short-form video ({total_blocks} <= {batch_size} blocks): Single-pass transcreation.")
            _, constrained_srt = inject_constraints_into_srt(original_blocks, condense_target_duration=condense_dur, loop=loop)
            loop_req = (
                "3. MANDATORY INFINITE LOOP STITCH: [Final Block] + [Block 1] MUST connect seamlessly as ONE complete sentence.\n"
                if loop else
                "3. NATURAL CONCLUSION: Provide a punchy, complete ending for the final scene without dangling connector words.\n"
            )
            if fit_short:
                prompt = (
                    f"Transcreate and aggressively condense these {total_blocks} subtitle blocks strictly into {target_language} "
                    f"to fit within a 1-minute YouTube Short (under {max_duration:.1f}s).\n"
                    f"CRITICAL REQUIREMENTS:\n"
                    f"1. Cut out all fluff; strictly adhere to each block's target words budget: [Target: ~X words (Max: Y)].\n"
                    f"2. NEVER start Block 1 with filler sounds! Dive straight into the story on frame 1.\n"
                    f"{loop_req}"
                    f"4. Valid SRT output with original timestamps only:\n\n"
                    f"{constrained_srt}"
                )
            else:
                loop_req_full = (
                    "2. MANDATORY INFINITE LOOP STITCH: Before outputting, stitch [Final Block] + [Block 1] together in your mind. "
                    "They MUST read continuously as ONE single, natural, complete, grammatically flawless sentence.\n"
                    if loop else
                    "2. NATURAL CONCLUSION: Conclude the final block naturally with a complete thought, satisfying reveal, or punchline without dangling connectors.\n"
                )
                filler_ban_line = (
                    "1. NEVER start Block 1 with weak filler sounds like 'Wow', 'Oh', 'Hey', or 'Look'! Dive straight into the story on frame 1.\n"
                    if is_english else
                    "1. NEVER start Block 1 with 'ओहो', 'वाह', 'Wow', 'अरे', or filler sounds! Dive straight into the story on frame 1.\n"
                )
                prompt = (
                    f"Transcreate the following {total_blocks} timestamped subtitle blocks strictly into {target_language}.\n"
                    f"CRITICAL REQUIREMENTS:\n"
                    f"{filler_ban_line}"
                    f"{loop_req_full}"
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

                _, chunk_constrained_srt = inject_constraints_into_srt(chunk, condense_target_duration=condense_dur, loop=loop)

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
        if anti_accent and not is_english:
            verified_srt = balance_consecutive_english(verified_srt)

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
    temperature: float = 0.4,
    anti_accent: bool = False,
    loop: bool = False
) -> str:
    keys = [api_key] if api_key else None
    translator = SRTDubTranslator(api_keys=keys, model=model)
    verified_srt, _ = translator.translate_and_rewrite_srt(
        srt_input=srt_input,
        target_language=target_language,
        batch_size=batch_size,
        temperature=temperature,
        anti_accent=anti_accent,
        loop=loop
    )
    return verified_srt
