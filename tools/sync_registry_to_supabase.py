#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/sync_registry_to_supabase.py
==================================
Exports and synchronizes the local SQLite video registry (output/video_registry.db)
to Supabase PostgreSQL cloud database in real-time.

Tables Synchronized:
  - videos  -> public.video_registry (on conflict video_id)
  - movies  -> public.registry_movies (on conflict movie_key)
  - events  -> public.registry_events

Usage:
  python tools/sync_registry_to_supabase.py --sync-all
  python tools/sync_registry_to_supabase.py --stats
  python tools/sync_registry_to_supabase.py --videos-only
  python tools/sync_registry_to_supabase.py --db "output/video_registry.db"
"""

import argparse
import json
import logging
import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Setup pathing
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.supabase_logger import get_supabase_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sync_registry_to_supabase")

DEFAULT_DB_PATH = PROJECT_ROOT / "output" / "video_registry.db"


def fetch_supabase_count(table_name: str, config: Dict[str, Any]) -> int:
    """Returns row count for a table in Supabase."""
    url = f"{config['supabase_url']}/rest/v1/{table_name}?select=count"
    req = urllib.request.Request(
        url,
        headers={
            "apikey": config["supabase_key"],
            "Authorization": f"Bearer {config['supabase_key']}",
            "Range-Unit": "items",
            "Range": "0-0",
            "Prefer": "count=exact"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            content_range = resp.headers.get("Content-Range", "")
            if "/" in content_range:
                total_str = content_range.split("/")[-1]
                if total_str.isdigit():
                    return int(total_str)
            return 0
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return -1  # Table doesn't exist yet
        logger.warning(f"Failed to fetch count for {table_name}: {e.code} {e.reason}")
        return 0
    except Exception as e:
        logger.warning(f"Error checking {table_name}: {e}")
        return 0


def postgrest_batch_upsert(
    table_name: str,
    records: List[Dict[str, Any]],
    on_conflict: str,
    config: Dict[str, Any],
    chunk_size: int = 50
) -> int:
    """Batch upserts records into Supabase via PostgREST."""
    if not records:
        return 0

    url = f"{config['supabase_url']}/rest/v1/{table_name}"
    if on_conflict:
        url += f"?on_conflict={urllib.parse.quote(on_conflict)}"

    headers = {
        "apikey": config["supabase_key"],
        "Authorization": f"Bearer {config['supabase_key']}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal"
    }

    synced_total = 0
    for i in range(0, len(records), chunk_size):
        chunk = records[i : i + chunk_size]
        body = json.dumps(chunk, default=str).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status in (200, 201, 204):
                    synced_total += len(chunk)
                    logger.info(f"  [{table_name}] Synced batch {i + 1}..{min(i + chunk_size, len(records))} ({len(chunk)} rows)")
                else:
                    logger.warning(f"  [{table_name}] HTTP {resp.status} for batch {i + 1}")
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            if e.code == 404:
                logger.error(f"  [{table_name}] Table does not exist in Supabase! Please run tools/create_video_registry_tables.sql in Supabase SQL Editor.")
                return -1
            logger.error(f"  [{table_name}] Upsert failed HTTP {e.code}: {err_body}")
        except Exception as e:
            logger.error(f"  [{table_name}] Network/request error: {e}")

    return synced_total


def sanitize_video_record(row: Dict[str, Any]) -> Dict[str, Any]:
    """Cleans a SQLite video row for Supabase ingestion."""
    clean = {}
    for k, v in row.items():
        if k == "id":
            continue  # Let Supabase manage id or use video_id as external key
        if v is None:
            clean[k] = None
        elif isinstance(v, (int, float)):
            clean[k] = v
        else:
            clean[k] = str(v)

    # Validate timestamps
    for dt_col in ("created_at", "updated_at", "uploaded_at"):
        val = clean.get(dt_col)
        if val and not isinstance(val, datetime):
            try:
                # Ensure ISO-8601 UTC
                dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
                clean[dt_col] = dt.isoformat()
            except Exception:
                if dt_col != "uploaded_at":
                    clean[dt_col] = datetime.now(timezone.utc).isoformat()
                else:
                    clean[dt_col] = None
    return clean


def sanitize_movie_record(row: Dict[str, Any]) -> Dict[str, Any]:
    clean = {}
    for k, v in row.items():
        if k == "id":
            continue
        clean[k] = v
    return clean


def sanitize_event_record(row: Dict[str, Any]) -> Dict[str, Any]:
    clean = {}
    for k, v in row.items():
        if k == "id":
            continue
        clean[k] = v
    return clean


def sync_registry(
    db_path: Path,
    sync_videos: bool = True,
    sync_movies: bool = True,
    sync_events: bool = True,
    dry_run: bool = False
) -> Dict[str, int]:
    """Reads SQLite database and pushes all records to Supabase."""
    if not db_path.exists():
        logger.error(f"SQLite database not found at: {db_path}")
        return {"error": "DB not found"}

    cfg = get_supabase_config()
    if not cfg.get("enabled") or not cfg.get("supabase_url") or not cfg.get("supabase_key"):
        logger.error("Supabase is not configured! Check .env or config/supabase_config.json")
        return {"error": "Supabase not configured"}

    logger.info(f"Connecting to SQLite: {db_path}")
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    results = {}

    # 1. Sync Movies first (referenced by videos)
    if sync_movies:
        try:
            cur.execute("SELECT * FROM movies")
            movie_rows = [dict(r) for r in cur.fetchall()]
            logger.info(f"Found {len(movie_rows)} movie record(s) in SQLite")
            if dry_run:
                logger.info(f"[Dry Run] Would sync {len(movie_rows)} movies")
                results["movies"] = len(movie_rows)
            else:
                clean_movies = [sanitize_movie_record(r) for r in movie_rows]
                results["movies"] = postgrest_batch_upsert("registry_movies", clean_movies, on_conflict="movie_key", config=cfg)
        except Exception as e:
            logger.error(f"Error reading movies table: {e}")
            results["movies"] = 0

    # 2. Sync Videos
    if sync_videos:
        try:
            cur.execute("SELECT * FROM videos")
            video_rows = [dict(r) for r in cur.fetchall()]
            logger.info(f"Found {len(video_rows)} video record(s) in SQLite")
            if dry_run:
                logger.info(f"[Dry Run] Would sync {len(video_rows)} videos")
                results["videos"] = len(video_rows)
            else:
                clean_videos = [sanitize_video_record(r) for r in video_rows]
                results["videos"] = postgrest_batch_upsert("video_registry", clean_videos, on_conflict="video_id", config=cfg)
        except Exception as e:
            logger.error(f"Error reading videos table: {e}")
            results["videos"] = 0

    # 3. Sync Events
    if sync_events:
        try:
            cur.execute("SELECT * FROM events")
            event_rows = [dict(r) for r in cur.fetchall()]
            logger.info(f"Found {len(event_rows)} event record(s) in SQLite")
            if dry_run:
                logger.info(f"[Dry Run] Would sync {len(event_rows)} events")
                results["events"] = len(event_rows)
            else:
                clean_events = [sanitize_event_record(r) for r in event_rows]
                results["events"] = postgrest_batch_upsert("registry_events", clean_events, on_conflict="", config=cfg)
        except Exception as e:
            logger.error(f"Error reading events table: {e}")
            results["events"] = 0

    con.close()
    return results


def print_stats(db_path: Path):
    """Compares SQLite local record counts against Supabase cloud counts."""
    cfg = get_supabase_config()
    print("\n" + "=" * 65)
    print("VIDEO REGISTRY DATABASE COMPARISON: SQLite vs Supabase")
    print("=" * 65)
    print(f"Local SQLite: {db_path}")
    print(f"Cloud Supabase: {cfg.get('supabase_url')}")
    print("-" * 65)

    if not db_path.exists():
        print(f"Local database not found: {db_path}")
        return

    con = sqlite3.connect(str(db_path))
    cur = con.cursor()

    tables = [
        ("videos", "video_registry"),
        ("movies", "registry_movies"),
        ("events", "registry_events"),
    ]

    for local_tbl, cloud_tbl in tables:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {local_tbl}")
            local_count = cur.fetchone()[0]
        except Exception:
            local_count = 0

        cloud_count = fetch_supabase_count(cloud_tbl, cfg)
        status = "OK" if local_count == cloud_count else "PENDING SYNC"
        if cloud_count == -1:
            cloud_str = "NOT CREATED (Run SQL)"
            status = "ACTION REQUIRED"
        else:
            cloud_str = str(cloud_count)

        print(f"Table: {local_tbl:<10} -> {cloud_tbl:<18} | Local: {local_count:<5} | Supabase: {cloud_str:<8} [{status}]")

    print("=" * 65 + "\n")
    con.close()


def main():
    parser = argparse.ArgumentParser(description="Synchronize SQLite Video Registry to Supabase Cloud")
    parser.add_argument("--db", type=str, default=str(DEFAULT_DB_PATH), help="Path to SQLite video_registry.db")
    parser.add_argument("--sync-all", action="store_true", help="Sync videos, movies, and events")
    parser.add_argument("--videos-only", action="store_true", help="Sync videos only")
    parser.add_argument("--movies-only", action="store_true", help="Sync movies only")
    parser.add_argument("--events-only", action="store_true", help="Sync events only")
    parser.add_argument("--stats", action="store_true", help="Display local vs cloud record counts")
    parser.add_argument("--dry-run", action="store_true", help="Simulate sync without uploading")

    args = parser.parse_args()
    db_path = Path(args.db)

    if args.stats or (not args.sync_all and not args.videos_only and not args.movies_only and not args.events_only):
        print_stats(db_path)
        if not args.sync_all and not args.videos_only and not args.movies_only and not args.events_only:
            print("Tip: Run with --sync-all to push all SQLite records to Supabase.\n")
            return

    sync_v = args.sync_all or args.videos_only
    sync_m = args.sync_all or args.movies_only
    sync_e = args.sync_all or args.events_only

    results = sync_registry(db_path, sync_videos=sync_v, sync_movies=sync_m, sync_events=sync_e, dry_run=args.dry_run)
    print("\nSync Results:")
    for k, v in results.items():
        print(f"  {k}: {v} row(s) synced")


if __name__ == "__main__":
    main()
