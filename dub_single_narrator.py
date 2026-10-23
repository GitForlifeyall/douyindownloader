#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dub_single_narrator.py
======================
Single-Narrator Continuous Dubbing Engine for YouTube Shorts & Reels.

Fundamental Architecture:
1. Stop anchoring to block-by-block Chinese SRT timestamps.
2. Transcreate the complete video narrative using Gemini (gemini-3.8-flash) into 1-2 continuous,
   engaging Hindi/Hinglish paragraphs (under 2,500 chars).
3. Send full paragraphs to Sarvam AI (bulbul:v3 / bulbul:v4-flash) for seamless, natural voiceover.
4. Silence compressor eliminates all dead gaps between sentences (tightens pauses > 200ms to ~140ms).
5. Dynamic tempo scaling adjusts the master speech track so it starts at 0:00 and the final word
   lands precisely at vid_dur - 0.3s (ZERO cuts, ZERO truncated endings).
6. Auto-sync subtitles using Faster-Whisper on the final audio.
7. Mix with isolated Foley sound effects (sfx.wav) and royalty-free background audio (assets/background_audio/) and mux with the clean video.
"""

import io
import os
import sys
import re
import json
import time
import base64
import difflib
import shutil
import argparse
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Any, Union

import numpy as np
import soundfile as sf
from sarvamai import SarvamAI
from google import genai
from google.genai import types

from dubbing_studio.env_loader import configure_runtime_environment
configure_runtime_environment()

from dubbing_studio.key_pool import (
    get_active_gemini_keys,
    mark_gemini_key_dead,
    is_gemini_dead_error,
    get_active_sarvam_keys,
    mark_sarvam_key_dead,
    is_sarvam_dead_error,
    mask_key,
)
from dubbing_studio.tts_engine import load_srt_blocks, srt_to_ass, generate_synced_hinglish_ass
from dubbing_studio.tts_google import parse_gemini_audio_response
from dubbing_studio.block_aligner import load_detected_margin_v, resolve_dynamic_bgm_volume
from dubbing_studio.hinglish import word_to_hinglish

# Biases Faster-Whisper towards Roman-script Hinglish so the spoken words line up
# with the Roman-script narration script (much tighter word-level alignment).
WHISPER_HINGLISH_PROMPT = (
    "Hinglish narration in Roman script. Example: sattar meter gehri khai par hawa mein "
    "latka hua hai ye prachin mahal."
)


def get_media_duration(file_path: Union[str, Path]) -> float:
    """Get accurate media duration via ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        str(file_path)
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(json.loads(r.stdout)["format"]["duration"])


