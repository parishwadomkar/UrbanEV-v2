#!/usr/bin/env python
# coding: utf-8
from __future__ import annotations

import argparse
import importlib
import os
import sys
import time
from datetime import datetime
from pathlib import Path

for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name, None)
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from utils import ensure_dir, load_json, resolve_project_path
from data_loader import check_input_paths, load_inputs
from preprocessing import preprocess
from model_builder import apply_scenario, apply_hard_no_slack, build_model
from solve_model import solve_model
from export_results import export_all, print_summary
from visualize_results import generate_run_figures
from run_profiles import apply_profile_defaults, load_run_profile
from technology_switches import apply_technology_switches
from computational_complexity import ResourceMonitor, model_statistics, write_run_complexity
from input_scenarios import add_input_selection_arguments, resolve_input_selection, resolve_scenario_paths

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the type-aware EV CPO optimization from VS Code/terminal."
    )
    parser.add_argument(
        "--scenario",
        choices=["with_redirection", "no_redirection"],
        default="with_redirection",
        help="Optimization scenario."
    )
    add_input_selection_arguments(parser)
    parser.add_argument(
        "--hard-no-slack",
        action="store_true",
        help="Fix all slack variables to zero. Use for feasibility/final no-slack runs."
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Check environment and input files only."
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=None,
        help="Override Gurobi Threads."
    )
    parser.add_argument(
        "--time-limit",
        type=int,
        default=None,
        help="Override Gurobi TimeLimit seconds."
    )
    parser.add_argument(
        "--mip-gap",
        type=float,
        default=None,
        help="Override Gurobi MIPGap."
    )
    parser.add_argument(
        "--root-method",
        choices=["auto", "primal", "dual", "barrier", "concurrent", "deterministic-concurrent"],
        default=None,
        help="Gurobi method for the root LP relaxation. Use 'dual' for memory-constrained full runs."
    )
    parser.add_argument(
        "--node-method",
        choices=["auto", "primal", "dual", "barrier"],
        default=None,
        help="Gurobi method for MIP node relaxations."
    )
    parser.add_argument(
        "--nodefile-start",
        type=float,
        default=None,
        help="GB of branch-and-bound node memory before nodes are compressed to disk."
    )
    parser.add_argument(
        "--soft-mem-limit-gb",
        type=float,
        default=None,
        help="Graceful Gurobi memory limit in GB. Leave headroom for Python/Pyomo and the OS."
    )
    parser.add_argument(
        "--pre-sparsify",
        type=int,
        choices=[-1, 0, 1, 2],
        default=None,
        help="Override Gurobi PreSparsify."
    )
    parser.add_argument(
        "--aggregate",
        type=int,
        choices=[-1, 0, 1, 2],
        default=None,
        help="Override Gurobi Aggregate presolve setting."
    )
    parser.add_argument(
        "--pre-passes",
        type=int,
        default=None,
        help="Override Gurobi PrePasses."
    )
    parser.add_argument(
        "--solver-cuts",
        type=int,
        choices=[-1, 0, 1, 2, 3],
        default=None,
        help="Override Gurobi global Cuts setting."
    )
    parser.add_argument(
        "--project-root",
        default=str(PROJECT_ROOT),
        help="Project root folder."
    )
    parser.add_argument(
        "--write-lp",
        action="store_true",
        help="Write model.lp to the run folder before solving."
    )
    parser.add_argument(
        "--disable-pv",
        action="store_true",
        help="Disable PV investment and PV operation."
    )
    parser.add_argument(
        "--disable-bess",
        action="store_true",
        help="Disable BESS investment and BESS operation."
    )
    parser.add_argument(
        "--speed-car-kmh",
        type=float,
        default=None,
        help="Sensitivity override for model_config.json speed_car_kmh."
    )
    parser.add_argument(
        "--value-time-sek-per-h",
        type=float,
        default=None,
        help="Sensitivity override for model_config.json value_time_sek_per_h."
    )
    parser.add_argument(
        "--max-redirection-distance-km",
        type=float,
        default=None,
        help="Sensitivity override for model_config.json max_redirection_distance_km."
    )
    parser.add_argument(
        "--sensitivity-name",
        default=None,
        help="Optional short label appended to the run folder name for sensitivity runs."
    )
    parser.add_argument(
        "--skip-figures",
        action="store_true",
        default=None,
        help="Skip automatic figure generation after successful result export."
    )
    parser.add_argument(
        "--figures-dpi",
        type=int,
        default=300,
        help="PNG resolution for automatically generated figures."
    )
    parser.add_argument(
        "--max-redirection-arcs-plot",
        type=int,
        default=150,
        help="Maximum number of annual redirection corridors drawn on the flow map."
    )
    return parser.parse_args()


