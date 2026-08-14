#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import math
import traceback
from pathlib import Path
from typing import Callable

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch, Patch
import numpy as np
import pandas as pd

from input_scenarios import VIPV_SCENARIOS

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
MONTH_DAYS = {
    "January": 31, "February": 28, "March": 31, "April": 30,
    "May": 31, "June": 30, "July": 31, "August": 31,
    "September": 30, "October": 31, "November": 30, "December": 31,
}
REPRESENTATIVE_MONTHS = ["January", "April", "July", "October"]
SEASON_TO_MONTHS = {
    "SPRING": ("March", "April", "May"),
    "SUMMER": ("June", "July", "August"),
    "AUTUMN": ("September", "October", "November"),
    "WINTER": ("December", "January", "February"),
}
SEASON_ORDER = ["SPRING", "SUMMER", "AUTUMN", "WINTER"]


def _read_csv(path: Path, required: bool = False) -> pd.DataFrame:
    if not path.exists():
        if required:
            raise FileNotFoundError(path)
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _summary_dict(results_dir: Path) -> dict[str, object]:
    df = _read_csv(results_dir / "model_summary.csv", required=True)
    if not {"Metric", "Value"}.issubset(df.columns):
        raise ValueError("model_summary.csv must contain Metric and Value columns")
    result: dict[str, object] = {}
    for _, row in df.iterrows():
        key = str(row["Metric"])
        value = row["Value"]
        try:
            result[key] = float(value)
        except (TypeError, ValueError):
            result[key] = value
    return result


def _infer_dataset(run_dir: Path) -> str | None:
    manifest = run_dir / "logs" / "lbbd_manifest.json"
    if manifest.exists():
        try:
            value = json.loads(manifest.read_text(encoding="utf-8")).get("dataset")
            if value in {"small", "full"}:
                return value
        except Exception:
            pass
    for value in ("small", "full"):
        if f"_{value}_" in run_dir.name.lower():
            return value
    try:
        value = _summary_dict(run_dir / "results").get("dataset")
        if str(value) in {"small", "full"}:
            return str(value)
    except Exception:
        pass
    return None



def _infer_vipv_scenario(run_dir: Path) -> str:
    for path in [run_dir / "run_metadata.json", run_dir / "logs" / "lbbd_manifest.json"]:
        if path.exists():
            try:
                value = json.loads(path.read_text(encoding="utf-8")).get("vipv_scenario")
                if value in VIPV_SCENARIOS:
                    return str(value)
            except Exception:
                pass
    try:
        value = _summary_dict(run_dir / "results").get("vipv_scenario")
        if value in VIPV_SCENARIOS:
            return str(value)
    except Exception:
        pass
    lower = run_dir.name.lower()
    for candidate in VIPV_SCENARIOS:
        if f"_{candidate.lower()}_" in lower:
            return candidate
    return "noVIPV"

def _resolve_geometry(project_root: Path, dataset: str | None, parking_shapefile: str | None, vipv_scenario: str = "noVIPV") -> Path | None:
    if parking_shapefile:
        path = Path(parking_shapefile)
        return path if path.is_absolute() else (project_root / path).resolve()
    if dataset is None:
        return None
    cfg_path = project_root / "config" / "paths.json"
    if not cfg_path.exists():
        return None
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    raw = cfg.get("datasets", {}).get(dataset, {}).get("parking_shapefile")
    if not raw:
        return None
    raw = str(raw).format(dataset=dataset, vipv_scenario=vipv_scenario)
    return (project_root / raw).resolve()


def _setup_style() -> None:
    plt.rcParams.update({
        "font.size": 11,
        "axes.titlesize": 14,
        "axes.labelsize": 12,
        "legend.fontsize": 9,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "figure.autolayout": False,
        "axes.grid": True,
        "grid.alpha": 0.25,
        "grid.linestyle": "--",
    })


def _boxed_legend_below(fig: plt.Figure, handles, labels, ncol: int, bottom: float = 0.20) -> None:
    if not handles:
        return
    fig.legend(
        handles,
        labels,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.015),
        ncol=max(1, int(ncol)),
        frameon=True,
        fancybox=True,
        framealpha=0.96,
        edgecolor="0.65",
        columnspacing=1.4,
        handlelength=2.4,
    )
    fig.subplots_adjust(bottom=bottom)


def _sem(series: pd.Series) -> float:
    values = _numeric(series).dropna()
    if len(values) <= 1:
        return 0.0
    return float(values.std(ddof=1) / math.sqrt(len(values)))


def _add_basemap(ax: plt.Axes, alpha: float = 0.30) -> bool:
    """Add a faint CartoDB basemap when contextily and internet access are available."""
    try:
        import contextily as ctx
        xlim, ylim = ax.get_xlim(), ax.get_ylim()
        ctx.add_basemap(
            ax,
            source=ctx.providers.CartoDB.PositronNoLabels,
            crs="EPSG:3857",
            alpha=float(alpha),
            reset_extent=False,
            attribution_size=6,
        )
        ax.set_xlim(xlim)
        ax.set_ylim(ylim)
        return True
    except Exception as exc:
        print(f"WARNING: Basemap unavailable; map generated with vector layers only ({exc})")
        return False


def _save(fig: plt.Figure, figures_dir: Path, stem: str, dpi: int) -> list[str]:
    figures_dir.mkdir(parents=True, exist_ok=True)
    png = figures_dir / f"{stem}.png"
    fig.savefig(png, dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return [png.name]


def _hour_axis(ax: plt.Axes) -> None:
    slots = np.arange(1, 49)
    ticks = np.arange(1, 49, 4)
    labels = [f"{(t - 1) / 2:.0f}:00" for t in ticks]
    ax.set_xlim(1, 48)
    ax.set_xticks(ticks)
    ax.set_xticklabels(labels)
    ax.set_xlabel("Time of representative day")


def _plot_economic_breakdown(results_dir: Path, figures_dir: Path, dpi: int) -> list[str]:
    metrics = _summary_dict(results_dir)
    types = ["slow", "medium", "fast"]
    type_colors = {"slow": "#4C78A8", "medium": "#F58518", "fast": "#54A24B"}
    component_colors = {
        "grid_direct": "#E45756",
        "grid_battery": "#B279A2",
        "distance": "#9D755D",
        "compensation": "#FF9DA6",
        "slack": "#BAB0AC",
        "pv": "#ECA82C",
        "bess": "#72B7B2",
    }

    revenue_by_type = {c: float(metrics.get(f"revenue_{c}_SEK", 0.0) or 0.0) / 1e6 for c in types}
    charger_capex_by_type = {c: float(metrics.get(f"capex_chargers_{c}_SEK", 0.0) or 0.0) / 1e6 for c in types}

    # Backward-compatible fallback for run folders exported before the detailed metrics were added.
    if sum(revenue_by_type.values()) <= 0:
        energies = np.array([float(metrics.get(f"energy_{c}_kWh", 0.0) or 0.0) for c in types])
        shares = energies / energies.sum() if energies.sum() > 0 else np.array([1.0, 0.0, 0.0])
        total = float(metrics.get("revenue_all_chargers_SEK", 0.0) or 0.0) / 1e6
        revenue_by_type = {c: total * shares[k] for k, c in enumerate(types)}
    if sum(charger_capex_by_type.values()) <= 0:
        counts = np.array([float(metrics.get(f"chargers_{c}_installed", 0.0) or 0.0) for c in types])
        shares = counts / counts.sum() if counts.sum() > 0 else np.array([1.0, 0.0, 0.0])
        total = float(metrics.get("capex_chargers_SEK", 0.0) or 0.0) / 1e6
        charger_capex_by_type = {c: total * shares[k] for k, c in enumerate(types)}

    grid_direct = float(metrics.get("grid_direct_cost_SEK", metrics.get("grid_cost_SEK", 0.0)) or 0.0) / 1e6
    grid_battery = float(metrics.get("grid_to_battery_cost_SEK", 0.0) or 0.0) / 1e6
    if grid_direct + grid_battery > 0 and "grid_direct_cost_SEK" not in metrics:
        grid_direct = float(metrics.get("grid_cost_SEK", 0.0) or 0.0) / 1e6
        grid_battery = 0.0

    rows = [
        ("Charging revenue", [(revenue_by_type[c], type_colors[c], c.capitalize()) for c in types]),
        ("Grid electricity", [(-grid_direct, component_colors["grid_direct"], "Grid direct"), (-grid_battery, component_colors["grid_battery"], "Grid to BESS")]),
        ("Redirection cost", [(-float(metrics.get("redirection_distance_cost_SEK", 0.0) or 0.0) / 1e6, component_colors["distance"], "Distance incentive"), (-float(metrics.get("redirection_price_compensation_SEK", 0.0) or 0.0) / 1e6, component_colors["compensation"], "Type compensation")]),
        ("Slack penalty", [(-float(metrics.get("slack_penalty_SEK", 0.0) or 0.0) / 1e6, component_colors["slack"], "Slack penalty")]),
        ("Charger capex", [(-charger_capex_by_type[c], type_colors[c], c.capitalize()) for c in types]),
        ("PV and BESS capex", [(-float(metrics.get("capex_PV_SEK", metrics.get("capex_PV_BESS_SEK", 0.0)) or 0.0) / 1e6, component_colors["pv"], "PV"), (-float(metrics.get("capex_BESS_SEK", 0.0) or 0.0) / 1e6, component_colors["bess"], "BESS")]),
    ]

    fig, ax = plt.subplots(figsize=(13.6, 7.0))
    y = np.arange(len(rows))
    totals = []
    for row_index, (_, segments) in enumerate(rows):
        left_positive = 0.0
        left_negative = 0.0
        total = 0.0
        for value, color, _ in segments:
            if abs(value) <= 1e-12:
                continue
            left = left_positive if value >= 0 else left_negative
            ax.barh(row_index, value, left=left, color=color, edgecolor="white", linewidth=0.5, height=0.68, zorder=3)
            if value >= 0:
                left_positive += value
            else:
                left_negative += value
            total += value
        totals.append(total)

    max_positive = max([v for v in totals if v > 0] + [1.0])
    min_negative = min([v for v in totals if v < 0] + [-1.0])
    span = max_positive - min_negative
    ax.set_xlim(min_negative - 0.07 * span, max_positive + 0.07 * span)
    label_pad = 0.012 * span
    for row_index, total in enumerate(totals):
        if total >= 0:
            ax.text(total + label_pad, row_index, f"{total:,.3f}", va="center", ha="left", fontweight="bold", clip_on=False)
        else:
            ax.text(total - label_pad, row_index, f"{total:,.3f}", va="center", ha="right", fontweight="bold", clip_on=False)

    ax.axvline(0, color="0.25", linewidth=0.9, zorder=4)
    ax.set_yticks(y)
    ax.set_yticklabels([row[0] for row in rows])
    ax.invert_yaxis()
    ax.set_xlabel("Annual cash flow (million SEK/year)")
    ax.set_title("Annual CPO objective composition")
    ax.grid(axis="x", alpha=0.28)
    ax.grid(axis="y", visible=False)

    profit = float(metrics.get("annual_profit_SEK", 0.0) or 0.0) / 1e6
    ax.text(0.985, 0.025, f"Net profit: {profit:,.3f} MSEK/year", transform=ax.transAxes,
            ha="right", va="bottom", bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.92, "edgecolor": "0.45"})

    counts = {c: int(round(float(metrics.get(f"chargers_{c}_installed", 0.0) or 0.0))) for c in types}
    pv_units = int(round(float(metrics.get("PV_panels_installed", 0.0) or 0.0)))
    bess_units = int(round(float(metrics.get("battery_units_installed", 0.0) or 0.0)))
    trip_eq = float(metrics.get("redirection_trip_equivalents_annual", 0.0) or 0.0)
    if trip_eq <= 0:
        redirected = float(metrics.get("energy_redirected_kWh", 0.0) or 0.0)
        trip_eq = redirected / 20.0 if redirected > 0 else 0.0

    legend_handles = [
        Patch(facecolor=type_colors["slow"], label=f"Slow: {counts['slow']:,} chargers"),
        Patch(facecolor=type_colors["medium"], label=f"Medium: {counts['medium']:,} chargers"),
        Patch(facecolor=type_colors["fast"], label=f"Fast: {counts['fast']:,} chargers"),
        Patch(facecolor=component_colors["pv"], label=f"PV: {pv_units:,} panels"),
        Patch(facecolor=component_colors["bess"], label=f"BESS: {bess_units:,} units"),
        Patch(facecolor=component_colors["grid_direct"], label="Grid direct"),
        Patch(facecolor=component_colors["grid_battery"], label="Grid to BESS"),
        Patch(facecolor=component_colors["distance"], label="Distance incentive"),
        Patch(facecolor=component_colors["compensation"], label="Type compensation"),
        Line2D([], [], color="none", label=f"Redirected: {trip_eq:,.0f} trip-equivalents/year"),
    ]
    fig.legend(
        handles=legend_handles,
        loc="upper right",
        bbox_to_anchor=(0.99, 0.90),
        ncol=1,
        frameon=True,
        fancybox=True,
        framealpha=0.96,
        edgecolor="0.65",
        title="Optimized deployment and flows",
    )
    fig.subplots_adjust(left=0.18, right=0.73, bottom=0.12, top=0.90)
    return _save(fig, figures_dir, "01_economic_breakdown", dpi)


