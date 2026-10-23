#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
config/__init__.py
==================
Exposes centralized configurations and prompts.
"""

from .system_prompts import (
    TRANSLATION_SYSTEM_PROMPT,
    GOOGLE_TTS_SYSTEM_PROMPT,
    SSML_SYSTEM_PROMPT,
    BANNED_WORDS,
)
from .settings import (
    PROJECT_ROOT,
    INPUT_DIR,
    OUTPUT_DIR,
    ASSETS_DIR,
    TIKTOK_DOWNLOADER_DIR,
    SUBTITLE_STYLE,
    DEFAULT_BLUR_BOX,
    DEFAULT_VOICES,
    DEFAULT_TARGET_LANGUAGE,
)

__all__ = [
    "TRANSLATION_SYSTEM_PROMPT",
    "GOOGLE_TTS_SYSTEM_PROMPT",
    "SSML_SYSTEM_PROMPT",
    "BANNED_WORDS",
    "PROJECT_ROOT",
    "INPUT_DIR",
    "OUTPUT_DIR",
    "ASSETS_DIR",
    "TIKTOK_DOWNLOADER_DIR",
    "SUBTITLE_STYLE",
    "DEFAULT_BLUR_BOX",
    "DEFAULT_VOICES",
    "DEFAULT_TARGET_LANGUAGE",
]
