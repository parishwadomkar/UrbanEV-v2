# Generated optimization figures

Figures are generated automatically after successful monolithic and LBBD result export.
PNG files use the run-level resolution setting (default: 300 dpi). The figure manifest records
which figure groups were generated, skipped, or failed.

## How to read the common result figures

- `01_economic_breakdown.png` separates annual revenue, grid electricity, redirection incentives,
  slack penalty, charger capex, and PV/BESS capex. Positive bars increase profit; negative bars reduce it.
- `02_charger_deployment_and_utilization.png` compares installed slow, medium, and fast chargers
  with the annual utilization of their available capacity.
- `03_monthly_energy_supply_mix.png` shows whether charger energy is supplied directly from the
  grid, directly from PV, or through battery discharge.
- `03a_input_pv_tou_profiles.png` verifies the month-specific stationary-PV capacity factors and
  retail ToU prices actually supplied to the optimization.
- `03b_seasonal_charging_demand_profiles.png` shows the four MATSim seasonal demand profiles used
  for the annual optimization, stacked as home and work+public charging demand.
- `03c_seasonal_energy_supply_profiles.png` shows the optimized seasonal supply mix from grid,
  direct stationary PV, and BESS discharge.
- `04_dispatch_<month>.png` gives the representative-day dispatch profile for selected months.
- `05_bess_soc_by_month.png` and `06_bess_operation_<month>.png` describe the linked BESS state of
  charge and charge/discharge operation. They are generated only when BESS output files exist.
- `07_redirection_month_time_heatmap.png` shows when redirected charging is used most strongly.
- `08_redirection_type_matrix.png` shows the origin charger-type to destination charger-type energy
  assignment in the exact exported solution.
- `10_slack_by_month.png` is generated only when positive unmet demand exists. A skipped slack figure
  normally means the optimized solution had zero positive slack.
- `11_map_public_charging_capacity.png` through `15_map_redirection_corridors_<month>.png` are spatial
  maps. If `contextily` or internet access is unavailable, maps are still generated from the vector geometry.
- `16_demand_supply_balance_annual_average.png` compares home and public charging supply accounting.

## How to read decomposition figures

- `09_decomposition_convergence.png` is the main certificate plot. The upper-bound line is the valid
  global master bound. The lower-bound line is the best exact feasible incumbent. The dashed gap line
  is `(UB - LB) / max(1, |UB|)` in percent.
- `17_decomposition_cut_generation.png` reports accepted master cuts and, for LBBD runs, the annual-LP
  and core-point violation signals before filtering. If it shows only exact-configuration cuts, this means
  the embedded master relaxation was already tight enough that LP/core/logic cuts were not violated at
  the evaluated candidates.
- `18_lbbd_cut_families.png` summarizes the accepted LBBD cuts by family and by iteration. It is a
  diagnostic of which inference mechanism actually changed the master, not a measure of solution quality.
- `19_lbbd_candidate_bounds.png` compares the master candidate value, annual LP relaxation, fixed-layout
  MIP upper bound, and exact feasible objective. The lower panel reports differences from the exact
  incumbent in kSEK/year, which is usually more informative than overlapping objective lines.
- `20_lbbd_infrastructure_evolution.png` shows how the candidate charger, PV, and BESS decisions change
  across iterations.
- `21_lbbd_iteration_timing.png` separates master-solve time from oracle/cut/export time and shows the
  cumulative runtime.
- `22_lbbd_gap_diagnostics.png` compares the global LBBD gap, master MIP gap, and exact fixed-layout MIP
  gap on a logarithmic scale.
- `23_lbbd_adaptive_master_control.png` verifies that the requested trial-master gap tightens as the
  certified LBBD gap decreases. This is important because a loose trial-master MIP gap can stall outer-loop
  convergence.
- `24_lbbd_candidate_reuse.png` shows whether an iteration evaluated a new infrastructure candidate or
  reused an exact result from the internal cache, together with repeated-candidate counts and new cuts.

## Regenerating figures

```powershell
python src\visualize_results.py --run-dir "runs\<RUN_FOLDER>" --dataset small --dpi 300 --redirection-map-month June
```
