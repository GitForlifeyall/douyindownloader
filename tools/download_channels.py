#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
download_channels.py
====================
Douyin Batch Channel Downloader, Sorter, Gemini Translator, and Google Drive Uploader.

Features:
1. Takes a list of Douyin channel URLs (via CLI arguments, text file, or Python import).
2. Extracts sec_user_id and author metadata (also resolves single video links to parent channel).
3. Downloads all videos for each channel and sorts them cleanly into dedicated channel folders:
   `<output_dir>/<Channel_Name>/<video_file>.mp4`
4. Extracts original Chinese captions and hashtag tags.
5. Translates captions and tags into natural, high-retention English using Gemini LLM
   (with multi-key round-robin pool from .env).
6. Generates structured JSON files:
   - `<output_dir>/<Channel_Name>/channel_metadata.json`
   - `<output_dir>/all_channels_metadata.json`
7. Automatically uploads all videos and metadata into Google Drive folder-wise:
   - Cloud Drive API: creates `<Channel_Name>` folder on Google Drive and uploads files.
   - Mounted/Local Drive: mirrors `<Channel_Name>` folders to mounted Drive path (e.g. `G:/My Drive/...`).
"""

import os
import re
import sys
import json
import time
import shutil
import asyncio
import logging
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Union

# Ensure root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Load .env runtime environment
from dubbing_studio.env_loader import configure_runtime_environment
configure_runtime_environment()

# Safe UTF-8 encoding on Windows
if sys.platform == "win32":
    import codecs
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "replace")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, "replace")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("ChannelDownloader")


DEFAULT_DRIVE_PATH = (
    Path("H:/My Drive/douyin") if Path("H:/My Drive").exists() else None
)


def sanitize_folder_name(name: str) -> str:
    """Sanitize channel nickname for Windows filesystem compatibility."""
    if not name:
        return "Unknown_Channel"
    # Replace illegal filename characters
    cleaned = re.sub(r'[\\/*?:"<>|]', "_", name).strip()
    return cleaned or "Unknown_Channel"


class GeminiMetadataTranslator:
    """
    Translates Chinese captions and tags to English using official Google GenAI SDK.
    Supports multi-key round-robin rotation and fallback models.
    """

    def __init__(self, model: str = "gemini-3.5-flash"):
        env_keys = [
            k.strip()
            for k in os.environ.get("GEMINI_API_KEYS", "").split(",")
            if k.strip()
        ]
        single_key = os.environ.get("GEMINI_API_KEY")
        if single_key and single_key not in env_keys:
            env_keys.insert(0, single_key)

        if not env_keys:
            raise ValueError(
                "No Gemini API keys found. Set GEMINI_API_KEY or GEMINI_API_KEYS in .env."
            )

        self.api_keys = env_keys
        self.current_key_idx = 0
        self.model = model
        # High-throughput, stable models
        self.fallback_models = [
            model,
            "gemini-3.5-flash",
            "gemini-3.5-flash-lite",
            "gemini-flash-latest",
            "gemini-3.1-flash-lite"
        ]
        # Remove duplicates while preserving order
        seen = set()
        self.fallback_models = [m for m in self.fallback_models if not (m in seen or seen.add(m))]

    def get_current_key(self) -> str:
        return self.api_keys[self.current_key_idx % len(self.api_keys)]

    def rotate_key(self):
        self.current_key_idx = (self.current_key_idx + 1) % len(self.api_keys)
        logger.info(
            f"Rotated to Gemini API key #{self.current_key_idx + 1} of {len(self.api_keys)}"
        )

    def translate_batch(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Translates a batch of video metadata items into English.
        Each item must have: 'video_id', 'caption', 'tags'.
        Returns list of dicts with 'video_id', 'translated_caption_en', 'translated_tags_en'.
        """
        if not items:
            return []

        from google import genai
        from google.genai import types

        prompt = (
            "You are an expert bilingual social media translator and cultural localization specialist.\n"
            "Translate the following Douyin video captions and tags from Chinese to fluent, natural, engaging English.\n\n"
            "Guidelines:\n"
            "1. 'translated_caption_en': Natural English that captures the original meaning, humor, or storytelling.\n"
            "2. 'translated_tags_en': Clean English SEO keywords/tags corresponding to the original hashtags.\n"
            "3. Output strictly valid JSON matching the schema below.\n\n"
            f"Input JSON:\n{json.dumps(items, ensure_ascii=False, indent=2)}\n\n"
            "Output JSON format:\n"
            "[\n"
            "  {\n"
            '    "video_id": "...",\n'
            '    "translated_caption_en": "...",\n'
            '    "translated_tags_en": ["tag1", "tag2"]\n'
            "  }\n"
            "]"
        )

        max_attempts = len(self.api_keys) * len(self.fallback_models)
        model_idx = 0
        for attempt in range(max_attempts):
            api_key = self.get_current_key()
            current_model = self.fallback_models[model_idx % len(self.fallback_models)]

            try:
                client = genai.Client(
                    api_key=api_key,
                    http_options=types.HttpOptions(timeout=15000)
                )
                response = client.models.generate_content(
                    model=current_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.3
                    )
                )
                if response and response.text:
                    parsed = json.loads(response.text.strip())
                    if isinstance(parsed, list):
                        return parsed
                    elif isinstance(parsed, dict) and "videos" in parsed:
                        return parsed["videos"]

                raise ValueError("Empty or non-JSON response from Gemini")

            except Exception as e:
                err_msg = str(e)
                logger.warning(
                    f"Gemini translation attempt {attempt + 1} with model {current_model} failed: {err_msg[:120]}"
                )
                self.rotate_key()
                # If overloaded, timed out, or rate-limited, switch model immediately
                if any(code in err_msg for code in ["503", "504", "429", "DEADLINE_EXCEEDED", "UNAVAILABLE", "ResourceExhausted"]):
                    model_idx += 1
                time.sleep(1.0)

        logger.error("All Gemini API keys and fallback models failed for this batch.")
        # Fallback to original text rather than crashing
        return [
            {
                "video_id": it["video_id"],
                "translated_caption_en": it.get("caption", ""),
                "translated_tags_en": it.get("tags", [])
            }
            for it in items
        ]


