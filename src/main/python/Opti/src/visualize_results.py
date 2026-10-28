#!/usr/bin/env python
"""Modified for the UrbanEV seasonal integration, 2026-10-22. See SOURCE_PROVENANCE.json."""
from __future__ import annotations

import argparse
import inspect
import json
import math
import os
import re
import traceback
from pathlib import Path
from typing import Callable
from urllib.parse import quote

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch, Patch
import numpy as np
import pandas as pd
from input_scenarios import VIPV_SCENARIOS
from preprocessing import SEASON_TO_MONTHS
SEASON_ORDER = ["SPRING", "SUMMER", "AUTUMN", "WINTER"]

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


def _add_basemap(ax: plt.Axes, alpha: float = 0.30, source: str = "auto") -> bool:
    """Draw licensed tiles only when the selected provider's access rules are met."""
    if source == "none":
        return False
    try:
        import contextily as ctx
        key = os.environ.get("CARTO_BASEMAP_API_KEY", "").strip()
        provider = "carto" if source == "auto" and key else "osm" if source == "auto" else source
        params = {}
        if provider == "carto":
            if not key:
                print("WARNING: CARTO basemap requires CARTO_BASEMAP_API_KEY; using vector layers only")
                return False
            params["source"] = (
                "https://basemaps.cartocdn.com/light_nolabels/"
                "{z}/{x}/{y}.png?key=" + quote(key, safe="")
            )
            params["attribution"] = "(C) OpenStreetMap contributors, (C) CARTO"
        elif provider == "osm":
            if "headers" not in inspect.signature(ctx.add_basemap).parameters:
                print("WARNING: OpenStreetMap basemap needs contextily with request-header support; using vector layers only")
                return False
            params["source"] = ctx.providers.OpenStreetMap.Mapnik
            params["headers"] = {
                "User-Agent": "Large-scale-LBBD-Optimization/1.0 (https://github.com/parishwadomkar/Large-scale-LBBD-Optimization)"
            }
        else:
            raise ValueError(f"Unsupported basemap provider: {provider}")
        xlim, ylim = ax.get_xlim(), ax.get_ylim()
        ctx.add_basemap(
            ax,
            crs="EPSG:3857",
            alpha=float(alpha),
            reset_extent=False,
            attribution_size=6,
            **params,
        )
        ax.set_xlim(xlim)
        ax.set_ylim(ylim)
        return True
    except Exception as exc:
        print(f"WARNING: Basemap unavailable ({type(exc).__name__}); using vector layers only")
        return False


def _save(fig: plt.Figure, figures_dir: Path, stem: str, dpi: int) -> list[str]:
    figures_dir.mkdir(parents=True, exist_ok=True)
    png = figures_dir / f"{stem}.png"
    fig.savefig(png, dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return [png.name]


def _hour_axis(ax: plt.Axes) -> None:
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
        run_dir / "iterations" / "benders_iteration_history.csv",
        run_dir / "results" / "benders_iteration_history.csv",
        run_dir / "results" / "lbbd_history.csv",
        run_dir / "results" / "alternative_c_history.csv",
        # Legacy names remain readable for existing result folders.
        run_dir / "iterations" / "lbbd_iteration_history.csv",
        run_dir / "results" / "lbbd_iteration_history.csv",
    ]
    return next((p for p in candidates if p.exists()), None)


def _history_method(df: pd.DataFrame, path: Path) -> str:
    if "lbbd_gap" in df.columns or path.name in {"lbbd_history.csv", "alternative_c_history.csv"}:
        return "LBBD"
    return "Benders"


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


def _lbbd_metadata(run_dir: Path) -> dict:
    path = run_dir / "run_metadata.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _lbbd_cut_accounting(run_dir: Path, df: pd.DataFrame, figures_dir: Path) -> tuple[pd.DataFrame, int | None]:
    metadata = _lbbd_metadata(run_dir)
    timing = metadata.get("computational_complexity", {}).get("phase_timing", {})
    recorded = "bootstrap_hall_cuts_added" in timing
    pre_loop = [
        ("initial_master", "Static origin", int(metadata.get("static_origin_profit_cuts", 0))),
        ("root_screen", "Hall/min-cut", int(metadata.get("root_hall_profit_cuts", 0))),
        ("bootstrap_repair", "Hall/min-cut", int(timing.get("bootstrap_hall_cuts_added", 0))),
    ] if recorded else []
    rows = []
    cumulative = 0
    for phase, family, count in pre_loop:
        cumulative += count
        rows.append((phase, 0, family, count, cumulative))
    for _, record in df.iterrows():
        iteration = int(record["iteration"])
        accepted = 0
        for column, family in _lbbd_cut_columns(df):
            raw = pd.to_numeric(record.get(column, 0), errors="coerce")
            count = int(round(float(raw))) if pd.notna(raw) else 0
            cumulative += count
            accepted += count
            rows.append(("outer_iteration", iteration, family, count, cumulative))
        if "new_cuts_total" in df.columns and accepted != int(record["new_cuts_total"]):
            raise ValueError(f"LBBD cut-family sum disagrees with new_cuts_total at iteration {iteration}")
    audit = pd.DataFrame(rows, columns=["phase", "iteration", "cut_family", "accepted_cuts", "cumulative_cuts"])
    audit.to_csv(figures_dir / "lbbd_cut_accounting.csv", index=False)
    baseline = sum(count for _, _, count in pre_loop) if recorded else None
    initial = metadata.get("initial_master_constraints")
    final = metadata.get("final_master_constraints")
    if baseline is not None and initial is not None and final is not None:
        # Static origin cuts are already present in the recorded initial master.
        extra_constraints = int(final) - int(initial)
        expected = cumulative - int(metadata.get("static_origin_profit_cuts", 0))
        if extra_constraints < expected:
            raise ValueError("Accepted cuts exceed the recorded increase in master constraints")
    return audit, baseline


def _lbbd_source_labels(df: pd.DataFrame) -> list[str]:
    names = {
        "lp_bootstrap": "LP bootstrap",
        "master_mip_incumbent": "master MIP",
        "lp_fallback": "LP fallback",
        "best_certified_incumbent_bound_only": "bound only",
    }
    return [
        f"{int(row['iteration'])}\n{names.get(str(row.get('candidate_source', '')), str(row.get('candidate_source', '')))}"
        for _, row in df.iterrows()
    ]


def _lbbd_exact_evaluation_audit(run_dir: Path, figures_dir: Path) -> pd.DataFrame:
    logs = _read_csv(run_dir / "results" / "solver_log_complexity.csv")
    if logs.empty or "log_name" not in logs.columns:
        return pd.DataFrame()
    rows = []
    for _, record in logs.iterrows():
        match = re.fullmatch(r"lbbd_exact_annual_(\d+)\.log", str(record["log_name"]))
        if not match:
            continue
        call_id = int(match.group(1))
        rows.append({
            "iteration": call_id if call_id < 100 else call_id // 100,
            "exact_call_id": call_id,
            "stage": "repair" if call_id >= 100 else "trial",
            "objective_SEK": record.get("final_objective"),
            "fixed_upper_bound_SEK": record.get("final_bound"),
            "solver_seconds": record.get("solver_seconds"),
            "work_units": record.get("work_units"),
            "log_name": record["log_name"],
        })
    audit = pd.DataFrame(rows)
    if not audit.empty:
        audit = audit.sort_values(["iteration", "exact_call_id"])
        audit.to_csv(figures_dir / "lbbd_exact_evaluations.csv", index=False)
    return audit

