@echo off
setlocal
title Douyin Google Chrome Session Login & Cookie Sync

echo ========================================================
echo       Launching Google Chrome for Douyin...
echo ========================================================

set "PY_EXE=.venv\Scripts\python.exe"
if not exist "%PY_EXE%" (
    set "PY_EXE=python"
)

"%PY_EXE%" tools\douyin_chrome_login.py %*

pause