def load_configs(project_root: Path, dataset: str, vipv_scenario: str) -> tuple[dict, dict, dict, str]:
    model_cfg = load_json(project_root / "config" / "model_config.json")
    solver_cfg = load_json(project_root / "config" / "solver_gurobi.json")
    paths = resolve_scenario_paths(project_root, dataset, vipv_scenario)
    return paths, model_cfg, solver_cfg, dataset



def _format_sensitivity_value(value: float) -> str:
    text = (f"{float(value):g}").replace("-", "m").replace(".", "p")
    return text


def apply_sensitivity_overrides(model_cfg: dict, args: argparse.Namespace) -> dict:
    """Apply command-line sensitivity overrides to the loaded model config.

    The base config file is not modified on disk. The returned dictionary is a
    record of the parameters changed for this run and is written to the terminal
    transcript and run metadata.
    """
    overrides = {}
    if args.speed_car_kmh is not None:
        model_cfg["speed_car_kmh"] = float(args.speed_car_kmh)
        overrides["speed_car_kmh"] = float(args.speed_car_kmh)
    if args.value_time_sek_per_h is not None:
        model_cfg["value_time_sek_per_h"] = float(args.value_time_sek_per_h)
        overrides["value_time_sek_per_h"] = float(args.value_time_sek_per_h)
    if args.max_redirection_distance_km is not None:
        model_cfg["max_redirection_distance_km"] = float(args.max_redirection_distance_km)
        overrides["max_redirection_distance_km"] = float(args.max_redirection_distance_km)
    return overrides


def make_sensitivity_suffix(args: argparse.Namespace, overrides: dict) -> str:
    if args.sensitivity_name:
        label = str(args.sensitivity_name).strip().replace(" ", "_")
        return "_" + label if label else ""
    if not overrides:
        return ""
    parts = []
    if "speed_car_kmh" in overrides:
        parts.append("speed" + _format_sensitivity_value(overrides["speed_car_kmh"]) + "kmh")
    if "value_time_sek_per_h" in overrides:
        parts.append("vot" + _format_sensitivity_value(overrides["value_time_sek_per_h"]) + "sekph")
    if "max_redirection_distance_km" in overrides:
        parts.append("dist" + _format_sensitivity_value(overrides["max_redirection_distance_km"]) + "km")
    return "_" + "_".join(parts)

