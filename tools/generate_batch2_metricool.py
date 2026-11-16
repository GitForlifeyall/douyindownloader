import csv
import json
import os
import re
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DRIVE_BATCH2 = Path(r"I:\My Drive\douyin\channel pending movies\batch_2")
DB_SRC = os.path.expandvars(r"%LOCALAPPDATA%\Google\DriveFS\109229035234283636114\metadata_sqlite_db")
LOCAL_OUT = Path("output/metricool_batch_2.csv")
DRIVE_OUT = DRIVE_BATCH2 / "metricool_batch_2.csv"

def load_headers() -> list[str]:
    with open("output/metricool_batch_1.csv", "r", encoding="utf-8-sig") as f:
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

def get_drive_file_id(cur: sqlite3.Cursor, title: str, drive_files: list[str]) -> str:
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
        with open(out_file, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
    except PermissionError:
        out_file = target_path.with_name(f"{target_path.stem}_updated{target_path.suffix}")
        with open(out_file, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
    return out_file

def main():
    headers = load_headers()
    
    # Copy DriveFS db to temp
    temp_db = Path("scratch/drivefs_query_batch2.db")
    temp_db.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DB_SRC, temp_db)
    
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    
    meta_path = DRIVE_BATCH2 / "metadata.json"
    with open(meta_path, "r", encoding="utf-8") as f:
        meta_data = json.load(f)
        
    videos = meta_data.get("videos", [])
    drive_files = [f.name for f in DRIVE_BATCH2.glob("*.mp4")]
    
    # Schedule: 20 videos per month (averaging every 1.5 days: alternating +1 day and +2 days)
    # Continuing immediately after Batch 1 (which ends on Dec 25, 2026) -> starts Dec 27, 2026 at 18:00:00
    start_date = datetime(2026, 12, 27, 18, 0, 0)
    slots = [start_date]
    for i in range(1, len(videos)):
        gap = 1 if (i % 2 == 1) else 2
        slots.append(slots[-1] + timedelta(days=gap))
    
    rows = []
    matched_count = 0
    
    for i, v in enumerate(videos):
        title = v.get("title", "")
        file_id = get_drive_file_id(cur, title, drive_files)
        
        if file_id:
            drive_url = f"https://drive.usercontent.google.com/download?id={file_id}&export=download&file=video.mp4"
            matched_count += 1
        else:
            drive_url = ""
            
        row = build_row(headers, title, slots[i], drive_url)
        rows.append(row)
        
    conn.close()
    
    written_local = safe_write_csv(LOCAL_OUT, headers, rows)
    written_drive = safe_write_csv(DRIVE_OUT, headers, rows)
    
    print(f"Batch 2 CSV generated with {len(rows)} posts.")
    print(f"Matched {matched_count}/{len(rows)} direct Google Drive CDN links.")
    print(f"Saved locally to: {written_local}")
    print(f"Saved to Drive:   {written_drive}")

if __name__ == "__main__":
    main()

