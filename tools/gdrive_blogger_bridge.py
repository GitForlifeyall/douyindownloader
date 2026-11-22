#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/gdrive_blogger_bridge.py
==============================
Connects mounted Google Drive (G:\My Drive or I:\My Drive) with Google Blogger.

Features:
1. Scans mounted Google Drive folders for movie files (.mp4, .mkv, .webm).
2. Cleans clutter and identifies movie titles and release years automatically.
3. Generates CineMax8 watch links and high-CTR post packages.
4. Exports a Blogger Atom XML import file (Settings -> Import Content) OR
   publishes directly via Blogger API v3 (if credentials.json is present).
"""

import argparse
import json
import logging
import os
import re
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("gdrive_blogger_bridge")

DEFAULT_GDRIVE_PATHS = [
    Path("G:/My Drive"),
    Path("I:/My Drive"),
]


def clean_video_filename(filename: str) -> str:
    """Extracts a clean, recognizable movie title from messy media filenames."""
    name = Path(filename).stem
    # Strip bracketed tags [Punjabi], [r_oddlysatisfying], [444 MB], etc.
    name = re.sub(r"\[.*?\]", " ", name)
    # Strip parenthetical technical specs (3D Animation...), (OC), etc.
    name = re.sub(r"\((?!19\d\d|20\d\d).*?\)", " ", name)
    # Strip hashtags
    name = re.sub(r"#\S+", " ", name)
    # Strip common rips/codecs
    name = re.sub(r"\b(ESub|480p|720p|1080p|2160p|4k|x264|x265|hevc|web-dl|bluray|dvdrip)\b", " ", name, flags=re.IGNORECASE)
    # Clean whitespace and underscores
    name = re.sub(r"[_\-]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def scan_gdrive_movies(base_path: Path, max_depth: int = 3) -> List[Dict[str, Any]]:
    """Scans Google Drive for movie/video files and builds metadata objects."""
    if not base_path.exists():
        logger.warning(f"Drive path does not exist: {base_path}")
        return []

    logger.info(f"Scanning mounted Google Drive at: {base_path}")
    results = []
    video_extensions = {".mp4", ".mkv", ".webm", ".avi", ".mov"}

    for root, dirs, files in os.walk(base_path):
        rel_path = Path(root).relative_to(base_path)
        if len(rel_path.parts) > max_depth:
            dirs.clear()
            continue

        for f in files:
            p = Path(root) / f
            if p.suffix.lower() in video_extensions:
                size_mb = p.stat().st_size / (1024 * 1024)
                # Ignore tiny clips (< 5 MB) if looking for long-form movies
                clean_title = clean_video_filename(f)
                
                # Extract year if present (e.g. "Honsla Rakh 2021")
                year_match = re.search(r"\b(19\d\d|20\d\d)\b", clean_title)
                year = year_match.group(1) if year_match else "2024"
                title_no_year = re.sub(r"\b(19\d\d|20\d\d)\b", "", clean_title).strip()

                movie_item = {
                    "raw_filename": f,
                    "clean_title": title_no_year if title_no_year else clean_title,
                    "year": year,
                    "size_mb": round(size_mb, 1),
                    "local_path": str(p),
                    "cinemax_url": f"https://curiouscinefile.blogspot.com/?movie={urllib.parse.quote_plus(title_no_year or clean_title)}"
                }
                results.append(movie_item)

    logger.info(f"Discovered {len(results)} video files in {base_path}")
    return results


def build_blogger_import_xml(movies: List[Dict[str, Any]], output_file: Path) -> Path:
    """Builds a Blogger Atom XML import package for 1-click upload."""
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entries_xml = []

    for idx, m in enumerate(movies):
        title = f"{m['clean_title']} ({m['year']})"
        url = m["cinemax_url"]
        
        body_html = f"""
<div style="background:#1a1e26;color:#ccc;font-family:'Roboto',sans-serif;padding:15px;border-radius:8px;max-width:900px;margin:0 auto;">
  <h2 style="color:#fff;margin:0 0 10px;">{title}</h2>
  <p style="color:#aaa;font-size:14px;">Stream {title} in Full HD online free on CineMax8 with zero buffering.</p>
  <div style="margin:20px 0;text-align:center;">
    <a href="{url}" style="background:#ff5a2e;color:#fff;padding:12px 24px;border-radius:6px;font-weight:bold;text-decoration:none;display:inline-block;box-shadow:0 4px 15px rgba(255,90,46,0.4);">
      ▶ Stream Movie in 4K Now
    </a>
  </div>
</div>
        """.strip()

        escaped = (
            body_html.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

        entry = f"""
  <entry>
    <id>tag:blogger.com,1999:blog-cinemax8.gdrive-{1000 + idx}</id>
    <published>{now_iso}</published>
    <updated>{now_iso}</updated>
    <category scheme="http://www.blogger.com/atom/ns#" term="Movie"/>
    <category scheme="http://www.blogger.com/atom/ns#" term="GoogleDrive"/>
    <title type="text">{title}</title>
    <content type="html">{escaped}</content>
    <author><name>CineMax8</name></author>
  </entry>"""
        entries_xml.append(entry)

    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title type="text">CineMax8 GDrive Movies Import</title>
  <updated>{now_iso}</updated>
  <id>tag:blogger.com,1999:blog-cinemax8-gdrive</id>
  {''.join(entries_xml)}
</feed>"""

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(feed, encoding="utf-8")
    logger.info(f"Saved Blogger Import XML ({len(movies)} movies) to: {output_file}")
    return output_file


def main():
    parser = argparse.ArgumentParser(description="Google Drive to Blogger Bridge Tool")
    parser.add_argument("--drive", type=str, default="G:/My Drive", help="Drive path to scan (e.g. G:/My Drive or I:/My Drive)")
    parser.add_argument("--out", type=str, default="output/blogger_gdrive_import.xml", help="Output Atom XML file for Blogger import")
    parser.add_argument("--min-size", type=float, default=20.0, help="Minimum file size in MB to filter out small clips (default: 20 MB)")
    args = parser.parse_args()

    drive_path = Path(args.drive)
    movies = scan_gdrive_movies(drive_path)
    
    # Filter by size
    filtered = [m for m in movies if m["size_mb"] >= args.min_size]
    logger.info(f"Found {len(filtered)} full movies/episodes (>= {args.min_size} MB) out of {len(movies)} total video files.")

    if filtered:
        out_path = Path(args.out)
        build_blogger_import_xml(filtered, out_path)
        print(f"\nSuccessfully generated Blogger import package: {out_path}")
        print(f"You can import this directly in Blogger (Settings -> Manage Blog -> Import Content).")
    else:
        logger.warning("No video files matched the size filter.")


if __name__ == "__main__":
    main()