class DouyinChannelBatchDownloader:
    """
    Main manager for batch downloading Douyin channels, sorting into folders,
    sorting by date or popularity, and uploading to Google Drive.
    """

    def __init__(
        self,
        output_dir: Union[str, Path] = "channels_download",
        translate: bool = False,
        gemini_model: str = "gemini-3.5-flash",
        max_videos_per_channel: Optional[int] = None,
        max_pages_per_channel: Optional[int] = None,
        sort_by: str = "date",
        folder_name: Optional[str] = None,
        no_metadata: bool = False,
        upload_gdrive: bool = False,
        drive_folder_id: Optional[str] = None,
        drive_path: Optional[Union[str, Path]] = None,
        service_account_json: Optional[Union[str, Path]] = None
    ):
        self.output_dir = Path(output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.custom_folder_name = folder_name
        self.translate = translate
        self.gemini_model = gemini_model
        self.max_videos = max_videos_per_channel
        self.max_pages = max_pages_per_channel
        self.sort_by = (sort_by or "date").lower()
        self.no_metadata = no_metadata

        self.upload_gdrive = upload_gdrive
        self.drive_folder_id = drive_folder_id or os.getenv("GDRIVE_FOLDER_ID")

        # Configure Google Drive sync directory (default: H:\My Drive\douyin)
        if drive_path is not None:
            if str(drive_path).lower() in ("none", "false", "0", ""):
                self.drive_path = None
            else:
                self.drive_path = Path(drive_path).resolve()
        elif os.getenv("GDRIVE_PATH"):
            self.drive_path = Path(os.getenv("GDRIVE_PATH")).resolve()
        elif DEFAULT_DRIVE_PATH:
            self.drive_path = DEFAULT_DRIVE_PATH
        else:
            self.drive_path = None

        self.service_account_json = service_account_json or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

        self.gdrive_uploader = None
        if self.upload_gdrive:
            from dubbing_studio.gdrive_uploader import GoogleDriveUploader, GDRIVE_AVAILABLE
            if not GDRIVE_AVAILABLE:
                raise ImportError(
                    "Google Drive upload requested but google-api-python-client is missing."
                )
            try:
                self.gdrive_uploader = GoogleDriveUploader(
                    service_account_json=self.service_account_json
                )
                logger.info("[GDrive] Cloud Google Drive Uploader initialized successfully.")
            except Exception as e:
                logger.warning(
                    f"[GDrive] Could not initialize Cloud Drive API: {e}. "
                    "Make sure credentials.json or a Service Account JSON is configured."
                )

        if self.drive_path:
            self.drive_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"[Drive] Sync target Google Drive directory: {self.drive_path}")

        self.tiktok_dir = PROJECT_ROOT / "TikTokDownloader"
        if not self.tiktok_dir.exists():
            raise FileNotFoundError(f"TikTokDownloader not found at {self.tiktok_dir}")

        # Inject into sys.path
        if str(self.tiktok_dir) not in sys.path:
            sys.path.insert(0, str(self.tiktok_dir))
        src_dir = self.tiktok_dir / "src"
        if src_dir.exists() and str(src_dir) not in sys.path:
            sys.path.insert(0, str(src_dir))

        self.translator = None
        if self.translate and not self.no_metadata:
            try:
                self.translator = GeminiMetadataTranslator(model=gemini_model)
                logger.info(f"[Downloader] Gemini translation enabled using {gemini_model}.")
            except Exception as e:
                logger.warning(f"Gemini translator initialization warning: {e}")
                self.translator = None
        elif self.no_metadata:
            logger.info("[Downloader] Metadata generation disabled (--no-metadata). Downloading videos only.")
        else:
            logger.info("[Downloader] Default mode: Downloading videos and original captions (no LLM translation).")

    async def _resolve_channel(self, app, url: str) -> Optional[Dict[str, str]]:
        """
        Resolves a Douyin URL (channel page, shortlink, or video) to sec_user_id and nickname.
        """
        from src.link import Extractor as LinkExtractor
        from src.interface import Detail

        link_extractor = LinkExtractor(app.parameter)

        # 1. Try extracting channel user ID
        sec_uids = await link_extractor.run(url, "user")
        if sec_uids and sec_uids[0]:
            sec_uid = sec_uids[0]
            return {"sec_user_id": sec_uid, "url": url}

        # 2. Check if user provided a video modal/direct link
        detail_ids = await link_extractor.run(url, "detail")
        if detail_ids and detail_ids[0]:
            vid = detail_ids[0]
            logger.info(f"URL appears to be a video ({vid}). Resolving author channel...")
            detail_obj = Detail(app.parameter, detail_id=vid)
            data = await detail_obj.run()
            if data and "author" in data:
                author = data["author"]
                sec_uid = author.get("sec_uid")
                nickname = author.get("nickname")
                if sec_uid:
                    return {
                        "sec_user_id": sec_uid,
                        "nickname": nickname,
                        "url": f"https://www.douyin.com/user/{sec_uid}"
                    }

        logger.warning(f"Could not resolve channel sec_user_id from: {url}")
        return None

    async def process_channels(self, urls: List[str]) -> Dict[str, Any]:
        """
        Downloads all channels in urls list, sorts videos into channel folders,
        translates captions & tags using Gemini, uploads to Drive folder-wise,
        and saves JSON metadata.
        """
        from src.application import TikTokDownloader
        from src.application.main_terminal import TikTok

        master_summary = {
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_channels": len(urls),
            "channels": []
        }

        async with TikTokDownloader() as app:
            app.check_config()
            await app.check_settings(False)
            terminal = TikTok(app.parameter, app.database, server_mode=True)

            for idx, raw_url in enumerate(urls, start=1):
                raw_url = raw_url.strip()
                if not raw_url or raw_url.startswith("#"):
                    continue

                logger.info("\n" + "=" * 65)
                logger.info(f"[{idx}/{len(urls)}] Processing Channel: {raw_url}")
                logger.info("=" * 65)

                resolved = await self._resolve_channel(app, raw_url)
                if not resolved:
                    logger.error(f"Skipping unresolved channel: {raw_url}")
                    continue

                sec_uid = resolved["sec_user_id"]
                logger.info(f"Identified sec_user_id: {sec_uid}")

                # Hook terminal._get_account_data to extract stats and sort by popularity if requested
                stats_by_caption: Dict[str, Dict[str, Any]] = {}
                orig_get_data = terminal._get_account_data

                async def hooked_get_account_data(*args, **kwargs):
                    data, earliest, latest = await orig_get_data(*args, **kwargs)
                    if data:
                        for it in data:
                            desc = (it.get("desc") or "").strip()
                            st = it.get("statistics") or {}
                            stats_entry = {
                                "likes": st.get("digg_count", 0),
                                "comments": st.get("comment_count", 0),
                                "shares": st.get("share_count", 0),
                                "saves": st.get("collect_count", 0),
                            }
                            if desc:
                                stats_by_caption[desc] = stats_entry
                            aid = str(it.get("aweme_id") or it.get("id") or "")
                            if aid:
                                stats_by_caption[aid] = stats_entry

                        if self.sort_by in ("popularity", "popular", "likes", "like"):
                            logger.info(f"Sorting {len(data)} works by popularity (highest likes first)...")
                            data.sort(
                                key=lambda x: (x.get("statistics") or {}).get("digg_count", 0),
                                reverse=True
                            )
                            if self.max_videos:
                                logger.info(f"Selected Top {self.max_videos} most popular videos to download.")
                                data = data[:self.max_videos]

                    return data, earliest, latest

                terminal._get_account_data = hooked_get_account_data

                # Download channel works
                pages = self.max_pages if self.max_pages is not None else None
                success = await terminal.deal_account_detail(
                    index=idx,
                    sec_user_id=sec_uid,
                    pages=pages
                )
                terminal._get_account_data = orig_get_data

                if not success:
                    logger.warning(f"No works retrieved or download aborted for: {sec_uid}")

                # Locate downloaded directory in TikTokDownloader/Volume/
                volume_dir = self.tiktok_dir / "Volume"
                matching_dirs = [
                    d for d in volume_dir.iterdir()
                    if d.is_dir() and sec_uid in d.name
                ]
                if not matching_dirs:
                    posts_dirs = [d for d in volume_dir.glob("UID*_Posts") if d.is_dir()]
                    if posts_dirs:
                        matching_dirs = [max(posts_dirs, key=lambda d: d.stat().st_mtime)]

                channel_name = resolved.get("nickname")
                source_folder = None
                if matching_dirs:
                    source_folder = matching_dirs[0]
                    parts = source_folder.name.split("_")
                    if len(parts) >= 3 and not channel_name:
                        channel_name = parts[1]

                if not channel_name:
                    channel_name = f"Channel_{sec_uid[:12]}"

                # Clean channel destination folder
                if self.custom_folder_name:
                    clean_name = sanitize_folder_name(self.custom_folder_name)
                else:
                    clean_name = sanitize_folder_name(channel_name)
                channel_dest = self.output_dir / clean_name
                channel_dest.mkdir(parents=True, exist_ok=True)

                logger.info(f"Organizing channel videos into: {channel_dest}")

                # Move/Copy video files into channel folder
                downloaded_videos: List[Path] = []
                if source_folder and source_folder.exists():
                    for video_file in source_folder.glob("*.mp4"):
                        dest_file = channel_dest / video_file.name
                        if not dest_file.exists():
                            shutil.copy2(video_file, dest_file)
                        downloaded_videos.append(dest_file)

                # Check channel_dest for all videos (sort by popularity or date)
                if self.sort_by in ("popularity", "popular", "likes", "like") and stats_by_caption:
                    def get_video_likes(vpath: Path) -> int:
                        clean_s = re.sub(r"^\d{4}-\d{2}-\d{2}\s+\d{2}\.\d{2}\.\d{2}-Video-[^-]+-", "", vpath.stem)
                        clean_s = re.sub(r"^\d{4}-\d{2}-\d{2}\s+\d{2}\.\d{2}\.\d{2}-", "", clean_s).strip()
                        m_stat = stats_by_caption.get(clean_s, {})
                        if not m_stat:
                            for k, v in stats_by_caption.items():
                                if k and (k in clean_s or clean_s in k):
                                    m_stat = v
                                    break
                        return m_stat.get("likes", 0)

                    all_videos = sorted(
                        list(channel_dest.glob("*.mp4")),
                        key=get_video_likes,
                        reverse=True
                    )
                else:
                    all_videos = sorted(
                        list(channel_dest.glob("*.mp4")),
                        key=lambda f: f.stat().st_mtime,
                        reverse=True
                    )

                if self.max_videos:
                    all_videos = all_videos[:self.max_videos]

                logger.info(f"Channel '{clean_name}' has {len(all_videos)} video(s) ready.")

                # If metadata generation is disabled, just upload/sync videos if requested and skip JSON
                if self.no_metadata:
                    logger.info(f"Skipping captions, tags, and metadata for channel '{clean_name}' (--no-metadata).")
                    dummy_channel_data = {
                        "channel_name": channel_name,
                        "sec_user_id": sec_uid,
                        "folder_path": str(channel_dest),
                        "total_videos": len(all_videos),
                        "videos": [{"filename": v.name, "local_path": str(v)} for v in all_videos]
                    }
                    if self.upload_gdrive or self.drive_path:
                        await self._upload_channel_to_drive(dummy_channel_data, channel_dest)
                    master_summary["channels"].append(dummy_channel_data)
                    continue

                # Extract captions and tags from video filenames (saves .txt caption file alongside each video)
                channel_data = self._build_channel_metadata(
                    app=app,
                    channel_name=channel_name,
                    sec_uid=sec_uid,
                    channel_url=resolved["url"],
                    video_paths=all_videos,
                    channel_dir=channel_dest,
                    stats_map=stats_by_caption
                )

                # Translate captions & tags into English using Gemini ONLY if --translate is explicitly enabled
                if self.translate and self.translator:
                    await self._translate_channel_metadata(channel_data)

                # Optional: Upload into Drive folder-wise
                await self._upload_channel_to_drive(channel_data, channel_dest)

                # Save channel metadata JSON (with Drive links if uploaded)
                channel_json_path = channel_dest / "channel_metadata.json"
                with open(channel_json_path, "w", encoding="utf-8") as f:
                    json.dump(channel_data, f, ensure_ascii=False, indent=2)

                logger.info(f"Saved channel metadata JSON to: {channel_json_path}")
                master_summary["channels"].append(channel_data)

        if not self.no_metadata:
            # Save root consolidated JSON
            all_channels_json_path = self.output_dir / "all_channels_metadata.json"
            with open(all_channels_json_path, "w", encoding="utf-8") as f:
                json.dump(master_summary, f, ensure_ascii=False, indent=2)

            # Also upload master JSON to Drive if requested
            if self.gdrive_uploader:
                try:
                    logger.info("[GDrive] Uploading master all_channels_metadata.json to Drive...")
                    self.gdrive_uploader.upload_file(
                        all_channels_json_path,
                        folder_id=self.drive_folder_id,
                        skip_if_exists=False
                    )
                except Exception as e:
                    logger.error(f"[GDrive] Failed to upload master JSON: {e}")

            if self.drive_path:
                try:
                    dest_master = self.drive_path / "all_channels_metadata.json"
                    shutil.copy2(all_channels_json_path, dest_master)
                    logger.info(f"[Drive] Copied master JSON to mounted Drive: {dest_master}")
                except Exception as e:
                    logger.error(f"[Drive] Failed to copy master JSON to mounted Drive: {e}")

            logger.info("\n" + "=" * 65)
            logger.info(f"Batch Processing Complete! Master JSON: {all_channels_json_path}")
            logger.info("=" * 65)
        else:
            logger.info("\n" + "=" * 65)
            logger.info(f"Batch Video Download Complete! All videos saved folder-wise in: {self.output_dir}")
            logger.info("=" * 65)

        return master_summary

    async def _upload_channel_to_drive(
        self,
        channel_data: Dict[str, Any],
        channel_dir: Path
    ):
        """
        Uploads channel videos and metadata to Google Drive folder-wise.
        Supports both Cloud Google Drive API and Local Mounted Drive directory.
        """
        channel_name = channel_data["channel_name"]

        # 1. Cloud Google Drive API
        if self.gdrive_uploader:
            try:
                logger.info(f"[GDrive] Starting folder-wise upload for channel '{channel_name}'...")
                gdrive_res = self.gdrive_uploader.upload_channel_folder(
                    channel_dir,
                    parent_folder_id=self.drive_folder_id
                )
                channel_data["drive_folder_id"] = gdrive_res.get("drive_folder_id")
                channel_data["drive_folder_link"] = gdrive_res.get("drive_folder_link")

                # Map individual video Drive links
                up_files = {u["filename"]: u for u in gdrive_res.get("uploaded_files", [])}
                for v in channel_data.get("videos", []):
                    fname = v.get("filename")
                    if fname in up_files:
                        v["drive_id"] = up_files[fname].get("drive_id")
                        v["drive_link"] = up_files[fname].get("drive_link")

                logger.info(
                    f"[GDrive] Finished channel upload to Google Drive: "
                    f"{gdrive_res.get('drive_folder_link')}"
                )
            except Exception as e:
                logger.error(f"[GDrive] Error uploading channel '{channel_name}' to Drive: {e}")

        # 2. Local Mounted Drive (e.g. G:\My Drive\Douyin_Channels\Channel_Name)
        if self.drive_path:
            try:
                dest_drive_channel = self.drive_path / sanitize_folder_name(channel_name)
                dest_drive_channel.mkdir(parents=True, exist_ok=True)
                logger.info(f"[Drive] Syncing channel folder to mounted Drive: {dest_drive_channel}...")

                # Copy videos and caption text files
                files_to_sync = list(channel_dir.glob("*.mp4")) + list(channel_dir.glob("*.txt"))
                for file_path in files_to_sync:
                    dest_file = dest_drive_channel / file_path.name
                    if not dest_file.exists():
                        shutil.copy2(file_path, dest_file)

                # Copy channel metadata
                meta_json = channel_dir / "channel_metadata.json"
                if meta_json.exists():
                    shutil.copy2(meta_json, dest_drive_channel / "channel_metadata.json")

                channel_data["drive_local_path"] = str(dest_drive_channel)
                logger.info(f"[Drive] Channel synced to: {dest_drive_channel}")
            except Exception as e:
                logger.error(f"[Drive] Error syncing channel '{channel_name}' to mounted Drive: {e}")

    def _build_channel_metadata(
        self,
        app,
        channel_name: str,
        sec_uid: str,
        channel_url: str,
        video_paths: List[Path],
        channel_dir: Path,
        stats_map: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Builds raw metadata for videos in the channel directory,
        extracting publish_time, captions, hashtag tags from filenames,
        and engagement stats (likes, comments, shares, saves) from Douyin API.
        Saves original caption into <video_stem>.txt alongside each video.
        """
        existing_meta = {}
        existing_json = channel_dir / "channel_metadata.json"
        if existing_json.exists():
            try:
                with open(existing_json, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    for v in d.get("videos", []):
                        existing_meta[v.get("filename")] = v
            except Exception:
                pass

        videos_list = []
        for vpath in video_paths:
            fname = vpath.name
            if fname in existing_meta and (not self.translate or existing_meta[fname].get("translated_caption_en")):
                videos_list.append(existing_meta[fname])
                continue

            # Extract date time from filename: "YYYY-MM-DD HH.MM.SS-Video-..."
            date_match = re.search(r"^(\d{4}-\d{2}-\d{2}\s+\d{2}\.\d{2}\.\d{2})", fname)
            publish_time = date_match.group(1).replace(".", ":") if date_match else ""

            # Extract tags with hashtag regex
            tags = re.findall(r"#([\w\u4e00-\u9fa5]+)", fname)

            # Extract clean caption text
            clean_stem = vpath.stem
            clean_stem = re.sub(r"^\d{4}-\d{2}-\d{2}\s+\d{2}\.\d{2}\.\d{2}-Video-[^-]+-", "", clean_stem)
            clean_stem = re.sub(r"^\d{4}-\d{2}-\d{2}\s+\d{2}\.\d{2}\.\d{2}-", "", clean_stem)
            caption_clean = clean_stem.strip()

            # Save original caption to .txt file alongside the video
            caption_txt_path = vpath.with_suffix(".txt")
            if not caption_txt_path.exists():
                try:
                    with open(caption_txt_path, "w", encoding="utf-8") as cf:
                        cf.write(caption_clean + "\n")
                except Exception as ce:
                    logger.warning(f"Could not write caption file {caption_txt_path}: {ce}")

            # Match stats if available
            v_stats = {}
            if stats_map:
                if caption_clean in stats_map:
                    v_stats = stats_map[caption_clean]
                else:
                    prefix = caption_clean.split("...")[0].strip() if "..." in caption_clean else caption_clean
                    for k, s_val in stats_map.items():
                        if not k:
                            continue
                        if (prefix and len(prefix) >= 4 and (prefix in k or k in prefix)) or (k in caption_clean or caption_clean in k or k in fname):
                            v_stats = s_val
                            break

            video_entry = {
                "video_id": f"vid_{abs(hash(fname)) % (10**16)}",
                "filename": fname,
                "caption_file": caption_txt_path.name,
                "local_path": str(vpath.relative_to(PROJECT_ROOT) if vpath.is_relative_to(PROJECT_ROOT) else vpath),
                "publish_time": publish_time,
                "likes": v_stats.get("likes", 0),
                "comments": v_stats.get("comments", 0),
                "shares": v_stats.get("shares", 0),
                "saves": v_stats.get("saves", 0),
                "original_caption": caption_clean,
                "original_tags": tags,
                "file_size_bytes": vpath.stat().st_size if vpath.exists() else 0
            }
            if self.translate:
                video_entry["translated_caption_en"] = ""
                video_entry["translated_tags_en"] = []

            videos_list.append(video_entry)

        # Sort videos list by popularity if requested
        if self.sort_by in ("popularity", "popular", "likes", "like"):
            videos_list.sort(key=lambda x: (x.get("likes") or 0), reverse=True)

        return {
            "channel_name": channel_name,
            "sec_user_id": sec_uid,
            "channel_url": channel_url,
            "sort_by": self.sort_by,
            "total_videos": len(videos_list),
            "folder_path": str(channel_dir.relative_to(PROJECT_ROOT) if channel_dir.is_relative_to(PROJECT_ROOT) else channel_dir),
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "videos": videos_list
        }

    async def _translate_channel_metadata(self, channel_data: Dict[str, Any]):
        """
        Translates captions and tags for all videos in channel_data using Gemini in batches.
        """
        videos = channel_data.get("videos", [])
        to_translate = [
            v for v in videos
            if not v.get("translated_caption_en") and v.get("original_caption")
        ]

        if not to_translate:
            logger.info("All video captions are already translated. Skipping Gemini call.")
            return

        logger.info(f"Translating {len(to_translate)} captions & tag sets with Gemini LLM...")

        # Process in batches of 10 items
        batch_size = 10
        for i in range(0, len(to_translate), batch_size):
            chunk = to_translate[i:i + batch_size]
            prompt_items = [
                {
                    "video_id": v["video_id"],
                    "caption": v["original_caption"],
                    "tags": v["original_tags"]
                }
                for v in chunk
            ]

            translated_results = self.translator.translate_batch(prompt_items)

            # Map results back to video dicts
            res_by_id = {r["video_id"]: r for r in translated_results if "video_id" in r}
            for v in chunk:
                vid = v["video_id"]
                if vid in res_by_id:
                    v["translated_caption_en"] = res_by_id[vid].get("translated_caption_en", "")
                    v["translated_tags_en"] = res_by_id[vid].get("translated_tags_en", [])
                else:
                    idx_in_chunk = chunk.index(v)
                    if idx_in_chunk < len(translated_results):
                        r = translated_results[idx_in_chunk]
                        v["translated_caption_en"] = r.get("translated_caption_en", "")
                        v["translated_tags_en"] = r.get("translated_tags_en", [])


def parse_urls_from_file(file_path: Union[str, Path]) -> List[str]:
    """Parse valid URLs from a text file, ignoring empty lines and comments."""
    p = Path(file_path)
    if not p.is_file():
        raise FileNotFoundError(f"Channels file not found: {p}")

    urls = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            clean = line.strip()
            clean = clean.split()[0] if clean else ""
            if clean and clean.startswith("http"):
                urls.append(clean)
    return urls


def download_douyin_channels(
    urls: List[str],
    output_dir: str = "channels_download",
    translate: bool = False,
    gemini_model: str = "gemini-3.5-flash",
    max_videos_per_channel: Optional[int] = None,
    max_pages_per_channel: Optional[int] = None,
    sort_by: str = "date",
    folder_name: Optional[str] = None,
    no_metadata: bool = False,
    upload_gdrive: bool = False,
    drive_folder_id: Optional[str] = None,
    drive_path: Optional[Union[str, Path]] = None,
    service_account_json: Optional[Union[str, Path]] = None
) -> Dict[str, Any]:
    """
    Programmatic entry point to download Douyin channels.
    By default, downloads videos and original captions into channel folders without LLM translation.
    Set translate=True to enable Gemini LLM English translation.
    Set sort_by='popularity' or 'likes' to sort channel works by highest likes.
    Set folder_name to override the destination channel folder name.
    """
    downloader = DouyinChannelBatchDownloader(
        output_dir=output_dir,
        translate=translate,
        gemini_model=gemini_model,
        max_videos_per_channel=max_videos_per_channel,
        max_pages_per_channel=max_pages_per_channel,
        sort_by=sort_by,
        folder_name=folder_name,
        no_metadata=no_metadata,
        upload_gdrive=upload_gdrive,
        drive_folder_id=drive_folder_id,
        drive_path=drive_path,
        service_account_json=service_account_json
    )
    return asyncio.run(downloader.process_channels(urls))


# Export alias
batch_download_channels = download_douyin_channels


def main():
    parser = argparse.ArgumentParser(
        description="Download Douyin channel videos into folders with original captions, optionally translate with Gemini LLM, and upload to Google Drive."
    )
    parser.add_argument(
        "--file", "-f",
        type=str,
        default="channelsondouin.txt" if Path("channelsondouin.txt").exists() else None,
        help="Path to text file containing Douyin channel URLs (default: channelsondouin.txt)"
    )
    parser.add_argument(
        "--urls", "-u",
        nargs="+",
        help="One or more Douyin channel URLs passed directly on the command line."
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        default="channels_download",
        help="Root directory where sorted channel folders will be saved (default: ./channels_download)"
    )
    parser.add_argument(
        "--folder-name", "--folder", "-fn",
        type=str,
        default=None,
        help="Custom destination folder name for downloaded channel videos (e.g. 'seal')."
    )
    parser.add_argument(
        "--sort-by",
        type=str,
        choices=["date", "popularity", "likes", "latest"],
        default="date",
        help="Sort videos by 'date' (latest first) or 'popularity'/'likes' (most liked first, default: date)."
    )
    parser.add_argument(
        "--popular", "--sort-by-popularity",
        dest="popular",
        action="store_true",
        help="Shortcut flag to sort channel videos by popularity (most liked first)."
    )
    parser.add_argument(
        "--translate", "--translate-en", "--translate-gemini",
        dest="translate",
        action="store_true",
        help="Enable Gemini LLM translation of captions and tags to English (off by default; default downloads original captions only)."
    )
    parser.add_argument(
        "--no-metadata", "--skip-metadata", "--videos-only",
        dest="no_metadata",
        action="store_true",
        help="Do not save captions, tags, or metadata JSON. Just download the videos into channel folders."
    )
    parser.add_argument(
        "--gemini-model", "-m",
        type=str,
        default="gemini-3.5-flash",
        help="Gemini model for English translation if --translate is enabled (default: gemini-3.5-flash)"
    )
    parser.add_argument(
        "--max-videos",
        type=int,
        default=None,
        help="Maximum videos to retain/download per channel (default: all)"
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Maximum API pages to retrieve per channel (default: all)"
    )
    # Google Drive upload flags
    parser.add_argument(
        "--upload-gdrive", "-g",
        action="store_true",
        help="Enable automatic folder-wise upload to Google Drive via Drive API."
    )
    parser.add_argument(
        "--drive-folder-id",
        type=str,
        default=None,
        help="Target parent Google Drive folder ID (or set GDRIVE_FOLDER_ID in .env)."
    )
    parser.add_argument(
        "--drive-path",
        type=str,
        default=None,
        help="Path to a mounted Google Drive directory (default: H:/My Drive/douyin if available)."
    )
    parser.add_argument(
        "--service-account",
        type=str,
        default=None,
        help="Path to Google Cloud Service Account JSON key file."
    )

    args = parser.parse_args()

    # Collect URLs
    channel_urls = []
    if args.urls:
        channel_urls.extend(args.urls)
    elif args.file:
        channel_urls.extend(parse_urls_from_file(args.file))
    else:
        logger.error("No input URLs provided. Specify --file <path> or --urls <url1> <url2>...")
        sys.exit(1)

    unique_urls = list(dict.fromkeys(channel_urls))
    logger.info(f"Loaded {len(unique_urls)} channel URL(s) to process.")

    chosen_sort = "popularity" if args.popular else args.sort_by

    download_douyin_channels(
        urls=unique_urls,
        output_dir=args.output_dir,
        translate=args.translate,
        gemini_model=args.gemini_model,
        max_videos_per_channel=args.max_videos,
        max_pages_per_channel=args.max_pages,
        sort_by=chosen_sort,
        folder_name=args.folder_name,
        no_metadata=args.no_metadata,
        upload_gdrive=args.upload_gdrive,
        drive_folder_id=args.drive_folder_id,
        drive_path=args.drive_path,
        service_account_json=args.service_account
    )


if __name__ == "__main__":
    main()
