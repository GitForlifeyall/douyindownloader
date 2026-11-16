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

## Video Registry (SQLite index)

Every pipeline run records each Douyin video, its rendered output, the Google Drive copy/link, and (for movie recaps) the linked movie identity.

- Database: `output/video_registry.db`
- Snapshots (JSON + CSV, refreshed after each write): `output/video_registry/`
- Drive mirror: `I:\My Drive\douyin\video_registry\` (override with `VIDEO_REGISTRY_DRIVE_DIR`)
- Disable with `--no-registry`, or point elsewhere with `--registry-db PATH`

Batch URL runs (`--batch-urls`) register each original Douyin URL immediately and link it to the movie name/year/genre/synopsis captured for that video.

Inspect and backfill:

```bash
python tools/registry_tool.py stats                 # totals, statuses, channels, movies
python tools/registry_tool.py list --status uploaded
python tools/registry_tool.py movies                # movie table with video counts
python tools/registry_tool.py movie "Inception"     # movie + linked videos/URLs
python tools/registry_tool.py get 7558092762407652668
python tools/registry_tool.py backfill --drive-scan # import pending_batches_state + Drive folders
python tools/registry_tool.py resolve-links         # fill shareable links via Drive API
python tools/registry_tool.py export --db-backup
```

Registry writes are best-effort: a failure there logs a warning and never aborts a render.

## Security

No API keys are hardcoded. Keys load from `GEMINI_API_KEY` / `GEMINI_API_KEYS` env vars only.

## Attribution

Downloader core: JoeanAmier/TikTokDownloader (see `TikTokDownloader/README.md`, `TikTokDownloader/license`).
