@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 launch.py --demo --open-browser
) else (
  python launch.py --demo --open-browser
)
if errorlevel 1 pause
