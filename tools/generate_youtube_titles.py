"""
generate_youtube_titles.py

Generates viral YouTube Shorts titles in the exact format:
"<Action/Hot Iron Ball vs Target> 🔥. #shorts #asmr #experiment"
and extracts 3 thumbnail frames for each video in:
"H:/My Drive/douyin/satisfyying for killing tech"
"""

import os
import sys
import glob
import json
import csv
import cv2
import re
from pathlib import Path
from PIL import Image

sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dubbing_studio.env_loader import configure_runtime_environment
configure_runtime_environment()

from google import genai
from google.genai import types

TARGET_DIR = Path(r"H:\My Drive\douyin\satisfyying for killing tech")
THUMBNAILS_DIR = TARGET_DIR / "thumbnails"
THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)

api_keys_str = os.getenv("GEMINI_API_KEYS", "") or os.getenv("GEMINI_API_KEY", "")
api_keys = [k.strip() for k in api_keys_str.split(",") if k.strip()]
if not api_keys:
    print("Error: No Gemini API keys found in .env")
    sys.exit(1)

def get_client(key_index=0):
    k = api_keys[key_index % len(api_keys)]
    return genai.Client(api_key=k, http_options=types.HttpOptions(timeout=30000))

def extract_3_frames(video_path: Path, output_subfolder: Path):
    output_subfolder.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video_path))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    ratios = [0.25, 0.50, 0.75]
    frame_indices = [int(total_frames * r) for r in ratios]
    thumb_paths = []
    middle_pil_img = None

    for idx, f_no in enumerate(frame_indices, 1):
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_no)
        ret, frame = cap.read()
        out_path = output_subfolder / f"thumb_{idx}.jpg"
        if ret and frame is not None:
            # Safe write with imencode for Windows unicode paths
            success, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
            if success:
                with open(out_path, "wb") as f:
                    f.write(buffer)
                thumb_paths.append(out_path)
            
            # Middle frame for fast vision inference
            if idx == 2 or middle_pil_img is None:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                p_img = Image.fromarray(rgb)
                p_img.thumbnail((400, 400))
                middle_pil_img = p_img

    cap.release()
    return thumb_paths, middle_pil_img

def analyze_and_generate_title(video_name: str, caption_text: str, middle_pil_img, key_idx: int):
    client = get_client(key_idx)
    prompt = (
        "You are an expert YouTube Shorts title creator for ASMR experiment channels.\n"
        "This video frame shows a 1000°C red-hot metal/iron ball experiment.\n"
        f"Original caption: '{caption_text}'\n"
        f"Filename: '{video_name}'\n\n"
        "TASK:\n"
        "1. Identify the exact target object/material the hot iron ball is placed on or melting (e.g. Styrofoam Tower, 5 Layers of Ice, Rubber Bands, Popcorn Kernels, Sunflower Seeds, Ice Block, Floral Foam, Soap, Watermelon, etc.).\n"
        "2. Formulate a catchy, high-CTR YouTube Shorts title strictly in this format:\n"
        "   Hot iron ball vs [Target Object] 🔥. #shorts #asmr #experiment\n"
        "   (or 'Hot iron balls vs [Target Object] 🔥. #shorts #asmr #experiment').\n"
        "3. Output strictly a JSON object: {\"target_object\": \"...\", \"youtube_title\": \"...\"}\n"
    )

    contents = [middle_pil_img, prompt] if middle_pil_img is not None else [prompt]
    models_to_try = ["gemini-3.5-flash-lite", "gemini-3.5-flash"]
    
    for m in models_to_try:
        try:
            resp = client.models.generate_content(
                model=m,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2
                )
            )
            if resp and resp.text:
                data = json.loads(resp.text.strip())
                title = data.get("youtube_title", "")
                if not title:
                    obj = data.get("target_object", "Oddly Satisfying Objects")
                    title = f"Hot iron ball vs {obj} 🔥. #shorts #asmr #experiment"
                
                # Clean base and enforce format
                clean_base = title.split("🔥")[0].split("#")[0].strip()
                if not clean_base.lower().startswith("hot iron ball"):
                    clean_base = f"Hot iron ball vs {clean_base}"
                clean_base = clean_base.rstrip(".")
                final_title = f"{clean_base} 🔥. #shorts #asmr #experiment"
                return final_title
        except Exception as e:
            print(f"Model {m} (key {key_idx}) warning: {e}", flush=True)

    # Fallback based on Chinese caption
    target = "Oddly Satisfying Objects"
    if "五层冰块" in caption_text:
        target = "5 Layers of Ice"
    elif "冰" in caption_text:
        target = "Ice Block"
    elif "爆米花" in caption_text or "玉米油" in caption_text:
        target = "Popcorn Kernels"
    elif "瓜子" in caption_text or "向日葵" in caption_text:
        target = "Sunflower Seeds"
    elif "皮筋" in caption_text:
        target = "Rubber Bands"

    return f"Hot iron ball vs {target} 🔥. #shorts #asmr #experiment"

