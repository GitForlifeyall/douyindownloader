#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/blogger_publisher.py
==========================
Automated Blogger API v3 Publishing & Atom XML Generator for CineMax8.

Allows:
1. Publishing individual or batch movie posts to Google Blogger via Blogger API v3.
2. Generating a Blogger Atom XML import file (Settings -> Manage Blog -> Import Content)
   for 1-click publishing of 20-100 movies without requiring API credentials.
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger("cinemax8.blogger")

try:
    from googleapiclient.discovery import build
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    BLOGGER_API_AVAILABLE = True
except ImportError:
    BLOGGER_API_AVAILABLE = False


BLOGGER_SCOPES = ["https://www.googleapis.com/auth/blogger"]


def format_cinemax8_post_html(movie: Dict[str, Any]) -> str:
    """
    Renders a high-conversion, responsive CineMax8 movie watch card HTML
    for Blogger post body content.
    """
    title = movie.get("title", "Movie Title")
    year = str(movie.get("year", "2026"))
    released = movie.get("released", f"{year}-07-15")
    genres = movie.get("genre", ["Action", "Adventure", "Drama"])
    if isinstance(genres, str):
        genres = [g.strip() for g in genres.split(",")]
    
    casts = movie.get("casts", ["Lead Actor", "Supporting Actor"])
    if isinstance(casts, str):
        casts = [c.strip() for c in casts.split(",")]

    duration = movie.get("duration", "120 min")
    country = movie.get("country", ["United States"])
    if isinstance(country, str):
        country = [c.strip() for c in country.split(",")]

    production = movie.get("production", ["Universal Pictures"])
    if isinstance(production, str):
        production = [p.strip() for p in production.split(",")]

    rating = str(movie.get("rating", "7.5"))
    votes = str(movie.get("votes", "1,850"))
    description = movie.get("description", "An intense cinematic movie experience.")
    poster = movie.get("poster", "https://image.tmdb.org/t/p/w500/5rhTDKUhPYvpdQIijFIs5VoWsON.jpg")
    embed_url = movie.get("embed_url", "https://www.youtube-nocookie.com/embed/fA3s_9u41sA?autoplay=0&rel=0")

    # Format casts as clickable badges
    cast_tags = " ".join([f'<span style="background:#2b3342;color:#9cb3d6;padding:3px 8px;border-radius:4px;margin:2px;display:inline-block;font-size:12px;">{c}</span>' for c in casts])
    genre_tags = " ".join([f'<span style="background:#ff5a2e;color:#fff;padding:2px 7px;border-radius:3px;font-size:11px;font-weight:700;margin-right:4px;">{g}</span>' for g in genres])

    return f"""
<div class="cinemax-post-container" style="background:#1a1e26;color:#ccc;font-family:'Roboto',sans-serif;padding:15px;border-radius:8px;max-width:900px;margin:0 auto;">
  <!-- Video Player -->
  <div style="position:relative;padding-bottom:56.25%;height:0;overflow:hidden;border-radius:8px 8px 0 0;background:#000;">
    <iframe src="{embed_url}" style="position:absolute;top:0;left:0;width:100%;height:100%;border:none;" allowfullscreen="allowfullscreen"></iframe>
  </div>

  <!-- Server Bar -->
  <div style="background:#202632;padding:10px 14px;display:flex;align-items:center;flex-wrap:wrap;gap:8px;border-top:1px solid #2e3747;">
    <span style="color:#fff;font-weight:700;font-size:12px;"><i class="fas fa-server"></i> SERVERS:</span>
    <span style="background:#ff5a2e;color:#fff;padding:4px 10px;border-radius:4px;font-size:11px;font-weight:bold;">Server 1: NovaStream (HD)</span>
    <span style="background:#2b3342;color:#ccc;padding:4px 10px;border-radius:4px;font-size:11px;">Server 2: TitanSpeed (4K)</span>
    <span style="background:#2b3342;color:#ccc;padding:4px 10px;border-radius:4px;font-size:11px;">Server 3: ApexCloud (HD)</span>
    <span style="background:#2b3342;color:#ccc;padding:4px 10px;border-radius:4px;font-size:11px;">Server 4: NebulaCore (Ultra)</span>
  </div>

  <!-- Movie Details Card -->
  <div style="background:#242b38;border:1px solid #333c4d;border-radius:0 0 8px 8px;padding:20px;display:flex;flex-wrap:wrap;gap:20px;margin-bottom:20px;">
    <div style="flex:0 0 170px;text-align:center;">
      <img src="{poster}" alt="{title}" style="width:100%;border-radius:6px;box-shadow:0 4px 16px rgba(0,0,0,0.6);" />
      <div style="color:#ffc107;margin-top:8px;font-size:13px;">★★★★★</div>
      <div style="font-size:12px;color:#aaa;"><strong>4.8 / 5</strong> ({votes} votes)</div>
    </div>

    <div style="flex:1;min-width:260px;">
      <h2 style="color:#fff;margin:0 0 8px;font-size:1.6rem;font-weight:800;">{title} ({year})</h2>
      <div style="margin-bottom:12px;">
        {genre_tags}
        <span style="background:#ffc107;color:#111;padding:2px 6px;border-radius:3px;font-size:11px;font-weight:bold;">IMDb: {rating}</span>
        <span style="background:#00acc1;color:#fff;padding:2px 6px;border-radius:3px;font-size:11px;font-weight:bold;">HD</span>
      </div>

      <p style="color:#bbb;line-height:1.6;font-size:13.5px;margin-bottom:14px;">{description}</p>

      <div style="font-size:12.5px;line-height:1.8;">
        <div><strong style="color:#fff;">Released:</strong> {released}</div>
        <div><strong style="color:#fff;">Duration:</strong> {duration}</div>
        <div><strong style="color:#fff;">Country:</strong> {', '.join(country)}</div>
        <div><strong style="color:#fff;">Production:</strong> {', '.join(production)}</div>
        <div style="margin-top:6px;"><strong style="color:#fff;">Casts:</strong><br/>{cast_tags}</div>
      </div>
    </div>
  </div>

  <!-- Discussion -->
  <div style="background:#242b38;border:1px solid #333c4d;border-radius:8px;padding:16px;">
    <h3 style="color:#fff;font-size:1.1rem;margin:0 0 12px;"><i class="fas fa-comments"></i> Discussion (2.4k Comments)</h3>
    <div style="border-top:1px solid #333c4d;padding-top:10px;font-size:12.5px;">
      <p style="margin:4px 0;"><strong style="color:#fff;">CinemaBuff99:</strong> Spectacular visuals and pacing! Streaming flawlessly on NovaStream.</p>
      <p style="margin:4px 0;"><strong style="color:#fff;">FilmEnthusiast:</strong> The cast ensemble delivers peak cinema. High quality HD stream.</p>
    </div>
  </div>
</div>
""".strip()