def _plot_decomposition_convergence(run_dir: Path, figures_dir: Path, dpi: int) -> list[str]:
    path = _find_history(run_dir)
    if path is None:
        raise ValueError("No decomposition iteration history")
    df = _read_csv(path, required=True)
    if df.empty or "iteration" not in df.columns:
        raise ValueError("Decomposition iteration history is empty")
    method = _history_method(df, path)
    iteration = _numeric(df["iteration"])
    ub_col = _first_present(df, ["global_best_UB_SEK", "global_ub_SEK", "master_best_bound_UB_SEK", "master_bound_SEK"])
    lb_col = _first_present(df, ["best_LB_SEK", "best_lb_SEK"])
    gap_col = _first_present(df, ["Benders_gap", "lbbd_gap"])
    if ub_col is None or lb_col is None:
        raise ValueError("Decomposition history lacks upper/lower-bound columns")
    ub = _numeric(df[ub_col]) / 1e6
    lb = _numeric(df[lb_col]) / 1e6
    fig, ax = plt.subplots(figsize=(9.8, 6.2))
    upper_line, = ax.plot(iteration, ub, marker="o", linewidth=1.8, label="Global master upper bound")
    lower_line, = ax.plot(iteration, lb, marker="o", linewidth=1.8, label="Best certified lower bound")
    ax.set_xticks(iteration)
    ax.set_xticklabels([str(int(v)) for v in iteration])
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
        valid = [(float(x), float(g)) for x, g in zip(iteration, gap_values) if np.isfinite(g)]
        for k, (x_value, gap) in enumerate((valid[0], valid[-1]) if len(valid) > 1 else valid):
            label = f"{gap:.4f}%" if gap < 0.1 else f"{gap:.3f}%"
            ax2.annotate(label, (x_value, gap), xytext=(7 if k == 0 else -8, 9 if k == 0 else 15), textcoords="offset points", ha="left" if k == 0 else "right", va="bottom", fontsize=8, color=gap_line.get_color())
        if method == "LBBD":
            target = _lbbd_metadata(run_dir).get("effective_settings", {}).get("lbbd_gap")
            if target is not None:
                ax2.axhline(100.0 * float(target), color="0.50", linestyle=":", linewidth=1.2)
                ax2.text(0.98, 0.16, f"Dotted target: {100.0 * float(target):.4f}%", transform=ax2.transAxes, ha="right", va="bottom", fontsize=9, color="0.35")
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

    method = _history_method(df, path)
    iteration = _numeric(df["iteration"]).astype(int)
    x = np.arange(len(iteration))

    if method != "LBBD":
        cuts = _numeric(df["cuts_added"]).fillna(0.0) if "cuts_added" in df.columns else pd.Series(0.0, index=df.index)
        candidates = _numeric(df["cut_candidates"]).fillna(cuts) if "cut_candidates" in df.columns else cuts.copy()
        cumulative = cuts.cumsum()
        width = 0.36

        fig, ax = plt.subplots(figsize=(9.8, 5.9))
        bars_candidates = ax.bar(
            x - width / 2, candidates, width=width,
            label="Cut candidates / triggers", alpha=0.72, zorder=2,
        )
        bars_added = ax.bar(
            x + width / 2, cuts, width=width,
            label="Cuts added", alpha=0.90, zorder=3,
        )
        ax.set_xticks(x)
        ax.set_xticklabels(iteration.astype(str))
        ax.set_xlabel(f"{method} iteration")
        ax.set_ylabel("Cuts in iteration")
        ax.set_title(f"{method} cut generation and cumulative master enrichment")

        for container in (bars_candidates, bars_added):
            labels = [f"{int(v)}" if v > 0 else "" for v in container.datavalues]
            ax.bar_label(container, labels=labels, padding=2, fontsize=8)

        ax2 = ax.twinx()
        cumulative_line, = ax2.plot(
            x, cumulative, marker="o", linewidth=2.3,
            label="Cumulative cuts", zorder=5,
        )
        ax2.set_ylabel("Cumulative cuts in master")
        ax2.set_ylim(
            0,
            max(1.0, 1.15 * float(cumulative.max()) if len(cumulative) else 1.0),
        )
        ax2.grid(False)

        h1, l1 = ax.get_legend_handles_labels()
        _boxed_legend_below(
            fig,
            h1 + [cumulative_line],
            l1 + ["Cumulative cuts"],
            ncol=3,
            bottom=0.23,
        )
        return _save(fig, figures_dir, "17_decomposition_cut_generation", dpi)

    audit, baseline = _lbbd_cut_accounting(run_dir, df, figures_dir)
    per_family = [(col, label) for col, label in _lbbd_cut_columns(df) if col in df.columns]
    active = [(col, label) for col, label in per_family if _numeric(df[col]).fillna(0).sum() > 0]
    pre_loop = audit[audit["phase"] != "outer_iteration"]
    pre_count = int(pre_loop["accepted_cuts"].sum())
    if not active and pre_count == 0:
        raise ValueError("No LBBD cuts were accepted")
    outer_total = _sum_columns(df, [col for col, _ in per_family]).to_numpy(dtype=float)
    cumulative = outer_total.cumsum() + (baseline or 0)
    fig, (setup_ax, ax) = plt.subplots(
        1, 2, figsize=(11.7, 5.6), gridspec_kw={"width_ratios": [1, 2.6]}
    )
    setup_parts = [
        ("Static origin", "#8c8c8c", int(pre_loop.loc[pre_loop["cut_family"] == "Static origin", "accepted_cuts"].sum())),
        ("Hall/min-cut (pre-loop)", "#4c78a8", int(pre_loop.loc[pre_loop["cut_family"] == "Hall/min-cut", "accepted_cuts"].sum())),
    ]
    base_height = 0
    for label, color, count in setup_parts:
        if count:
            setup_ax.bar(0, count, bottom=base_height, width=0.62, color=color, label=label)
            base_height += count
    setup_ax.text(0, pre_count + max(0.2, 0.02 * pre_count), str(pre_count) if baseline is not None else "unreported", ha="center", fontsize=9)
    setup_ax.set_ylim(0, max(1.35, pre_count * 1.16))
    setup_ax.set_xlim(-0.7, 0.7)
    setup_ax.set_xticks([0], ["Pre-loop"])
    setup_ax.set_ylabel("Accepted before iteration 1")
    setup_ax.set_title("Initial strengthening")

    colors = {"Hall/min-cut": "#4c78a8", "Component LP": "#72b7b2", "Annual LP": "#f58518",
              "Core-point LP": "#eeca3b", "Exact configuration": "#54a24b", "Partial logic": "#b279a2"}
    bottom = np.zeros(len(df))
    for col, label in active:
        vals = _numeric(df[col]).fillna(0).to_numpy(dtype=float)
        ax.bar(iteration, vals, bottom=bottom, width=0.58, color=colors[label], label=label)
        bottom += vals
    for xx, value in zip(iteration, bottom):
        ax.text(xx, value + 0.04, str(int(round(value))), ha="center", fontsize=9)
    ax.set_xticks(iteration)
    ax.set_xlabel("LBBD iteration")
    ax.set_ylabel("Cuts accepted in iteration")
    ax.set_ylim(0, max(1.4, 1.30 * float(bottom.max(initial=0))))
    ax.set_title("Outer-loop cut generation")

    ax2 = ax.twinx()
    line, = ax2.plot(iteration, cumulative, marker="o", color="#d62728", linewidth=2.0, label="Cumulative accepted cuts")
    lower = max(0, (baseline or 0) - max(1.0, 0.3 * float(outer_total.sum())))
    ax2.set_ylim(lower, max(lower + 2.0, float(cumulative.max(initial=0)) + 1.0))
    ax2.set_ylabel("Cumulative accepted cuts")
    ax2.grid(False)
    for xx, value in zip(iteration, cumulative):
        ax2.annotate(str(int(round(value))), (xx, value), xytext=(0, 7), textcoords="offset points", ha="center", color=line.get_color(), fontsize=8)
    if baseline is None:
        fig.suptitle("LBBD cuts (pre-loop accounting unavailable)")
    else:
        fig.suptitle(f"LBBD cuts: {pre_count} before iteration 1; {int(outer_total.sum())} in outer iterations")
    h0, l0 = setup_ax.get_legend_handles_labels()
    h1, l1 = ax.get_legend_handles_labels()
    _boxed_legend_below(fig, h0 + h1 + [line], l0 + l1 + ["Cumulative accepted cuts"], ncol=3, bottom=0.24)
    return _save(fig, figures_dir, "17_decomposition_cut_generation", dpi)



def _load_lbbd_history(run_dir: Path) -> pd.DataFrame:
    path = _find_history(run_dir)
    if path is None:
        raise ValueError("No LBBD iteration history")
    df = _read_csv(path, required=True)
    if df.empty or "iteration" not in df.columns or _history_method(df, path) != "LBBD":
        raise ValueError("Run does not contain LBBD iteration history")
    return df.copy()


def _plot_lbbd_cut_families(run_dir: Path, figures_dir: Path, dpi: int) -> list[str]:
    df = _load_lbbd_history(run_dir)
    audit, baseline = _lbbd_cut_accounting(run_dir, df, figures_dir)
    families = [(column, label) for column, label in _lbbd_cut_columns(df) if column in df.columns]
    if not families:
        raise ValueError("LBBD history lacks cut-family columns")
    totals = pd.Series({label: int(audit.loc[audit["cut_family"] == label, "accepted_cuts"].sum()) for _, label in families})
    static = int(audit.loc[audit["cut_family"] == "Static origin", "accepted_cuts"].sum())
    if static:
        totals["Static origin"] = static
    if not totals.sum():
        raise ValueError("No LBBD cuts were accepted")
    fig, ax = plt.subplots(figsize=(9.3, 5.6))
    y = np.arange(len(totals))
    bars = ax.barh(y, totals.to_numpy(dtype=float), height=0.62, color=["#4c78a8" if name == "Hall/min-cut" else "#54a24b" if name == "Exact configuration" else "#9a9a9a" for name in totals.index])
    ax.set_yticks(y)
    ax.set_yticklabels(totals.index)
    ax.invert_yaxis()
    ax.set_xlabel("Cuts accepted into master")
    ax.set_title(f"Accepted LBBD cuts by family ({int(totals.sum())} total)")
    maximum = max(1.0, float(totals.max()))
    ax.set_xlim(0, 1.18 * maximum)
    for bar, value in zip(bars, totals):
        ax.text(
            bar.get_width() + 0.02 * maximum,
            bar.get_y() + bar.get_height() / 2,
            f"{int(round(value))}",
            ha="left",
            va="center",
        )
    if baseline is not None:
        pre = audit[audit["phase"] != "outer_iteration"]
        root = int(pre.loc[pre["phase"] == "root_screen", "accepted_cuts"].sum())
        boot = int(pre.loc[pre["phase"] == "bootstrap_repair", "accepted_cuts"].sum())
        outer = int(audit.loc[audit["phase"] == "outer_iteration", "accepted_cuts"].sum())
        fig.text(0.53, 0.02, f"Before iterations: bootstrap Hall {boot}, root Hall {root}, static origin {static}; outer iterations: {outer}", ha="center", fontsize=9)
    else:
        fig.text(0.53, 0.02, "Pre-loop cut counts unavailable; outer iterations only", ha="center", fontsize=9)
    ax.grid(axis="x", alpha=0.25)
    ax.grid(axis="y", visible=False)
    return _save(fig, figures_dir, "18_lbbd_cut_families", dpi)



