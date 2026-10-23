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
