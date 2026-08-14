========== MONOLITHIC TERMINAL LOG ==========
Run transcript : C:\Users\omkarp\IdeaProjects\GotVIPV\src\main\python\Opti\runs\2026-08-12_132848_full_noVIPV_no_redirection_withPV_withBESS_slackpenalty\README_RUN.txt
=============================================

Project root  : C:\Users\omkarp\IdeaProjects\GotVIPV\src\main\python\Opti
Dataset       : full
VIPV scenario : noVIPV
Run profile   : monolithic.full
Scenario      : no_redirection
Disable PV    : False
Disable BESS  : False
Hard no-slack : False
Sensitivity overrides: none
Run directory : C:\Users\omkarp\IdeaProjects\GotVIPV\src\main\python\Opti\runs\2026-08-12_132848_full_noVIPV_no_redirection_withPV_withBESS_slackpenalty
Loading inputs...
Preprocessing inputs...
Hex cells: 587
Active redirection arc-slots: 435,756
Seasonal demand enabled: True
Season mapping: WINTER->Dec/Jan/Feb; SPRING->Mar/Apr/May; SUMMER->Jun/Jul/Aug; AUTUMN->Sep/Oct/Nov
PVGIS detected input unit: W
PVGIS implied annual yield: 951.1 kWh/kWp-year
Retail ToU range: 1.0009 - 3.3403 SEK/kWh
Building type-aware Pyomo model...
Applying no-redirection benchmark: fixing z, z_od, Yarc, n_trip and r_tail to zero.
Solving with Gurobi...
Read LP format model from file C:\Users\omkarp\AppData\Local\Temp\tmpmyxxpvtu.pyomo.lp
Reading time = 14.83 seconds
x1: 10570215 rows, 6095996 columns, 22459522 nonzeros
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
Set parameter LogFile to value "C:/Users/omkarp/IdeaProjects/GotVIPV/src/main/python/Opti/runs/2026-08-12_132848_full_noVIPV_no_redirection_withPV_withBESS_slackpenalty/logs/gurobi_run.log"
Set parameter NodefileDir to value "C:\Users\omkarp\IdeaProjects\GotVIPV\src\main\python\Opti\runs\2026-08-12_132848_full_noVIPV_no_redirection_withPV_withBESS_slackpenalty\nodefiles"
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

Optimize a model with 10570215 rows, 6095996 columns and 22459522 nonzeros (Max)
Model fingerprint: 0x02338224
Model has 3384055 linear objective coefficients
Variable types: 5754949 continuous, 341047 integer (338112 binary)
Coefficient statistics:
  Matrix range     [4e-05, 5e+02]
  Objective range  [3e+01, 6e+05]
  Bounds range     [1e+00, 1e+03]
  RHS range        [2e-03, 1e+03]

Found heuristic solution: objective -1.75965e+12
Presolve removed 5836060 rows and 1698008 columns (presolve time = 5s)...
Presolve removed 5836060 rows and 1698008 columns (presolve time = 10s)...
Presolve removed 5836060 rows and 2036120 columns (presolve time = 15s)...
Presolve removed 5836060 rows and 2036120 columns (presolve time = 20s)...
Presolve removed 6112802 rows and 2745386 columns (presolve time = 25s)...
Presolve removed 6277715 rows and 2910299 columns (presolve time = 30s)...
Presolve removed 6277715 rows and 2910299 columns (presolve time = 35s)...
Presolve removed 6935956 rows and 3351447 columns (presolve time = 40s)...
Presolve removed 7576949 rows and 3794956 columns (presolve time = 45s)...
Presolve removed 7899566 rows and 4025560 columns (presolve time = 50s)...
Presolve removed 8169861 rows and 4221818 columns (presolve time = 55s)...
Presolve removed 8458842 rows and 4434008 columns (presolve time = 60s)...
Presolve removed 8683032 rows and 4601693 columns (presolve time = 65s)...
Presolve removed 8871553 rows and 4745338 columns (presolve time = 70s)...
Presolve removed 9053641 rows and 4885547 columns (presolve time = 75s)...
Presolve removed 9237697 rows and 5027066 columns (presolve time = 80s)...
Presolve removed 9422521 rows and 5171337 columns (presolve time = 85s)...
Presolve removed 9569669 rows and 5287311 columns (presolve time = 90s)...
Presolve removed 9717570 rows and 5403976 columns (presolve time = 95s)...
Presolve removed 9866026 rows and 5521062 columns (presolve time = 100s)...
Presolve removed 10022883 rows and 5646073 columns (presolve time = 105s)...
Presolve removed 10156760 rows and 5753978 columns (presolve time = 110s)...
Presolve removed 10291258 rows and 5863859 columns (presolve time = 115s)...
Presolve removed 10498017 rows and 6034906 columns (presolve time = 120s)...
Presolve removed 10562186 rows and 6089187 columns
Presolve time: 122.05s
Presolved: 8029 rows, 6809 columns, 25317 nonzeros
Found heuristic solution: objective -2.03083e+10
Variable types: 6228 continuous, 581 integer (577 binary)
Root relaxation presolve removed 1490 rows and 2325 columns
Root relaxation presolved: 6539 rows, 4484 columns, 18695 nonzeros


