# DeepSeek Handoff Log

## Overview
This document logs architectural understanding, audits, and code changes performed by **DeepSeek (OpenCode)** in this repository.

---

## Instructions for DeepSeek
- Before making changes, read `AGENTS.md` and the other handoff files in this folder.
- Log every modification, bugfix, or pipeline alteration below with timestamps and file paths.
- Keep test artifacts in `tests/test_artifacts/` and final video filenames `<= 49` characters.

---

## Session History & Changes

### [2026-11-16] Codebase Read-Only Audit (no code changes)
- Read all handoffs, `AGENTS.md`, `README.md`, `decisions.md`, `main.py`, `pipeline.py`, `config/`, `dubbing_studio/*`, `tools/` entry points, and `tests/`.
- Mapped the end-to-end pipeline: download -> Faster-Whisper transcribe -> OCR subtitle/watermark clean or movie crop (parallel) -> HTDemucs stem separation -> narrator/dialogue detection -> Gemini transcreation -> metadata -> block-aligned TTS + mux -> Drive sync -> optional thumbnail.
- Findings reported to user (not yet fixed):
  1. `config/__init__.py` imports `config.settings`, which was deleted in the 2026-11-13 cleanup; `import config` raises `ModuleNotFoundError`, so root `main.py` is broken at import time. `dubbing_studio/` does not depend on `config`, so `python -m dubbing_studio.pipeline` still works.
  2. `dubbing_studio/pipeline.py` `run()` thumbnail block references undefined names `blocks` and `clean_title` (lines ~1603/1607), so `--thumbnail` raises `NameError`, which is swallowed by the surrounding `except`, producing no thumbnail.
  3. `README.md` is stale (references removed `run.bat`, root `srt_dub_translator.py`, `TikTokDownloader/requirements.txt`).
  4. `clean_youtube_tags()` always returns exactly 3 tags (`Animation`, `3D Explained`, subject), conflicting with the `AGENTS.md` movie rule of 4-5 broad tags; master metadata also hardcodes `_hindi_metadata.json` lookup for English batches.
- No files were modified except creating this handoff file.

### [2026-11-16] Durable Video Registry (SQLite + JSON/CSV/Drive snapshots)
Implemented a durable index of every downloaded video, its render, Drive copy/link, and linked movie identity.

**New files**
- `dubbing_studio/video_registry.py`
  - SQLite schema: `videos`, `events`, `movies` + auto-migration for `drive_filename` and movie columns.
  - Video key priority: Douyin aweme ID -> existing row by local path/filename -> stable `local:<sha1>`.
  - Status flow `downloaded -> rendered -> uploaded` (never downgrades `uploaded`), plus `failed`.
  - API: `record_download`, `record_render`, `record_drive`, `record_movie`, `record_failure`, `record_skip`, `get`, `list`, `stats`, `list_movies`, `find_movie`, `find_by_final_filename`, `export`.
  - `record_drive` derives `drive_folder`/filename from `drive_path`; keeps the original render filename in `final_filename` and stores renamed Drive copies in the new `drive_filename` column.
  - Snapshot export (`video_registry.json` / `.csv`, optional `.db`) with WAL checkpoint before the DB copy; mirrors to `<My Drive>/douyin/video_registry/` unless `VIDEO_REGISTRY_NO_DRIVE=1`.
  - Custom `--registry-db` paths keep their snapshots beside the DB (tests/backfills never overwrite the live snapshot).
- `tools/registry_tool.py`: `stats`, `list`, `movies`, `movie <name>`, `get`, `export`, `backfill`, `resolve-links`.
  - `backfill` imports `output/pending_batches_state.json`, scans local `output/`, and with `--drive-scan` indexes mounted Drive batch folders.
  - Drive filenames are already shortened to <=49 chars, so matching normalizes emoji/punctuation and uses prefix/ratio scoring with one-to-one assignment; unmatched files get honest standalone rows.
  - `resolve-links` fills shareable `drive_link`/`drive_file_id` via the Drive API and re-exports snapshots.
- `tests/test_video_registry.py`: dependency-free self-check (`python tests/test_video_registry.py`).

