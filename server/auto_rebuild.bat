@echo off
REM Headless weekly rebuild for the Windows scheduled task "SJB Ladder Rebuild".
REM Same as build.bat (refresh PlayHQ ladder -> regenerate site\data.json) but with
REM NO pause and with output appended to logs\rebuild.log. serve_site.py reads files
REM fresh per request, so the regenerated data.json is live immediately -- no restart.
setlocal
cd /d "%~dp0\.."
if not exist "logs" mkdir "logs"
set "PY=C:\Users\randi\AppData\Local\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"

echo ================================================================>> "logs\rebuild.log"
echo [%DATE% %TIME%] starting weekly rebuild>> "logs\rebuild.log"
"%PY%" server\fetch_ladder.py >> "logs\rebuild.log" 2>&1
"%PY%" server\build_site.py >> "logs\rebuild.log" 2>&1
echo [%DATE% %TIME%] done (exit %ERRORLEVEL%)>> "logs\rebuild.log"
endlocal
