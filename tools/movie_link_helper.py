#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/movie_link_helper.py
===========================
Helper tool to generate dynamic CineMax8 (Method 1) streaming links,
pinned comment CTAs, and YouTube/Facebook description snippets.

Usage:
    # Single movie:
    python tools/movie_link_helper.py --movie "The Matrix"
    python tools/movie_link_helper.py --movie "The Odyssey"

    # Batch from metadata.json:
    python tools/movie_link_helper.py --metadata "I:\\My Drive\\douyin\\channel pending movies\\metadata.json"
"""

import argparse
import json
import re
import urllib.parse
from pathlib import Path

BLOG_BASE_URL = "https://curiouscinefile.blogspot.com/"


def clean_movie_title(raw_title: str) -> str:
    """Clean raw channel/video titles by stripping tags, hashtags, and clutter."""
    t = re.sub(r"\[.*?\]", "", raw_title)
    t = re.sub(r"\(\s*3d animation in english\s*\)", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\(\s*3d animation in hindi\s*\)", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\(\s*3d animation\s*\)", "", t, flags=re.IGNORECASE)
    t = re.sub(r"#\S+", "", t)
    t = re.sub(r"[_\-]+", " ", t)
    t = re.sub(r"\s{2,}", " ", t)
    return t.strip()


def generate_cinemax_link(title: str) -> str:
    """Generate dynamic CineMax8 Method 1 query URL."""
    clean = clean_movie_title(title)
    encoded = urllib.parse.quote_plus(clean)
    return f"{BLOG_BASE_URL}?movie={encoded}"


def format_social_snippets(title: str) -> dict:
    """Format high-CTR CTA snippets for YouTube, Facebook, and pinned comments."""
    clean = clean_movie_title(title)
    url = generate_cinemax_link(clean)

    pinned_comment = (
        f"🍿 Watch \"{clean}\" in Full HD (Free & Instant):\n"
        f"👉 {url}\n\n"
        f"Enjoy streaming! Comment your favorite scene below 👇🎬"
    )

    caption_cta = (
        f"Comment \"MOVIE\" for the link, or watch \"{clean}\" directly in HD:\n"
        f"🍿 {url} #MovieRecap #MovieExplained #Shorts"
    )

    yt_description_block = (
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🍿 WATCH FULL MOVIE IN FULL HD:\n"
        f"👉 {url}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    return {
        "title": clean,
        "url": url,
        "pinned_comment": pinned_comment,
        "caption_cta": caption_cta,
        "yt_description_block": yt_description_block
    }


def process_metadata_file(meta_path: Path):
    if not meta_path.exists():
        print(f"Error: {meta_path} does not exist.")
        return

    data = json.loads(meta_path.read_text(encoding="utf-8"))
    videos = data.get("videos", [])
    print(f"\nProcessing {len(videos)} videos from {meta_path.name}...\n")

    results = []
    for idx, v in enumerate(videos, 1):
        raw_title = v.get("title", "")
        snips = format_social_snippets(raw_title)
        results.append(snips)
        print(f"[{idx}/{len(videos)}] {snips['title']}")
        print(f"  🔗 URL: {snips['url']}\n")

    out_file = Path("output/cinemax8_links_export.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved complete links mapping ({len(results)} movies) to {out_file}")


def main():
    parser = argparse.ArgumentParser(description="CineMax8 Dynamic Movie Link Generator")
    parser.add_argument("--movie", type=str, help="Movie title (e.g. 'The Matrix')")
    parser.add_argument("--metadata", type=str, help="Path to metadata.json to process in batch")
    args = parser.parse_args()

    if args.movie:
        snips = format_social_snippets(args.movie)
        print("\n" + "=" * 60)
        print(f"  CINEMAX8 DYNAMIC LINK GENERATOR: {snips['title']}")
        print("=" * 60)
        print(f"\n🔗 DIRECT STREAMING LINK:\n{snips['url']}")
        print(f"\n📌 HIGH-CTR PINNED COMMENT:\n{snips['pinned_comment']}")
        print(f"\n📱 SOCIAL CAPTION / DM AUTO-REPLY:\n{snips['caption_cta']}")
        print(f"\n📺 YOUTUBE DESCRIPTION SNIPPET:\n{snips['yt_description_block']}")
        print("=" * 60 + "\n")
    elif args.metadata:
        process_metadata_file(Path(args.metadata))
    else:
        # Default test showcase
        for title in ["The Odyssey", "The Matrix", "Inception", "Interstellar"]:
            snips = format_social_snippets(title)
            print(f"• {snips['title']} -> {snips['url']}")


if __name__ == "__main__":
    main()