def _plot_lbbd_candidate_bounds(run_dir: Path, figures_dir: Path, dpi: int) -> list[str]:
    """Show exact certification quality of evaluated infrastructures.

    Master/global bounds are intentionally excluded here.  Bootstrap and LP-fallback
    candidates are not primal solutions of the same master MIP, so mixing their Eta
    values with exact recourse can create visually dramatic but algorithmically
    meaningless "relaxation errors".  Global bound convergence is shown in figure 09.
    """
    df = _load_lbbd_history(run_dir)
    if "candidate_exact_objective_SEK" not in df.columns:
        raise ValueError("LBBD history lacks exact candidate objectives")
    iteration = _numeric(df["iteration"])
    exact = _numeric(df["candidate_exact_objective_SEK"]) / 1e6
    fixed_ub = (
        _numeric(df["candidate_fixed_upper_bound_SEK"]) / 1e6
        if "candidate_fixed_upper_bound_SEK" in df.columns
        else pd.Series(np.nan, index=df.index)
    )
    best_lb = (
        _numeric(df["best_lb_SEK"]) / 1e6
        if "best_lb_SEK" in df.columns
        else exact.cummax()
    )
    fixed_gap = (
        100.0 * _numeric(df["candidate_fixed_gap"])
        if "candidate_fixed_gap" in df.columns
        else pd.Series(np.nan, index=df.index)
    )
    if "candidate_cached" in df.columns:
        distinct = _numeric(df["candidate_cached"]).fillna(0.0) < 0.5
        exact = exact.where(distinct)
        fixed_ub = fixed_ub.where(distinct)
        fixed_gap = fixed_gap.where(distinct)

    if exact.notna().sum() == 0:
        raise ValueError("No exact candidate certifications in LBBD history")

    fig, (ax_top, ax_bottom) = plt.subplots(
        2, 1, figsize=(11.4, 8.2), sharex=True,
        gridspec_kw={"height_ratios": [1.2, 0.8]},
    )
    ax_top.ticklabel_format(axis="y", style="plain", useOffset=False)
    ax_top.scatter(iteration, exact, s=48, zorder=4, label="Reported exact feasible candidate")
    if fixed_ub.notna().any():
        ax_top.scatter(iteration, fixed_ub, s=62, marker="o", facecolors="none", edgecolors="#e26a20", linewidths=1.5, zorder=5, label="Fixed-layout exact upper bound")
    if best_lb.notna().any():
        ax_top.step(iteration, best_lb, where="post", linewidth=2.2, label="Best certified incumbent")

    _annotate_selected_points(ax_top, iteration, exact, lambda y: f"{y:.3f} MSEK", color="#1f77b4", every=False, final=True, max_points=4)
    ax_top.margins(x=0.08, y=0.22)
    ax_top.set_ylabel("Objective (million SEK/year)")
    ax_top.set_title("Reported exact-certified candidate by outer iteration", pad=12)
    evaluation_audit = _lbbd_exact_evaluation_audit(run_dir, figures_dir)
    exact_roles = _lbbd_metadata(run_dir).get("computational_complexity", {}).get("solver_log_roles", [])
    exact_calls = len(evaluation_audit) if not evaluation_audit.empty else next((int(v["Solver calls"]) for v in exact_roles if v.get("Model role") == "exact_annual_oracle"), None)
    shown = int(exact.notna().sum())
    if exact_calls is not None and exact_calls > shown:
        note = f"{exact_calls} exact MIP calls; {shown} reported iteration outcomes plotted."
        for repair in evaluation_audit.loc[evaluation_audit["stage"] == "repair"].itertuples():
            raw = evaluation_audit[(evaluation_audit["iteration"] == repair.iteration) & (evaluation_audit["stage"] == "trial")]
            if not raw.empty:
                note += f"\nIteration {repair.iteration}: raw {float(raw.iloc[0]['objective_SEK']) / 1e6:.3f} MSEK (penalized slack); repaired {float(repair.objective_SEK) / 1e6:.3f} MSEK."
        ax_top.text(0.02, 0.035, note, transform=ax_top.transAxes, fontsize=8, va="bottom")

    positive_gap = fixed_gap.where(fixed_gap > 0)
    if positive_gap.notna().any():
        ax_bottom.scatter(iteration, positive_gap, s=40, label="Fixed-layout exact MIP gap")
        ax_bottom.set_yscale("log")
        _annotate_selected_points(ax_bottom, iteration, positive_gap, lambda y: f"{y:.5f}%", color="#1f77b4", every=False, final=True, max_points=4)
    else:
        ax_bottom.text(0.5, 0.5, "No positive fixed-layout certification gaps", transform=ax_bottom.transAxes, ha="center", va="center")
    ax_bottom.set_xlabel("LBBD iteration")
    ax_bottom.set_xticks(iteration)
    ax_bottom.set_xticklabels(_lbbd_source_labels(df))
    ax_bottom.set_ylabel("Exact fixed-layout gap (%)")
    ax_bottom.set_title("Fixed-layout precision of the reported candidates")

    handles1, labels1 = ax_top.get_legend_handles_labels()
    handles2, labels2 = ax_bottom.get_legend_handles_labels()
    _boxed_legend_below(fig, handles1 + handles2, labels1 + labels2, ncol=2, bottom=0.27)
    return _save(fig, figures_dir, "19_lbbd_candidate_bounds", dpi)


def _plot_lbbd_infrastructure_evolution(
    run_dir: Path,
    figures_dir: Path,
    dpi: int,
) -> list[str]:
    df = _load_lbbd_history(run_dir)

    best_columns = {
        "Slow": "best_slow",
        "Medium": "best_medium",
        "Fast": "best_fast",
        "PV": "best_PV",
        "BESS": "best_BESS",
    }
    legacy_columns = {
        "Slow": "slow",
        "Medium": "medium",
        "Fast": "fast",
        "PV": "PV",
        "BESS": "BESS",
    }

    if all(column in df.columns for column in best_columns.values()):
        columns = best_columns
        title = "Best-certified LBBD infrastructure by iteration"
    else:
        columns = legacy_columns
        title = "Evaluated LBBD infrastructure by iteration"

    if not any(column in df.columns for column in columns.values()):
        raise ValueError("LBBD history lacks infrastructure counts")

    iteration = _numeric(df["iteration"]).to_numpy(dtype=float)

    fig, axes = plt.subplots(
        1,
        3,
        figsize=(14.0, 4.8),
        sharex=True,
    )

    for label in ("Slow", "Medium", "Fast"):
        column = columns[label]
        if column not in df.columns:
            continue
        values = _numeric(df[column]).ffill()
        line, = axes[0].step(
            iteration,
            values,
            where="post",
            marker="o",
            linewidth=1.8,
            label=label,
        )
        valid = values.dropna()
        if not valid.empty:
            _annotate_xy(
                axes[0],
                float(iteration[-1]),
                float(valid.iloc[-1]),
                f"{int(round(valid.iloc[-1])):,}",
                color=line.get_color(),
                xytext=(0, 8),
                fontsize=8,
            )

    axes[0].set_title("Public chargers")
    axes[0].set_ylabel("Installed chargers")
    axes[0].legend(frameon=True)

    if columns["PV"] in df.columns:
        values = _numeric(df[columns["PV"]]).ffill()
        line, = axes[1].step(
            iteration,
            values,
            where="post",
            marker="o",
            linewidth=1.8,
        )
        valid = values.dropna()
        if not valid.empty:
            _annotate_xy(
                axes[1],
                float(iteration[-1]),
                float(valid.iloc[-1]),
                f"{int(round(valid.iloc[-1])):,}",
                color=line.get_color(),
                xytext=(0, 8),
                fontsize=8,
            )

    axes[1].set_title("Photovoltaic deployment")
    axes[1].set_ylabel("Installed PV panels")

    if columns["BESS"] in df.columns:
        values = _numeric(df[columns["BESS"]]).ffill()
        line, = axes[2].step(
            iteration,
            values,
            where="post",
            marker="o",
            linewidth=1.8,
        )
        valid = values.dropna()
        if not valid.empty:
            _annotate_xy(
                axes[2],
                float(iteration[-1]),
                float(valid.iloc[-1]),
                f"{int(round(valid.iloc[-1])):,}",
                color=line.get_color(),
                xytext=(0, 8),
                fontsize=8,
            )

    axes[2].set_title("Battery storage deployment")
    axes[2].set_ylabel("Installed BESS units")

    for ax in axes:
        ax.set_xlabel("LBBD iteration")
        ax.set_xticks(iteration)
        ax.set_xticklabels([str(int(v)) for v in iteration])
        ax.margins(x=0.07, y=0.16)

    fig.suptitle(title, y=0.98)
    fig.subplots_adjust(
        left=0.07,
        right=0.98,
        bottom=0.16,
        top=0.84,
        wspace=0.30,
    )

    return _save(fig,figures_dir, "20_lbbd_infrastructure_evolution", dpi)


