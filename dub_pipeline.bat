@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title Douyin / TikTok Automated Dubbing Studio
cd /d "%~dp0"

set PYTHON_EXE=python
python -c "import cv2, torch" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    if exist "TikTokDownloader\.venv\Scripts\python.exe" (
        set PYTHON_EXE=TikTokDownloader\.venv\Scripts\python.exe
    )
)

if "%~1"=="" (
    echo ======================================================
    echo   Douyin / TikTok Automated Dubbing Studio
    echo   Default Engine: Sarvam AI (Bulbul v3 - Shubh)
    echo ======================================================
    echo.
    set /p VIDEO_URL="Paste Douyin/TikTok URL, MP4 Path, or Folder: "
    if not defined VIDEO_URL (
        echo [Error] No URL or Folder entered. Exiting.
        pause
        exit /b 1
    )
    rem Remove enclosing quotes if user dragged and dropped
    set "VIDEO_URL=!VIDEO_URL:"=!"
    "%PYTHON_EXE%" pipeline.py --url "!VIDEO_URL!"
) else (
    set "ARG1=%~1"
    if "!ARG1:~0,2!"=="--" (
        "%PYTHON_EXE%" pipeline.py %*
    ) else (
        "%PYTHON_EXE%" pipeline.py --url "%~1"
    )
)

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [Pipeline Error] Process exited with code %ERRORLEVEL%
)
