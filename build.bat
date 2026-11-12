@echo off
REM Rebuild the stats site's data from the CSVs in data\scores\.
REM Run this after you drop a new game's two CSVs into that folder.
cd /d "%~dp0"
REM Refresh live league ladders (PlayHQ) first. Non-fatal: if it can't reach the
REM feed, the last-saved ladder in data\ladder.json is used and the build goes on.
python server\fetch_ladder.py
python server\build_site.py
pause
