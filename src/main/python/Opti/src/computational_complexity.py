from __future__ import annotations

import json
import math
import re
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

try:
    import pyomo.environ as pyo
except Exception:  # Allows comparison/log parsing without Pyomo imports.
    pyo = None


_NUM = r"[-+0-9.eE]+"


class ResourceMonitor:
    """Best-effort process-tree RSS monitor.

    Uses psutil when available. A missing psutil installation never prevents an
    optimization run; memory fields are simply left blank.
    """

    def __init__(self, interval_seconds: float = 0.5):
        self.interval_seconds = max(0.1, float(interval_seconds))
        self.peak_rss_bytes = 0
        self.last_rss_bytes = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        try:
            import psutil  # type: ignore
            self._psutil = psutil
            self._process = psutil.Process()
        except Exception:
            self._psutil = None
            self._process = None

    @property
    def available(self) -> bool:
        return self._process is not None

    def _sample(self) -> int:
        if self._process is None:
            return 0
        total = 0
        try:
            procs = [self._process] + self._process.children(recursive=True)
        except Exception:
            procs = [self._process]
        for proc in procs:
            try:
                total += int(proc.memory_info().rss)
            except Exception:
                pass
        self.last_rss_bytes = total
        self.peak_rss_bytes = max(self.peak_rss_bytes, total)
        return total

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self._sample()

    def start(self) -> "ResourceMonitor":
        if self.available and self._thread is None:
            self._sample()
            self._thread = threading.Thread(target=self._run, name="resource-monitor", daemon=True)
            self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._sample()

    def as_metrics(self) -> dict[str, float | None]:
        if not self.available:
            return {
                "peak_process_tree_rss_MB": None,
                "final_process_tree_rss_MB": None,
            }
        return {
            "peak_process_tree_rss_MB": self.peak_rss_bytes / (1024.0 ** 2),
            "final_process_tree_rss_MB": self.last_rss_bytes / (1024.0 ** 2),
        }


def model_statistics(model) -> dict[str, int | float | None]:
    """Count active Pyomo components without iterating every scalar variable.

    Large full-data models contain millions of scalar variables. Counting each
    VarData object would itself become a material post-build workload, so this
    routine uses indexed-component cardinalities and classifies each uniform
    variable component from one representative entry. Solver logs remain the
    authoritative source for the exact matrix rows, columns and nonzeros.
    """
    if pyo is None or model is None:
        return {}
    total = binary = integer = continuous = 0
    variable_components = 0
    for component in model.component_objects(pyo.Var, active=True, descend_into=True):
        try:
            count = int(len(component))
        except Exception:
            count = sum(1 for _ in component.values())
        if count <= 0:
            continue
        variable_components += 1
        total += count
        try:
            sample = next(iter(component.values()))
            if sample.is_binary():
                binary += count
            elif sample.is_integer():
                integer += count
            else:
                continuous += count
        except Exception:
            continuous += count
    constraints = 0
    constraint_components = 0
    for component in model.component_objects(pyo.Constraint, active=True, descend_into=True):
        constraint_components += 1
        try:
            constraints += int(len(component))
        except Exception:
            constraints += sum(1 for _ in component.values())
    objectives = sum(
        int(len(component))
        for component in model.component_objects(pyo.Objective, active=True, descend_into=True)
    )
    return {
        "variables_total": int(total),
        "variables_continuous": int(continuous),
        "variables_integer_nonbinary": int(integer),
        "variables_binary": int(binary),
        "variable_components": int(variable_components),
        "constraints_active": int(constraints),
        "constraint_components": int(constraint_components),
        "objectives_active": int(objectives),
    }


def _slot_arc_counts(data: dict) -> list[int]:
    counts: Counter[tuple[str, int]] = Counter()
    for _, _, mon, t in data.get("allowed_st", []):
        counts[(str(mon), int(t))] += 1
    all_keys = [
        (str(mon), int(t))
        for mon in data.get("MONTHS", [])
        for t in data.get("INTERVALS", [])
    ]
    return [int(counts.get(key, 0)) for key in all_keys]