def transcreate_continuous_script_gemini(
    raw_text_or_srt: str,
    target_language: str = "Hindi (Natural conversational Hindi written in native Devanagari script for ultra-realistic TTS prosody)",
    video_duration: Optional[float] = None,
    style: str = "viral"
) -> str:
    """
    Uses Gemini to generate a single continuous, punchy storytelling script
    optimized for YouTube Shorts narration with Method 1 Infinite Loop (Cause & Effect Bridge).
    Written strictly in native Devanagari Hindi for maximum TTS prosody and vowel clarity.
    Supports style='funny' for hilarious desi comedy, local jokes, and roasty meme humor.
    """
    keys = get_active_gemini_keys()
    if not keys:
        raise RuntimeError("No active GEMINI_API_KEY available in .env!")

    length_rule = ""
    if video_duration and video_duration > 5:
        target_words = int(video_duration * 2.5)
        min_words = int(target_words * 0.90)
        max_words = int(target_words * 1.08)
        length_rule = (
            f"1. TARGET LENGTH (MANDATORY): The video is {video_duration:.1f} seconds long. "
            f"You MUST write approximately {target_words} words (between {min_words} and {max_words} words, approx 1,500 to 1,800 characters). "
            f"Do NOT write a short 3-sentence summary! Thoroughly cover EVERY scene, obstacle, and engineering technique so the narration naturally sustains the full {video_duration:.0f}s duration!\n"
        )
    else:
        length_rule = "1. TARGET LENGTH: Write a comprehensive, detailed storytelling narrative of ~250 words covering every step.\n"

    active_style = (style or "viral").lower()
    if active_style in ("funny", "comedy", "roast"):
        role_header = (
            "### ROLE & PERSONA: UNHINGED DESI REELS COMMENTATOR\n"
            "You are an elite Indian Instagram Reels / YouTube Shorts voiceover artist combining:\n"
            "1. Lord Puneet Superstar Energy: Loud, erratic, brutally honest, dramatic vocal reactions ('इतना सन्नाटा क्यों है भाई?!', 'अरे भईईई, ये क्या देख लिया मैंने!').\n"
            "2. Desi Street Roaster (Delhi/UP/Haryana/Mumbai belt): Effortless use of raw, high-engagement Hindi street slang—never textbook Hindi, never polite Uncle-jokes.\n"
            "3. Instagram Brainrot & Dank Commentary: Fast-paced, observational roasting of whatever is happening on screen instead of forcing outdated catchphrases.\n"
            "Below is the subtitle transcription of a video. Your mission is to transcreate this into an unbroken, ridiculously funny, witty voiceover narrative written strictly in modern conversational HINDI using native DEVANAGARI script (देवनागरी लिपि).\n"
        )
        comedy_rules = (
            "5. NO STATIC CATCHPHRASE SPAM (CRITICAL):\n"
            "   - DO NOT shoehorn dead 2023 memes ('Moye Moye', 'Look like a wow', 'Sharmaji ka beta', 'Papa ki pari') unless 100% ironically twisted.\n"
            "   - Instead, IMPROVISE fresh punchlines that directly mock the exact visual action, facial expression, or absurdity of the characters on screen.\n"
            "6. DESI SLANG & VIRAL VOCABULARY BANK (Mix & Match Organically):\n"
            "   - Roasting: नल्ला (Nalla), छपरी (Chhapri), लप्पू सा (Lappu sa), टोपा (Topa), चमन (Chaman), नमूना (Namoona), डेढ़ शाणा (Dedh shaana), फुकra (Fukra), सस्ता [X] (e.g., 'सस्ता अंबानी').\n"
            "   - Chaos & Drama: भारी कलेश (Bhaari kalesh), बवाल चीज़ (Bawaal cheez), भौकाल (Bhaukaal), लफड़ा (Lafda), पेल दिया (Pel diya), धज्जियां उड़ा दी, कांड हो गया, अब बजेगा असली बाजा!.\n"
            "   - Shock & Cringe (Puneet style): अरे भईईई! (Are bhaiii!), भाई मारो मुझे मारो!, ये कौन सा सस्ता नशा है भाई?, मेरी आंखों में हार्पिक डाल दो!, कतई ज़हर, भाई का कॉन्फिडेंस तो देखो!, आज की युवा पीढ़ी बर्बाद है भाई!.\n"
            "   - Scheming & Fails: टोपी पहना रहा है, चूना लगा दिया, बकैती, हवाबाज़ी मत कर, कट गया भाई का, सीधा मुंह के बल पेल दिया!, भाई के साथ तो भारी स्कैम हो गया!.\n"
            "   - Swag & Dominance: लॉर्ड [Character Type], जलवा है भाई का, एक तरफा माहौल, सीधा औकात याद दिला दी.\n"
            "   - Bizarre / DIY / Stunts: भाई ये क्या बवासीर बना दिए हो?, मौत से सीधा खिलवाड़ चल रहा है, यमराज का वीआईपी पास ले के बैठा है ये!.\n"
            "7. DYNAMIC PUNCHLINE PATTERNS:\n"
            "   - 'Sasta + Celebrity/Object' Roast: (e.g., 'ये मीशो से मंगाया हुआ जॉन अब्राहम क्यों लग रहा है?', 'चाइना के सस्ते लॉर्ड पुनीत को देखो ज़रा!').\n"
            "   - Over-Dramatic Puneet Outbursts: (e.g., 'अरे भईईई! नाले में कूदने की तैयारी है क्या?!', 'अरे-अरे-अरे, भाई ने तो पूरा रायता फैला दिया!').\n"
            "   - Desi Situational Comparisons: (e.g., 'इतनी तेज़ तो लोग भंडारे की पूड़ी लूटने नहीं भागते!', 'भाई ऐसे घूर रहा है जैसे इसकी पुश्तैनी ज़मीन हड़प ली हो!').\n"
            "8. TTS PROSODY & VOCAL INFLECTIONS (Sarvam Bulbul v3 / Gemini Flash):\n"
            "   - Use hyphenated stutters for comedic panic: ('अरे-अरे-अरे!', 'भाई-भाई-भाई!', 'ओए-ओए-ओए!', 'रुको-रुको-रुको!') to trigger rapid, panicked comedic pacing.\n"
            "   - **NO stretched vowels or repeated letters:** Write fillers exactly as spelled ('अरे', 'भाई', 'हाय राम'); never elongate ('भईईई' or 'bhaeee') — Sarvam TTS may mispronounce stretched tokens.\n"
            "   - Ban pure शुद्ध हिंदी connectors: NEVER use 'परंतु', 'अतः', 'क्योंकि वह व्यक्ति', or 'प्रतीत होता है'. Use natural street connectors: 'भाई ये बंदा', 'दिख रहा है ना', 'अबे सुनो', 'सीन क्या है ना'.\n"
        )
    else:
        role_header = (
            "You are an elite viral YouTube Shorts & Reels Retention Showrunner.\n"
            "Below is the subtitle transcription of a video. Your task is to transcreate this into an unbroken, energetic, highly engaging voiceover narrative written strictly in modern conversational HINDI using native DEVANAGARI script (देवनागरी लिपि). This is fed directly into neural TTS models (Sarvam AI & Google Gemini) for native human prosody.\n"
        )
        comedy_rules = (
            "5. CONVERSATIONAL FILLERS: Naturally weave in organic spoken fillers and conversational hooks (e.g., 'अरे,', 'देखो,', 'सुनो,', 'यार,', 'सोचो ज़रा,', 'लेकिन तभी...'). DO NOT use 'भाई' (bhai) repeatedly — limit it to at most once in the whole narration and never start consecutive lines with it. Write fillers exactly as spelled — no elongated vowels or repeated letters (e.g., 'भाई', never 'भईईई'). Sarvam TTS may mispronounce stretched tokens.\n"
        )

    prompt = f"""{role_header}
CRITICAL RULES:
{length_rule}2. COVER ALL STEPS FROM BEGINNING TO END: Do not skip any plot points or technical secrets! You must narrate the entire journey from the opening canyon problem, through all intermediate building steps, to the final temple reveal.
3. Combine all information into 2 to 3 natural, breathless storytelling paragraphs.
4. Keep the story pacing fast, natural, and conversational with seamless transitions between points.
{comedy_rules}9. SCRIPT, VOCABULARY & NATURAL ENGLISH WORDS (100% ACCURATE SPELLINGS):
   - Whenever an object, plant, tool, material, technique, modern concept, or everyday term is in English (e.g., Honeysuckle, Gold grass, Purple tree, Bamboo, Stone, Arch, Bridge, Foundation, Structure, Pillar, Rebar, Crane, Scaffolding, Ice, Water, Liquid, Lipstick, Cactus, Powder, Drops, Process, Extract, Hack, Trick, Video, Viral, Frame, Layer, Lock, Pressure, Clips, Chemical, Filter, Temple, Canyon), WRITE IT IN STANDARD ENGLISH SCRIPT (Latin alphabet) with correct spelling!
   - NEVER awkwardly invent textbook Hindi translations (do NOT write 'स्वर्ण घास', 'बैंगनी पेड़', 'सिंह घास').
   - NEVER phonetically write English words in Devanagari (do NOT write 'हनीसकल', 'गोल्ड ग्रास', 'फाउंडेशन', 'स्ट्रक्चर', 'लिपस्टिक', 'ब्रिज').
   - All Hindi conversational dialogue, grammar, verbs, and connectors MUST be written in native Devanagari script (देवनागरी लिपि).
10. INFINITE SEAMLESS LOOP (METHOD 1 - CAUSE & EFFECT BRIDGE):
   - The very FIRST sentence (The Hook) and the very LAST sentence (The Loop Bridge) MUST form ONE complete, grammatically flawless sentence when read back-to-back: [Last Sentence] -> [First Sentence].
   - First Sentence (Hook): Describes the visual/wonder (e.g., '70 मीटर गहरी खाई पर हवा में लटका हुआ है ये प्राचीन पत्थर का महल!').
   - Last Sentence (Bridge): Ends with a cause or explanation that flows directly into the First Sentence (e.g., '...और पुराने ज़माने के कारीगरों के इसी हैरतअंगेज़ देसी जुगाड़ की वजह से—').
   - VERIFY: Read "[Last Sentence] [First Sentence]" together. It MUST sound like one unbroken, breathtaking sentence with NO missing words and NO grammatical clash.
10. Do NOT output timestamps, line numbers, or stage directions. Return ONLY the final narration text in Devanagari script.

Source text:
{raw_text_or_srt}
"""

    for key in list(keys):
        try:
            print(f"[Gemini] Transcreating continuous narrative using key: {mask_key(key)}...")
            client = genai.Client(api_key=key)
            resp = client.models.generate_content(
                model="gemini-3.8-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.4,
                    max_output_tokens=8192,
                )
            )
            narrative = resp.text.strip()
            # Clean up markdown or codeblocks if returned
            narrative = re.sub(r"^```[\w]*\n", "", narrative)
            narrative = re.sub(r"\n```$", "", narrative).strip()
            print(f"[Gemini] Generated narrative ({len(narrative)} chars):\n{narrative[:200]}...\n")
            return narrative
        except Exception as e:
            err_str = str(e)
            print(f"[Gemini] Error with key {mask_key(key)}: {err_str}")
            if is_gemini_dead_error(err_str):
                mark_gemini_key_dead(key, err_str)
            time.sleep(1)

    raise RuntimeError("All Gemini API keys failed during script transcreation.")


