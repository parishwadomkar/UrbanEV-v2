@echo off
setlocal
cd /d "%~dp0.."
set "DATASET=%~1"
if "%DATASET%"=="" set "DATASET=full"

echo Running LBBD: %DATASET% / PV_noBESS_noRedirection
python src_lbbd\run_lbbd.py --dataset %DATASET% --scenario no_redirection --disable-bess
if errorlevel 1 exit /b %errorlevel%
endlocal
