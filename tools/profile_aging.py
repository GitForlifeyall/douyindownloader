#!/usr/bin/env python3
"""
tools/profile_aging.py
======================
Seeds realistic Bookmarks Toolbar entries, browsing history, and UI visibility
into Camoufox/Firefox profiles to give profiles an aged, authentically used appearance.
"""

import sys
import os
import sqlite3
import time
import random
import json

def generate_guid(length=12):
    chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
    return "".join(random.choice(chars) for _ in range(length))

def reverse_host(url):
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc
        if not host:
            return ""
        return ".".join(reversed(host.split("."))) + "."
    except:
        return ""

DEFAULT_TOOLBAR_BOOKMARKS = [
    ("Google", "https://www.google.com/"),
    ("YouTube", "https://www.youtube.com/"),
    ("Reddit", "https://www.reddit.com/"),
    ("Wikipedia", "https://www.wikipedia.org/"),
    ("Amazon", "https://www.amazon.com/"),
    ("Netflix", "https://www.netflix.com/"),
    ("BBC News", "https://www.bbc.com/news"),
    ("Outlook", "https://outlook.live.com/"),
    ("Weather", "https://weather.com/"),
]

REALISTIC_HISTORY_SITES = [
    ("Google - weather today", "https://www.google.com/search?q=weather+today"),
    ("Google - top movies 2025", "https://www.google.com/search?q=top+movies+2025"),
    ("Google - healthy quick dinner recipes", "https://www.google.com/search?q=healthy+quick+dinner+recipes"),
    ("Google - best wireless headphones review", "https://www.google.com/search?q=best+wireless+headphones+review"),
    ("Google - local coffee shops", "https://www.google.com/search?q=local+coffee+shops"),
    ("Wikipedia - Earth", "https://en.wikipedia.org/wiki/Earth"),
    ("Wikipedia - Solar System", "https://en.wikipedia.org/wiki/Solar_System"),
    ("Wikipedia - World Wide Web", "https://en.wikipedia.org/wiki/World_Wide_Web"),
    ("Wikipedia - History of cinema", "https://en.wikipedia.org/wiki/History_of_cinema"),
    ("Wikipedia - Artificial intelligence", "https://en.wikipedia.org/wiki/Artificial_intelligence"),
    ("Reddit - AskReddit", "https://www.reddit.com/r/AskReddit/"),
    ("Reddit - Technology", "https://www.reddit.com/r/technology/"),
    ("Reddit - Science", "https://www.reddit.com/r/science/"),
    ("Reddit - Movies", "https://www.reddit.com/r/movies/"),
    ("YouTube - Trending", "https://www.youtube.com/feed/trending"),
    ("YouTube - Explore", "https://www.youtube.com/feed/explore"),
    ("BBC News - World", "https://www.bbc.com/news/world"),
    ("Reuters - World News", "https://www.reuters.com/world/"),
    ("CNN - Breaking News", "https://www.cnn.com/"),
    ("TechCrunch - Latest", "https://techcrunch.com/"),
    ("Amazon - Today's Deals", "https://www.amazon.com/gp/goldbox"),
    ("Amazon - Best Sellers", "https://www.amazon.com/Best-Sellers/zgbs"),
    ("IMDb - Top 250 Movies", "https://www.imdb.com/chart/top/"),
    ("Rotten Tomatoes", "https://www.rottentomatoes.com/"),
    ("GitHub", "https://github.com/"),
    ("Stack Overflow", "https://stackoverflow.com/"),
    ("Medium", "https://medium.com/"),
    ("The Verge", "https://www.theverge.com/"),
]

