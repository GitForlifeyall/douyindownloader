@echo off
set SCRIPT_DIR=%~dp0
set EXT_DIR=%SCRIPT_DIR%tools\flowkit\extension
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --user-data-dir="%USERPROFILE%\.flowkit_chrome_profile" --load-extension="%EXT_DIR%" "https://flow.google.com/"
exit