def _plot_charger_deployment(results_dir: Path, figures_dir: Path, dpi: int) -> list[str]:
    df = _read_csv(results_dir / "energy_by_charger_type.csv", required=True)
    if df.empty:
        raise ValueError("energy_by_charger_type.csv is empty")
    all_rows = df[df["DemandClass"].astype(str).str.upper() == "ALL"].copy()
    all_rows["InstalledChargers"] = _numeric(all_rows["InstalledChargers"]).fillna(0)
    all_rows["CapacityRatio_all_classes"] = _numeric(all_rows["CapacityRatio_all_classes"]).fillna(0)
    all_rows = all_rows.set_index("ChargerType").reindex(["slow", "medium", "fast"]).fillna(0).reset_index()
    x = np.arange(len(all_rows))
    colors = ["#4C78A8", "#4C78A8", "#4C78A8"]
    fig, ax = plt.subplots(figsize=(8.8, 5.7))
    bars = ax.bar(x, all_rows["InstalledChargers"].to_numpy(), color=colors, alpha=0.88, zorder=2)
    ax.set_xticks(x)
    ax.set_xticklabels([str(v).capitalize() for v in all_rows["ChargerType"]])
    ax.set_ylabel("Installed public chargers")
    ax.set_title("Public charger deployment and annual utilization")
    ax.set_axisbelow(True)
    for bar in bars:
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), f"{bar.get_height():,.0f}", ha="center", va="bottom", zorder=5)

    ax2 = ax.twinx()
    utilization = 100 * all_rows["CapacityRatio_all_classes"].to_numpy()
    line, = ax2.plot(
        x,
        utilization,
        marker="o",
        linewidth=2.8,
        markersize=7,
        color="#F58518",
        markerfacecolor="#F58518",
        markeredgecolor="white",
        markeredgewidth=0.8,
        label="Capacity utilization",
        zorder=6,
    )
    ax2.set_ylabel("Annual capacity utilization (%)")
    ax2.set_ylim(0, max(55.0, 1.15 * float(np.max(utilization)) if len(utilization) else 55.0))
    ax2.grid(False)
    ax2.legend(handles=[line], loc="upper left", bbox_to_anchor=(0.015, 0.985), frameon=True, framealpha=0.94, edgecolor="0.65")
    fig.subplots_adjust(left=0.12, right=0.88, bottom=0.14, top=0.88)
    return _save(fig, figures_dir, "02_charger_deployment_and_utilization", dpi)


def _prepare_hourly(results_dir: Path) -> pd.DataFrame:
    df = _read_csv(results_dir / "hourly_energy.csv", required=True)
    if df.empty:
        raise ValueError("hourly_energy.csv is empty")
    df["Month"] = pd.Categorical(df["Month"], categories=MONTHS, ordered=True)
    numeric_cols = [c for c in df.columns if c not in {"HexID", "Month", "TimeIndex"}]
    for col in numeric_cols:
        df[col] = _numeric(df[col]).fillna(0.0)
    return df


def _served_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c.startswith("E_") and c.endswith("_kWh_day")]


def _plot_monthly_energy(results_dir: Path, figures_dir: Path, dpi: int) -> list[str]:
    df = _prepare_hourly(results_dir)
    grouped = df.groupby("Month", observed=False)[[
        "Grid_direct_kWh_day", "PV_direct_kWh_day", "Batt_discharge_kWh_day",
        "Grid_batt_kWh_day", "PV_batt_kWh_day",
    ]].sum().reindex(MONTHS).fillna(0.0)
    for month in MONTHS:
        grouped.loc[month] *= MONTH_DAYS[month]
    x = np.arange(12)
    fig, ax = plt.subplots(figsize=(11, 6.4))
    bottom = np.zeros(12)
    for col, label in [
        ("Grid_direct_kWh_day", "Grid to chargers"),
        ("PV_direct_kWh_day", "PV to chargers"),
        ("Batt_discharge_kWh_day", "BESS to chargers"),
    ]:
        vals = grouped[col].to_numpy() / 1e6
        ax.bar(x, vals, bottom=bottom, label=label)
        bottom += vals
    ax.set_xticks(x)
    ax.set_xticklabels([m[:3] for m in MONTHS])
    ax.set_ylabel("Energy supplied (GWh/month)")
    ax.set_title("Monthly charging-energy supply mix")
    handles, labels = ax.get_legend_handles_labels()
    if ax.get_legend() is not None:
        ax.get_legend().remove()
    _boxed_legend_below(fig, handles, labels, ncol=3, bottom=0.20)
    return _save(fig, figures_dir, "03_monthly_energy_supply_mix", dpi)


def _season_weighted_monthly_profile(
    df: pd.DataFrame,
    season: str,
    value_cols: list[str],
    month_col: str = "Month",
    time_col: str = "TimeIndex",
) -> pd.DataFrame:
    months = SEASON_TO_MONTHS[season]
    sub = df[df[month_col].astype(str).isin(months)].copy()
    if sub.empty:
        raise ValueError(f"No data available for {season}")
    for col in value_cols:
        sub[col] = _numeric(sub[col]).fillna(0.0)
    by_month = sub.groupby([month_col, time_col], observed=False)[value_cols].sum().reset_index()
    by_month["_days"] = by_month[month_col].astype(str).map(MONTH_DAYS).astype(float)
    for col in value_cols:
        by_month[col] = by_month[col] * by_month["_days"]
    denominator = float(sum(MONTH_DAYS[m] for m in months))
    out = by_month.groupby(time_col, observed=False)[value_cols].sum().reindex(range(1, 49), fill_value=0.0) / denominator
    return out