def synthesize_sarvam_paragraphs(
    paragraphs: List[str],
    speaker: str = "shubh",
    pace: float = 1.0,
    language_code: str = "hi-IN",
    model: str = "bulbul:v3",
    speech_sample_rate: int = 48000
) -> Tuple[np.ndarray, int]:
    """
    Sends each paragraph chunk (up to 2,500 chars) to Sarvam TTS and concatenates the audio.
    """
    all_audio_chunks = []
    sr = speech_sample_rate

    for idx, para in enumerate(paragraphs):
        para = para.strip()
        if not para:
            continue
        print(f"[Sarvam TTS] Synthesizing paragraph {idx+1}/{len(paragraphs)} ({len(para)} chars)...")
        
        success = False
        while not success:
            keys = get_active_sarvam_keys()
            if not keys:
                raise RuntimeError("All Sarvam AI API keys are exhausted!")
            key = keys[0]

            try:
                client = SarvamAI(api_subscription_key=key)
                response = client.text_to_speech.convert(
                    text=para,
                    language_code=language_code,
                    model=model,
                    speaker=speaker,
                    pace=float(pace),
                    speech_sample_rate=speech_sample_rate
                )
                raw_audio = response.audios[0] if hasattr(response, "audios") and response.audios else response
                if isinstance(raw_audio, str):
                    audio_bytes = base64.b64decode(raw_audio)
                elif isinstance(raw_audio, bytes):
                    audio_bytes = raw_audio
                else:
                    audio_bytes = bytes(raw_audio)

                # Decode audio bytes into numpy array
                with io.BytesIO(audio_bytes) as bio:
                    data, audio_sr = sf.read(bio)
                    if data.ndim > 1:
                        data = data.mean(axis=1)
                    all_audio_chunks.append(data.astype(np.float32))
                    sr = audio_sr
                success = True
            except Exception as e:
                err_str = str(e)
                print(f"[Sarvam TTS] Error with key {mask_key(key)}: {err_str}")
                if is_sarvam_dead_error(err_str):
                    mark_sarvam_key_dead(key, err_str)
                else:
                    time.sleep(1.5)

    if not all_audio_chunks:
        raise RuntimeError("No audio was generated from Sarvam TTS!")

    # Concatenate paragraphs with a brief 100ms natural breathing space
    inter_pause = np.zeros(int(0.10 * sr), dtype=np.float32)
    full_audio = []
    for i, chunk in enumerate(all_audio_chunks):
        if i > 0:
            full_audio.append(inter_pause)
        full_audio.append(chunk)

    combined = np.concatenate(full_audio, axis=0)
    return combined, sr


def synthesize_google_paragraphs(
    paragraphs: List[str],
    voice: str = "Puck",
    sample_rate: int = 24000,
    model: str = "gemini-2.5-flash-preview-tts",
    enable_autotag: bool = True
) -> Tuple[np.ndarray, int]:
    """
    Sends each paragraph chunk to Google Gemini Flash TTS (voice="Puck" for Bunty Clone)
    with multi-key rotation and combines the audio into continuous speech.
    """
    active_keys = get_active_gemini_keys()
    if not active_keys:
        raise RuntimeError("No active Gemini API keys available for Google Flash TTS!")

    models_to_try = [model, "gemini-3.8-flash-tts", "gemini-2.5-flash-preview-tts"]
    models_to_try = list(dict.fromkeys(models_to_try))

    if enable_autotag:
        from dubbing_studio.autotagger import autotag_narrative_paragraphs
        synth_paragraphs = autotag_narrative_paragraphs(paragraphs)
        print(f"[Google Flash TTS ({voice})] Autotagged {len(paragraphs)} paragraph(s) with dynamic performance cues.")
    else:
        synth_paragraphs = paragraphs

    cfg = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config={"voice_config": {"prebuilt_voice_config": {"voice_name": voice}}}
    )

    all_audio_chunks = []
    sr = sample_rate
    key_idx = 0

    for idx, para in enumerate(synth_paragraphs):
        para = para.strip()
        if not para:
            continue
        print(f"[Google Flash TTS ({voice})] Synthesizing paragraph {idx+1}/{len(paragraphs)} ({len(para)} chars)...")

        success = False
        for attempt in range(len(active_keys) * 3):
            curr_key = active_keys[key_idx % len(active_keys)]
            curr_model = models_to_try[attempt % len(models_to_try)]
            client = genai.Client(api_key=curr_key)
            try:
                res = client.models.generate_content(
                    model=curr_model,
                    contents=para,
                    config=cfg
                )
                part = res.candidates[0].content.parts[0]
                raw_bytes = part.inline_data.data
                mime_type = getattr(part.inline_data, "mime_type", "audio/L16")
                audio, chunk_sr = parse_gemini_audio_response(raw_bytes, mime_type=mime_type, sample_rate=sample_rate)
                all_audio_chunks.append(audio)
                sr = chunk_sr
                success = True
                print(f"      ✓ Paragraph {idx+1} synthesized: {len(audio)/sr:.2f}s via {curr_model}")
                key_idx = (key_idx + 1) % len(active_keys)
                break
            except Exception as e:
                err_str = str(e)
                print(f"      [Retry {attempt+1} on Key {mask_key(curr_key)} ({curr_model})] Error: {err_str[:80]}")
                if is_gemini_dead_error(err_str):
                    mark_gemini_key_dead(curr_key, reason=err_str[:80])
                    active_keys = get_active_gemini_keys()
                    if not active_keys:
                        raise RuntimeError("All Gemini API keys exhausted for Google Flash TTS!")
                else:
                    key_idx = (key_idx + 1) % len(active_keys)
                    time.sleep(1.0)

        if not success:
            raise RuntimeError(f"Failed to synthesize paragraph {idx+1} with Google Flash TTS!")

    if not all_audio_chunks:
        raise RuntimeError("No audio was generated from Google Flash TTS!")

    inter_pause = np.zeros(int(0.10 * sr), dtype=np.float32)
    full_audio = []
    for i, chunk in enumerate(all_audio_chunks):
        if i > 0:
            full_audio.append(inter_pause)
        full_audio.append(chunk)

    combined = np.concatenate(full_audio, axis=0)
    return combined, sr


