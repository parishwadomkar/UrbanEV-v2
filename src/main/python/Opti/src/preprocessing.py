from __future__ import annotations

from collections import defaultdict
import math
import networkx as nx
import numpy as np
import pandas as pd

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
M_ABBR = {
    "January": "Jan", "February": "Feb", "March": "Mar", "April": "Apr",
    "May": "May", "June": "Jun", "July": "Jul", "August": "Aug",
    "September": "Sep", "October": "Oct", "November": "Nov", "December": "Dec",
}
MONTH_NUM_TO_NAME = {i + 1: m for i, m in enumerate(MONTHS)}
N_MONTH = {
    "January": 31, "February": 28, "March": 31, "April": 30,
    "May": 31, "June": 30, "July": 31, "August": 31,
    "September": 30, "October": 31, "November": 30, "December": 31,
}
INTERVALS = list(range(1, 49))
HSOC = list(range(0, 49))
DAYS = sum(N_MONTH.values())
PUB_TYPES = ["slow", "medium", "fast"]
DEMAND_CLASSES = ["home", "public"]
SEASON_TO_MONTHS = {
    "WINTER": ("December", "January", "February"),
    "SPRING": ("March", "April", "May"),
    "SUMMER": ("June", "July", "August"),
    "AUTUMN": ("September", "October", "November"),
}
MONTH_TO_SEASON = {month: season for season, months in SEASON_TO_MONTHS.items() for month in months}


def retail_price_from_ore(p_ore: float, cfg: dict) -> float:
    p_sek = float(p_ore) / 100.0
    return (
        p_sek
        + cfg["electricity_tax_sek_per_kwh"]
        + cfg["grid_fee_sek_per_kwh"]
        + cfg["retail_markup_sek_per_kwh"]
    ) * (1.0 + cfg["vat"])


