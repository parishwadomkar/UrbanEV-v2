from __future__ import annotations

import numpy as np
import pandas as pd

SEASONS = {"WINTER", "SPRING", "SUMMER", "AUTUMN"}

MODEL_CONFIG_KEYS = frozenset({
    "speed_car_kmh", "speed_walk_kmh", "value_time_sek_per_h",
    "max_redirection_distance_km", "arc_activity_threshold_kwh", "redir_min_kwh",
    "x_kwh_per_trip", "time_slots_per_day", "slot_hours", "rho_half_hours_per_hour",
    "penalty_per_kwh_slack", "charger_resources", "discount_rate", "asset_specs",
    "charger_capacity_kwh_per_slot", "charger_price_sek_per_kwh",
    "battery_max_units_per_hex", "battery_cell_cap_kwh", "battery_power_kw",
    "battery_duration_h", "initial_soc_fraction", "soc_min_fraction", "soc_max_fraction",
    "eta_charge", "eta_discharge", "panel_kw", "pvgis_power_col", "pvgis_power_unit",
    "pvgis_min_annual_kwh_per_kwp", "pvgis_max_annual_kwh_per_kwp", "vat",
    "electricity_tax_sek_per_kwh", "grid_fee_sek_per_kwh", "retail_markup_sek_per_kwh",
    "work_charging_policy", "missing_demand_policy", "require_data_provenance",
    "pvgis_input_timezone", "bess_boundary",
})


def validate_model_config(cfg):
    unknown = set(cfg) - MODEL_CONFIG_KEYS
    if unknown:
        raise ValueError(
            f"Unsupported model settings: {sorted(unknown)}. Use the supplied "
            "config/model_config.json; installation capacities belong in the input data."
        )
    for key, types in [
        ("charger_resources", {"slow", "medium", "fast"}),
        ("charger_capacity_kwh_per_slot", {"home", "slow", "medium", "fast"}),
    ]:
        values = cfg.get(key)
        if not isinstance(values, dict) or set(values) != types:
            raise ValueError(f"{key} must contain exactly {sorted(types)}.")
        numbers = np.asarray(list(values.values()), dtype=float)
        if not np.isfinite(numbers).all() or (numbers <= 0).any():
            raise ValueError(f"{key} must contain finite, positive values.")
        if key == "charger_resources" and (numbers != np.floor(numbers)).any():
            raise ValueError("charger_resources must contain integer resource weights.")


def validate_capacity_inputs(parking):
    if "PublicRes" not in parking:
        raise ValueError(
            "Capacity input must contain PublicRes, the final public installation "
            "resource budget. ParkingCap is not a supported substitute."
        )
    require_columns(parking, ["HexID", "PublicRes", "homeChar", "Panels"], "Parking")
    out = parking.copy()
    for col in ["HexID", "homeChar", "Panels"]:
        out[col] = numeric(out, col, integer=True)
    out["PublicRes"] = numeric(out, "PublicRes")
    if out["HexID"].duplicated().any():
        raise ValueError("Parking HexID must be unique.")
    return out


def numeric(frame, column, *, integer=False, nonnegative=True):
    values = pd.to_numeric(frame[column], errors="coerce")
    if not np.isfinite(values.to_numpy(dtype=float)).all():
        raise ValueError(f"{column} must contain finite numeric values.")
    if nonnegative and (values < 0).any():
        raise ValueError(f"{column} must be nonnegative.")
    if integer and (values != np.floor(values)).any():
        raise ValueError(f"{column} must contain integer values.")
    return values.astype(int if integer else float)


def require_columns(frame, columns, label):
    missing = set(columns) - set(frame.columns)
    if missing:
        raise ValueError(f"{label} is missing columns: {sorted(missing)}")


