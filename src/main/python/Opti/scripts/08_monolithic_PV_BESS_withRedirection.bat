@echo off
setlocal
cd /d "%~dp0.."
set "DATASET=%~1"
if "%DATASET%"=="" set "DATASET=full"
set "VIPV=%~2"
if "%VIPV%"=="" set "VIPV=noVIPV"
python src\run_optimization.py --dataset "%DATASET%" --vipv-scenario "%VIPV%" --scenario with_redirection
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