def run_smoke(project_root: Path, paths: dict, model_cfg: dict) -> int:
    print("========== ENVIRONMENT ==========")
    print(f"Project root : {project_root}")
    print(f"Dataset      : {paths.get('dataset')}")
    print(f"VIPV scenario: {paths.get('vipv_scenario')}")
    print(f"Python exe   : {sys.executable}")
    print(f"Python ver   : {sys.version}")
    print(f"Conda env    : {os.environ.get('CONDA_DEFAULT_ENV', '')}")

    print("\n========== PACKAGE IMPORTS ==========")
    packages = [
        "pandas",
        "geopandas",
        "numpy",
        "pyomo.environ",
        "networkx",
        "matplotlib",
        "shapely",
        "gurobipy",
        "openpyxl",
    ]

    ok = True
    for pkg in packages:
        try:
            mod = importlib.import_module(pkg)
            if pkg == "gurobipy":
                import gurobipy as gp
                version = gp.gurobi.version()
            else:
                version = getattr(mod, "__version__", "OK")
            print(f"{pkg:<18}: {version}")
        except Exception as exc:
            ok = False
            print(f"{pkg:<18}: FAIL - {exc}")

    try:
        import pyomo.environ as pyo
        available = pyo.SolverFactory("gurobi").available()
        print(f"{'SolverFactory':<18}: gurobi available = {available}")
        ok = ok and bool(available)
    except Exception as exc:
        ok = False
        print(f"{'SolverFactory':<18}: FAIL - {exc}")

    print("\n========== INPUT DATA PATHS ==========")
    for p, exists in check_input_paths(paths):
        print(f"{p:<115} {'OK' if exists else 'MISSING'}")
        ok = ok and exists

    if ok:
        print("\n========== INPUT CONTENT VALIDATION ==========")
        try:
            raw = load_inputs(paths)
            data = preprocess(raw, model_cfg)
            pv_diag = data["pv_diag"]
            pv_unit = str(pv_diag["detected_input_unit"].iloc[0]) if not pv_diag.empty else "unknown"
            pv_yield = float(pv_diag["annualized_kwh_per_kwp"].sum()) if not pv_diag.empty else 0.0
            price_values = [float(v) for month in data["tou"].values() for v in month.values()]
            print(f"Seasonal demand enabled : {data['seasonal_demand_enabled']}")
            if data["seasonal_demand_enabled"]:
                print("Season-to-month mapping  : WINTER=Dec/Jan/Feb; SPRING=Mar/Apr/May; SUMMER=Jun/Jul/Aug; AUTUMN=Sep/Oct/Nov")
            print(f"PVGIS detected unit     : {pv_unit}")
            print(f"PV annualized yield     : {pv_yield:,.1f} kWh/kWp-year")
            print(f"Retail ToU price range  : {min(price_values):.4f} to {max(price_values):.4f} SEK/kWh")
            print("Seasonal demand totals  :")
            for row in data["seasonal_demand_diagnostics"].itertuples(index=False):
                print(
                    f"  {row.Season:<6} representative day = {row.RepresentativeDay_TotalMATSim_kWh:,.1f} kWh; "
                    f"optimizer boundary = {row.SeasonAnnualized_OptimizationBoundary_kWh / row.Days:,.1f} kWh/day"
                )
        except Exception as exc:
            ok = False
            print(f"INPUT CONTENT VALIDATION: FAIL - {exc}")

    print("\nSMOKE TEST:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def make_run_dir(
    paths: dict,
    scenario: str,
    dataset: str,
    vipv_scenario: str,
    hard_no_slack: bool,
    disable_pv: bool,
    disable_bess: bool,
    sensitivity_suffix: str = "",
) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    slack_suffix = "hardnoslack" if hard_no_slack else "slackpenalty"

    if disable_pv and disable_bess:
        tech_suffix = "noPV_noBESS"
    elif disable_pv and not disable_bess:
        tech_suffix = "noPV_withBESS"
    elif not disable_pv and disable_bess:
        tech_suffix = "withPV_noBESS"
    else:
        tech_suffix = "withPV_withBESS"

    run_dir = (
        Path(paths["runs_root"])
        / f"{stamp}_{dataset}_{vipv_scenario}_{scenario}_{tech_suffix}{sensitivity_suffix}_{slack_suffix}"
    )

    for sub in ["logs", "results", "model", "nodefiles"]:
        ensure_dir(run_dir / sub)

    return run_dir




class TeeStream:
    """Write terminal output to multiple streams at once."""

    def __init__(self, *streams):
        self.streams = [s for s in streams if s is not None]

    def write(self, message: str) -> int:
        for stream in self.streams:
            try:
                stream.write(message)
            except UnicodeEncodeError:
                stream.write(message.encode("utf-8", errors="replace").decode("utf-8"))
        self.flush()
        return len(message)

    def flush(self) -> None:
        for stream in self.streams:
            try:
                stream.flush()
            except Exception:
                pass