def _plot_lbbd_iteration_timing(run_dir: Path, figures_dir: Path, dpi: int) -> list[str]:
    df = _load_lbbd_history(run_dir)
    if "master_solve_seconds" not in df.columns or "elapsed_seconds" not in df.columns:
        raise ValueError("LBBD history lacks timing diagnostics")
    iteration = _numeric(df["iteration"]).astype(int).to_numpy()
    master = _numeric(df["master_solve_seconds"]).fillna(0.0).to_numpy(dtype=float, copy=True)
    elapsed = _numeric(df["elapsed_seconds"]).ffill().fillna(0.0).to_numpy(dtype=float)
    iteration_total = np.diff(np.concatenate(([0.0], elapsed)))
    timing = _lbbd_metadata(run_dir).get("computational_complexity", {}).get("phase_timing", {})
    end_to_end = timing.get("total_runtime_seconds")
    outer_duration = timing.get("decomposition_solve_seconds")
    fig, ax = plt.subplots(figsize=(11.5, 6.1))
    if end_to_end is not None and outer_duration is not None:
        outer = float(outer_duration)
        finalization = float(timing.get("export_seconds", 0)) + float(timing.get("figure_generation_seconds", 0))
        pre_loop = float(end_to_end) - outer - finalization
        if pre_loop < -1.0 or abs(outer - float(elapsed[-1])) > 2.0:
            raise ValueError("LBBD timing phases do not reconcile with iteration history")
        master[0] = 0.0 if str(df.iloc[0].get("candidate_source", "")) == "lp_bootstrap" else master[0]
        if np.any(master > iteration_total + 1.0):
            raise ValueError("Master MIP duration exceeds the corresponding iteration duration")
        other = np.maximum(0.0, iteration_total - master)
        phases = np.arange(len(iteration) + 2)
        setup = np.concatenate(([max(0.0, pre_loop)], np.zeros(len(iteration) + 1)))
        mip = np.concatenate(([0.0], master, [0.0]))
        auxiliary = np.concatenate(([0.0], other, [0.0]))
        finish = np.concatenate((np.zeros(len(iteration) + 1), [finalization]))
        ax.bar(phases, setup / 3600.0, width=0.69, label="Pre-loop (input, model build, LP bootstrap)", color="#8c8c8c")
        ax.bar(phases, mip / 3600.0, width=0.69, label="Master MIP", color="#4c78a8")
        ax.bar(phases, auxiliary / 3600.0, bottom=mip / 3600.0, width=0.69, label="Other outer work (LP, exact MIP, cuts)", color="#f58518")
        ax.bar(phases, finish / 3600.0, width=0.69, label="Final export and figures", color="#54a24b")
        total = setup + mip + auxiliary + finish
        ax.set_xticks(phases, ["Pre-loop"] + [str(v) for v in iteration] + ["Finalize"])
        ax.set_ylabel("Phase duration (hours)")
        ax2 = ax.twinx()
        line, = ax2.plot(phases, np.cumsum(total) / 3600.0, marker="o", linestyle="--", linewidth=2.0, color="#d62728", label="Cumulative end-to-end time")
        ax2.set_ylabel("Cumulative end-to-end time (hours)")
        ax2.grid(False)
        ax.text(0.02, 0.97, f"Total {float(end_to_end) / 3600.0:.2f} h", transform=ax.transAxes, va="top", fontsize=9)
        ax.set_title("LBBD runtime by execution phase")
    else:
        # Older run folders do not always contain a full phase-timing record.
        other = np.maximum(0.0, iteration_total - master)
        phases = np.arange(len(iteration))
        ax.bar(phases, master / 3600.0, label="Reported master-solve attribution")
        ax.bar(phases, other / 3600.0, bottom=master / 3600.0, label="Other iteration work")
        ax.set_xticks(phases, iteration.astype(str))
        ax.set_ylabel("Reported iteration duration (hours)")
        ax2 = ax.twinx()
        line, = ax2.plot(phases, elapsed / 3600.0, marker="o", linestyle="--", label="Cumulative outer-loop time")
        ax2.set_ylabel("Cumulative outer-loop time (hours)")
        ax2.grid(False)
        ax.set_title("LBBD outer-loop timing (pre-loop timing unavailable)")
    ax.set_xlabel("Execution phase / LBBD iteration")
    h1, l1 = ax.get_legend_handles_labels()
    _boxed_legend_below(fig, h1 + [line], l1 + [line.get_label()], ncol=3, bottom=0.23)
    return _save(fig, figures_dir, "21_lbbd_iteration_timing", dpi)


def _is_monolithic_run(run_dir: Path) -> bool:
    scalars = _read_csv(run_dir / "results" / "computational_complexity_scalars.csv")
    if not scalars.empty and "Method" in scalars.columns:
        return str(scalars.iloc[0]["Method"]).strip().lower() == "monolithic"
    return "slackpenalty" in run_dir.name.lower()


def _plot_monolithic_runtime(run_dir: Path, figures_dir: Path, dpi: int) -> list[str]:
    metadata = _lbbd_metadata(run_dir).get("computational_complexity", {})
    timing = dict(metadata.get("phase_timing", {}) or {})
    resources = dict(metadata.get("resource_usage", {}) or {})
    scalars = _read_csv(run_dir / "results" / "computational_complexity_scalars.csv")
    if {"Metric", "Value"}.issubset(scalars.columns):
        for row in scalars.itertuples(index=False):
            if getattr(row, "Source", "") == "phase_timing":
                timing.setdefault(str(row.Metric), row.Value)
            elif getattr(row, "Source", "") == "resource_monitor":
                resources.setdefault(str(row.Metric), row.Value)

    def finite_nonnegative(value: object) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) and number >= 0.0 else None

    total = finite_nonnegative(timing.get("total_runtime_seconds"))
    solve = finite_nonnegative(timing.get("solve_seconds"))
    if total is None or solve is None or total <= 0:
        raise ValueError("Completed monolithic phase timing is unavailable; regenerate after complexity export")
    phase_specs = [
        ("Input", "input_load_seconds", "#4c78a8"),
        ("Preprocess", "preprocessing_seconds", "#72b7b2"),
        ("Build", "model_build_seconds", "#f2cf5b"),
        ("Solve", "solve_seconds", "#f58518"),
        ("Export", "export_seconds", "#54a24b"),
        ("Infrastructure regularization", "infrastructure_regularization_seconds", "#b279a2"),
        ("Figures", "figure_generation_seconds", "#9d755d"),
    ]
    durations = [(label, finite_nonnegative(timing.get(key)) or 0.0, color) for label, key, color in phase_specs]
    recorded = sum(seconds for _, seconds, _ in durations)
    if recorded > total + max(30.0, total * 0.001):
        raise ValueError("Monolithic phase durations exceed recorded end-to-end runtime")
    remainder = max(0.0, total - recorded)
    if remainder > 0:
        durations.append(("Other", remainder, "#a0a0a0"))

    trace = _read_csv(run_dir / "results" / "resource_usage.csv")
    if {"elapsed_seconds", "process_tree_rss_MB"}.issubset(trace.columns):
        elapsed = _numeric(trace["elapsed_seconds"]).to_numpy(dtype=float)
        rss = _numeric(trace["process_tree_rss_MB"]).to_numpy(dtype=float) / 1024.0
        valid = np.isfinite(elapsed) & np.isfinite(rss) & (elapsed >= 0) & (rss >= 0)
        elapsed, rss = elapsed[valid], rss[valid]
    else:
        elapsed, rss = np.array([]), np.array([])
    if len(elapsed):
        fig, (ax_time, ax_minor, ax_detail) = plt.subplots(
            3, 1, figsize=(11.2, 8.3), gridspec_kw={"height_ratios": [0.7, 1.2, 1.8]}
        )
    else:
        fig, (ax_time, ax_minor) = plt.subplots(
            2, 1, figsize=(11.2, 6.0), gridspec_kw={"height_ratios": [0.7, 1.5]}
        )
        ax_detail = None
    cursor = 0.0
    for label, seconds, color in durations:
        if seconds > 0:
            ax_time.barh(0, seconds / 3600.0, left=cursor / 3600.0, height=0.55, color=color, label=label)
        cursor += seconds
    ax_time.set_xlim(0, max(total, cursor) / 3600.0 * 1.04)
    ax_time.set_yticks([])
    ax_time.set_xlabel("End-to-end elapsed time (hours)")
    ax_time.set_title("Run phases; solver call includes Pyomo/Gurobi interface time", loc="left")
    ax_time.grid(axis="y", visible=False)

    short = [(label, seconds / 60.0, color) for label, seconds, color in durations if label != "Solve" and seconds > 0]
    if short:
        ax_minor.barh([item[0] for item in short], [item[1] for item in short], color=[item[2] for item in short])
        ax_minor.invert_yaxis()
        ax_minor.set_xlim(0, max(item[1] for item in short) * 1.15)
    ax_minor.set_xlabel("Duration (minutes)")
    ax_minor.set_title("Input, preparation, and output phases", loc="left")

    if ax_detail is not None:
        stride = max(1, math.ceil(len(elapsed) / 4000))
        sampled = np.unique(np.append(np.arange(0, len(elapsed), stride), len(elapsed) - 1))
        ax_detail.plot(elapsed[sampled] / 3600.0, rss[sampled], color="#4c78a8", linewidth=1.25)
        peak_mb = finite_nonnegative(resources.get("peak_process_tree_rss_MB"))
        peak = max(float(np.max(rss)), peak_mb / 1024.0 if peak_mb is not None else 0.0)
        ax_detail.text(0.02, 0.96, f"Peak process-tree RSS: {peak:.1f} GiB", transform=ax_detail.transAxes, va="top", bbox={"facecolor": "white", "alpha": 0.85, "edgecolor": "none"})
        ax_detail.set_xlim(0, max(total, float(np.max(elapsed))) / 3600.0)
        ax_detail.set_xlabel("Elapsed time (hours)")
        ax_detail.set_ylabel("Process-tree RSS (GiB)")
        ax_detail.set_title("Measured process memory; distinct from Gurobi SoftMemLimit", loc="left")

    certificate_path = run_dir / "results" / "solver_certificate.json"
    certificate = json.loads(certificate_path.read_text(encoding="utf-8")) if certificate_path.exists() else {}
    status = str(certificate.get("termination_reason", "unreported")).replace("_", " ")
    gap = finite_nonnegative(certificate.get("gurobi_mip_gap"))
    gap_text = f" | achieved MIP gap {100.0 * gap:.4f}%" if gap is not None else ""
    fig.suptitle("Monolithic runtime and resource usage", y=0.98)
    fig.text(0.08, 0.91, f"Total {total / 3600.0:.2f} h | solve {solve / 3600.0:.2f} h | termination: {status}{gap_text}", fontsize=10)
    handles, labels = ax_time.get_legend_handles_labels()
    _boxed_legend_below(fig, handles, labels, ncol=4, bottom=0.17)
    fig.subplots_adjust(left=0.12, right=0.96, top=0.82, hspace=0.78)
    return _save(fig, figures_dir, "25_monolithic_runtime_and_memory", dpi)


