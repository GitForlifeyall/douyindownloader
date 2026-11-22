@echo off
setlocal
title Account Studio Dashboard
cd /d "%~dp0"

set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
    echo [ERROR] Virtual environment python.exe not found at %PYTHON_EXE%
    pause
    exit /b 1
)

echo ==============================================================
echo   ACCOUNT STUDIO • NATIVE DESKTOP DASHBOARD
echo   Automated Account Creator (Instagram, Facebook, Metricool)
echo   Local Server: http://127.0.0.1:8950
echo ==============================================================

"%PYTHON_EXE%" tools\dashboard_server.py

endlocal