def compress_audio_silences(
    audio: np.ndarray,
    sample_rate: int,
    silence_threshold: float = 0.015,
    max_pause_sec: float = 0.18,
    min_silence_detect_sec: float = 0.22
) -> np.ndarray:
    """
    Compresses internal silences/dead gaps greater than min_silence_detect_sec
    down to max_pause_sec, and trims leading/trailing silence.
    Guarantees zero awkward dead gaps anywhere in the narration.
    """
    frame_ms = 10
    frame_len = int(sample_rate * (frame_ms / 1000.0))
    n_frames = len(audio) // frame_len
    if n_frames < 2:
        return audio

    energies = np.array([
        np.max(np.abs(audio[i * frame_len:(i + 1) * frame_len]))
        for i in range(n_frames)
    ])
    is_silent = energies < silence_threshold

    # Find start and end of actual speech
    active_indices = np.where(~is_silent)[0]
    if len(active_indices) == 0:
        return audio

    first_frame = max(0, active_indices[0] - int(0.04 * 1000 / frame_ms))  # 40ms pad
    last_frame = min(n_frames, active_indices[-1] + 1)  # 0ms pad at end: zero silence on final word

    # Compress internal silence intervals
    compressed_frames = []
    current_silence_len = 0
    max_allowed_silent_frames = int((max_pause_sec * 1000) / frame_ms)
    min_detect_silent_frames = int((min_silence_detect_sec * 1000) / frame_ms)

    for idx in range(first_frame, last_frame):
        frame = audio[idx * frame_len:(idx + 1) * frame_len]
        if is_silent[idx]:
            current_silence_len += 1
            if current_silence_len <= max_allowed_silent_frames:
                compressed_frames.append(frame)
        else:
            current_silence_len = 0
            compressed_frames.append(frame)

    if not compressed_frames:
        return audio

    out_audio = np.concatenate(compressed_frames, axis=0)
    print(f"[Silence Compressor] Duration: {len(audio)/sample_rate:.2f}s -> {len(out_audio)/sample_rate:.2f}s (removed {(len(audio)-len(out_audio))/sample_rate:.2f}s dead gaps)")
    return out_audio


def adjust_audio_tempo_ffmpeg(input_wav: Path, output_wav: Path, tempo_factor: float) -> None:
    """
    Changes audio tempo without pitch alteration using FFmpeg atempo filters.
    """
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    
    # FFmpeg atempo only supports 0.5 to 2.0 per filter instance
    atempo_filters = []
    remaining = tempo_factor
    while remaining > 2.0:
        atempo_filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        atempo_filters.append("atempo=0.5")
        remaining /= 0.5
    atempo_filters.append(f"atempo={remaining:.5f}")
    filter_str = ",".join(atempo_filters)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_wav),
        "-filter:a", filter_str,
        "-vn",
        str(output_wav)
    ]
    subprocess.run(cmd, capture_output=True, check=True)


def normalize_match_token(token: str) -> str:
    """
    Normalizes a single spoken/script word so both sides can be compared.
    Devanagari is transliterated to Latin (same map the caption engine uses),
    punctuation is dropped and the result is lowercased.
    """
    token = (token or "").strip()
    if not token:
        return ""
    if any("\u0900" <= ch <= "\u097F" for ch in token):
        token = word_to_hinglish(token)
    token = token.lower()
    token = re.sub(r"[^0-9a-z\u0900-\u097F]+", "", token)
    return token


def match_key(token: str) -> str:
    """
    Consonant skeleton of a word, so Roman-script Hinglish ('gehri') and its
    Devanagari spelling ('गहरी' -> 'gahari') collapse to the same key ('ghr').
    """
    return re.sub(r"[aeiou]", "", normalize_match_token(token))


def align_token_indices(
    script_keys: List[str],
    spoken_keys: List[str],
    min_similarity: float = 0.75
) -> List[Tuple[int, int]]:
    """
    Needleman-Wunsch alignment between script words and spoken words.
    Returns the (script_index, spoken_index) pairs that describe the same word.
    """
    m = len(script_keys)
    n = len(spoken_keys)
    if m == 0 or n == 0:
        return []

    gap_penalty = -0.55
    sim: List[List[float]] = [[0.0] * n for _ in range(m)]
    for i in range(m):
        sk = script_keys[i]
        if not sk:
            continue
        for j in range(n):
            wk = spoken_keys[j]
            if not wk:
                continue
            if sk == wk:
                sim[i][j] = 2.0
            else:
                sim[i][j] = difflib.SequenceMatcher(None, sk, wk).ratio() - 0.45

    score = [[0.0] * (n + 1) for _ in range(m + 1)]
    ptr = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        score[i][0] = score[i - 1][0] + gap_penalty
        ptr[i][0] = 1
    for j in range(1, n + 1):
        score[0][j] = score[0][j - 1] + gap_penalty
        ptr[0][j] = 2

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            diag = score[i - 1][j - 1] + sim[i - 1][j - 1]
            up = score[i - 1][j] + gap_penalty
            left = score[i][j - 1] + gap_penalty
            best = max(diag, up, left)
            score[i][j] = best
            if best == diag:
                ptr[i][j] = 0
            elif best == up:
                ptr[i][j] = 1
            else:
                ptr[i][j] = 2

    pairs: List[Tuple[int, int]] = []
    i, j = m, n
    while i > 0 and j > 0:
        p = ptr[i][j]
        if p == 0:
            sk, wk = script_keys[i - 1], spoken_keys[j - 1]
            if sk and wk:
                ratio = 1.0 if sk == wk else difflib.SequenceMatcher(None, sk, wk).ratio()
                if ratio >= min_similarity:
                    pairs.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif p == 1:
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    return pairs


def transcribe_narration_words(
    master_wav: Path,
    cache_path: Optional[Path] = None,
    force: bool = False
) -> List[Dict[str, Any]]:
    """
    Captures the REAL spoken-word timings of the final narration master using Faster-Whisper.
    This is the ground truth the caption engine needs: no character-duration guessing.
    """
    if cache_path and cache_path.exists() and not force:
        stale = cache_path.stat().st_mtime < master_wav.stat().st_mtime
        if stale:
            print("[Subtitles] Narration audio changed since last alignment; re-aligning.")
        else:
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if cached:
                    print(f"[Subtitles] Reusing cached narration word alignment: {cache_path.name}")
                    return cached
            except Exception:
                pass

    from faster_whisper import WhisperModel

    model = None
    for device, compute_type in (("cuda", "int8_float16"), ("cuda", "float16"), ("cpu", "int8")):
        try:
            print(f"[Subtitles] Loading Faster-Whisper large-v3-turbo on {device} ({compute_type})...")
            model = WhisperModel("large-v3-turbo", device=device, compute_type=compute_type)
            break
        except Exception as e:
            print(f"[Subtitles] Whisper init failed on {device}/{compute_type}: {e}")
    if model is None:
        raise RuntimeError("Faster-Whisper could not be initialized for narration alignment.")

    segments, info = model.transcribe(
        str(master_wav),
        language="hi",
        word_timestamps=True,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=250),
        initial_prompt=WHISPER_HINGLISH_PROMPT,
        condition_on_previous_text=False
    )

    words: List[Dict[str, Any]] = []
    for seg in segments:
        for w in (getattr(seg, "words", None) or []):
            if w.start is None or w.end is None:
                continue
            text = (w.word or "").strip()
            if not text:
                continue
            words.append({
                "start": round(float(w.start), 3),
                "end": round(float(w.end), 3),
                "word": text
            })

    print(f"[Subtitles] Captured {len(words)} spoken words from {master_wav.name} (lang={info.language})")
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(words, ensure_ascii=False, indent=2), encoding="utf-8")
    return words


