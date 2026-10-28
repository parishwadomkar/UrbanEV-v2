# Benders benchmark

This entry point uses the shared seasonal inputs, model configuration, and result exports. Available cut strategies are `standard` and `corepoint`. Run options are listed by:

```powershell
python src_benders/run_benders.py --help
```

For the decomposition method, validation experiments, and reference execution examples, see the [original Benders documentation](https://github.com/parishwadomkar/Large-scale-LBBD-Optimization/blob/main/src_benders/README.md), the [reference repository](https://github.com/parishwadomkar/Large-scale-LBBD-Optimization), and the [associated paper](https://doi.org/10.1016/j.adapen.2026.100310).

Local installation, input requirements, resource settings, and comparison tools are documented in the [UrbanEV-Opti README](../README.md).
