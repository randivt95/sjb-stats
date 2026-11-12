@echo off
REM Double-click to run the Shake Jelly Balls STATS site on this machine.
REM It rebuilds the data from data\scores\ first, then serves the site.
REM For phones on the same wifi, use start-wifi.bat instead.
cd /d "%~dp0"
python server\build_site.py
python server\serve_site.py
pause