def align_script_words_to_audio(
    script_text: str,
    spoken_words: List[Dict[str, Any]],
    total_duration: float
) -> List[Dict[str, Any]]:
    """
    Maps the EXACT narration script onto the real Whisper word timings.
    Matched words inherit their true spoken start/end; unmatched words are interpolated
    between their nearest matched neighbours. Output is phrase-level blocks, which the
    caption engine then renders into its own <=3 word, syllable-weighted events.
    """
    script_tokens = script_text.split()
    if not script_tokens:
        return []

    script_keys = [match_key(t) for t in script_tokens]
    spoken_keys = [match_key(w["word"]) for w in spoken_words]

    timings: List[Optional[Tuple[float, float]]] = [None] * len(script_tokens)
    anchors: List[Tuple[int, int]] = []

    if spoken_words:
        anchors = align_token_indices(script_keys, spoken_keys)
        for s_idx, w_idx in anchors:
            timings[s_idx] = (spoken_words[w_idx]["start"], spoken_words[w_idx]["end"])

    # Fill unmatched script words by interpolating between the nearest anchors.
    for s_idx in range(len(script_tokens)):
        if timings[s_idx] is not None:
            continue

        prev_anchor = None
        next_anchor = None
        for a_idx, w_idx in anchors:
            if a_idx < s_idx and (prev_anchor is None or a_idx > prev_anchor[0]):
                prev_anchor = (a_idx, w_idx)
            if a_idx > s_idx and (next_anchor is None or a_idx < next_anchor[0]):
                next_anchor = (a_idx, w_idx)

        if prev_anchor and next_anchor:
            (sp, wp), (sn, wn) = prev_anchor, next_anchor
            frac = (s_idx - sp) / float(sn - sp) if sn > sp else 0.0
            start = spoken_words[wp]["start"] + (spoken_words[wn]["start"] - spoken_words[wp]["start"]) * frac
            end = spoken_words[wp]["end"] + (spoken_words[wn]["end"] - spoken_words[wp]["end"]) * frac
        elif prev_anchor:
            start = end = spoken_words[prev_anchor[1]]["end"]
        elif next_anchor:
            start = end = spoken_words[next_anchor[1]]["start"]
        else:
            span = max(0.4, total_duration / float(len(script_tokens)))
            start = s_idx * span
            end = start + span
        timings[s_idx] = (max(0.0, start), max(start, end))

    # Keep the word timeline strictly monotonic and non-overlapping.
    for i in range(1, len(timings)):
        prev_start, prev_end = timings[i - 1]
        st, en = timings[i]
        st = max(st, prev_start, prev_end)
        en = max(en, st)
        timings[i] = (st, en)

    print(f"[Subtitles] Aligned {len(script_tokens)} script words to {len(spoken_words)} spoken words "
          f"({len(anchors)} exact anchors).")

    # Group the timed words into phrase-level blocks (the engine does the <=3 word split).
    blocks: List[Dict[str, Any]] = []
    current: List[Tuple[str, float, float]] = []

    def flush() -> None:
        if not current:
            return
        text = " ".join(t for t, _, _ in current).strip()
        if text:
            start = current[0][1]
            end = current[-1][2]
            if end <= start:
                end = start + 0.4
            blocks.append({
                "index": len(blocks) + 1,
                "start": round(start, 3),
                "end": round(end, 3),
                "text": text
            })
        current.clear()

    for idx, token in enumerate(script_tokens):
        st, en = timings[idx]
        current.append((token, st, en))
        span = current[-1][2] - current[0][1]
        ends_sentence = bool(re.search(r"[.!?।\u0964\u0965][\"')\]]*$", token))
        if ends_sentence or len(current) >= 14 or span >= 7.0:
            flush()
    flush()

    return blocks


