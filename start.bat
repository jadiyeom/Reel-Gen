@echo off
REM Start the review dashboard (local website) and open it in the browser.
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

echo Starting Shorts Studio dashboard using %PY%...
start "ShortsStudio" /min cmd /c "%PY% run.py serve"

REM give the server a moment to boot, then open the browser
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:5000"

echo.
echo  Shorts Studio running at  http://127.0.0.1:5000
echo  Run  stop.bat  to shut it down.
echo.
timeout /t 3 /nobreak >nul
