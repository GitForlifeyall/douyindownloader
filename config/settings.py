#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
config/settings.py
==================
Centralized Configuration & Path Management for Douyin/TikTok Dubbing Studio.
"""

from pathlib import Path

# Project Roots
PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = PROJECT_ROOT / "input"
OUTPUT_DIR = PROJECT_ROOT / "output"
ASSETS_DIR = PROJECT_ROOT / "assets"
TIKTOK_DOWNLOADER_DIR = PROJECT_ROOT / "TikTokDownloader"

# Ensure directories exist
INPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Default Subtitle & Typography Styling
SUBTITLE_STYLE = {
    "font_name": "Montserrat ExtraBold",
    "fallback_font": "Arial Black",
    "font_size": 96,
    "primary_color": "&H00FFFFFF",     # Pure White
    "outline_color": "&H00000000",     # Deep Black Outline
    "back_color": "&H00000000",
    "bold": 1,
    "outline": 5,
    "shadow": 3,
    "alignment": 2,                     # Bottom-centered
    "margin_v": 485,                    # Exact Y anchor
    "scale_x": 100,
    "scale_y": 100,
    "spacing": 1.0,
}

# Subtitle Inpainting / Luminance Blur Box Dimensions (Default Douyin Shorts)
DEFAULT_BLUR_BOX = {
    "y_min": 1346,
    "y_max": 1435,
    "height": 89,
    "width": 900,
    "center_x": 540,
    "blur_sigma": 18
}

# Default Voice Engine Mappings
DEFAULT_VOICES = {
    "sarvam": "shubh",
    "google": "Orus",
    "omnivoice": "male_deep",
    "kokoro": "hm_omega"
}

DEFAULT_TARGET_LANGUAGE = "Hindi (Natural Spoken Hinglish in Devanagari script)"
