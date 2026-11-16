#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Self-check for dubbing_studio.video_registry.

Run with:  python tests/test_video_registry.py
No pytest required. Uses a throwaway DB inside tests/test_artifacts/.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dubbing_studio.video_registry import (  # noqa: E402
    VideoRegistry,
    drive_relative,
    extract_video_id,
)

ARTIFACTS = ROOT / "tests" / "test_artifacts"
ARTIFACTS.mkdir(parents=True, exist_ok=True)
DB_PATH = ARTIFACTS / "registry_selfcheck.db"


def _cleanup() -> None:
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(DB_PATH) + suffix)
        if candidate.exists():
            candidate.unlink()
    snapshot_dir = ARTIFACTS / "video_registry"
    if snapshot_dir.exists():
        for child in snapshot_dir.iterdir():
            child.unlink()
        snapshot_dir.rmdir()


def run() -> None:
    _cleanup()
    reg = VideoRegistry(db_path=DB_PATH, auto_export=False, sync_drive=False)

    url = "https://www.douyin.com/video/7558092762407652668"
    video_id = "7558092762407652668"
    assert extract_video_id(url) == video_id
    assert drive_relative(Path(r"I:\My Drive\douyin\batch_1\clip.mp4").parent) == r"douyin\batch_1"

    reg.record_download(
        source_url=url,
        local_path=r"C:\x\input\batch_1\7558092762407652668.mp4",
        batch="batch_1",
    )
    reg.record_render(
        video_id=video_id,
        final_video=r"C:\x\output\batch_1\Long Rendered Title.mp4",
        title="Long Rendered Title",
        language="English",
        tts_engine="elevenlabs",
        metadata={"title": "Long Rendered Title", "tags": ["movie"]},
    )
    reg.record_movie(
        "The Odyssey",
        movie_year=2026,
        movie_genre="epic",
        movie_synopsis="A hero returns home.",
        video_id=video_id,
        channel="batch_1",
        batch="batch_1",
    )
    # Mounted Drive copy has a truncated filename and only a path.
    reg.record_drive(
        video_id=video_id,
        drive_path=r"I:\My Drive\douyin\batch_1\Long Rendered Title.mp4",
        link="https://drive.google.com/file/d/abc/view",
        file_id="abc",
    )

    row = reg.get(video_id)
    assert row["source_url"] == url, row["source_url"]
    assert row["status"] == "uploaded", row["status"]
    assert row["movie_name"] == "The Odyssey", row["movie_name"]
    assert row["movie_year"] == 2026
    assert row["drive_folder"] == r"douyin\batch_1", row["drive_folder"]
    assert row["drive_filename"] is None  # same name: no separate Drive name needed
    assert row["final_filename"] == "Long Rendered Title.mp4"

    # A renamed Drive copy must keep the render filename intact.
    reg.record_drive(
        video_id=video_id,
        drive_path=r"I:\My Drive\douyin\batch_1\Long Rendered.mp4",
    )
    row = reg.get(video_id)
    assert row["final_filename"] == "Long Rendered Title.mp4", row["final_filename"]
    assert row["drive_filename"] == "Long Rendered.mp4", row["drive_filename"]
    assert reg.find_by_final_filename("Long Rendered.mp4")["video_id"] == video_id

    stats = reg.stats()
    assert stats["total"] == 1, stats
    assert stats["movies"] == 1, stats
    assert stats["with_movie"] == 1, stats
    assert reg.list_movies()[0]["video_count"] == 1

    outputs = reg.export(include_db_backup=True)
    assert Path(outputs["json"]).exists()
    assert Path(outputs["csv"]).exists()
    assert Path(outputs["db"]).exists()

    _cleanup()
    print("video_registry self-check passed")


if __name__ == "__main__":
    run()
