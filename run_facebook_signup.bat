@echo off
setlocal
cd /d "%~dp0"

set "NODE_EXE=%LOCALAPPDATA%\Programs\NodeJS\node22\node.exe"
if not exist "%NODE_EXE%" (
    echo [ERROR] Node.js 22 not found at %NODE_EXE%
    pause
    exit /b 1
)

set "ACCOUNT=shravyageorgeann433@outlook.in|dnjnludzb7|M.C521_SN1.0.U.MsaArtifacts.-ClQn*FgnkFcArCA4rzy*1u7dy58f3uIWIp2IkNaxcX5LNse6yO2AdHK41lhshg2STuPFqkXFPLkhWYQynJWMp09bzKPmsv6*m9m8aOjppZ9dZb5dt12j5KdaXjfxzrxA*DzWC65kI9AMFnIX4fOVSgLcO4H2sPz2VxPuM!voM3to!46NkKv8DY4uEhd!dq2WOKfGpde6Oe!IG0ZnLFmouCkP4mraa6d0JKKI3lg3S!TEYQCA2m!ZLpEEMmMTQQh8*kFNchHSCioud84uUvqipHZGHDZCDfwPT6UxbzmN0n7OqGtUCRrMhrszbge2AG7msFDoBJ4s7Rc8OQdL3QmXiBlYLYlNuYQGRtfGi4TfRvH8aYSJ!13AnfnEoXPBwKb3Hg$|9e5f94bc-e8a4-4e73-b8be-63364c29d753"
set "PROXY=customer-resi_66c2a9b7-cc-in-city-ahmedabad:oMw6GpW~=ghV@pr.oxylabs.io:7777"

echo ==============================================================
echo   Running Facebook Account Creator (Camoufox Node.js)
echo   Proxy: %PROXY%
echo ==============================================================

"%NODE_EXE%" --experimental-sqlite tools/facebook_signup_camoufox.mjs --account "%ACCOUNT%" --proxy "%PROXY%" %*

endlocal
