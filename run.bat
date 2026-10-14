@echo off
chcp 65001 >nul
title DouK-Downloader (TikTokDownloader)
cd /d "%~dp0TikTokDownloader"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" main.py
) else (
    python main.py
)
pause
