# Configuration files

`solver_gurobi.json` contains settings shared by all methods. `run_profiles.json` contains calibrated method- and dataset-specific settings. Values supplied on the command line take precedence over both files.

## VIPV scenario data layout

The optimization inputs are resolved from `config/paths.json` using both dataset size and VIPV scenario. The expected layout is:

```text
data/
  ElPrice.csv
  PVGISdata.csv
  small/<VIPV_SCENARIO>/
    demandHexGrid_optimization_shrunk30.gpkg
    shortestpath.csv
    CharParksmall.shp (+ shapefile sidecars)
  full/<VIPV_SCENARIO>/
    demandHexGrid_optimization_full.gpkg
    shortestpath.csv
    CharParkfull.shp (+ shapefile sidecars)
```

The ten accepted scenario names are `noVIPV`, `VIPV20_Wp400`, `VIPV20_Wp700`, `VIPV20_Wp1000`, `VIPV50_Wp400`, `VIPV50_Wp700`, `VIPV50_Wp1000`, `VIPV80_Wp400`, `VIPV80_Wp700`, and `VIPV80_Wp1000`.

Recommended CLI syntax is `--vipv-scenario VIPV50_Wp700 --dataset full`. Convenience syntax is also supported: `--VIPV50_Wp700 --full` or `--VIPV50_Wp700 full`. Existing scripts that do not specify a VIPV scenario continue to use the configured defaults (`noVIPV`, `small`).

Run folders include the dataset and VIPV scenario names so results from the ten demand scenarios remain traceable.

## Seasonal annualization and PVGIS unit validation

If the demand GeoPackage contains a `Season` field, the optimizer requires all four labels and maps them as follows: `WINTER -> Dec/Jan/Feb`, `SPRING -> Mar/Apr/May`, `SUMMER -> Jun/Jul/Aug`, and `AUTUMN -> Sep/Oct/Nov`. The corresponding seasonal MATSim profile is used for each month and operating quantities are weighted with the exact number of days in that month.

`ElPrice.csv` remains month-specific and is converted to the retail half-hour tariff used by the optimization. `PVGISdata.csv` remains month/hour-specific. `model_config.json` contains `pvgis_power_unit`. For the supplied Gothenburg `PVGISdata.csv`, this is set explicitly to `W`, because `500W_P` is the hourly electrical output in watts from a fixed 500 Wp panel. The CSV uses semicolon delimiters and decimal commas; `src/data_loader.py` parses these explicitly. This affects input parsing only; the MILP PV constraint and objective are unchanged.

The smoke test now performs content validation after the ordinary path/import checks and reports the season mapping, detected PVGIS unit, implied annual stationary-PV yield, and retail ToU range. This is intended to catch scaling errors before a full MILP is constructed.
