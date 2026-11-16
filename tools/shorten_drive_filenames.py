import os
import re
from pathlib import Path

DRIVE_ROOT = Path(r"I:\My Drive\douyin\channel pending movies")
MAX_TOTAL_LEN = 49  # strictly < 50 characters

def shorten_name(filename: str, max_total_len: int = MAX_TOTAL_LEN) -> str:
    if not filename.endswith(".mp4"):
        return filename
    stem = filename[:-4]
    
    # Strip clutter
    s = re.sub(r"\[Viral Movie[^\]]*\]", "", stem, flags=re.IGNORECASE)
    s = re.sub(r"\[\d+\]", "", s)
    s = re.sub(r"\(\s*3d animation[^\)]*\)", "", s, flags=re.IGNORECASE)
    s = re.sub(r"3d animation", "", s, flags=re.IGNORECASE)
    s = re.sub(r"#\S+", "", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    
    max_stem = max_total_len - 4
    if len(s) > max_stem:
        words = s.split()
        cand = ""
        for w in words:
            test = w if not cand else f"{cand} {w}"
            if len(test) <= max_stem:
                cand = test
            else:
                break
        s = cand if cand else s[:max_stem]
    s = s.strip()
    return f"{s}.mp4"

def rename_folder_files(folder_path: Path):
    if not folder_path.exists():
        return
        
    files = [f for f in folder_path.iterdir() if f.is_file() and f.suffix == ".mp4"]
    print(f"\nProcessing {folder_path.name}: {len(files)} MP4 files")
    
    used_names: set[str] = set()
    renamed_count = 0
    
    for f in sorted(files, key=lambda x: str(x)):
        new_name = shorten_name(f.name, MAX_TOTAL_LEN)
        
        # Handle collisions while keeping length <= MAX_TOTAL_LEN
        if new_name.lower() in used_names or (folder_path / new_name).exists() and (folder_path / new_name) != f:
            counter = 2
            base_stem = new_name[:-4]
            while True:
                suffix = f"_{counter}.mp4"
                avail_stem_len = MAX_TOTAL_LEN - len(suffix)
                trimmed_stem = base_stem[:avail_stem_len].strip()
                cand_name = f"{trimmed_stem}{suffix}"
                if cand_name.lower() not in used_names and not (folder_path / cand_name).exists():
                    new_name = cand_name
                    break
                counter += 1
                
        used_names.add(new_name.lower())
        
        if f.name != new_name:
            target = folder_path / new_name
            try:
                f.rename(target)
                renamed_count += 1
                assert len(new_name) < 50, f"Error: {new_name} is {len(new_name)} chars!"
            except Exception as e:
                print(f"Error renaming {f.name} -> {new_name}: {e}")
                
    print(f"Done {folder_path.name}: {renamed_count} files renamed, all <= {MAX_TOTAL_LEN} chars.")

def main():
    folders = ["Curious Cinefile", "batch_1", "batch_2", "batch_3", "batch_4"]
    for folder_name in folders:
        rename_folder_files(DRIVE_ROOT / folder_name)

if __name__ == "__main__":
    main()

