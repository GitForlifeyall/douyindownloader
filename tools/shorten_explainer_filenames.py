import json
import os
import re
from pathlib import Path

TARGET_DIR = Path(r"I:\My Drive\douyin\explainer 1 final")
BACKUP_MAP_FILE = TARGET_DIR / "filename_backup_map.json"

def clean_explainer(filename: str, max_total_len: int = 49) -> str:
    ext = ".mp4"
    stem = filename[:-4] if filename.endswith(".mp4") else filename
    
    # Strip known clutter tags
    tags_to_remove = [
        r"\( ?3d animation in hindi ?\)", r"\( ?3d animation in english ?\)", r"\( ?3d animation ?\)",
        r"3d animation",
        r"#shorts?", r"#short", r"#fyp"
    ]
    for pattern in tags_to_remove:
        stem = re.sub(pattern, "", stem, flags=re.IGNORECASE)
        
    stem = re.sub(r"\s{2,}", " ", stem).strip()
    
    # Specific smart refinement for the longest one to preserve meaning:
    if "Why Nobody Dared" in stem:
        stem = "Why Nobody Dared To Open Old Letters ✉️"
        
    max_stem_len = max_total_len - len(ext) # 45 chars
    
    if len(stem) > max_stem_len:
        cut = stem[:max_stem_len]
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        stem = cut.strip()
        
    # Clean dangling conjunctions and trailing symbols
    stem = stem.rstrip(" ,.-–_&+:;!?")
    dangling = [" and", " the", " a", " an", " in", " of", " to", " for", " with", " as", " is", " from"]
    for d in dangling:
        if stem.lower().endswith(d):
            stem = stem[:-len(d)].rstrip(" ,.-–_&+:;!?")
            
    if not stem:
        stem = "video"
        
    return stem + ext

def main():
    if not TARGET_DIR.exists():
        print(f"Directory {TARGET_DIR} does not exist!")
        return

    mp4_files = sorted(list(TARGET_DIR.glob("*.mp4")))
    print(f"Scanning {TARGET_DIR}: {len(mp4_files)} MP4 files found.")
    
    backup_map = {}
    if BACKUP_MAP_FILE.exists():
        try:
            with open(BACKUP_MAP_FILE, "r", encoding="utf-8") as f:
                backup_map = json.load(f)
        except Exception:
            backup_map = {}
            
    renamed_count = 0
    for f in mp4_files:
        old_name = f.name
        new_name = clean_explainer(old_name, max_total_len=49)
        
        if old_name != new_name:
            new_path = TARGET_DIR / new_name
            try:
                f.rename(new_path)
                backup_map[old_name] = new_name
                renamed_count += 1
                print(f"[{len(new_name)} chars] {old_name} -> {new_name}")
            except Exception as e:
                print(f"Error renaming {old_name} -> {new_name}: {e}")
                
    # Save backup map
    with open(BACKUP_MAP_FILE, "w", encoding="utf-8") as f:
        json.dump(backup_map, f, ensure_ascii=False, indent=2)
        
    print(f"\nDone! Renamed {renamed_count} files.")
    
    # Verify results
    remaining_mp4s = sorted(list(TARGET_DIR.glob("*.mp4")))
    over_49 = [f.name for f in remaining_mp4s if len(f.name) >= 50]
    print(f"Total files now in {TARGET_DIR.name}: {len(remaining_mp4s)}")
    print(f"Files >= 50 characters: {len(over_49)}")
    if over_49:
        print("Still over 50:", over_49)
    else:
        print("ALL 100% of filenames in explainer 1 final are strictly < 50 characters (max 49 chars)!")

if __name__ == "__main__":
    main()

