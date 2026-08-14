@echo off
setlocal
if "%~2"=="" (
  echo Usage: %~nx0 "runs\MONOLITHIC_RUN" "runs\LBBD_RUN"
  exit /b 2
)
python src\compare_runs.py --monolithic-run "%~1" --lbbd-run "%~2"
if errorlevel 1 exit /b %errorlevel%
endlocal