def main():
    videos = sorted(TARGET_DIR.glob("*.mp4"))
    print(f"Processing {len(videos)} videos in {TARGET_DIR}...", flush=True)

    results = []

    for i, vpath in enumerate(videos, 1):
        sub_thumb_dir = THUMBNAILS_DIR / f"video_{i:02d}"

        # Read original caption
        txt_file = vpath.with_suffix(".txt")
        caption = ""
        if txt_file.exists():
            with open(txt_file, "r", encoding="utf-8") as tf:
                caption = tf.read().strip()

        print(f"[{i:02d}/{len(videos)}] Extracting 3 thumbnail frames for: {vpath.name[:45]}...", flush=True)
        thumb_paths, middle_pil_img = extract_3_frames(vpath, sub_thumb_dir)

        print(f"[{i:02d}/{len(videos)}] Generating viral Shorts title with Gemini...", flush=True)
        title = analyze_and_generate_title(vpath.name, caption, middle_pil_img, key_idx=i-1)
        print(f"   🎯 Title: {title}\n", flush=True)

        # 1. Update the companion .txt caption file
        if txt_file.exists():
            with open(txt_file, "w", encoding="utf-8") as f:
                f.write(title + "\n\nOriginal caption:\n" + caption + "\n")

        # 2. Write dedicated _title.txt file
        title_file = vpath.with_name(vpath.stem + "_title.txt")
        with open(title_file, "w", encoding="utf-8") as f:
            f.write(title + "\n")

        results.append({
            "index": i,
            "filename": vpath.name,
            "youtube_title": title,
            "original_caption": caption,
            "thumbnails": [str(p.relative_to(TARGET_DIR)) for p in thumb_paths]
        })

    # Save master titles.txt
    master_txt = TARGET_DIR / "titles.txt"
    with open(master_txt, "w", encoding="utf-8") as f:
        for r in results:
            f.write(f"{r['index']:02d}. {r['youtube_title']}\n")
    print(f"Saved master titles to: {master_txt}", flush=True)

    # Save master titles.json
    master_json = TARGET_DIR / "titles.json"
    with open(master_json, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"Saved master JSON to: {master_json}", flush=True)

    # Save master titles.csv
    master_csv = TARGET_DIR / "titles.csv"
    with open(master_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Index", "Filename", "YouTube Title", "Original Caption", "Thumbnail 1", "Thumbnail 2", "Thumbnail 3"])
        for r in results:
            t1 = r["thumbnails"][0] if len(r["thumbnails"]) > 0 else ""
            t2 = r["thumbnails"][1] if len(r["thumbnails"]) > 1 else ""
            t3 = r["thumbnails"][2] if len(r["thumbnails"]) > 2 else ""
            writer.writerow([r["index"], r["filename"], r["youtube_title"], r["original_caption"], t1, t2, t3])
    print(f"Saved master CSV to: {master_csv}", flush=True)

    # Update channel_metadata.json
    channel_meta_path = TARGET_DIR / "channel_metadata.json"
    meta_dict = {
        "channel_name": "satisfyying for killing tech",
        "total_videos": len(results),
        "titles_format": "Hot iron ball vs [Target] 🔥. #shorts #asmr #experiment",
        "videos": results
    }
    with open(channel_meta_path, "w", encoding="utf-8") as f:
        json.dump(meta_dict, f, ensure_ascii=False, indent=2)
    print(f"Saved channel_metadata.json to: {channel_meta_path}", flush=True)

if __name__ == "__main__":
    main()