def _plot_resource_memory(run_dir: Path, figures_dir: Path, dpi: int) -> list[str]:
    figures_dir.mkdir(parents=True, exist_ok=True)
    trace = _read_csv(run_dir / "results" / "resource_usage.csv", required=True)
    required = {"elapsed_seconds", "process_tree_rss_MB"}
    if not required.issubset(trace.columns):
        raise ValueError("Resource trace lacks elapsed_seconds or process_tree_rss_MB")
    trace = trace.copy()
    trace["elapsed_seconds"] = _numeric(trace["elapsed_seconds"])
    trace["rss_gib"] = _numeric(trace["process_tree_rss_MB"]) / 1024.0
    trace = trace.loc[
        np.isfinite(trace["elapsed_seconds"]) & np.isfinite(trace["rss_gib"])
        & (trace["elapsed_seconds"] >= 0) & (trace["rss_gib"] >= 0)
    ].sort_values("elapsed_seconds").reset_index(drop=True)
    if len(trace) < 2:
        raise ValueError("Resource trace has fewer than two valid RSS samples")

    metadata = _lbbd_metadata(run_dir)
    complexity = metadata.get("computational_complexity", {})
    resources = complexity.get("resource_usage", {}) or {}
    settings = metadata.get("effective_settings", {}) or {}
    scalars = _read_csv(run_dir / "results" / "computational_complexity_scalars.csv")
    scalar_values = dict(zip(scalars["Metric"].astype(str), scalars["Value"])) if {"Metric", "Value"}.issubset(scalars.columns) else {}

    def number(value: object) -> float | None:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) and result >= 0 else None

    t = trace["elapsed_seconds"].to_numpy(dtype=float) / 3600.0
    rss = trace["rss_gib"].to_numpy(dtype=float)
    trace_peak = float(rss.max())
    monitor_peak_mb = number(resources.get("peak_process_tree_rss_MB", scalar_values.get("peak_process_tree_rss_MB")))
    monitor_peak = monitor_peak_mb / 1024.0 if monitor_peak_mb is not None else None
    soft_limit = number(settings.get("soft_mem_limit_gb", scalar_values.get("soft_mem_limit_gb")))
    node_start = number(settings.get("nodefile_start", scalar_values.get("nodefile_start_gb")))
    master_threads = number(settings.get("threads", scalar_values.get("solver_threads_requested")))
    recourse_threads = number(settings.get("subproblem_threads"))
    node_calls = []
    for path in sorted((run_dir / "logs").glob("*.log")):
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            if any("Created node file directory" in line for line in stream):
                node_calls.append(path.stem)

    history = _read_csv(run_dir / "results" / "lbbd_history.csv")
    if {"iteration", "elapsed_seconds"}.issubset(history.columns):
        ends = history[["iteration", "elapsed_seconds"]].copy()
        ends["iteration"] = _numeric(ends["iteration"])
        ends["elapsed_seconds"] = _numeric(ends["elapsed_seconds"])
        ends = ends.dropna().sort_values("elapsed_seconds")
        ends = ends.loc[ends["elapsed_seconds"].between(0, float(trace["elapsed_seconds"].iloc[-1]) + 60)]
    else:
        ends = pd.DataFrame(columns=["iteration", "elapsed_seconds"])

    if ends.empty:
        fig, ax = plt.subplots(figsize=(11.5, 5.7))
        ax_intervals = None
    else:
        fig, (ax, ax_intervals) = plt.subplots(
            2, 1, figsize=(11.5, 8.0), sharex=False,
            gridspec_kw={"height_ratios": [2.5, 1.1]},
        )
    if len(trace) > 6000:
        bin_index = np.arange(len(trace)) * 2500 // len(trace)
        groups = trace.groupby(bin_index)["rss_gib"]
        selected = np.unique(np.concatenate(([0, len(trace) - 1], groups.idxmin().to_numpy(), groups.idxmax().to_numpy())))
    else:
        selected = np.arange(len(trace))
    ax.plot(t[selected], rss[selected], color="#35618a", linewidth=0.95, label="Process-tree RSS (saved trace)")
    peak_idx = int(rss.argmax())
    ax.scatter([t[peak_idx]], [trace_peak], s=29, color="#b14739", zorder=5,
               label=f"Saved-trace peak {trace_peak:.1f} GiB")
    if monitor_peak is not None and monitor_peak > trace_peak + 0.05:
        ax.axhline(monitor_peak, color="#b14739", linestyle=":", linewidth=1.15,
                   label=f"Faster-monitor peak {monitor_peak:.1f} GiB")
    for row in ends.itertuples(index=False):
        end_h = float(row.elapsed_seconds) / 3600.0
        ax.axvline(end_h, color="#7d806d", linestyle="--", linewidth=0.8, alpha=0.6)
        ax.text(end_h, 0.97, f"I{int(row.iteration)}", transform=ax.get_xaxis_transform(),
                ha="right", va="top", fontsize=8, rotation=90)
    ax.set_xlim(0, max(float(t[-1]), 0.001) * 1.015)
    ax.set_ylim(bottom=0)
    ax.set_ylabel("Process-tree RSS (GiB)")
    ax.set_xlabel("Elapsed run time (hours)")
    ax.set_title("Measured resident memory; dashed markers denote completed LBBD iterations", loc="left")
    ax.legend(loc="upper left", fontsize=8, framealpha=0.94)

    if ax_intervals is not None:
        interval_rows = []
        previous = 0.0
        for row in ends.itertuples(index=False):
            end = float(row.elapsed_seconds)
            if end <= previous:
                continue
            portion = trace.loc[(trace["elapsed_seconds"] >= previous) & (trace["elapsed_seconds"] < end), "rss_gib"]
            if len(portion):
                interval_rows.append((f"Start–I{int(row.iteration)}" if not interval_rows else f"I{int(row.iteration)}",
                                      previous / 3600.0, end / 3600.0, float(portion.median()), float(portion.max()), len(portion)))
            previous = end
        if previous < float(trace["elapsed_seconds"].iloc[-1]):
            portion = trace.loc[trace["elapsed_seconds"] >= previous, "rss_gib"]
            if len(portion):
                interval_rows.append(("Finalization", previous / 3600.0,
                                      float(trace["elapsed_seconds"].iloc[-1]) / 3600.0,
                                      float(portion.median()), float(portion.max()), len(portion)))
        if interval_rows:
            summary = pd.DataFrame(interval_rows, columns=["interval", "start_hour", "end_hour", "median_trace_rss_GiB", "peak_trace_rss_GiB", "sample_count"])
            summary.to_csv(figures_dir / "26_memory_interval_summary.csv", index=False)
            positions = np.arange(len(summary))
            ax_intervals.bar(positions, summary["peak_trace_rss_GiB"], color="#b7cad9", label="Peak in saved trace")
            ax_intervals.bar(positions, summary["median_trace_rss_GiB"], width=0.54, color="#35618a", label="Median in saved trace")
            ax_intervals.set_xticks(positions, summary["interval"], fontsize=9)
            ax_intervals.set_ylabel("RSS (GiB)")
            ax_intervals.set_title("Recorded intervals (first includes initialization and bootstrap)", loc="left")
            ax_intervals.legend(loc="upper right", ncol=2, fontsize=8)

    median = float(np.median(rss))
    p95 = float(np.quantile(rss, 0.95))
    cadence = float(np.median(np.diff(trace["elapsed_seconds"])))
    peak_label = f"Monitor peak {monitor_peak:.1f} GiB" if monitor_peak is not None else "Monitor peak unavailable"
    settings_text = ", ".join(filter(None, [
        f"NodefileStart {node_start:g} GB (configured)" if node_start is not None else None,
        f"SoftMemLimit {soft_limit:g} GB (Gurobi allocation)" if soft_limit is not None else None,
        f"threads {int(master_threads)}/{int(recourse_threads)} master/recourse" if master_threads is not None and recourse_threads is not None else None,
    ]))
    fig.suptitle("Memory use during optimization", fontsize=16, y=0.98)
    fig.text(0.10, 0.095,
             f"{peak_label}; saved trace: peak {trace_peak:.1f}, median {median:.1f}, P95 {p95:.1f} GiB; median sample interval {cadence:.1f} s.\n"
             f"{settings_text or 'Solver memory settings unavailable'}. Node-file directory creation reported by {len(node_calls)} solver log(s)"
             + (f" ({', '.join(node_calls[:3])}{'…' if len(node_calls) > 3 else ''})." if node_calls else ".")
             + "\nNode-file disk usage was not sampled. A fall in RSS does not establish a node-file or code-saving effect."
             + (" All saved phase labels are 'run'." if "phase" in trace.columns and trace["phase"].nunique() == 1 and str(trace["phase"].iloc[0]) == "run" else ""),
             fontsize=8.7, va="top")
    fig.subplots_adjust(left=0.10, right=0.97, top=0.89, bottom=0.18,
                        hspace=0.48 if ax_intervals is not None else 0.2)
    return _save(fig, figures_dir, "26_process_memory_profile", dpi)