def write_run_folder_readme(
    run_dir: Path,
    dataset: str,
    vipv_scenario: str,
    scenario: str,
    disable_pv: bool,
    disable_bess: bool,
    sensitivity_overrides: dict | None = None,
) -> None:
    readme = run_dir / "README_RUN_FOLDER.txt"
    tech = (
        "no PV, no BESS" if disable_pv and disable_bess else
        "PV enabled, BESS disabled" if (not disable_pv and disable_bess) else
        "PV disabled, BESS enabled" if (disable_pv and not disable_bess) else
        "PV enabled, BESS enabled"
    )
    sensitivity_overrides = sensitivity_overrides or {}
    sensitivity_text = "None" if not sensitivity_overrides else ", ".join(
        f"{k}={v}" for k, v in sensitivity_overrides.items()
    )
    readme.write_text(
        "Monolithic optimization run folder\n"
        "==================================\n\n"
        "This folder is produced by src/run_optimization.py. It contains the outputs from the full monolithic Pyomo/Gurobi formulation.\n\n"
        "Core files:\n"
        "- README_RUN.txt: complete terminal transcript from this run.\n"
        "- results/model_summary.csv: detailed economic, energy, and infrastructure metrics.\n"
        "- results/infrastructure_by_hex.csv: charger/PV/BESS deployment by cell.\n"
        "- results/redirections.csv and redirections_by_type.csv: optimized redirected flows.\n"
        "- results/hourly_energy.csv: slot-level energy dispatch.\n"
        "- results/pvgis_diagnostics.csv: detected PV input units and implied monthly/annual PV yield.\n"
        "- results/input_monthly_profiles.csv: exact month-slot stationary PV factors and retail ToU prices.\n"
        "- results/seasonal_demand_diagnostics.csv: seasonal MATSim demand totals and annualization checks.\n"
        "- figures/: automatically generated diagnostic and manuscript-oriented figures.\n"
        "- logs/gurobi_run.log: Gurobi solver log.\n"
        "- logs/pyomo_solve.log: Pyomo solve log.\n\n"
        f"VIPV input scenario: {vipv_scenario}\n"
        f"Optimization scenario: {scenario}\n"
        f"Dataset: {dataset}\n"
        f"Technology: {tech}\n"
        f"Sensitivity overrides: {sensitivity_text}\n",
        encoding="utf-8",
    )


