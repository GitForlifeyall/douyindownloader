@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title Google Flow Multi-Profile Launcher

set "PROFILE_NAME=%~1"
if "%PROFILE_NAME%"=="" (
    echo ======================================================
    echo   Google Flow Multi-Profile Browser Launcher
    echo ======================================================
    echo.
    set /p PROFILE_NAME="Enter Profile Name (default: account_1): "
    if "!PROFILE_NAME!"=="" set "PROFILE_NAME=account_1"
)

set PYTHON_EXE=python
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
) else if exist "%LOCALAPPDATA%\Programs\Python\Python315\python.exe" (
    set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python315\python.exe"
)

"%PYTHON_EXE%" tools\flow_profile_manager.py launch "!PROFILE_NAME!"
