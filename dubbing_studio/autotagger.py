#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dubbing_studio/autotagger.py
============================
Automated Audio & Speech Autotagger for Google Gemini TTS.
Replicates Google AI Studio's "Autotag" feature:
  - Injects contextual scene delivery styles into speech_metadata.style
  - Adds inline vocal performance tags (<laugh>, <chuckle>, <short pause>, <gasp>, <sigh>)
  - Tailored specifically for viral Reels/Shorts storytelling dynamics.
"""

import re
from typing import List, Dict, Any, Optional
from google.genai import types


def autotag_subtitle_block(
    text: str,
    index: int,
    total_blocks: int,
    tone: str = "viral_shorts"
) -> types.Part:
    """
    Automatically analyzes a subtitle line and returns a types.Part with
    inline vocal tags and expressive speech_metadata.style, exactly like
    Google AI Studio's 'Autotag' feature.
    """
    tagged_text = text.strip()
    style = "energetic, engaging, conversational"

    # Block 1 / Opening Hook
    if index == 1:
        style = "excited, punchy, high-energy viral shorts hook"
        if not re.search(r"<laugh>|<chuckle>|<gasp>", tagged_text):
            # If the hook is mischievous or surprising, insert an organic vocal cue
            if any(w in tagged_text.lower() for w in ["किक", "लात", "दबंग", "चोरी", "पकड़", "भागो"]):
                # Add a subtle chuckle after the hook exclamation
                if "!" in tagged_text:
                    tagged_text = tagged_text.replace("!", "! <laugh>", 1)
                elif "?" in tagged_text:
                    tagged_text = tagged_text.replace("?", "? <gasp>", 1)

    # Final Block / Triumphant Climax with CTA
    elif index == total_blocks:
        style = "triumphant, enthusiastic, warm YouTube creator ending with subscribe call to action"
        if "लो" in tagged_text and not re.search(r"<laugh>|<sigh>", tagged_text):
            tagged_text = re.sub(r"(लो[,!]?)", r"\1 <laugh>", tagged_text, count=1)

    # Middle / Action & Instruction
    else:
        # Warnings, secrets, educational hacks
        if any(w in tagged_text for w in ["ताकि", "क्रैक ना हो", "ध्यान रहे", "फटे नहीं", "सीक्रेट", "टिप"]):
            style = "informative, intriguing, educational advisory with sharp emphasis"
            if "ताकि" in tagged_text:
                tagged_text = tagged_text.replace("ताकि", "<short pause> ताकि", 1)

        # Tasting, sensory, delicious transformation
        elif any(w in tagged_text for w in ["क्रिस्टल", "ट्रांसलूसेंट", "हनी", "खुशबूदार", "टेस्टी", "सोने जैसी"]):
            style = "mouth-watering, satisfied, delighted, sensory enthusiasm"

        # Action / Technique / Process
        elif any(w in tagged_text for w in ["स्टीम", "हीट", "पिघला", "धोकर", "जार", "लेयर"]):
            style = "crisp, fast-paced, engaging action narration"

        else:
            style = "lively, confident, conversational storyteller"

    # Clean double spaces or invalid tag spacing
    tagged_text = re.sub(r"\s+", " ", tagged_text).strip()

    return types.Part(
        text=tagged_text,
        speech_metadata=types.SpeechMetadata(style=style)
    )


def autotag_srt_blocks(blocks: List[Dict[str, Any]], tone: str = "viral_shorts") -> List[Dict[str, Any]]:
    """
    Applies automatic audio tagging across all blocks in an SRT.
    Adds 'part' and 'tagged_text' and 'style' to each block dictionary.
    """
    total = len(blocks)
    for b in blocks:
        idx = b.get("index", 1)
        part = autotag_subtitle_block(b["text"], index=idx, total_blocks=total, tone=tone)
        b["part"] = part
        b["tagged_text"] = part.text
        b["style"] = part.speech_metadata.style if part.speech_metadata else ""
    return blocks


def autotag_narrative_paragraphs(paragraphs: List[str]) -> List[str]:
    """
    Autotags continuous narrative paragraphs for Google Gemini Flash TTS.
    Injects inline performance cues (<short pause>, <gasp>, <chuckle>)
    to maximize human realism, retention, and viral pacing.
    """
    tagged = []
    for idx, p in enumerate(paragraphs):
        text = p.strip()
        # Ensure natural pause on ellipses if not already tagged
        text = re.sub(r"\.\.\.(?!\s*<short pause>)", "... <short pause>", text)
        
        # Add subtle gasp before rhetorical questions about surprising mysteries
        text = re.sub(r"(banaya kaise gaya\?|kaise hua\?|aakhir ye hua kaise\?)", r"<gasp> \1", text, flags=re.IGNORECASE)
        
        # Clean up multiple consecutive pauses/spaces
        text = re.sub(r"(<short pause>\s*){2,}", "<short pause> ", text)
        text = re.sub(r"\s+", " ", text).strip()
        tagged.append(text)
    return tagged
