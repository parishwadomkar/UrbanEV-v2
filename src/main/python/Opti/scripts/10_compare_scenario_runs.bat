@echo off
setlocal EnableExtensions

if "%~3"=="" (
  echo Usage: %~nx0 monolithic^|lbbd "runs\RUN_1" "runs\RUN_2" ["runs\RUN_3" ...]
  echo.
  echo The first run is used as the comparison baseline by default.
  exit /b 1
)

set "METHOD=%~1"
shift
set "RUN_ARGS="

:collect
if "%~1"=="" goto execute
set RUN_ARGS=%RUN_ARGS% --run "%~1"
shift
goto collect

:execute
python src\compare_scenarios.py --method %METHOD% %RUN_ARGS%
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" exit /b %RC%

endlocal
