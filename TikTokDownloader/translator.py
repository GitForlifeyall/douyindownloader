#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TikTokDownloader/translator.py
==============================
Bridge to dubbing_studio translator.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dubbing_studio.translator import (
    SRTDubTranslator,
    translate_and_rewrite_srt,
    parse_srt as load_srt,
    parse_time,
    format_time,
    inject_constraints_into_srt,
    clean_and_verify_srt,
    SYSTEM_PROMPT,
    DEFAULT_TARGET_LANGUAGE,
)


class GeminiTranslator:
    """Backward-compatible wrapper."""
    def __init__(self, api_keys=None, model="gemini-3.8-flash"):
        self.translator = SRTDubTranslator(api_keys=api_keys, model=model)

    def translate_srt(self, input_srt: str, target_language: str = DEFAULT_TARGET_LANGUAGE, batch_size: int = 35):
        verified_srt, _ = self.translator.translate_and_rewrite_srt(
            srt_input=input_srt,
            target_language=target_language,
            batch_size=batch_size,
            temperature=0.4
        )
        return verified_srt
