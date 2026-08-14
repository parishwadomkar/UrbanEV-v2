@echo off
setlocal
cd /d "%~dp0.."
set "DATASET=%~1"
if "%DATASET%"=="" set "DATASET=full"

echo Running Monolithic: %DATASET% / PV_noBESS_noRedirection
python src\run_optimization.py --dataset %DATASET% --scenario no_redirection --disable-bess
if errorlevel 1 exit /b %errorlevel%
endlocal