Root simplex log...

Iteration    Objective       Primal Inf.    Dual Inf.      Time
       0    4.1533622e+08   9.023013e+04   0.000000e+00    123s
    1640    4.1039060e+08   0.000000e+00   0.000000e+00    123s
    1640    4.1039060e+08   0.000000e+00   0.000000e+00    123s

Root relaxation: objective 4.103906e+08, 1640 iterations, 0.03 seconds (0.05 work units)

    Nodes    |    Current Node    |     Objective Bounds      |     Work
 Expl Unexpl |  Obj  Depth IntInf | Incumbent    BestBd   Gap | It/Node Time

     0     0 4.1039e+08    0    4 -2.031e+10 4.1039e+08   102%     -  123s
H    0     0                    -3.47401e+09 4.1039e+08   112%     -  123s
H    0     0                    3.794172e+08 4.1039e+08  8.16%     -  123s
     0     0 4.1039e+08    0    4 3.7942e+08 4.1039e+08  8.16%     -  123s
H    0     0                    4.102746e+08 4.1039e+08  0.03%     -  123s
H    0     0                    4.102937e+08 4.1039e+08  0.02%     -  123s
     0     0 4.1029e+08    0    4 4.1029e+08 4.1029e+08  0.00%     -  123s

Cutting planes:
  Implied bound: 2
  MIR: 10
  Flow cover: 6
  Relax-and-lift: 2

Explored 1 nodes (1669 simplex iterations) in 124.57 seconds (483.52 work units)
Thread count was 8 (of 20 available processors)

Solution count 6: 4.10294e+08 4.10275e+08 3.79417e+08 ... -1.75965e+12

Optimal solution found (tolerance 1.00e-04)
Best objective 4.102936579938e+08, best bound 4.102936579938e+08, gap 0.0000%

- Status: ok
  Return code: 0
  Message: Model was solved to optimality (subject to tolerances), and an optimal solution is available.
  Termination condition: optimal
  Termination message: Model was solved to optimality (subject to tolerances), and an optimal solution is available.
  Wall time: 124.7260000705719
  Error rc: 0


================  OPTIMAL ANNUAL PROFIT  ================
Total profit : 410,293,658 SEK / yr

==================  BREAKDOWN  =================
Revenue (all chargers)             :   585,275,261
Opex - grid purchases              :   115,563,839
Opex - redirection distance        :             0
Opex - redirection price comp.     :             0
Opex - unmet-demand penalty        :             0
Capex - chargers                   :    24,078,474
Capex - PV & batteries             :    35,339,289
----------------------------------------------------------
Slow   chargers:        606 | energy:   1,559,544.0 | cap ratio: 0.027
Medium chargers:      2,608 | energy:  62,844,148.5 | cap ratio: 0.125
Fast   chargers:        165 | energy:  30,712,750.4 | cap ratio: 0.425
==========================================================

Writing CSV/XLSX outputs...
Combined XLSX written to: C:\Users\omkarp\IdeaProjects\GotVIPV\src\main\python\Opti\runs\2026-08-12_132848_full_noVIPV_no_redirection_withPV_withBESS_slackpenalty\results\combined_results.xlsx
Output files written to: C:\Users\omkarp\IdeaProjects\GotVIPV\src\main\python\Opti\runs\2026-08-12_132848_full_noVIPV_no_redirection_withPV_withBESS_slackpenalty\results
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
Figure skipped: slack (No positive slack)
Figure generated: spatial_maps
Figures written to: C:\Users\omkarp\IdeaProjects\GotVIPV\src\main\python\Opti\runs\2026-08-12_132848_full_noVIPV_no_redirection_withPV_withBESS_slackpenalty\figures
Run finished successfully. Run directory: C:\Users\omkarp\IdeaProjects\GotVIPV\src\main\python\Opti\runs\2026-08-12_132848_full_noVIPV_no_redirection_withPV_withBESS_slackpenalty

Terminal transcript written to: C:\Users\omkarp\IdeaProjects\GotVIPV\src\main\python\Opti\runs\2026-08-12_132848_full_noVIPV_no_redirection_withPV_withBESS_slackpenalty\README_RUN.txt
