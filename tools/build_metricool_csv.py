import csv
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

TEMPLATE_CSV = Path(r"c:\Users\rudra\Downloads\Mtr_calendar_template.csv")
BATCH_DIR = Path(r"I:\My Drive\douyin\animal_viral_mirrored_batch")
METADATA_JSON = BATCH_DIR / "metadata.json"
ENRICHED_JSON = BATCH_DIR / "metricool_enriched.json"
LINKS_JSON = BATCH_DIR / "drive_links.json"

OUT_DRIVE_CSV = BATCH_DIR / "metricool_schedule_direct.csv"
OUT_LOCAL_CSV = Path("output/metricool_schedule.csv")

MAX_YT_TITLE_CHARS = 98  # Shorter than 100 UTF-16 units required by YouTube/Metricool
MAX_FB_TITLE_CHARS = 250  # Strictly <= 255 UTF-16 units with margin
MAX_COMBINED_TEXT_UTF8 = 400  # Strict <= 500 UTF-8 bytes (even with emoji/URL overhead) on Threads
MAX_IMPORTS_PER_MONTH = 20

# Core documentary & animal niche keywords to append within Threads' 500-char limit
CORE_DOC_KEYWORDS = [
    "wildlife documentary in hindi",
    "animal documentary",
    "nature documentary",
    "animal behavior",
    "symbiosis in nature",
    "3d wildlife animation hindi",
    "wild animals survival",
    "वन्यजीव डॉक्यूमेंट्री",
    "प्रकृति के रहस्य",
]


def utf8_len(text: str) -> int:
    """Measure UTF-8 byte length (Threads API counts UTF-8 bytes for non-ASCII/emojis)."""
    return len(text.encode("utf-8"))


def utf16_len(text: str) -> int:
    """Measure string length in UTF-16 code units (matching JS/YouTube/Facebook)."""
    return len(text.encode("utf-16-le")) // 2


def clamp_text(text: str, max_u16: int) -> str:
    """Trim text cleanly at word boundary without exceeding max_u16 UTF-16 units."""
    text = text.strip()
    if utf16_len(text) <= max_u16:
        return text
    words = text.split()
    out = ""
    for w in words:
        cand = w if not out else f"{out} {w}"
        if utf16_len(cand) > max_u16:
            break
        out = cand
    if out:
        return out
    trimmed = text
    while trimmed and utf16_len(trimmed) > max_u16:
        trimmed = trimmed[:-1]
    return trimmed.strip()


YT_TITLE_SUFFIX = " #shorts #fyp"


