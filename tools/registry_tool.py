#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/registry_tool.py
======================
Inspect, backfill, export, and resolve links for the SQLite video registry.

Examples:
  python tools/registry_tool.py stats
  python tools/registry_tool.py list --status uploaded --limit 20
  python tools/registry_tool.py movies
  python tools/registry_tool.py get 7558092762407652668
  python tools/registry_tool.py export --db-backup
  python tools/registry_tool.py backfill
  python tools/registry_tool.py backfill --drive-scan
  python tools/registry_tool.py resolve-links
"""

import argparse
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from dubbing_studio.env_loader import configure_runtime_environment

configure_runtime_environment()

from dubbing_studio.video_registry import (  # noqa: E402
    VideoRegistry,
    drive_relative,
    resolve_drive_base,
)

DEFAULT_PENDING_STATE = ROOT_DIR / "output" / "pending_batches_state.json"
DEFAULT_DRIVE_BATCH_ROOT = Path("channel pending movies")
SKIP_DIRS = {"clean_videos", "audio_stems", "input", "scratch", "tests", "test_artifacts"}


def _table(rows, columns, max_width=48):
    if not rows:
        print("(no records)")
        return
    def cell(value):
        text = "" if value is None else str(value)
        text = text.replace("\n", " ")
        return text if len(text) <= max_width else text[: max_width - 1] + "…"

    widths = {column: len(column) for column in columns}
    for row in rows:
        for column in columns:
            widths[column] = min(max_width, max(widths[column], len(cell(row.get(column)))))

    header = "  ".join(column.ljust(widths[column]) for column in columns)
    print(header)
    print("-" * len(header))
    for row in rows:
        print("  ".join(cell(row.get(column)).ljust(widths[column]) for column in columns))


def _video_columns():
    return ["video_id", "status", "movie_name", "channel", "final_filename", "drive_link", "drive_path"]


def cmd_stats(registry: VideoRegistry, args) -> None:
    stats = registry.stats()
    print(json.dumps(stats, indent=2, ensure_ascii=False))


def cmd_list(registry: VideoRegistry, args) -> None:
    rows = registry.list(status=args.status, channel=args.channel, limit=args.limit)
    _table(rows, _video_columns())
    print(f"\n{len(rows)} row(s)")


def cmd_movies(registry: VideoRegistry, args) -> None:
    rows = registry.list_movies(limit=args.limit)
    _table(rows, ["movie_name", "movie_year", "movie_genre", "video_count", "movie_source"])
    print(f"\n{len(rows)} movie(s)")


def cmd_movie(registry: VideoRegistry, args) -> None:
    movie = registry.find_movie(args.name)
    if not movie:
        raise SystemExit(f"No movie row for: {args.name}")
    rows = [row for row in registry.list(limit=10000) if row.get("movie_id") == movie["id"]]
    print(json.dumps({**movie, "video_count": len(rows)}, indent=2, ensure_ascii=False))
    print()
    _table(rows, ["video_id", "source_url", "status", "final_filename", "drive_link"])


def cmd_get(registry: VideoRegistry, args) -> None:
    row = registry.get(args.video_id)
    if not row:
        row = registry.find_by_final_filename(args.video_id)
    if not row:
        raise SystemExit(f"No registry row for: {args.video_id}")
    print(json.dumps(row, indent=2, ensure_ascii=False))


def cmd_export(registry: VideoRegistry, args) -> None:
    outputs = registry.export(include_db_backup=args.db_backup)
    for key, value in outputs.items():
        print(f"{key}: {value}")


def _record_pending_state(registry: VideoRegistry, state_path: Path, drive_root: Path) -> int:
    if not state_path.exists():
        print(f"[Backfill] Pending-state file not found: {state_path}")
        return 0

    data = json.loads(state_path.read_text(encoding="utf-8"))
    batches = data.get("batches", {}) if isinstance(data, dict) else {}
    recorded = 0

    for batch_name, batch_info in batches.items():
        items = (batch_info or {}).get("items", {}) or {}
        language = "Hindi" if "hindi" in batch_name.lower() else "English"
        for item_key, item in items.items():
            if not isinstance(item, dict):
                continue
            video_id = str(item.get("video_id") or item_key)
            metadata = item.get("metadata") or {}
            registry.record_download(
                source_url=str(item.get("url") or ""),
                video_id=video_id,
                batch=batch_name,
                channel=batch_name,
            )

            if item.get("status") != "completed":
                item_status = str(item.get("status") or "")
                if item_status.startswith("failed"):
                    registry.record_failure(
                        str(item.get("error") or item_status or "unknown failure"),
                        video_id=video_id,
                    )
                elif item_status.startswith("skipped"):
                    registry.record_skip(item_status, video_id=video_id)
                continue

            drive_filename = str(item.get("drive_filename") or "")
            registry.record_render(
                video_id=video_id,
                final_filename=drive_filename or "",
                title=str(metadata.get("title") or ""),
                language=language,
                tts_engine=str(item.get("tts_engine") or ""),
                duration_sec=item.get("final_duration_sec"),
                metadata=metadata,
                channel=batch_name,
                batch=batch_name,
            )
            if metadata.get("movie_name"):
                registry.record_movie(
                    movie_name=str(metadata.get("movie_name")),
                    movie_year=metadata.get("movie_year"),
                    movie_genre=str(metadata.get("movie_genre") or ""),
                    movie_synopsis=str(metadata.get("movie_synopsis") or ""),
                    movie_source=str(metadata.get("movie_source") or "batch-state"),
                    video_id=video_id,
                )

            if drive_filename:
                drive_path = drive_root / batch_name / drive_filename
                if drive_path.exists():
                    registry.record_drive(
                        video_id=video_id,
                        final_filename=drive_filename,
                        drive_folder=drive_relative(drive_path.parent),
                        drive_path=str(drive_path),
                    )
            recorded += 1

    print(f"[Backfill] Imported {recorded} item(s) from {state_path.name}")
    return recorded


def _scan_output_videos(registry: VideoRegistry, output_dir: Path) -> int:
    recorded = 0
    for path in sorted(output_dir.rglob("*.mp4")):
        if any(part.lower() in SKIP_DIRS for part in path.parts):
            continue
        if path.stem.endswith(("_clean", "_wmtmp")):
            continue
        if registry.find_by_final_filename(path.name):
            continue
        channel = path.parent.name if path.parent != output_dir else ""
        registry.record_download(local_path=path, channel=channel)
        registry.record_render(
            final_video=path,
            title=path.stem,
            language="",
            tts_engine="",
            channel=channel,
        )
        recorded += 1
    print(f"[Backfill] Imported {recorded} unindexed local video(s) from {output_dir}")
    return recorded


def _scan_drive_videos(registry: VideoRegistry, drive_root: Path) -> int:
    if not drive_root.exists():
        print(f"[Backfill] Drive root not found: {drive_root}")
        return 0

    rows = registry.list(limit=5000)
    by_filename = {}
    for row in rows:
        for key in (row.get("final_filename"), row.get("drive_filename")):
            if key:
                by_filename.setdefault(key, row)
    claimed_ids = set()
    recorded = 0

    for path in sorted(drive_root.rglob("*.mp4")):
        existing = by_filename.get(path.name)
        if existing is None:
            existing = _match_drive_file(rows, path, claimed_ids)

        if existing is not None:
            video_id = existing["video_id"]
            if existing.get("drive_path"):
                print(f"  [skip] {path.name} (row already linked)")
                continue
            if video_id in claimed_ids:
                print(f"  [skip] {path.name} (row already linked to another file)")
                continue
            registry.record_drive(
                video_id=video_id,
                final_filename=path.name,
                drive_folder=drive_relative(path.parent),
                drive_path=str(path),
            )
            existing["drive_path"] = str(path)
            claimed_ids.add(video_id)
        else:
            # Keep an honest standalone row for a Drive file we cannot match.
            key = registry.resolve_video_id(local_path=str(path))
            registry.record_render(
                video_id=key,
                title=path.stem,
                channel=path.parent.name,
            )
            registry.record_drive(
                video_id=key,
                final_filename=path.name,
                drive_folder=drive_relative(path.parent),
                drive_path=str(path),
            )
            claimed_ids.add(key)
        recorded += 1

    print(f"[Backfill] Indexed {recorded} Drive video(s) under {drive_root}")
    return recorded


def _name_key(value: str) -> str:
    """Lowercase alphanumeric key with emoji/punctuation/bracket clutter removed."""
    text = str(value or "")
    text = re.sub(r"\[[^\]]*\]|\([^)]*\)|\{[^}]*\}", " ", text)
    words = re.findall(r"[a-z0-9']+", text.lower())
    return " ".join(words)


def _name_score(candidate: str, stored: str) -> float:
    if not candidate or not stored:
        return 0.0
    if candidate == stored:
        return 1.0
    shorter, longer = (candidate, stored) if len(candidate) <= len(stored) else (stored, candidate)
    # Drive copies are truncated to <=49 chars, so a long prefix is a strong signal.
    if longer.startswith(shorter) and len(shorter) >= 18:
        return 0.92 - 0.25 * (len(longer) - len(shorter)) / max(len(longer), 1)
    return SequenceMatcher(None, candidate, stored).ratio()


def _match_drive_file(rows, path: Path, claimed_ids):
    """
    Match a Drive file to a registry row whose stored filename differs.
    Drive filenames are shortened/sanitized, so compare normalized prefixes.
    """
    candidate_key = _name_key(path.stem)
    if len(candidate_key) < 8:
        return None

    channel = path.parent.name
    in_channel = [row for row in rows if channel and row.get("channel") == channel]
    pool = in_channel or rows

    best_row, best_score = None, 0.0
    for row in pool:
        if not row.get("final_filename") or row["video_id"] in claimed_ids:
            continue
        row_key = _name_key(Path(row["final_filename"]).stem) or _name_key(row.get("title") or "")
        score = _name_score(candidate_key, row_key)
        if score > best_score:
            best_row, best_score = row, score

    if best_row and best_score >= 0.70:
        print(f"  [match] {path.name} -> {best_row['video_id']} (score {best_score:.2f})")
        return best_row
    if best_score >= 0.55:
        print(f"  [unmatched] {path.name} (best score {best_score:.2f}, below threshold)")
    return None


def cmd_backfill(registry: VideoRegistry, args) -> None:
    drive_base = Path(args.drive_base) if args.drive_base else resolve_drive_base()
    drive_root = (drive_base / DEFAULT_DRIVE_BATCH_ROOT) if drive_base else Path("channel pending movies")

    if not args.no_pending_state:
        _record_pending_state(registry, Path(args.pending_state), drive_root)
    if not args.no_output_scan:
        _scan_output_videos(registry, Path(args.output_dir))
    if args.drive_scan:
        _scan_drive_videos(registry, drive_root)

    outputs = registry.export(include_db_backup=True)
    print(f"[Backfill] Exported snapshots: {outputs.get('json')} / {outputs.get('csv')}")


def _q(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("'", "\\'")


def _resolve_folder_id(service, relative_folder: str, cache) -> str:
    segments = [s for s in str(relative_folder).replace("\\", "/").split("/") if s and s.lower() != "my drive"]
    parent = "root"
    for segment in segments:
        cache_key = (parent, segment)
        if cache_key in cache:
            parent = cache[cache_key]
            continue
        result = service.files().list(
            q=(
                f"name = '{_q(segment)}' and mimeType = 'application/vnd.google-apps.folder' "
                f"and '{parent}' in parents and trashed = false"
            ),
            spaces="drive",
            fields="files(id, name)",
        ).execute()
        files = result.get("files", [])
        if not files:
            return ""
        parent = files[0]["id"]
        cache[cache_key] = parent
    return parent


def cmd_resolve_links(registry: VideoRegistry, args) -> None:
    from dubbing_studio.gdrive_uploader import GoogleDriveUploader

    uploader = GoogleDriveUploader()
    service = uploader.service
    folder_cache = {}
    rows = [
        row for row in registry.list(limit=args.limit)
        if not row.get("drive_link") and row.get("final_filename")
    ]
    if not rows:
        print("[Resolve] Every indexed video already has a Drive link.")
        return

    resolved = 0
    for row in rows:
        filename = row["final_filename"]
        folder = row.get("drive_folder") or ""
        if not folder and row.get("drive_path"):
            folder = drive_relative(Path(row["drive_path"]).parent)
        folder_id = _resolve_folder_id(service, folder, folder_cache) if folder else ""

        query = f"name = '{_q(filename)}' and trashed = false"
        if folder_id:
            query += f" and '{folder_id}' in parents"
        result = service.files().list(
            q=query,
            spaces="drive",
            fields="files(id, name, webViewLink, parents)",
            pageSize=10,
        ).execute()
        files = result.get("files", [])

        if not files and folder_id:
            # Fall back to a global name search if the folder moved/renamed.
            result = service.files().list(
                q=f"name = '{_q(filename)}' and trashed = false",
                spaces="drive",
                fields="files(id, name, webViewLink, parents)",
                pageSize=10,
            ).execute()
            files = result.get("files", [])

        if not files:
            print(f"  [not found] {filename}")
            continue

        chosen = files[0]
        link = chosen.get("webViewLink") or f"https://drive.google.com/file/d/{chosen.get('id')}/view"
        registry.record_drive(
            video_id=row["video_id"],
            final_filename=filename,
            drive_folder=folder,
            drive_path=row.get("drive_path") or "",
            file_id=chosen.get("id", ""),
            link=link,
        )
        resolved += 1
        print(f"  [linked] {filename} -> {link}")

    print(f"\n[Resolve] Linked {resolved}/{len(rows)} video(s).")
    registry.export(include_db_backup=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Video registry inspector / backfill tool")
    parser.add_argument("--db", type=str, default="", help="Custom SQLite registry path")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("stats")

    list_parser = sub.add_parser("list")
    list_parser.add_argument("--status", default=None)
    list_parser.add_argument("--channel", default=None)
    list_parser.add_argument("--limit", type=int, default=100)

    movies_parser = sub.add_parser("movies")
    movies_parser.add_argument("--limit", type=int, default=100)

    movie_parser = sub.add_parser("movie")
    movie_parser.add_argument("name")

    get_parser = sub.add_parser("get")
    get_parser.add_argument("video_id")

    export_parser = sub.add_parser("export")
    export_parser.add_argument("--db-backup", action="store_true", help="Also copy the SQLite file to the snapshot folder")

    backfill_parser = sub.add_parser("backfill")
    backfill_parser.add_argument("--pending-state", default=str(DEFAULT_PENDING_STATE))
    backfill_parser.add_argument("--output-dir", default=str(ROOT_DIR / "output"))
    backfill_parser.add_argument("--drive-base", default="")
    backfill_parser.add_argument("--drive-scan", action="store_true", help="Also scan the mounted Drive batch folders")
    backfill_parser.add_argument("--no-pending-state", action="store_true")
    backfill_parser.add_argument("--no-output-scan", action="store_true")

    resolve_parser = sub.add_parser("resolve-links")
    resolve_parser.add_argument("--limit", type=int, default=500)

    args = parser.parse_args()
    registry = VideoRegistry(db_path=args.db or None)

    commands = {
        "stats": cmd_stats,
        "list": cmd_list,
        "movies": cmd_movies,
        "movie": cmd_movie,
        "get": cmd_get,
        "export": cmd_export,
        "backfill": cmd_backfill,
        "resolve-links": cmd_resolve_links,
    }
    commands[args.command](registry, args)


if __name__ == "__main__":
    main()
