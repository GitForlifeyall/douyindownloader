import sys
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, ".")

from dubbing_studio.separator import AudioStemSeparator

def main():
    download_dir = Path("TikTokDownloader/Volume/Download")
    candidates = list(download_dir.glob("*道可道*.mp4"))
    if not candidates:
        print("Error: Could not find original downloaded video!")
        sys.exit(1)

    video_path = candidates[0]
    output_dir = Path("output/audio_stems")
    clean_name = "道可道 - 恭喜你成功制作出桂花蜜"

    print(f"Testing DBS-TIGER separator on: {video_path.name}")
    separator = AudioStemSeparator()
    stems = separator.separate_audio(
        video_or_audio_path=video_path,
        output_dir=output_dir,
        clean_name=clean_name,
        force=True
    )

    print("\n[Result] Separation finished successfully!")
    for k, v in stems.items():
        if isinstance(v, Path) and v.is_file():
            print(f"  {k:10s} : {v.name} ({v.stat().st_size / 1024 / 1024:.2f} MB)")
        else:
            print(f"  {k:10s} : {v}")

if __name__ == "__main__":
    main()
