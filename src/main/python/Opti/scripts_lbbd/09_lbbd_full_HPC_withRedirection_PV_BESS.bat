@echo off
REM Calibrated full-data LBBD run for a 256 GB Windows workstation/HPC node.
REM Most algorithmic tolerances are read from config\run_profiles.json.
REM Optional first argument: number of threads. Default is 10.
set THREADS=%1
if "%THREADS%"=="" set THREADS=10

set NODEDIR=%CD%\runs\gurobi_nodefiles
if not exist "%NODEDIR%" mkdir "%NODEDIR%"

python src_lbbd\run_lbbd.py ^
  --dataset full ^
  --scenario with_redirection ^
  --threads %THREADS% ^
  --soft-mem-limit-gb 180 ^
  --nodefile-start 0.5 ^
  --nodefile-dir "%NODEDIR%"
