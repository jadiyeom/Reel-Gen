@echo off
REM Stop the review dashboard.
echo Stopping Shorts Studio dashboard...

REM kill whatever is listening on port 5000 (the dashboard server)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5000" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)

REM close the minimized server window if it's still around
taskkill /FI "WINDOWTITLE eq ShortsStudio*" /T /F >nul 2>&1

echo Stopped.
timeout /t 2 /nobreak >nul
