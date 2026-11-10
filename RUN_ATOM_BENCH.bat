@echo off
setlocal
cd /d "%~dp0"
echo ATOM Matrix 1.0 hardware bench check on COM30
echo Windows account:
whoami
echo.
echo Reads the node IP over USB, then tests its TCP stream and reconnect.
echo Results are saved under artifacts\atom-bench-*. No firmware is flashed.
echo.
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -B scripts\check_atom_node.py --port COM30 --serial-seconds 2 --seconds 12
) else (
  python -B scripts\check_atom_node.py --port COM30 --serial-seconds 2 --seconds 12
)
set BENCH_RESULT=%errorlevel%
echo.
echo Bench exit code: %BENCH_RESULT%
echo 0 = passed; 1 = failed or access blocked; 2 = node Wi-Fi offline.
pause
exit /b %BENCH_RESULT%
