@echo off
setlocal
title Douyin Session Login & Cookie Sync

echo ========================================================
echo       Launching Douyin Persistent Browser...
echo ========================================================

set "NODE_EXE=%LOCALAPPDATA%\Programs\NodeJS\node22\node.exe"
if not exist "%NODE_EXE%" (
    set "NODE_EXE=node"
)

"%NODE_EXE%" --experimental-sqlite tools\douyin_login_cookie.mjs

pause
