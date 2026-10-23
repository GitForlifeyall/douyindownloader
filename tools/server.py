#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
server.py
=========
FastAPI headless server and CLI entrypoint for Google Cloud Run (GPU).
Supports:
  - Cloud Run HTTP requests: POST /dub (processes video, dubs, uploads to Google Drive)
  - Health checks: GET /health
  - Direct CLI invocation: python server.py --url "<douyin_url>"
"""

import os
import sys
import argparse
from pathlib import Path
from typing import Optional, Dict, Any

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field

# Ensure packages are discoverable
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dubbing_studio.pipeline import DubbingPipeline
from dubbing_studio.gdrive_uploader import GoogleDriveUploader, GDRIVE_AVAILABLE

app = FastAPI(
    title="Douyin / TikTok Dubbing Studio Cloud API",
    description="Headless GPU video dubbing, subtitle removal, and Google Drive delivery service.",
    version="1.0.0"
)


class DubRequest(BaseModel):
    url: str = Field(..., description="Douyin or TikTok video URL")
    target_lang: str = Field("Hindi", description="Target dubbing language (e.g. Hindi, English, Spanish)")
    voice: Optional[str] = Field("shubh", description="Voice ID (Sarvam: shubh, bulbul:v3; Gemini: Orus)")
    speed: float = Field(1.0, description="Base voice playback speed multiplier")
    preserve_bgm: bool = Field(True, description="Separate and preserve original BGM/SFX using Demucs")
    clean_subtitles: bool = Field(True, description="Inpaint and erase Chinese subtitles using STTN GPU")
    remove_watermark: bool = Field(False, description="Inpaint corner creator watermarks")
    drive_folder_id: Optional[str] = Field(None, description="Google Drive folder ID to auto-upload the results")


@app.get("/")
@app.get("/health")
def health_check():
    """Health check endpoint for Google Cloud Run."""
    has_gpu = False
    gpu_name = "None"
    try:
        import torch
        has_gpu = torch.cuda.is_available()
        if has_gpu:
            gpu_name = torch.cuda.get_device_name(0)
    except Exception:
        pass

    return {
        "status": "healthy",
        "gpu_available": has_gpu,
        "gpu_device": gpu_name,
        "gdrive_integration": GDRIVE_AVAILABLE,
        "default_drive_folder": os.getenv("GDRIVE_FOLDER_ID", "Not Set")
    }


def execute_pipeline(req: DubRequest) -> Dict[str, Any]:
    """Execute dubbing pipeline and optionally upload outputs to Google Drive."""
    output_dir = Path(os.getenv("OUTPUT_DIR", "/app/output"))
    output_dir.mkdir(parents=True, exist_ok=True)

    pipeline = DubbingPipeline(output_dir=output_dir)
    result = pipeline.run(
        url_or_file=req.url,
        target_lang=req.target_lang,
        voice=req.voice,
        base_speed=req.speed,
        preserve_bgm=req.preserve_bgm,
        clean_subtitles=req.clean_subtitles,
        remove_watermark=req.remove_watermark
    )

    # Optional Google Drive Upload
    target_drive_folder = req.drive_folder_id or os.getenv("GDRIVE_FOLDER_ID")
    drive_uploads = {}

    if target_drive_folder and GDRIVE_AVAILABLE:
        try:
            uploader = GoogleDriveUploader()
            # Upload final video
            if result.get("video") and Path(result["video"]).exists():
                v_res = uploader.upload_file(result["video"], folder_id=target_drive_folder)
                drive_uploads["video"] = v_res.get("webViewLink")

            # Upload dubbed srt
            if result.get("srt") and Path(result["srt"]).exists():
                s_res = uploader.upload_file(result["srt"], folder_id=target_drive_folder)
                drive_uploads["srt"] = s_res.get("webViewLink")
                
            result["drive_links"] = drive_uploads
        except Exception as e:
            print(f"[GDrive Error] Failed to upload to Google Drive: {e}")
            result["drive_error"] = str(e)

    return result


@app.post("/dub")
def dub_video(request: DubRequest):
    """Trigger end-to-end dubbing pipeline on Cloud Run GPU."""
    try:
        res = execute_pipeline(request)
        return res
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Douyin Dubbing Studio Cloud Server / CLI")
    parser.add_argument("--url", type=str, help="Douyin/TikTok URL to dub via CLI")
    parser.add_argument("--lang", type=str, default="Hindi", help="Target language")
    parser.add_argument("--voice", type=str, default="shubh", help="Voice identifier")
    parser.add_argument("--drive-folder", type=str, default=None, help="Google Drive Folder ID")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="HTTP server bind host")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8080")), help="HTTP server port")

    args = parser.parse_args()

    if args.url:
        # CLI Mode
        req = DubRequest(
            url=args.url,
            target_lang=args.lang,
            voice=args.voice,
            drive_folder_id=args.drive_folder
        )
        out = execute_pipeline(req)
        print("\nPipeline finished successfully!")
        print(out)
    else:
        # Server Mode for Cloud Run
        import uvicorn
        print(f"[*] Starting Cloud Run server on {args.host}:{args.port}...")
        uvicorn.run("server:app", host=args.host, port=args.port, reload=False)
