========== MONOLITHIC TERMINAL LOG ==========
Run transcript : C:\Users\omkarp\IdeaProjects\GotVIPV\src\main\python\Opti\runs\2026-08-12_142251_full_VIPV50_Wp700_no_redirection_withPV_withBESS_slackpenalty\README_RUN.txt
=============================================

Project root  : C:\Users\omkarp\IdeaProjects\GotVIPV\src\main\python\Opti
Dataset       : full
VIPV scenario : VIPV50_Wp700
Run profile   : monolithic.full
Scenario      : no_redirection
Disable PV    : False
Disable BESS  : False
Hard no-slack : False
Sensitivity overrides: none
Run directory : C:\Users\omkarp\IdeaProjects\GotVIPV\src\main\python\Opti\runs\2026-08-12_142251_full_VIPV50_Wp700_no_redirection_withPV_withBESS_slackpenalty
Loading inputs...
Preprocessing inputs...
Hex cells: 587
Active redirection arc-slots: 425,004
Seasonal demand enabled: True
Season mapping: WINTER->Dec/Jan/Feb; SPRING->Mar/Apr/May; SUMMER->Jun/Jul/Aug; AUTUMN->Sep/Oct/Nov
PVGIS detected input unit: W
PVGIS implied annual yield: 951.1 kWh/kWp-year
Retail ToU range: 1.0009 - 3.3403 SEK/kWh
Building type-aware Pyomo model...
Applying no-redirection benchmark: fixing z, z_od, Yarc, n_trip and r_tail to zero.
Solving with Gurobi...
Read LP format model from file C:\Users\omkarp\AppData\Local\Temp\tmp_tuereni.pyomo.lp
Reading time = 14.80 seconds
x1: 10474503 rows, 6095996 columns, 22399186 nonzeros
Set parameter Threads to value 8
Set parameter Presolve to value 2
Set parameter NumericFocus to value 2
Set parameter Heuristics to value 0.1
Set parameter MIPGap to value 0.0001
Set parameter NodefileStart to value 0.5
Set parameter Cuts to value 1
Set parameter TimeLimit to value 96600
Set parameter MIPFocus to value 1
Set parameter Method to value 1
Set parameter NodeMethod to value 1
Set parameter PreSparsify to value 1
Set parameter SoftMemLimit to value 56
Set parameter LogFile to value "C:/Users/omkarp/IdeaProjects/GotVIPV/src/main/python/Opti/runs/2026-08-12_142251_full_VIPV50_Wp700_no_redirection_withPV_withBESS_slackpenalty/logs/gurobi_run.log"
Set parameter NodefileDir to value "C:\Users\omkarp\IdeaProjects\GotVIPV\src\main\python\Opti\runs\2026-08-12_142251_full_VIPV50_Wp700_no_redirection_withPV_withBESS_slackpenalty\nodefiles"
Gurobi Optimizer version 13.0.1 build v13.0.1rc0 (win64 - Windows 11+.0 (26200.2))

CPU model: 12th Gen Intel(R) Core(TM) i7-12700, instruction set [SSE2|AVX|AVX2]
Thread count: 12 physical cores, 20 logical processors, using up to 8 threads

Non-default parameters:
TimeLimit  96600
SoftMemLimit  56
Method  1
Heuristics  0.1
MIPFocus  1
NodefileStart  0.5
NodeMethod  1
Cuts  1
NumericFocus  2
Presolve  2
PreSparsify  1
Threads  8

Optimize a model with 10474503 rows, 6095996 columns and 22399186 nonzeros (Max)
Model fingerprint: 0x9013e32b
Model has 3384055 linear objective coefficients
Variable types: 5754949 continuous, 341047 integer (338112 binary)
Coefficient statistics:
  Matrix range     [4e-05, 5e+02]
  Objective range  [3e+01, 6e+05]
  Bounds range     [1e+00, 1e+03]
  RHS range        [7e-03, 1e+03]

