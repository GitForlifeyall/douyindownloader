#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dubbing_studio/video_registry.py
================================
Durable SQLite registry for every Douyin/TikTok video handled by the studio.

Tracks (per video):
  - Douyin video ID + source URL
  - local raw download path
  - rendered final filename / title / language / TTS engine
  - Google Drive folder + mounted path + shareable link + file ID
  - status (downloaded -> rendered -> uploaded / failed) and error text

The SQLite database lives locally (default: output/video_registry.db) because
syncing a live SQLite file through Google Drive Desktop can lock/corrupt it.
After every write, a JSON + CSV snapshot is exported and mirrored to
<My Drive>/douyin/video_registry/ so the index is always available in Drive.

Environment overrides:
  VIDEO_REGISTRY_DB          Explicit SQLite path
  VIDEO_REGISTRY_DRIVE_DIR   Explicit Drive snapshot folder
  VIDEO_REGISTRY_NO_EXPORT   Set to 1 to disable snapshot exports
  VIDEO_REGISTRY_NO_DRIVE    Set to 1 to skip copying snapshots to Drive
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import sqlite3
import string
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "output" / "video_registry.db"
DEFAULT_SNAPSHOT_DIR = PROJECT_ROOT / "output" / "video_registry"
DRIVE_SNAPSHOT_SUBDIR = "video_registry"

# Columns that callers may write through upsert().
_WRITABLE_FIELDS = {
    "source_url",
    "platform",
    "channel",
    "batch",
    "original_filename",
    "local_path",
    "final_filename",
    "drive_filename",
    "title",
    "description",
    "tags",
    "target_language",
    "tts_engine",
    "duration_sec",
    "status",
    "drive_folder",
    "drive_path",
    "drive_file_id",
    "drive_link",
    "thumbnail_path",
    "thumbnail_link",
    "metadata_json",
    "movie_id",
    "movie_name",
    "movie_year",
    "movie_genre",
    "movie_synopsis",
    "movie_context",
    "movie_source",
    "movie_source_url",
    "error",
    "uploaded_at",
}

_VIDEO_ID_PATTERNS = (
    r"/video/(\d{8,})",
    r"/note/(\d{8,})",
    r"modal_id=(\d{8,})",
    r"[?&]vid=(\d{8,})",
    r"\b(\d{19})\b",
    r"\b(\d{15,20})\b",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL UNIQUE,
    source_url TEXT,
    platform TEXT DEFAULT 'douyin',
    channel TEXT,
    batch TEXT,
    original_filename TEXT,
    local_path TEXT,
    final_filename TEXT,
    drive_filename TEXT,
    title TEXT,
    description TEXT,
    tags TEXT,
    target_language TEXT,
    tts_engine TEXT,
    duration_sec REAL,
    status TEXT NOT NULL DEFAULT 'downloaded',
    drive_folder TEXT,
    drive_path TEXT,
    drive_file_id TEXT,
    drive_link TEXT,
    thumbnail_path TEXT,
    thumbnail_link TEXT,
    metadata_json TEXT,
    movie_id INTEGER,
    movie_name TEXT,
    movie_year INTEGER,
    movie_genre TEXT,
    movie_synopsis TEXT,
    movie_context TEXT,
    movie_source TEXT,
    movie_source_url TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    uploaded_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_videos_video_id ON videos(video_id);
CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status);
CREATE INDEX IF NOT EXISTS idx_videos_channel ON videos(channel);
CREATE INDEX IF NOT EXISTS idx_videos_final_filename ON videos(final_filename);

