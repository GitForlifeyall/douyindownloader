#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
srt_dub_translator.py
======================
Automated SRT Translation & Dubbing Pipeline using Google GenAI SDK.
Transcreates SRT subtitles into high-retention viral voiceover scripts
with strict time-fitting (isochrony), constraint injection, and format validation.
"""

import os
import sys
import re
import time
import logging
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Union, Any

from google import genai
from google.genai import types

# Configure UTF-8 for Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Setup Logger
logger = logging.getLogger("srt_dub_translator")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Default Gemini API key pool - load from environment only.
# Set GEMINI_API_KEY or GEMINI_API_KEYS (comma-separated). Never hardcode keys.
DEFAULT_GEMINI_KEYS = [
    k.strip()
    for k in os.environ.get("GEMINI_API_KEYS", "").split(",")
    if k.strip()
]

DEFAULT_TARGET_LANGUAGE = "Hindi (Conversational Bollywood/Hinglish in Devanagari script)"

# Upgraded SYSTEM_PROMPT for viral retention & dubbing
SYSTEM_PROMPT = (
    "You are an elite viral YouTube Shorts & Movie Recap Showrunner, Retention Director, and Dubbing Adapter for {target_language}.\n"
    "Your job is NOT to do a dry, literal translation. Your job is to **transcreate** timestamped subtitle blocks into an addictive, high-retention voiceover script that glues viewers to the screen while strictly fitting each scene's time window.\n\n"
    "### 1. HIGH-RETENTION & VIRAL HOOK RULES:\n"
    "- **BLOCK 1 & 2 (THE 3-SECOND SCROLL-STOPPER HOOK):** Never start with boring setup or names. Rewrite Block 1 so it immediately triggers shock, danger, or an intense curiosity gap while matching what is visually on screen (e.g., instead of 'This man is walking into a cave', write 'इस गुफा में कदम रखना इस आदमी की आख़िरी गलती थी—').\n"
    "- **MICRO-CLIFFHANGERS (OPEN LOOPS):** Every 3 to 4 blocks, end the line with a forward-driving connector or suspense pivot ('लेकन तभी—', 'पर उसे कहाँ पता था कि—', 'और अगले ही पल जो हुआ—') so the viewer's brain cannot swipe away.\n"
    "- **ZERO FLUFF & ACTIVE TENSION:** Cut all passive descriptions. Use punchy, visceral verbs. Make every sentence feel like a ticking clock.\n"
    "- **THE SEAMLESS LOOP (FINAL BLOCK):** Phrase the very last subtitle block so its tone or final words flow naturally back into Block 1 to boost rewatch retention.\n\n"
    "### 2. CRITICAL DUBBING TIME-FITTING RULES (ISOCHRONY):\n"
    "- Each input block begins with a constraint tag: `[Block #N | Dur: X.Xs | Max: Y words]`.\n"
    "- Your adapted line for that block **MUST NOT exceed Y words**.\n"
    "- **REMOVE THE TAG:** Never include `[Block #N | Dur: ... | Max: ...]` in your final output. Output only the clean spoken dialogue under the timestamp.\n"
    "- Compress long original sentences into their hardest-hitting emotional core so the voice actor finishes speaking cleanly before the scene cut.\n\n"
    "### 3. LANGUAGE & TTS VOICE DELIVERY RULES ({target_language}):\n"
    "- If {target_language} is Hindi: Write in **Devanagari script**, but use **natural, everyday spoken Hinglish / Bollywood street-level Hindi** that young Indian viewers actually speak.\n"
    "- **BANNED FORMAL WORDS:** NEVER use textbook Sanskritized Hindi (use 'हॉस्पिटल' not 'चिकित्सालय', 'पुलिस' not 'आरक्षी', 'शॉक' not 'अचंभित', 'प्लान' not 'योजना', 'दिमाग़' not 'मस्तिष्क', 'सीक्रेट' not 'रहस्यमय').\n"
    "- **TTS PAUSES & EMPHASIS:** Use em-dashes (`—`), ellipses (`...`), and commas to force the AI voiceover (ElevenLabs/Sarvam) to take dramatic breaths and speed up during action beats. Write numbers out in words.\n\n"
    "### 4. STRICT SRT FORMAT INTEGRITY:\n"
    "- NEVER merge, split, reorder, or delete subtitle blocks.\n"
    "- Output the EXACT same number of blocks with the EXACT original timestamps.\n"
    "- Output raw, valid SRT text ONLY. No markdown backticks (```), no explanations, and no commentary."
)


# ==============================================================================
# Helper Functions: Timestamp parsing and formatting
# ==============================================================================
def parse_time(time_str: str) -> float:
    """Convert SRT timestamp (HH:MM:SS,mmm or HH:MM:SS.mmm) to total seconds."""
    time_str = time_str.strip().replace(",", ".")
    parts = time_str.split(":")
    if len(parts) == 3:
        return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return float(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


def format_time(seconds: float) -> str:
    """Convert total seconds to standard SRT timestamp format (HH:MM:SS,mmm)."""
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


# ==============================================================================
# 1. Pre-Process SRT: inject_constraints_into_srt
# ==============================================================================
def parse_srt(srt_input: Union[str, Path]) -> List[Dict[str, Any]]:
    """
    Parse any standard .srt file or raw SRT string into structured blocks.
    Returns list of dicts with:
      - index: int
      - start_sec: float
      - end_sec: float
      - start_str: str
      - end_str: str
      - timestamp: str
      - text: str
    """
    if isinstance(srt_input, Path) or (isinstance(srt_input, str) and (os.path.exists(srt_input) or "\n" not in srt_input)):
        content = Path(srt_input).read_text(encoding="utf-8")
    else:
        content = str(srt_input)

    # Normalize newlines
    content = content.replace("\r\n", "\n").replace("\r", "\n").strip()

    # Match SRT block pattern: Index, Timestamps, Subtitle text
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
        idx = int(idx_str)
        # Clean up multi-line text into a single cohesive line
        clean_text = " ".join(text_str.strip().split())
        start_sec = parse_time(start_str)
        end_sec = parse_time(end_str)

        # Standardize timestamp string representation
        std_start = format_time(start_sec)
        std_end = format_time(end_sec)
        timestamp_line = f"{std_start} --> {std_end}"

        blocks.append({
            "index": idx,
            "start_sec": start_sec,
            "end_sec": end_sec,
            "start_str": std_start,
            "end_str": std_end,
            "timestamp": timestamp_line,
            "text": clean_text
        })

    # Fallback parser if regex missed blocks due to irregular formatting
    if not blocks and content:
        raw_chunks = [c.strip() for c in content.split("\n\n") if c.strip()]
        for i, chunk in enumerate(raw_chunks, 1):
            lines = [line.strip() for line in chunk.split("\n") if line.strip()]
            if len(lines) >= 2:
                ts_match = re.search(r"(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})", chunk)
                if ts_match:
                    s_str, e_str = ts_match.group(1), ts_match.group(2)
                    s_sec, e_sec = parse_time(s_str), parse_time(e_str)
                    text_lines = [l for l in lines if "-->" not in l and not l.isdigit()]
                    c_text = " ".join(" ".join(text_lines).split())
                    blocks.append({
                        "index": i,
                        "start_sec": s_sec,
                        "end_sec": e_sec,
                        "start_str": format_time(s_sec),
                        "end_str": format_time(e_sec),
                        "timestamp": f"{format_time(s_sec)} --> {format_time(e_sec)}",
                        "text": c_text
                    })

    return blocks


def inject_constraints_into_srt(srt_input: Union[str, Path, List[Dict[str, Any]]]) -> Tuple[List[Dict[str, Any]], str]:
    """
    1. Parse any standard .srt file into structured blocks:
       (index, timestamp, start_sec, end_sec, duration, text)
    2. Calculate duration = max(0.5, round(end_sec - start_sec, 1))
    3. Calculate max_words = max(2, round(duration * 2.5))
    4. Prepend [Block #{index} | Dur: {duration}s | Max: {max_words} words] to the text
       of each block so the LLM does not have to do mental math.

    Returns:
      (processed_blocks, constrained_srt_string)
    """
    if isinstance(srt_input, list):
        # Already structured blocks
        blocks = [dict(b) for b in srt_input]
    else:
        blocks = parse_srt(srt_input)

    srt_output_lines = []

    for b in blocks:
        # Calculate duration and max_words per architectural spec
        duration = max(0.5, round(b["end_sec"] - b["start_sec"], 1))
        max_words = max(2, round(duration * 2.5))

        b["duration"] = duration
        b["max_words"] = max_words

        # Constraint tag
        tag = f"[Block #{b['index']} | Dur: {duration}s | Max: {max_words} words]"
        constrained_text = f"{tag} {b['text']}"
        b["constrained_text"] = constrained_text

        # Format constrained SRT block
        srt_output_lines.append(f"{b['index']}\n{b['timestamp']}\n{constrained_text}\n")

    constrained_srt_str = "\n".join(srt_output_lines).strip() + "\n"
    return blocks, constrained_srt_str


# ==============================================================================
# 3. Post-Process & Validation: clean_and_verify_srt
# ==============================================================================
def clean_and_verify_srt(
    raw_translated_srt: str,
    original_blocks: List[Dict[str, Any]]
) -> Tuple[str, Dict[str, Any]]:
    """
    Post-process and validate Gemini output:
    1. Strip accidental [Block ... | Dur: ... | Max: ...] tags or markdown fences (```srt).
    2. Verify exact number of blocks and identical timestamps as input SRT.
       If any timestamp drifted, overwrite with original input timestamps from memory.
    3. Log warning for any block where word count > max_words * 1.25 for downstream
       TTS atempo speed compression.

    Returns:
      (clean_srt_string, validation_report)
    """
    # 1. Clean markdown code fences and wrappers
    cleaned = raw_translated_srt.strip()
    cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\s*\n?", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned, flags=re.MULTILINE)
    cleaned = cleaned.replace("```srt", "").replace("```", "").strip()

    # 2. Strip any injected constraint tags that LLM may have echoed
    cleaned = re.sub(
        r"\[\s*Block\s*#?\d+\s*\|\s*Dur:\s*[\d\.]+s?\s*\|\s*Max:\s*\d+\s*words?\s*\]\s*",
        "",
        cleaned,
        flags=re.IGNORECASE
    )

    # Parse translated blocks from the cleaned text
    translated_blocks = parse_srt(cleaned)

    # Fallback split if standard parse returned fewer blocks than original
    if len(translated_blocks) != len(original_blocks):
        # Try chunk splitting by double newline
        chunks = [c.strip() for c in cleaned.split("\n\n") if c.strip()]
        temp_blocks = []
        for i, chk in enumerate(chunks, 1):
            lines = [l.strip() for l in chk.split("\n") if l.strip()]
            if not lines:
                continue
            # Check if first line is index or timestamp
            t_text_lines = []
            for l in lines:
                if l.isdigit() and len(l) <= 4:
                    continue
                if "-->" in l:
                    continue
                t_text_lines.append(l)
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
        msg = f"Block count mismatch! Original has {num_orig} blocks, but model returned {num_trans} blocks. Reconciling..."
        logger.warning(msg)
        warnings.append(msg)

    # Reconcile, enforce original timestamps, and validate word count
    final_srt_blocks = []
    for i, orig_b in enumerate(original_blocks):
        orig_idx = orig_b["index"]
        orig_ts = orig_b["timestamp"]
        max_words = orig_b["max_words"]
        threshold = max_words * 1.25

        # Get translated text
        if i < len(translated_blocks):
            trans_text = translated_blocks[i]["text"]
        else:
            # Fallback to original text if model dropped the last block
            trans_text = orig_b["text"]
            warnings.append(f"Block #{orig_idx} missing from output; restored fallback text.")

        # Clean any remaining tags or stray symbols
        trans_text = re.sub(r"\[\s*Block\s*#?\d+.*?\]", "", trans_text).strip()
        trans_text = " ".join(trans_text.split())

        # Word count calculation (whitespace-separated words)
        words = [w for w in trans_text.split() if w.strip()]
        word_count = len(words)

        is_oversized = word_count > threshold
        if is_oversized:
            speed_factor = round(word_count / max_words, 2)
            warn_msg = (
                f"Block #{orig_idx} word count ({word_count}) exceeds threshold {threshold:.1f} "
                f"(max_words={max_words}). Downstream TTS 'atempo' speed compression advised: ~{speed_factor}x."
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

        # Assemble SRT block with verified original index and original timestamp from memory
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


# ==============================================================================
# 2. Gemini Translation Layer: SRTDubTranslator
# ==============================================================================
class SRTDubTranslator:
    """
    Automated Dubbing Translator using Google GenAI SDK.
    Supports API key rotation, error handling, batching for long videos,
    read-only context continuity, and validation.
    """

    def __init__(
        self,
        api_keys: Optional[List[str]] = None,
        model: str = "gemini-3.8-flash",
        system_prompt_template: str = SYSTEM_PROMPT
    ):
        # Keys from explicit args or GEMINI_API_KEY / GEMINI_API_KEYS env only.
        env_keys = [
            k.strip()
            for k in os.environ.get("GEMINI_API_KEYS", "").split(",")
            if k.strip()
        ]
        env_key = os.environ.get("GEMINI_API_KEY")
        if env_key and env_key not in env_keys:
            env_keys.insert(0, env_key)
        if api_keys:
            self.api_keys = list(api_keys)
        elif env_keys:
            self.api_keys = env_keys
        else:
            self.api_keys = list(DEFAULT_GEMINI_KEYS)

        if not self.api_keys:
            raise ValueError(
                "No Gemini API keys configured. Set GEMINI_API_KEY or "
                "GEMINI_API_KEYS env var, or pass api_keys=[...]."
            )

        self.current_key_idx = 0
        self.model = model
        self.system_prompt_template = system_prompt_template
        # Models to try in case of temporary 503 or quota
        self.fallback_models = ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3-flash-preview"]
        if self.model not in self.fallback_models:
            self.fallback_models.insert(0, self.model)

    def get_current_key(self) -> str:
        return self.api_keys[self.current_key_idx % len(self.api_keys)]

    def rotate_key(self):
        self.current_key_idx = (self.current_key_idx + 1) % len(self.api_keys)
        logger.info(f"Rotated to API key #{self.current_key_idx + 1} of {len(self.api_keys)}")

    def _call_gemini_with_retry(
        self,
        prompt: str,
        system_instruction: str,
        temperature: float = 0.4
    ) -> str:
        """Call Gemini generate_content with types.GenerateContentConfig and key rotation."""
        max_attempts = len(self.api_keys) * len(self.fallback_models) * 2
        models_to_try = [self.model] + [m for m in self.fallback_models if m != self.model]

        for attempt in range(max_attempts):
            api_key = self.get_current_key()
            current_model = models_to_try[(attempt // len(self.api_keys)) % len(models_to_try)]

            try:
                client = genai.Client(api_key=api_key)
                config = types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=temperature
                )
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
                    f"Attempt {attempt + 1}: [{current_model}] Key #{self.current_key_idx + 1} failed: {err_str[:120]}"
                )
                # Rotate key on 429, 403, or quota issues
                self.rotate_key()
                time.sleep(1.2)

        raise RuntimeError("All Gemini API keys and models exhausted without successful response.")

    def translate_and_rewrite_srt(
        self,
        srt_input: Union[str, Path, List[Dict[str, Any]]],
        target_language: str = DEFAULT_TARGET_LANGUAGE,
        batch_size: int = 35,
        temperature: float = 0.4
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Main pipeline method:
        1. Inject constraints into SRT blocks.
        2. Format system prompt with target_language.
        3. If short-form (<= batch_size blocks), send full SRT in 1 call for full story arc.
           If long-form (> batch_size blocks), chunk into 35 blocks per call, passing
           the last 2 translated blocks as read-only context for narrative & gender consistency.
        4. Clean, verify timestamps, and validate word count thresholds.
        """
        # Step 1: Pre-process & inject constraints
        original_blocks, _ = inject_constraints_into_srt(srt_input)
        total_blocks = len(original_blocks)

        logger.info(f"Loaded {total_blocks} subtitle blocks for transcreation into '{target_language}'.")

        # Step 2: Build formatted system prompt
        system_instruction = self.system_prompt_template.format(target_language=target_language)

        translated_blocks_accumulator: List[str] = []
        translated_objects_history: List[Dict[str, Any]] = []

        # Step 3: Handle single-pass vs batched execution
        if total_blocks <= batch_size:
            logger.info(f"Short-form video ({total_blocks} <= {batch_size} blocks): Sending full SRT in single call for cohesive hook & loop.")
            _, constrained_srt = inject_constraints_into_srt(original_blocks)
            prompt = (
                f"Transcreate the following {total_blocks} timestamped subtitle blocks into {target_language}.\n"
                f"Strictly adhere to the hook, micro-cliffhanger, word count limits, and SRT formatting rules:\n\n"
                f"{constrained_srt}"
            )
            raw_response = self._call_gemini_with_retry(prompt, system_instruction, temperature=temperature)
            translated_blocks_accumulator.append(raw_response)

        else:
            logger.info(f"Long-form recap ({total_blocks} blocks): Chunking into batches of {batch_size} blocks with rolling context.")

            for start_idx in range(0, total_blocks, batch_size):
                chunk = original_blocks[start_idx : start_idx + batch_size]
                chunk_range_str = f"Blocks {chunk[0]['index']} to {chunk[-1]['index']}"
                logger.info(f"Translating chunk: {chunk_range_str} ({len(chunk)} blocks)...")

                _, chunk_constrained_srt = inject_constraints_into_srt(chunk)

                # Context from previous translated chunk (last 2 blocks)
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

                # Pre-clean chunk to parse and record into history for next iteration's context
                cleaned_chunk = re.sub(r"^```(?:srt)?\s*\n", "", chunk_raw_resp.strip(), flags=re.IGNORECASE)
                cleaned_chunk = re.sub(r"\n```\s*$", "", cleaned_chunk).strip()
                cleaned_chunk = re.sub(r"\[\s*Block\s*#?\d+.*?\]\s*", "", cleaned_chunk, flags=re.IGNORECASE)

                parsed_chunk_blocks = parse_srt(cleaned_chunk)
                if parsed_chunk_blocks:
                    translated_objects_history.extend(parsed_chunk_blocks)
                else:
                    # Fallback line parse
                    for b_orig in chunk:
                        translated_objects_history.append({"index": b_orig["index"], "text": b_orig["text"]})

                translated_blocks_accumulator.append(chunk_raw_resp)

        combined_raw_translated = "\n\n".join(translated_blocks_accumulator)

        # Step 4: Post-Process & Validation
        verified_srt, validation_report = clean_and_verify_srt(combined_raw_translated, original_blocks)

        logger.info(
            f"Transcreation complete! {validation_report['total_blocks']} blocks processed. "
            f"Oversized warnings: {validation_report['oversized_count']}."
        )

        return verified_srt, validation_report


# ==============================================================================
# Functional API wrappers matching Architectural Requirements
# ==============================================================================
def translate_and_rewrite_srt(
    srt_input: Union[str, Path, List[Dict[str, Any]]],
    target_language: str = DEFAULT_TARGET_LANGUAGE,
    api_key: Optional[str] = None,
    model: str = "gemini-3.8-flash",
    batch_size: int = 35,
    temperature: float = 0.4
) -> str:
    """
    Direct function interface matching Architectural Requirement #2:
    - Pre-processes input with inject_constraints_into_srt
    - Calls Gemini with types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, temperature=0.4)
    - Validates with clean_and_verify_srt
    - Returns verified SRT string.
    """
    keys = [api_key] if api_key else None
    translator = SRTDubTranslator(api_keys=keys, model=model)
    verified_srt, _ = translator.translate_and_rewrite_srt(
        srt_input=srt_input,
        target_language=target_language,
        batch_size=batch_size,
        temperature=temperature
    )
    return verified_srt


# ==============================================================================
# CLI Entry Point
# ==============================================================================
def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Automated SRT Dubbing & Translation Pipeline (Gemini SDK)"
    )
    parser.add_argument("input_srt", help="Path to input .srt file")
    parser.add_argument("-o", "--output", help="Path to output translated .srt file (optional)")
    parser.add_argument(
        "-l", "--lang",
        default=DEFAULT_TARGET_LANGUAGE,
        help="Target language / style (default: Hindi conversational Hinglish)"
    )
    parser.add_argument(
        "-m", "--model",
        default="gemini-3.8-flash",
        help="Gemini model name (default: gemini-3.8-flash)"
    )
    parser.add_argument(
        "-b", "--batch-size",
        type=int,
        default=35,
        help="Max subtitle blocks per Gemini call (default: 35)"
    )
    parser.add_argument(
        "-t", "--temperature",
        type=float,
        default=0.4,
        help="Model temperature (default: 0.4)"
    )

    args = parser.parse_args()

    input_path = Path(args.input_srt)
    if not input_path.exists():
        print(f"Error: Input SRT file not found: {input_path}")
        sys.exit(1)

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.parent / f"{input_path.stem}_dubbed.srt"

    translator = SRTDubTranslator(model=args.model)
    verified_srt, report = translator.translate_and_rewrite_srt(
        srt_input=input_path,
        target_language=args.lang,
        batch_size=args.batch_size,
        temperature=args.temperature
    )

    output_path.write_text(verified_srt, encoding="utf-8")
    print(f"\n==========================================")
    print(f"Successfully generated dubbed SRT!")
    print(f"Output File: {output_path}")
    print(f"Total Blocks: {report['total_blocks']}")
    print(f"Oversized Blocks (> 1.25x limit): {report['oversized_count']}")
    if report["oversized_blocks"]:
        print("Blocks flagged for TTS compression:")
        for ob in report["oversized_blocks"]:
            print(f"  - Block #{ob['index']}: {ob['word_count']} words (Max: {ob['max_words']}, Atempo: ~{ob['recommended_atempo']}x)")
    print(f"==========================================\n")


if __name__ == "__main__":
    main()
