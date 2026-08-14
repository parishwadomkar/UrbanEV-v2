@echo off
setlocal
cd /d "%~dp0.."
set "DATASET=%~1"
if "%DATASET%"=="" set "DATASET=full"

echo Running Monolithic: %DATASET% / noPV_BESS_withRedirection
python src\run_optimization.py --dataset %DATASET% --scenario with_redirection --disable-pv
if errorlevel 1 exit /b %errorlevel%
endlocal