def _plot_seasonal_demand_profiles(results_dir: Path, figures_dir: Path, dpi: int) -> list[str]:
    df = _read_csv(results_dir / "supply_by_demand_class.csv", required=True)
    required = ["Month", "TimeIndex", "Demand_home_total_kWh_day", "Demand_public_base_kWh_day"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing seasonal-demand columns: {missing}")

    fig, axes = plt.subplots(2, 2, figsize=(14.5, 9.2), sharex=True, sharey=True)
    x = np.arange(1, 49)
    handles = labels = None
    for ax, season in zip(axes.flat, SEASON_ORDER):
        profile = _season_weighted_monthly_profile(
            df, season, ["Demand_home_total_kWh_day", "Demand_public_base_kWh_day"]
        )
        home = profile["Demand_home_total_kWh_day"].to_numpy() / 1e3
        public = profile["Demand_public_base_kWh_day"].to_numpy() / 1e3
        ax.stackplot(x, home, public, labels=["Home charging demand", "Work + public charging demand"], alpha=0.88)
        ax.plot(x, home + public, linewidth=1.4, label="Total charging demand")
        ax.set_title(f"{season.title()} ({', '.join(m[:3] for m in SEASON_TO_MONTHS[season])})")
        _hour_axis(ax)
        ax.set_ylabel("Energy (MWh per 30-minute slot)")
        if handles is None:
            handles, labels = ax.get_legend_handles_labels()
    fig.suptitle("Seasonal MATSim charging-demand profiles used by the annual optimization", y=0.99)
    _boxed_legend_below(fig, handles or [], labels or [], ncol=3, bottom=0.12)
    fig.subplots_adjust(top=0.91, hspace=0.30, wspace=0.18)
    return _save(fig, figures_dir, "03b_seasonal_charging_demand_profiles", dpi)


def _plot_seasonal_supply_profiles(results_dir: Path, figures_dir: Path, dpi: int) -> list[str]:
    df = _prepare_hourly(results_dir)
    cols = ["Grid_direct_kWh_day", "PV_direct_kWh_day", "Batt_discharge_kWh_day"]
    served_cols = _served_columns(df)
    if served_cols:
        df = df.copy()
        df["_served_total"] = df[served_cols].sum(axis=1)
    else:
        df = df.copy()
        df["_served_total"] = df[cols].sum(axis=1)
    value_cols = cols + ["_served_total"]

    fig, axes = plt.subplots(2, 2, figsize=(14.5, 9.2), sharex=True, sharey=True)
    x = np.arange(1, 49)
    handles = labels = None
    for ax, season in zip(axes.flat, SEASON_ORDER):
        profile = _season_weighted_monthly_profile(df, season, value_cols)
        grid = profile[cols[0]].to_numpy() / 1e3
        pv = profile[cols[1]].to_numpy() / 1e3
        bess = profile[cols[2]].to_numpy() / 1e3
        served = profile["_served_total"].to_numpy() / 1e3
        ax.stackplot(x, grid, pv, bess, labels=["Grid", "Direct stationary PV", "BESS discharge"], alpha=0.88)
        ax.plot(x, served, linewidth=1.4, label="Energy served")
        ax.set_title(f"{season.title()} ({', '.join(m[:3] for m in SEASON_TO_MONTHS[season])})")
        _hour_axis(ax)
        ax.set_ylabel("Energy (MWh per 30-minute slot)")
        if handles is None:
            handles, labels = ax.get_legend_handles_labels()
    fig.suptitle("Seasonal charging-energy supply profiles in the optimized solution", y=0.99)
    _boxed_legend_below(fig, handles or [], labels or [], ncol=4, bottom=0.12)
    fig.subplots_adjust(top=0.91, hspace=0.30, wspace=0.18)
    return _save(fig, figures_dir, "03c_seasonal_energy_supply_profiles", dpi)


def _plot_input_pv_tou_profiles(results_dir: Path, figures_dir: Path, dpi: int) -> list[str]:
    df = _read_csv(results_dir / "input_monthly_profiles.csv", required=True)
    required = ["Month", "TimeIndex", "PV_capacity_factor", "Retail_price_SEK_per_kWh"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing PV/ToU profile columns: {missing}")
    for col in required[2:]:
        df[col] = _numeric(df[col]).fillna(0.0)

    fig, axes = plt.subplots(2, 1, figsize=(11.5, 8.4), sharex=True)
    for month in REPRESENTATIVE_MONTHS:
        sub = df[df["Month"].astype(str) == month].sort_values("TimeIndex")
        if sub.empty:
            continue
        axes[0].plot(sub["TimeIndex"], sub["PV_capacity_factor"], linewidth=1.8, label=month)
        axes[1].plot(sub["TimeIndex"], sub["Retail_price_SEK_per_kWh"], linewidth=1.8, label=month)
    axes[0].set_ylabel("Stationary PV capacity factor")
    axes[0].set_title("Month-specific stationary-PV potential supplied to the optimization")
    axes[1].set_ylabel("Retail grid price (SEK/kWh)")
    axes[1].set_title("Month-specific retail ToU electricity price supplied to the optimization")
    _hour_axis(axes[1])
    axes[0].set_xlim(1, 48)
    handles, labels = axes[0].get_legend_handles_labels()
    _boxed_legend_below(fig, handles, labels, ncol=4, bottom=0.13)
    fig.subplots_adjust(top=0.93, hspace=0.30)
    return _save(fig, figures_dir, "03a_input_pv_tou_profiles", dpi)


def _plot_dispatch_month(df: pd.DataFrame, month: str, figures_dir: Path, dpi: int) -> list[str]:
    sub = df[df["Month"].astype(str) == month]
    if sub.empty:
        raise ValueError(f"No hourly rows for {month}")
    cols = ["Grid_direct_kWh_day", "PV_direct_kWh_day", "Batt_discharge_kWh_day"]
    agg = sub.groupby("TimeIndex")[cols].sum().reindex(range(1, 49), fill_value=0.0)
    served_cols = _served_columns(sub)
    served = sub.groupby("TimeIndex")[served_cols].sum().sum(axis=1).reindex(range(1, 49), fill_value=0.0) if served_cols else agg.sum(axis=1)
    x = np.arange(1, 49)
    fig, ax = plt.subplots(figsize=(10.8, 6.1))
    ax.stackplot(x, agg[cols[0]], agg[cols[1]], agg[cols[2]], labels=["Grid", "Direct PV", "BESS discharge"], alpha=0.85)
    ax.plot(x, served.to_numpy(), linewidth=1.8, label="Energy served")
    _hour_axis(ax)
    ax.set_ylabel("Energy (kWh per 30-minute slot)")
    ax.set_title(f"{month}: aggregate charging-energy dispatch")
    handles, labels = ax.get_legend_handles_labels()
    if ax.get_legend() is not None:
        ax.get_legend().remove()
    _boxed_legend_below(fig, handles, labels, ncol=4, bottom=0.21)
    return _save(fig, figures_dir, f"04_dispatch_{month.lower()}", dpi)


def _plot_soc_by_month(results_dir: Path, figures_dir: Path, dpi: int) -> list[str]:
    hourly = _prepare_hourly(results_dir)
    infra = _read_csv(results_dir / "infrastructure_by_hex.csv", required=True)
    if "Battery_units" not in infra.columns:
        raise ValueError("Battery_units is missing from infrastructure_by_hex.csv")
    infra["Battery_units"] = _numeric(infra["Battery_units"]).fillna(0.0)
    hourly = hourly.merge(infra[["HexID", "Battery_units"]], on="HexID", how="left")
    hourly = hourly[hourly["Battery_units"] > 0].copy()
    if hourly.empty:
        raise ValueError("No installed BESS units")
    hourly["SOC_per_unit_kWh"] = hourly["SOC_end_kWh"] / hourly["Battery_units"]
    pivot = hourly.groupby(["TimeIndex", "Month"], observed=False)["SOC_per_unit_kWh"].mean().unstack("Month").reindex(index=range(1, 49), columns=MONTHS)
    fig, ax = plt.subplots(figsize=(11, 6.8))
    for month in MONTHS:
        if month in pivot and pivot[month].notna().any():
            ax.plot(pivot.index, pivot[month], linewidth=1.25, label=month[:3])
    _hour_axis(ax)
    ax.set_ylabel("Mean BESS state of charge (kWh per installed unit)")
    ax.set_title("Mean BESS state of charge by representative month")
    handles, labels = ax.get_legend_handles_labels()
    if ax.get_legend() is not None:
        ax.get_legend().remove()
    _boxed_legend_below(fig, handles, labels, ncol=6, bottom=0.24)
    return _save(fig, figures_dir, "05_bess_soc_by_month", dpi)


def _plot_battery_operation_month(df: pd.DataFrame, month: str, figures_dir: Path, dpi: int, results_dir: Path | None = None) -> list[str]:
    sub = df[df["Month"].astype(str) == month].copy()
    if sub.empty:
        raise ValueError(f"No hourly rows for {month}")
    if results_dir is None:
        raise ValueError("Results directory is required for BESS-unit normalization")
    infra = _read_csv(results_dir / "infrastructure_by_hex.csv", required=True)
    if "Battery_units" not in infra.columns:
        raise ValueError("Battery_units is missing from infrastructure_by_hex.csv")
    infra = infra[["HexID", "Battery_units"]].copy()
    infra["Battery_units"] = _numeric(infra["Battery_units"]).fillna(0.0)
    sub = sub.merge(infra, on="HexID", how="left")
    sub = sub[sub["Battery_units"] > 0].copy()
    if sub.empty:
        raise ValueError(f"No installed BESS units in {month}")

    sub["PV_charge_per_unit"] = sub["PV_batt_kWh_day"] / sub["Battery_units"]
    sub["Grid_charge_per_unit"] = sub["Grid_batt_kWh_day"] / sub["Battery_units"]
    sub["Discharge_per_unit"] = sub["Batt_discharge_kWh_day"] / sub["Battery_units"]
    sub["SOC_per_unit"] = sub["SOC_end_kWh"] / sub["Battery_units"]

    grp = sub.groupby("TimeIndex")
    stats = pd.DataFrame({
        "mean_pv": grp["PV_charge_per_unit"].mean(),
        "sem_pv": grp["PV_charge_per_unit"].apply(_sem),
        "mean_grid": grp["Grid_charge_per_unit"].mean(),
        "sem_grid": grp["Grid_charge_per_unit"].apply(_sem),
        "mean_discharge": grp["Discharge_per_unit"].mean(),
        "sem_discharge": grp["Discharge_per_unit"].apply(_sem),
        "mean_soc": grp["SOC_per_unit"].mean(),
        "sem_soc": grp["SOC_per_unit"].apply(_sem),
    }).reindex(range(1, 49), fill_value=0.0)
    if float(stats[["mean_pv", "mean_grid", "mean_discharge"]].to_numpy().sum()) <= 1e-9:
        raise ValueError(f"No BESS operation in {month}")

    x = stats.index.to_numpy(dtype=float)
    fig, ax1 = plt.subplots(figsize=(11.5, 7.4))
    ax2 = ax1.twinx()
    ax1.bar(x, stats["mean_pv"], yerr=stats["sem_pv"], label="PV charge per BESS unit", alpha=0.82, capsize=2.5)
    ax1.bar(x, stats["mean_grid"], bottom=stats["mean_pv"], yerr=stats["sem_grid"], label="Grid charge per BESS unit", alpha=0.82, capsize=2.5)
    ax1.bar(x, -stats["mean_discharge"], yerr=stats["sem_discharge"], label="Discharge per BESS unit", alpha=0.82, capsize=2.5)

    for _, trace in sub.sort_values("TimeIndex").groupby("HexID"):
        ax2.plot(trace["TimeIndex"], trace["SOC_per_unit"], linewidth=0.45, alpha=0.12, color="grey")
    ax2.plot(x, stats["mean_soc"], color="red", linewidth=2.0, linestyle="--", label="Mean SoC per BESS unit")
    ax2.fill_between(x, stats["mean_soc"] - stats["sem_soc"], stats["mean_soc"] + stats["sem_soc"], color="red", alpha=0.14)
    ax2.plot([], [], color="grey", linewidth=0.7, alpha=0.5, label="Cell-level SoC traces")

    ax1.axhline(0, color="black", linewidth=0.8)
    ax1.set_xlim(0.4, 48.6)
    ax1.set_xticks(np.arange(1, 49, 4))
    ax1.set_xlabel("30-minute time-interval slots (1–48)")
    ax1.set_ylabel("Mean charge/discharge (kWh per BESS unit per 30-minute slot)")
    ax2.set_ylabel("State of charge (kWh per BESS unit)")
    ax2.grid(False)
    ax1.set_title(f"{month}: BESS operation across cells with installed storage")
    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    _boxed_legend_below(fig, h1 + h2, l1 + l2, ncol=3, bottom=0.25)
    return _save(fig, figures_dir, f"06_bess_operation_{month.lower()}", dpi)


def _plot_demand_supply_balance(results_dir: Path, figures_dir: Path, dpi: int) -> list[str]:
    df = _read_csv(results_dir / "supply_by_demand_class.csv", required=True)
    if df.empty:
        raise ValueError("supply_by_demand_class.csv is empty")
    required = [
        "Month", "TimeIndex", "DaysInMonth",
        "Demand_home_total_kWh_day", "Demand_public_base_kWh_day",
        "Home_private_served_kWh_day",
        "Grid_to_home_residual_allocated_kWh_day",
        "PV_to_home_residual_allocated_kWh_day",
        "BESS_to_home_residual_allocated_kWh_day",
        "Grid_to_public_allocated_kWh_day",
        "PV_to_public_allocated_kWh_day",
        "BESS_to_public_allocated_kWh_day",
        "Slack_home_kWh_day", "Slack_public_kWh_day",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing supply-accounting columns: {missing}")
    for col in required[1:]:
        df[col] = _numeric(df[col]).fillna(0.0)

    weighted_cols = [c for c in required if c not in {"Month", "TimeIndex", "DaysInMonth"}]
    for col in weighted_cols:
        df[col] = df[col] * df["DaysInMonth"]
    annual = df.groupby("TimeIndex")[weighted_cols].sum().reindex(range(1, 49), fill_value=0.0) / 365.0
    x = np.arange(1, 49)

    fig, ax = plt.subplots(figsize=(15.5, 8.5))
    positive_bottom = np.zeros(48)
    for col, label in [
        ("Demand_home_total_kWh_day", "Home demand"),
        ("Demand_public_base_kWh_day", "Public demand (work + public)"),
    ]:
        vals = annual[col].to_numpy() / 1e3
        ax.bar(x, vals, bottom=positive_bottom, label=label, width=0.82)
        positive_bottom += vals

    negative_bottom = np.zeros(48)
    negative_series = [
        ("Home_private_served_kWh_day", "Home chargers (private)"),
        ("Grid_to_home_residual_allocated_kWh_day", "Residual home via public chargers: grid"),
        ("PV_to_home_residual_allocated_kWh_day", "Residual home via public chargers: PV"),
        ("BESS_to_home_residual_allocated_kWh_day", "Residual home via public chargers: BESS"),
        ("Grid_to_public_allocated_kWh_day", "Public demand: grid"),
        ("PV_to_public_allocated_kWh_day", "Public demand: PV"),
        ("BESS_to_public_allocated_kWh_day", "Public demand: BESS"),
    ]
    slack = annual["Slack_home_kWh_day"].to_numpy() + annual["Slack_public_kWh_day"].to_numpy()
    if float(np.max(slack)) > 1e-8:
        negative_series.append(("_slack_total", "Unserved demand (slack)"))
        annual["_slack_total"] = slack
    for col, label in negative_series:
        vals = annual[col].to_numpy() / 1e3
        ax.bar(x, -vals, bottom=-negative_bottom, label=label, width=0.82)
        negative_bottom += vals

    ax.axhline(0, color="black", linewidth=1.0)
    ax.set_xlim(0.4, 48.6)
    ax.set_xticks(np.arange(1, 49, 2))
    ax.set_xlabel("Time of day (30-minute interval: 1–48)")
    ax.set_ylabel("Annual weighted-average representative-day energy (MWh per 30-minute slot)")
    ax.set_title("Charging demand and supply balance by demand class and energy source", pad=18)
    ax.text(0.5, 1.005, "Supply-source attribution across demand classes is a proportional ex-post allocation; source totals and class totals are preserved.", transform=ax.transAxes, ha="center", va="bottom", fontsize=9, color="0.35", style="italic")
    handles, labels = ax.get_legend_handles_labels()
    _boxed_legend_below(fig, handles, labels, ncol=3, bottom=0.27)
    return _save(fig, figures_dir, "16_demand_supply_balance_annual_average", dpi)


def _plot_redirection_heatmap(results_dir: Path, figures_dir: Path, dpi: int) -> list[str]:
    df = _read_csv(results_dir / "redirections.csv")
    if df.empty:
        raise ValueError("No positive redirection flows")
    df["Energy_kWh_day"] = _numeric(df["Energy_kWh_day"]).fillna(0.0)
    pivot = df.groupby(["Month", "TimeIndex"])["Energy_kWh_day"].sum().unstack("TimeIndex").reindex(index=MONTHS, columns=range(1, 49), fill_value=0.0)
    fig, ax = plt.subplots(figsize=(12, 5.2))
    image = ax.imshow(pivot.to_numpy(), aspect="auto", interpolation="nearest")
    ax.set_yticks(range(12))
    ax.set_yticklabels([m[:3] for m in MONTHS])
    ticks = np.arange(0, 48, 4)
    ax.set_xticks(ticks)
    ax.set_xticklabels([f"{t / 2:.0f}:00" for t in ticks])
    ax.set_xlabel("Time of representative day")
    ax.set_ylabel("Month")
    ax.set_title("Aggregate redirected energy by month and time")
    cbar = fig.colorbar(image, ax=ax)
    cbar.set_label("Redirected energy (kWh per representative day slot)")
    return _save(fig, figures_dir, "07_redirection_month_time_heatmap", dpi)


def _plot_redirection_type_matrix(results_dir: Path, figures_dir: Path, dpi: int) -> list[str]:
    df = _read_csv(results_dir / "redirections_by_type.csv")
    if df.empty:
        raise ValueError("No type-pair redirection reconstruction")
    df["Energy_kWh_annual"] = _numeric(df["Energy_kWh_annual"]).fillna(0.0)
    types = ["slow", "medium", "fast"]
    pivot = df.pivot_table(index="OriginType", columns="DestinationType", values="Energy_kWh_annual", aggfunc="sum", fill_value=0.0).reindex(index=types, columns=types, fill_value=0.0) / 1e3
    fig, ax = plt.subplots(figsize=(6.5, 5.5))
    image = ax.imshow(pivot.to_numpy(), interpolation="nearest")
    ax.set_xticks(range(3)); ax.set_xticklabels([v.capitalize() for v in types])
    ax.set_yticks(range(3)); ax.set_yticklabels([v.capitalize() for v in types])
    ax.set_xlabel("Destination charger type")
    ax.set_ylabel("Origin tariff-reference type")
    ax.set_title("Annual type-aware redirection matrix")
    for r in range(3):
        for c in range(3):
            ax.text(c, r, f"{pivot.iloc[r, c]:,.1f}", ha="center", va="center")
    cbar = fig.colorbar(image, ax=ax)
    cbar.set_label("Redirected energy (MWh/year)")
    return _save(fig, figures_dir, "08_redirection_type_matrix", dpi)


def _find_history(run_dir: Path) -> Path | None:
    candidates = [
        run_dir / "results" / "lbbd_history.csv",
        run_dir / "results" / "alternative_c_history.csv",
        run_dir / "iterations" / "lbbd_iteration_history.csv",
        run_dir / "results" / "lbbd_iteration_history.csv",
    ]
    return next((p for p in candidates if p.exists()), None)


def _first_present(df: pd.DataFrame, names: list[str]) -> str | None:
    return next((name for name in names if name in df.columns), None)



def _compact_number(value: float, unit: str = "") -> str:
    if value is None or not np.isfinite(value):
        return "n/a"
    abs_value = abs(float(value))
    if abs_value >= 1e6:
        return f"{value / 1e6:.3f}M{unit}"
    if abs_value >= 1e3:
        return f"{value / 1e3:.1f}k{unit}"
    if abs_value >= 10:
        return f"{value:.1f}{unit}"
    return f"{value:.3g}{unit}"


def _annotate_xy(
    ax: plt.Axes,
    x_value: float,
    y_value: float,
    label: str,
    *,
    color: str = "0.20",
    xytext: tuple[int, int] = (0, 8),
    fontsize: int = 8,
    ha: str = "center",
) -> None:
    if not np.isfinite(x_value) or not np.isfinite(y_value):
        return
    ax.annotate(
        label,
        (x_value, y_value),
        xytext=xytext,
        textcoords="offset points",
        ha=ha,
        va="bottom" if xytext[1] >= 0 else "top",
        fontsize=fontsize,
        color=color,
        bbox=dict(boxstyle="round,pad=0.18", fc="white", ec="0.75", alpha=0.86),
    )


def _annotate_selected_points(
    ax: plt.Axes,
    x_values: pd.Series | np.ndarray,
    y_values: pd.Series | np.ndarray,
    formatter: Callable[[float], str],
    *,
    color: str = "0.20",
    every: bool = False,
    final: bool = True,
    max_points: int = 8,
    fontsize: int = 8,
) -> None:
    xs = np.asarray(x_values, dtype=float)
    ys = np.asarray(y_values, dtype=float)
    valid = [k for k, (x, y) in enumerate(zip(xs, ys)) if np.isfinite(x) and np.isfinite(y)]
    if not valid:
        return
    if every and len(valid) <= max_points:
        selected = valid
    else:
        selected = sorted(set([valid[0], valid[-1]] + ([int(valid[np.nanargmax(ys[valid])])] if len(valid) else [])))
    if final and valid[-1] not in selected:
        selected.append(valid[-1])
    for offset_idx, k in enumerate(selected):
        y_offset = 9 if offset_idx % 2 == 0 else -14
        _annotate_xy(
            ax,
            float(xs[k]),
            float(ys[k]),
            formatter(float(ys[k])),
            color=color,
            xytext=(0, y_offset),
            fontsize=fontsize,
        )


def _lbbd_cut_columns(df: pd.DataFrame) -> list[tuple[str, str]]:
    return [
        ("hall_profit_cuts_added", "Hall/min-cut"),
        ("component_lp_cuts_added", "Component LP"),
        ("annual_lp_cut_added", "Annual LP"),
        ("annual_core_cut_added", "Core-point LP"),
        ("exact_config_cut_added", "Exact configuration"),
        ("partial_logic_cuts_added", "Partial logic"),
    ]


def _sum_columns(df: pd.DataFrame, columns: list[str]) -> pd.Series:
    present = [col for col in columns if col in df.columns]
    if not present:
        return pd.Series(0.0, index=df.index)
    return sum((_numeric(df[col]).fillna(0.0) for col in present), start=pd.Series(0.0, index=df.index))

def _plot_decomposition_convergence(run_dir: Path, figures_dir: Path, dpi: int) -> list[str]:
    path = _find_history(run_dir)
    if path is None:
        raise ValueError("No decomposition iteration history")
    df = _read_csv(path, required=True)
    if df.empty or "iteration" not in df.columns:
        raise ValueError("Decomposition iteration history is empty")
    method = "LBBD"
    iteration = _numeric(df["iteration"])
    ub_col = _first_present(df, ["global_best_UB_SEK", "global_ub_SEK", "master_best_bound_UB_SEK", "master_bound_SEK"])
    lb_col = _first_present(df, ["best_LB_SEK", "best_lb_SEK"])
    gap_col = _first_present(df, ["lbbd_gap"])
    if ub_col is None or lb_col is None:
        raise ValueError("Decomposition history lacks upper/lower-bound columns")
    ub = _numeric(df[ub_col]) / 1e6
    lb = _numeric(df[lb_col]) / 1e6
    fig, ax = plt.subplots(figsize=(9.8, 6.2))
    upper_line, = ax.plot(iteration, ub, marker="o", linewidth=1.8, label="Global master upper bound")
    lower_line, = ax.plot(iteration, lb, marker="o", linewidth=1.8, label="Best certified lower bound")
    ax.set_xlabel(f"{method} iteration")
    ax.set_ylabel("Objective bound (million SEK/year)")
    ax.set_title(f"{method} convergence")
    handles, labels = [upper_line, lower_line], ["Global master upper bound", "Best certified lower bound"]
    if gap_col is not None:
        ax2 = ax.twinx()
        gap_values = 100 * _numeric(df[gap_col])
        gap_line, = ax2.plot(iteration, gap_values, linestyle="--", linewidth=1.8, marker=".", markersize=5, label=f"Certified {method} gap")
        finite_gap = gap_values[np.isfinite(gap_values)]
        if len(finite_gap):
            ax2.set_ylim(0, max(0.01, 1.22 * float(finite_gap.max())))
        ax2.set_ylabel(f"Certified {method} gap (%)")
        ax2.grid(False)
        for k, (x_value, gap) in enumerate(zip(iteration, gap_values)):
            if not np.isfinite(gap):
                continue
            label = f"{gap:.4f}%" if gap < 0.1 else f"{gap:.3f}%"
            offset = 8 if k % 2 == 0 else -13
            ax2.annotate(label, (x_value, gap), xytext=(0, offset), textcoords="offset points", ha="center", va="bottom" if offset > 0 else "top", fontsize=8, color=gap_line.get_color())
        handles.append(gap_line)
        labels.append(f"Certified {method} gap")
    _boxed_legend_below(fig, handles, labels, ncol=3, bottom=0.23)
    return _save(fig, figures_dir, "09_decomposition_convergence", dpi)


def _plot_decomposition_cut_generation(run_dir: Path, figures_dir: Path, dpi: int) -> list[str]:
    path = _find_history(run_dir)
    if path is None:
        raise ValueError("No decomposition iteration history")
    df = _read_csv(path, required=True)
    if df.empty or "iteration" not in df.columns:
        raise ValueError("Decomposition history lacks iteration data")
    method = "LBBD"
    iteration = _numeric(df["iteration"]).astype(int)

    cut_families = _lbbd_cut_columns(df)
    added_columns = [col for col, _ in cut_families]
    cuts = _sum_columns(df, added_columns)
    cumulative = cuts.cumsum()
    x = np.arange(len(iteration))

    # LBBD-specific view: the important question is not just how many cuts were
    # added, but whether the LP/core-point oracles actually found violated cuts.
    annual_violation = _numeric(df["annual_lp_violation_SEK"]).fillna(0.0) / 1e3 if "annual_lp_violation_SEK" in df.columns else pd.Series(0.0, index=df.index)
    core_violation = _numeric(df["annual_core_violation_at_candidate_SEK"]).fillna(0.0) / 1e3 if "annual_core_violation_at_candidate_SEK" in df.columns else pd.Series(0.0, index=df.index)
    partial_violated = _numeric(df["partial_logic_cuts_violated"]).fillna(0.0) if "partial_logic_cuts_violated" in df.columns else pd.Series(0.0, index=df.index)
    comp_violated = _numeric(df["component_lp_cuts_violated"]).fillna(0.0) if "component_lp_cuts_violated" in df.columns else pd.Series(0.0, index=df.index)

    fig, (ax_top, ax_bottom) = plt.subplots(
        2, 1, figsize=(11.2, 8.0), sharex=True,
        gridspec_kw={"height_ratios": [1.0, 1.15]},
    )

    bars = ax_top.bar(x, cuts, width=0.62, label="Cuts accepted into master", alpha=0.88)
    ax_top.bar_label(bars, labels=[f"{int(v)}" if v > 0 else "0" for v in cuts], padding=2, fontsize=8)
    ax_top.set_ylabel("Accepted cuts")
    ax_top.set_title("LBBD cut generation: accepted cuts and separation diagnostics")
    ax_top.set_ylim(0, max(1.0, 1.30 * float(max(cuts.max(), 1.0))))
    ax_top2 = ax_top.twinx()
    cum_line, = ax_top2.plot(x, cumulative, marker="o", linewidth=2.1, label="Cumulative cuts")
    ax_top2.set_ylabel("Cumulative accepted cuts")
    ax_top2.set_ylim(0, max(1.0, 1.25 * float(max(cumulative.max(), 1.0))))
    ax_top2.grid(False)
    _annotate_selected_points(ax_top2, x, cumulative.to_numpy(dtype=float), lambda y: f"cum {int(round(y))}", color=cum_line.get_color(), every=True)

    ann_line, = ax_bottom.plot(x, annual_violation, marker="o", linewidth=1.8, label="Candidate annual-LP violation (kSEK)")
    core_line, = ax_bottom.plot(x, core_violation, marker="s", linestyle="--", linewidth=1.8, label="Core-point annual-LP violation at candidate (kSEK)")
    ax_bottom.axhline(0, linewidth=1.0, color="0.30")
    ax_bottom.set_ylabel("Violation before filtering (kSEK)")
    ax_bottom.set_xlabel("LBBD iteration")
    ax_bottom.set_xticks(x)
    ax_bottom.set_xticklabels(iteration.astype(str))
    _annotate_selected_points(ax_bottom, x, annual_violation.to_numpy(dtype=float), lambda y: f"{y:.1f}", color=ann_line.get_color(), every=True)
    _annotate_selected_points(ax_bottom, x, core_violation.to_numpy(dtype=float), lambda y: f"{y:.1f}", color=core_line.get_color(), every=True)

    ax_count = ax_bottom.twinx()
    violated_total = comp_violated + partial_violated
    if float(violated_total.max()) > 0:
        vio_line, = ax_count.step(x, violated_total, where="mid", linewidth=1.6, label="Violated component/logic cuts")
        ax_count.set_ylabel("Violated discrete cuts")
        ax_count.set_ylim(0, 1.20 * float(violated_total.max()))
        ax_count.grid(False)
        extra_handles = [vio_line]
        extra_labels = ["Violated component/logic cuts"]
    else:
        extra_handles, extra_labels = [], []
        ax_count.set_yticks([])

    handles1, labels1 = ax_top.get_legend_handles_labels()
    handles2, labels2 = ax_top2.get_legend_handles_labels()
    handles3, labels3 = ax_bottom.get_legend_handles_labels()
    _boxed_legend_below(
        fig,
        handles1 + handles2 + handles3 + extra_handles,
        labels1 + labels2 + labels3 + extra_labels,
        ncol=2,
        bottom=0.24,
    )
    if float(cuts.sum()) <= 3 and float((annual_violation > 1e-6).sum()) == 0:
        fig.text(
            0.50, 0.965,
            "Only exact-configuration cuts were accepted; LP/core violations were zero or negative at the tested candidates.",
            ha="center", va="top", fontsize=9,
            bbox=dict(boxstyle="round,pad=0.25", fc="#FFF8DC", ec="0.70", alpha=0.95),
        )
    return _save(fig, figures_dir, "17_decomposition_cut_generation", dpi)



def _load_lbbd_history(run_dir: Path) -> pd.DataFrame:
    path = _find_history(run_dir)
    if path is None:
        raise ValueError("No LBBD iteration history")
    df = _read_csv(path, required=True)
    if df.empty or "iteration" not in df.columns:
        raise ValueError("Run does not contain LBBD iteration history")
    return df.copy()


def _plot_lbbd_cut_families(run_dir: Path, figures_dir: Path, dpi: int) -> list[str]:
    df = _load_lbbd_history(run_dir)
    families = [(column, label) for column, label in _lbbd_cut_columns(df) if column in df.columns]
    if not families:
        raise ValueError("LBBD history lacks cut-family columns")
    iteration = _numeric(df["iteration"]).astype(int).to_numpy()
    matrix = pd.DataFrame({label: _numeric(df[column]).fillna(0.0).to_numpy(dtype=float) for column, label in families}, index=iteration)
    totals = matrix.sum(axis=0)
    if float(totals.sum()) <= 0:
        raise ValueError("No LBBD cuts were added")

    fig, (ax_left, ax_right) = plt.subplots(1, 2, figsize=(13.8, 5.9), gridspec_kw={"width_ratios": [0.95, 1.55]})

    y = np.arange(len(totals))
    bars = ax_left.barh(y, totals.to_numpy(dtype=float), height=0.62)
    ax_left.set_yticks(y)
    ax_left.set_yticklabels(totals.index)
    ax_left.set_xlabel("Total cuts accepted")
    ax_left.set_title("Total cuts by family")
    max_total = max(1.0, float(totals.max()))
    ax_left.set_xlim(0, 1.25 * max_total)
    for bar, value in zip(bars, totals):
        label = f"{int(value)}" if value > 0 else "0"
        ax_left.text(bar.get_width() + 0.03 * max_total, bar.get_y() + bar.get_height() / 2, label, va="center", fontsize=9)

    image = ax_right.imshow(matrix.T.to_numpy(dtype=float), aspect="auto", interpolation="nearest")
    ax_right.set_yticks(np.arange(len(matrix.columns)))
    ax_right.set_yticklabels(matrix.columns)
    ax_right.set_xticks(np.arange(len(iteration)))
    ax_right.set_xticklabels(iteration.astype(str))
    ax_right.set_xlabel("LBBD iteration")
    ax_right.set_title("Cut-family activity by iteration")
    for row in range(matrix.shape[1]):
        for col in range(matrix.shape[0]):
            value = matrix.iloc[col, row]
            if value > 0:
                ax_right.text(col, row, f"{int(value)}", ha="center", va="center", fontsize=8, color="white" if value >= max_total / 2 else "black")
    cbar = fig.colorbar(image, ax=ax_right, fraction=0.045, pad=0.03)
    cbar.set_label("Cuts accepted")

    if float(totals.drop(labels=["Exact configuration"], errors="ignore").sum()) <= 0 and "Exact configuration" in totals.index:
        fig.text(
            0.50, 0.015,
            "Interpretation: this run closed almost entirely through the embedded relaxation and exact configuration cuts; other cut families were available but not violated enough to be inserted.",
            ha="center", va="bottom", fontsize=9,
            bbox=dict(boxstyle="round,pad=0.25", fc="#FFF8DC", ec="0.70", alpha=0.95),
        )
        fig.subplots_adjust(bottom=0.17)
    else:
        fig.subplots_adjust(bottom=0.11)
    return _save(fig, figures_dir, "18_lbbd_cut_families", dpi)



def _plot_lbbd_candidate_bounds(run_dir: Path, figures_dir: Path, dpi: int) -> list[str]:
    df = _load_lbbd_history(run_dir)
    iteration = _numeric(df["iteration"])
    exact_col = "candidate_exact_objective_SEK"
    if exact_col not in df.columns or not _numeric(df[exact_col]).notna().any():
        raise ValueError("LBBD history lacks exact candidate objectives")
    exact = _numeric(df[exact_col])
    series = [
        ("master_eta_SEK", "Master candidate value"),
        ("annual_lp_upper_SEK", "Annual LP upper estimate"),
        ("candidate_fixed_upper_bound_SEK", "Fixed-layout MIP upper bound"),
        ("candidate_exact_objective_SEK", "Fixed-layout feasible objective"),
    ]
    present = [(column, label) for column, label in series if column in df.columns and _numeric(df[column]).notna().any()]
    if len(present) < 2:
        raise ValueError("LBBD history lacks candidate-bound diagnostics")

    fig, (ax_top, ax_bottom) = plt.subplots(2, 1, figsize=(11.4, 8.2), sharex=True, gridspec_kw={"height_ratios": [1.15, 0.95]})
    for column, label in present:
        values = _numeric(df[column]) / 1e6
        line, = ax_top.plot(iteration, values, marker="o", linewidth=1.8, label=label)
        if column == exact_col:
            _annotate_selected_points(ax_top, iteration, values, lambda y: f"{y:.3f} MSEK", color=line.get_color(), every=True)
    ax_top.margins(x=0.08, y=0.22)
    ax_top.set_ylabel("Candidate value (million SEK/year)")
    ax_top.set_title("LBBD candidate evaluation: relaxation values versus exact recourse", pad=12)

    exact_values = exact.to_numpy(dtype=float)
    for column, label in present:
        if column == exact_col:
            continue
        diff = (_numeric(df[column]).to_numpy(dtype=float) - exact_values) / 1e3
        line, = ax_bottom.plot(iteration, diff, marker="o", linewidth=1.8, label=f"{label} − exact objective")
        _annotate_selected_points(ax_bottom, iteration, diff, lambda y: f"{y:+.1f} kSEK", color=line.get_color(), every=False)
    ax_bottom.axhline(0, linewidth=1.0, color="0.25")
    ax_bottom.margins(x=0.08, y=0.25)
    ax_bottom.set_xlabel("LBBD iteration")
    ax_bottom.set_ylabel("Difference from exact objective (kSEK/year)")
    ax_bottom.set_title("Relaxation/certification error at each evaluated infrastructure")

    handles1, labels1 = ax_top.get_legend_handles_labels()
    handles2, labels2 = ax_bottom.get_legend_handles_labels()
    _boxed_legend_below(fig, handles1 + handles2, labels1 + labels2, ncol=2, bottom=0.28)
    return _save(fig, figures_dir, "19_lbbd_candidate_bounds", dpi)



def _plot_lbbd_infrastructure_evolution(run_dir: Path, figures_dir: Path, dpi: int) -> list[str]:
    df = _load_lbbd_history(run_dir)
    columns = [("slow", "Slow"), ("medium", "Medium"), ("fast", "Fast"), ("PV", "PV"), ("BESS", "BESS")]
    present = [(column, label) for column, label in columns if column in df.columns]
    if not present:
        raise ValueError("LBBD history lacks infrastructure counts")
    iteration = _numeric(df["iteration"])
    fig, ax = plt.subplots(figsize=(10.7, 6.2))
    for column, label in present:
        values = _numeric(df[column]).astype(float)
        first_valid = values.dropna()
        if first_valid.empty:
            continue
        base = float(first_valid.iloc[0])
        if abs(base) > 1e-12:
            indexed = 100.0 * (values / base - 1.0)
            axis_label = "Change from first master candidate (%)"
        else:
            indexed = values
            axis_label = "Installed units"
        final = values.dropna().iloc[-1]
        ax.plot(iteration, indexed, marker="o", linewidth=1.8, label=f"{label} (final {final:,.0f})")
    ax.axhline(0, linewidth=0.8, color="0.25")
    ax.set_xlabel("LBBD iteration")
    ax.set_ylabel(axis_label)
    ax.set_title("LBBD infrastructure-candidate evolution")
    handles, labels = ax.get_legend_handles_labels()
    _boxed_legend_below(fig, handles, labels, ncol=3, bottom=0.24)
    return _save(fig, figures_dir, "20_lbbd_infrastructure_evolution", dpi)


def _plot_lbbd_iteration_timing(run_dir: Path, figures_dir: Path, dpi: int) -> list[str]:
    df = _load_lbbd_history(run_dir)
    if "master_solve_seconds" not in df.columns or "elapsed_seconds" not in df.columns:
        raise ValueError("LBBD history lacks timing diagnostics")
    iteration = _numeric(df["iteration"]).astype(int).to_numpy()
    master = _numeric(df["master_solve_seconds"]).fillna(0.0).to_numpy(dtype=float)
    elapsed = _numeric(df["elapsed_seconds"]).ffill().fillna(0.0).to_numpy(dtype=float)
    iteration_total = np.diff(np.concatenate(([0.0], elapsed)))
    other = np.maximum(0.0, iteration_total - master)
    x = np.arange(len(iteration))
    fig, ax = plt.subplots(figsize=(10.6, 6.3))
    ax.bar(x, master / 60.0, label="Master solve", width=0.72)
    ax.bar(x, other / 60.0, bottom=master / 60.0, label="Oracles, cuts and export", width=0.72)
    ax.set_xticks(x)
    ax.set_xticklabels(iteration.astype(str))
    ax.set_xlabel("LBBD iteration")
    ax.set_ylabel("Iteration time (minutes)")
    ax.set_title("LBBD iteration runtime composition")
    ax2 = ax.twinx()
    line, = ax2.plot(x, elapsed / 60.0, marker="o", linewidth=2.0, linestyle="--", label="Cumulative runtime")
    ax2.set_ylabel("Cumulative runtime (minutes)")
    ax2.grid(False)
    h1, l1 = ax.get_legend_handles_labels()
    _boxed_legend_below(fig, h1 + [line], l1 + ["Cumulative runtime"], ncol=3, bottom=0.23)
    return _save(fig, figures_dir, "21_lbbd_iteration_timing", dpi)


def _plot_lbbd_gap_diagnostics(run_dir: Path, figures_dir: Path, dpi: int) -> list[str]:
    df = _load_lbbd_history(run_dir)
    iteration = _numeric(df["iteration"])
    series = [
        ("lbbd_gap", "Certified global gap"),
        ("master_internal_gap", "Master solve gap"),
        ("candidate_fixed_gap", "Fixed-layout MIP gap"),
    ]
    present = [(column, label) for column, label in series if column in df.columns and _numeric(df[column]).notna().any()]
    if not present:
        raise ValueError("LBBD history lacks gap diagnostics")
    fig, ax = plt.subplots(figsize=(10.2, 6.1))
    for column, label in present:
        values = 100.0 * _numeric(df[column])
        values = values.where(values > 0)
        ax.semilogy(iteration, values, marker="o", linewidth=1.8, label=label)
    ax.set_xlabel("LBBD iteration")
    ax.set_ylabel("Gap (%) — logarithmic scale")
    ax.set_title("LBBD global, master and fixed-layout gap diagnostics")
    handles, labels = ax.get_legend_handles_labels()
    _boxed_legend_below(fig, handles, labels, ncol=3, bottom=0.23)
    return _save(fig, figures_dir, "22_lbbd_gap_diagnostics", dpi)


def _plot_lbbd_adaptive_master_control(run_dir: Path, figures_dir: Path, dpi: int) -> list[str]:
    df = _load_lbbd_history(run_dir)
    required = {"iteration", "lbbd_gap", "master_gap_requested"}
    if not required.issubset(df.columns):
        raise ValueError("LBBD history lacks adaptive master-gap diagnostics")
    iteration = _numeric(df["iteration"])
    certified = 100.0 * _numeric(df["lbbd_gap"])
    requested = 100.0 * _numeric(df["master_gap_requested"])
    master_actual = (
        100.0 * _numeric(df["master_internal_gap"])
        if "master_internal_gap" in df.columns else pd.Series(np.nan, index=df.index)
    )

    fig, ax = plt.subplots(figsize=(11.0, 6.7))
    plotted = []
    for values, label, style in [
        (certified, "Certified LBBD gap", "-"),
        (requested, "Requested trial-master gap", "--"),
        (master_actual, "Achieved master gap", ":"),
    ]:
        positive = values.where(values > 0)
        if positive.notna().any():
            line, = ax.semilogy(iteration, positive, marker="o", linewidth=1.9, linestyle=style, label=label)
            plotted.append((line, positive, label))
            _annotate_selected_points(ax, iteration, positive, lambda y: f"{y:.4f}%", color=line.get_color(), every=True, max_points=7)
    plotted_values = pd.concat([certified, requested, master_actual], axis=0).dropna()
    plotted_values = plotted_values[plotted_values > 0]
    if not plotted_values.empty:
        ax.set_ylim(float(plotted_values.min()) / 1.55, float(plotted_values.max()) * 1.85)
    ax.margins(x=0.07)
    ax.set_xlabel("LBBD iteration")
    ax.set_ylabel("Gap (%) — logarithmic scale")
    ax.set_title("Adaptive LBBD master-gap control", pad=12)

    handles, labels = ax.get_legend_handles_labels()
    if "candidate_repeat_count" in df.columns:
        ax2 = ax.twinx()
        repeats = _numeric(df["candidate_repeat_count"]).fillna(0.0)
        repeat_line, = ax2.step(
            iteration, repeats, where="mid", linewidth=1.6,
            label="Consecutive repeated candidate count",
        )
        ax2.set_ylabel("Repeated-candidate count")
        ax2.set_ylim(0, max(1.0, 1.20 * float(repeats.max())))
        ax2.grid(False)
        if float(repeats.max()) > 0:
            _annotate_selected_points(ax2, iteration, repeats, lambda y: f"repeat {int(y)}", color=repeat_line.get_color(), every=True)
        handles.append(repeat_line)
        labels.append("Consecutive repeated candidate count")
    _boxed_legend_below(fig, handles, labels, ncol=2, bottom=0.27)
    return _save(fig, figures_dir, "23_lbbd_adaptive_master_control", dpi)



def _plot_lbbd_candidate_reuse(run_dir: Path, figures_dir: Path, dpi: int) -> list[str]:
    df = _load_lbbd_history(run_dir)
    required = {"iteration", "candidate_cached", "candidate_repeat_count", "new_cuts_total"}
    if not required.issubset(df.columns):
        raise ValueError("LBBD history lacks candidate-cache diagnostics")
    iteration = _numeric(df["iteration"]).astype(int).to_numpy()
    cached = _numeric(df["candidate_cached"]).fillna(0.0).clip(0, 1).to_numpy(dtype=float)
    evaluated = 1.0 - cached
    cuts = _numeric(df["new_cuts_total"]).fillna(0.0).to_numpy(dtype=float)
    repeats = _numeric(df["candidate_repeat_count"]).fillna(0.0).to_numpy(dtype=float)
    x = np.arange(len(iteration))

    fig, ax = plt.subplots(figsize=(10.7, 6.2))
    ax.bar(x, evaluated, label="New candidate evaluated", width=0.70)
    ax.bar(x, cached, bottom=evaluated, label="Exact result reused from cache", width=0.70)
    ax.set_xticks(x)
    ax.set_xticklabels(iteration.astype(str))
    ax.set_xlabel("LBBD iteration")
    ax.set_ylabel("Candidate evaluation indicator")
    ax.set_ylim(0, 1.25)
    ax.set_title("LBBD candidate reuse, repetition and new inference")

    ax2 = ax.twinx()
    repeat_line, = ax2.plot(x, repeats, marker="o", linewidth=1.8, label="Repeated-candidate count")
    cut_line, = ax2.plot(x, cuts, marker="s", linestyle="--", linewidth=1.6, label="New cuts added")
    ax2.set_ylabel("Count")
    ax2.set_ylim(0, max(1.0, 1.20 * float(max(repeats.max(initial=0), cuts.max(initial=0)))))
    ax2.grid(False)
    h1, l1 = ax.get_legend_handles_labels()
    _boxed_legend_below(fig, h1 + [repeat_line, cut_line], l1 + ["Repeated-candidate count", "New cuts added"], ncol=2, bottom=0.25)
    return _save(fig, figures_dir, "24_lbbd_candidate_reuse", dpi)

def _plot_slack(results_dir: Path, figures_dir: Path, dpi: int) -> list[str]:
    df = _read_csv(results_dir / "slack.csv")
    if df.empty:
        raise ValueError("No positive slack")
    df["Slack_kWh_annual"] = _numeric(df["Slack_kWh_annual"]).fillna(0.0)
    agg = df.groupby("Month")["Slack_kWh_annual"].sum().reindex(MONTHS, fill_value=0.0)
    if float(agg.sum()) <= 1e-8:
        raise ValueError("No positive slack")
    fig, ax = plt.subplots(figsize=(9.5, 5))
    ax.bar(np.arange(12), agg.to_numpy())
    ax.set_xticks(np.arange(12)); ax.set_xticklabels([m[:3] for m in MONTHS])
    ax.set_ylabel("Unmet demand (kWh/year)")
    ax.set_title("Annualized unmet charging demand by month")
    return _save(fig, figures_dir, "10_slack_by_month", dpi)


def _load_geometry(path: Path):
    import geopandas as gpd
    gdf = gpd.read_file(path)[["HexID", "geometry"]].copy()
    gdf = gdf.loc[:, ~gdf.columns.duplicated()].copy()
    gdf["HexID"] = pd.to_numeric(gdf["HexID"], errors="coerce")
    gdf = gdf.dropna(subset=["HexID", "geometry"]).drop_duplicates("HexID")
    gdf["HexID"] = gdf["HexID"].astype(int)
    if gdf.crs is None:
        raise ValueError(f"Geometry file has no CRS: {path}")
    return gdf


def _merge_geometry(results_dir: Path, geometry_path: Path):
    gdf = _load_geometry(geometry_path)
    infra = _read_csv(results_dir / "infrastructure_by_hex.csv", required=True)
    infra = infra.loc[:, ~infra.columns.duplicated()].copy()
    if "HexID" not in infra.columns:
        raise ValueError("infrastructure_by_hex.csv lacks HexID")
    infra["HexID"] = pd.to_numeric(infra["HexID"], errors="coerce").astype("Int64")
    infra = infra.dropna(subset=["HexID"]).drop_duplicates("HexID").copy()
    infra["HexID"] = infra["HexID"].astype(int)
    for col in [c for c in infra.columns if c != "HexID"]:
        infra[col] = pd.to_numeric(infra[col], errors="coerce").fillna(0.0)
    merged = gdf.merge(infra, on="HexID", how="left", validate="one_to_one")
    for col in [c for c in infra.columns if c != "HexID"]:
        merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0.0)
    return gdf, merged


def _plot_choropleth(
    merged,
    base,
    column: str,
    title: str,
    cbar_label: str,
    figures_dir: Path,
    stem: str,
    dpi: int,
    cmap: str = "viridis",
    symmetric: bool = False,
    basemap_alpha: float = 0.25,
) -> list[str]:
    if column not in merged.columns:
        raise ValueError(f"Missing map column: {column}")
    merged3857 = merged.to_crs(epsg=3857)
    base3857 = base.to_crs(epsg=3857)
    fig, ax = plt.subplots(figsize=(10.5, 10.5))
    base3857.boundary.plot(ax=ax, linewidth=0.15, alpha=0.15, color="0.35", zorder=1)
    _add_basemap(ax, alpha=basemap_alpha)
    values = pd.to_numeric(merged3857[column], errors="coerce").fillna(0.0)
    merged3857[column] = values
    kwargs = {
        "column": column,
        "ax": ax,
        "cmap": cmap,
        "legend": True,
        "edgecolor": "white",
        "linewidth": 0.15,
        "alpha": 0.78,
        "zorder": 2,
    }
    if symmetric:
        vmax = float(np.nanmax(np.abs(values.to_numpy()))) if len(values) else 0.0
        if vmax > 0:
            kwargs.update({"vmin": -vmax, "vmax": vmax})
    merged3857.plot(**kwargs)
    base3857.boundary.plot(ax=ax, linewidth=0.20, alpha=0.35, color="0.25", zorder=3)
    ax.set_axis_off()
    ax.set_aspect("equal")
    ax.set_title(title)
    if len(fig.axes) > 1:
        fig.axes[-1].set_ylabel(cbar_label)
    return _save(fig, figures_dir, stem, dpi)


def _plot_redirection_corridors(
    redir: pd.DataFrame,
    merged,
    base,
    figures_dir: Path,
    dpi: int,
    max_flow_arcs: int,
    month: str,
    basemap_alpha: float,
) -> list[str]:
    required = {"from_HexID", "to_HexID", "Month", "Energy_kWh_day"}
    if not required.issubset(redir.columns):
        raise ValueError(f"redirections.csv lacks columns: {sorted(required - set(redir.columns))}")
    sub = redir[redir["Month"].astype(str) == month].copy()
    if sub.empty:
        raise ValueError(f"No positive redirection flows for {month}")
    sub["Energy_kWh_day"] = pd.to_numeric(sub["Energy_kWh_day"], errors="coerce").fillna(0.0)
    agg = (
        sub.groupby(["from_HexID", "to_HexID"], as_index=False)["Energy_kWh_day"]
        .sum()
        .query("Energy_kWh_day > 0")
        .nlargest(max(1, int(max_flow_arcs)), "Energy_kWh_day")
    )
    if agg.empty:
        raise ValueError(f"No positive aggregated redirection corridors for {month}")

    merged3857 = merged.to_crs(epsg=3857)
    base3857 = base.to_crs(epsg=3857)
    cent = merged3857.set_index("HexID").geometry.centroid
    rows = []
    for _, row in agg.iterrows():
        i, j = int(row["from_HexID"]), int(row["to_HexID"])
        if i not in cent.index or j not in cent.index:
            continue
        p1, p2 = cent.loc[i], cent.loc[j]
        if p1.equals(p2):
            continue
        rows.append((p1.x, p1.y, p2.x, p2.y, float(row["Energy_kWh_day"])))
    if not rows:
        raise ValueError(f"No redirection corridors could be matched to geometry for {month}")

    weights = np.asarray([r[4] for r in rows], dtype=float)
    max_weight = max(float(weights.max()), 1e-12)
    fig, ax = plt.subplots(figsize=(12, 12))
    base3857.boundary.plot(ax=ax, color="0.45", linewidth=0.30, alpha=0.20, zorder=1)
    _add_basemap(ax, alpha=basemap_alpha)
    base3857.boundary.plot(ax=ax, color="0.35", linewidth=0.28, alpha=0.28, zorder=2)

    for fx, fy, tx, ty, energy in sorted(rows, key=lambda r: r[4]):
        lw = 0.6 + 3.6 * math.sqrt(max(energy, 0.0) / max_weight)
        arrow = FancyArrowPatch(
            (fx, fy),
            (tx, ty),
            arrowstyle="-|>",
            linewidth=lw,
            edgecolor="black",
            facecolor="lightgray",
            mutation_scale=5.5 + 2.4 * lw,
            alpha=0.78,
            shrinkA=1.5,
            shrinkB=1.5,
            zorder=3,
        )
        ax.add_patch(arrow)

    quantiles = np.unique(np.quantile(weights[weights > 0], [0.10, 0.50, 1.00]))
    legend_handles = []
    for value in quantiles:
        lw = 0.6 + 3.6 * math.sqrt(float(value) / max_weight)
        if value >= 1000.0:
            label = f"{value / 1e3:,.2f} MWh/day"
        else:
            label = f"{value:,.1f} kWh/day"
        legend_handles.append(Line2D([], [], color="black", linewidth=lw, label=label))
    fig.legend(
        handles=legend_handles,
        title="Corridor energy",
        loc="lower center",
        bbox_to_anchor=(0.5, 0.012),
        ncol=max(1, len(legend_handles)),
        frameon=True,
        fancybox=True,
        framealpha=0.96,
        edgecolor="0.6",
    )
    ax.set_axis_off()
    ax.set_aspect("equal")
    ax.set_title(f"{month}: redirected charging-demand corridors\nTop {len(rows)} origin–destination flows")
    fig.subplots_adjust(bottom=0.105, top=0.92)
    return _save(fig, figures_dir, f"15_map_redirection_corridors_{month.lower()}", dpi)


def _plot_maps(
    results_dir: Path,
    figures_dir: Path,
    geometry_path: Path,
    dpi: int,
    max_flow_arcs: int,
    redirection_month: str = "June",
    basemap_alpha: float = 0.28,
) -> list[str]:
    base, merged = _merge_geometry(results_dir, geometry_path)
    outputs: list[str] = []
    outputs += _plot_choropleth(
        merged, base, "Total_public_capacity_kWh_slot", "Installed public charging capacity",
        "kWh per 30-minute slot", figures_dir, "11_map_public_charging_capacity", dpi,
        basemap_alpha=basemap_alpha,
    )
    outputs += _plot_choropleth(
        merged, base, "PV_panels", "Installed PV panels", "PV panels",
        figures_dir, "12_map_pv_installation", dpi, basemap_alpha=basemap_alpha,
    )
    outputs += _plot_choropleth(
        merged, base, "Battery_units", "Installed BESS units", "10-kWh BESS units",
        figures_dir, "13_map_bess_installation", dpi, basemap_alpha=basemap_alpha,
    )

    redir = _read_csv(results_dir / "redirections.csv")
    if not redir.empty:
        redir["Energy_kWh_annual"] = _numeric(redir["Energy_kWh_annual"]).fillna(0.0)
        out = redir.groupby("from_HexID")["Energy_kWh_annual"].sum()
        inc = redir.groupby("to_HexID")["Energy_kWh_annual"].sum()
        merged["Net_redirection_in_kWh_annual"] = merged["HexID"].map(inc).fillna(0.0) - merged["HexID"].map(out).fillna(0.0)
        outputs += _plot_choropleth(
            merged, base, "Net_redirection_in_kWh_annual", "Net annual redirected energy by cell",
            "Incoming minus outgoing kWh/year", figures_dir, "14_map_net_redirection", dpi,
            cmap="coolwarm", symmetric=True, basemap_alpha=basemap_alpha,
        )
        outputs += _plot_redirection_corridors(
            redir, merged, base, figures_dir, dpi, max_flow_arcs,
            month=redirection_month, basemap_alpha=basemap_alpha,
        )
    return outputs


def _write_figures_readme(figures_dir: Path) -> None:
    text = """# Generated optimization figures

Figures are generated automatically after successful monolithic and LBBD result export.
PNG files use the run-level resolution setting (default: 300 dpi). The figure manifest records
which figure groups were generated, skipped, or failed.

## How to read the common result figures

- `01_economic_breakdown.png` separates annual revenue, grid electricity, redirection incentives,
  slack penalty, charger capex, and PV/BESS capex. Positive bars increase profit; negative bars reduce it.
- `02_charger_deployment_and_utilization.png` compares installed slow, medium, and fast chargers
  with the annual utilization of their available capacity.
- `03_monthly_energy_supply_mix.png` shows whether charger energy is supplied directly from the
  grid, directly from PV, or through battery discharge.
- `03a_input_pv_tou_profiles.png` verifies the month-specific stationary-PV capacity factors and
  retail ToU prices actually supplied to the optimization.
- `03b_seasonal_charging_demand_profiles.png` shows the four MATSim seasonal demand profiles used
  for the annual optimization, stacked as home and work+public charging demand.
- `03c_seasonal_energy_supply_profiles.png` shows the optimized seasonal supply mix from grid,
  direct stationary PV, and BESS discharge.
- `04_dispatch_<month>.png` gives the representative-day dispatch profile for selected months.
- `05_bess_soc_by_month.png` and `06_bess_operation_<month>.png` describe the linked BESS state of
  charge and charge/discharge operation. They are generated only when BESS output files exist.
- `07_redirection_month_time_heatmap.png` shows when redirected charging is used most strongly.
- `08_redirection_type_matrix.png` shows the origin charger-type to destination charger-type energy
  assignment in the exact exported solution.
- `10_slack_by_month.png` is generated only when positive unmet demand exists. A skipped slack figure
  normally means the optimized solution had zero positive slack.
- `11_map_public_charging_capacity.png` through `15_map_redirection_corridors_<month>.png` are spatial
  maps. If `contextily` or internet access is unavailable, maps are still generated from the vector geometry.
- `16_demand_supply_balance_annual_average.png` compares home and public charging supply accounting.

## How to read decomposition figures

- `09_decomposition_convergence.png` is the main certificate plot. The upper-bound line is the valid
  global master bound. The lower-bound line is the best exact feasible incumbent. The dashed gap line
  is `(UB - LB) / max(1, |UB|)` in percent.
- `17_decomposition_cut_generation.png` reports accepted master cuts and, for LBBD runs, the annual-LP
  and core-point violation signals before filtering. If it shows only exact-configuration cuts, this means
  the embedded master relaxation was already tight enough that LP/core/logic cuts were not violated at
  the evaluated candidates.
- `18_lbbd_cut_families.png` summarizes the accepted LBBD cuts by family and by iteration. It is a
  diagnostic of which inference mechanism actually changed the master, not a measure of solution quality.
- `19_lbbd_candidate_bounds.png` compares the master candidate value, annual LP relaxation, fixed-layout
  MIP upper bound, and exact feasible objective. The lower panel reports differences from the exact
  incumbent in kSEK/year, which is usually more informative than overlapping objective lines.
- `20_lbbd_infrastructure_evolution.png` shows how the candidate charger, PV, and BESS decisions change
  across iterations.
- `21_lbbd_iteration_timing.png` separates master-solve time from oracle/cut/export time and shows the
  cumulative runtime.
- `22_lbbd_gap_diagnostics.png` compares the global LBBD gap, master MIP gap, and exact fixed-layout MIP
  gap on a logarithmic scale.
- `23_lbbd_adaptive_master_control.png` verifies that the requested trial-master gap tightens as the
  certified LBBD gap decreases. This is important because a loose trial-master MIP gap can stall outer-loop
  convergence.
- `24_lbbd_candidate_reuse.png` shows whether an iteration evaluated a new infrastructure candidate or
  reused an exact result from the internal cache, together with repeated-candidate counts and new cuts.

## Regenerating figures

```powershell
python src\\visualize_results.py --run-dir "runs\\<RUN_FOLDER>" --dataset small --dpi 300 --redirection-map-month June
```
"""
    (figures_dir / "README_FIGURES.md").write_text(text, encoding="utf-8")



def generate_run_figures(
    run_dir: str | Path,
    project_root: str | Path | None = None,
    dataset: str | None = None,
    parking_shapefile: str | None = None,
    dpi: int = 300,
    max_flow_arcs: int = 150,
    redirection_map_month: str = "June",
    basemap_alpha: float = 0.28,
) -> pd.DataFrame:
    run_dir = Path(run_dir).resolve()
    project_root = Path(project_root).resolve() if project_root else Path(__file__).resolve().parents[1]
    results_dir = run_dir / "results"
    if not results_dir.exists():
        raise FileNotFoundError(f"Results folder not found: {results_dir}")
    figures_dir = run_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    _setup_style()
    dataset = dataset or _infer_dataset(run_dir)
    vipv_scenario = _infer_vipv_scenario(run_dir)
    geometry_path = _resolve_geometry(project_root, dataset, parking_shapefile, vipv_scenario)

    tasks: list[tuple[str, Callable[[], list[str]]]] = [
        ("economic_breakdown", lambda: _plot_economic_breakdown(results_dir, figures_dir, dpi)),
        ("charger_deployment", lambda: _plot_charger_deployment(results_dir, figures_dir, dpi)),
        ("monthly_energy", lambda: _plot_monthly_energy(results_dir, figures_dir, dpi)),
        ("input_pv_tou_profiles", lambda: _plot_input_pv_tou_profiles(results_dir, figures_dir, dpi)),
        ("seasonal_demand_profiles", lambda: _plot_seasonal_demand_profiles(results_dir, figures_dir, dpi)),
        ("seasonal_supply_profiles", lambda: _plot_seasonal_supply_profiles(results_dir, figures_dir, dpi)),
    ]
    hourly = None
    try:
        hourly = _prepare_hourly(results_dir)
        for month in REPRESENTATIVE_MONTHS:
            tasks.append((f"dispatch_{month}", lambda month=month: _plot_dispatch_month(hourly, month, figures_dir, dpi)))
        tasks.append(("bess_soc", lambda: _plot_soc_by_month(results_dir, figures_dir, dpi)))
        for month in ["January", "July"]:
            tasks.append((f"bess_operation_{month}", lambda month=month: _plot_battery_operation_month(hourly, month, figures_dir, dpi, results_dir=results_dir)))
    except Exception:
        pass
    tasks += [
        ("demand_supply_balance", lambda: _plot_demand_supply_balance(results_dir, figures_dir, dpi)),
        ("redirection_heatmap", lambda: _plot_redirection_heatmap(results_dir, figures_dir, dpi)),
        ("redirection_type_matrix", lambda: _plot_redirection_type_matrix(results_dir, figures_dir, dpi)),
        ("decomposition_convergence", lambda: _plot_decomposition_convergence(run_dir, figures_dir, dpi)),
        ("decomposition_cut_generation", lambda: _plot_decomposition_cut_generation(run_dir, figures_dir, dpi)),
        ("lbbd_cut_families", lambda: _plot_lbbd_cut_families(run_dir, figures_dir, dpi)),
        ("lbbd_candidate_bounds", lambda: _plot_lbbd_candidate_bounds(run_dir, figures_dir, dpi)),
        ("lbbd_infrastructure_evolution", lambda: _plot_lbbd_infrastructure_evolution(run_dir, figures_dir, dpi)),
        ("lbbd_iteration_timing", lambda: _plot_lbbd_iteration_timing(run_dir, figures_dir, dpi)),
        ("lbbd_gap_diagnostics", lambda: _plot_lbbd_gap_diagnostics(run_dir, figures_dir, dpi)),
        ("lbbd_adaptive_master_control", lambda: _plot_lbbd_adaptive_master_control(run_dir, figures_dir, dpi)),
        ("lbbd_candidate_reuse", lambda: _plot_lbbd_candidate_reuse(run_dir, figures_dir, dpi)),
        ("slack", lambda: _plot_slack(results_dir, figures_dir, dpi)),
    ]
    if geometry_path is not None and geometry_path.exists():
        tasks.append(("spatial_maps", lambda: _plot_maps(
            results_dir,
            figures_dir,
            geometry_path,
            dpi,
            max_flow_arcs,
            redirection_month=redirection_map_month,
            basemap_alpha=basemap_alpha,
        )))

    records = []
    for name, task in tasks:
        try:
            files = task()
            records.append({"figure_group": name, "status": "generated", "files": ";".join(files), "message": ""})
            print(f"Figure generated: {name}")
        except (ValueError, FileNotFoundError) as exc:
            records.append({"figure_group": name, "status": "skipped", "files": "", "message": str(exc)})
            print(f"Figure skipped: {name} ({exc})")
        except Exception as exc:
            records.append({"figure_group": name, "status": "failed", "files": "", "message": f"{type(exc).__name__}: {exc}"})
            print(f"WARNING: Figure failed: {name} ({exc})")
            (figures_dir / f"ERROR_{name}.txt").write_text(traceback.format_exc(), encoding="utf-8")
    if geometry_path is None or not geometry_path.exists():
        records.append({"figure_group": "spatial_maps", "status": "skipped", "files": "", "message": "Parking/hex geometry path unavailable"})
    manifest = pd.DataFrame(records)
    manifest.to_csv(figures_dir / "figures_manifest.csv", index=False)
    _write_figures_readme(figures_dir)
    print(f"Figures written to: {figures_dir}")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate publication-quality figures from an existing optimization run folder.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--dataset", choices=["small", "full"], default=None)
    parser.add_argument("--parking-shapefile", default=None)
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--max-flow-arcs", type=int, default=150)
    parser.add_argument("--redirection-map-month", choices=MONTHS, default="June")
    parser.add_argument("--basemap-alpha", type=float, default=0.28)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    generate_run_figures(
        run_dir=args.run_dir,
        project_root=args.project_root,
        dataset=args.dataset,
        parking_shapefile=args.parking_shapefile,
        dpi=max(100, int(args.dpi)),
        max_flow_arcs=max(1, int(args.max_flow_arcs)),
        redirection_map_month=args.redirection_map_month,
        basemap_alpha=min(1.0, max(0.0, float(args.basemap_alpha))),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
