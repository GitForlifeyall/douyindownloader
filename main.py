#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.py
=======
Root Master Entrypoint for Douyin & TikTok Video Automated Dubbing Studio.

Features:
  - Automatic download of Douyin / TikTok videos into input/ folder
  - AI subtitle speech-to-text (Faster-Whisper GPU)
  - Isochronic viral transcreation with Gemini (config/system_prompts.py)
  - Subtitle removal / luminance-suppressed blur
  - High-fidelity voiceover synthesis (Sarvam AI / Google Gemini TTS / OmniVoice / Kokoro)
  - Meta Demucs Foley/SFX stem isolation and studio mixing
  - Continuous, syllable-accurate ASS subtitle burning

Usage:
  # Auto-download an entire Douyin profile and process all videos:
  python main.py --profile "https://www.douyin.com/user/MS4wLjABAAAA..."

  # Download top 10 most popular videos from a profile:
  python main.py --profile "https://www.douyin.com/user/MS4wLjABAAAA..." --max-videos 10 --sort-by popularity

  # Dub a Douyin URL directly (saves raw to input/, dubbed to output/):
  python main.py --url "https://v.douyin.com/..."

  # Dub using Google Gemini TTS:
  python main.py --url "https://v.douyin.com/..." --tts google --voice Orus

  # Batch process an entire input folder:
  python main.py --folder ./input

  # Reorganize and clean up output folders:
  python main.py --reorganize
"""

import sys
from pathlib import Path

# Ensure root workspace is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dubbing_studio.pipeline import main as pipeline_main, DubbingPipeline
from dubbing_studio.downloader import DownloaderAPI
from config import (
    INPUT_DIR,
    OUTPUT_DIR,
    TRANSLATION_SYSTEM_PROMPT,
    GOOGLE_TTS_SYSTEM_PROMPT,
    DEFAULT_VOICES,
    DEFAULT_TARGET_LANGUAGE
)

if __name__ == "__main__":
    pipeline_main()
