python src\run_optimization.py `
  --vipv-scenario VIPV50_Wp700 `
  --dataset full `
  --scenario no_redirection `
  --threads 8 `
  --soft-mem-limit-gb 56 `
  --mip-gap 0.0001 `
  --nodefile-start 0.5


python src\compare_scenarios.py `
  --method monolithic `
  --run "runs\2026-08-12_132848_full_noVIPV_no_redirection_withPV_withBESS_slackpenalty" `
  --run "runs\2026-08-12_142251_full_VIPV50_Wp700_no_redirection_withPV_withBESS_slackpenalty" `
  --baseline-index 1

  