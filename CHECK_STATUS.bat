@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -c "import urllib.request,json; d=json.load(urllib.request.urlopen('http://127.0.0.1:8788/api/status',timeout=5));print(json.dumps(d,indent=2))"
) else (
  python -c "import urllib.request,json; d=json.load(urllib.request.urlopen('http://127.0.0.1:8788/api/status',timeout=5));print(json.dumps(d,indent=2))"
)
pause
