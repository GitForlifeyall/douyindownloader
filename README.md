# douyindownloader

Douyin / TikTok downloader + SRT dubbing pipeline (transcribe -> Gemini transcreate -> Kokoro TTS -> dubbed video).

> Upstream downloader code is based on [JoeanAmier/TikTokDownloader](https://github.com/JoeanAmier/TikTokDownloader). Custom dubbing scripts in this repo are original additions. See `TikTokDownloader/license` and attribution below.

## Layout

- `run.bat` - Windows launcher
- `srt_dub_translator.py` - Gemini SRT transcreation pipeline (env keys only)
- `TikTokDownloader/` - app code
  - `pipeline.py` - download -> transcribe -> translate -> TTS/dub
  - `transcribe.py` - Faster-Whisper transcription
  - `translator.py` - wrapper around `srt_dub_translator`
  - `generate_tts.py` - Kokoro TTS + ffmpeg dub
  - `dub_hindi_first_half.py` - example Hindi dub script
  - `src/` - upstream downloader source

## Setup

1. Python 3.10+ recommended.
2. Copy `.env.example` to `.env` and set:
   - `GEMINI_API_KEY` (or `GEMINI_API_KEYS` comma-separated)
   - `KOKORO_MODEL_PATH`, `KOKORO_VOICES_PATH`
3. Install deps from `TikTokDownloader/requirements.txt` / `pyproject.toml`.
4. Run `run.bat` or `python TikTokDownloader/main.py`.

## Security

No API keys are hardcoded. Keys load from `GEMINI_API_KEY` / `GEMINI_API_KEYS` env vars only.

## Attribution

Downloader core: JoeanAmier/TikTokDownloader (see `TikTokDownloader/README.md`, `TikTokDownloader/license`).
