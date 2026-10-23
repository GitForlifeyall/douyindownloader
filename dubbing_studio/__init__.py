#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dubbing_studio
==============
Modular Video Localization & Automated Dubbing Studio.
"""

from .env_loader import configure_runtime_environment
from .key_pool import (
    get_active_gemini_keys,
    mark_gemini_key_dead,
    get_active_sarvam_keys,
    mark_sarvam_key_dead,
    get_active_elevenlabs_keys,
    mark_elevenlabs_key_dead,
    get_pool_status,
)
from .downloader import DownloaderAPI
from .transcriber import Transcriber
from .translator import (
    SRTDubTranslator,
    inject_constraints_into_srt,
    clean_and_verify_srt,
    translate_and_rewrite_srt,
    SYSTEM_PROMPT,
)
from .tts_engine import KokoroTTS
from .tts import SarvamTTS, generate_sarvam_tts
from .tts_google import GoogleGeminiTTS
from .tts_elevenlabs import ElevenLabsTTS
from .tts_omnivoice import OmniVoiceTTS
from .separator import AudioStemSeparator


def __getattr__(name: str):
    if name == "DubbingPipeline":
        from .pipeline import DubbingPipeline
        return DubbingPipeline
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "configure_runtime_environment",
    "DownloaderAPI",
    "Transcriber",
    "SRTDubTranslator",
    "KokoroTTS",
    "SarvamTTS",
    "GoogleGeminiTTS",
    "ElevenLabsTTS",
    "OmniVoiceTTS",
    "AudioStemSeparator",
    "generate_sarvam_tts",
    "DubbingPipeline",
    "inject_constraints_into_srt",
    "clean_and_verify_srt",
    "translate_and_rewrite_srt",
    "SYSTEM_PROMPT",
]

