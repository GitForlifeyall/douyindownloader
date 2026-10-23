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
from typing import Optional, Union

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
                    desc = extracted_info[0].get("desc", "video")
                    print(f"[DownloaderAPI] Starting download: {desc}")
                    await downloader.run(extracted_info, "detail", tiktok=is_tiktok)

                after_files = {p for d in dirs_to_check for p in d.glob("*.mp4")}
                new_files = list(after_files - before_files)
                if new_files:
                    found_video = new_files[0]
                else:
                    # Match by video ID if not detected in difference
                    matching = [p for d in dirs_to_check for p in d.glob("*.mp4") if detail_id in p.name]
                    if matching:
                        found_video = matching[0]
                    else:
                        # Fallback to most recent non-dubbed video
                        raw_videos = [
                            p for d in dirs_to_check for p in d.glob("*.mp4")
                            if "dubbed" not in p.name and "_clean" not in p.name and "sample" not in p.name and "half" not in p.name and "temp" not in p.name
                        ]
                        if raw_videos:
                            found_video = max(raw_videos, key=lambda f: f.stat().st_mtime)
                        else:
                            raise RuntimeError("Download completed, but raw video file was not found in destination directory.")

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
                volume_dir = self.base_dir / "Volume"
                matching_dirs = [
                    d for d in volume_dir.iterdir()
                    if d.is_dir() and sec_uid in d.name
                ]
                if not matching_dirs:
                    posts_dirs = [d for d in volume_dir.glob("UID*_Posts") if d.is_dir()]
                    if posts_dirs:
                        matching_dirs = [max(posts_dirs, key=lambda d: d.stat().st_mtime)]

                source_folder = None
                if matching_dirs:
                    source_folder = matching_dirs[0]
                    parts = source_folder.name.split("_")
                    if len(parts) >= 3 and not channel_name:
                        channel_name = parts[1]

                if not channel_name:
                    channel_name = f"Channel_{sec_uid[:12]}"

                clean_name = sanitize_folder_name(channel_name)
                channel_dest = out_base / clean_name
                channel_dest.mkdir(parents=True, exist_ok=True)

                print(f"[DownloaderAPI] Moving downloaded channel videos to: {channel_dest}")

                # 5. Move all .mp4 videos and .txt caption files into destination folder
                downloaded_count = 0
                if source_folder and source_folder.exists():
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