class BloggerPublisher:
    """Publishes movie watch cards to Google Blogger using Blogger API v3."""

    def __init__(self, blog_id: str, credentials_path: Optional[str] = None):
        self.blog_id = blog_id
        self.credentials_path = credentials_path or os.getenv("BLOGGER_CREDENTIALS_JSON", "credentials.json")
        self.service = self._init_service()

    def _init_service(self):
        if not BLOGGER_API_AVAILABLE:
            raise ImportError("Blogger API requires google-api-python-client and google-auth-oauthlib.")

        token_path = Path("token_blogger.json")
        creds = None

        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), BLOGGER_SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, BLOGGER_SCOPES)
                creds = flow.run_local_server(port=0)
            token_path.write_text(creds.to_json())

        return build("blogger", "v3", credentials=creds)

    def publish_movie(
        self,
        movie_data: Dict[str, Any],
        is_draft: bool = False,
    ) -> Dict[str, Any]:
        """Publishes a single movie post to Blogger."""
        title = f"{movie_data.get('title', 'Movie')} ({movie_data.get('year', '2026')})"
        content = format_cinemax8_post_html(movie_data)

        labels = ["Movie", "CineMax8"]
        if "genre" in movie_data:
            genres = movie_data["genre"]
            if isinstance(genres, list):
                labels.extend(genres)
            elif isinstance(genres, str):
                labels.extend([g.strip() for g in genres.split(",")])

        body = {
            "kind": "blogger#post",
            "title": title,
            "content": content,
            "labels": list(set(labels)),
        }

        res = self.service.posts().insert(
            blogId=self.blog_id,
            body=body,
            isDraft=is_draft,
        ).execute()

        logger.info(f"Published to Blogger: {res.get('url')}")
        return res


def generate_blogger_atom_xml(movies: List[Dict[str, Any]], output_path: Path) -> Path:
    """
    Generates a Blogger-compatible Atom XML export/import file.
    Can be imported directly into Blogger via:
    Settings -> Manage Blog -> Import Content -> Upload XML.
    Requires ZERO Google API keys or OAuth credentials!
    """
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    entries_xml = []
    for idx, movie in enumerate(movies):
        title = f"{movie.get('title', 'Movie')} ({movie.get('year', '2026')})"
        content_html = format_cinemax8_post_html(movie)
        # Escape XML entities in content
        escaped_content = (
            content_html.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

        genres = movie.get("genre", ["Movie"])
        if isinstance(genres, str):
            genres = [g.strip() for g in genres.split(",")]

        categories = "\n".join([f'<category scheme="http://www.blogger.com/atom/ns#" term="{g}"/>' for g in genres])

        post_id = f"tag:blogger.com,1999:blog-cinemax8.post-{1000 + idx}"

        entry = f"""
  <entry>
    <id>{post_id}</id>
    <published>{now_iso}</published>
    <updated>{now_iso}</updated>
    {categories}
    <title type="text">{title}</title>
    <content type="html">{escaped_content}</content>
    <author>
      <name>CineMax8</name>
    </author>
  </entry>"""
        entries_xml.append(entry)

    feed_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title type="text">CineMax8 Blog Import</title>
  <updated>{now_iso}</updated>
  <id>tag:blogger.com,1999:blog-cinemax8</id>
  {''.join(entries_xml)}
</feed>"""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(feed_xml, encoding="utf-8")
    return output_path


if __name__ == "__main__":
    print("Blogger Publisher Module loaded successfully.")
