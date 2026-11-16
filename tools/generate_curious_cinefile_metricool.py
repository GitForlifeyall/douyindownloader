import csv
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

TEMPLATE_CSV = Path(r"c:\Users\rudra\Downloads\Mtr_calendar_template.csv")
DRIVE_ROOT = Path(r"I:\My Drive\douyin\channel pending movies")

def load_headers() -> list[str]:
    if TEMPLATE_CSV.exists():
        with TEMPLATE_CSV.open("r", encoding="utf-8-sig", newline="") as f:
            return next(csv.reader(f))
    # Fallback to standard 99 Metricool headers if template not found
    with open("output/metricool_curious_cinefile.csv", "r", encoding="utf-8", errors="ignore") as f:
        return next(csv.reader(f))

def clean_title(title: str) -> str:
    # Remove all variations of (3D Animation In English) and (3D Animation)
    t = re.sub(r"\(\s*3d animation in english\s*\)", "", title, flags=re.IGNORECASE)
    t = re.sub(r"\(\s*3d animation\s*\)", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t

def make_text(title: str) -> str:
    # Strip #shorts from the title inside the comment prompt to keep it clean
    bare_title = re.sub(r"#\S+", "", title).strip()
    return f'Comment "MOVIE" for the movie name! 🍿🎬 {bare_title} #MovieRecap #MovieExplained #Shorts'

def build_row(headers: list[str], title: str, sched_dt: datetime) -> dict[str, str]:
    c_title = clean_title(title)
    if "#shorts" not in c_title.lower():
        yt_title = f"{c_title} #shorts"
    else:
        yt_title = c_title

    bare_title = re.sub(r"#\S+", "", c_title).strip()
    fb_title = f"{bare_title} #MovieExplained #MovieRecap"
    text_caption = make_text(yt_title)
    
    row = {h: "" for h in headers}
    row.update({
        "Text": text_caption,
        "Date": sched_dt.strftime("%Y-%m-%d"),
        "Time": sched_dt.strftime("%H:%M:%S"),
        "Draft": "false",
        "Facebook": "true",
        "Twitter/X": "false",
        "LinkedIn": "false",
        "GBP": "false",
        "Instagram": "true",
        "Pinterest": "false",
        "TikTok": "true",
        "Youtube": "true",
        "Threads": "true",
        "Bluesky": "false",
        "Instagram Post Type": "REEL",
        "Instagram Show Reel On Feed": "true",
        "Youtube Video Title": yt_title,
        "Youtube Video Type": "SHORT",
        "Youtube Video Privacy": "PUBLIC",
        "Youtube video for kids": "false",
        "Youtube AI generated content": "false",
        "Youtube notify subscribers": "true",
        "Youtube Video Category": "FILM_ANIMATION",
        "Youtube Video Tags": "movie, movie explanation, movie recap, movies, ending explained",
        "Facebook Post Type": "REEL",
        "Facebook Title": fb_title,
        "TikTok disable comments": "false",
        "TikTok disable duet": "false",
        "TikTok disable stitch": "false",
        "TikTok Post Privacy": "PUBLIC_TO_EVERYONE",
        "TikTok Branded Content": "false",
        "TikTok Your Brand": "false",
        "TikTok Auto Add Music": "false",
        "TikTok Ai generated content": "false",
        "Threads Reply Control": "EVERYONE",
        "Threads Is Spoiler": "false",
        "Threads Post Type": "POST",
        "Brand name": "Curious",
    })
    return row

def get_slots(start_dt: datetime, count: int) -> list[datetime]:
    slots = []
    # First 3 days: 2 posts per day (12:00:00 and 18:00:00)
    cur = start_dt
    day_count = 0
    while len(slots) < count:
        if day_count < 3:
            slots.append(cur.replace(hour=12, minute=0, second=0))
            if len(slots) < count:
                slots.append(cur.replace(hour=18, minute=0, second=0))
        else:
            slots.append(cur.replace(hour=18, minute=0, second=0))
        cur += timedelta(days=1)
        day_count += 1
    return slots

def safe_write_csv(target_path: Path, headers: list[str], rows: list[dict[str, str]]) -> Path:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    out_file = target_path
    try:
        with out_file.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=headers)
            w.writeheader()
            w.writerows(rows)
    except PermissionError:
        out_file = target_path.with_name(target_path.stem + "_updated" + target_path.suffix)
        with out_file.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=headers)
            w.writeheader()
            w.writerows(rows)
    print(f"Wrote {len(rows)} rows to {out_file}")
    return out_file

def main():
    headers = load_headers()
    headers[0] = headers[0].replace("\ufeff", "")

    # Load 3 batches
    cc_path = DRIVE_ROOT / "Curious Cinefile" / "metadata.json"
    b1_path = DRIVE_ROOT / "batch_1" / "metadata.json"
    b2_path = DRIVE_ROOT / "batch_2" / "metadata.json"

    cc_meta = json.loads(cc_path.read_text(encoding="utf-8"))["videos"]
    b1_meta = json.loads(b1_path.read_text(encoding="utf-8"))["videos"]
    b2_meta = json.loads(b2_path.read_text(encoding="utf-8"))["videos"]

    all_videos = cc_meta + b1_meta + b2_meta
    print(f"Loaded: Curious Cinefile={len(cc_meta)}, Batch 1={len(b1_meta)}, Batch 2={len(b2_meta)} -> Total={len(all_videos)}")

    start_date = datetime(2026, 11, 14)
    slots = get_slots(start_date, len(all_videos))

    all_rows = []
    for vid, slot in zip(all_videos, slots):
        all_rows.append(build_row(headers, vid["title"], slot))

    # 1. Master 100-video schedule
    safe_write_csv(Path("output/metricool_curious_cinefile.csv"), headers, all_rows)
    safe_write_csv(Path("output/metricool_curious_cinefile_100_master.csv"), headers, all_rows)

    # 2. The 62 new videos (Batch 1 + Batch 2)
    new_62_videos = b1_meta + b2_meta
    slots_62 = get_slots(datetime(2026, 12, 19), len(new_62_videos))
    rows_62 = [build_row(headers, v["title"], s) for v, s in zip(new_62_videos, slots_62)]
    safe_write_csv(Path("output/metricool_curious_cinefile_batches_1_and_2.csv"), headers, rows_62)

    # 3. Copy to Google Drive Curious Cinefile folder
    drive_out = DRIVE_ROOT / "Curious Cinefile" / "metricool_curious_cinefile_master.csv"
    safe_write_csv(drive_out, headers, all_rows)
    safe_write_csv(DRIVE_ROOT / "batch_1" / "metricool_batch_1.csv", headers, [build_row(headers, v["title"], s) for v, s in zip(b1_meta, slots_62[:len(b1_meta)])])
    safe_write_csv(DRIVE_ROOT / "batch_2" / "metricool_batch_2.csv", headers, [build_row(headers, v["title"], s) for v, s in zip(b2_meta, slots_62[len(b1_meta):])])

if __name__ == "__main__":
    main()
