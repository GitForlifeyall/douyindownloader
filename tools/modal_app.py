#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
modal_app.py
============
Cloud-native Serverless GPU Pipeline orchestrator for Modal.com.
Executes on NVIDIA L4 (24GB VRAM) cloud GPUs with zero local bandwidth usage.
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any

import modal

app = modal.App("douyin-dubbing-studio")

# Define the cloud container image built in Modal's cloud datacenter
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg", "git", "libgl1", "libglib2.0-0", "libgomp1")
    .pip_install(
        "torch==2.3.1",
        "torchvision==0.18.1",
        "torchaudio==2.3.1",
        extra_index_url="https://download.pytorch.org/whl/cu121",
    )
    .pip_install(
        "faster-whisper>=1.0.0",
        "demucs>=4.0.1",
        "google-genai>=0.1.0",
        "sarvamai>=0.1.37",
        "soundfile>=0.12.1",
        "numpy<2.0.0",
        "opencv-python-headless>=4.10.0.84",
        "scikit-image>=0.24.0",
        "einops>=0.8.0",
        "filesplit>=3.0.2",
        "Pillow>=10.4.0",
        "scipy>=1.13.0",
        "tqdm>=4.66.5",
        "paddleocr>=2.7.0",
        "paddlepaddle>=2.6.0",
        "aiofiles>=24.1.0",
        "httpx>=0.27.0",
        "pydantic>=2.7.0",
        "google-api-python-client>=2.150.0",
        "google-auth>=2.35.0",
    )
    .add_local_dir("dubbing_studio", remote_path="/root/app/dubbing_studio")
    .add_local_dir(
        "TikTokDownloader",
        remote_path="/root/app/TikTokDownloader",
        ignore=["**/.venv/**", "**/__pycache__/**", "**/Volume/Download/**"]
    )
    .add_local_dir(
        "video-subtitle-remover-main",
        remote_path="/root/app/video-subtitle-remover-main",
        ignore=["**/__pycache__/**", "**/.venv/**"]
    )
    .add_local_file("remove_subtitles.py", remote_path="/root/app/remove_subtitles.py")
    .add_local_file("pipeline.py", remote_path="/root/app/pipeline.py")
)


@app.function(
    image=image,
    gpu="L4",
    timeout=900,
    secrets=[
        modal.Secret.from_name("dubbing-secrets", required_keys=["GEMINI_API_KEY", "SARVAM_API_KEY"])
    ]
)
def render_video_cloud(
    url: str,
    target_lang: str = "Hindi",
    voice: str = "shubh",
    speed: float = 1.0,
    preserve_bgm: bool = True,
    clean_subtitles: bool = True,
    remove_watermark: bool = False
) -> Dict[str, Any]:
    """Runs the full pipeline on Modal cloud L4 GPU."""
    import sys
    sys.path.insert(0, "/root/app")
    from dubbing_studio.pipeline import DubbingPipeline

    out_dir = Path("/root/app/output")
    out_dir.mkdir(parents=True, exist_ok=True)

    pipeline = DubbingPipeline(output_dir=out_dir)
    res = pipeline.run(
        url_or_file=url,
        target_lang=target_lang,
        voice=voice,
        base_speed=speed,
        preserve_bgm=preserve_bgm,
        clean_subtitles=clean_subtitles,
        remove_watermark=remove_watermark
    )

    # Read binary bytes of final assets to return back to caller
    video_bytes = None
    if res.get("video") and Path(res["video"]).exists():
        video_bytes = Path(res["video"]).read_bytes()

    srt_content = None
    if res.get("srt") and Path(res["srt"]).exists():
        srt_content = Path(res["srt"]).read_text(encoding="utf-8")

    return {
        "status": "success",
        "video_name": Path(res["video"]).name if res.get("video") else "output.mp4",
        "video_bytes": video_bytes,
        "srt_content": srt_content,
        "metadata": res.get("metadata"),
        "metrics": res.get("metrics")
    }


@app.local_entrypoint()
def main(
    url: str,
    lang: str = "Hindi",
    voice: str = "shubh",
    output_dir: Optional[str] = None
):
    """Local CLI trigger to launch cloud render and save directly to local or Google Drive folder."""
    import json

    # Auto-detect target save folder (Mounted Google Drive or local output)
    target_dir = Path(output_dir) if output_dir else None
    if not target_dir:
        # Check standard Google Drive mount points
        for candidate in [Path("G:/My Drive/Dubbed_Videos"), Path("G:/My Drive"), Path("./output")]:
            try:
                candidate.mkdir(parents=True, exist_ok=True)
                target_dir = candidate
                break
            except Exception:
                continue

    if not target_dir:
        target_dir = Path("./output")
        target_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n=======================================================")
    print(f" [Modal Cloud] Dispatching video render to NVIDIA L4 GPU")
    print(f" URL             : {url}")
    print(f" Target Language : {lang}")
    print(f" Local Save Path : {target_dir.resolve()}")
    print(f"=======================================================\n")

    result = render_video_cloud.remote(
        url=url,
        target_lang=lang,
        voice=voice
    )

    # Save output to Google Drive or local folder
    if result.get("video_bytes"):
        out_video = target_dir / result["video_name"]
        out_video.write_bytes(result["video_bytes"])
        print(f"\n[+] Rendered video saved to: {out_video}")

    if result.get("srt_content"):
        out_srt = target_dir / f"{Path(result['video_name']).stem}.srt"
        out_srt.write_text(result["srt_content"], encoding="utf-8")
        print(f"[+] Dubbed SRT saved to: {out_srt}")

    if result.get("metadata"):
        out_meta = target_dir / f"{Path(result['video_name']).stem}_metadata.json"
        out_meta.write_text(json.dumps(result["metadata"], ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[+] SEO Metadata saved to: {out_meta}")

    print("\n[Done] Pipeline finished!")
