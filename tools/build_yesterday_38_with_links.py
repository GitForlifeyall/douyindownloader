import csv
import json
import os
import re
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

TEMPLATE_CSV = Path(r"c:\Users\rudra\Downloads\Mtr_calendar_template.csv")
DRIVE_ROOT = Path(r"I:\My Drive\douyin\channel pending movies")
DB_SRC = os.path.expandvars(r"%LOCALAPPDATA%\Google\DriveFS\109229035234283636114\metadata_sqlite_db")

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

def build_row(headers: list[str], title: str, sched_dt: datetime, drive_url: str) -> dict[str, str]:
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
        "Picture Url 1": drive_url,
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

def get_drive_file_id(cur: sqlite3.Cursor, title: str, drive_files: list[str]) -> str:
    # 1. First find matching filename in local directory
    clean = re.sub(r"[^\w\s]", "", title).strip().lower()
    words = clean.split()
    target_f = ""
    for f in drive_files:
        f_clean = re.sub(r"[^\w\s]", "", f).strip().lower()
        if len(words) >= 3 and " ".join(words[:3]) in f_clean:
            target_f = f
            break
        elif len(words) >= 2 and " ".join(words[:2]) in f_clean:
            target_f = f
            break
            
    if target_f:
        cur.execute("SELECT id FROM items WHERE local_title = ?", (target_f,))
        row = cur.fetchone()
        if row:
            return row[0]

    # 2. Fallback prefix query
    query_prefix = " ".join(words[:4]) if len(words) >= 4 else clean
    cur.execute("SELECT id FROM items WHERE local_title LIKE ? AND local_title LIKE ?", (f"%{query_prefix}%", "%.mp4"))
    row = cur.fetchone()
    if row:
        return row[0]
        
    return ""

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

    # Copy DriveFS db to scratch to query without locking
    shutil.copy(DB_SRC, "scratch/drivefs_query.db")
    conn = sqlite3.connect("scratch/drivefs_query.db")
    cur = conn.cursor()

    # Load yesterday's Curious Cinefile metadata
    cc_dir = DRIVE_ROOT / "Curious Cinefile"
    cc_path = cc_dir / "metadata.json"
    cc_meta = json.loads(cc_path.read_text(encoding="utf-8"))["videos"]
    drive_files = [f.name for f in cc_dir.iterdir() if f.suffix == ".mp4"]

    start_date = datetime(2026, 11, 14)
    slots = get_slots(start_date, len(cc_meta))

    rows = []
    found_links = 0
    for i, (vid, slot) in enumerate(zip(cc_meta, slots)):
        title = vid["title"]
        fid = get_drive_file_id(cur, title, drive_files)
        
        if fid:
            found_links += 1
            # Direct download CDN URL for Metricool
            drive_url = f"https://drive.usercontent.google.com/download?id={fid}&export=download&file=video.mp4"
        else:
            drive_url = ""
            print(f"Warning: Could not find Drive ID for video {i+1}: {title}")

        rows.append(build_row(headers, title, slot, drive_url))

    print(f"Successfully matched {found_links}/{len(cc_meta)} Google Drive direct URLs!")

    # 1. Write yesterday's 38 to output/metricool_curious_cinefile_yesterday_38.csv
    out_file = safe_write_csv(Path("output/metricool_curious_cinefile_yesterday_38.csv"), headers, rows)

    # 2. Also write to Google Drive folder
    drive_out = DRIVE_ROOT / "Curious Cinefile" / "metricool_schedule_38_with_drive_links.csv"
    safe_write_csv(drive_out, headers, rows)

if __name__ == "__main__":
    main()