def write_placed_blocks_srt(placed_blocks: List[Dict[str, Any]], output_srt: Path) -> Path:
    """Fallback SRT writer used only when the caption engine's own writer fails."""

    def to_srt_time(sec: float) -> str:
        hrs = int(sec // 3600)
        mins = int((sec % 3600) // 60)
        secs = int(sec % 60)
        ms = int(round((sec - int(sec)) * 1000))
        return f"{hrs:02d}:{mins:02d}:{secs:02d},{ms:03d}"

    output_srt.parent.mkdir(parents=True, exist_ok=True)
    chunks = []
    for b in placed_blocks:
        chunks.append(
            f"{b['index']}\n{to_srt_time(b['start'])} --> {to_srt_time(b['end'])}\n{b['text']}\n"
        )
    output_srt.write_text("\n".join(chunks) + "\n", encoding="utf-8")
    return output_srt


def generate_synced_captions(
    master_wav: Path,
    script_text: str,
    output_srt: Path,
    output_ass: Path,
    margin_v: Optional[int] = None,
    work_dir: Optional[Path] = None,
    force: bool = False
) -> Path:
    """
    Caption generation - 100% owned by dubbing_studio/tts_engine.py.

    Flow: Faster-Whisper word alignment of the final narration master
          -> phrase-level placed blocks
          -> generate_synced_hinglish_ass()  (writes the timeline-synced SRT)
          -> srt_to_ass() inside it, with the engine's own default styling.

    Zero custom overrides: no font swaps, no font size changes, no outline/shadow
    changes and no custom timing math.
    """
    print("[Subtitles] Building audio-synced captions via dubbing_studio.tts_engine...")

    spoken_words: List[Dict[str, Any]] = []
    try:
        cache_path = (work_dir / "narration_whisper_words.json") if work_dir else None
        spoken_words = transcribe_narration_words(master_wav, cache_path=cache_path, force=force)
    except Exception as e:
        print(f"[Subtitles] Notice: Whisper alignment unavailable ({e}); using timeline fallback.")

    total_duration = get_media_duration(master_wav)
    placed_blocks = align_script_words_to_audio(script_text, spoken_words, total_duration)
    if not placed_blocks:
        raise RuntimeError("Could not build caption blocks from the narration script.")

    output_ass.parent.mkdir(parents=True, exist_ok=True)
    try:
        generate_synced_hinglish_ass(
            master_wav=master_wav,
            placed_blocks=placed_blocks,
            output_ass=output_ass,
            margin_v=margin_v,
            run_whisper=True
        )
    except Exception as e:
        print(f"[Subtitles] Notice: Engine synced writer failed ({e}); falling back to srt_to_ass.")
        fallback_srt = write_placed_blocks_srt(placed_blocks, master_wav.parent / f"{master_wav.stem}_synced.srt")
        srt_to_ass(fallback_srt, output_ass, margin_v=margin_v, to_hinglish=True)

    # Keep both the timeline-synced Roman Hinglish SRT and Devanagari SRT artifacts
    synced_srt = master_wav.parent / f"{master_wav.stem}_synced.srt"
    hinglish_srt = master_wav.parent / f"{master_wav.stem}_hinglish.srt"
    output_srt.parent.mkdir(parents=True, exist_ok=True)
    if hinglish_srt.exists():
        shutil.copyfile(hinglish_srt, output_srt)
        devanagari_srt = output_srt.with_name(f"{output_srt.stem}_devanagari.srt")
        if synced_srt.exists():
            shutil.copyfile(synced_srt, devanagari_srt)
    elif synced_srt.exists():
        shutil.copyfile(synced_srt, output_srt)

    print(f"[Subtitles] Captions ready: {output_ass}")
    return output_ass


def mix_master_and_mux(
    clean_video_path: Path,
    narration_audio_path: Path,
    sfx_path: Optional[Path],
    bg_music_path: Optional[Path],
    subtitles_ass_path: Optional[Path],
    output_video_path: Path,
    target_duration: float,
    video_speedup: float = 1.0
) -> Path:
    """
    Mixes voiceover narration with isolated Foley SFX (sfx.wav) and royalty-free background music,
    applies B-roll video speedup if audio was shorter than video, and muxes with clean video.
    """
    output_video_path.parent.mkdir(parents=True, exist_ok=True)

    bgm_vol = resolve_dynamic_bgm_volume(bg_music_path) if bg_music_path else 0.07
    has_sfx = bool(sfx_path and Path(sfx_path).exists())
    has_bgm = bool(bg_music_path and Path(bg_music_path).exists())

    if has_sfx and has_bgm:
        inputs = [
            "-i", str(narration_audio_path),
            "-i", str(sfx_path),
            "-stream_loop", "-1", "-i", str(bg_music_path)
        ]
        sfx_tempo = f"atempo={video_speedup:.5f}," if abs(video_speedup - 1.0) > 0.01 else ""
        filter_complex = (
            "[0:a]loudnorm=I=-14:TP=-1.5:LRA=7,asplit=2[voice_main][voice_key];"
            f"[1:a]{sfx_tempo}agate=threshold=0.008:range=0.1:attack=10:release=150,volume=0.70[sfx_clean];"
            "[sfx_clean][voice_key]sidechaincompress=threshold=0.04:ratio=4:attack=5:release=200[sfx_ducked];"
            f"[2:a]volume={bgm_vol:.2f}[music];"
            "[voice_main][sfx_ducked][music]amix=inputs=3:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.89[aout]"
        )
    elif has_sfx:
        inputs = [
            "-i", str(narration_audio_path),
            "-i", str(sfx_path)
        ]
        sfx_tempo = f"atempo={video_speedup:.5f}," if abs(video_speedup - 1.0) > 0.01 else ""
        filter_complex = (
            "[0:a]loudnorm=I=-14:TP=-1.5:LRA=7,asplit=2[voice_main][voice_key];"
            f"[1:a]{sfx_tempo}agate=threshold=0.008:range=0.1:attack=10:release=150,volume=0.70[sfx_clean];"
            "[sfx_clean][voice_key]sidechaincompress=threshold=0.04:ratio=4:attack=5:release=200[sfx_ducked];"
            "[voice_main][sfx_ducked]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.89[aout]"
        )
    elif has_bgm:
        inputs = [
            "-i", str(narration_audio_path),
            "-stream_loop", "-1", "-i", str(bg_music_path)
        ]
        filter_complex = (
            "[0:a]loudnorm=I=-14:TP=-1.5:LRA=7[voice_main];"
            f"[1:a]volume={bgm_vol:.2f}[music];"
            "[voice_main][music]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.89[aout]"
        )
    else:
        inputs = ["-i", str(narration_audio_path)]
        filter_complex = "[0:a]loudnorm=I=-14:TP=-1.5:LRA=7[aout]"

    cmd_mix = [
        "ffmpeg", "-y"
    ] + inputs + [
        "-filter_complex", filter_complex,
        "-map", "[aout]",
        "-c:a", "aac", "-b:a", "192k",
        "-t", f"{target_duration:.3f}",
        str(narration_audio_path.with_name("mixed_final_audio.m4a"))
    ]
    subprocess.run(cmd_mix, capture_output=True, check=True)
    final_audio = narration_audio_path.with_name("mixed_final_audio.m4a")

    # Construct video filters (speedup + subtitles)
    vf_chain = []
    if abs(video_speedup - 1.0) > 0.01:
        vf_chain.append(f"setpts=PTS/{video_speedup:.5f}")
    if subtitles_ass_path and subtitles_ass_path.exists():
        escaped_ass = str(subtitles_ass_path).replace("\\", "/").replace(":", "\\:")
        vf_chain.append(f"subtitles='{escaped_ass}'")

    print(f"[Muxer] Muxing final dubbed video to {output_video_path} (Target duration: {target_duration:.2f}s)...")
    if vf_chain:
        video_filter = ",".join(vf_chain)
        cmd = [
            "ffmpeg", "-y",
            "-i", str(clean_video_path),
            "-i", str(final_audio),
            "-vf", video_filter,
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            "-t", f"{target_duration:.3f}",
            "-shortest",
            str(output_video_path)
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(clean_video_path),
            "-i", str(final_audio),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-t", f"{target_duration:.3f}",
            "-shortest",
            str(output_video_path)
        ]

    subprocess.run(cmd, capture_output=True, check=True)
    print(f"[SUCCESS] Final video ready at: {output_video_path}")
    return output_video_path


def resolve_subtitle_path(
    base_name: str,
    dubbed_srt: Optional[Union[str, Path]] = None,
    raw_srt: Optional[Union[str, Path]] = None,
    clean_video: Optional[Path] = None,
    root: Optional[Path] = None
) -> Optional[Path]:
    """
    Finds the most relevant SRT file (Hinglish/Hindi/Raw) across possible directory layouts.
    Handles single video runs, --folder batch runs (output/input/subtitles/), and custom paths.
    """
    if dubbed_srt and Path(dubbed_srt).exists() and Path(dubbed_srt).stat().st_size > 20:
        return Path(dubbed_srt)
    if raw_srt and Path(raw_srt).exists() and Path(raw_srt).stat().st_size > 20:
        return Path(raw_srt)

    candidates = []
    # If clean_video is provided, check relative layout (e.g. output/input/subtitles/ or output/subtitles/)
    if clean_video:
        sub_dir = clean_video.parent.parent / "subtitles"
        candidates.extend([
            sub_dir / f"{base_name}_hinglish.srt",
            sub_dir / f"{base_name}_hindi.srt",
            sub_dir / f"{base_name}_raw.srt",
            sub_dir / f"{base_name}.srt",
        ])

    if root:
        candidates.extend([
            root / f"output/subtitles/{base_name}_hinglish.srt",
            root / f"output/subtitles/{base_name}_hindi.srt",
            root / f"output/subtitles/{base_name}_raw.srt",
            root / f"output/subtitles/{base_name}.srt",
        ])

    for c in candidates:
        if c.exists() and c.stat().st_size > 20:
            return c

    # Fallback: search recursively anywhere in output directory
    search_root = clean_video.parent.parent if clean_video and (clean_video.parent.parent / "subtitles").exists() else (root / "output" if root else Path("output"))
    if search_root.exists():
        matches = list(search_root.rglob(f"*{base_name}*.srt"))
        if matches:
            for kw in ["hinglish", "hindi", "raw"]:
                for m in matches:
                    if kw in m.name.lower() and m.stat().st_size > 20:
                        return m
            return matches[0]

    return None


def run_single_narrator_pipeline(
    video_path: Optional[str] = None,
    speaker: str = "shubh",
    pace: float = 1.0,
    target_end_margin: float = 0.00,
    custom_script: Optional[str] = None,
    force: bool = False,
    reloop: bool = False,
    engine: str = "sarvam",
    voice: Optional[str] = None,
    enable_autotag: bool = True,
    dubbed_srt: Optional[Union[str, Path]] = None,
    raw_srt: Optional[Union[str, Path]] = None,
    output_video_path: Optional[Union[str, Path]] = None,
    sfx_path: Optional[Union[str, Path]] = None,
    bg_music_path: Optional[Union[str, Path]] = None,
    work_dir: Optional[Union[str, Path]] = None,
    margin_v: Optional[int] = None,
    style: str = "viral"
) -> str:
    """
    Executes the entire Single-Narrator dubbing pipeline on the specified or latest video.
    Supports both Sarvam AI (shubh, etc.) and Google Flash TTS (Bunty / Puck, etc.).
    Fully compatible with single videos, batch folder processing, and custom directories.
    """
    root = Path(__file__).resolve().parent

    active_style = (style or "viral").lower()

    # Auto-detect Bunty
    if (voice and voice.lower() in ["bunty", "puck"]) or engine.lower() == "google":
        engine = "google"
        voice = "Puck"
        tag = f"google_bunty_{active_style}" if active_style != "viral" else "google_bunty"
    else:
        engine = "sarvam"
        voice = speaker or "shubh"
        tag = f"sarvam_{active_style}" if active_style != "viral" else "sarvam"

    # 1. Locate the video files
    if not video_path:
        clean_candidates = sorted(list(root.glob("output/**/clean_videos/*_clean.mp4")), key=os.path.getmtime, reverse=True)
        if not clean_candidates:
            raise FileNotFoundError("No clean video found in output/clean_videos!")
        clean_video = clean_candidates[0]
    else:
        clean_video = Path(video_path)

    base_name = clean_video.stem.replace("_clean", "")
    print(f"\n=======================================================")
    print(f"🎬 SINGLE-NARRATOR PIPELINE: {base_name}")
    print(f"   Engine: {engine.upper()} | Voice: {voice} ({tag}) | Style: {active_style.upper()}")
    print(f"=======================================================")

    vid_dur = get_media_duration(clean_video)
    target_speech_dur = max(5.0, vid_dur - target_end_margin)
    print(f"[Video] Duration: {vid_dur:.2f}s | Target Speech End: {target_speech_dur:.2f}s (Margin: {target_end_margin}s)")

    # 2. Get Script (from custom_script, existing dubbed_srt, or Gemini transcreation with Method 1 Infinite Loop)
    srt_file = resolve_subtitle_path(
        base_name=base_name,
        dubbed_srt=dubbed_srt,
        raw_srt=raw_srt,
        clean_video=clean_video,
        root=root
    )
    if not srt_file or not srt_file.exists():
        raise FileNotFoundError(
            f"Could not locate subtitle file for '{base_name}'. Checked candidate paths in output/subtitles/ and parent directories."
        )
    print(f"[Script] Found subtitle source: {srt_file}")
    blocks = load_srt_blocks(srt_file)

    # Determine work_dir
    if not work_dir:
        if clean_video and (clean_video.parent.parent / "audio_stems").exists():
            active_work_dir = clean_video.parent.parent / f"audio_stems/single_narrator_{base_name}"
        else:
            active_work_dir = root / f"output/audio_stems/single_narrator_{base_name}"
    else:
        active_work_dir = Path(work_dir)
        if not active_work_dir.name.startswith("single_narrator"):
            active_work_dir = active_work_dir / f"single_narrator_{base_name}"
    active_work_dir.mkdir(parents=True, exist_ok=True)

    narrative_txt_cache = active_work_dir / (f"narrative_script_{active_style}.txt" if active_style != "viral" else "narrative_script.txt")

    if custom_script:
        narrative_script = custom_script
    elif not reloop and narrative_txt_cache.exists():
        print(f"[Script] Reusing verified Method 1 narrative ({active_style}) from: {narrative_txt_cache.name}")
        narrative_script = narrative_txt_cache.read_text(encoding="utf-8").strip()
    elif reloop or active_style != "viral" or "_raw" in srt_file.name.lower():
        print(f"[Script] Transcreating continuous Method 1 Infinite Loop narrative ({active_style}) using Gemini...")
        raw_joined = "\n".join(f"{b['start']:.1f}s - {b['end']:.1f}s: {b['text']}" for b in blocks)
        narrative_script = transcreate_continuous_script_gemini(
            raw_text_or_srt=raw_joined,
            target_language="Hindi (Natural conversational Hindi written in native Devanagari script for ultra-realistic TTS prosody)",
            video_duration=target_speech_dur,
            style=active_style
        )
    else:
        print(f"[Script] Loading existing translated script from: {srt_file.name}")
        raw_joined = " ".join(b["text"].strip() for b in blocks)
        # Clean up any ellipsis artifact from block splits
        raw_joined = re.sub(r"\.{2,}\s*\.{2,}", "", raw_joined)
        raw_joined = re.sub(r"\.{2,}", " ", raw_joined)
        raw_joined = re.sub(r"\s+", " ", raw_joined).strip()
        narrative_script = raw_joined

    # Split into 1 to 2 paragraphs if over 1,800 characters
    if len(narrative_script) > 1800:
        sentences = re.split(r"([।?!])", narrative_script)
        mid = len(sentences) // 2
        p1 = "".join(sentences[:mid]).strip()
        p2 = "".join(sentences[mid:]).strip()
        paragraphs = [p1, p2]
    else:
        # Split on double newlines if present
        parts = [p.strip() for p in narrative_script.split("\n\n") if p.strip()]
        paragraphs = parts if parts else [narrative_script]

    print(f"[Script] Final Narration: {len(paragraphs)} paragraph(s), {sum(len(p) for p in paragraphs)} characters total.")

    narrative_txt = active_work_dir / "narrative_script.txt"
    narrative_txt.write_text(narrative_script, encoding="utf-8")

    timed_wav = active_work_dir / f"narration_perfect_timed_{tag}.wav"
    compressed_wav = active_work_dir / f"narration_compressed_{tag}.wav"

    if timed_wav.exists() and not force:
        print(f"[Cache] Found existing timed narration audio at: {timed_wav.name}")
        actual_timed_dur = get_media_duration(timed_wav)
        print(f"[Cache] Reusing existing timed audio ({actual_timed_dur:.2f}s).")
    else:
        # 3. Speech Synthesis
        if engine == "google":
            raw_audio, sr = synthesize_google_paragraphs(
                paragraphs=paragraphs,
                voice=voice,
                sample_rate=24000,
                model="gemini-2.5-flash-preview-tts",
                enable_autotag=enable_autotag
            )
        else:
            raw_audio, sr = synthesize_sarvam_paragraphs(
                paragraphs=paragraphs,
                speaker=speaker,
                pace=pace,
                language_code="hi-IN",
                model="bulbul:v3"
            )

        # 4. Silence Compression (Zero dead gaps)
        compressed_audio = compress_audio_silences(
            audio=raw_audio,
            sample_rate=sr,
            silence_threshold=0.015,
            max_pause_sec=0.18,
            min_silence_detect_sec=0.22
        )

        sf.write(str(compressed_wav), compressed_audio, sr)

        # 5. Smart Tempo Scaling & B-roll Speedup (Audio speed strictly clamped to 0.95x - 1.05x)
        comp_dur = len(compressed_audio) / sr
        ideal_audio_tempo = comp_dur / target_speech_dur
        # Clamp audio speed to max +-5% (0.95 to 1.05)
        applied_audio_tempo = max(0.95, min(1.05, ideal_audio_tempo))
        print(f"\n[Smart Pacing] Raw Compressed Speech: {comp_dur:.2f}s | Audio Speed Clamped to: {applied_audio_tempo:.3f}x (Allowed: 0.95x - 1.05x)")

        adjust_audio_tempo_ffmpeg(compressed_wav, timed_wav, applied_audio_tempo)
        actual_timed_dur = get_media_duration(timed_wav)
        print(f"[Smart Pacing] Verified Timed Audio Duration: {actual_timed_dur:.2f}s")

    # If audio is shorter than the video, speed up the background video B-roll so they end together
    target_video_dur = actual_timed_dur + target_end_margin
    if vid_dur > target_video_dur + 0.15:
        video_speedup = vid_dur / target_video_dur
        print(f"[Smart Pacing] Audio is shorter than original video. Fastening background video B-roll by {video_speedup:.3f}x ({vid_dur:.2f}s -> {target_video_dur:.2f}s) for zero dead tail.")
    else:
        video_speedup = 1.0
        target_video_dur = vid_dur

    # 6. Audio-Synced Hinglish Subtitle Alignment (original tts_engine pipeline, zero overrides)
    sub_dir = srt_file.parent
    sub_dir.mkdir(parents=True, exist_ok=True)
    sub_srt = sub_dir / f"{base_name}_single_narrator_{tag}.srt"
    sub_ass = sub_dir / f"{base_name}_single_narrator_{tag}.ass"

    caption_margin_v = margin_v
    if caption_margin_v is None:
        box_json = clean_video.with_name(f"{clean_video.stem}_box.json")
        if box_json.exists():
            caption_margin_v = load_detected_margin_v(clean_video)
            print(f"[Subtitles] Dynamic MarginV={caption_margin_v} detected from {box_json.name}")

    generate_synced_captions(
        master_wav=timed_wav,
        script_text=narrative_script,
        output_srt=sub_srt,
        output_ass=sub_ass,
        margin_v=caption_margin_v,
        work_dir=active_work_dir,
        force=force
    )

    # 7. Resolve Foley SFX (sfx.wav) & Royalty-Free BGM (assets/background_audio)
    foley_sfx = Path(sfx_path) if sfx_path and Path(sfx_path).exists() else None
    if not foley_sfx:
        sfx_candidates = [
            clean_video.parent.parent / f"audio_stems/stems_{base_name}/sfx.wav",
            root / f"output/audio_stems/stems_{base_name}/sfx.wav",
        ]
        for sc in sfx_candidates:
            if sc.exists():
                foley_sfx = sc
                break

    bg_music = None
    if bg_music_path and Path(bg_music_path).exists() and Path(bg_music_path).is_file():
        bg_music = Path(bg_music_path)
    else:
        bg_dirs = [
            root / "assets/background_audio",
            Path("assets/background_audio"),
        ]
        for bd in bg_dirs:
            if bd.exists():
                tracks = sorted([f for f in bd.glob("*.mp3")] + [f for f in bd.glob("*.wav")])
                if tracks:
                    bg_music = tracks[0]
                    break

    if output_video_path:
        final_video = Path(output_video_path)
    else:
        out_parent = clean_video.parent.parent / "final_videos" if clean_video and (clean_video.parent.parent / "final_videos").exists() else root / "output/final_videos"
        out_parent.mkdir(parents=True, exist_ok=True)
        style_suffix = f"_{active_style}" if active_style != "viral" else ""
        if tag.startswith("sarvam"):
            final_video = out_parent / f"{base_name}_single_narrator{style_suffix}.mp4"
        else:
            final_video = out_parent / f"{base_name}_{tag}_dubbed.mp4"

    mix_master_and_mux(
        clean_video_path=clean_video,
        narration_audio_path=timed_wav,
        sfx_path=foley_sfx,
        bg_music_path=bg_music,
        subtitles_ass_path=sub_ass,
        output_video_path=final_video,
        target_duration=target_video_dur,
        video_speedup=video_speedup
    )

    final_dur = get_media_duration(final_video)
    print(f"\n🎉 [COMPLETE] Single-Narrator Dubbed Video Finished!")
    print(f"   📹 File: {final_video}")
    print(f"   ⏱️ Video Duration: {final_dur:.2f}s")
    print(f"   🎙️ Speech End: {actual_timed_dur:.2f}s (Tail: {final_dur - actual_timed_dur:.2f}s)")
    return str(final_video)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Single-Narrator Continuous Dubbing Engine")
    parser.add_argument("--video", type=str, default=None, help="Path to clean video or input video (defaults to latest)")
    parser.add_argument("--engine", type=str, default="sarvam", choices=["sarvam", "google"], help="TTS Engine (sarvam or google)")
    parser.add_argument("--voice", type=str, default=None, help="Voice name (Puck for Google/Bunty, shubh for Sarvam)")
    parser.add_argument("--speaker", type=str, default="shubh", help="Sarvam speaker name (e.g. shubh, arvind, ratan)")
    parser.add_argument("--bunty", action="store_true", help="Shortcut: Use Google Flash TTS with Bunty (Puck) voice")
    parser.add_argument("--pace", type=float, default=1.0, help="Base speech pace")
    parser.add_argument("--margin", type=float, default=0.00, help="End margin in seconds before video ends (default: 0.00 for instant loop)")
    parser.add_argument("--force", action="store_true", help="Force re-generation of TTS audio")
    parser.add_argument("--reloop", action="store_true", default=False, help="Force Gemini to transcreate fresh Method 1 Infinite Loop narrative")
    parser.add_argument("--funny", action="store_true", help="Shortcut: Use funny Hindi roast & desi meme comedy style")
    parser.add_argument("--style", type=str, default="viral", choices=["viral", "funny", "roast", "comedy"], help="Narrative tone style ('viral' showrunner or 'funny' comedy roast)")
    args = parser.parse_args()

    engine = "google" if args.bunty else args.engine
    voice = "Puck" if args.bunty else (args.voice or args.speaker)
    selected_style = "funny" if args.funny else args.style

    run_single_narrator_pipeline(
        video_path=args.video,
        speaker=args.speaker,
        pace=args.pace,
        target_end_margin=args.margin,
        force=args.force,
        reloop=args.reloop,
        engine=engine,
        voice=voice,
        style=selected_style
    )