def preprocessing_scalars(data: dict) -> dict[str, Any]:
    types = len(data.get("PUB_TYPES", []))
    arc_slots = len(data.get("allowed_st", []))
    slot_counts = sorted(_slot_arc_counts(data))
    if slot_counts:
        p95_index = min(len(slot_counts) - 1, int(math.ceil(0.95 * len(slot_counts))) - 1)
        median = float(pd.Series(slot_counts).median())
        average = float(sum(slot_counts) / len(slot_counts))
        p95 = float(slot_counts[p95_index])
        maximum = int(max(slot_counts))
    else:
        median = average = p95 = 0.0
        maximum = 0
    return {
        "hex_cells": len(data.get("hex_ids", [])),
        "representative_months": len(data.get("MONTHS", [])),
        "time_slots_per_day": len(data.get("INTERVALS", [])),
        "month_slot_blocks": len(data.get("MONTHS", [])) * len(data.get("INTERVALS", [])),
        "public_charger_types": types,
        "demand_classes": len(data.get("DEMAND_CLASSES", [])),
        "spatial_redirection_arcs": len(data.get("allowed", [])),
        "active_redirection_arc_slots": arc_slots,
        "origin_slot_records": len(data.get("ORIGIN_ST", [])),
        "destination_slot_records": len(data.get("DEST_ST", [])),
        "demand_event_records": len(data.get("demand_event_annual", [])),
        "battery_big_m_records": len(data.get("M_BATT", [])),
        "type_pair_arc_slot_records": arc_slots * types * types,
        "arc_slots_average_per_month_slot": average,
        "arc_slots_median_per_month_slot": median,
        "arc_slots_p95_per_month_slot": p95,
        "arc_slots_max_per_month_slot": maximum,
    }


def slot_redirection_complexity(data: dict) -> pd.DataFrame:
    c = len(data.get("PUB_TYPES", []))
    a = len(data.get("allowed_st", []))
    slot_counts = _slot_arc_counts(data)
    max_slot_arcs = max(slot_counts) if slot_counts else 0
    rows = [
        {
            "Method": "Monolithic",
            "Model role": "Exact annual model",
            "Aggregate arc-flow variables": a,
            "Type-pair arc-flow variables": a * c * c,
            "Arc activation binaries": a,
            "Trip integer variables": a,
            "Arc tail variables": a,
            "Origin/destination marginal variables": 0,
            "Maximum type-pair variables in one slot": max_slot_arcs * c * c,
            "Notes": "All exact redirection and type-pair decisions are present simultaneously.",
        },
        {
            "Method": "LBBD",
            "Model role": "Embedded-relaxation master",
            "Aggregate arc-flow variables": a,
            "Type-pair arc-flow variables": 0,
            "Arc activation binaries": 0,
            "Trip integer variables": 0,
            "Arc tail variables": 0,
            "Origin/destination marginal variables": 0,
            "Maximum type-pair variables in one slot": max_slot_arcs * c * c,
            "Notes": "The master retains continuous aggregate redirection; exact annual MIP and monthly logic oracles restore discrete/type-pair logic.",
        },
        {
            "Method": "LBBD",
            "Model role": "Exact annual certification oracle",
            "Aggregate arc-flow variables": a,
            "Type-pair arc-flow variables": a * c * c,
            "Arc activation binaries": a,
            "Trip integer variables": a,
            "Arc tail variables": a,
            "Origin/destination marginal variables": 0,
            "Maximum type-pair variables in one slot": max_slot_arcs * c * c,
            "Notes": "Same exact redirection logic as the monolithic formulation, with investments fixed.",
        },
    ]
    return pd.DataFrame(rows)


def _last_float(pattern: str, text: str, group: int = 1) -> float | None:
    matches = list(re.finditer(pattern, text, flags=re.MULTILINE))
    if not matches:
        return None
    try:
        return float(matches[-1].group(group))
    except Exception:
        return None


