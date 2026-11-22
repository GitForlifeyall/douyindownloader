#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dubbing_studio/downloader.py
============================
Clean API adapter for TikTokDownloader.
Treats the TikTokDownloader repository strictly as an external library/service
without polluting custom pipeline code.
"""

import sys
import asyncio
from pathlib import Path
from typing import Optional, Union, Dict, Any, List

# Ensure runtime environment is configured
from .env_loader import configure_runtime_environment
configure_runtime_environment()


class DownloaderAPI:
    """
    Adapter treating TikTokDownloader strictly as a backend video extraction API.
    """

    def __init__(self, tiktok_downloader_dir: Optional[Union[str, Path]] = None):
        if tiktok_downloader_dir:
            self.base_dir = Path(tiktok_downloader_dir).resolve()
        else:
            # Default to sibling TikTokDownloader directory
            self.base_dir = Path(__file__).resolve().parent.parent / "TikTokDownloader"

        if not self.base_dir.exists():
            raise FileNotFoundError(f"TikTokDownloader directory not found at: {self.base_dir}")

        # Inject into sys.path strictly for API usage
        if str(self.base_dir) not in sys.path:
            sys.path.insert(0, str(self.base_dir))
        src_dir = self.base_dir / "src"
        if src_dir.exists() and str(src_dir) not in sys.path:
            sys.path.insert(0, str(src_dir))

    @staticmethod
    def _parse_duration_sec(raw_val: Any) -> Optional[float]:
        """Parse metadata duration ('HH:MM:SS', 'MM:SS', numeric seconds or ms) into seconds."""
        if raw_val is None or raw_val == "":
            return None
        if isinstance(raw_val, (int, float)):
            val = float(raw_val)
            return (val / 1000.0) if val > 7200 else val
        s = str(raw_val).strip()
        if ":" in s:
            try:
                parts = [float(p) for p in s.split(":")]
                if len(parts) == 3:
                    return parts[0] * 3600.0 + parts[1] * 60.0 + parts[2]
                if len(parts) == 2:
                    return parts[0] * 60.0 + parts[1]
            except Exception:
                return None
        try:
            val = float(s)
            return (val / 1000.0) if val > 7200 else val
        except Exception:
            return None

    def probe_video_duration(self, url: str) -> Optional[float]:
        """Check Douyin/TikTok video duration in seconds BEFORE downloading media bytes."""
        local_candidate = Path(url)
        if local_candidate.exists() and local_candidate.is_file():
            return None
        from src.application import TikTokDownloader
        from src.interface import Detail, DetailTikTok
        from src.link import Extractor, ExtractorTikTok
        from src.extract import Extractor as DataExtractor
        from src.storage import RecordManager

        async def _async_probe(target_url: str) -> Optional[float]:
            is_tiktok = "tiktok.com" in target_url.lower()
            async with TikTokDownloader() as app:
                app.check_config()
                await app.check_settings(False)
                link_extractor = ExtractorTikTok(app.parameter) if is_tiktok else Extractor(app.parameter)
                ids = await link_extractor.run(target_url, type_="detail")
                if not ids:
                    return None
                detail_obj = (DetailTikTok if is_tiktok else Detail)(app.parameter, detail_id=ids[0])
                detail_data = await detail_obj.run()
                if not detail_data:
                    return None
                rm = RecordManager()
                root, params, logger_cls = rm.run(app.parameter)
                data_extractor = DataExtractor(app.parameter)
                async with logger_cls(root, console=app.console, **params) as record:
                    extracted_info = await data_extractor.run([detail_data], record, tiktok=is_tiktok)
                    if not extracted_info:
                        return None
                    return self._parse_duration_sec(extracted_info[0].get("duration"))

        try:
            return asyncio.run(_async_probe(url))
        except Exception as e:
            print(f"[DownloaderAPI] Pre-download duration probe skipped ({e})")
            return None

    def download_video(self, url: str, output_dir: Optional[Union[str, Path]] = None) -> Path:
        """
        Download a Douyin or TikTok video, or return local video Path if already downloaded.
        
        Args:
            url: Douyin/TikTok video URL or path to a local video file.
            output_dir: Directory where the raw video will be saved.
            
        Returns:
            Path object pointing to the downloaded/local MP4 file.
        """
        project_root = Path(__file__).resolve().parent.parent
        default_input_dir = project_root / "input"
        out_path = Path(output_dir) if output_dir else default_input_dir
        out_path.mkdir(parents=True, exist_ok=True)

        # 1. Handle local file paths directly
        local_candidate = Path(url)
        if not local_candidate.exists() and (out_path / url).exists():
            local_candidate = out_path / url
        if local_candidate.exists() and local_candidate.suffix.lower() in [".mp4", ".mkv", ".mov", ".webm"]:
            print(f"[DownloaderAPI] Input is already a local video file: {local_candidate.name}")
            return local_candidate

        print(f"\n==========================================")
        print(f"[DownloaderAPI] Extracting Douyin/TikTok Video")
        print(f"Target URL: {url}")
        print(f"Output Directory: {out_path}")
        print(f"==========================================")

        # Dynamically import TikTokDownloader core modules
        from src.application import TikTokDownloader
        from src.interface import Detail, DetailTikTok
        from src.link import Extractor, ExtractorTikTok
        from src.extract import Extractor as DataExtractor
        from src.downloader import Downloader
        from src.storage import RecordManager

        async def _async_download(target_url: str) -> Path:
            is_tiktok = "tiktok.com" in target_url.lower()
            async with TikTokDownloader() as app:
                app.check_config()
                await app.check_settings(False)

                link_extractor = ExtractorTikTok(app.parameter) if is_tiktok else Extractor(app.parameter)
                ids = await link_extractor.run(target_url, type_="detail")
                if not ids:
                    raise RuntimeError(f"Could not extract video ID from URL: {target_url}")

                detail_id = ids[0]
                print(f"[DownloaderAPI] Found video ID: {detail_id}. Fetching metadata...")
                detail_obj = (DetailTikTok if is_tiktok else Detail)(app.parameter, detail_id=detail_id)
                detail_data = await detail_obj.run()
                if not detail_data:
                    raise RuntimeError(f"Failed to fetch detail metadata for ID: {detail_id}")

                volume_download_dir = self.base_dir / "Volume" / "Download"
                dirs_to_check = [out_path] if out_path == volume_download_dir else [volume_download_dir, out_path]

                before_files = {p for d in dirs_to_check for p in d.glob("*.mp4")}
                record_manager = RecordManager()
                root, params, logger_cls = record_manager.run(app.parameter)
                data_extractor = DataExtractor(app.parameter)
                downloader = Downloader(app.parameter)

                async with logger_cls(root, console=app.console, **params) as record:
                    extracted_info = await data_extractor.run([detail_data], record, tiktok=is_tiktok)
                    if not extracted_info:
                        raise RuntimeError("Failed to extract downloadable video stream.")
                    info = extracted_info[0]
                    desc = info.get("desc", "video")
                    create_time = str(info.get("create_time", "")).replace(":", ".")
                    nickname = str(info.get("nickname", ""))
                    expected_stem = downloader.generate_detail_name(info)
                    stem_prefix = expected_stem[:32] if len(expected_stem) > 32 else expected_stem

                    pre_match = [
                        p for d in dirs_to_check for p in d.glob("*.mp4")
                        if p.stem == expected_stem
                        or (stem_prefix and p.stem.startswith(stem_prefix))
                        or (create_time and nickname and create_time in p.name and nickname in p.name)
                        or detail_id in p.name
                    ]
                    if pre_match:
                        found_video = pre_match[0]
                        print(f"[DownloaderAPI] Found cached video matching metadata: {found_video.name}")
                    else:
                        print(f"[DownloaderAPI] Starting download: {desc}")
                        await downloader.run(extracted_info, "detail", tiktok=is_tiktok)

                        after_files = {p for d in dirs_to_check for p in d.glob("*.mp4")}
                        new_files = list(after_files - before_files)
                        if new_files:
                            found_video = new_files[0]
                        else:
                            # If skipped by SQLite recorder because file was cleaned up from disk, delete DB record and re-download
                            try:
                                import sqlite3
                                db_p = Path("TikTokDownloader/Volume/DouK-Downloader.db")
                                if db_p.exists():
                                    with sqlite3.connect(str(db_p)) as conn:
                                        conn.execute("DELETE FROM download_data WHERE ID = ?", (str(detail_id),))
                                        conn.commit()
                                print(f"[DownloaderAPI] Cleared stale DB record for ID {detail_id}; re-fetching fresh video...")
                                await downloader.run(extracted_info, "detail", tiktok=is_tiktok)
                                after_files = {p for d in dirs_to_check for p in d.glob("*.mp4")}
                                new_files = list(after_files - before_files)
                            except Exception as re_err:
                                print(f"[DownloaderAPI] DB record clear error: {re_err}")

                            if new_files:
                                found_video = new_files[0]
                            else:
                                matching = [
                                    p for d in dirs_to_check for p in d.glob("*.mp4")
                                    if p.stem == expected_stem
                                    or (stem_prefix and p.stem.startswith(stem_prefix))
                                    or (create_time and nickname and create_time in p.name and nickname in p.name)
                                    or detail_id in p.name
                                ]
                                if matching:
                                    found_video = matching[0]
                                else:
                                    raise RuntimeError(f"Download skipped or missing on disk for ID {detail_id} ({expected_stem}).")

                # If found in volume_download_dir and out_path is different, move to out_path
                if out_path.resolve() != found_video.parent.resolve():
                    dest = out_path / found_video.name
                    import shutil
                    if dest.exists():
                        dest.unlink()
                    shutil.move(str(found_video), str(dest))
                    found_video = dest

                print(f"[DownloaderAPI] Downloaded video ready at: {found_video.name}")
                return found_video

        return asyncio.run(_async_download(url))

    def download_channel(
        self,
        channel_url: str,
        output_dir: Optional[Union[str, Path]] = None,
        max_videos: Optional[int] = None,
        sort_by: str = "popularity",
        max_pages: Optional[int] = None
    ) -> Path:
        """
        Download all videos from a Douyin profile / channel URL into a dedicated folder.

        Args:
            channel_url: Douyin profile URL (e.g. https://www.douyin.com/user/...) or shortlink.
            output_dir: Base directory where the channel folder will be created (default: input/).
            max_videos: Max number of videos to download (default: None for all available).
            sort_by: 'popularity' (highest likes first) or 'latest' / 'date'.
            max_pages: Optional limit on pagination requests.

        Returns:
            Path pointing to the folder containing the downloaded channel videos.
        """
        import re
        import shutil

        # Clean and normalize channel_url
        channel_url = str(channel_url).strip().strip("'\"")
        url_match = re.search(r"https?://[^\s\"<>\\^`{|}，。；！？、【】《》]+", channel_url)
        if url_match:
            channel_url = url_match.group(0)
        elif channel_url.startswith("MS4wLjABAAAA"):
            channel_url = f"https://www.douyin.com/user/{channel_url}"
        elif channel_url.startswith("douyin.com") or channel_url.startswith("www.douyin.com") or channel_url.startswith("v.douyin.com"):
            channel_url = f"https://{channel_url}"

        project_root = Path(__file__).resolve().parent.parent
        default_input_dir = project_root / "input"
        out_base = Path(output_dir) if output_dir else default_input_dir
        out_base.mkdir(parents=True, exist_ok=True)

        print("\n" + "=" * 65)
        print(" [DownloaderAPI] Extracting Douyin Channel / Profile")
        print(f" Target Channel URL : {channel_url}")
        print(f" Output Base Folder : {out_base}")
        print(f" Sort By Strategy   : {sort_by} (Max: {max_videos or 'All'})")
        print("=" * 65)

        from src.application import TikTokDownloader
        from src.application.main_terminal import TikTok
        from src.link import Extractor
        from src.interface import Detail, User

        def sanitize_folder_name(name: str) -> str:
            cleaned = re.sub(r'[\\/*?:"<>|]', "", str(name))
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            return cleaned or "douyin_channel"

        async def _async_download_channel() -> Path:
            async with TikTokDownloader() as app:
                app.check_config()
                await app.check_settings(False)
                terminal = TikTok(app.parameter, app.database, server_mode=True)
                link_extractor = Extractor(app.parameter)

                # 1. Resolve sec_user_id and nickname
                sec_uid = None
                channel_name = None

                # Check if direct user URL
                sec_uids = await link_extractor.run(channel_url, "user")
                if sec_uids and sec_uids[0]:
                    sec_uid = sec_uids[0]
                    try:
                        user_obj = User(app.parameter, sec_user_id=sec_uid)
                        user_data = await user_obj.run()
                        if user_data and "nickname" in user_data:
                            channel_name = user_data["nickname"]
                    except Exception:
                        pass

                # If not resolved as user, check if video detail link of author
                if not sec_uid:
                    detail_ids = await link_extractor.run(channel_url, "detail")
                    if detail_ids and detail_ids[0]:
                        vid = detail_ids[0]
                        print(f"[DownloaderAPI] URL appears to be a video ({vid}). Resolving author channel...")
                        detail_obj = Detail(app.parameter, detail_id=vid)
                        detail_data = await detail_obj.run()
                        if detail_data and "author" in detail_data:
                            author = detail_data["author"]
                            sec_uid = author.get("sec_uid")
                            channel_name = author.get("nickname")

                if not sec_uid:
                    raise RuntimeError(f"Could not resolve Douyin channel sec_user_id from: {channel_url}")

                print(f"[DownloaderAPI] Resolved sec_user_id: {sec_uid}")
                if channel_name:
                    print(f"[DownloaderAPI] Author Nickname: {channel_name}")

                # 2. Hook account data extraction to sort by popularity if requested
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

                        if sort_by in ("popularity", "popular", "likes", "like"):
                            print(f"[DownloaderAPI] Sorting {len(data)} works by popularity (highest likes first)...")
                            data.sort(
                                key=lambda x: (x.get("statistics") or {}).get("digg_count", 0),
                                reverse=True
                            )
                            if max_videos:
                                print(f"[DownloaderAPI] Selected Top {max_videos} most popular videos to download.")
                                data = data[:max_videos]

                    return data, earliest, latest

                terminal._get_account_data = hooked_get_account_data

                # Track state of Volume directory before downloading
                volume_dir = self.base_dir / "Volume"
                volume_dir.mkdir(parents=True, exist_ok=True)
                dirs_before = {d.resolve(): d.stat().st_mtime for d in volume_dir.iterdir() if d.is_dir()}

                # 3. Download channel works
                print(f"[DownloaderAPI] Downloading works for account: {sec_uid}...")
                success = await terminal.deal_account_detail(
                    index=1,
                    sec_user_id=sec_uid,
                    pages=max_pages
                )
                terminal._get_account_data = orig_get_data

                if not success:
                    print(f"[DownloaderAPI] Warning: deal_account_detail completed without items or was aborted.")

                # 4. Locate downloaded directory in TikTokDownloader/Volume/
                all_volume_dirs = [
                    d for d in volume_dir.iterdir()
                    if d.is_dir() and d.name not in ("Cache", "Data", "Download")
                ]

                # Priority 1: Newly created or modified directory during this download
                candidate_dirs = [
                    d for d in all_volume_dirs
                    if (d.resolve() not in dirs_before) or (d.stat().st_mtime > dirs_before.get(d.resolve(), 0))
                ]

                # Priority 2: Directory name matching channel nickname
                if not candidate_dirs and channel_name:
                    candidate_dirs = [d for d in all_volume_dirs if channel_name in d.name]

                # Priority 3: Directory name containing sec_uid
                if not candidate_dirs:
                    candidate_dirs = [d for d in all_volume_dirs if sec_uid in d.name]

                # Priority 4: Most recently modified UID* directory (UID*_Posts or UID*_发布作品)
                if not candidate_dirs:
                    uid_dirs = [d for d in all_volume_dirs if d.name.startswith("UID")]
                    if uid_dirs:
                        candidate_dirs = [max(uid_dirs, key=lambda d: d.stat().st_mtime)]
                    elif all_volume_dirs:
                        candidate_dirs = [max(all_volume_dirs, key=lambda d: d.stat().st_mtime)]

                source_folder = candidate_dirs[0] if candidate_dirs else None
                if source_folder:
                    parts = source_folder.name.split("_")
                    if len(parts) >= 3 and not channel_name:
                        channel_name = parts[1]

                if not channel_name:
                    channel_name = f"Channel_{sec_uid[:12]}"

                clean_name = sanitize_folder_name(channel_name)
                channel_dest = out_base / clean_name
                channel_dest.mkdir(parents=True, exist_ok=True)

                print(f"[DownloaderAPI] Destination folder: {channel_dest}")

                # 5. Move all .mp4 videos and .txt caption files into destination folder
                downloaded_count = 0
                if source_folder and source_folder.exists():
                    print(f"[DownloaderAPI] Moving videos from: {source_folder.name} to {channel_dest.name}")
                    for item_file in source_folder.iterdir():
                        if item_file.is_file() and item_file.suffix.lower() in [".mp4", ".txt"]:
                            dest_file = channel_dest / item_file.name
                            if not dest_file.exists():
                                shutil.copy2(str(item_file), str(dest_file))
                            if item_file.suffix.lower() == ".mp4":
                                downloaded_count += 1

                # If no files found in source_folder, check if channel_dest already has videos
                existing_videos = list(channel_dest.glob("*.mp4"))
                if not existing_videos and downloaded_count == 0:
                    raise RuntimeError(f"No videos downloaded for channel {channel_url} in {source_folder}")

                print(f"[DownloaderAPI] Successfully prepared {len(existing_videos)} videos in: {channel_dest}")
                return channel_dest

        return asyncio.run(_async_download_channel())