Found heuristic solution: objective -1.60628e+12
Presolve removed 5740348 rows and 1698008 columns (presolve time = 5s)...
Presolve removed 5740348 rows and 1698008 columns (presolve time = 10s)...
Presolve removed 5740348 rows and 2036120 columns (presolve time = 15s)...
Presolve removed 5740348 rows and 2036120 columns (presolve time = 20s)...
Presolve removed 6051060 rows and 2778178 columns (presolve time = 25s)...
Presolve removed 6215676 rows and 2942794 columns (presolve time = 30s)...
Presolve removed 6215676 rows and 2942794 columns (presolve time = 35s)...
Presolve removed 6692991 rows and 3261658 columns (presolve time = 40s)...
Presolve removed 7401062 rows and 3747181 columns (presolve time = 45s)...
Presolve removed 7722191 rows and 3974809 columns (presolve time = 50s)...
Presolve removed 7996747 rows and 4173789 columns (presolve time = 55s)...
Presolve removed 8262547 rows and 4366941 columns (presolve time = 60s)...
Presolve removed 8470727 rows and 4521201 columns (presolve time = 65s)...
Presolve removed 8673350 rows and 4672921 columns (presolve time = 70s)...
Presolve removed 8846896 rows and 4805514 columns (presolve time = 75s)...
Presolve removed 9036596 rows and 4951377 columns (presolve time = 80s)...
Presolve removed 9159018 rows and 5045380 columns (presolve time = 85s)...
Presolve removed 9313052 rows and 5164400 columns (presolve time = 90s)...
Presolve removed 9405854 rows and 5236954 columns (presolve time = 96s)...
Presolve removed 9475523 rows and 5291877 columns (presolve time = 100s)...
Presolve removed 9568736 rows and 5364868 columns (presolve time = 105s)...
Presolve removed 9638840 rows and 5419678 columns (presolve time = 110s)...
Presolve removed 9709019 rows and 5474713 columns (presolve time = 115s)...
Presolve removed 9771406 rows and 5524218 columns (presolve time = 120s)...
Presolve removed 9857424 rows and 5592214 columns (presolve time = 125s)...
Presolve removed 9943673 rows and 5661136 columns (presolve time = 130s)...
Presolve removed 10030141 rows and 5730482 columns (presolve time = 136s)...
Presolve removed 10108925 rows and 5794054 columns (presolve time = 141s)...
Presolve removed 10187886 rows and 5858157 columns (presolve time = 145s)...
Presolve removed 10251245 rows and 5910010 columns (presolve time = 150s)...
Presolve removed 10338565 rows and 5981912 columns (presolve time = 156s)...
Presolve removed 10434337 rows and 6061890 columns (presolve time = 161s)...
Presolve removed 10466477 rows and 6089196 columns
Presolve time: 162.31s
Presolved: 8026 rows, 6800 columns, 25290 nonzeros
Found heuristic solution: objective -2.96473e+10
Variable types: 6219 continuous, 581 integer (577 binary)
Root relaxation presolve removed 1482 rows and 2166 columns
Root relaxation presolved: 6544 rows, 4634 columns, 19106 nonzeros


Root simplex log...

Iteration    Objective       Primal Inf.    Dual Inf.      Time
       0    3.8025723e+08   1.452342e+05   0.000000e+00    164s
    1541    3.7333930e+08   0.000000e+00   0.000000e+00    164s
    1541    3.7333930e+08   0.000000e+00   0.000000e+00    164s

Root relaxation: objective 3.733393e+08, 1541 iterations, 0.05 seconds (0.05 work units)

    Nodes    |    Current Node    |     Objective Bounds      |     Work
 Expl Unexpl |  Obj  Depth IntInf | Incumbent    BestBd   Gap | It/Node Time

     0     0 3.7334e+08    0    3 -2.965e+10 3.7334e+08   101%     -  163s
H    0     0                    -4.04322e+09 3.7334e+08   109%     -  163s
H    0     0                    -3.77482e+09 3.7334e+08   110%     -  163s
H    0     0                    3.468501e+08 3.7334e+08  7.64%     -  164s
     0     0 3.7334e+08    0    3 3.4685e+08 3.7334e+08  7.64%     -  164s
H    0     0                    3.732492e+08 3.7334e+08  0.02%     -  164s
     0     0 3.7325e+08    0    3 3.7325e+08 3.7325e+08  0.00%     -  164s

Cutting planes:
  Implied bound: 2
  MIR: 4
  Flow cover: 8