def _run_optimization_impl(
    args: argparse.Namespace,
    project_root: Path,
    paths: dict,
    model_cfg: dict,
    solver_cfg: dict,
    dataset: str,
    run_dir: Path,
) -> int:
    total_started = time.perf_counter()
    monitor = ResourceMonitor().start()
    phase_timing: dict[str, float] = {}
    print(f"Project root  : {project_root}")
    print(f"Dataset       : {dataset}")
    print(f"VIPV scenario : {args.vipv_scenario}")
    print(f"Run profile   : {getattr(args, '_run_profile', 'monolithic')}")
    print(f"Scenario      : {args.scenario}")
    print(f"Disable PV    : {args.disable_pv}")
    print(f"Disable BESS  : {args.disable_bess}")
    print(f"Hard no-slack : {args.hard_no_slack}")
    sensitivity_overrides = getattr(args, "_sensitivity_overrides", {}) or {}
    if sensitivity_overrides:
        print("Sensitivity overrides:")
        for key, value in sensitivity_overrides.items():
            print(f"  {key}: {value}")
    else:
        print("Sensitivity overrides: none")
    print(f"Run directory : {run_dir}")

    print("Loading inputs...")
    phase_started = time.perf_counter()
    raw = load_inputs(paths)
    phase_timing["input_load_seconds"] = time.perf_counter() - phase_started

    print("Preprocessing inputs...")
    phase_started = time.perf_counter()
    data = preprocess(raw, model_cfg)
    phase_timing["preprocessing_seconds"] = time.perf_counter() - phase_started
    data["dataset"] = dataset
    data["vipv_scenario"] = args.vipv_scenario
    data["disable_pv"] = args.disable_pv
    data["disable_bess"] = args.disable_bess

    print(f"Hex cells: {len(data['hex_ids'])}")
    print(f"Active redirection arc-slots: {len(data['allowed_st']):,}")
    print(f"Seasonal demand enabled: {data['seasonal_demand_enabled']}")
    if data["seasonal_demand_enabled"]:
        print("Season mapping: WINTER->Dec/Jan/Feb; SPRING->Mar/Apr/May; SUMMER->Jun/Jul/Aug; AUTUMN->Sep/Oct/Nov")
    pv_diag = data["pv_diag"]
    if not pv_diag.empty:
        print(f"PVGIS detected input unit: {pv_diag['detected_input_unit'].iloc[0]}")
        print(f"PVGIS implied annual yield: {float(pv_diag['annualized_kwh_per_kwp'].sum()):,.1f} kWh/kWp-year")
    profile = data["input_monthly_profiles"]
    print(
        "Retail ToU range: "
        f"{float(profile['Retail_price_SEK_per_kWh'].min()):.4f} - "
        f"{float(profile['Retail_price_SEK_per_kWh'].max()):.4f} SEK/kWh"
    )

    print("Building type-aware Pyomo model...")
    phase_started = time.perf_counter()
    model = build_model(data, model_cfg)
    phase_timing["model_build_seconds"] = time.perf_counter() - phase_started
    main_model_stats = model_statistics(model)

    apply_technology_switches(
        model=model,
        disable_pv=args.disable_pv,
        disable_bess=args.disable_bess,
    )

    apply_scenario(model, args.scenario)

    if args.hard_no_slack:
        apply_hard_no_slack(model)

    if args.write_lp:
        lp_path = run_dir / "model" / "model.lp"
        model.write(str(lp_path), io_options={"symbolic_solver_labels": True})
        print(f"LP model written to: {lp_path}")

    print("Solving with Gurobi...")
    phase_started = time.perf_counter()
    results = solve_model(model, solver_cfg, run_dir)
    phase_timing["solve_seconds"] = time.perf_counter() - phase_started
    print(results.solver)

    term = str(results.solver.termination_condition).lower()
    if "infeasible" in term:
        print(
            "\nModel is infeasible under the current options. "
            "If --hard-no-slack was used, rerun without it and inspect slack diagnostics."
        )
        print(f"Run directory: {run_dir}")
        monitor.stop()
        phase_timing["total_runtime_seconds"] = time.perf_counter() - total_started
        write_run_complexity(
            run_dir, "Monolithic", data,
            phase_timing=phase_timing,
            model_stats={"main_model": main_model_stats},
            resource_monitor=monitor,
            extra_scalars={"termination_infeasible": 1},
        )
        return 2

    print_summary(model, data, model_cfg)

    print("Writing CSV/XLSX outputs...")
    phase_started = time.perf_counter()
    export_all(model, data, model_cfg, run_dir)
    phase_timing["export_seconds"] = time.perf_counter() - phase_started

    phase_started = time.perf_counter()
    if not args.skip_figures:
        print("Generating result figures...")
        try:
            generate_run_figures(
                run_dir=run_dir,
                project_root=project_root,
                dataset=dataset,
                parking_shapefile=paths.get("parking_shapefile"),
                dpi=max(100, int(args.figures_dpi)),
                max_flow_arcs=max(1, int(args.max_redirection_arcs_plot)),
            )
        except Exception as exc:
            print(f"WARNING: Figure generation failed without invalidating optimization results: {exc}")
    phase_timing["figure_generation_seconds"] = time.perf_counter() - phase_started
    monitor.stop()
    phase_timing["total_runtime_seconds"] = time.perf_counter() - total_started
    write_run_complexity(
        run_dir, "Monolithic", data,
        phase_timing=phase_timing,
        model_stats={"main_model": main_model_stats},
        resource_monitor=monitor,
        extra_scalars={"solver_mip_gap_requested": solver_cfg.get("mip_gap")},
    )

    print(f"Run finished successfully. Run directory: {run_dir}")
    return 0


