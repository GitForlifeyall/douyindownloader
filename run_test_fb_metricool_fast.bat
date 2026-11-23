@echo off
setlocal
cd /d "%~dp0"

set "NODE_EXE=%LOCALAPPDATA%\Programs\NodeJS\node22\node.exe"
if not exist "%NODE_EXE%" set "NODE_EXE=node"

echo =========================================================================
echo   FAST FB + METRICOOL TEST RUNNER (NO TRAJECTORY, NO INPUT DELAYS)
echo =========================================================================
echo.

"%NODE_EXE%" --experimental-sqlite tools\test_fb_metricool_fast.mjs %*

endlocal