def _plot_lbbd_gap_diagnostics(run_dir: Path, figures_dir: Path, dpi: int) -> list[str]:
    df = _load_lbbd_history(run_dir)
    iteration = _numeric(df["iteration"])
    master_col = "master_mip_gap" if "master_mip_gap" in df.columns else "master_internal_gap"
    series = [
        ("lbbd_gap", "Certified global LBBD gap"),
        (master_col, "Achieved master MIP gap (incumbent solves only)"),
        ("candidate_fixed_gap", "Fixed-layout exact MIP gap"),
    ]
    present = [(column, label) for column, label in series if column in df.columns and _numeric(df[column]).notna().any()]
    if not present:
        raise ValueError("LBBD history lacks gap diagnostics")
    fig, ax = plt.subplots(figsize=(10.4, 6.2))
    for column, label in present:
        values = 100.0 * _numeric(df[column])
        if column == master_col and "master_gap_is_mip" in df.columns:
            values = values.where(_numeric(df["master_gap_is_mip"]).fillna(0) > 0.5)
        if column == "candidate_fixed_gap" and "candidate_cached" in df.columns:
            values = values.where(_numeric(df["candidate_cached"]).fillna(0) < 0.5)
        positive = values.where(values > 0)
        if positive.notna().any():
            if column == "lbbd_gap":
                ax.semilogy(iteration, positive, marker="o", linewidth=1.8, label=label)
            else:
                ax.scatter(iteration, positive, s=54, marker="D" if column == master_col else "o", color="#54a24b" if column == master_col else "#f58518", label=label, zorder=5)
    ax.set_xticks(iteration)
    ax.set_xlabel("LBBD iteration")
    ax.set_ylabel("Gap (%) — logarithmic scale")
    ax.set_title("LBBD and Gurobi gaps (different denominators)")
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
    if "candidate_source" in df.columns:
        requested = requested.where(~df["candidate_source"].astype(str).eq("lp_bootstrap"))
    master_col = "master_mip_gap" if "master_mip_gap" in df.columns else "master_internal_gap"
    master_actual = (
        100.0 * _numeric(df[master_col])
        if master_col in df.columns else pd.Series(np.nan, index=df.index)
    )
    if "master_gap_is_mip" in df.columns:
        master_actual = master_actual.where(_numeric(df["master_gap_is_mip"]).fillna(0) > 0.5)

    fig, ax = plt.subplots(figsize=(10.9, 5.9))
    for values, label, style in [
        (certified, "Certified LBBD gap", "-"),
        (requested, "Requested master MIP gap", "--"),
        (master_actual, "Achieved master MIP gap", ":"),
    ]:
        positive = values.where(values > 0)
        if positive.notna().any():
            if label == "Achieved master MIP gap":
                ax.scatter(iteration, positive, s=72, marker="D", label=label, zorder=6, color="#54a24b")
            else:
                line, = ax.semilogy(iteration, positive, marker="o", linewidth=1.9, linestyle=style, label=label)

    plotted_values = pd.concat([certified, requested, master_actual], axis=0).dropna()
    plotted_values = plotted_values[plotted_values > 0]
    if not plotted_values.empty:
        ax.set_ylim(float(plotted_values.min()) / 1.55, float(plotted_values.max()) * 1.85)
    ax.margins(x=0.10)
    ax.set_xlabel("LBBD iteration")
    ax.set_xticks(iteration)
    ax.set_xticklabels(_lbbd_source_labels(df))
    ax.set_ylabel("Gap (%) — logarithmic scale")
    ax.set_title("Adaptive LBBD master control (MIP gaps where available)", pad=12)

    if master_actual.notna().any():
        valid = master_actual.dropna()
        for idx, value in valid.items():
            ax.annotate(f"{value:.4f}%", (iteration.loc[idx], value), xytext=(15, -16), textcoords="offset points", ha="left", fontsize=9, color="#328a39")
    ax.text(0.98, 0.97, "Achieved MIP gap requires an incumbent and bound\nfrom the same master solve", transform=ax.transAxes, ha="right", va="top", fontsize=8)
    handles, labels = ax.get_legend_handles_labels()
    _boxed_legend_below(fig, handles, labels, ncol=3, bottom=0.25)
    return _save(fig, figures_dir, "23_lbbd_adaptive_master_control", dpi)

def _plot_lbbd_candidate_reuse(run_dir: Path, figures_dir: Path, dpi: int) -> list[str]:
    df = _load_lbbd_history(run_dir)
    required = {"iteration", "candidate_cached", "candidate_repeat_count", "new_cuts_total"}
    if not required.issubset(df.columns):
        raise ValueError("LBBD history lacks candidate-cache diagnostics")
    iteration = _numeric(df["iteration"]).astype(int).to_numpy()
    cached = _numeric(df["candidate_cached"]).fillna(0.0).clip(0, 1).to_numpy(dtype=float)
    bound_only = df.get("candidate_source", pd.Series("", index=df.index)).astype(str).str.contains("bound_only").to_numpy(dtype=bool)
    evaluated = np.where(bound_only, 0.0, 1.0 - cached)
    reused = np.where(bound_only, 0.0, cached)
    cuts = _numeric(df["new_cuts_total"]).fillna(0.0).to_numpy(dtype=float)
    x = np.arange(len(iteration))

    fig, ax = plt.subplots(figsize=(10.7, 6.2))
    ax.bar(x, evaluated, label="New exact certification in history", width=0.70)
    ax.bar(x, reused, bottom=evaluated, label="Cached exact result reused", width=0.70)
    ax.bar(x, bound_only.astype(float), bottom=evaluated + reused, label="Bound-only closure (no exact solve)", width=0.70)
    ax.set_xticks(x)
    ax.set_xticklabels(iteration.astype(str))
    ax.set_xlabel("LBBD iteration")
    ax.set_ylabel("Outer-iteration event")
    ax.set_ylim(0, 1.25)
    ax.set_title("LBBD candidate handling and outer-iteration cuts")

    ax2 = ax.twinx()
    cut_line, = ax2.plot(x, cuts, marker="s", linestyle="--", linewidth=1.8, color="#d62728", label="Outer-iteration cuts added")
    ax2.set_ylabel("Count")
    ax2.set_ylim(0, max(1.4, 1.35 * float(cuts.max(initial=0))))
    ax2.grid(False)
    exact_roles = _lbbd_metadata(run_dir).get("computational_complexity", {}).get("solver_log_roles", [])
    exact_calls = next((int(v["Solver calls"]) for v in exact_roles if v.get("Model role") == "exact_annual_oracle"), None)
    if exact_calls is not None and exact_calls > int(evaluated.sum()):
        ax.text(0.02, 0.96, f"{exact_calls} exact MIP calls in total; repair calls may occur within an iteration", transform=ax.transAxes, ha="left", va="top", fontsize=8)
    h1, l1 = ax.get_legend_handles_labels()
    _boxed_legend_below(fig, h1 + [cut_line], l1 + ["Outer-iteration cuts added"], ncol=2, bottom=0.25)
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
    gdf = gdf.dropna(subset=["HexID", "geometry"])
    if (gdf["HexID"] % 1 != 0).any():
        raise ValueError(f"Noninteger HexID in geometry file: {path}")
    duplicates = gdf[gdf.duplicated("HexID", keep=False)]
    for cell_id, group in duplicates.groupby("HexID"):
        shapes = group.geometry.tolist()
        if any(not shapes[0].equals(other) for other in shapes[1:]):
            raise ValueError(f"Conflicting polygons for HexID {int(cell_id)} in {path}")
    gdf = gdf.drop_duplicates("HexID")
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
    basemap_source: str = "auto",
) -> list[str]:
    if column not in merged.columns:
        raise ValueError(f"Missing map column: {column}")
    merged3857 = merged.to_crs(epsg=3857)
    base3857 = base.to_crs(epsg=3857)
    fig, ax = plt.subplots(figsize=(10.5, 10.5))
    base3857.boundary.plot(ax=ax, linewidth=0.15, alpha=0.15, color="0.35", zorder=1)
    _add_basemap(ax, alpha=basemap_alpha, source=basemap_source)
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


def _great_circle_km(p1, p2) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (p1.x, p1.y, p2.x, p2.y))
    dlon, dlat = lon2 - lon1, lat2 - lat1
    a = math.sin(dlat / 2.0) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    return 6371.0088 * 2.0 * math.asin(min(1.0, math.sqrt(max(0.0, a))))


