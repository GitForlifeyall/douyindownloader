@echo off
setlocal
cd /d "%~dp0"

set "NODE_EXE=%LOCALAPPDATA%\Programs\NodeJS\node22\node.exe"
if not exist "%NODE_EXE%" (
    echo [ERROR] Node.js 22 not found at %NODE_EXE%
    pause
    exit /b 1
)

set "ACCOUNT=AuLumb3394@outlook.com|dlfsznt6597|M.C537_SN1.0.U.MsaArtifacts.-CoqUbMi5MaM6LhmwsGRPSGcmu*24lfZRS9oo3m28eVwsZnbBEny6!jlBk6Ccdt!Mm90J7qJqxjZqiYrpFnyOL20FKALur1REvd8bDENSBFtWbJ7KHJh6f3kzCkpy8K9ilXkd7I9n*2iNkj7MTLnTxxd7trV!XmAbjwtIt!3Mp1oW*3C5lEqv0IWwxp*CvfM7aZz77KgtbengvgitepAnomwfpN1r6FThpeELEP!xi3AaRwnNBkJRe3YygfGEzmZcuJlGIAuEl9Ocb!eQiSSK9uAO2lHJdqeQ4dQgFP7C3wKKhx2s9Bh00Kx5ky9lT6pbo*gtp4lsi6jNr*XZHKgYRH65fv!oOM676t0v7faeMugGdi57yYU49p93otH60ED2d5cxDEpsQHo5Fbk4!VNqVSgzCCKjvmCnFbFl5G7aZWxM2aNRghAktcQHrajmIFphaQ$$|9e5f94bc-e8a4-4e73-b8be-63364c29d753"
set "PROXY=wu_ddfbe3f8:4mS8mKr=+iiA@unblock.oxylabs.io:60000"

echo ==============================================================
echo   Running Instagram Account Creator (Camoufox Node.js)
echo   Account: AuLumb3394@outlook.com
echo   Proxy: %PROXY%
echo ==============================================================

"%NODE_EXE%" --experimental-sqlite tools/instagram_signup_camoufox.mjs --account "%ACCOUNT%" --proxy "%PROXY%" %*

endlocal
