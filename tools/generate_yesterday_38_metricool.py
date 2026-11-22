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
            headers = next(csv.reader(f))
            headers[0] = headers[0].replace("\ufeff", "")
            return headers
    with open("output/metricool_curious_cinefile_100_master.csv", "r", encoding="utf-8-sig") as f:
        headers = next(csv.reader(f))
        headers[0] = headers[0].replace("\ufeff", "")
        return headers

def clean_title(title: str) -> str:
    t = re.sub(r"\(\s*3d animation in english\s*\)", "", title, flags=re.IGNORECASE)
    t = re.sub(r"\(\s*3d animation\s*\)", "", t, flags=re.IGNORECASE)
    t = re.sub(r"3d animation", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t

def make_text(title: str) -> str:
    bare_title = re.sub(r"#\S+", "", title).strip()
    return f'Comment "MOVIE" for the movie name! 🍿🎬 {bare_title} #MovieRecap #MovieExplained #Shorts'

def build_row(headers: list[str], title: str, sched_dt: datetime) -> dict[str, str]:
    c_title = clean_title(title)
    if "#shorts" not in c_title.lower():
        yt_title = f"{c_title} #shorts"
    else:
        yt_title = c_title

    text_caption = make_text(yt_title)
    
    row = {h: "" for h in headers}
    row.update({
        "Text": text_caption,
        "Date": sched_dt.strftime("%Y-%m-%d"),
        "Time": sched_dt.strftime("%H:%M:%S"),
        "Draft": "true",
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
        "Youtube AI generated content": "true",
        "Youtube notify subscribers": "true",
        "Youtube Video Category": "FILM_ANIMATION",
        "Youtube Video Tags": "movie, movie explanation, movie recap, movies, ending explained",
        "Facebook Post Type": "REEL",
        "Facebook Title": yt_title,
        "TikTok disable comments": "false",
        "TikTok disable duet": "false",
        "TikTok disable stitch": "false",
        "TikTok Post Privacy": "PUBLIC_TO_EVERYONE",
        "TikTok Branded Content": "false",
        "TikTok Your Brand": "false",
        "TikTok Auto Add Music": "false",
        "TikTok Ai generated content": "true",
        "Threads Reply Control": "EVERYONE",
        "Threads Is Spoiler": "false",
        "Threads Post Type": "POST",
        "Brand name": "Curious",
    })
    return row

def get_slots(start_dt: datetime, count: int) -> list[datetime]:
    slots = []
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

def main():
    headers = load_headers()

    # Load yesterday's 38 Curious Cinefile videos from Google Drive
    cc_path = DRIVE_ROOT / "Curious Cinefile" / "metadata.json"
    cc_meta = json.loads(cc_path.read_text(encoding="utf-8"))["videos"]
    print(f"Loaded yesterday's Curious Cinefile: {len(cc_meta)} videos")

    start_date = datetime(2026, 11, 14)
    slots = get_slots(start_date, len(cc_meta))

    rows = []
    for vid, slot in zip(cc_meta, slots):
        rows.append(build_row(headers, vid["title"], slot))

    # 1. Write yesterday's 38 videos to dedicated output file
    out_yesterday = Path("output/metricool_curious_cinefile_yesterday_38.csv")
    with out_yesterday.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows to {out_yesterday}")

    # 2. Also save to Google Drive Curious Cinefile folder
    drive_yesterday = DRIVE_ROOT / "Curious Cinefile" / "metricool_schedule_38_videos_yesterday.csv"
    with drive_yesterday.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        w.writerows(rows)
    print(f"Saved to Google Drive: {drive_yesterday}")

if __name__ == "__main__":
    main()

