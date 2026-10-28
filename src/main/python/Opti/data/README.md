# Local inputs only

No input data are shipped in this archive. Restore your newly prepared files here after replacing the code folder.

| Dataset | Per-treatment directory | Required files |
|---|---|---|
| Full | `data/full/<VIPV_SCENARIO>/` | `demandHexGrid_optimization_full.gpkg`, `shortestpath.csv`, `CharParkfull.shp` and sidecars |
| Small | `data/small/<VIPV_SCENARIO>/` | `demandHexGrid_optimization_shrunk30.gpkg`, `shortestpath.csv`, `CharParksmall.shp` and sidecars |
| Shared | `data/` | `PVGISdata.csv`, `ElPrice.csv` |

The ten exact treatment names are defined in `config/paths.json`. Each demand layer contains all four seasons. Do not create four independent optimization folders for a single treatment's seasons.

Optional `provenance.json` is generated next to each demand layer by the registration workflow; no prefilled registration is included. See [the provenance guide](../docs/DATA_PROVENANCE.md) for schemas, units, time alignment, registration and the limitations for spatial subsets.

Validate without solving:

```powershell
python scripts/validate_inputs.py --dataset full --all-scenarios
```

The default `small` selection in `config/paths.json` is retained from UrbanEV. The Windows wrappers and matrix runner explicitly default to `full`. Always specify the dataset in final experiment commands.