def seed_profile(profile_dir):
    profile_dir = os.path.abspath(profile_dir)
    os.makedirs(profile_dir, exist_ok=True)
    db_path = os.path.join(profile_dir, "places.sqlite")

    # Clean stale lock files if browser is not actively running
    for ext in ["-wal", "-shm"]:
        p = db_path + ext
        if os.path.exists(p) and not os.path.exists(os.path.join(profile_dir, "parent.lock")):
            try: os.remove(p)
            except: pass

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS moz_places (
        id INTEGER PRIMARY KEY,
        url TEXT,
        title TEXT,
        rev_host TEXT,
        visit_count INTEGER DEFAULT 0,
        hidden INTEGER DEFAULT 0,
        typed INTEGER DEFAULT 0,
        frecency INTEGER DEFAULT -1,
        last_visit_date INTEGER,
        guid TEXT UNIQUE,
        foreign_count INTEGER DEFAULT 0,
        url_hash INTEGER DEFAULT 0,
        description TEXT,
        preview_image_url TEXT,
        origin_id INTEGER DEFAULT 0
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS moz_historyvisits (
        id INTEGER PRIMARY KEY,
        from_visit INTEGER,
        place_id INTEGER,
        visit_date INTEGER,
        visit_type INTEGER,
        session INTEGER
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS moz_bookmarks (
        id INTEGER PRIMARY KEY,
        type INTEGER,
        fk INTEGER,
        parent INTEGER,
        position INTEGER,
        title TEXT,
        keyword_id INTEGER,
        folder_type TEXT,
        dateAdded INTEGER,
        lastModified INTEGER,
        guid TEXT UNIQUE,
        syncStatus INTEGER DEFAULT 0,
        syncChangeCounter INTEGER DEFAULT 1
    );
    """)

    # Ensure standard root bookmark folders exist
    cur.execute("SELECT id FROM moz_bookmarks WHERE guid='root________';")
    now_us = int(time.time() * 1000000)
    if not cur.fetchone():
        cur.executemany("""
            INSERT OR IGNORE INTO moz_bookmarks (id, type, fk, parent, position, title, dateAdded, lastModified, guid)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            (1, 2, None, 0, 0, "", now_us, now_us, "root________"),
            (2, 2, None, 1, 0, "menu", now_us, now_us, "menu________"),
            (3, 2, None, 1, 1, "toolbar", now_us, now_us, "toolbar_____"),
            (4, 2, None, 1, 2, "tags", now_us, now_us, "tags________"),
            (5, 2, None, 1, 3, "unfiled", now_us, now_us, "unfiled_____"),
            (6, 2, None, 1, 4, "mobile", now_us, now_us, "mobile______"),
        ])

    now_sec = time.time()
    bookmarks_added = 0

    # 1. Insert Bookmarks on Toolbar (parent = 3)
    for pos, (title, url) in enumerate(DEFAULT_TOOLBAR_BOOKMARKS):
        cur.execute("SELECT id FROM moz_places WHERE url=?", (url,))
        row = cur.fetchone()
        place_id = None
        days_ago = random.uniform(3, 22)
        visit_time_us = int((now_sec - days_ago * 86400) * 1000000)
        v_count = random.randint(6, 28)

        if row:
            place_id = row[0]
            cur.execute("UPDATE moz_places SET visit_count=visit_count+?, frecency=2200 WHERE id=?", (v_count, place_id))
        else:
            cur.execute("""
                INSERT INTO moz_places (url, title, rev_host, visit_count, typed, frecency, last_visit_date, guid)
                VALUES (?, ?, ?, ?, 1, 2200, ?, ?)
            """, (url, title, reverse_host(url), v_count, visit_time_us, generate_guid()))
            place_id = cur.lastrowid

        # Insert visit entries
        for _ in range(min(v_count, 4)):
            v_us = int((now_sec - random.uniform(1, 25) * 86400) * 1000000)
            cur.execute("""
                INSERT INTO moz_historyvisits (from_visit, place_id, visit_date, visit_type, session)
                VALUES (0, ?, ?, 1, 0)
            """, (place_id, v_us))

        # Check if already in toolbar
        cur.execute("SELECT id FROM moz_bookmarks WHERE parent=3 AND fk=?", (place_id,))
        if not cur.fetchone():
            cur.execute("""
                INSERT INTO moz_bookmarks (type, fk, parent, position, title, dateAdded, lastModified, guid)
                VALUES (1, ?, 3, ?, ?, ?, ?, ?)
            """, (place_id, pos, title, visit_time_us, visit_time_us, generate_guid()))
            bookmarks_added += 1

    # 2. Seed Realistic Browsing History (if places count is small)
    cur.execute("SELECT COUNT(*) FROM moz_places WHERE url NOT LIKE '%facebook%' AND url NOT LIKE '%instagram%';")
    non_meta_count = cur.fetchone()[0]
    history_added = 0

    if non_meta_count < 20:
        for title, url in REALISTIC_HISTORY_SITES:
            cur.execute("SELECT id FROM moz_places WHERE url=?", (url,))
            if not cur.fetchone():
                days_ago = random.uniform(1, 30)
                visit_time_us = int((now_sec - days_ago * 86400) * 1000000)
                v_count = random.randint(1, 6)
                cur.execute("""
                    INSERT INTO moz_places (url, title, rev_host, visit_count, typed, frecency, last_visit_date, guid)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (url, title, reverse_host(url), v_count, 1 if random.random() < 0.3 else 0, random.randint(150, 900), visit_time_us, generate_guid()))
                place_id = cur.lastrowid
                history_added += 1
                for _ in range(v_count):
                    v_us = int((now_sec - random.uniform(1, 30) * 86400) * 1000000)
                    cur.execute("""
                        INSERT INTO moz_historyvisits (from_visit, place_id, visit_date, visit_type, session)
                        VALUES (0, ?, ?, 1, 0)
                    """, (place_id, v_us))

    conn.commit()
    conn.close()

    # 3. Update xulstore.json to ensure the Bookmarks Toolbar is always visible
    xulstore_path = os.path.join(profile_dir, "xulstore.json")
    xul_data = {}
    if os.path.exists(xulstore_path):
        try:
            with open(xulstore_path, "r", encoding="utf-8") as f:
                xul_data = json.load(f)
        except:
            xul_data = {}
    
    browser_entry = xul_data.setdefault("chrome://browser/content/browser.xhtml", {})
    browser_entry["PersonalToolbar"] = {"collapsed": "false"}
    
    try:
        with open(xulstore_path, "w", encoding="utf-8") as f:
            json.dump(xul_data, f, indent=2)
    except:
        pass

    return {
        "success": True,
        "bookmarks_added": bookmarks_added,
        "history_added": history_added,
        "total_bookmarks": len(DEFAULT_TOOLBAR_BOOKMARKS),
        "db_path": db_path,
    }

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python profile_aging.py <profile_dir>")
        sys.exit(1)
    target = sys.argv[1]
    res = seed_profile(target)
    print(json.dumps(res, indent=2))