def _plot_redirection_corridors(
    redir: pd.DataFrame,
    merged,
    base,
    figures_dir: Path,
    dpi: int,
    max_flow_arcs: int,
    month: str,
    basemap_alpha: float,
    basemap_source: str = "auto",
    distance_limit_km: float = 1.5,
) -> list[str]:
    required = {"from_HexID", "to_HexID", "Month", "Energy_kWh_day", "Distance_km"}
    if not required.issubset(redir.columns):
        raise ValueError(f"redirections.csv lacks columns: {sorted(required - set(redir.columns))}")
    sub = redir[redir["Month"].astype(str) == month].copy()
    if sub.empty:
        raise ValueError(f"No positive redirection flows for {month}")
    sub["Energy_kWh_day"] = pd.to_numeric(sub["Energy_kWh_day"], errors="coerce").fillna(0.0)
    sub["Distance_km"] = pd.to_numeric(sub["Distance_km"], errors="coerce")
    flows = (
        sub.groupby(["from_HexID", "to_HexID"], as_index=False)
        .agg(Energy_kWh_day=("Energy_kWh_day", "sum"),
             reported_distance_min_km=("Distance_km", "min"),
             reported_distance_max_km=("Distance_km", "max"))
        .query("Energy_kWh_day > 0")
    )
    if flows.empty:
        raise ValueError(f"No positive aggregated redirection corridors for {month}")

    merged3857 = merged.to_crs(epsg=3857)
    base3857 = base.to_crs(epsg=3857)
    cent = merged3857.set_index("HexID").geometry.centroid
    cent_geo = cent.to_crs(epsg=4326)
    chosen = set(flows.nlargest(max(1, int(max_flow_arcs)), "Energy_kWh_day").index)
    diagnostics = []
    rows = []
    for idx, row in flows.iterrows():
        i, j = int(row["from_HexID"]), int(row["to_HexID"])
        found = i in cent.index and j in cent.index
        reported = float(row["reported_distance_max_km"])
        metric = _great_circle_km(cent_geo.loc[i], cent_geo.loc[j]) if found else math.nan
        web = cent.loc[i].distance(cent.loc[j]) / 1000.0 if found else math.nan
        inconsistent = bool(
            math.isfinite(reported)
            and reported - float(row["reported_distance_min_km"]) > 0.001
        )
        over_limit = bool(math.isfinite(metric) and metric > distance_limit_km + 0.02)
        over_reported = bool(math.isfinite(metric) and math.isfinite(reported) and metric > reported + 0.10)
        flag = not found or not math.isfinite(reported) or inconsistent or over_limit or over_reported
        diagnostics.append({
            "from_HexID": i, "to_HexID": j,
            "Energy_kWh_day": float(row["Energy_kWh_day"]),
            "reported_distance_min_km": row["reported_distance_min_km"],
            "reported_distance_max_km": reported,
            "centroid_distance_km": metric,
            "web_mercator_span_km_not_ground_distance": web,
            "distance_limit_km": distance_limit_km,
            "missing_hex_geometry": not found,
            "inconsistent_reported_distance": inconsistent,
            "centroid_exceeds_limit": over_limit,
            "centroid_exceeds_reported_distance": over_reported,
            "requires_spatial_review": flag,
            "selected_for_map": idx in chosen,
        })
        if idx in chosen and found and not cent.loc[i].equals(cent.loc[j]):
            p1, p2 = cent.loc[i], cent.loc[j]
            rows.append((p1.x, p1.y, p2.x, p2.y, float(row["Energy_kWh_day"]), flag))
    audit_path = figures_dir / f"15_redirection_corridor_distance_audit_{month.lower()}.csv"
    pd.DataFrame(diagnostics).sort_values("Energy_kWh_day", ascending=False).to_csv(audit_path, index=False)
    flagged_count = sum(r[5] for r in rows)
    if flagged_count:
        print(f"WARNING: {flagged_count} plotted {month} redirection corridors need spatial review; see {audit_path.name}")
    if not rows:
        raise ValueError(f"No redirection corridors could be matched to geometry for {month}")

    weights = np.asarray([r[4] for r in rows], dtype=float)
    max_weight = max(float(weights.max()), 1e-12)
    fig, ax = plt.subplots(figsize=(12, 12))
    base3857.boundary.plot(ax=ax, color="0.45", linewidth=0.30, alpha=0.20, zorder=1)
    _add_basemap(ax, alpha=basemap_alpha, source=basemap_source)
    base3857.boundary.plot(ax=ax, color="0.35", linewidth=0.28, alpha=0.28, zorder=2)

    for fx, fy, tx, ty, energy, flagged in sorted(rows, key=lambda r: r[4]):
        lw = 0.6 + 3.6 * math.sqrt(max(energy, 0.0) / max_weight)
        arrow = FancyArrowPatch(
            (fx, fy),
            (tx, ty),
            arrowstyle="-|>",
            linewidth=lw,
            edgecolor="#b2182b" if flagged else "black",
            facecolor="#b2182b" if flagged else "lightgray",
            linestyle="--" if flagged else "-",
            mutation_scale=5.5 + 2.4 * lw,
            alpha=0.78,
            shrinkA=1.5,
            shrinkB=1.5,
            zorder=4 if flagged else 3,
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
    if flagged_count:
        legend_handles.append(Line2D([], [], color="#b2182b", linestyle="--", linewidth=2,
                                     label=f"Spatial review: {flagged_count} shown"))
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
    ax.set_title(f"{month}: redirected charging-demand corridors\nTop {len(rows)} origin–destination flows"
                 + (f"; {flagged_count} need distance review" if flagged_count else ""))
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
    basemap_source: str = "auto",
    distance_limit_km: float = 1.5,
) -> list[str]:
    base, merged = _merge_geometry(results_dir, geometry_path)
    outputs: list[str] = []
    outputs += _plot_choropleth(
        merged, base, "Total_public_capacity_kWh_slot", "Installed public charging capacity",
        "kWh per 30-minute slot", figures_dir, "11_map_public_charging_capacity", dpi,
        basemap_alpha=basemap_alpha, basemap_source=basemap_source,
    )
    outputs += _plot_choropleth(
        merged, base, "PV_panels", "Installed PV panels", "PV panels",
        figures_dir, "12_map_pv_installation", dpi,
        basemap_alpha=basemap_alpha, basemap_source=basemap_source,
    )
    outputs += _plot_choropleth(
        merged, base, "Battery_units", "Installed BESS units", "10-kWh BESS units",
        figures_dir, "13_map_bess_installation", dpi,
        basemap_alpha=basemap_alpha, basemap_source=basemap_source,
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
            basemap_source=basemap_source,
        )
        outputs += _plot_redirection_corridors(
            redir, merged, base, figures_dir, dpi, max_flow_arcs,
            month=redirection_month, basemap_alpha=basemap_alpha,
            basemap_source=basemap_source, distance_limit_km=distance_limit_km,
        )
    return outputs


def _write_figures_readme(figures_dir: Path) -> None:
    text = """# Generated optimization figures

Figures are generated automatically after successful monolithic, Benders, and LBBD result export.
PNG files use the run-level resolution setting (default: 300 dpi). The figure manifest records
which figure groups were generated, skipped, or failed.

## How to read the common result figures

- `01_economic_breakdown.png` separates annual revenue, grid electricity, redirection incentives,
  slack penalty, charger capex, and PV/BESS capex. Positive bars increase profit; negative bars reduce it.
- `02_charger_deployment_and_utilization.png` compares installed slow, medium, and fast chargers
  with the annual utilization of their available capacity.
- `03_monthly_energy_supply_mix.png` shows whether charger energy is supplied directly from the
  grid, directly from PV, or through battery discharge.
- `04_dispatch_<month>.png` gives the representative-day dispatch profile for selected months.
- `05_bess_soc_by_month.png` and `06_bess_operation_<month>.png` describe the linked BESS state of
  charge and charge/discharge operation. They are generated only when BESS output files exist.
- `07_redirection_month_time_heatmap.png` shows when redirected charging is used most strongly.
- `08_redirection_type_matrix.png` shows the origin charger-type to destination charger-type energy
  assignment in the exact exported solution.
- `10_slack_by_month.png` is generated only when positive unmet demand exists. A skipped slack figure
  normally means the optimized solution had zero positive slack.
- `11_map_public_charging_capacity.png` through `15_map_redirection_corridors_<month>.png` are spatial
  maps. CARTO raster tiles require a key in `CARTO_BASEMAP_API_KEY`. With no key, the default
  uses OpenStreetMap tiles if `contextily` supports custom request headers; otherwise vector
  geometry is retained. Source attribution must remain legible on published maps.
- `15_redirection_corridor_distance_audit_<month>.csv` checks every exported corridor in the
  selected month against hex-centroid great-circle distance. Red dashed arrows require spatial
  review; a mismatch does not establish which input is wrong. Web Mercator span is not ground
  distance. Check the model's shortest-path distance table and shapefile ID/CRS before publication.
- `16_demand_supply_balance_annual_average.png` compares home and public charging supply accounting.
- `25_monolithic_runtime_and_memory.png` shows recorded end-to-end monolithic run phases and
  process-tree RSS where available. Generate it again after the run has written its complexity
  metadata; it cannot use LBBD iteration timing for a monolithic solve.
- `26_process_memory_profile.png` shows measured process-tree RSS over time, including
  iteration-end markers and per-interval statistics where LBBD history exists. The monitor's
  faster peak is distinguished from the saved five-second trace peak. It reports solver memory
  settings and the solver calls that logged node-file-directory creation; node-file disk bytes
  were not monitored. The CSV's `process_tree_rss_MB` is bytes divided by 1024 squared, and is
  converted to GiB by dividing by another 1024. `26_memory_interval_summary.csv` contains
  the numerical interval values.
  Regenerate figures after `resource_usage.csv` and run complexity metadata have been exported.

## Additional seasonal and certification figures

- `31_seasonal_demand_heatmaps` retains the month and half-hour structure of public and residual-home demand.
- `32_solution_certificate` distinguishes feasible profit from its valid global upper bound.
- `33_exact_spatial_decomposition` reports independent site MILPs in no-redirection mode. Partial sums describe processed sites, not intermediate bounds for the entire city.
- `34_charger_utilization` compares annual utilization and service by charger technology.

## How to read decomposition figures

- `09_decomposition_convergence.png` is the main certificate plot. The upper-bound line is the valid
  global master bound. The lower-bound line is the best exact feasible incumbent. The dashed gap line
  is `(UB - LB) / max(1, |UB|)` in percent.

- `17_decomposition_cut_generation.png` separates accepted pre-loop cuts (root and LP-bootstrap Hall cuts, plus any static origin cuts) from cuts added in each outer iteration. The cumulative line includes both phases.
  `lbbd_cut_accounting.csv` lists the accepted counts by phase, iteration and family. Hall cuts preserve penalized unmet-demand slack.

- `18_lbbd_cut_families.png` includes all recorded LBBD cut families, including bootstrap Hall cuts, and displays zero-count families explicitly. Accepted inference cuts are distinct from Gurobi's internal cutting planes.

- `19_lbbd_candidate_bounds.png` shows the reported exact-certified iteration outcome, its fixed-infrastructure upper bound, the best certified incumbent, and fixed-infrastructure certification gap. A repair can cause more than one exact MIP call within an iteration; the history stores the final reported outcome. `lbbd_exact_evaluations.csv` separately lists every exact solver call extracted from the archived solver-log statistics, including raw slack-penalized trial objectives and repair objectives where available.

- `20_lbbd_infrastructure_evolution.png` shows the actual charger, photovoltaic-panel, and battery-unit counts of the best certified
  infrastructure across LBBD iterations.

- `21_lbbd_iteration_timing.png` shows pre-loop preparation and LP bootstrap, each outer iteration, and final export/figures as distinct phases. Its cumulative curve covers the complete end-to-end run. The LP-bootstrap solve is attributed to pre-loop rather than counted again as an iteration-1 master MIP.

- `22_lbbd_gap_diagnostics.png` compares the global LBBD gap, achieved master MIP gap where an incumbent and bound came from the same master solve, and exact fixed-layout gaps for newly certified outcomes. Cached or bound-only iterations do not create new fixed-layout gap points.

- `23_lbbd_adaptive_master_control.png` compares requested master MIP tolerance and genuine achieved master MIP gaps with the certified outer gap. The LP bootstrap has no requested MIP solve, while fallback and bound-only iterations have no achieved master MIP gap without a master incumbent.

- `24_lbbd_candidate_reuse.png` distinguishes a new exact-certified outcome, a cache hit, and a bound-only termination without a new exact solve. Its cut line counts outer-iteration additions only; the bootstrap cuts appear in figures 17 and 18.

## Regenerating figures

```powershell
python src\\visualize_results.py --run-dir "runs\\<RUN_FOLDER>" --dataset full --dpi 300 --redirection-map-month June
```
"""
    (figures_dir / "README_FIGURES.md").write_text(text, encoding="utf-8")



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



