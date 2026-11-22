#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import time
import shutil
from pathlib import Path

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

import gradio_client
import soundfile as sf
from dubbing_studio.tts_engine import load_srt_blocks

SRT_PATH = Path("output/2026-09-03 16.39.11-Video-机械之眼-两个大小不同的圆钢管该如何焊接？ ...焊接 #电焊 #劳动人民的智慧 #技巧_hindi.srt")
CACHE_DIR = Path("output/cache_omnivoice")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

blocks = load_srt_blocks(SRT_PATH)
target_blocks = [b for b in blocks if b["index"] <= 7]

SPACES = [
    'D3vShoaib/OmniVoice',
    'archivartaunik/OmniVoice',
    'k2-fsa/OmniVoice'
]

clients = {}
for s in SPACES:
    try:
        print(f"Connecting to {s}...")
        clients[s] = gradio_client.Client(s, httpx_kwargs={'timeout': 120.0})
        print(f"  -> Connected to {s}")
    except Exception as e:
        print(f"  -> Failed to connect to {s}: {e}")

for b in target_blocks:
    idx = b["index"]
    cache_file = CACHE_DIR / f"block_{idx:02d}.wav"
    if cache_file.exists():
        print(f"Block #{idx:02d} already cached. Skipping.")
        continue

    text = b["text"].strip()
    print(f"\nSynthesizing Block #{idx:02d}: {text[:35]}...")
    success = False

    for space_name, client in clients.items():
        try:
            print(f"  Trying endpoint: {space_name}...")
            t0 = time.time()
            res = client.predict(
                text,
                'Hindi',
                32,
                2.0,
                True,
                1.0,
                0,
                True,
                True,
                'Male / 男',
                'Young Adult / 青年',
                'Moderate Pitch / 中音调',
                'Auto',
                'Indian Accent / 印度口音',
                'Auto',
                api_name='/_design_fn'
            )
            temp_wav, status = res
            if not temp_wav or not Path(temp_wav).exists():
                raise RuntimeError(f"Returned invalid path: {res}")
            shutil.copy(temp_wav, str(cache_file))
            data, sr = sf.read(str(cache_file))
            dur = len(data) / sr
            print(f"  [SUCCESS via {space_name}] Block #{idx:02d} ({dur:.2f}s) in {time.time() - t0:.1f}s")
            success = True
            break
        except Exception as e:
            print(f"  [Failed on {space_name}]: {str(e)[:100]}")
            time.sleep(2)

    if not success:
        print(f"ERROR: Could not synthesize Block #{idx:02d} on any space!")
        sys.exit(1)

print("\nAll OmniVoice blocks 1-7 are completely synthesized and cached!")
