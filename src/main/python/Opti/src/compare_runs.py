#!/usr/bin/env python
"""Modified for the UrbanEV seasonal integration, 2026-10-22. See SOURCE_PROVENANCE.json."""
from __future__ import annotations

import argparse
import math
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from provenance import validate_comparison
from input_scenarios import VIPV_SCENARIOS, resolve_scenario_paths
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from computational_complexity import (
    collect_solver_log_detail,
    preprocessing_scalars,
    read_scalar_file,
    slot_redirection_complexity,
    summarize_solver_logs,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MONTH_DAYS = {
    "January": 31, "February": 28, "March": 31, "April": 30,
    "May": 31, "June": 30, "July": 31, "August": 31,
    "September": 30, "October": 31, "November": 30, "December": 31,
}

METHODS = ("Monolithic", "Benders", "LBBD")

MEMORY_TRACE_CANDIDATES = (
    Path("results/resource_usage.csv"),
    Path("results/resource_monitor.csv"),
    Path("results/memory_trace.csv"),
    Path("results/rss_trace.csv"),
    Path("logs/resource_usage.csv"),
    Path("logs/resource_monitor.csv"),
    Path("logs/memory_trace.csv"),
    Path("logs/rss_trace.csv"),
)

MEMORY_ELAPSED_COLUMNS = (
    "elapsed_seconds",
    "elapsed_s",
    "elapsed",
    "seconds",
    "time_seconds",
)

MEMORY_TIMESTAMP_COLUMNS = (
    "timestamp",
    "datetime",
    "sample_time",
    "wall_time",
)

MEMORY_RSS_MB_COLUMNS = (
    "process_tree_rss_MB",
    "process_tree_rss_mb",
    "total_rss_MB",
    "total_rss_mb",
    "rss_MB",
    "rss_mb",
)

MEMORY_RSS_GB_COLUMNS = (
    "process_tree_rss_GB",
    "process_tree_rss_gb",
    "total_rss_GB",
    "total_rss_gb",
    "rss_GB",
    "rss_gb",
)

MEMORY_RSS_BYTES_COLUMNS = (
    "process_tree_rss_bytes",
    "total_rss_bytes",
    "rss_bytes",
)

MEMORY_PHASE_COLUMNS = (
    "phase",
    "stage",
    "solver_role",
    "model_role",
)


def load_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def resolve_project_path(project_root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (project_root / path).resolve()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare monolithic, arc-witness Benders, and LBBD result folders."
    )
    parser.add_argument("--monolithic-run", default=None, help="Optional monolithic run folder.")
    parser.add_argument("--benders-run", default=None, help="Optional arc-witness Benders run folder.")
    parser.add_argument("--lbbd-run", default=None, help="Optional LBBD run folder.")
    parser.add_argument("--out", default=None, help="Optional output XLSX path.")
    parser.add_argument("--vipv-scenario", choices=VIPV_SCENARIOS, default=None)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--dataset", choices=["small", "full"], default=None)
    parser.add_argument("--scenario", choices=["with_redirection", "no_redirection"], default=None)
    parser.add_argument(
        "--skip-complexity-recompute", action="store_true",
        help="Do not reload project inputs to recompute exact preprocessing/redirection set sizes.",
    )
    parser.add_argument(
        "--monolithic-memory-trace",
        default=None,
        help="Optional CSV with elapsed time and process-tree RSS samples for the monolithic run.",
    )
    parser.add_argument(
        "--benders-memory-trace",
        default=None,
        help="Optional CSV with elapsed time and process-tree RSS samples for the Benders run.",
    )
    parser.add_argument(
        "--lbbd-memory-trace",
        default=None,
        help="Optional CSV with elapsed time and process-tree RSS samples for the LBBD run.",
    )
    args = parser.parse_args()
    if not any((args.monolithic_run, args.benders_run, args.lbbd_run)):
        parser.error("Provide at least one of --monolithic-run, --benders-run, or --lbbd-run.")
    return args


def _resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _number(value: Any) -> Any:
    if value is None:
        return math.nan
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return math.nan
    try:
        return float(text)
    except ValueError:
        return text


def _read_summary(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "results" / "model_summary.csv"
    if not path.exists():
        print(f"No feasible solution summary for {run_dir}; retaining its solver certificate.")
        return {}
    frame = pd.read_csv(path)
    if not {"Metric", "Value"}.issubset(frame.columns):
        raise ValueError(f"Expected Metric/Value columns in {path}")
    return {str(row.Metric): _number(row.Value) for row in frame.itertuples(index=False)}


def _read_csv_if_present(path: Path) -> pd.DataFrame | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return None


def _annual_public_demand(run_dir: Path) -> float:
    frame = _read_csv_if_present(run_dir / "results" / "hourly_energy.csv")
    if frame is None or "Demand_public_base_kWh_day" not in frame.columns:
        return math.nan
    if "Month" not in frame.columns:
        return math.nan
    days = frame["Month"].map(MONTH_DAYS).fillna(0)
    return float((pd.to_numeric(frame["Demand_public_base_kWh_day"], errors="coerce").fillna(0) * days).sum())


def _annual_slack(run_dir: Path) -> float:
    frame = _read_csv_if_present(run_dir / "results" / "slack.csv")
    if frame is None or frame.empty:
        return 0.0
    for column in ("Slack_kWh_annual", "AnnualSlack_kWh", "annual_slack_kWh"):
        if column in frame.columns:
            return float(pd.to_numeric(frame[column], errors="coerce").fillna(0).sum())
    return math.nan


def _active_redirection_arcs(run_dir: Path) -> float:
    frame = _read_csv_if_present(run_dir / "results" / "redirections.csv")
    if frame is None or frame.empty:
        return 0.0
    if "Energy_kWh_day" in frame.columns:
        return float((pd.to_numeric(frame["Energy_kWh_day"], errors="coerce").fillna(0).abs() > 1e-8).sum())
    return float(len(frame))


def _load_capacity_config(project_root: Path) -> dict[str, float]:
    import json

    path = project_root / "config" / "model_config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): float(v) for k, v in cfg["charger_capacity_kwh_per_slot"].items()}


def _enrich(metrics: dict[str, Any], run_dir: Path, capacity: dict[str, float]) -> dict[str, Any]:
    out = dict(metrics)
    infrastructure = _read_csv_if_present(run_dir / "results" / "infrastructure_by_hex.csv")
    for key, column in [("PV_panels_installed", "PV_panels"), ("battery_units_installed", "Battery_units")]:
        if not math.isfinite(float(out.get(key, math.nan))) and infrastructure is not None and column in infrastructure:
            values = pd.to_numeric(infrastructure[column], errors="raise")
            if values.isna().any() or not values.map(math.isfinite).all():
                raise ValueError(f"Non-finite infrastructure values in {column}: {run_dir}")
            out[key] = float(values.sum())
    if not math.isfinite(float(out.get("annual_public_demand_kWh", math.nan))):
        out["annual_public_demand_kWh"] = _annual_public_demand(run_dir)
    if not math.isfinite(float(out.get("annual_slack_kWh", math.nan))):
        out["annual_slack_kWh"] = _annual_slack(run_dir)
    if not math.isfinite(float(out.get("active_redirection_arcs", math.nan))):
        out["active_redirection_arcs"] = _active_redirection_arcs(run_dir)
    if not math.isfinite(float(out.get("public_charger_capacity_kWh_per_slot", math.nan))):
        out["public_charger_capacity_kWh_per_slot"] = sum(
            float(out.get(f"chargers_{kind}_installed", 0.0) or 0.0) * float(capacity[kind])
            for kind in ("slow", "medium", "fast")
        )
    demand = float(out.get("annual_public_demand_kWh", math.nan))
    redirected = float(out.get("energy_redirected_kWh", math.nan))
    if not math.isfinite(float(out.get("share_redirected_public_demand", math.nan))):
        out["share_redirected_public_demand"] = redirected / demand if demand > 0 else 0.0
    return out



def _read_json_if_present(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _infer_dataset(run_dirs: dict[str, Path], explicit: str | None) -> str:
    if explicit:
        return explicit
    for run_dir in run_dirs.values():
        candidates = [
            run_dir / "run_metadata.json",
            run_dir / "logs" / "benders_manifest.json",
            run_dir / "logs" / "lbbd_manifest.json",
        ]
        for path in candidates:
            value = _read_json_if_present(path).get("dataset")
            if value in {"small", "full"}:
                return str(value)
        lower = run_dir.name.lower()
        for value in ("small", "full"):
            if f"_{value}_" in lower:
                return value
    raise ValueError("Could not infer a common dataset; provide --dataset small or --dataset full.")


def _infer_scenario(run_dirs: dict[str, Path], explicit: str | None) -> str:
    if explicit:
        return explicit
    for run_dir in run_dirs.values():
        for path in [run_dir / "run_metadata.json", run_dir / "logs" / "benders_manifest.json"]:
            value = _read_json_if_present(path).get("scenario")
            if value in {"with_redirection", "no_redirection"}:
                return str(value)
        lower = run_dir.name.lower()
        if "no_redirection" in lower or "noredirection" in lower:
            return "no_redirection"
        if "with_redirection" in lower or "withredirection" in lower:
            return "with_redirection"
    return "with_redirection"


def _load_preprocessed_comparison_data(root: Path, dataset: str, scenario: str, vipv_scenario: str, context: dict) -> dict:
    from data_loader import load_inputs
    from preprocessing import preprocess
    model_cfg = context["assumptions"]["model_config"]
    paths = resolve_scenario_paths(root, dataset, vipv_scenario)
    raw = load_inputs(paths)
    if raw["provenance"]["files"] != context["provenance"]["files"]:
        raise ValueError("Local inputs no longer match the compared run; complexity cannot be recomputed from changed data.")
    data = preprocess(raw, model_cfg)
    data["dataset"] = dataset
    data["vipv_scenario"] = vipv_scenario
    if scenario == "no_redirection":
        data["allowed"] = []
        data["T_dict"] = {}
        data["allowed_st"] = []
        data["OUT"] = {}
        data["IN"] = {}
        data["ORIGIN_ST"] = []
        data["DEST_ST"] = []
    return data


def _infer_vipv_scenario(run_dirs: dict[str, Path], explicit: str | None) -> str:
    if explicit:
        return explicit
    for run_dir in run_dirs.values():
        for path in [run_dir / "run_metadata.json", run_dir / "logs" / "lbbd_manifest.json"]:
            value = _read_json_if_present(path).get("vipv_scenario")
            if value in VIPV_SCENARIOS:
                return str(value)
        summary = _read_summary(run_dir)
        value = summary.get("vipv_scenario")
        if value in VIPV_SCENARIOS:
            return str(value)
        for candidate in VIPV_SCENARIOS:
            if f"_{candidate.lower()}_" in run_dir.name.lower():
                return candidate
    return "noVIPV"



def _history_total_seconds(run_dir: Path) -> float:
    for path in [
        run_dir / "results" / "lbbd_history.csv",
        run_dir / "iterations" / "benders_iteration_history.csv",
    ]:
        frame = _read_csv_if_present(path)
        if frame is not None and "elapsed_seconds" in frame.columns:
            values = pd.to_numeric(frame["elapsed_seconds"], errors="coerce").dropna()
            if not values.empty:
                return float(values.max())
    meta = _read_json_if_present(run_dir / "run_metadata.json")
    for key in ("elapsed_seconds", "total_runtime_seconds"):
        try:
            value = float(meta.get(key))
            if math.isfinite(value):
                return value
        except Exception:
            pass
    return math.nan



def _column(frame: pd.DataFrame, names: tuple[str, ...]) -> str | None:
    lookup = {str(column).strip().lower(): str(column) for column in frame.columns}
    for name in names:
        column = lookup.get(name.lower())
        if column is not None:
            return column
    return None


def _read_memory_trace_file(path: Path, method: str) -> pd.DataFrame:
    frame = _read_csv_if_present(path)
    if frame is None or frame.empty:
        return pd.DataFrame()

    elapsed_col = _column(frame, MEMORY_ELAPSED_COLUMNS)
    timestamp_col = _column(frame, MEMORY_TIMESTAMP_COLUMNS)

    if elapsed_col is not None:
        elapsed = pd.to_numeric(frame[elapsed_col], errors="coerce")
    elif timestamp_col is not None:
        timestamp = pd.to_datetime(frame[timestamp_col], errors="coerce", utc=True)
        if timestamp.notna().sum() < 2:
            return pd.DataFrame()
        elapsed = (timestamp - timestamp.min()).dt.total_seconds()
    else:
        return pd.DataFrame()

    rss_mb_col = _column(frame, MEMORY_RSS_MB_COLUMNS)
    rss_gb_col = _column(frame, MEMORY_RSS_GB_COLUMNS)
    rss_bytes_col = _column(frame, MEMORY_RSS_BYTES_COLUMNS)

    if rss_mb_col is not None:
        rss_mb = pd.to_numeric(frame[rss_mb_col], errors="coerce")
    elif rss_gb_col is not None:
        rss_mb = pd.to_numeric(frame[rss_gb_col], errors="coerce") * 1024.0
    elif rss_bytes_col is not None:
        rss_mb = pd.to_numeric(frame[rss_bytes_col], errors="coerce") / (1024.0 ** 2)
    else:
        return pd.DataFrame()

    phase_col = _column(frame, MEMORY_PHASE_COLUMNS)
    if phase_col is not None:
        phase = frame[phase_col].fillna("").astype(str)
    else:
        phase = pd.Series([""] * len(frame), index=frame.index, dtype="object")

    out = pd.DataFrame(
        {
            "Method": method,
            "elapsed_seconds": elapsed,
            "process_tree_rss_MB": rss_mb,
            "Phase": phase,
            "Trace source": str(path),
        }
    )

    out = out.dropna(subset=["elapsed_seconds", "process_tree_rss_MB"])
    out = out[
        (out["elapsed_seconds"] >= 0.0)
        & (out["process_tree_rss_MB"] >= 0.0)
    ].copy()

    if out.empty:
        return out

    out = (
        out.sort_values("elapsed_seconds")
        .drop_duplicates(subset=["elapsed_seconds"], keep="last")
        .reset_index(drop=True)
    )

    elapsed_origin = float(out["elapsed_seconds"].iloc[0])
    out["elapsed_seconds"] = out["elapsed_seconds"] - elapsed_origin
    out["elapsed_minutes"] = out["elapsed_seconds"] / 60.0
    out["process_tree_rss_GB"] = out["process_tree_rss_MB"] / 1024.0

    duration = float(out["elapsed_seconds"].max())
    if duration > 0.0:
        out["normalized_elapsed"] = out["elapsed_seconds"] / duration
    else:
        out["normalized_elapsed"] = 0.0

    return out


def _discover_memory_trace(
    run_dir: Path,
    method: str,
    override: Path | None,
) -> tuple[pd.DataFrame, str]:
    candidates: list[Path] = []

    if override is not None:
        candidates.append(override)

    candidates.extend(run_dir / relative for relative in MEMORY_TRACE_CANDIDATES)

    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)

        if not resolved.exists():
            continue

        frame = _read_memory_trace_file(resolved, method)
        if not frame.empty:
            return frame, str(resolved)

    return pd.DataFrame(), ""


def _time_weighted_memory(frame: pd.DataFrame) -> tuple[float, float]:
    if frame is None or len(frame) < 2:
        return math.nan, math.nan

    elapsed = pd.to_numeric(frame["elapsed_seconds"], errors="coerce").to_numpy(dtype=float)
    rss = pd.to_numeric(frame["process_tree_rss_MB"], errors="coerce").to_numpy(dtype=float)

    valid = (
        pd.notna(elapsed)
        & pd.notna(rss)
    )
    elapsed = elapsed[valid]
    rss = rss[valid]

    if len(elapsed) < 2:
        return math.nan, math.nan

    integral_mb_seconds = 0.0
    total_seconds = 0.0

    for index in range(len(elapsed) - 1):
        dt = float(elapsed[index + 1] - elapsed[index])
        if dt <= 0.0:
            continue
        integral_mb_seconds += 0.5 * float(rss[index] + rss[index + 1]) * dt
        total_seconds += dt

    if total_seconds <= 0.0:
        return math.nan, math.nan

    weighted_mean_mb = integral_mb_seconds / total_seconds
    memory_time_gb_hours = integral_mb_seconds / (1024.0 * 3600.0)
    return weighted_mean_mb, memory_time_gb_hours


def _memory_frames(
    run_dirs: dict[str, Path],
    trace_overrides: dict[str, Path | None],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    traces: list[pd.DataFrame] = []

    for method in METHODS:
        run_dir = run_dirs.get(method)
        if run_dir is None:
            rows.append(
                {
                    "Method": method,
                    "Run available": False,
                    "Trace available": False,
                    "Trace source": "",
                }
            )
            continue

        scalars = read_scalar_file(run_dir)
        runtime = _first_scalar(scalars, "total_runtime_seconds")
        if not math.isfinite(runtime):
            runtime = _history_total_seconds(run_dir)

        scalar_peak = _first_scalar(scalars, "peak_process_tree_rss_MB")

        trace, source = _discover_memory_trace(
            run_dir,
            method,
            trace_overrides.get(method),
        )

        row: dict[str, Any] = {
            "Method": method,
            "Run available": True,
            "Trace available": not trace.empty,
            "Trace source": source,
            "Run runtime (s)": runtime,
            "Run runtime (min)": runtime / 60.0 if math.isfinite(runtime) else math.nan,
            "Scalar peak RSS (MB)": scalar_peak,
            "Scalar peak RSS (GB)": scalar_peak / 1024.0 if math.isfinite(scalar_peak) else math.nan,
        }

        if trace.empty:
            rows.append(row)
            continue

        traces.append(trace)

        sampled_peak = float(trace["process_tree_rss_MB"].max())
        duration = float(trace["elapsed_seconds"].max())
        intervals = pd.to_numeric(trace["elapsed_seconds"], errors="coerce").diff().dropna()
        weighted_mean, memory_time = _time_weighted_memory(trace)

        row.update(
            {
                "Samples": int(len(trace)),
                "Median sample interval (s)": (
                    float(intervals.median()) if not intervals.empty else math.nan
                ),
                "Trace duration (s)": duration,
                "Trace duration (min)": duration / 60.0,
                "Runtime coverage (fraction)": (
                    duration / runtime
                    if math.isfinite(runtime) and runtime > 0.0
                    else math.nan
                ),
                "Trace peak RSS (MB)": sampled_peak,
                "Trace peak RSS (GB)": sampled_peak / 1024.0,
                "Mean RSS (MB)": float(trace["process_tree_rss_MB"].mean()),
                "Median RSS (MB)": float(trace["process_tree_rss_MB"].median()),
                "P95 RSS (MB)": float(trace["process_tree_rss_MB"].quantile(0.95)),
                "Time-weighted mean RSS (MB)": weighted_mean,
                "Memory-time integral (GB h)": memory_time,
                "Trace peak difference vs scalar (fraction)": (
                    (sampled_peak - scalar_peak) / abs(scalar_peak)
                    if math.isfinite(scalar_peak) and abs(scalar_peak) > 1e-12
                    else math.nan
                ),
            }
        )
        rows.append(row)

    summary = pd.DataFrame(rows)
    trace_frame = (
        pd.concat(traces, ignore_index=True)
        if traces
        else pd.DataFrame()
    )
    return summary, trace_frame


def _write_rss_figure(
    memory_trace: pd.DataFrame,
    comparison_output: Path,
) -> list[Path]:
    if memory_trace is None or memory_trace.empty:
        return []

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        print(f"WARNING: Matplotlib is unavailable; RSS figure skipped: {exc}")
        return []

    fig, axes = plt.subplots(1, 2, figsize=(12.0, 4.8))

    plotted = 0
    for method in METHODS:
        subset = memory_trace[memory_trace["Method"] == method].copy()
        if subset.empty:
            continue

        subset = subset.sort_values("elapsed_seconds")
        axes[0].plot(
            subset["elapsed_minutes"],
            subset["process_tree_rss_GB"],
            label=method,
            linewidth=1.5,
        )
        axes[1].plot(
            100.0 * subset["normalized_elapsed"],
            subset["process_tree_rss_GB"],
            label=method,
            linewidth=1.5,
        )
        plotted += 1

    axes[0].set_xlabel("Elapsed time (min)")
    axes[0].set_ylabel("Process-tree RSS (GB)")
    axes[0].set_title("Absolute elapsed time")

    axes[1].set_xlabel("Elapsed run time (%)")
    axes[1].set_ylabel("Process-tree RSS (GB)")
    axes[1].set_title("Normalized elapsed time")

    for ax in axes:
        ax.grid(True, alpha=0.25)

    if plotted > 1:
        axes[1].legend(frameon=False)

    fig.suptitle("Process-tree resident memory over time")
    fig.tight_layout()

    pdf_path = comparison_output.with_name(
        comparison_output.stem + "_rss_vs_elapsed_time.pdf"
    )
    png_path = comparison_output.with_name(
        comparison_output.stem + "_rss_vs_elapsed_time.png"
    )

    fig.savefig(pdf_path, bbox_inches="tight")
    fig.savefig(png_path, dpi=300, bbox_inches="tight")
    plt.close(fig)

    return [pdf_path, png_path]


def _complexity_frames(run_dirs: dict[str, Path]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    all_detail = []
    all_summary = []
    scalar_by_method: dict[str, dict[str, Any]] = {}
    for method, run_dir in run_dirs.items():
        scalars = read_scalar_file(run_dir)
        if not math.isfinite(float(scalars.get("total_runtime_seconds", math.nan))):
            scalars["total_runtime_seconds"] = _history_total_seconds(run_dir)
        scalar_by_method[method] = scalars
        detail = collect_solver_log_detail(run_dir)
        if not detail.empty:
            detail.insert(0, "Method", method)
            all_detail.append(detail)
            summary = summarize_solver_logs(detail.drop(columns=["Method"]).copy())
            if not summary.empty:
                summary.insert(0, "Method", method)
                all_summary.append(summary)

    detail_frame = pd.concat(all_detail, ignore_index=True) if all_detail else pd.DataFrame()
    summary_frame = pd.concat(all_summary, ignore_index=True) if all_summary else pd.DataFrame()
    timing_keys = sorted(set().union(*[
        {key for key in metrics if key.endswith("_seconds")}
        for metrics in scalar_by_method.values()
    ]))
    timing_rows = []
    for key in timing_keys:
        row = {"Phase": key}
        for method in ("Monolithic", "Benders", "LBBD"):
            row[method] = scalar_by_method.get(method, {}).get(key, math.nan)
        timing_rows.append(row)
    timing_frame = pd.DataFrame(timing_rows)

    primary_role = {"Monolithic": "main_model", "Benders": "master", "LBBD": "master"}
    summary_metrics = [
        ("Total runtime", "total_runtime_seconds", "s"),
        ("Peak process-tree RSS", "peak_process_tree_rss_MB", "MB"),
        ("Input loading", "input_load_seconds", "s"),
        ("Preprocessing", "preprocessing_seconds", "s"),
        ("Pyomo/master build", None, "s"),
        ("Initial solver rows", "Max initial_rows", "count"),
        ("Initial solver columns", "Max initial_columns", "count"),
        ("Initial solver nonzeros", "Max initial_nonzeros", "count"),
        ("Presolved rows", "Max presolved_rows", "count"),
        ("Presolved columns", "Max presolved_columns", "count"),
        ("Presolved nonzeros", "Max presolved_nonzeros", "count"),
        ("Rows removed by presolve", "Rows removed by presolve", "fraction"),
        ("Columns removed by presolve", "Columns removed by presolve", "fraction"),
        ("Solver calls for primary role", "Solver calls", "count"),
        ("Total primary-role solver time", "Total solver_seconds", "s"),
        ("Total primary-role nodes", "Total nodes_explored", "count"),
        ("Total primary-role work units", "Total work_units", "work units"),
        ("Maximum reported barrier factor memory", "Max barrier_factor_memory_MB", "MB"),
    ]
    computational_rows = []
    for label, key, unit in summary_metrics:
        row = {"Metric": label, "Unit": unit}
        for method in ("Monolithic", "Benders", "LBBD"):
            scalars = scalar_by_method.get(method, {})
            if label == "Pyomo/master build":
                if method == "LBBD":
                    value = scalars.get("master_build_seconds", math.nan)
                else:
                    value = scalars.get("model_build_seconds", math.nan)
            elif key in scalars:
                value = scalars.get(key, math.nan)
            else:
                value = math.nan
                if not summary_frame.empty:
                    subset = summary_frame[
                        (summary_frame["Method"] == method)
                        & (summary_frame["Model role"] == primary_role[method])
                    ]
                    if not subset.empty and key in subset.columns:
                        value = subset.iloc[0][key]
            row[method] = value
        computational_rows.append(row)
    computational_frame = pd.DataFrame(computational_rows)
    return computational_frame, timing_frame, summary_frame, detail_frame


ROW_SPEC = [
    ("Slow chargers (11 kW)", "chargers_slow_installed", 0, "count"),
    ("Medium chargers (22 kW)", "chargers_medium_installed", 0, "count"),
    ("Fast chargers (50 kW)", "chargers_fast_installed", 0, "count"),
    ("Public charger capacity (kWh/30 min)", "public_charger_capacity_kWh_per_slot", 0, "number"),
    ("PV panels (500 W)", "PV_panels_installed", 0, "count"),
    ("Battery units (10 kWh)", "battery_units_installed", 0, "count"),
    ("Energy Flows (kWh/yr)", None, 0, "section"),
    ("Grid electricity purchase", "grid_total_kWh", 0, "number"),
    ("Direct grid to chargers", "grid_direct_kWh", 1, "number"),
    ("Grid to battery charging", "grid_to_battery_kWh", 1, "number"),
    ("PV generated locally", "pv_used_total_kWh", 0, "number"),
    ("Direct to chargers", "pv_direct_kWh", 1, "number"),
    ("PV to battery charging", "pv_to_battery_kWh", 1, "number"),
    ("Battery Discharge", "battery_discharge_kWh", 0, "number"),
    ("Public demand redirected", "energy_redirected_kWh", 0, "number"),
    ("Active redirection arcs", "active_redirection_arcs", 0, "count"),
    ("Share of redirected public demand", "share_redirected_public_demand", 0, "percent"),
    ("Annual economic terms (SEK/yr)", None, 0, "section"),
    ("Public charging revenue", "revenue_all_chargers_SEK", 0, "currency"),
    ("Grid electricity cost", "grid_cost_SEK", 0, "currency"),
    ("Redirection incentive", "redirection_total_cost_SEK", 0, "currency"),
    ("Redirection distance compensation", "redirection_distance_cost_SEK", 1, "currency"),
    ("Redirection price compensation", "redirection_price_compensation_SEK", 1, "currency"),
    ("Unmet demand penalty", "slack_penalty_SEK", 0, "currency"),
    ("Annual CapEx chargers", "capex_chargers_SEK", 0, "currency"),
    ("Annual CapEx (PV + BESS)", "capex_PV_BESS_SEK", 0, "currency"),
    ("Net Profit (Obj)", "annual_profit_SEK", 0, "currency"),
]


def _difference(value: Any, base: Any) -> float:
    try:
        a, b = float(value), float(base)
        return a - b if math.isfinite(a) and math.isfinite(b) else math.nan
    except Exception:
        return math.nan


def _relative(value: Any, base: Any) -> float:
    diff = _difference(value, base)
    try:
        b = float(base)
        if math.isfinite(diff) and math.isfinite(b) and abs(b) > 1e-12:
            return diff / abs(b)
    except Exception:
        pass
    return math.nan


def _requested_frame(all_metrics: dict[str, dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for label, key, indent, kind in ROW_SPEC:
        record: dict[str, Any] = {
            "Metric": label,
            "MetricKey": key or "",
            "Indent": indent,
            "Format": kind,
        }
        if key is not None:
            for method in ("Monolithic", "Benders", "LBBD"):
                record[method] = all_metrics.get(method, {}).get(key, math.nan)
            record["Benders - Monolithic"] = _difference(record["Benders"], record["Monolithic"])
            record["LBBD - Monolithic"] = _difference(record["LBBD"], record["Monolithic"])
            record["Benders relative difference"] = _relative(record["Benders"], record["Monolithic"])
            record["LBBD relative difference"] = _relative(record["LBBD"], record["Monolithic"])
        rows.append(record)
    return pd.DataFrame(rows)


def _raw_frame(all_metrics: dict[str, dict[str, Any]]) -> pd.DataFrame:
    keys = sorted(set().union(*(set(values) for values in all_metrics.values())))
    rows = []
    for key in keys:
        row = {"Metric": key}
        for method in ("Monolithic", "Benders", "LBBD"):
            row[method] = all_metrics.get(method, {}).get(key, math.nan)
        row["Benders - Monolithic"] = _difference(row["Benders"], row["Monolithic"])
        row["LBBD - Monolithic"] = _difference(row["LBBD"], row["Monolithic"])
        row["Benders relative difference"] = _relative(row["Benders"], row["Monolithic"])
        row["LBBD relative difference"] = _relative(row["LBBD"], row["Monolithic"])
        rows.append(row)
    return pd.DataFrame(rows)



def _finite_float(value: Any) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else math.nan
    except Exception:
        return math.nan


def _first_scalar(scalars: dict[str, Any], *keys: str) -> float:
    for key in keys:
        value = _finite_float(scalars.get(key))
        if math.isfinite(value):
            return value
    return math.nan


def _solver_summary_value(
    summary: pd.DataFrame,
    method: str,
    roles: tuple[str, ...],
    column: str,
) -> float:
    if summary is None or summary.empty or column not in summary.columns:
        return math.nan
    subset = summary[
        (summary["Method"].astype(str) == str(method))
        & (summary["Model role"].astype(str).isin(list(roles)))
    ]
    if subset.empty:
        return math.nan
    values = pd.to_numeric(subset[column], errors="coerce").dropna()
    return float(values.sum()) if column.startswith("Total ") or column == "Solver calls" else (
        float(values.max()) if not values.empty else math.nan
    )


def _read_history(run_dir: Path, method: str) -> pd.DataFrame:
    candidates = (
        [run_dir / "iterations" / "benders_iteration_history.csv"]
        if method == "Benders"
        else [run_dir / "results" / "lbbd_history.csv"]
    )
    for path in candidates:
        frame = _read_csv_if_present(path)
        if frame is not None:
            return frame
    return pd.DataFrame()


def _certification_frame(run_dirs: dict[str, Path], all_metrics: dict[str, dict[str, Any]]) -> pd.DataFrame:
    """Distinguish an incumbent from a proof of the requested gap."""
    rows = []
    for method, directory in run_dirs.items():
        meta = _read_json_if_present(directory / "run_metadata.json")
        manifest = _read_json_if_present(directory / "logs" / "benders_manifest.json")
        cert = _read_json_if_present(directory / "results" / "solver_certificate.json")
        hist = _read_history(directory, method)
        last = hist.iloc[-1].to_dict() if not hist.empty else {}
        first_certified = math.nan
        if method != "Monolithic" and {"best_lb_SEK", "elapsed_seconds"}.issubset(hist.columns):
            mask = pd.to_numeric(hist["best_lb_SEK"], errors="coerce").notna()
            elapsed = pd.to_numeric(hist.loc[mask, "elapsed_seconds"], errors="coerce").dropna()
            if not elapsed.empty:
                first_certified = float(elapsed.iloc[0])
        if method == "Monolithic":
            incumbent = _finite_float(cert.get("objective_SEK"))
            if not math.isfinite(incumbent):
                incumbent = _finite_float(all_metrics[method].get("annual_profit_SEK"))
            bound = _finite_float(cert.get("valid_bound_SEK"))
            target = _finite_float(cert.get("requested_mip_gap"))
            termination = str(cert.get("termination_reason") or "unrecorded")
            gap = (max(0.0, bound - incumbent) / max(1.0, abs(incumbent))) if math.isfinite(bound) and math.isfinite(incumbent) else math.nan
            denominator = "max(1, abs(incumbent))"
            met = termination == "gap_converged" and math.isfinite(gap) and math.isfinite(target) and gap <= target + 1e-9
        else:
            incumbent = _finite_float(meta.get("best_lb_SEK"))
            if not math.isfinite(incumbent):
                incumbent = _finite_float(last.get("best_lb_SEK"))
            bound = _finite_float(meta.get("global_ub_SEK"))
            if not math.isfinite(bound):
                bound = _finite_float(last.get("global_ub_SEK" if method == "LBBD" else "global_best_UB_SEK"))
            if method == "LBBD" and cert.get("spatial_solve_complete"):
                incumbent = _finite_float(cert.get("objective_SEK"))
                bound = _finite_float(cert.get("valid_bound_SEK"))
                target = _finite_float(cert.get("requested_mip_gap"))
                termination = str(meta.get("termination") or "in_progress_or_unrecorded")
                denominator = "max(1, abs(incumbent))"
                gap = (max(0.0, bound - incumbent) / max(1.0, abs(incumbent))) if math.isfinite(bound) and math.isfinite(incumbent) else math.nan
            elif method == "LBBD":
                target = _finite_float(meta.get("effective_settings", {}).get("lbbd_gap"))
                termination = str(meta.get("termination") or "in_progress_or_unrecorded")
                denominator = "max(1, abs(global_UB))"
                gap = (max(0.0, bound - incumbent) / max(1.0, abs(bound))) if math.isfinite(bound) and math.isfinite(incumbent) else math.nan
            else:
                target = _finite_float(manifest.get("benders_gap"))
                termination = str(meta.get("termination") or last.get("status") or "in_progress_or_unrecorded")
                denominator = "max(1, abs(certified_LB))"
                gap = (max(0.0, bound - incumbent) / max(1.0, abs(incumbent))) if math.isfinite(bound) and math.isfinite(incumbent) else math.nan
            met = termination == "certified_gap" and math.isfinite(gap) and math.isfinite(target) and gap <= target + 1e-9
        rows.append({
            "Method": method, "Termination": termination,
            "Feasible incumbent / certified LB (SEK/yr)": incumbent,
            "Valid global UB (SEK/yr)": bound,
            "Gap (fraction)": gap, "Gap denominator": denominator,
            "Requested gap (fraction)": target,
            "Requested convergence proved": bool(met),
            "Time to first certified feasible (s)": first_certified,
            "Run folder": str(directory),
        })
    return pd.DataFrame(rows)


def _slot_structure_statistics(data: dict) -> dict[str, float]:
    months = [str(v) for v in data.get("MONTHS", [])]
    slots = [int(v) for v in data.get("INTERVALS", [])]
    cells = [int(v) for v in data.get("hex_ids", [])]
    charger_types = len(data.get("PUB_TYPES", []))
    by_slot: dict[tuple[str, int], list[tuple[int, int]]] = {
        (m, t): [] for m in months for t in slots
    }
    for i, j, mon, t in data.get("allowed_st", []):
        by_slot.setdefault((str(mon), int(t)), []).append((int(i), int(j)))

    arc_counts: list[int] = []
    origin_counts: list[int] = []
    destination_counts: list[int] = []
    equality_counts: list[int] = []
    type_pair_counts: list[int] = []
    component_counts: list[int] = []

    for key in [(m, t) for m in months for t in slots]:
        arcs = by_slot.get(key, [])
        origins = {i for i, _ in arcs}
        destinations = {j for _, j in arcs}
        arc_count = len(arcs)
        arc_counts.append(arc_count)
        origin_counts.append(len(origins))
        destination_counts.append(len(destinations))
        type_pair_counts.append(arc_count * charger_types * charger_types)
        equality_counts.append(
            charger_types * (len(origins) + len(destinations)) + arc_count
        )

        parent = {i: i for i in cells}
        def find(a: int) -> int:
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a
        def union(a: int, b: int) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)
        for i, j in arcs:
            union(i, j)
        component_counts.append(len({find(i) for i in cells}))

    def avg(values: list[int]) -> float:
        return float(sum(values) / len(values)) if values else 0.0
    def maximum(values: list[int]) -> int:
        return int(max(values)) if values else 0

    return {
        "I": len(cells),
        "M": len(months),
        "H": len(slots),
        "HSOC": len(data.get("HSOC", [])),
        "C": charger_types,
        "B": len(data.get("DEMAND_CLASSES", [])),
        "blocks": len(months) * len(slots),
        "A": len(data.get("allowed_st", [])),
        "O": len(data.get("ORIGIN_ST", [])),
        "D": len(data.get("DEST_ST", [])),
        "mean_arcs": avg(arc_counts),
        "max_arcs": maximum(arc_counts),
        "sum_type_pairs": float(sum(type_pair_counts)),
        "mean_type_pairs": avg(type_pair_counts),
        "max_type_pairs": maximum(type_pair_counts),
        "sum_slot_equalities": float(sum(equality_counts)),
        "mean_slot_equalities": avg(equality_counts),
        "max_slot_equalities": maximum(equality_counts),
        "sum_components": float(sum(component_counts)),
        "mean_components": avg(component_counts),
        "max_components": maximum(component_counts),
    }


def _complexity_record(
    component: str,
    metric: str,
    definition: str,
    current_size: Any,
    unit: str = "count",
    notes: str = "",
) -> dict[str, Any]:
    return {
        "Component": component,
        "Metric": metric,
        "Order / definition": definition,
        "Current size": current_size,
        "Unit": unit,
        "Source / notes": notes,
    }


def _detailed_complexity_tables(
    data: dict | None,
    run_dirs: dict[str, Path],
    solver_summary: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    scalar_map = {method: read_scalar_file(path) for method, path in run_dirs.items()}
    stats = _slot_structure_statistics(data) if data is not None else {
        key: math.nan for key in [
            "I", "M", "H", "HSOC", "C", "B", "blocks", "A", "O", "D",
            "mean_arcs", "max_arcs", "sum_type_pairs", "mean_type_pairs",
            "max_type_pairs", "sum_slot_equalities", "mean_slot_equalities",
            "max_slot_equalities", "sum_components", "mean_components", "max_components",
        ]
    }
    I, M, H, HSOC, C, B, A = (stats[k] for k in ["I", "M", "H", "HSOC", "C", "B", "A"])

    bsc = scalar_map.get("Benders", {})
    bh = _read_history(run_dirs["Benders"], "Benders") if "Benders" in run_dirs else pd.DataFrame()
    b_cuts = (
        float(pd.to_numeric(bh.get("cuts_added"), errors="coerce").fillna(0).sum())
        if not bh.empty and "cuts_added" in bh.columns else math.nan
    )
    b_rows = [
        _complexity_record("Master problem", "Binary variables", "Recorded active Pyomo binary variables", _first_scalar(bsc, "master_variables_binary"), notes="Arc activation and battery-mode binaries are retained in the master."),
        _complexity_record("Master problem", "Non-binary integer variables", "Recorded active Pyomo general-integer variables", _first_scalar(bsc, "master_variables_integer_nonbinary")),
        _complexity_record("Master problem", "Continuous variables", "Recorded active Pyomo continuous variables", _first_scalar(bsc, "master_variables_continuous")),
        _complexity_record("Master problem", "Total variables", "Binary + general integer + continuous", _first_scalar(bsc, "master_variables_total")),
        _complexity_record("Master problem", "Active constraints before dynamic cuts", "Recorded active Pyomo constraints at construction", _first_scalar(bsc, "master_constraints_active")),
        _complexity_record("Master problem", "Benders cuts added", "sum_k |C_k^BD|", b_cuts),
        _complexity_record("Master problem", "Initial solver matrix rows", "Gurobi master log: initial rows", _solver_summary_value(solver_summary, "Benders", ("master",), "Max initial_rows")),
        _complexity_record("Master problem", "Initial solver matrix columns", "Gurobi master log: initial columns", _solver_summary_value(solver_summary, "Benders", ("master",), "Max initial_columns")),
        _complexity_record("Master problem", "Presolved rows", "Gurobi master log: maximum presolved rows", _solver_summary_value(solver_summary, "Benders", ("master",), "Max presolved_rows")),
        _complexity_record("Master problem", "Presolved columns", "Gurobi master log: maximum presolved columns", _solver_summary_value(solver_summary, "Benders", ("master",), "Max presolved_columns")),
        _complexity_record("Annual redirection block", "Type-specific redirected-energy variables avoided", "|A||C|^2", A * C * C),
        _complexity_record("Annual redirection block", "Aggregate redirected-energy variables retained", "|A|", A),
        _complexity_record("Annual redirection block", "Arc-activation binaries retained", "|A|", A),
        _complexity_record("Annual redirection block", "Trip-count integers retained", "|A|", A),
        _complexity_record("Annual redirection block", "Tail-energy variables retained", "|A|", A),
        _complexity_record("Annual redirection block", "Exact monolithic redirection variables", "|A|(|C|^2+4)", A * (C * C + 4)),
        _complexity_record("Slot LP recourse", "Independent month-slot LPs per full pass", "|M||H|", stats["blocks"]),
        _complexity_record("Slot LP recourse", "Raw active arc-slots", "sum_(m,t)|A_(m,t)| = |A|", A),
        _complexity_record("Slot LP recourse", "Mean / maximum active arcs per slot", "mean / max |A_(m,t)|", f"{stats['mean_arcs']:.2f} / {int(stats['max_arcs'])}" if math.isfinite(stats['mean_arcs']) else ""),
        _complexity_record("Slot LP recourse", "Type-pair flow variables per full pass", "sum_(m,t)|A_(m,t)||C|^2", stats["sum_type_pairs"]),
        _complexity_record("Slot LP recourse", "Mean / maximum LP variables per slot", "mean / max |A_(m,t)||C|^2", f"{stats['mean_type_pairs']:.2f} / {int(stats['max_type_pairs'])}" if math.isfinite(stats['mean_type_pairs']) else ""),
        _complexity_record("Slot LP recourse", "LP equality constraints per full pass", "sum_(m,t)[|C|(|O_(m,t)|+|D_(m,t)|)+|A_(m,t)|]", stats["sum_slot_equalities"]),
        _complexity_record("Slot LP recourse", "Mean / maximum LP equalities per slot", "mean / max [|C|(|O|+|D|)+|A|]", f"{stats['mean_slot_equalities']:.2f} / {int(stats['max_slot_equalities'])}" if math.isfinite(stats['mean_slot_equalities']) else ""),
        _complexity_record("Observed execution", "Slot-LP solver calls", "Recorded calls across all Benders iterations", _first_scalar(bsc, "slot_lp_calls")),
        _complexity_record("Observed execution", "Iterations completed", "Recorded Benders iterations", _first_scalar(bsc, "iterations_completed")),
        _complexity_record("Observed execution", "Model build time", "Input preprocessing excluded", _first_scalar(bsc, "model_build_seconds"), unit="s"),
        _complexity_record("Observed execution", "Total runtime", "Build + solve + export + figures", _first_scalar(bsc, "total_runtime_seconds"), unit="s"),
        _complexity_record("Observed execution", "Peak process-tree RSS", "Python plus descendant Gurobi processes", _first_scalar(bsc, "peak_process_tree_rss_MB"), unit="MB"),
    ]

    lsc = scalar_map.get("LBBD", {})
    lh = _read_history(run_dirs["LBBD"], "LBBD") if "LBBD" in run_dirs else pd.DataFrame()
    l_cuts = (
        float(pd.to_numeric(lh.get("new_cuts_total"), errors="coerce").fillna(0).sum())
        if not lh.empty and "new_cuts_total" in lh.columns else math.nan
    )
    embedded_energy = 4 * I * M * H + I * M * HSOC if all(math.isfinite(v) for v in [I, M, H, HSOC]) else math.nan
    l_rows = [
        _complexity_record("Initial LBBD master", "Binary variables", "Bit encodings for exact configuration cuts", _first_scalar(lsc, "initial_master_variables_binary")),
        _complexity_record("Initial LBBD master", "Non-binary integer variables", "|I|(|C|+2): chargers, PV panels and BESS units", _first_scalar(lsc, "initial_master_variables_integer_nonbinary")),
        _complexity_record("Initial LBBD master", "Continuous variables", "Embedded redirection, service, Theta, slack and linked energy relaxation", _first_scalar(lsc, "initial_master_variables_continuous")),
        _complexity_record("Initial LBBD master", "Total variables", "Recorded active Pyomo variables", _first_scalar(lsc, "initial_master_variables_total")),
        _complexity_record("Initial LBBD master", "Active constraints", "Recorded active Pyomo constraints", _first_scalar(lsc, "initial_master_constraints_active")),
        _complexity_record("Final LBBD master", "Binary variables", "Initial bit encodings plus pooled partial-cut indicators", _first_scalar(lsc, "final_master_variables_binary")),
        _complexity_record("Final LBBD master", "Total variables", "Master after all generated cuts and pooled indicators", _first_scalar(lsc, "final_master_variables_total")),
        _complexity_record("Final LBBD master", "Active constraints", "Master after all generated cuts and links", _first_scalar(lsc, "final_master_constraints_active")),
        _complexity_record("Final LBBD master", "Cuts added", "sum_k new inference cuts", l_cuts),
        _complexity_record("Embedded recourse relaxation", "Continuous aggregate redirection variables", "|A|", A),
        _complexity_record("Embedded recourse relaxation", "Charger-type service variables", "|I||M||H||C|", I * M * H * C if all(math.isfinite(v) for v in [I, M, H, C]) else math.nan),
        _complexity_record("Embedded recourse relaxation", "Home/local/slack variables", "4|I||M||H|", 4 * I * M * H if all(math.isfinite(v) for v in [I, M, H]) else math.nan),
        _complexity_record("Embedded recourse relaxation", "Component-slot Theta variables", "sum_(m,t) number of connected components", stats["sum_components"]),
        _complexity_record("Embedded recourse relaxation", "Linked PV/BESS variables", "4|I||M||H| + |I||M||H_soc|", embedded_energy),
        _complexity_record("Exact logic omitted from master", "Type-pair arc flows", "|A||C|^2", A * C * C),
        _complexity_record("Exact logic omitted from master", "Activation, trip and tail variables", "3|A|", 3 * A),
        _complexity_record("Exact logic omitted from master", "Total exact redirection variables avoided in master", "|A|(|C|^2+3)", A * (C * C + 3)),
        _complexity_record("Exact annual certification MIP", "Binary variables", "Recorded exact fixed-investment annual model", _first_scalar(lsc, "best_exact_annual_oracle_variables_binary")),
        _complexity_record("Exact annual certification MIP", "Non-binary integer variables", "Recorded exact fixed-investment annual model", _first_scalar(lsc, "best_exact_annual_oracle_variables_integer_nonbinary")),
        _complexity_record("Exact annual certification MIP", "Continuous variables", "Recorded exact fixed-investment annual model", _first_scalar(lsc, "best_exact_annual_oracle_variables_continuous")),
        _complexity_record("Exact annual certification MIP", "Active constraints", "Recorded exact fixed-investment annual model", _first_scalar(lsc, "best_exact_annual_oracle_constraints_active")),
        _complexity_record("Oracle system", "Connected component-slot models", "sum_(m,t)|K_(m,t)|", stats["sum_components"]),
        _complexity_record("Oracle system", "Mean / maximum components per slot", "mean / max |K_(m,t)|", f"{stats['mean_components']:.2f} / {int(stats['max_components'])}" if math.isfinite(stats['mean_components']) else ""),
        _complexity_record("Oracle system", "Exact annual MIP solver calls", "Observed exact certification solves", _solver_summary_value(solver_summary, "LBBD", ("exact_annual_oracle",), "Solver calls")),
        _complexity_record("Oracle system", "Linked annual LP solver calls", "Candidate and core-point LP evaluations", _solver_summary_value(solver_summary, "LBBD", ("linked_annual_lp",), "Solver calls")),
        _complexity_record("Oracle system", "Monthly logic-MIP solver calls", "Exact monthly partial-assignment inference", _solver_summary_value(solver_summary, "LBBD", ("monthly_logic_mip",), "Solver calls")),
        _complexity_record("Oracle system", "Component-LP solver calls", "Optional component multicuts", _solver_summary_value(solver_summary, "LBBD", ("component_lp",), "Solver calls")),
        _complexity_record("Observed execution", "Iterations completed", "Recorded LBBD iterations", _first_scalar(lsc, "iterations_completed")),
        _complexity_record("Observed execution", "Distinct exact investment candidates", "Exact annual oracle cache size", _first_scalar(lsc, "unique_exact_candidates")),
        _complexity_record("Observed execution", "Master build time", "Embedded master construction", _first_scalar(lsc, "master_build_seconds"), unit="s"),
        _complexity_record("Observed execution", "Oracle-model build time", "Monthly/annual reusable model construction", _first_scalar(lsc, "oracle_model_build_seconds"), unit="s"),
        _complexity_record("Observed execution", "Total runtime", "Build + decomposition + export + figures", _first_scalar(lsc, "total_runtime_seconds"), unit="s"),
        _complexity_record("Observed execution", "Peak process-tree RSS", "Python plus descendant Gurobi processes", _first_scalar(lsc, "peak_process_tree_rss_MB"), unit="MB"),
    ]

    def primary_scalar(method: str, suffix: str) -> float:
        prefix = {"Monolithic": "main_model", "Benders": "master", "LBBD": "initial_master"}[method]
        return _first_scalar(scalar_map.get(method, {}), f"{prefix}_{suffix}")
    def primary_solver(method: str, column: str) -> float:
        roles = {"Monolithic": ("main_model",), "Benders": ("master",), "LBBD": ("master",)}[method]
        return _solver_summary_value(solver_summary, method, roles, column)
    def build_seconds(method: str) -> float:
        key = "master_build_seconds" if method == "LBBD" else "model_build_seconds"
        return _first_scalar(scalar_map.get(method, {}), key)

    metric_specs = [
        ("Total runtime", "s", "Lower is better", lambda m: _first_scalar(scalar_map.get(m, {}), "total_runtime_seconds"), "End-to-end wall-clock time."),
        ("Peak process-tree RSS", "MB", "Lower is better", lambda m: _first_scalar(scalar_map.get(m, {}), "peak_process_tree_rss_MB"), "Measured Python plus descendant solver RSS; requires psutil."),
        ("Primary model build time", "s", "Lower is better", build_seconds, "Monolithic/Benders model build; LBBD embedded-master build."),
        ("Primary model total variables", "count", "Lower is better", lambda m: primary_scalar(m, "variables_total"), "Initial model presented by each method."),
        ("Primary model binary variables", "count", "Lower is better", lambda m: primary_scalar(m, "variables_binary"), "Initial active Pyomo binary variables."),
        ("Primary model general-integer variables", "count", "Lower is better", lambda m: primary_scalar(m, "variables_integer_nonbinary"), "Initial active non-binary integer variables."),
        ("Primary model continuous variables", "count", "Lower is better", lambda m: primary_scalar(m, "variables_continuous"), "Initial active continuous variables."),
        ("Primary model active constraints", "count", "Lower is better", lambda m: primary_scalar(m, "constraints_active"), "Before dynamic decomposition cuts."),
        ("Solver initial rows", "count", "Lower is better", lambda m: primary_solver(m, "Max initial_rows"), "From Gurobi logs."),
        ("Solver initial columns", "count", "Lower is better", lambda m: primary_solver(m, "Max initial_columns"), "From Gurobi logs."),
        ("Solver initial nonzeros", "count", "Lower is better", lambda m: primary_solver(m, "Max initial_nonzeros"), "From Gurobi logs."),
        ("Solver presolved rows", "count", "Lower is better", lambda m: primary_solver(m, "Max presolved_rows"), "Maximum observed primary-role presolved model."),
        ("Solver presolved columns", "count", "Lower is better", lambda m: primary_solver(m, "Max presolved_columns"), "Maximum observed primary-role presolved model."),
        ("Solver presolved nonzeros", "count", "Lower is better", lambda m: primary_solver(m, "Max presolved_nonzeros"), "Maximum observed primary-role presolved model."),
        ("Rows removed by presolve", "fraction", "Higher is better", lambda m: primary_solver(m, "Rows removed by presolve"), "Fraction of initial rows removed."),
        ("Columns removed by presolve", "fraction", "Higher is better", lambda m: primary_solver(m, "Columns removed by presolve"), "Fraction of initial columns removed."),
        ("Primary solver time", "s", "Lower is better", lambda m: primary_solver(m, "Total solver_seconds"), "Sum across primary-role solver calls."),
        ("Primary branch-and-bound nodes", "count", "Lower is better", lambda m: primary_solver(m, "Total nodes_explored"), "Sum across primary-role solves."),
        ("Primary solver work units", "work units", "Lower is better", lambda m: primary_solver(m, "Total work_units"), "Gurobi deterministic work measure."),
        ("Exact redirection variables simultaneously in primary model", "count", "Lower is better", lambda m: {"Monolithic": A * (C*C + 4), "Benders": A * 4, "LBBD": A}.get(m, math.nan), "Monolithic: type-pair + aggregate + activation + trips + tail; Benders: aggregate exact block; LBBD: continuous aggregate flow only."),
    ]
    efficiency_rows = []
    for metric, unit, direction, getter, notes in metric_specs:
        values = {method: _finite_float(getter(method)) for method in ("Monolithic", "Benders", "LBBD")}
        mono = values["Monolithic"]
        row = {"Metric": metric, "Unit": unit, **values}
        for method in ("Benders", "LBBD"):
            value = values[method]
            row[f"{method} difference vs Monolithic"] = value - mono if math.isfinite(value) and math.isfinite(mono) else math.nan
            if math.isfinite(value) and math.isfinite(mono) and abs(mono) > 1e-12:
                row[f"{method} efficiency change vs Monolithic"] = (
                    (mono - value) / abs(mono)
                    if direction == "Lower is better" else (value - mono) / abs(mono)
                )
            else:
                row[f"{method} efficiency change vs Monolithic"] = math.nan
        row["Preferred direction"] = direction
        row["Notes"] = notes
        efficiency_rows.append(row)

    return pd.DataFrame(b_rows), pd.DataFrame(l_rows), pd.DataFrame(efficiency_rows)

def _style_workbook(path: Path, requested: pd.DataFrame) -> None:
    wb = load_workbook(path)
    navy = "1F4E78"
    light_blue = "D9EAF7"
    pale = "EEF5FA"
    white = "FFFFFF"
    thin = Side(style="thin", color="B7C9D6")

    ws = wb["Comparison"]
    ws.freeze_panes = "B7"
    ws.auto_filter.ref = f"A6:H{ws.max_row}"
    ws.sheet_view.showGridLines = False
    ws["A1"] = "Optimization method comparison"
    ws["A1"].font = Font(size=16, bold=True, color=white)
    ws["A1"].fill = PatternFill("solid", fgColor=navy)
    ws.merge_cells("A1:H1")
    ws["A2"] = "Monolithic run"
    ws["A3"] = "Benders run"
    ws["A4"] = "LBBD run"
    for row in range(2, 5):
        ws.cell(row, 1).font = Font(bold=True)
    for col in range(1, 9):
        cell = ws.cell(6, col)
        cell.fill = PatternFill("solid", fgColor=navy)
        cell.font = Font(bold=True, color=white)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = Border(bottom=thin)

    for idx, spec in enumerate(ROW_SPEC, start=7):
        _, _, indent, kind = spec
        metric_cell = ws.cell(idx, 1)
        metric_cell.alignment = Alignment(indent=indent, vertical="center")
        for col in range(1, 9):
            ws.cell(idx, col).border = Border(bottom=Border(bottom=thin).bottom)
        if kind == "section":
            for col in range(1, 9):
                ws.cell(idx, col).fill = PatternFill("solid", fgColor=light_blue)
                ws.cell(idx, col).font = Font(bold=True, color=navy)
        elif indent:
            for col in range(1, 9):
                ws.cell(idx, col).fill = PatternFill("solid", fgColor=pale)
        if kind == "count":
            fmt = '#,##0'
        elif kind in {"currency", "number"}:
            fmt = '#,##0.00'
        elif kind == "percent":
            fmt = '0.0000%'
        else:
            fmt = 'General'
        for col in range(2, 7):
            ws.cell(idx, col).number_format = fmt if kind != "section" else "General"
        for col in (7, 8):
            ws.cell(idx, col).number_format = '0.0000%'
    ws.column_dimensions["A"].width = 39
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 18
    ws.column_dimensions["D"].width = 18
    for col in range(5, 9):
        ws.column_dimensions[get_column_letter(col)].width = 23
    for row in range(1, ws.max_row + 1):
        ws.row_dimensions[row].height = 21

    raw = wb["Raw metrics"]
    raw.freeze_panes = "B2"
    raw.auto_filter.ref = raw.dimensions
    raw.sheet_view.showGridLines = False
    for cell in raw[1]:
        cell.fill = PatternFill("solid", fgColor=navy)
        cell.font = Font(bold=True, color=white)
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
    raw.column_dimensions["A"].width = 44
    for col in range(2, raw.max_column + 1):
        raw.column_dimensions[get_column_letter(col)].width = 23
        for row in range(2, raw.max_row + 1):
            raw.cell(row, col).number_format = '0.000000'

    folders = wb["Run folders"]
    folders.sheet_view.showGridLines = False
    for cell in folders[1]:
        cell.fill = PatternFill("solid", fgColor=navy)
        cell.font = Font(bold=True, color=white)
    folders.column_dimensions["A"].width = 18
    folders.column_dimensions["B"].width = 110

    for sheet_name in [
        "Computational summary", "Build timing", "Redirection complexity",
        "Solver complexity", "Solver log detail", "Preprocessing scalars",
        "Benders complexity", "LBBD complexity", "Efficiency summary",
        "Memory summary", "Memory trace", "Certification",
    ]:
        if sheet_name not in wb.sheetnames:
            continue
        extra = wb[sheet_name]
        extra.freeze_panes = "A2"
        extra.auto_filter.ref = extra.dimensions
        extra.sheet_view.showGridLines = False
        for cell in extra[1]:
            cell.fill = PatternFill("solid", fgColor=navy)
            cell.font = Font(bold=True, color=white)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        for col in range(1, extra.max_column + 1):
            max_len = max(
                len(str(extra.cell(row, col).value or ""))
                for row in range(1, min(extra.max_row, 100) + 1)
            )
            extra.column_dimensions[get_column_letter(col)].width = min(42, max(12, max_len + 2))
        extra_max_row, extra_max_column = extra.max_row, extra.max_column
        for row in range(2, extra_max_row + 1):
            unit = str(extra.cell(row, 5).value or "").lower() if extra_max_column >= 5 else ""
            for col in range(1, extra_max_column + 1):
                value = extra.cell(row, col).value
                if isinstance(value, (int, float)):
                    header = str(extra.cell(1, col).value or "").lower()
                    if "efficiency change" in header or "fraction" in header or "gap" in header or "removed" in header or unit == "fraction":
                        extra.cell(row, col).number_format = "0.0000%"
                    elif unit == "count":
                        extra.cell(row, col).number_format = "#,##0"
                    else:
                        extra.cell(row, col).number_format = "#,##0.000"
        if sheet_name in {"Benders complexity", "LBBD complexity"}:
            extra.column_dimensions["A"].width = 29
            extra.column_dimensions["B"].width = 39
            extra.column_dimensions["C"].width = 48
            extra.column_dimensions["D"].width = 22
            extra.column_dimensions["E"].width = 14
            extra.column_dimensions["F"].width = 55
            previous_component = None
            for row in range(2, extra.max_row + 1):
                component = extra.cell(row, 1).value
                if component != previous_component:
                    for col in range(1, extra.max_column + 1):
                        extra.cell(row, col).fill = PatternFill("solid", fgColor=light_blue)
                        extra.cell(row, col).font = Font(bold=True, color=navy)
                previous_component = component
        elif sheet_name == "Efficiency summary":
            extra.column_dimensions["A"].width = 43
            extra.column_dimensions["B"].width = 14
            for col in range(3, min(extra.max_column, 9) + 1):
                extra.column_dimensions[get_column_letter(col)].width = 22
            if extra.max_column >= 10:
                extra.column_dimensions[get_column_letter(extra.max_column - 1)].width = 18
                extra.column_dimensions[get_column_letter(extra.max_column)].width = 60
        elif sheet_name == "Memory summary":
            extra.column_dimensions["A"].width = 16
            extra.column_dimensions["B"].width = 14
            extra.column_dimensions["C"].width = 14
            extra.column_dimensions["D"].width = 60
            for col in range(5, extra.max_column + 1):
                extra.column_dimensions[get_column_letter(col)].width = 22
            headers = {
                str(extra.cell(1, col).value or ""): col
                for col in range(1, extra.max_column + 1)
            }
            for header in ("Runtime coverage (fraction)", "Trace peak difference vs scalar (fraction)"):
                col = headers.get(header)
                if col is not None:
                    for row in range(2, extra.max_row + 1):
                        extra.cell(row, col).number_format = "0.00%"
        elif sheet_name == "Memory trace":
            extra.column_dimensions["A"].width = 16
            extra.column_dimensions["B"].width = 18
            extra.column_dimensions["C"].width = 22
            extra.column_dimensions["D"].width = 16
            extra.column_dimensions["E"].width = 60
            for col in range(6, extra.max_column + 1):
                extra.column_dimensions[get_column_letter(col)].width = 20
    wb.save(path)


def main() -> int:
    args = parse_args()
    root = Path(args.project_root).resolve()
    supplied = {
        "Monolithic": args.monolithic_run,
        "Benders": args.benders_run,
        "LBBD": args.lbbd_run,
    }
    run_dirs = {
        method: _resolve(root, value)
        for method, value in supplied.items()
        if value is not None
    }
    for method, run_dir in run_dirs.items():
        if not run_dir.exists():
            raise FileNotFoundError(f"{method} run folder does not exist: {run_dir}")
    contexts = validate_comparison(run_dirs.values(), allow_partial=args.allow_partial)
    capacity = {str(k): float(v) for k, v in contexts[0]["assumptions"]["model_config"]["charger_capacity_kwh_per_slot"].items()}
    all_metrics = {
        method: _enrich(_read_summary(run_dir), run_dir, capacity)
        for method, run_dir in run_dirs.items()
    }
    # Demand is an input and should be common when like-for-like runs are compared.
    # This also supports older result folders that did not export the demand total.
    shared_demand = next(
        (
            float(metrics.get("annual_public_demand_kWh"))
            for metrics in all_metrics.values()
            if math.isfinite(float(metrics.get("annual_public_demand_kWh", math.nan)))
        ),
        math.nan,
    )
    if math.isfinite(shared_demand):
        for metrics in all_metrics.values():
            demand = float(metrics.get("annual_public_demand_kWh", math.nan))
            if not math.isfinite(demand):
                metrics["annual_public_demand_kWh"] = shared_demand
            redirected = float(metrics.get("energy_redirected_kWh", 0.0) or 0.0)
            metrics["share_redirected_public_demand"] = redirected / shared_demand if shared_demand > 0 else 0.0
    requested = _requested_frame(all_metrics)
    raw = _raw_frame(all_metrics)
    certification = _certification_frame(run_dirs, all_metrics)
    computational_summary, build_timing, solver_complexity, solver_log_detail = _complexity_frames(run_dirs)

    trace_values = {
        "Monolithic": args.monolithic_memory_trace,
        "Benders": args.benders_memory_trace,
        "LBBD": args.lbbd_memory_trace,
    }
    trace_overrides = {
        method: _resolve(root, value) if value is not None else None
        for method, value in trace_values.items()
    }
    memory_summary, memory_trace = _memory_frames(run_dirs, trace_overrides)

    dataset = args.dataset or contexts[0]["assumptions"]["dataset"]
    scenario = args.scenario or contexts[0]["assumptions"]["scenario"]
    vipv_scenario = args.vipv_scenario or contexts[0]["vipv_scenario"]
    if (dataset, scenario, vipv_scenario) != (contexts[0]["assumptions"]["dataset"], contexts[0]["assumptions"]["scenario"], contexts[0]["vipv_scenario"]):
        raise ValueError("Explicit comparison input selection differs from the saved run identity.")
    preprocessing_frame = pd.DataFrame()
    redirection_complexity = pd.DataFrame()
    comparison_data = None
    if not args.skip_complexity_recompute:
        print(f"Recomputing exact preprocessing complexity for dataset={dataset}, scenario={scenario}...")
        try:
            comparison_data = _load_preprocessed_comparison_data(root, dataset, scenario, vipv_scenario, contexts[0])
            preprocessing_frame = pd.DataFrame([
                {"Metric": key, "Value": value}
                for key, value in preprocessing_scalars(comparison_data).items()
            ])
            redirection_complexity = slot_redirection_complexity(comparison_data)
        except Exception as exc:
            print(f"WARNING: Exact preprocessing complexity recomputation failed: {exc}")
    benders_complexity, lbbd_complexity, efficiency_summary = _detailed_complexity_tables(
        comparison_data, run_dirs, solver_complexity
    )
    if args.out:
        output = _resolve(root, args.out)
    else:
        out_dir = root / "runs" / "comparisons"
        out_dir.mkdir(parents=True, exist_ok=True)
        tag = "_".join(method.lower() for method in METHODS if method in run_dirs)
        output = out_dir / f"{datetime.now():%Y-%m-%d_%H%M%S}_{tag}_comparison.xlsx"
    output.parent.mkdir(parents=True, exist_ok=True)

    visible_requested = requested.drop(columns=["MetricKey", "Indent", "Format"])
    run_folders = pd.DataFrame(
        [{"Method": method, "Run folder": str(path)} for method, path in run_dirs.items()]
    )
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        # Leave rows 1-5 for title and run paths.
        visible_requested.to_excel(writer, sheet_name="Comparison", index=False, startrow=5)
        raw.to_excel(writer, sheet_name="Raw metrics", index=False)
        certification.to_excel(writer, sheet_name="Certification", index=False, na_rep="NA")
        run_folders.to_excel(writer, sheet_name="Run folders", index=False)
        computational_summary.to_excel(writer, sheet_name="Computational summary", index=False)
        build_timing.to_excel(writer, sheet_name="Build timing", index=False)
        redirection_complexity.to_excel(writer, sheet_name="Redirection complexity", index=False)
        solver_complexity.to_excel(writer, sheet_name="Solver complexity", index=False)
        solver_log_detail.to_excel(writer, sheet_name="Solver log detail", index=False)
        preprocessing_frame.to_excel(writer, sheet_name="Preprocessing scalars", index=False)
        benders_complexity.to_excel(writer, sheet_name="Benders complexity", index=False)
        lbbd_complexity.to_excel(writer, sheet_name="LBBD complexity", index=False)
        efficiency_summary.to_excel(writer, sheet_name="Efficiency summary", index=False)
        memory_summary.to_excel(writer, sheet_name="Memory summary", index=False, na_rep="NA")
        if not memory_trace.empty:
            memory_trace.to_excel(writer, sheet_name="Memory trace", index=False)
    wb = load_workbook(output)
    ws = wb["Comparison"]
    ws["B2"] = str(run_dirs["Monolithic"]) if "Monolithic" in run_dirs else "NA"
    ws["B3"] = str(run_dirs["Benders"]) if "Benders" in run_dirs else "NA"
    ws["B4"] = str(run_dirs["LBBD"]) if "LBBD" in run_dirs else "NA"
    wb.save(output)
    _style_workbook(output, requested)

    rss_paths = _write_rss_figure(memory_trace, output)
    if rss_paths:
        for path in rss_paths:
            print(f"RSS figure written to: {path}")
    else:
        print(
            "WARNING: No temporal RSS trace was found. "
            "The Memory summary sheet contains the available scalar peak RSS, "
            "but an RSS-versus-time curve cannot be reconstructed."
        )

    print(f"Comparison workbook written to: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
