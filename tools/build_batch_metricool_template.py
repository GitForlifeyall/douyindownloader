#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build a Metricool calendar CSV *template* for a rendered batch.

Reads the canonical Metricool header from the local calendar template and the
batch `metadata.json` (schema: {number_of_videos, videos:[{title, description, tags}]}),
then emits one row per video with:

    Text                <- description
    Youtube Video Title <- title
    Youtube Video Tags  <- tags (comma separated)

`Date`, `Time` and `Picture Url 1` (the Google Drive video link) are intentionally
left BLANK so they can be filled in at scheduling time.

Outputs:
    I:\\My Drive\\douyin\\channel pending movies\\<batch>\\metricool_schedule_template.csv
    output\\<batch>\\metricool_schedule_template.csv
"""

import csv
import json
from pathlib import Path

TEMPLATE_CSV = Path(r"c:\Users\rudra\Downloads\Mtr_calendar_template.csv")
DRIVE_PENDING_ROOT = Path(r"I:\My Drive\douyin\channel pending movies")

BATCH_NAME = "batch_1"
OUT_FILENAME = "metricool_schedule_template.csv"

# YouTube defaults for a movie-recap Shorts channel (title/description/tags come from metadata)
YOUTUBE_DEFAULTS = {
    "Youtube": "true",
    "Youtube Video Type": "SHORT",
    "Youtube Video Privacy": "PUBLIC",
    "Youtube video for kids": "false",
    "Youtube AI generated content": "true",
    "Youtube notify subscribers": "true",
    "Youtube Video Category": "FILM_ANIMATION",
}


def load_headers() -> list[str]:
    with TEMPLATE_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        return next(csv.reader(f))


def write_csv(path: Path, headers: list[str], rows: list[dict[str, str]]) -> Path:
    """Write CSV with UTF-8 BOM, falling back to a *_new file if locked open."""
    path.parent.mkdir(parents=True, exist_ok=True)
    target = path
    try:
        with target.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
    except PermissionError:
        target = path.with_name(path.stem + "_new" + path.suffix)
        with target.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {target}")
    return target


def main() -> None:
    headers = load_headers()

    drive_batch_dir = DRIVE_PENDING_ROOT / BATCH_NAME
    metadata_path = drive_batch_dir / "metadata.json"
    meta = json.loads(metadata_path.read_text(encoding="utf-8"))
    videos = meta.get("videos", [])

    rows: list[dict[str, str]] = []
    for vid in videos:
        title = str(vid.get("title") or "").strip()
        description = str(vid.get("description") or "").strip()
        tags = [str(t).strip() for t in (vid.get("tags") or []) if str(t).strip()]

        row = {h: "" for h in headers}
        row.update(YOUTUBE_DEFAULTS)
        row.update(
            {
                "Text": description,
                "Youtube Video Title": title,
                "Youtube Video Tags": ", ".join(tags),
                # Date, Time, Picture Url 1 (Drive link) intentionally left blank
            }
        )
        rows.append(row)

    write_csv(drive_batch_dir / OUT_FILENAME, headers, rows)
    write_csv(Path("output") / BATCH_NAME / OUT_FILENAME, headers, rows)


if __name__ == "__main__":
    main()
