import json
import os
import re
from pathlib import Path

TARGET_DIR = Path(r"I:\My Drive\douyin\final_videos")
BACKUP_MAP_FILE = TARGET_DIR / "filename_backup_map.json"

def clean_stem(filename: str, max_total_len: int = 49) -> str:
    ext = ".mp4"
    stem = filename[:-4] if filename.endswith(".mp4") else filename
    
    # Strip known clutter tags
    tags_to_remove = [
        r"\[viral mirrored\]", r"\[viral movie\]", r"\[viral paragraph\]", r"\[funny paragraph\]", r"\[funny\]",
        r"\( ?3d animation in hindi ?\)", r"\( ?3d animation in english ?\)", r"\( ?3d animation ?\)",
        r"3d animation",
        r"#shorts", r"#short", r"#fyp", r"#birds", r"#nature", r"#zombie", r"#animation",
        r"_hindi_funny_elevenlabs_dubbed", r"_hindi_funny_elevenlabs_roger",
        r"_hindi_sarvam_dubbed_captioned", r"_hindi_sarvam_dubbed", r"_hindi_dubbed"
    ]
    for pattern in tags_to_remove:
        stem = re.sub(pattern, "", stem, flags=re.IGNORECASE)
        
    stem = re.sub(r"\s{2,}", " ", stem).strip()
    
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
    
    # Check existing backup map
    backup_map = {}
    if BACKUP_MAP_FILE.exists():
        try:
            with open(BACKUP_MAP_FILE, "r", encoding="utf-8") as f:
                backup_map = json.load(f)
        except Exception:
            backup_map = {}
            
    # Plan new names
    planned = {}
    used_names = set()
    
    # First preserve already compliant names if they are short enough
    # But if it has tags like (3D Animation In Hindi) or [Viral Mirrored], we should clean it
    for f in mp4_files:
        old_name = f.name
        if len(old_name) <= 49 and not any(k in old_name.lower() for k in ["viral", "animation", "hindi_dubbed", "#short"]):
            planned[old_name] = old_name
            used_names.add(old_name)

    # Now compute cleaned names for the rest
    for f in mp4_files:
        old_name = f.name
        if old_name in planned:
            continue
            
        new_name = clean_stem(old_name, max_total_len=49)
        
        # Resolve collisions
        counter = 2
        candidate = new_name
        while candidate in used_names or (TARGET_DIR / candidate).exists() and candidate != old_name:
            suffix = f"_{counter}.mp4"
            base = new_name[:-4][:49 - len(suffix)].strip()
            candidate = f"{base}{suffix}"
            counter += 1
            
        planned[old_name] = candidate
        used_names.add(candidate)
        
    # Perform renaming
    renamed_count = 0
    for f in mp4_files:
        old_name = f.name
        new_name = planned[old_name]
        if old_name != new_name:
            new_path = TARGET_DIR / new_name
            try:
                f.rename(new_path)
                backup_map[old_name] = new_name
                renamed_count += 1
            except Exception as e:
                print(f"Error renaming {old_name} -> {new_name}: {e}")
                
    # Save backup map
    with open(BACKUP_MAP_FILE, "w", encoding="utf-8") as f:
        json.dump(backup_map, f, ensure_ascii=False, indent=2)
        
    print(f"\nDone! Renamed {renamed_count} files.")
    
    # Verify results
    remaining_mp4s = list(TARGET_DIR.glob("*.mp4"))
    over_49 = [f.name for f in remaining_mp4s if len(f.name) >= 50]
    print(f"Total files now in {TARGET_DIR.name}: {len(remaining_mp4s)}")
    print(f"Files >= 50 characters: {len(over_49)}")
    if over_49:
        print("Still over 50:", over_49[:5])
    else:
        print("ALL 100% of filenames in final_videos are strictly < 50 characters (max 49 chars)!")

if __name__ == "__main__":
    main()