def build_tou(spot_df: pd.DataFrame, cfg: dict) -> dict:
    required = [M_ABBR[m] for m in MONTHS]
    missing = [c for c in required if c not in spot_df.columns]
    if missing:
        raise ValueError(f"ElPrice.csv is missing month columns: {missing}")
    if len(spot_df.index) < 24:
        raise ValueError("ElPrice.csv must contain at least 24 hourly rows (0,...,23).")

    clean = spot_df.copy()
    for col in required:
        clean[col] = pd.to_numeric(clean[col], errors="coerce")
        if clean[col].iloc[:24].isna().any():
            raise ValueError(f"ElPrice.csv contains non-numeric/missing values in the first 24 rows of column {col}.")

    return {
        m: {t: retail_price_from_ore(clean.at[(t - 1) // 2, M_ABBR[m]], cfg) for t in INTERVALS}
        for m in MONTHS
    }


def pvf_daily(r: float, n: int) -> float:
    return (r * (1 + r) ** n) / ((1 + r) ** n - 1) / 365.0


def build_daily_costs(cfg: dict) -> dict:
    out = {}
    r = float(cfg["discount_rate"])
    for asset, spec in cfg["asset_specs"].items():
        capex = float(spec["capex_sek"])
        life = int(spec["life_years"])
        om = float(spec.get("fixed_om_fraction", 0.0))
        out[asset] = round(capex * pvf_daily(r, life) + capex * om / 365.0, 4)
    return out


def _coerce_localized_numeric(series: pd.Series, label: str) -> pd.Series:
    """Convert numeric or European-decimal text to float without masking bad data."""
    if pd.api.types.is_numeric_dtype(series):
        out = pd.to_numeric(series, errors="coerce")
    else:
        cleaned = (
            series.astype("string")
            .str.strip()
            .str.replace("\u00a0", "", regex=False)
            .str.replace(" ", "", regex=False)
            .str.replace(",", ".", regex=False)
        )
        out = pd.to_numeric(cleaned, errors="coerce")

    bad = out.isna()
    if bad.any():
        examples = series.loc[bad].astype(str).head(5).tolist()
        raise ValueError(
            f"{label} contains {int(bad.sum())} non-numeric/missing values after "
            f"localized-number parsing. Example values: {examples}"
        )
    return out.astype(float)


def _resolve_pvgis_power_unit(values: pd.Series, cfg: dict, power_col: str) -> str:
    requested = str(cfg.get("pvgis_power_unit", "auto")).strip().lower()
    aliases = {
        "w": "W", "watt": "W", "watts": "W",
        "kw": "kW", "kilowatt": "kW", "kilowatts": "kW",
        "cf": "cf", "capacity_factor": "cf", "factor": "cf",
        "auto": "auto",
    }
    if requested not in aliases:
        raise ValueError(
            "model_config.json pvgis_power_unit must be one of: auto, W, kW, cf."
        )
    requested = aliases[requested]
    if requested != "auto":
        return requested

    lower_name = str(power_col).lower()
    if "factor" in lower_name or lower_name in {"cf", "pv_cf", "capacity_factor"}:
        return "cf"

    positive = pd.to_numeric(values, errors="coerce").dropna()
    positive = positive[positive > 0]
    if positive.empty:
        raise ValueError(f"PVGIS column {power_col!r} contains no positive values.")

    q999 = float(positive.quantile(0.999))
    panel_kw = float(cfg["panel_kw"])
    panel_w = panel_kw * 1000.0
    candidates = {
        "W": q999 / panel_w,
        "kW": q999 / panel_kw,
    }
    plausible = [unit for unit, cf_hi in candidates.items() if 0.05 <= cf_hi <= 1.50]
    if len(plausible) == 1:
        return plausible[0]

    raise ValueError(
        f"Could not safely infer units for PVGIS column {power_col!r}. "
        f"99.9th percentile={q999:.6g}, panel_kw={panel_kw:.6g}. "
        "Set pvgis_power_unit explicitly to 'W', 'kW', or 'cf' in config/model_config.json."
    )


def build_pvgis_monthly_hourly_cf(pvgis_df: pd.DataFrame, cfg: dict):
    power_col = cfg["pvgis_power_col"]
    required_cols = {"year", "month", "date", "hour", power_col}
    missing = required_cols - set(pvgis_df.columns)
    if missing:
        raise ValueError(f"PVGIS file is missing required columns: {missing}")

    df = pvgis_df.copy()
    df["month"] = _coerce_localized_numeric(df["month"], "PVGIS month").astype(int)
    df["hour"] = _coerce_localized_numeric(df["hour"], "PVGIS hour").astype(int)
    df[power_col] = _coerce_localized_numeric(
        df[power_col], f"PVGIS column {power_col!r}"
    )
    if df["hour"].min() < 0 or df["hour"].max() > 23:
        raise ValueError("PVGIS hour column must be in the range 0,...,23.")
    if df["month"].min() < 1 or df["month"].max() > 12:
        raise ValueError("PVGIS month column must be in the range 1,...,12.")

    panel_kw = float(cfg["panel_kw"])
    panel_rated_w = panel_kw * 1000.0
    detected_unit = _resolve_pvgis_power_unit(df[power_col], cfg, power_col)

    if detected_unit == "W":
        df["_power_w"] = df[power_col].astype(float)
        df["_cf"] = df["_power_w"] / panel_rated_w
    elif detected_unit == "kW":
        df["_power_w"] = df[power_col].astype(float) * 1000.0
        df["_cf"] = df[power_col].astype(float) / panel_kw
    else:
        df["_cf"] = df[power_col].astype(float)
        df["_power_w"] = df["_cf"] * panel_rated_w

    if (df["_cf"] < -1e-9).any():
        raise ValueError("PVGIS power/capacity-factor input contains negative values.")
    df["_cf"] = df["_cf"].clip(lower=0.0, upper=1.0)
    df["_power_w"] = df["_cf"] * panel_rated_w

    monthly_hourly = (
        df.groupby(["month", "hour"], as_index=False)
        .agg(avg_power_w=("_power_w", "mean"), cf=("_cf", "mean"))
    )
    full_idx = pd.MultiIndex.from_product([range(1, 13), range(0, 24)], names=["month", "hour"])
    monthly_hourly = (
        monthly_hourly.set_index(["month", "hour"])
        .reindex(full_idx, fill_value=0.0)
        .reset_index()
    )
    monthly_hourly["cf"] = monthly_hourly["cf"].clip(0.0, 1.0)

    cf_lookup = {
        (MONTH_NUM_TO_NAME[int(r.month)], int(r.hour)): float(r.cf)
        for r in monthly_hourly.itertuples(index=False)
    }
    pv_cf = {mon: {t: cf_lookup[(mon, (t - 1) // 2)] for t in INTERVALS} for mon in MONTHS}

    raw_counts = df.groupby("month").agg(
        n_days=("date", "nunique"),
        raw_input_min=(power_col, "min"),
        raw_input_mean=(power_col, "mean"),
        raw_input_max=(power_col, "max"),
    )
    daily_cf = monthly_hourly.groupby("month")["cf"].sum()
    diag_rows = []
    for month_num in range(1, 13):
        mon = MONTH_NUM_TO_NAME[month_num]
        cf_day_sum = float(daily_cf.get(month_num, 0.0))
        avg_kwh_per_kwp_day = cf_day_sum
        avg_kwh_per_panel_day = panel_kw * cf_day_sum
        row = {
            "month": month_num,
            "month_name": mon,
            "detected_input_unit": detected_unit,
            "panel_kw": panel_kw,
            "n_days_in_input": int(raw_counts.loc[month_num, "n_days"]) if month_num in raw_counts.index else 0,
            "raw_input_min": float(raw_counts.loc[month_num, "raw_input_min"]) if month_num in raw_counts.index else 0.0,
            "raw_input_mean": float(raw_counts.loc[month_num, "raw_input_mean"]) if month_num in raw_counts.index else 0.0,
            "raw_input_max": float(raw_counts.loc[month_num, "raw_input_max"]) if month_num in raw_counts.index else 0.0,
            "max_capacity_factor": float(monthly_hourly.loc[monthly_hourly["month"] == month_num, "cf"].max()),
            "avg_kwh_per_kwp_day": avg_kwh_per_kwp_day,
            "avg_kwh_per_panel_day": avg_kwh_per_panel_day,
            "annualized_kwh_per_kwp": avg_kwh_per_kwp_day * N_MONTH[mon],
            "annualized_kwh_per_panel": avg_kwh_per_panel_day * N_MONTH[mon],
        }
        diag_rows.append(row)
    pv_diag = pd.DataFrame(diag_rows)

    annual_kwh_per_kwp = float(pv_diag["annualized_kwh_per_kwp"].sum())
    min_yield = float(cfg.get("pvgis_min_annual_kwh_per_kwp", 100.0))
    max_yield = float(cfg.get("pvgis_max_annual_kwh_per_kwp", 2500.0))
    if not (min_yield <= annual_kwh_per_kwp <= max_yield):
        raise ValueError(
            "PVGIS preprocessing produced an implausible annualized PV yield: "
            f"{annual_kwh_per_kwp:.2f} kWh/kWp-year. "
            f"Configured diagnostic range is [{min_yield:.1f}, {max_yield:.1f}]. "
            "Check pvgis_power_unit and pvgis_power_col before optimization."
        )

    return pv_cf, pv_diag


def get_distance_dict(dist_df: pd.DataFrame) -> dict:
    df = dist_df.copy()
    df["distance_km"] = df["distance"] / 1000.0
    return {(int(r.from_HexID), int(r.to_HexID)): round(float(r.distance_km), 4) for _, r in df.iterrows()}


def preprocess(raw: dict, cfg: dict) -> dict:
    gdf = raw["gdf"].copy()
    parking_gdf = raw["parking_gdf"].copy()
    dist_df = raw["dist_df"].copy()
    spot_df = raw["spot_df"].copy()
    pvgis_df = raw["pvgis_df"].copy()

    gdf["HexID"] = gdf["HexID"].astype(int)
    gdf["charType"] = gdf["charType"].astype(str).str.lower().str.strip()
    hex_ids = sorted(gdf["HexID"].unique())
    time_indices = sorted(gdf["TimeIndex"].astype(int).unique())

    parking_gdf["HexID"] = parking_gdf["HexID"].astype(int)
    parking_gdf["ParkingCap"] = parking_gdf["ParkingCap"]/2.0 + int(cfg["parking_capacity_add"])
    parking_gdf["homeChar"] = parking_gdf["homeChar"] + int(cfg["home_charger_add"])

    cl = parking_gdf.set_index("HexID")["ParkingCap"].to_dict()
    home_avail = parking_gdf.set_index("HexID")["homeChar"].to_dict()
    for i in hex_ids:
        cl.setdefault(int(i), 0)
        home_avail.setdefault(int(i), 0)

    charger_capacity = cfg["charger_capacity_kwh_per_slot"]
    charger_capacity_pub = {c: float(charger_capacity[c]) for c in PUB_TYPES}
    charger_price = {c: float(cfg["charger_price_sek_per_kwh"][c]) for c in PUB_TYPES}
    charger_resources = {c: float(cfg["charger_resources"][c]) for c in PUB_TYPES}
    eligible = {"home": PUB_TYPES[:], "public": PUB_TYPES[:]}
    delta_price = {(co, cd): max(0.0, charger_price[cd] - charger_price[co]) for co in PUB_TYPES for cd in PUB_TYPES}

    daily_cost = build_daily_costs(cfg)
    tou = build_tou(spot_df, cfg)
    pv_cf, pv_diag = build_pvgis_monthly_hourly_cf(pvgis_df, cfg)
    input_profile_rows = [
        {
            "Month": mon,
            "Season": MONTH_TO_SEASON[mon],
            "TimeIndex": int(t),
            "PV_capacity_factor": float(pv_cf[mon][t]),
            "Retail_price_SEK_per_kWh": float(tou[mon][t]),
        }
        for mon in MONTHS for t in INTERVALS
    ]
    input_monthly_profiles = pd.DataFrame(input_profile_rows)
    dist_dict = get_distance_dict(dist_df)
    hex_id_set = set(int(i) for i in hex_ids)

    # Keep only distance arcs whose origin and destination both exist
    # in the selected demand/parking dataset.
    allowed = {
        (int(i), int(j))
        for (i, j), d in dist_dict.items()
        if (
            int(i) in hex_id_set
            and int(j) in hex_id_set
            and int(i) != int(j)
            and float(d) <= float(cfg["max_redirection_distance_km"])
        )
    }
    beta = float(cfg["value_time_sek_per_h"]) * (1.0 / float(cfg["speed_car_kmh"]) + 2.0 / float(cfg["speed_walk_kmh"]))
    t_dict = {(i, j): beta * dist_dict[(i, j)] for (i, j) in allowed}

    seasonal_demand_enabled = "Season" in gdf.columns
    if seasonal_demand_enabled:
        gdf["Season"] = gdf["Season"].astype(str).str.upper().str.strip()
        observed_seasons = set(gdf["Season"].dropna().unique())
        unknown_seasons = observed_seasons - set(SEASON_TO_MONTHS)
        if unknown_seasons:
            raise ValueError(f"Demand GeoPackage contains unrecognized Season values: {sorted(unknown_seasons)}")
        missing_seasons = set(SEASON_TO_MONTHS) - observed_seasons
        if missing_seasons:
            raise ValueError(
                "Season-specific optimization demand must contain all four seasons. "
                f"Missing: {sorted(missing_seasons)}"
            )
        grp = (
            gdf[["Season", "HexID", "TimeIndex", "Demand", "charType"]]
            .groupby(["Season", "HexID", "TimeIndex", "charType"], as_index=False)["Demand"]
            .sum()
        )
        home_profile = defaultdict(float)
        public_profile = defaultdict(float)
        for r in grp.itertuples(index=False):
            key = (str(r.Season), int(r.HexID), int(r.TimeIndex))
            if str(r.charType) == "home":
                home_profile[key] += float(r.Demand)
            else:
                public_profile[key] += float(r.Demand)

        def source_demand(i: int, mon: str, t: int, char_type: str) -> float:
            key = (MONTH_TO_SEASON[mon], int(i), int(t))
            return float(home_profile[key] if char_type == "home" else public_profile[key])
    else:
        grp = (
            gdf[["HexID", "TimeIndex", "Demand", "charType"]]
            .groupby(["HexID", "TimeIndex", "charType"], as_index=False)["Demand"]
            .sum()
        )
        home_profile = defaultdict(float)
        public_profile = defaultdict(float)
        for r in grp.itertuples(index=False):
            key = (int(r.HexID), int(r.TimeIndex))
            if str(r.charType) == "home":
                home_profile[key] += float(r.Demand)
            else:
                public_profile[key] += float(r.Demand)

        def source_demand(i: int, mon: str, t: int, char_type: str) -> float:
            key = (int(i), int(t))
            return float(home_profile[key] if char_type == "home" else public_profile[key])

    home_kwh_per_slot = float(charger_capacity["home"])
    home_demand_total_event = {}
    home_private_served_event = {}
    demand_event_annual = {}

    for i in hex_ids:
        cap_i = float(home_avail[i]) * home_kwh_per_slot
        for mon in MONTHS:
            for t in time_indices:
                raw_home = float(source_demand(int(i), mon, int(t), "home"))
                raw_public = float(source_demand(int(i), mon, int(t), "public"))
                private_served = min(raw_home, cap_i)
                residual_home = max(raw_home - private_served, 0.0)

                home_demand_total_event[(int(i), mon, int(t))] = raw_home
                home_private_served_event[(int(i), mon, int(t))] = private_served
                demand_event_annual[(int(i), mon, int(t), "home")] = residual_home
                demand_event_annual[(int(i), mon, int(t), "public")] = raw_public

    # Backward-compatible alias; all current optimization code should use demand_event_annual.
    demand_event = demand_event_annual

    seasonal_diag_rows = []
    for season, months in SEASON_TO_MONTHS.items():
        representative_month = months[0]
        raw_home = sum(
            home_demand_total_event[(int(i), representative_month, int(t))]
            for i in hex_ids for t in time_indices
        )
        private_home = sum(
            home_private_served_event[(int(i), representative_month, int(t))]
            for i in hex_ids for t in time_indices
        )
        residual_home = sum(
            demand_event_annual[(int(i), representative_month, int(t), "home")]
            for i in hex_ids for t in time_indices
        )
        public = sum(
            demand_event_annual[(int(i), representative_month, int(t), "public")]
            for i in hex_ids for t in time_indices
        )
        n_days = sum(N_MONTH[m] for m in months)
        seasonal_diag_rows.append({
            "Season": season,
            "Months": ",".join(months),
            "Days": n_days,
            "RepresentativeDay_HomeTotal_kWh": raw_home,
            "RepresentativeDay_HomePrivateServed_kWh": private_home,
            "RepresentativeDay_HomeResidual_kWh": residual_home,
            "RepresentativeDay_Public_kWh": public,
            "RepresentativeDay_TotalMATSim_kWh": raw_home + public,
            "SeasonAnnualized_TotalMATSim_kWh": (raw_home + public) * n_days,
            "SeasonAnnualized_OptimizationBoundary_kWh": (residual_home + public) * n_days,
        })
    seasonal_demand_diagnostics = pd.DataFrame(seasonal_diag_rows)

    def arc_active(i: int, j: int, mon: str, t: int) -> bool:
        return (
            demand_event_annual.get((int(i), mon, int(t), "public"), 0.0)
            + demand_event_annual.get((int(j), mon, int(t), "public"), 0.0)
        ) > float(cfg["arc_activity_threshold_kwh"])

    allowed_st = {
        (int(i), int(j), mon, int(t))
        for (i, j) in allowed
        for mon in MONTHS
        for t in INTERVALS
        if arc_active(i, j, mon, t)
    }

    g = nx.Graph()
    g.add_nodes_from(hex_ids)
    g.add_edges_from(allowed)
    pub_demand = {
        i: sum(demand_event_annual[(int(i), mon, int(t), "public")] for mon in MONTHS for t in time_indices)
        for i in hex_ids
    }
    for comp in nx.connected_components(g):
        if any(pub_demand[i] > 0 for i in comp) and all(cl[i] == 0 for i in comp):
            i_star = max(comp, key=lambda i: pub_demand[i])
            cl[i_star] = 2

    if "Panels" not in parking_gdf.columns:
        raise KeyError("Parking shapefile must contain a 'Panels' column for PV upper bounds.")
    pv_upper = parking_gdf.set_index("HexID")["Panels"].to_dict()
    for i in hex_ids:
        pv_upper.setdefault(int(i), 0)

    out = defaultdict(list)
    incoming = defaultdict(list)
    for (i, j, mon, t) in allowed_st:
        out[(i, mon, t)].append(j)
        incoming[(j, mon, t)].append(i)
    origin_st = sorted(out.keys())
    dest_st = sorted(incoming.keys())

    prev_month = {MONTHS[i]: MONTHS[i - 1] if i > 0 else MONTHS[-1] for i in range(len(MONTHS))}
    k_batt = float(cfg["battery_cell_cap_kwh"]) / (float(cfg["battery_duration_h"]) * float(cfg["rho_half_hours_per_hour"]))
    m_batt = {int(i): k_batt * int(cfg["battery_max_units_per_hex"]) for i in hex_ids}
    max_k_per_resource = max(charger_capacity_pub[c] / charger_resources[c] for c in PUB_TYPES)
    m_redir = {int(j): float(max_k_per_resource * cl[int(j)]) for j in hex_ids}

    return {
        "MONTHS": MONTHS,
        "N_MONTH": N_MONTH,
        "DAYS": DAYS,
        "INTERVALS": INTERVALS,
        "HSOC": HSOC,
        "PUB_TYPES": PUB_TYPES,
        "DEMAND_CLASSES": DEMAND_CLASSES,
        "hex_ids": hex_ids,
        "time_indices": time_indices,
        "cl": cl,
        "home_avail": home_avail,
        "home_demand_total_event": home_demand_total_event,
        "home_private_served_event": home_private_served_event,
        "demand_event": demand_event,
        "demand_event_annual": demand_event_annual,
        "seasonal_demand_enabled": seasonal_demand_enabled,
        "month_to_season": dict(MONTH_TO_SEASON),
        "allowed": sorted(allowed),
        "allowed_st": sorted(allowed_st),
        "ORIGIN_ST": origin_st,
        "DEST_ST": dest_st,
        "OUT": out,
        "IN": incoming,
        "dist_dict": dist_dict,
        "T_dict": t_dict,
        "beta": beta,
        "tou": tou,
        "pv_cf": pv_cf,
        "pv_diag": pv_diag,
        "input_monthly_profiles": input_monthly_profiles,
        "seasonal_demand_diagnostics": seasonal_demand_diagnostics,
        "pv_upper": pv_upper,
        "daily_cost": daily_cost,
        "charger_capacity_pub": charger_capacity_pub,
        "charger_capacity": charger_capacity,
        "charger_price": charger_price,
        "charger_resources": charger_resources,
        "delta_price": delta_price,
        "eligible": eligible,
        "prev_month": prev_month,
        "pv_kwh_per_panel_slot_at_cf1": float(cfg["panel_kw"]) * float(cfg["slot_hours"]),
        "K_BATT": k_batt,
        "M_BATT": m_batt,
        "M_REDIR": m_redir,
    }
