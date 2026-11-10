@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (
 echo Usage: START_WIFI_NODE.bat ^<DEVICE_IP^> [PORT]
 echo For example: START_WIFI_NODE.bat 192.168.0.125 8766
 pause
 exit /b 1
)
set NODE_PORT=8766
if not "%~2"=="" set NODE_PORT=%~2
py -3 launch.py --node-host %1 --node-port %NODE_PORT% --open-browser
if errorlevel 1 pause
