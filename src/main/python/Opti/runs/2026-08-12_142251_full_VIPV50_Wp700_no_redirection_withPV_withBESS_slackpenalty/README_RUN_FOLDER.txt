Monolithic optimization run folder
==================================

This folder is produced by src/run_optimization.py. It contains the outputs from the full monolithic Pyomo/Gurobi formulation.

Core files:
- README_RUN.txt: complete terminal transcript from this run.
- results/model_summary.csv: detailed economic, energy, and infrastructure metrics.
- results/infrastructure_by_hex.csv: charger/PV/BESS deployment by cell.
- results/redirections.csv and redirections_by_type.csv: optimized redirected flows.
- results/hourly_energy.csv: slot-level energy dispatch.
- results/pvgis_diagnostics.csv: detected PV input units and implied monthly/annual PV yield.
- results/input_monthly_profiles.csv: exact month-slot stationary PV factors and retail ToU prices.
- results/seasonal_demand_diagnostics.csv: seasonal MATSim demand totals and annualization checks.
- figures/: automatically generated diagnostic and manuscript-oriented figures.
- logs/gurobi_run.log: Gurobi solver log.
- logs/pyomo_solve.log: Pyomo solve log.

VIPV input scenario: VIPV50_Wp700
Optimization scenario: no_redirection
Dataset: full
Technology: PV enabled, BESS enabled
Sensitivity overrides: None