def validate_inputs(raw, cfg):
    validate_model_config(cfg)
    gdf, parking, distances = (raw[k].copy() for k in ("gdf", "parking_gdf", "dist_df"))
    require_columns(gdf, ["Season", "HexID", "TimeIndex", "charType", "Demand"], "Demand")
    parking = validate_capacity_inputs(parking)
    require_columns(distances, ["from_HexID", "to_HexID", "distance"], "Distances")
    if int(cfg["time_slots_per_day"]) != 48 or float(cfg["slot_hours"]) != 0.5:
        raise ValueError("This formulation requires 48 half-hour intervals per representative day.")
    if gdf.empty or parking.empty:
        raise ValueError("Demand and parking inputs must be nonempty.")
    gdf["Season"] = gdf["Season"].astype("string").str.strip().str.upper()
    if gdf["Season"].isna().any() or set(gdf["Season"]) != SEASONS:
        raise ValueError("Demand must contain exactly WINTER, SPRING, SUMMER and AUTUMN.")
    for col in ["HexID", "TimeIndex"]:
        gdf[col] = numeric(gdf, col, integer=True)
    gdf["Demand"] = numeric(gdf, "Demand")
    gdf["charType"] = gdf["charType"].astype("string").str.strip().str.lower()
    keys = ["Season", "HexID", "TimeIndex", "charType"]
    if gdf.duplicated(keys).any():
        raise ValueError("Duplicate season/hex/slot/category demand records.")
    if cfg.get("work_charging_policy", "reject") == "merge_public":
        gdf.loc[gdf["charType"] == "work", "charType"] = "public"
    if gdf["charType"].isna().any() or not set(gdf["charType"]) <= {"home", "public"}:
        raise ValueError("Demand charType must be home/public; set work_charging_policy=merge_public explicitly for work charging.")
    keys = ["Season", "HexID", "TimeIndex", "charType"]
    if gdf.duplicated(keys).any():
        if cfg.get("work_charging_policy") == "merge_public":
            gdf = gdf.groupby(keys, as_index=False)["Demand"].sum()
        else:
            raise ValueError("Duplicate season/hex/slot/category demand records.")
    ids = sorted(gdf["HexID"].unique())
    expected = pd.MultiIndex.from_product([sorted(SEASONS), ids, range(1, 49), ["home", "public"]], names=keys)
    observed = pd.MultiIndex.from_frame(gdf[keys])
    if len(observed.difference(expected)):
        raise ValueError("Demand contains an invalid slot or category.")
    missing = expected.difference(observed)
    if len(missing):
        if cfg.get("missing_demand_policy", "error") != "explicit_zero":
            raise ValueError(f"Demand is missing {len(missing)} season/hex/slot/category records. Supply explicit zero records or select missing_demand_policy=explicit_zero.")
        gdf = gdf.set_index(keys)[["Demand"]].reindex(expected, fill_value=0).reset_index()
    if not set(ids) <= set(parking["HexID"]):
        raise ValueError("Some demand HexID values have no parking record.")
    if getattr(raw["gdf"], "crs", None) is None or getattr(parking, "crs", None) is None:
        raise ValueError("Demand and parking inputs must declare their coordinate reference systems.")
    if raw["gdf"].crs != parking.crs:
        raise ValueError("Demand and parking CRS differ; align them before optimization.")
    for col in ["from_HexID", "to_HexID"]:
        distances[col] = numeric(distances, col, integer=True)
    distances["distance"] = numeric(distances, "distance")
    if distances.duplicated(["from_HexID", "to_HexID"]).any():
        raise ValueError("Duplicate shortest-path origin/destination records.")
    boundary = cfg.get("bess_boundary", "legacy_linked_months")
    if boundary not in {"legacy_linked_months", "cyclic_day"}:
        raise ValueError("bess_boundary must be legacy_linked_months or cyclic_day.")
    if cfg.get("require_data_provenance", False) and not raw.get("provenance", {}).get("source_verified", False):
        raise ValueError("Verified source provenance is required. Run scripts/register_inputs.py with the iteration-100 sources.")
    recorded_basis = raw.get("provenance", {}).get("pvgis_input_timezone")
    if recorded_basis and recorded_basis != cfg.get("pvgis_input_timezone", "as_supplied"):
        raise ValueError("PVGIS timezone differs between provenance and model configuration.")
    return gdf, parking, distances


def disable_redirection(data):
    data.update(allowed=[], allowed_st=[], OUT={}, IN={}, ORIGIN_ST=[], DEST_ST=[], T_dict={})


def align_pvgis_clock(frame, cfg):
    basis = cfg.get("pvgis_input_timezone", "as_supplied")
    if basis == "as_supplied":
        return frame.copy()
    if basis not in {"UTC", "Europe/Stockholm"}:
        raise ValueError("pvgis_input_timezone must be UTC, Europe/Stockholm or as_supplied.")
    out = frame.copy()
    parts = {}
    for key in ["year", "month", "date", "hour"]:
        parts[key] = numeric(out, key, integer=True)
    stamp = pd.to_datetime({"year": parts["year"], "month": parts["month"], "day": parts["date"], "hour": parts["hour"]}, errors="raise")
    if basis == "UTC":
        stamp = stamp.dt.tz_localize("UTC").dt.tz_convert("Europe/Stockholm")
    out["year"], out["month"], out["date"], out["hour"] = stamp.dt.year, stamp.dt.month, stamp.dt.day, stamp.dt.hour
    return out
