@echo off
REM Runs the STATS site so anyone on the same wifi can reach it.
REM Rebuilds the data first, then serves on all interfaces.
cd /d "%~dp0"
python server\build_site.py
python server\serve_site.py --lan
pause