CREATE TABLE IF NOT EXISTS movies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    movie_key TEXT NOT NULL UNIQUE,
    movie_name TEXT NOT NULL,
    movie_year INTEGER,
    movie_genre TEXT,
    movie_synopsis TEXT,
    movie_context TEXT,
    movie_source TEXT,
    movie_source_url TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_movies_key ON movies(movie_key);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL,
    event TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_video_id ON events(video_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _norm_path(value: Optional[Union[str, Path]]) -> str:
    if not value:
        return ""
    try:
        return str(Path(value).expanduser().resolve())
    except Exception:
        return str(value)


def extract_video_id(value: Optional[Union[str, Path]]) -> str:
    """Extract a Douyin/TikTok aweme ID from a URL or filename, or return ''."""
    text = str(value or "")
    for pattern in _VIDEO_ID_PATTERNS:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return ""


def _movie_key(name: str, year: Optional[Any] = None) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", str(name or "").lower()).strip()
    year_text = str(year).strip() if year not in (None, "") else ""
    return f"{normalized or 'unknown'}|{year_text}"


def drive_relative(path: Optional[Union[str, Path]]) -> str:
    """Return a path relative to the mounted 'My Drive' root when possible."""
    if not path:
        return ""
    parts = Path(path).parts
    if "My Drive" in parts:
        idx = parts.index("My Drive")
        return str(Path(*parts[idx + 1:]))
    return str(Path(path))


def resolve_drive_base() -> Optional[Path]:
    """Find the mounted Google Drive 'douyin' base directory, if any."""
    env_base = os.getenv("VIDEO_REGISTRY_DRIVE_BASE")
    if env_base and Path(env_base).exists():
        return Path(env_base)
    candidates = [Path("I:/My Drive/douyin"), Path("H:/My Drive/douyin"), Path("G:/My Drive/douyin")]
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            return candidate
    for letter in string.ascii_uppercase:
        candidate = Path(f"{letter}:/My Drive/douyin")
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


class VideoRegistry:
    """SQLite-backed video index with JSON/CSV snapshots."""

    def __init__(
        self,
        db_path: Optional[Union[str, Path]] = None,
        auto_export: Optional[bool] = None,
        sync_drive: Optional[bool] = None,
        snapshot_dir: Optional[Union[str, Path]] = None,
    ):
        env_db = os.getenv("VIDEO_REGISTRY_DB")
        self.db_path = Path(db_path or env_db or DEFAULT_DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        if not snapshot_dir:
            # Custom databases get snapshots beside the DB, not in the default
            # output folder (prevents test/backfill runs from overwriting the
            # live snapshot).
            if not db_path and not env_db:
                snapshot_dir = DEFAULT_SNAPSHOT_DIR
            else:
                snapshot_dir = self.db_path.parent / DRIVE_SNAPSHOT_SUBDIR
        self.snapshot_dir = Path(snapshot_dir)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

        if auto_export is None:
            auto_export = os.getenv("VIDEO_REGISTRY_NO_EXPORT", "").strip() not in ("1", "true", "True")
        if sync_drive is None:
            sync_drive = os.getenv("VIDEO_REGISTRY_NO_DRIVE", "").strip() not in ("1", "true", "True")
        self.auto_export = auto_export
        self.sync_drive = sync_drive

        self._init_db()

    # ------------------------------------------------------------------
    # Connection / schema
    # ------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            existing = {row["name"] for row in conn.execute("PRAGMA table_info(videos)")}
            added_columns = {
                "drive_filename": "TEXT",
                "movie_id": "INTEGER",
                "movie_name": "TEXT",
                "movie_year": "INTEGER",
                "movie_genre": "TEXT",
                "movie_synopsis": "TEXT",
                "movie_context": "TEXT",
                "movie_source": "TEXT",
                "movie_source_url": "TEXT",
            }
            for column, ddl in added_columns.items():
                if column not in existing:
                    conn.execute(f"ALTER TABLE videos ADD COLUMN {column} {ddl}")
            conn.commit()

    # ------------------------------------------------------------------
    # Identity resolution
    # ------------------------------------------------------------------
    def resolve_video_id(
        self,
        video_id: Optional[str] = None,
        source_url: Optional[Union[str, Path]] = None,
        local_path: Optional[Union[str, Path]] = None,
    ) -> str:
        """Resolve a stable key, reusing an existing row for the same local file."""
        if video_id:
            return str(video_id).strip()

        for value in (source_url, local_path):
            found = extract_video_id(value)
            if found:
                return found

        norm_local = _norm_path(local_path)
        if norm_local:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT video_id FROM videos WHERE local_path = ? OR original_filename = ? LIMIT 1",
                    (norm_local, Path(norm_local).name),
                ).fetchone()
                if row:
                    return row["video_id"]

        # source_url may itself be a local input path (folder/batch runs)
        source_text = str(source_url or "")
        if source_text and not source_text.lower().startswith(("http://", "https://")):
            norm_source = _norm_path(source_text)
            if norm_source and norm_source != norm_local:
                with self._connect() as conn:
                    row = conn.execute(
                        "SELECT video_id FROM videos WHERE local_path = ? OR original_filename = ? LIMIT 1",
                        (norm_source, Path(norm_source).name),
                    ).fetchone()
                    if row:
                        return row["video_id"]

        seed = f"{_norm_path(local_path)}|{source_url or ''}"
        if not seed.strip("|"):
            seed = f"unknown:{datetime.now(timezone.utc).timestamp()}"
        digest = hashlib.sha1(seed.encode("utf-8", errors="replace")).hexdigest()[:16]
        return f"local:{digest}"

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    def _upsert(self, video_id: str, event: str, detail: str = "", **fields: Any) -> Dict[str, Any]:
        clean: Dict[str, Any] = {}
        for key, value in fields.items():
            if key not in _WRITABLE_FIELDS:
                continue
            if value is None:
                continue
            if isinstance(value, (list, dict)):
                value = json.dumps(value, ensure_ascii=False)
            if isinstance(value, str):
                value = value.strip()
                if not value:
                    continue
            clean[key] = value

        now = _now()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, status FROM videos WHERE video_id = ?", (video_id,)
            ).fetchone()

            if row:
                current_status = row["status"] or "downloaded"
                incoming_status = clean.get("status")
                # Never downgrade a finished upload back to rendered/downloaded.
                if incoming_status in ("downloaded", "rendered") and current_status == "uploaded":
                    clean.pop("status", None)
                clean["updated_at"] = now
                assignments = ", ".join(f"{key} = ?" for key in clean)
                conn.execute(
                    f"UPDATE videos SET {assignments} WHERE video_id = ?",
                    (*clean.values(), video_id),
                )
            else:
                base: Dict[str, Any] = {
                    "video_id": video_id,
                    "status": clean.pop("status", "downloaded"),
                    "created_at": now,
                    "updated_at": now,
                }
                base.update(clean)
                columns = ", ".join(base.keys())
                placeholders = ", ".join("?" for _ in base)
                conn.execute(
                    f"INSERT INTO videos ({columns}) VALUES ({placeholders})",
                    tuple(base.values()),
                )

            conn.execute(
                "INSERT INTO events (video_id, event, detail, created_at) VALUES (?, ?, ?, ?)",
                (video_id, event, detail[:2000], now),
            )
            conn.commit()
            result = conn.execute(
                "SELECT * FROM videos WHERE video_id = ?", (video_id,)
            ).fetchone()
            row_dict = dict(result) if result else {"video_id": video_id}

        self._after_write()
        return row_dict

    def record_download(
        self,
        source_url: str = "",
        local_path: Optional[Union[str, Path]] = None,
        video_id: Optional[str] = None,
        channel: str = "",
        batch: str = "",
        platform: str = "douyin",
        original_filename: str = "",
    ) -> Dict[str, Any]:
        """Record/refresh a downloaded raw video."""
        key = self.resolve_video_id(video_id=video_id, source_url=source_url, local_path=local_path)
        filename = original_filename or (Path(local_path).name if local_path else "")
        fields: Dict[str, Any] = {
            "source_url": source_url,
            "local_path": _norm_path(local_path),
            "platform": platform,
            "channel": channel,
            "batch": batch,
            "original_filename": filename,
        }
        return self._upsert(key, "download", filename, **fields)

    def record_render(
        self,
        final_video: Optional[Union[str, Path]] = None,
        title: str = "",
        language: str = "",
        tts_engine: str = "",
        duration_sec: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
        video_id: Optional[str] = None,
        source_url: Optional[Union[str, Path]] = None,
        local_path: Optional[Union[str, Path]] = None,
        channel: str = "",
        batch: str = "",
        status: str = "rendered",
        final_filename: str = "",
    ) -> Dict[str, Any]:
        """Record a completed render (called even when the result came from cache)."""
        key = self.resolve_video_id(
            video_id=video_id,
            source_url=source_url or local_path,
            local_path=local_path or final_video,
        )
        meta = metadata or {}
        fields: Dict[str, Any] = {
            "final_filename": final_filename or (Path(final_video).name if final_video else ""),
            "local_path": _norm_path(final_video) if final_video else "",
            "title": title or str(meta.get("title") or ""),
            "description": str(meta.get("description") or ""),
            "tags": meta.get("tags") or [],
            "metadata_json": meta or None,
            "target_language": language,
            "tts_engine": tts_engine,
            "duration_sec": duration_sec,
            "channel": channel,
            "batch": batch,
            "status": status,
        }
        return self._upsert(key, "render", fields.get("final_filename") or "", **fields)

    def record_drive(
        self,
        video_id: Optional[str] = None,
        final_filename: str = "",
        drive_folder: str = "",
        drive_path: Optional[Union[str, Path]] = None,
        file_id: str = "",
        link: str = "",
        thumbnail_path: Optional[Union[str, Path]] = None,
        thumbnail_link: str = "",
        source_url: Optional[Union[str, Path]] = None,
        local_path: Optional[Union[str, Path]] = None,
        status: str = "uploaded",
    ) -> Dict[str, Any]:
        """Record a Google Drive copy/upload (mounted path and/or API link)."""
        if not final_filename and drive_path:
            final_filename = Path(drive_path).name
        if not drive_folder and drive_path:
            drive_folder = drive_relative(Path(drive_path).parent)

        key = ""
        if not video_id and not source_url and not local_path and final_filename:
            # We only have a Drive filename: attach to an existing render row.
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT video_id FROM videos WHERE final_filename = ? OR drive_filename = ? LIMIT 1",
                    (final_filename, final_filename),
                ).fetchone()
                if row:
                    key = row["video_id"]
        if not key:
            key = self.resolve_video_id(
                video_id=video_id,
                source_url=source_url or local_path,
                local_path=local_path,
            )
            if key.startswith("local:") and not video_id and final_filename:
                with self._connect() as conn:
                    row = conn.execute(
                        "SELECT video_id FROM videos WHERE final_filename = ? OR drive_filename = ? LIMIT 1",
                        (final_filename, final_filename),
                    ).fetchone()
                    if row:
                        key = row["video_id"]

        fields: Dict[str, Any] = {
            "final_filename": final_filename,
            "drive_folder": drive_folder,
            "drive_path": str(drive_path) if drive_path else "",
            "drive_file_id": file_id,
            "drive_link": link,
            "thumbnail_path": _norm_path(thumbnail_path) if thumbnail_path else "",
            "thumbnail_link": thumbnail_link,
            "status": status,
        }

        # A renamed/truncated Drive copy must not overwrite the render filename.
        if final_filename:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT final_filename FROM videos WHERE video_id = ?", (key,)
                ).fetchone()
            current = (row["final_filename"] or "").strip() if row else ""
            if current and current != final_filename:
                fields["drive_filename"] = final_filename
                fields.pop("final_filename", None)

        if status == "uploaded":
            fields["uploaded_at"] = _now()
        return self._upsert(key, "drive", str(drive_path or link), **fields)

    def record_failure(
        self,
        error: str,
        video_id: Optional[str] = None,
        source_url: Optional[Union[str, Path]] = None,
        local_path: Optional[Union[str, Path]] = None,
    ) -> Dict[str, Any]:
        key = self.resolve_video_id(
            video_id=video_id, source_url=source_url or local_path, local_path=local_path
        )
        return self._upsert(key, "failure", error, status="failed", error=error)

    def record_skip(
        self,
        reason: str,
        video_id: Optional[str] = None,
        source_url: Optional[Union[str, Path]] = None,
        local_path: Optional[Union[str, Path]] = None,
    ) -> Dict[str, Any]:
        """Record a video that was intentionally not processed (e.g. too long)."""
        key = self.resolve_video_id(
            video_id=video_id, source_url=source_url or local_path, local_path=local_path
        )
        return self._upsert(key, "skip", reason, status="skipped", error=reason)

    def record_movie(
        self,
        movie_name: str,
        movie_year: Optional[Any] = None,
        movie_genre: str = "",
        movie_synopsis: str = "",
        movie_context: str = "",
        movie_source: str = "",
        movie_source_url: str = "",
        video_id: Optional[str] = None,
        source_url: Optional[Union[str, Path]] = None,
        local_path: Optional[Union[str, Path]] = None,
        channel: str = "",
        batch: str = "",
    ) -> Dict[str, Any]:
        """
        Upsert a movie row and link it to a specific video.
        Returns {} when no movie name is known.
        """
        name = (movie_name or "").strip()
        if not name:
            return {}

        year: Optional[int] = None
        if movie_year not in (None, ""):
            try:
                year = int(str(movie_year)[:4])
                if not (1900 <= year <= 2100):
                    year = None
            except Exception:
                year = None

        key = _movie_key(name, year)
        now = _now()
        details: Dict[str, Any] = {
            "movie_name": name,
            "movie_year": year,
            "movie_genre": movie_genre.strip(),
            "movie_synopsis": movie_synopsis.strip(),
            "movie_context": movie_context.strip(),
            "movie_source": movie_source.strip(),
            "movie_source_url": movie_source_url.strip(),
        }

        with self._connect() as conn:
            row = conn.execute("SELECT * FROM movies WHERE movie_key = ?", (key,)).fetchone()
            if not row and year:
                # Adopt an earlier year-less row for the same movie.
                row = conn.execute(
                    "SELECT * FROM movies WHERE movie_name = ? AND movie_year IS NULL ORDER BY id DESC LIMIT 1",
                    (name,),
                ).fetchone()
                if row:
                    conn.execute(
                        "UPDATE movies SET movie_key = ?, movie_year = ? WHERE id = ?",
                        (key, year, row["id"]),
                    )
                    row = conn.execute("SELECT * FROM movies WHERE id = ?", (row["id"],)).fetchone()

            if row:
                movie_id = row["id"]
                updates = {
                    column: value
                    for column, value in details.items()
                    if value not in (None, "")
                }
                updates["updated_at"] = now
                assignments = ", ".join(f"{column} = ?" for column in updates)
                conn.execute(
                    f"UPDATE movies SET {assignments} WHERE id = ?",
                    (*updates.values(), movie_id),
                )
            else:
                cursor = conn.execute(
                    "INSERT INTO movies (movie_key, movie_name, movie_year, movie_genre, "
                    "movie_synopsis, movie_context, movie_source, movie_source_url, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        key,
                        name,
                        year,
                        details["movie_genre"],
                        details["movie_synopsis"],
                        details["movie_context"],
                        details["movie_source"],
                        details["movie_source_url"],
                        now,
                        now,
                    ),
                )
                movie_id = cursor.lastrowid
            conn.commit()

        video_key = self.resolve_video_id(
            video_id=video_id, source_url=source_url, local_path=local_path
        )
        linked_fields: Dict[str, Any] = {
            "movie_id": movie_id,
            "channel": channel,
            "batch": batch,
            **{column: value for column, value in details.items() if value not in (None, "")},
        }
        self._upsert(video_key, "movie", f"{name} ({year or 'unknown year'})", **linked_fields)

        return {"movie_id": movie_id, "movie_key": key, **details}

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def get(self, video_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM videos WHERE video_id = ?", (video_id,)).fetchone()
        return dict(row) if row else None

    def find_by_local_path(self, local_path: Union[str, Path]) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM videos WHERE local_path = ? LIMIT 1", (_norm_path(local_path),)
            ).fetchone()
        return dict(row) if row else None

    def find_by_final_filename(self, filename: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM videos WHERE final_filename = ? OR drive_filename = ? LIMIT 1",
                (filename, filename),
            ).fetchone()
        return dict(row) if row else None

    def list(
        self,
        status: Optional[str] = None,
        channel: Optional[str] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        clauses: List[str] = []
        params: List[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if channel:
            clauses.append("channel = ?")
            params.append(channel)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM videos {where} ORDER BY id DESC LIMIT ?", params
            ).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> Dict[str, Any]:
        with self._connect() as conn:
            status_rows = conn.execute(
                "SELECT status, COUNT(*) AS count FROM videos GROUP BY status"
            ).fetchall()
            channel_rows = conn.execute(
                "SELECT channel, COUNT(*) AS count FROM videos "
                "WHERE channel IS NOT NULL AND channel != '' GROUP BY channel ORDER BY count DESC"
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) AS count FROM videos").fetchone()["count"]
            linked = conn.execute(
                "SELECT COUNT(*) AS count FROM videos WHERE drive_link IS NOT NULL AND drive_link != ''"
            ).fetchone()["count"]
            uploaded = conn.execute(
                "SELECT COUNT(*) AS count FROM videos WHERE status = 'uploaded'"
            ).fetchone()["count"]
            movies = conn.execute("SELECT COUNT(*) AS count FROM movies").fetchone()["count"]
            with_movie = conn.execute(
                "SELECT COUNT(*) AS count FROM videos WHERE movie_name IS NOT NULL AND movie_name != ''"
            ).fetchone()["count"]
        return {
            "database": str(self.db_path),
            "snapshot_dir": str(self.snapshot_dir),
            "total": total,
            "uploaded": uploaded,
            "with_drive_link": linked,
            "with_movie": with_movie,
            "movies": movies,
            "by_status": {row["status"]: row["count"] for row in status_rows},
            "by_channel": {row["channel"]: row["count"] for row in channel_rows},
        }

    def list_movies(self, limit: int = 500) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT m.*, COUNT(v.id) AS video_count "
                "FROM movies m LEFT JOIN videos v ON v.movie_id = m.id "
                "GROUP BY m.id ORDER BY m.id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [dict(row) for row in rows]

    def find_movie(self, name: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM movies WHERE lower(movie_name) = lower(?) "
                "ORDER BY id DESC LIMIT 1",
                (name.strip(),),
            ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Snapshot exports
    # ------------------------------------------------------------------
    def _rows_for_export(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM videos ORDER BY id ASC").fetchall()
        return [dict(row) for row in rows]

    def _atomic_write(self, target: Path, writer) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f"{target.name}.tmp")
        writer(tmp)
        os.replace(tmp, target)

    def export(
        self,
        json_path: Optional[Union[str, Path]] = None,
        csv_path: Optional[Union[str, Path]] = None,
        include_db_backup: bool = False,
    ) -> Dict[str, str]:
        """Write JSON + CSV snapshots locally, then mirror them to Drive."""
        rows = self._rows_for_export()
        json_target = Path(json_path) if json_path else self.snapshot_dir / "video_registry.json"
        csv_target = Path(csv_path) if csv_path else self.snapshot_dir / "video_registry.csv"

        payload = {
            "generated_at": _now(),
            "database": str(self.db_path),
            "count": len(rows),
            "videos": rows,
        }

        self._atomic_write(
            json_target,
            lambda tmp: tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"),
        )

        fieldnames = list(rows[0].keys()) if rows else [
            "video_id", "source_url", "channel", "batch", "final_filename", "title",
            "status", "drive_folder", "drive_path", "drive_link", "created_at", "updated_at",
        ]

        def _write_csv(tmp: Path) -> None:
            with open(tmp, "w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                for row in rows:
                    writer.writerow(row)

        self._atomic_write(csv_target, _write_csv)

        outputs = {"json": str(json_target), "csv": str(csv_target)}

        if include_db_backup:
            # Flush WAL first so the copied .db contains every committed row.
            try:
                with self._connect() as conn:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    conn.commit()
            except Exception as exc:
                print(f"[Registry] Warning: WAL checkpoint failed ({exc})")
            db_backup = self.snapshot_dir / "video_registry.db"
            self._atomic_write(db_backup, lambda tmp: shutil.copy2(str(self.db_path), str(tmp)))
            outputs["db"] = str(db_backup)

        if self.sync_drive:
            env_dir = os.getenv("VIDEO_REGISTRY_DRIVE_DIR", "").strip()
            drive_dir = Path(env_dir) if env_dir else None
            if drive_dir is None:
                drive_base = resolve_drive_base()
                drive_dir = (drive_base / DRIVE_SNAPSHOT_SUBDIR) if drive_base else None
            if drive_dir is not None:
                try:
                    drive_dir.mkdir(parents=True, exist_ok=True)
                    for key, local_file in outputs.items():
                        dest = drive_dir / Path(local_file).name
                        tmp = dest.with_name(f"{dest.name}.tmp")
                        shutil.copy2(local_file, tmp)
                        os.replace(tmp, dest)
                    outputs["drive_dir"] = str(drive_dir)
                except Exception as exc:
                    outputs["drive_sync_error"] = str(exc)

        return outputs

    def _after_write(self) -> None:
        if not self.auto_export:
            return
        try:
            self.export(include_db_backup=False)
        except Exception as exc:
            print(f"[Registry] Warning: snapshot export failed ({exc})")


_DEFAULT_REGISTRY: Optional[VideoRegistry] = None


def get_registry() -> VideoRegistry:
    """Process-wide default registry (honours VIDEO_REGISTRY_DB)."""
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = VideoRegistry()
    return _DEFAULT_REGISTRY