**Pipeline/CLI integration** (`dubbing_studio/pipeline.py`)
- `DubbingPipeline(..., registry_db=None, enable_registry=True)`; registry failures only warn and never abort a render.
- `run()`: records download, render (cached and normal paths) and Drive copies; resolves/links movie identity and syncs it back into the generated metadata dict.
- `run_folder()`: pre-registers each input, passes the resolved `video_id` through render/movie/Drive hooks, and records mounted copies + API uploads + final sync.
- `run_urls()`: registers every original batch URL immediately after download, records failed URL downloads as `failed`, and defaults `capture_movie_details=True`.
- New CLI flags: `--registry-db`, `--no-registry`, `--capture-movie-details` (auto-enabled for `--batch-urls`).
- Fixed the pre-existing thumbnail `NameError` by using the resolved metadata/clean title instead of undefined `blocks`/`clean_title`.

**Movie identity** (`dubbing_studio/translator.py`)
- Movie-style metadata prompt now returns `movie_name`, `movie_year`, `movie_genre`, `movie_synopsis`; metadata dict carries them through.
- Added `lookup_movie_details()` (free Wikipedia summary/plot lookup, year + synopsis parsing, numeric-title guard, opt-in Gemini fallback) plus wiki-markup cleanup.

**Docs**
- `.env.example`: `VIDEO_REGISTRY_DB`, `VIDEO_REGISTRY_DRIVE_DIR`, `VIDEO_REGISTRY_NO_EXPORT`, `VIDEO_REGISTRY_NO_DRIVE`.
- `README.md`: new "Video Registry" section with CLI examples and DB/snapshot/Drive locations.

**Backfill outcome (live DB)**
- `python tools/registry_tool.py backfill --drive-scan` -> `output/video_registry.db` with 174 videos: 155 uploaded (linked to shortened Drive filenames, original render name kept in `final_filename`, Drive name in `drive_filename`), 2 rendered, 5 downloaded (unknown state), 8 skipped, 4 failed; channels batch_1..batch_4 + Curious Cinefile.
- Added `record_skip()` / `skipped` status so `skipped_duration` items are not mislabelled as downloaded; `failed_download` / `failed_pipeline` items are stored as `failed` with the error.
- Snapshots written to `output/video_registry/` and `I:\My Drive\douyin\video_registry\` (JSON + CSV + SQLite copy).
- Existing rows have `with_movie = 0`: the old batch state/metadata never stored a movie name, so movie identities start being captured from the next run onward (or can be added later with `tools/registry_tool.py`).
- Mounted Drive copies supply paths but no shareable links, so `with_drive_link = 0` until `resolve-links` runs with Drive API credentials.

### [2026-11-16] Monetization Playbook (operating guide for the revenue ideas)

Added `docs/monetization_playbook.md`: the operating manual for turning the recap pipeline into revenue, not a pipeline runbook.

**Contents**
- Baseline audit: blog has 0 posts + placeholder player, 11 ad slots / 6 unique Adsterra keys, popunder + smartlink triggers; registry holds 155 uploaded renders as the content backlog.
- Funnel model (source clip -> render -> Shorts/Reels -> CTA -> blog/list/offer).
- Track A: YouTube YPP (1k subs / 10M Shorts views) with reused-content fixes; Facebook/IG monetization checks via Meta Business Suite and native-Reels rules; removal of "comment MOVIE" engagement-bait CTA.
- Track B: blog/SEO — AdSense vs Adsterra decision table, article template targeting the "{Movie} ending explained" query, 28 posts in 14 days, required privacy/about/contact/disclosure pages, commands using `tools/registry_tool.py movies|movie|export`.
- Track C: affiliate stack (VPN/streaming/Amazon/Audible/app-install CPA) with disclosure and per-article UTM tracking.
- Track D: brand/CPA media kit + rate card; Track E: WhatsApp/Telegram/email owned audience; Track F: productized dubbing/script/thumbnail services; Track G: multi-language page network.
- Weekly cadence, KPI columns, 30/60/90 plan, revenue scenario table, and non-negotiable guardrails (no pirated streams, no bought engagement, AdSense/popunder mutually exclusive, disclose AI/sponsors/affiliates, TMDB key off-client).

**Notes**
- Research for the guide: verified `registry_tool` subcommand flags, pipeline `--batch-urls`/`--capture-movie-details` behaviour, Drive sync vs `--move-to-drive` semantics, and that the root `main.py` entry point is still broken (`config/__init__.py` imports deleted `config.settings`) — commands in docs use `python -m dubbing_studio.pipeline`.
- No production code changed in this session; docs only.
