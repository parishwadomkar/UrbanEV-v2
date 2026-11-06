# Optimization inputs

The default `full` dataset contains ten treatment folders defined in [paths.json](../config/paths.json). Each demand layer covers all four seasons.

| Location | Required inputs |
| --- | --- |
| `full/<VIPV_SCENARIO>/` | Demand GeoPackage, shortest-path CSV, and `CharParkfull.shp` with its sidecars |
| `data/` | `PVGISdata.csv` and `ElPrice.csv` |

The [input contract](../config/README.md) describes units, required fields, and model policies. Public installation budgets (`PublicRes`), home-charger counts (`homeChar`), and panel limits (`Panels`) are supplied directly.

Validate the published inputs from `src/main/python/Opti` without solving:

```powershell
python scripts/validate_inputs.py --dataset full --all-scenarios
```
