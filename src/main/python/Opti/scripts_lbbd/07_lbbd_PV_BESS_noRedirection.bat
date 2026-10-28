@echo off
setlocal
cd /d "%~dp0.."
set "DATASET=%~1"
if "%DATASET%"=="" set "DATASET=full"
set "VIPV=%~2"
if "%VIPV%"=="" set "VIPV=noVIPV"
python src_lbbd\run_lbbd.py --dataset "%DATASET%" --vipv-scenario "%VIPV%" --scenario no_redirection
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
