import time
import sys
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dubbing_studio.downloader import DownloaderAPI

url = "https://www.douyin.com/video/7686433263632427898"
print(f"Starting download for {url}...")

t0 = time.time()
downloader = DownloaderAPI()
video_path = downloader.download_video(url)
t1 = time.time()

print(f"\n[TIMING] Download completed in: {t1 - t0:.2f} seconds")
print(f"Video file: {video_path}")
print(f"File size: {video_path.stat().st_size / (1024*1024):.2f} MB")