def _last_int(pattern: str, text: str, group: int = 1) -> int | None:
    value = _last_float(pattern, text, group)
    return None if value is None else int(round(value))


def classify_log(path: Path) -> str:
    name = path.name.lower()
    parent = path.parent.name.lower()
    # Parent folders are more reliable than filenames because component LP logs
    # may include the phrase "master_candidate" in their source label.
    if parent == "component_lp" or "component" in parent:
        return "component_lp"
    if parent == "logic_mip" or "logic_mip" in parent or "exact_baseline" in name:
        return "monthly_logic_mip"
    if name == "gurobi_run.log":
        return "main_model"
    if "exact_annual" in name:
        return "exact_annual_oracle"
    if "linked_annual_lp" in name:
        return "linked_annual_lp"
    if "master" in name:
        return "master"
    if "subproblem" in name or "type_assignment" in name:
        return "subproblem"
    return "other"


def parse_gurobi_log(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    row: dict[str, Any] = {
        "log_file": str(path),
        "log_name": path.name,
        "model_role": classify_log(path),
    }
    optimize = list(re.finditer(
        rf"Optimize a model with\s+({_NUM})\s+rows,\s+({_NUM})\s+columns and\s+({_NUM})\s+nonzeros",
        text,
    ))
    if optimize:
        m = optimize[-1]
        row.update({
            "initial_rows": int(float(m.group(1))),
            "initial_columns": int(float(m.group(2))),
            "initial_nonzeros": int(float(m.group(3))),
        })
    vt = list(re.finditer(
        rf"Variable types:\s+({_NUM})\s+continuous,\s+({_NUM})\s+integer\s+\(({_NUM})\s+binary\)",
        text,
    ))
    if vt:
        m = vt[0]
        row.update({
            "initial_continuous": int(float(m.group(1))),
            "initial_integer_total": int(float(m.group(2))),
            "initial_binary": int(float(m.group(3))),
        })
    removed = list(re.finditer(rf"Presolve removed\s+({_NUM})\s+rows and\s+({_NUM})\s+columns", text))
    if removed:
        m = removed[-1]
        row.update({
            "presolve_removed_rows": int(float(m.group(1))),
            "presolve_removed_columns": int(float(m.group(2))),
        })
    presolved = list(re.finditer(
        rf"^Presolved:\s+({_NUM})\s+rows,\s+({_NUM})\s+columns,\s+({_NUM})\s+nonzeros",
        text,
        flags=re.MULTILINE,
    ))
    if presolved:
        m = presolved[-1]
        row.update({
            "presolved_rows": int(float(m.group(1))),
            "presolved_columns": int(float(m.group(2))),
            "presolved_nonzeros": int(float(m.group(3))),
        })
    root = list(re.finditer(
        rf"Root relaxation presolved:\s+({_NUM})\s+rows,\s+({_NUM})\s+columns,\s+({_NUM})\s+nonzeros",
        text,
    ))
    if root:
        m = root[-1]
        row.update({
            "root_presolved_rows": int(float(m.group(1))),
            "root_presolved_columns": int(float(m.group(2))),
            "root_presolved_nonzeros": int(float(m.group(3))),
        })
    factor = list(re.finditer(r"Factor NZ\s*:\s*[^\n]*\(roughly\s+([0-9.]+)\s+(MB|GB) of memory\)", text))
    if factor:
        value = float(factor[-1].group(1))
        if factor[-1].group(2).upper() == "GB":
            value *= 1024.0
        row["barrier_factor_memory_MB"] = value
    explored = list(re.finditer(
        rf"Explored\s+({_NUM})\s+nodes\s+\(({_NUM})\s+simplex iterations\)\s+in\s+({_NUM})\s+seconds\s+\(({_NUM})\s+work units\)",
        text,
    ))
    if explored:
        m = explored[-1]
        row.update({
            "nodes_explored": int(float(m.group(1))),
            "simplex_iterations": int(float(m.group(2))),
            "solver_seconds": float(m.group(3)),
            "work_units": float(m.group(4)),
        })
    else:
        solved = list(re.finditer(
            rf"Solved in\s+({_NUM})\s+iterations and\s+({_NUM})\s+seconds\s+\(({_NUM})\s+work units\)",
            text,
        ))
        if solved:
            m = solved[-1]
            row.update({
                "simplex_iterations": int(float(m.group(1))),
                "solver_seconds": float(m.group(2)),
                "work_units": float(m.group(3)),
                "nodes_explored": 0,
            })
    thread = list(re.finditer(r"Thread count was\s+([0-9]+)", text))
    if thread:
        row["threads_used"] = int(thread[-1].group(1))
    else:
        thread = list(re.finditer(r"using up to\s+([0-9]+)\s+threads", text))
        if thread:
            row["threads_used"] = int(thread[-1].group(1))
    final = list(re.finditer(
        rf"Best objective\s+({_NUM}),\s+best bound\s+({_NUM}),\s+gap\s+({_NUM})%",
        text,
    ))
    if final:
        m = final[-1]
        row.update({
            "final_objective": float(m.group(1)),
            "final_bound": float(m.group(2)),
            "final_gap": float(m.group(3)) / 100.0,
        })
    row["log_size_bytes"] = path.stat().st_size
    return row


def collect_solver_log_detail(run_dir: Path) -> pd.DataFrame:
    logs_dir = Path(run_dir) / "logs"
    rows = []
    if logs_dir.exists():
        for path in sorted(logs_dir.rglob("*.log")):
            try:
                parsed = parse_gurobi_log(path)
                if parsed.get("initial_rows") is not None or parsed.get("solver_seconds") is not None:
                    rows.append(parsed)
            except Exception as exc:
                rows.append({"log_file": str(path), "log_name": path.name, "model_role": classify_log(path), "parse_error": str(exc)})
    return pd.DataFrame(rows)


def summarize_solver_logs(detail: pd.DataFrame) -> pd.DataFrame:
    if detail is None or detail.empty:
        return pd.DataFrame()
    numeric = [
        "initial_rows", "initial_columns", "initial_nonzeros",
        "presolved_rows", "presolved_columns", "presolved_nonzeros",
        "root_presolved_rows", "root_presolved_columns", "root_presolved_nonzeros",
        "solver_seconds", "work_units", "nodes_explored", "simplex_iterations",
        "barrier_factor_memory_MB", "threads_used",
    ]
    for col in numeric:
        if col in detail.columns:
            detail[col] = pd.to_numeric(detail[col], errors="coerce")
    rows = []
    for role, grp in detail.groupby("model_role", dropna=False):
        record: dict[str, Any] = {"Model role": role, "Solver calls": int(len(grp))}
        for col in ["initial_rows", "initial_columns", "initial_nonzeros", "presolved_rows", "presolved_columns", "presolved_nonzeros", "root_presolved_rows", "root_presolved_columns", "root_presolved_nonzeros", "barrier_factor_memory_MB", "threads_used"]:
            if col in grp:
                record[f"Max {col}"] = float(grp[col].max()) if grp[col].notna().any() else math.nan
                record[f"Median {col}"] = float(grp[col].median()) if grp[col].notna().any() else math.nan
        for col in ["solver_seconds", "work_units", "nodes_explored", "simplex_iterations"]:
            if col in grp:
                record[f"Total {col}"] = float(grp[col].sum(min_count=1)) if grp[col].notna().any() else math.nan
        if record.get("Max initial_rows") and math.isfinite(record.get("Max presolved_rows", math.nan)):
            record["Rows removed by presolve"] = 1.0 - record["Max presolved_rows"] / max(1.0, record["Max initial_rows"])
        if record.get("Max initial_columns") and math.isfinite(record.get("Max presolved_columns", math.nan)):
            record["Columns removed by presolve"] = 1.0 - record["Max presolved_columns"] / max(1.0, record["Max initial_columns"])
        rows.append(record)
    return pd.DataFrame(rows)


def _metric_rows(metrics: dict[str, Any], source: str) -> pd.DataFrame:
    rows = []
    for key, value in metrics.items():
        unit = ""
        if key.endswith("_seconds"):
            unit = "s"
        elif key.endswith("_MB"):
            unit = "MB"
        elif "gap" in key.lower() or "fraction" in key.lower():
            unit = "fraction"
        else:
            unit = "count"
        rows.append({"Metric": key, "Value": value, "Unit": unit, "Source": source})
    return pd.DataFrame(rows)


def merge_run_metadata(run_dir: Path, updates: dict[str, Any]) -> None:
    path = Path(run_dir) / "run_metadata.json"
    current: dict[str, Any] = {}
    if path.exists():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            current = {}
    current.update(updates)
    path.write_text(json.dumps(current, indent=2), encoding="utf-8")


def write_run_complexity(
    run_dir: Path,
    method: str,
    data: dict,
    phase_timing: dict[str, float] | None = None,
    model_stats: dict[str, dict[str, Any]] | None = None,
    resource_monitor: ResourceMonitor | None = None,
    extra_scalars: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_dir = Path(run_dir)
    results_dir = run_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    shared = preprocessing_scalars(data)
    phases = dict(phase_timing or {})
    resources = resource_monitor.as_metrics() if resource_monitor is not None else {}
    extra = dict(extra_scalars or {})
    detail = collect_solver_log_detail(run_dir)
    summary = summarize_solver_logs(detail.copy())

    scalar_frames = [
        _metric_rows(shared, "preprocessing"),
        _metric_rows(phases, "phase_timing"),
        _metric_rows(resources, "resource_monitor"),
        _metric_rows(extra, "run"),
    ]
    for role, stats in (model_stats or {}).items():
        scalar_frames.append(_metric_rows({f"{role}_{k}": v for k, v in stats.items()}, "pyomo_model"))
    scalars = pd.concat(scalar_frames, ignore_index=True)
    scalars.insert(0, "Method", str(method))
    scalars.to_csv(results_dir / "computational_complexity_scalars.csv", index=False)

    redirection = slot_redirection_complexity(data)
    redirection.to_csv(results_dir / "slot_redirection_complexity.csv", index=False)
    if not detail.empty:
        detail.to_csv(results_dir / "solver_log_complexity.csv", index=False)
    if not summary.empty:
        summary.insert(0, "Method", str(method))
        summary.to_csv(results_dir / "computational_complexity_table.csv", index=False)
    else:
        pd.DataFrame(columns=["Method", "Model role", "Solver calls"]).to_csv(
            results_dir / "computational_complexity_table.csv", index=False
        )

    metadata_complexity = {
        "preprocessing": shared,
        "phase_timing": phases,
        "resource_usage": resources,
        "model_statistics": model_stats or {},
        "solver_log_roles": summary.to_dict(orient="records") if not summary.empty else [],
    }
    merge_run_metadata(run_dir, {"computational_complexity": metadata_complexity})
    return metadata_complexity


def read_scalar_file(run_dir: Path) -> dict[str, Any]:
    path = Path(run_dir) / "results" / "computational_complexity_scalars.csv"
    if not path.exists():
        return {}
    frame = pd.read_csv(path)
    if not {"Metric", "Value"}.issubset(frame.columns):
        return {}
    out: dict[str, Any] = {}
    for row in frame.itertuples(index=False):
        value = getattr(row, "Value")
        try:
            value = float(value)
        except Exception:
            pass
        out[str(getattr(row, "Metric"))] = value
    return out


def read_phase_timing(run_dir: Path) -> dict[str, Any]:
    scalars = read_scalar_file(run_dir)
    return {key: value for key, value in scalars.items() if key.endswith("_seconds")}