def format_youtube_title(title: str) -> str:
    """Append '#shorts #fyp' to Hindi YouTube title while staying < 100 UTF-16 units."""
    cleaned = re.sub(r"#\S+", "", title)
    cleaned = re.sub(r"[<>]", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    base_max = MAX_YT_TITLE_CHARS - utf16_len(YT_TITLE_SUFFIX)
    base = clamp_text(cleaned, base_max)
    return f"{base}{YT_TITLE_SUFFIX}"


def format_facebook_title(title: str, max_u16: int = MAX_FB_TITLE_CHARS) -> str:
    """Keep Hindi Facebook title + whole #hashtags within <= 255 UTF-16 units."""
    title = re.sub(r"\s{2,}", " ", title.strip())
    if utf16_len(title) <= max_u16:
        return title
    if "#" not in title:
        return clamp_text(title, max_u16)

    prefix, hash_part = title.split("#", 1)
    prefix = prefix.strip()
    hashtags = [tag.strip() for tag in f"#{hash_part}".split() if tag.strip()]
    if utf16_len(prefix) >= max_u16:
        return clamp_text(prefix, max_u16)

    out = prefix
    for tag in hashtags:
        cand = f"{out} {tag}"
        if utf16_len(cand) > max_u16:
            break
        out = cand
    return out


def build_combined_text(hook_hi: str, extra_kw: str, raw_tags: list[str]) -> str:
    """Build single-line Hindi hook + documentary keywords <= 400 UTF-8 bytes, 0 hashtags."""
    clean_hook = re.sub(r"#\S+", "", hook_hi).replace("\n", " ").strip()
    clean_hook = re.sub(r"\s{2,}", " ", clean_hook)

    # Deduplicate candidate keywords (video-specific first, then core documentary niche)
    seen: set[str] = set()
    candidates: list[str] = []
    raw_pool = list(extra_kw.split(",")) + [t for t in raw_tags] + CORE_DOC_KEYWORDS
    for token in raw_pool:
        tok = re.sub(r"#\S+", "", str(token)).replace("\n", " ").strip()
        key = tok.lower()
        if tok and key not in seen:
            seen.add(key)
            candidates.append(tok)

    prefix = f"{clean_hook} | "
    budget = MAX_COMBINED_TEXT_UTF8 - utf8_len(prefix)
    if budget <= 15:
        return clean_hook

    chosen: list[str] = []
    cur = 0
    for kw in candidates:
        add = kw if not chosen else f", {kw}"
        if cur + utf8_len(add) > budget:
            continue
        chosen.append(kw)
        cur += utf8_len(add)

    return f"{prefix}{', '.join(chosen)}" if chosen else clean_hook


def to_direct_drive_url(url: str) -> str:
    """Convert Google Drive view URL to direct CDN download URL for Metricool."""
    if "/file/d/" in url:
        fid = url.split("/file/d/", 1)[1].split("/", 1)[0]
        return f"https://drive.usercontent.google.com/download?id={fid}&export=download&file=video.mp4"
    return url


def allocate_monthly_slots(
    total_videos: int, start_date: datetime, per_month_cap: int = MAX_IMPORTS_PER_MONTH
) -> list[datetime]:
    """Assign up to per_month_cap (20) video timestamps per calendar month."""
    slots: list[datetime] = []
    month_counts: dict[tuple[int, int], int] = defaultdict(int)
    cur_day = start_date.replace(hour=18, minute=0, second=0, microsecond=0)

    days_left = 0
    probe = cur_day
    while probe.month == start_date.month and probe.year == start_date.year:
        days_left += 1
        probe += timedelta(days=1)

    if total_videos >= per_month_cap and days_left < per_month_cap:
        for d in range(per_month_cap - days_left):
            extra_dt = (start_date + timedelta(days=d)).replace(
                hour=12, minute=0, second=0, microsecond=0
            )
            if len(slots) < total_videos and month_counts[(extra_dt.year, extra_dt.month)] < per_month_cap:
                slots.append(extra_dt)
                month_counts[(extra_dt.year, extra_dt.month)] += 1

    while len(slots) < total_videos:
        ym = (cur_day.year, cur_day.month)
        if month_counts[ym] < per_month_cap:
            slots.append(cur_day)
            month_counts[ym] += 1
            cur_day += timedelta(days=1)
        else:
            cur_day = (
                cur_day.replace(year=cur_day.year + 1, month=1, day=1)
                if cur_day.month == 12
                else cur_day.replace(month=cur_day.month + 1, day=1)
            )

    slots.sort()
    return slots


def write_csv(path: Path, headers: list[str], rows: list[dict[str, str]]) -> Path:
    """Write CSV with UTF-8 BOM, falling back if file is locked open."""
    path.parent.mkdir(parents=True, exist_ok=True)
    target = path
    try:
        with target.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
    except PermissionError:
        target = path.with_name(path.stem + "_new" + path.suffix)
        with target.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {target}")
    return target


def main() -> None:
    with TEMPLATE_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        headers = next(csv.reader(f))

    meta = json.loads(METADATA_JSON.read_text(encoding="utf-8"))
    enriched = json.loads(ENRICHED_JSON.read_text(encoding="utf-8"))
    links = json.loads(LINKS_JSON.read_text(encoding="utf-8"))

    brand_name = enriched.get("brand_name", "humourforu")
    enriched_by_file = {v["filename"]: v for v in enriched["videos"]}

    videos = meta["videos"]
    start_dt = datetime(2026, 11, 12, 18, 0, 0)
    slots = allocate_monthly_slots(len(videos), start_dt, MAX_IMPORTS_PER_MONTH)

    all_rows: list[dict[str, str]] = []
    for vid, sched_dt in zip(videos, slots):
        fn = vid["filename"]
        if fn not in links:
            raise KeyError(f"Missing Google Drive link for {fn}")
        if fn not in enriched_by_file:
            raise KeyError(f"Missing enriched metadata for {fn}")

        ev = enriched_by_file[fn]
        link_entry = links[fn]
        raw_url = link_entry["url"] if isinstance(link_entry, dict) else link_entry
        direct_url = to_direct_drive_url(raw_url)
        tags_list = vid.get("tags", [])[:3]
        tags_str = ", ".join(tags_list)

        yt_title = format_youtube_title(ev["youtube_title_hi"])
        fb_title = format_facebook_title(ev["facebook_title_hi"])
        combined_text = build_combined_text(
            ev.get("threads_hook_short") or ev["threads_text_hi"],
            ev.get("extra_keywords", ""),
            tags_list,
        )

        row = {h: "" for h in headers}
        row.update(
            {
                "Text": combined_text,
                "Date": sched_dt.strftime("%Y-%m-%d"),
                "Time": sched_dt.strftime("%H:%M:%S"),
                "Draft": "false",
                "Facebook": "true",
                "Twitter/X": "false",
                "LinkedIn": "false",
                "GBP": "false",
                "Instagram": "true",
                "Pinterest": "false",
                "TikTok": "false",
                "Youtube": "true",
                "Threads": "true",
                "Bluesky": "false",
                "Picture Url 1": direct_url,
                "Instagram Post Type": "REEL",
                "Instagram Show Reel On Feed": "true",
                "Youtube Video Title": yt_title,
                "Youtube Video Type": "SHORT",
                "Youtube Video Privacy": "PUBLIC",
                "Youtube video for kids": "false",
                "Youtube AI generated content": "true",
                "Youtube notify subscribers": "true",
                "Youtube Video Category": "FILM_ANIMATION",
                "Youtube Video Tags": tags_str,
                "Facebook Post Type": "REEL",
                "Facebook Title": fb_title,
                "Threads Reply Control": "EVERYONE",
                "Threads Is Spoiler": "false",
                "Threads Post Type": "POST",
                "Brand name": brand_name,
            }
        )
        all_rows.append(row)

    write_csv(OUT_LOCAL_CSV, headers, all_rows)
    write_csv(OUT_DRIVE_CSV, headers, all_rows)


if __name__ == "__main__":
    main()
