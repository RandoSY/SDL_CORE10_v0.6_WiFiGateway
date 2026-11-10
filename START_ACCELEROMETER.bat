@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 start_accelerometer.py --open-browser %*
) else (
  python start_accelerometer.py --open-browser %*
)
if errorlevel 1 (
  echo Review the startup error above. USB is optional; check the saved node address and whether port 8799 is already in use.
  pause
)
