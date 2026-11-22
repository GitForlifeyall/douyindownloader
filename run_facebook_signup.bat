@echo off
setlocal
cd /d "%~dp0"

rem ===========================================================================
rem  Facebook signup through the shared identity runner.
rem
rem  Usage:
rem    run_facebook_signup.bat --identity <identity_id_or_email> [flags]
rem
rem  Examples:
rem    run_facebook_signup.bat --identity hanijyra562
rem    run_facebook_signup.bat --identity hanijyra562 --headless --skip-2fa
rem
rem  What changed:
rem    * No credentials in this file any more. Mailbox comes from the identity store.
rem    * No proxy in this file any more. The identity's proxy is verified first,
rem      pinned to -cc-us, and given a stable sticky session.
rem    * The old wu_...@unblock.oxylabs.io Web Unblocker is gone: it is a
rem      scraping product, it returns 401, and Meta rejects its IPs.
rem ===========================================================================

set "PY_EXE=%~dp0.venv\Scripts\python.exe"
if not exist "%PY_EXE%" set "PY_EXE=python"

if "%~1"=="" (
    echo Usage: run_facebook_signup.bat --identity ^<identity_id_or_email^> [flags]
    echo.
    echo The proxy and mailbox are read from the identity store, not from this file.
    echo Create an identity in the dashboard first, then run:
    echo     run_facebook_signup.bat --identity your_identity_id
    exit /b 1
)

echo ==============================================================
echo   Facebook signup via identity runner
echo ==============================================================
"%PY_EXE%" tools\run_identity.py --platform facebook %*

endlocal