def main() -> int:
    args = parse_args()
    project_root = Path(args.project_root).resolve()
    resolve_input_selection(args, project_root)
    paths, model_cfg, solver_cfg, dataset = load_configs(project_root, args.dataset, args.vipv_scenario)
    apply_profile_defaults(args, load_run_profile(project_root, "monolithic", dataset))
    args._run_profile = f"monolithic.{dataset}"
    sensitivity_overrides = apply_sensitivity_overrides(model_cfg, args)
    args._sensitivity_overrides = sensitivity_overrides
    sensitivity_suffix = make_sensitivity_suffix(args, sensitivity_overrides)

    if args.threads is not None:
        solver_cfg["threads"] = int(args.threads)
    if args.time_limit is not None:
        solver_cfg["time_limit_seconds"] = int(args.time_limit)
    if args.mip_gap is not None:
        solver_cfg["mip_gap"] = float(args.mip_gap)

    method_map = {
        "auto": None,
        "primal": 0,
        "dual": 1,
        "barrier": 2,
        "concurrent": 3,
        "deterministic-concurrent": 4,
    }
    node_method_map = {"auto": None, "primal": 0, "dual": 1, "barrier": 2}

    if method_map[args.root_method] is not None:
        solver_cfg["method"] = method_map[args.root_method]
    if node_method_map[args.node_method] is not None:
        solver_cfg["node_method"] = node_method_map[args.node_method]
    if args.nodefile_start is not None:
        solver_cfg["nodefile_start_gb"] = float(args.nodefile_start)
    if args.soft_mem_limit_gb is not None:
        solver_cfg["soft_mem_limit_gb"] = float(args.soft_mem_limit_gb)
    if args.pre_sparsify is not None:
        solver_cfg["pre_sparsify"] = int(args.pre_sparsify)
    if args.aggregate is not None:
        solver_cfg["aggregate"] = int(args.aggregate)
    if args.pre_passes is not None:
        solver_cfg["pre_passes"] = int(args.pre_passes)
    if args.solver_cuts is not None:
        solver_cfg["cuts"] = int(args.solver_cuts)

    if args.smoke:
        return run_smoke(project_root, paths, model_cfg)

    run_dir = make_run_dir(
        paths=paths,
        scenario=args.scenario,
        dataset=dataset,
        vipv_scenario=args.vipv_scenario,
        hard_no_slack=args.hard_no_slack,
        disable_pv=args.disable_pv,
        disable_bess=args.disable_bess,
        sensitivity_suffix=sensitivity_suffix,
    )
    write_run_folder_readme(
        run_dir,
        dataset,
        args.vipv_scenario,
        args.scenario,
        args.disable_pv,
        args.disable_bess,
        sensitivity_overrides=sensitivity_overrides,
    )

    terminal_log = run_dir / "README_RUN.txt"
    with terminal_log.open("w", encoding="utf-8", errors="replace") as log_file:
        tee_out = TeeStream(sys.__stdout__, log_file)
        tee_err = TeeStream(sys.__stderr__, log_file)
        from contextlib import redirect_stdout, redirect_stderr
        import traceback

        with redirect_stdout(tee_out), redirect_stderr(tee_err):
            print("========== MONOLITHIC TERMINAL LOG ==========")
            print(f"Run transcript : {terminal_log}")
            print("=============================================\n")
            try:
                rc = _run_optimization_impl(
                    args=args,
                    project_root=project_root,
                    paths=paths,
                    model_cfg=model_cfg,
                    solver_cfg=solver_cfg,
                    dataset=dataset,
                    run_dir=run_dir,
                )
                print(f"\nTerminal transcript written to: {terminal_log}")
                return rc
            except Exception:
                print("\nERROR: Monolithic run failed. Full traceback follows.\n")
                traceback.print_exc()
                print(f"\nTerminal transcript written to: {terminal_log}")
                return 1


if __name__ == "__main__":
    raise SystemExit(main())