Explored 1 nodes (1634 simplex iterations) in 165.65 seconds (485.02 work units)
Thread count was 8 (of 20 available processors)

Solution count 6: 3.73249e+08 3.4685e+08 -3.77482e+09 ... -1.60628e+12

Optimal solution found (tolerance 1.00e-04)
Best objective 3.732491690576e+08, best bound 3.732530276293e+08, gap 0.0010%

- Status: ok
  Return code: 0
  Message: Model was solved to optimality (subject to tolerances), and an optimal solution is available.
  Termination condition: optimal
  Termination message: Model was solved to optimality (subject to tolerances), and an optimal solution is available.
  Wall time: 165.82500004768372
  Error rc: 0


================  OPTIMAL ANNUAL PROFIT  ================
Total profit : 373,249,169 SEK / yr

==================  BREAKDOWN  =================
Revenue (all chargers)             :   534,697,014
Opex - grid purchases              :   106,080,617
Opex - redirection distance        :             0
Opex - redirection price comp.     :             0
Opex - unmet-demand penalty        :        20,201
Capex - chargers                   :    22,988,136
Capex - PV & batteries             :    32,358,890
----------------------------------------------------------
Slow   chargers:        617 | energy:   1,785,396.3 | cap ratio: 0.030
Medium chargers:      2,418 | energy:  55,769,078.3 | cap ratio: 0.120
Fast   chargers:        163 | energy:  29,271,209.9 | cap ratio: 0.410
==========================================================

Writing CSV/XLSX outputs...
Combined XLSX written to: C:\Users\omkarp\IdeaProjects\GotVIPV\src\main\python\Opti\runs\2026-08-12_142251_full_VIPV50_Wp700_no_redirection_withPV_withBESS_slackpenalty\results\combined_results.xlsx
Output files written to: C:\Users\omkarp\IdeaProjects\GotVIPV\src\main\python\Opti\runs\2026-08-12_142251_full_VIPV50_Wp700_no_redirection_withPV_withBESS_slackpenalty\results
Generating result figures...
Figure generated: economic_breakdown
Figure generated: charger_deployment
Figure generated: monthly_energy
Figure generated: input_pv_tou_profiles
Figure generated: seasonal_demand_profiles
Figure generated: seasonal_supply_profiles
Figure generated: dispatch_January
Figure generated: dispatch_April
Figure generated: dispatch_July
Figure generated: dispatch_October
Figure generated: bess_soc
Figure generated: bess_operation_January
Figure generated: bess_operation_July
Figure generated: demand_supply_balance
Figure skipped: redirection_heatmap (No positive redirection flows)
Figure skipped: redirection_type_matrix (No type-pair redirection reconstruction)
Figure skipped: decomposition_convergence (No decomposition iteration history)
Figure skipped: decomposition_cut_generation (No decomposition iteration history)
Figure skipped: lbbd_cut_families (No LBBD iteration history)
Figure skipped: lbbd_candidate_bounds (No LBBD iteration history)
Figure skipped: lbbd_infrastructure_evolution (No LBBD iteration history)
Figure skipped: lbbd_iteration_timing (No LBBD iteration history)
Figure skipped: lbbd_gap_diagnostics (No LBBD iteration history)
Figure skipped: lbbd_adaptive_master_control (No LBBD iteration history)
Figure skipped: lbbd_candidate_reuse (No LBBD iteration history)
Figure generated: slack
Figure generated: spatial_maps
Figures written to: C:\Users\omkarp\IdeaProjects\GotVIPV\src\main\python\Opti\runs\2026-08-12_142251_full_VIPV50_Wp700_no_redirection_withPV_withBESS_slackpenalty\figures
Run finished successfully. Run directory: C:\Users\omkarp\IdeaProjects\GotVIPV\src\main\python\Opti\runs\2026-08-12_142251_full_VIPV50_Wp700_no_redirection_withPV_withBESS_slackpenalty

Terminal transcript written to: C:\Users\omkarp\IdeaProjects\GotVIPV\src\main\python\Opti\runs\2026-08-12_142251_full_VIPV50_Wp700_no_redirection_withPV_withBESS_slackpenalty\README_RUN.txt
