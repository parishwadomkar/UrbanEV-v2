@echo off
setlocal
cd /d "%~dp0.."
if "%~3"=="" (
  echo Usage: %~nx0 "runs\MONOLITHIC_RUN" "runs\BENDERS_RUN" "runs\LBBD_RUN"
  exit /b 2
)
python src\compare_runs.py --monolithic-run "%~1" --benders-run "%~2" --lbbd-run "%~3"
if errorlevel 1 exit /b %errorlevel%
endlocal
