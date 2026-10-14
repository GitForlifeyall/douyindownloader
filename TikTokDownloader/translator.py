#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TikTokDownloader/translator.py
==============================
Refactored subtitle translation & dubbing module.
Delegates to srt_dub_translator with backward-compatible functions and classes.
"""

import os
import sys
from pathlib import Path
from typing import List, Dict, Optional, Union

# Ensure parent directory is in path
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from srt_dub_translator import (
    DEFAULT_GEMINI_KEYS,
    DEFAULT_TARGET_LANGUAGE,
    SYSTEM_PROMPT,
    parse_time,
    format_time,
    parse_srt as load_srt,
    inject_constraints_into_srt,
    clean_and_verify_srt,
    SRTDubTranslator,
    translate_and_rewrite_srt,
)


class GeminiTranslator:
    """Backward-compatible wrapper around SRTDubTranslator."""

    def __init__(
        self,
        api_keys: Optional[List[str]] = None,
        model: str = "gemini-3.8-flash"
    ):
        self.translator = SRTDubTranslator(api_keys=api_keys, model=model)
        self.api_keys = self.translator.api_keys
        self.model = model

    def get_current_key(self) -> str:
        return self.translator.get_current_key()

    def rotate_key(self):
        self.translator.rotate_key()

    def call_gemini(self, prompt: str, system_instruction: str) -> str:
        return self.translator._call_gemini_with_retry(
            prompt=prompt,
            system_instruction=system_instruction,
            temperature=0.4
        )

    def translate_srt(
        self,
        input_srt: str,
        target_language: str = DEFAULT_TARGET_LANGUAGE,
        batch_size: int = 35
    ) -> str:
        verified_srt, _ = self.translator.translate_and_rewrite_srt(
            srt_input=input_srt,
            target_language=target_language,
            batch_size=batch_size,
            temperature=0.4
        )
        return verified_srt


if __name__ == "__main__":
    import argparse

    default_test_srt = os.environ.get("DUB_SRT_FILE", "Volume/Download/sample.srt")
    
    parser = argparse.ArgumentParser(description="Translate and adapt SRT for viral dubbing")
    parser.add_argument("srt_file", nargs="?", default=default_test_srt, help="Path to input SRT file")
    parser.add_argument("target_lang", nargs="?", default=DEFAULT_TARGET_LANGUAGE, help="Target language")
    parser.add_argument("--model", default="gemini-3.8-flash", help="Gemini model name")
    parser.add_argument("--batch-size", type=int, default=35, help="Batch size for long videos")
    args = parser.parse_args()

    srt_path = Path(args.srt_file)
    if not srt_path.exists():
        print(f"Error: SRT file does not exist: {srt_path}")
        sys.exit(1)

    translator = GeminiTranslator(model=args.model)
    out_srt = translator.translate_srt(str(srt_path), target_language=args.target_lang, batch_size=args.batch_size)

    out_path = srt_path.parent / f"{srt_path.stem}_dubbed.srt"
    out_path.write_text(out_srt, encoding="utf-8")
    print(f"\n[Success] Translated SRT successfully saved to: {out_path}")
