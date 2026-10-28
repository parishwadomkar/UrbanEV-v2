# Configuration and input contract

| File | Purpose |
| --- | --- |
| `paths.json` | Dataset/treatment selection, input paths, and run root |
| `model_config.json` | Economic coefficients, service rates, asset limits, and model policies |
| `solver_gurobi.json` | Base Gurobi settings |
| `run_profiles.json` | Method/dataset defaults for unset command-line options |

Explicit command-line values override profile defaults. Relative input paths are resolved from Opti. `{vipv_scenario}` selects the demand treatment; each configured case must provide all required inputs.

## Required inputs

| Input | Required fields and units |
| --- | --- |
| Seasonal demand layer | `Season`, `HexID`, `TimeIndex`, `charType`, `Demand`; kWh per half-hour interval |
| Installation-capacity layer | `HexID`, `PublicRes`, `homeChar`, `Panels` |
| Shortest-path CSV | `from_HexID`, `to_HexID`, `distance`; metres |
| PVGIS table | `year`, `month`, `date`, `hour`, configured power column; `date` is day of month |
| Spot-price CSV | `Jan` through `Dec`; 24 ordered hourly rows; öre/kWh |

Demand seasons are `WINTER`, `SPRING`, `SUMMER`, and `AUTUMN`; slots are 1–48; charging classes are `home` and `public`. The full season/cell/slot/class grid, including zeros, is required by default. Demand and capacity geometries must declare matching coordinate reference systems. Cell IDs must be integers; capacity records must have unique IDs. Values must be finite and nonnegative.

`PublicRes` is the final installation resource budget and may be fractional. `homeChar` and `Panels` are integer availability limits. Public charger counts are optimized subject to the configured resource weights. Input capacities are used directly. Retain the `.shp`, `.shx`, `.dbf`, and `.prj` files together, including `.cpg` when supplied.

## Model policies

| Setting | Meaning |
| --- | --- |
| `work_charging_policy` | `reject`, or `merge_public` to include a supplied work category in public demand |
| `missing_demand_policy` | `error`, or `explicit_zero` for intentionally sparse demand |
| `require_data_provenance` | Require a registered source record when `true`; input hashes are recorded independently |
| `pvgis_input_timezone` | `as_supplied`, `UTC`, or `Europe/Stockholm`; the demand and price clock must be consistent |
| `pvgis_power_unit` | Explicit PVGIS unit: `W`, `kW`, or `cf` |
| `bess_boundary` | `legacy_linked_months` or `cyclic_day` |

Unknown model settings are rejected. See [model assumptions](../assets/MODEL_ASSUMPTIONS.md) for annual accounting and storage conventions, and the [main README](../README.md) for local resource settings and run commands.
