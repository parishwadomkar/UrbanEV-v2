# Monolithic scenario scripts

Scripts 01–08 cover every cold-start combination of redirection, PV, and BESS.
Calibrated solver and algorithm settings are loaded automatically from:

- `config/solver_gurobi.json`
- `config/run_profiles.json`

Run a script without an argument for the `full` dataset, or pass `small` as the first argument.

Example:

```bat
08_monolithic_PV_BESS_withRedirection.bat small
```

No previous run folder or external infrastructure solution is read.

Figures are generated automatically after a successful result export. Use `--skip-figures` only when post-processing should be disabled.


## Monolithic–LBBD comparison

Use `09_compare_monolithic_lbbd.bat` to compare one completed monolithic run with one completed LBBD run:

```bat
09_compare_monolithic_lbbd.bat "runs\MONOLITHIC_RUN" "runs\LBBD_RUN"
```

The comparison utility accepts only monolithic and LBBD run folders.

## Same-method multi-scenario comparison

Use `10_compare_scenario_runs.bat` to compare two or more completed runs produced by the same solution method. The first run is the baseline unless `src/compare_scenarios.py` is called directly with another `--baseline-index`.

Monolithic example:

```bat
10_compare_scenario_runs.bat monolithic "runs\RUN_SC01_NOREDIR" "runs\RUN_SC01_REDIR" "runs\RUN_SC02_NOREDIR" "runs\RUN_SC02_REDIR"
```

LBBD example:

```bat
10_compare_scenario_runs.bat lbbd "runs\RUN_1" "runs\RUN_2" "runs\RUN_3"
```

For explicit labels, baseline selection, or output naming, use the Python utility directly:

```powershell
python src\compare_scenarios.py `
  --method monolithic `
  --run "runs\RUN_1" `
  --run "runs\RUN_2" `
  --run "runs\RUN_3" `
  --label "Sc01: Chargers only - no redir." `
  --label "Sc02: Chargers + PV - no redir." `
  --label "Sc03: Chargers + PV + BESS - no redir." `
  --baseline-index 1
```

The workbook contains a publication-style scenario summary, changes relative to the selected baseline, matched no-/with-redirection effects, scenario rankings, run/solver metadata, raw metrics, and consistency checks. Columns follow the order supplied on the command line.