def _plot_month_slot_demand(results_dir: Path, figures_dir: Path, dpi: int) -> list[str]:
    hourly = _prepare_hourly(results_dir)
    columns = ["Demand_public_base_kWh_day", "Demand_home_kWh_day"]
    totals = hourly.groupby(["Month", "TimeIndex"], observed=False)[columns].sum()
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    for ax, column, title in zip(axes, columns, ["Public demand", "Residual home demand"]):
        table = totals[column].unstack("TimeIndex").reindex(index=MONTHS, columns=range(1, 49)).fillna(0)
        values = table.to_numpy() / 1000
        image = ax.imshow(values, aspect="auto", origin="lower", cmap="viridis",
                          vmin=0, vmax=float(values.max()) if values.max() > 0 else 1.0)
        ax.set_yticks(range(12), [m[:3] for m in MONTHS])
        ax.set_title(title)
        fig.colorbar(image, ax=ax, label="MWh per half-hour")
    axes[-1].set_xticks(np.arange(0, 48, 4), [f"{h:02d}:00" for h in range(0, 24, 2)])
    axes[-1].set_xlabel("Local clock as supplied in the model inputs")
    fig.tight_layout()
    return _save(fig, figures_dir, "31_seasonal_demand_heatmaps", dpi)


def _plot_solution_certificate(run_dir: Path, figures_dir: Path, dpi: int) -> list[str]:
    path = run_dir / "results" / "solver_certificate.json"
    if not path.exists():
        raise ValueError("No common solver certificate")
    certificate = json.loads(path.read_text(encoding="utf-8"))
    profit = certificate.get("objective_SEK")
    bound = certificate.get("valid_bound_SEK")
    if profit is None or bound is None:
        raise ValueError("A feasible objective and valid upper bound are required")
    gap = certificate.get("gurobi_mip_gap")
    target = certificate.get("requested_mip_gap")
    status = "Certified target reached" if gap is not None and target is not None and gap <= target + 1e-9 else "Target not certified"
    fig, axes = plt.subplots(1, 2, figsize=(10.8, 5))
    values = np.array([float(profit), float(bound)]) / 1e6
    axes[0].bar(["Feasible profit", "Valid upper bound"], values, color=["#54a24b", "#4c78a8"])
    for j, value in enumerate(values):
        axes[0].annotate(f"{value:,.4f}", (j, value), xytext=(0, 5), textcoords="offset points", ha="center")
    axes[0].set_ylabel("Annual net profit (million SEK)")
    axes[0].margins(y=0.15)
    axes[0].set_title(status)
    axes[1].axis("off")
    lines = [f"Termination: {certificate.get('termination_reason', 'unknown')}"]
    if gap is not None:
        lines.append(f"Certified relative gap: {100 * gap:.6f}%")
    if target is not None:
        lines.append(f"Requested relative gap: {100 * target:.6f}%")
    lines.append(f"Remaining objective uncertainty: {max(0, float(bound) - float(profit)):,.2f} SEK/year")
    if "sites_total" in certificate:
        lines.append(f"Exact site solves completed: {certificate['sites_completed']}/{certificate['sites_total']}")
    if certificate.get("regularization_enabled"):
        lines.append("Secondary objective: annualized asset cost")
        lines.append(f"Profit tolerance: {certificate['regularization_profit_tolerance_SEK']:g} SEK/year")
    axes[1].text(0.02, 0.85, "\n\n".join(lines), va="top", fontsize=10, wrap=True)
    fig.tight_layout()
    return _save(fig, figures_dir, "32_solution_certificate", dpi)


def _plot_spatial_decomposition(run_dir: Path, figures_dir: Path, dpi: int) -> list[str]:
    history = _read_csv(run_dir / "results" / "spatial_decomposition_history.csv", required=True)
    if history.empty or "profit_SEK" not in history:
        raise ValueError("No solved independent annual site MILPs")
    solved = history.loc[history["status"] == "solved"].copy()
    x = _numeric(solved["site_position"])
    lower = _numeric(solved["profit_SEK"])
    upper = _numeric(solved["upper_bound_SEK"])
    fig, axes = plt.subplots(2, 2, figsize=(11.5, 8))
    axes[0, 0].plot(x, lower.cumsum() / 1e6, label="Sum of feasible site profits")
    axes[0, 0].plot(x, upper.cumsum() / 1e6, linestyle="--", label="Sum of site upper bounds")
    axes[0, 0].set_ylabel("Cumulative annual profit (million SEK)")
    axes[0, 0].set_title("Bounds summed over processed sites\n(not citywide bounds before completion)")
    axes[0, 0].legend(fontsize=8)
    axes[0, 1].plot(x, 100 * _numeric(solved["primary_gap"]), color="#e45756")
    axes[0, 1].set_ylabel("Primary site MIP gap (%)")
    axes[0, 1].set_title("Independent exact annual solves")
    axes[1, 0].plot(x, _numeric(solved["primary_solve_seconds"]), label="Profit maximization")
    if "regularization_seconds" in solved:
        axes[1, 0].plot(x, _numeric(solved["regularization_seconds"]), label="Infrastructure regularization")
    axes[1, 0].set_ylabel("Solver wall time (seconds/site)")
    axes[1, 0].legend(fontsize=8)
    for charger in ["slow", "medium", "fast"]:
        axes[1, 1].plot(x, _numeric(solved[charger]).cumsum(), label=charger.capitalize())
    axes[1, 1].set_ylabel("Cumulative installed public chargers")
    axes[1, 1].legend(fontsize=8)
    for ax in axes.flat:
        ax.set_xlabel("Site processing order")
    fig.tight_layout()
    return _save(fig, figures_dir, "33_exact_spatial_decomposition", dpi)


def _plot_charger_utilization(results_dir: Path, figures_dir: Path, dpi: int) -> list[str]:
    energy = _read_csv(results_dir / "energy_by_charger_type.csv", required=True)
    selected = energy.loc[energy["DemandClass"] == "ALL"].copy()
    if selected.empty:
        raise ValueError("No annual charger utilization rows")
    fig, axes = plt.subplots(1, 2, figsize=(10.8, 4.8))
    labels = selected["ChargerType"].str.capitalize()
    axes[0].bar(labels, 100 * _numeric(selected["CapacityRatio_all_classes"]), color=["#4c78a8", "#f58518", "#e45756"])
    axes[0].set_ylabel("Annual energy / installed annual energy capacity (%)")
    axes[0].set_title("Charger utilization")
    axes[1].bar(labels, _numeric(selected["AnnualEnergy_kWh"]) / 1e6, color=["#4c78a8", "#f58518", "#e45756"])
    axes[1].set_ylabel("Energy served (GWh/year)")
    axes[1].set_title("Service by charger technology")
    fig.tight_layout()
    return _save(fig, figures_dir, "34_charger_utilization", dpi)


def generate_run_figures(
    run_dir: str | Path,
    project_root: str | Path | None = None,
    dataset: str | None = None,
    parking_shapefile: str | None = None,
    dpi: int = 300,
    max_flow_arcs: int = 150,
    redirection_map_month: str = "June",
    basemap_alpha: float = 0.28,
    basemap_source: str = "auto",
    redirection_distance_limit_km: float | None = None,
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
    geometry_path = _resolve_geometry(project_root, dataset, parking_shapefile, _infer_vipv_scenario(run_dir))
    if redirection_distance_limit_km is None:
        config_path = project_root / "config" / "model_config.json"
        config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
        redirection_distance_limit_km = float(config.get("max_redirection_distance_km", 1.5))
    if not math.isfinite(redirection_distance_limit_km) or redirection_distance_limit_km <= 0:
        raise ValueError("Redirection distance limit must be positive and finite")

    tasks: list[tuple[str, Callable[[], list[str]]]] = [
        ("economic_breakdown", lambda: _plot_economic_breakdown(results_dir, figures_dir, dpi)),
        ("charger_deployment", lambda: _plot_charger_deployment(results_dir, figures_dir, dpi)),
        ("monthly_energy", lambda: _plot_monthly_energy(results_dir, figures_dir, dpi)),
        ("input_pv_tou_profiles", lambda: _plot_input_pv_tou_profiles(results_dir, figures_dir, dpi)),
        ("seasonal_demand_profiles", lambda: _plot_seasonal_demand_profiles(results_dir, figures_dir, dpi)),
        ("seasonal_supply_profiles", lambda: _plot_seasonal_supply_profiles(results_dir, figures_dir, dpi)),
        ("seasonal_demand_heatmaps", lambda: _plot_month_slot_demand(results_dir, figures_dir, dpi)),
        ("solution_certificate", lambda: _plot_solution_certificate(run_dir, figures_dir, dpi)),
        ("charger_utilization", lambda: _plot_charger_utilization(results_dir, figures_dir, dpi)),
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
    if (results_dir / "spatial_decomposition_history.csv").exists():
        tasks.append(("exact_spatial_decomposition", lambda: _plot_spatial_decomposition(run_dir, figures_dir, dpi)))
        if not (results_dir / "lbbd_history.csv").exists():
            tasks = [(name, task) for name, task in tasks
                     if not name.startswith(("decomposition_", "lbbd_"))]
    if _is_monolithic_run(run_dir):
        tasks.append(("monolithic_runtime", lambda: _plot_monolithic_runtime(run_dir, figures_dir, dpi)))
    if (results_dir / "resource_usage.csv").exists():
        tasks.append(("resource_memory", lambda: _plot_resource_memory(run_dir, figures_dir, dpi)))
    if geometry_path is not None and geometry_path.exists():
        tasks.append(("spatial_maps", lambda: _plot_maps(
            results_dir,
            figures_dir,
            geometry_path,
            dpi,
            max_flow_arcs,
            redirection_month=redirection_map_month,
            basemap_alpha=basemap_alpha,
            basemap_source=basemap_source,
            distance_limit_km=redirection_distance_limit_km,
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
        finally:
            plt.close("all")
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
    parser.add_argument("--basemap-source", choices=["auto", "carto", "osm", "none"], default="auto")
    parser.add_argument("--redirection-distance-limit-km", type=float, default=None)
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
        basemap_source=args.basemap_source,
        redirection_distance_limit_km=args.redirection_distance_limit_km,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
