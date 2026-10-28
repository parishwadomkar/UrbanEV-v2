"""Modified for the UrbanEV seasonal integration, 2026-10-22. See SOURCE_PROVENANCE.json."""
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import pyomo.environ as pyo
from pyomo.opt import SolverStatus, TerminationCondition

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
for path in (str(PROJECT_ROOT), str(SRC_DIR), str(Path(__file__).resolve().parent)):
    if path not in sys.path:
        sys.path.insert(0, path)

from data_loader import check_input_paths, load_inputs
from export_results import export_all
from model_builder import apply_scenario, build_model
from input_scenarios import add_input_selection_arguments, resolve_input_selection, resolve_scenario_paths
from provenance import record_run_context, assert_restart_identity
from preprocessing import preprocess
from utils import ensure_dir, load_json
from run_profiles import apply_profile_defaults, load_run_profile
from technology_switches import apply_technology_switches
from visualize_results import generate_run_figures
from computational_complexity import ResourceMonitor, model_statistics, write_run_complexity
from solve_model import _gurobi_log_has_soft_memory_stop
from spatial_exact import add_spatial_arguments, solve_spatial_exact
from src_lbbd.decomposition_types import ComponentLogicOptimalityCut, build_slot_components
from src_lbbd.network_feasibility import FeasibilityNetworkOracle
from src_lbbd.operational_recourse import (
    build_monthly_recourse_model,
    solve_monthly_recourse_lp,
    solve_monthly_recourse_mip,
)
from src_lbbd.lbbd_master import (
    AnnualLPDualCut,
    ExactConfigCut,
    InvestmentPoint,
    add_annual_lp_cut,
    add_component_lp_cut,
    add_exact_config_cut,
    add_hall_profit_cut,
    add_partial_component_logic_cut,
    add_static_origin_profit_cuts,
    build_lbbd_master,
    build_global_components,
    component_lp_cut_violation,
    extract_investment,
    partial_logic_cut_violation,
)


class TeeStream:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for stream in self.streams:
            stream.write(text)
            stream.flush()
        return len(text)

    def flush(self):
        for stream in self.streams:
            stream.flush()


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Logic-based Benders decomposition with an embedded continuous "
            "redirection relaxation and exact annual MIP certification."
        )
    )
    add_input_selection_arguments(parser)
    add_spatial_arguments(parser)
    parser.add_argument("--no-redirection-mode", choices=["auto", "spatial", "master"], default="auto")
    parser.add_argument("--hard-no-slack", action="store_true")
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--scenario", choices=["with_redirection", "no_redirection"], default="no_redirection")
    parser.add_argument("--solver", default=None)
    parser.add_argument("--threads", type=int, default=None)
    parser.add_argument(
        "--mip-gap", type=float, default=None,
        help=(
            "Convenience override for the exact annual MIP gap and certified LBBD gap. "
            "The master trial gap remains profile-calibrated unless --master-gap is supplied."
        ),
    )
    parser.add_argument("--subproblem-threads", type=int, default=None)
    parser.add_argument("--master-gap", type=float, default=None)
    parser.add_argument(
        "--master-gap-tight", type=float, default=None,
        help="Tight master MIP gap used automatically after repeated candidates or near convergence.",
    )
    parser.add_argument(
        "--adaptive-master-gap-factor", type=float, default=None,
        help="Multiplicative reduction applied to the trial-master gap during stagnation.",
    )
    parser.add_argument(
        "--stagnation-patience", type=int, default=None,
        help="Repeated-candidate iterations before the master gap is tightened.",
    )
    parser.add_argument(
        "--stagnation-max-rounds", type=int, default=None,
        help="Maximum tight-master repeats with no new cuts before terminating as stalled.",
    )
    parser.add_argument("--subproblem-gap", type=float, default=None)
    parser.add_argument("--logic-mip-gap", type=float, default=None)
    parser.add_argument("--lbbd-gap", type=float, default=None)
    parser.add_argument("--max-iterations", type=int, default=None)
    parser.add_argument("--time-limit", type=int, default=None)
    parser.add_argument("--master-time-limit", type=int, default=None)
    parser.add_argument("--master-late-time-limit", type=int, default=None)
    parser.add_argument("--master-full-solve-iterations", type=int, default=None)
    parser.add_argument("--master-bound-focus-after", type=int, default=None)
    parser.add_argument("--master-mip-focus-early", type=int, default=None)
    parser.add_argument("--master-mip-focus-late", type=int, default=None)
    parser.add_argument(
        "--first-master-solution-limit", type=int, default=None,
        help=(
            "Optional feasibility bootstrap for iteration 1. When positive, Gurobi stops "
            "the first master after this many feasible solutions; later masters use the "
            "normal MIP-gap target. A value of 1 also activates Gurobi's extra "
            "feasible-point heuristics."
        ),
    )
    parser.add_argument(
        "--first-master-heuristics", type=float, default=None,
        help="Optional Heuristics setting used only for the first LBBD master.",
    )
    parser.add_argument(
        "--first-master-lp-bootstrap", action="store_true", default=None,
        help=(
            "Use the continuous relaxation of the initial LBBD master to build an "
            "internal integer investment candidate before the first master MIP. "
            "Recommended for the full dataset when time-to-first-incumbent is poor."
        ),
    )
    parser.add_argument(
        "--no-first-master-lp-bootstrap", dest="first_master_lp_bootstrap",
        action="store_false", default=None,
        help="Disable the continuous-relaxation bootstrap even when enabled by the run profile.",
    )
    parser.add_argument(
        "--first-master-lp-time-limit", type=int, default=None,
        help="Time limit in seconds for the initial continuous master relaxation.",
    )
    parser.add_argument(
        "--bootstrap-hall-refinement-rounds", type=int, default=None,
        help=(
            "Number of additional continuous-master solves used to absorb newly "
            "generated Hall/min-cut profit cuts before the first exact annual "
            "certification. Experimental; disabled in the calibrated full profile."
        ),
    )
    parser.add_argument(
        "--bootstrap-hall-repair-passes", type=int, default=None,
        help=(
            "Number of fast deterministic Hall-capacity repair passes applied to the "
            "rounded LP-bootstrap investment before exact annual certification. The "
            "repair only adds chargers within the existing per-cell resource limits."
        ),
    )
    parser.add_argument(
        "--exact-slack-repair-passes", type=int, default=None,
        help=(
            "Number of deterministic resource-feasible repair passes applied after an "
            "exact annual MIP returns positive slack. The repair may add chargers when "
            "resource is free or perform resource-neutral charger-type swaps; every "
            "repaired point is re-certified by the exact annual MIP before it can improve LB."
        ),
    )
    parser.add_argument(
        "--integer-only-master-start", action="store_true", default=None,
        help=(
            "Warm-start later master MIPs with only integer/binary variables from the "
            "best certified investment. Continuous master variables are left undefined "
            "for Gurobi to recompute, which is more robust numerically on the full model."
        ),
    )
    parser.add_argument(
        "--full-master-start", dest="integer_only_master_start", action="store_false", default=None,
        help="Use the legacy complete master MIP start including continuous variables.",
    )
    parser.add_argument(
        "--bootstrap-checkpoint", default=None,
        help=(
            "Optional JSON checkpoint from a previous compatible LBBD bootstrap run. "
            "When supplied, reuse its investment point and previously proved valid upper bound "
            "instead of re-solving the initial continuous master."
        ),
    )
    parser.add_argument(
        "--resume-certified-run", default=None,
        help=(
            "Development resume from a previous compatible LBBD run directory. The best "
            "certified investment is loaded from results/lbbd_best_infrastructure_by_hex.csv "
            "and the previously proved global upper bound is reused after metadata checks. "
            "The investment is re-certified by the exact annual MIP in the new run."
        ),
    )
    parser.add_argument(
        "--development-investment-run", default=None,
        help=(
            "Development-only investment seed from any compatible completed run (for example "
            "the monolithic benchmark). The per-cell investment layout is loaded from "
            "results/infrastructure_by_hex.csv and is ALWAYS re-certified by the LBBD exact "
            "annual MIP before it can improve the certified lower bound. No objective value or "
            "solver bound from this external run is used as an LBBD certificate."
        ),
    )
    parser.add_argument(
        "--bound-polish", action="store_true", default=None,
        help=(
            "Enable adaptive bound polishing. While the certified outer gap is still large, "
            "the master remains feasibility/incumbent focused; once the gap is below "
            "--bound-polish-trigger-gap it switches to best-bound focus and uses BestBdStop "
            "for the requested outer LBBD certificate."
        ),
    )
    parser.add_argument(
        "--no-bound-polish", dest="bound_polish", action="store_false", default=None,
        help="Disable bound polishing even when enabled by the selected run profile.",
    )
    parser.add_argument(
        "--bound-polish-trigger-gap", type=float, default=None,
        help=(
            "Outer relative-gap threshold at which --bound-polish switches the master from "
            "incumbent improvement to best-bound polishing. The calibrated full profile uses 0.001 (0.1%%)."
        ),
    )
    parser.add_argument(
        "--lp-fallback-on-master-no-incumbent", action="store_true", default=None,
        help=(
            "If a later master MIP returns a valid best bound but no incumbent, "
            "continue from a rounded continuous-master point instead of aborting."
        ),
    )
    parser.add_argument(
        "--no-lp-fallback-on-master-no-incumbent",
        dest="lp_fallback_on_master_no_incumbent", action="store_false", default=None,
        help="Disable the continuous-master fallback after a no-incumbent master MIP.",
    )
    parser.add_argument(
        "--master-start-completion-time-limit", type=int, default=None,
        help=(
            "Time limit in seconds for the fixed-investment LP used to complete a "
            "feasible master start after rounding the bootstrap relaxation."
        ),
    )
    parser.add_argument(
        "--refresh-master-start", action="store_true", default=None,
        help=(
            "Before later full-data master solves, refresh a complete feasible start "
            "by solving the current master with the best certified investments fixed."
        ),
    )
    parser.add_argument(
        "--no-refresh-master-start", dest="refresh_master_start",
        action="store_false", default=None,
        help="Disable fixed-investment start refreshes even when enabled by the profile.",
    )
    parser.add_argument(
        "--no-master-mip-start", action="store_true",
        help="Disable the internally generated feasible zero-slack/slack-only MIP start for the LBBD master.",
    )
    parser.add_argument(
        "--master-heuristic-time", type=float, default=None,
        help="Optional Gurobi NoRelHeurTime for the master; profile value is used when omitted.",
    )
    parser.add_argument(
        "--master-heuristic-work", type=float, default=None,
        help="Optional Gurobi NoRelHeurWork for the master; profile value is used when omitted.",
    )
    parser.add_argument("--finalization-reserve", type=int, default=None)
    parser.add_argument("--subproblem-time-limit", type=int, default=None)
    parser.add_argument("--component-lp-time-limit", type=int, default=None)
    parser.add_argument("--annual-lp-time-limit", type=int, default=None)
    parser.add_argument("--logic-mip-time-limit", type=int, default=None)
    parser.add_argument("--annual-lp-frequency", type=int, default=None)
    parser.add_argument("--annual-core-cut-frequency", type=int, default=None)
    parser.add_argument("--core-point-weight", type=float, default=None)
    parser.add_argument("--exact-fallback-frequency", type=int, default=None)
    parser.add_argument("--logic-mip-frequency", type=int, default=None)
    parser.add_argument("--lp-cut-limit", type=int, default=None)
    parser.add_argument("--logic-cut-limit", type=int, default=None)
    parser.add_argument("--lp-cut-abs-tol", type=float, default=None)
    parser.add_argument("--lp-cut-rel-tol", type=float, default=None)
    parser.add_argument("--logic-cut-abs-tol", type=float, default=None)
    parser.add_argument("--screen-skip-exact-slack-kwh", type=float, default=None)
    parser.add_argument("--nodefile-start", type=float, default=None)
    parser.add_argument("--nodefile-dir", default=None, help="Optional fast local directory for Gurobi node files.")
    parser.add_argument("--soft-mem-limit-gb", type=float, default=None)
    parser.add_argument("--skip-root-hall", action="store_true", default=None)
    parser.add_argument("--skip-static-origin-cuts", action="store_true", default=None)
    parser.add_argument("--skip-component-lp", action="store_true", default=None)
    parser.add_argument(
        "--enable-component-lp", dest="skip_component_lp", action="store_false", default=None,
        help="Override the profile and enable monthly component LP separation.",
    )
    parser.add_argument("--skip-annual-lp", action="store_true", default=None)
    parser.add_argument("--skip-logic-mip", action="store_true", default=None)
    parser.add_argument("--disable-pv", action="store_true")
    parser.add_argument("--disable-bess", action="store_true")
    parser.add_argument("--write-lp", action="store_true")
    parser.add_argument("--tee", action="store_true", default=None)
    parser.add_argument("--run-name", default=None)
    parser.add_argument(
        "--skip-figures", action="store_true", default=None,
        help="Skip automatic figure generation after successful incumbent export.",
    )
    parser.add_argument(
        "--figures-dpi", type=int, default=300,
        help="PNG resolution for automatically generated figures.",
    )
    parser.add_argument(
        "--max-redirection-arcs-plot", type=int, default=150,
        help="Maximum redirection corridors shown on the spatial flow map.",
    )
    parser.add_argument(
        "--redirection-map-month", default="June",
        help="Representative month used for the redirection-corridor map.",
    )
    parser.add_argument(
        "--basemap-alpha", type=float, default=0.28,
        help="Opacity of the optional web basemap used in spatial figures.",
    )
    parser.add_argument("--generate-figures", dest="skip_figures", action="store_false", default=None)
    return parser.parse_args()

def _load_configs(root: Path, dataset: str, vipv_scenario: str):
    cfg = load_json(root / "config" / "model_config.json")
    solver_cfg = load_json(root / "config" / "solver_gurobi.json")
    paths = resolve_scenario_paths(root, dataset, vipv_scenario)
    return paths, cfg, solver_cfg


def _configure_solver(
    opt, args, run_dir: Path, log_name: str, threads: int, gap: float | None,
    time_limit: int, mip: bool, mip_focus: int | None = None,
    solution_limit: int | None = None,
    heuristics_override: float | None = None,
    cuts_override: int | None = None,
    enable_norel: bool = True,
    suppress_improve_start: bool = False,
    best_bound_stop: float | None = None,
    objective_cutoff: float | None = None,
):
    base = dict(getattr(args, "_solver_cfg", {}) or {})
    options = {
        "Threads": int(max(1, threads)),
        "TimeLimit": int(max(1, time_limit)),
        "Presolve": base.get("presolve"),
        "NumericFocus": base.get("numeric_focus"),
        "Heuristics": (base.get("heuristics") if heuristics_override is None else float(heuristics_override)),
        "Cuts": (base.get("cuts") if cuts_override is None else int(cuts_override)),
        "NodefileStart": float(args.nodefile_start),
        "SoftMemLimit": args.soft_mem_limit_gb,
        "PreSparsify": base.get("pre_sparsify"),
        "Aggregate": base.get("aggregate"),
        "AggFill": base.get("agg_fill"),
        "SubMIPNodes": base.get("sub_mip_nodes"),
        "PumpPasses": base.get("pump_passes"),
        "ImproveStartGap": (None if suppress_improve_start else base.get("improve_start_gap")),
        "ImproveStartTime": (None if suppress_improve_start else base.get("improve_start_time")),
        "IntegralityFocus": base.get("integrality_focus"),
        "StartTimeLimit": base.get("start_time_limit"),
        "StartWorkLimit": base.get("start_work_limit"),
        "StartNodeLimit": base.get("start_node_limit"),
        "BestBdStop": best_bound_stop,
        "Cutoff": objective_cutoff,
    }
    for name, value in options.items():
        if value is not None:
            opt.options[name] = value
    node_dir = Path(args.nodefile_dir).expanduser() if args.nodefile_dir else (run_dir / "nodefiles")
    node_dir.mkdir(parents=True, exist_ok=True)
    opt.options["NodefileDir"] = str(node_dir.resolve()).replace("\\", "/")
    opt.options["LogFile"] = str((run_dir / "logs" / log_name).resolve()).replace("\\", "/")
    if mip:
        if gap is not None:
            opt.options["MIPGap"] = float(gap)
        opt.options["MIPFocus"] = int(base.get("mip_focus", 1) if mip_focus is None else mip_focus)
        if solution_limit is not None and int(solution_limit) > 0:
            opt.options["SolutionLimit"] = int(solution_limit)
        root_method = str(base.get("root_method", "")).lower()
        node_method = str(base.get("node_method", "")).lower()
        method_map = {"primal": 0, "dual": 1, "barrier": 2, "concurrent": 3, "deterministic_concurrent": 4, "auto": None, "": None}
        if method_map.get(root_method) is not None:
            opt.options["Method"] = method_map[root_method]
        if method_map.get(node_method) is not None:
            opt.options["NodeMethod"] = method_map[node_method]
        if log_name.startswith("lbbd_master") and bool(enable_norel):
            norel_time = args.master_heuristic_time if args.master_heuristic_time is not None else base.get("master_norel_heur_time")
            norel_work = args.master_heuristic_work if args.master_heuristic_work is not None else base.get("master_norel_heur_work")
            if norel_time is not None and float(norel_time) > 0:
                opt.options["NoRelHeurTime"] = float(norel_time)
            if norel_work is not None and float(norel_work) > 0:
                opt.options["NoRelHeurWork"] = float(norel_work)
    else:
        opt.options["Method"] = 1


class _ExpectedAbortedLoadFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "Loading a SolverResults object with an 'aborted' status" not in record.getMessage()


def _solve_and_load(opt, model, *, tee: bool, warmstart: bool = False):
    model._last_solve_loaded_incumbent = False
    kwargs = {"tee": bool(tee), "load_solutions": False}
    if warmstart:
        kwargs["warmstart"] = True
    try:
        results = opt.solve(model, **kwargs)
    except TypeError:
        kwargs.pop("warmstart", None)
        results = opt.solve(model, **kwargs)

    has_solution = len(getattr(results, "solution", [])) > 0
    term = getattr(results.solver, "termination_condition", None)
    status = getattr(results.solver, "status", None)
    if status == SolverStatus.error and _gurobi_log_has_soft_memory_stop(Path(str(opt.options.get("LogFile", "")))):
        results.solver.status = SolverStatus.aborted
        results.solver.termination_condition = TerminationCondition.resourceInterrupt
        status = results.solver.status
        term = results.solver.termination_condition
    # Gurobi can return an incumbent under time, memory, or SolutionLimit
    # termination.  If a solution is present, load it unless the solver explicitly
    # reports an infeasible/unbounded/error state.  This is important for the
    # first-master feasibility bootstrap (SolutionLimit=1).
    term_text = str(term).replace("_", "").replace(" ", "").lower()
    status_text = str(status).replace("_", "").replace(" ", "").lower()
    bad_term = (
        "infeasible" in term_text
        or ("unbounded" in term_text and "infeasibleorunbounded" not in term_text)
        or "solverfailure" in term_text
        or "internalsolvererror" in term_text
        or term_text == "error"
        or "licensing" in term_text
        or "invalidproblem" in term_text
    )
    loadable = has_solution and not bad_term and status_text != "error"
    if loadable:
        logger = logging.getLogger("pyomo.core")
        filter_ = _ExpectedAbortedLoadFilter()
        logger.addFilter(filter_)
        try:
            model.solutions.load_from(results)
            model._last_solve_loaded_incumbent = True
        finally:
            logger.removeFilter(filter_)
    return results


def _solve_lp_and_load(opt, model, *, tee: bool):
    """Solve an LP without letting Pyomo crash on an interrupted solve.

    With the classic Pyomo/Gurobi interface, ``load_solutions=True`` asks Pyomo to
    load the result immediately.  If Gurobi stops at a time limit before a usable
    primal solution exists, the solver status can be ``aborted`` and Pyomo raises a
    ``ValueError`` while loading.  Large full-data LP refinements can legitimately
    hit such a limit.

    Solve with automatic loading disabled, then explicitly load only when the
    results object actually contains a solution.  Callers still decide whether the
    termination condition is strong enough for their purpose.
    """
    model._last_solve_loaded_incumbent = False
    results = opt.solve(model, tee=bool(tee), load_solutions=False)
    try:
        has_solution = len(getattr(results, "solution", [])) > 0
    except Exception:
        has_solution = False
    if has_solution:
        try:
            model.solutions.load_from(results)
            model._last_solve_loaded_incumbent = True
        except ValueError as exc:
            print(
                "WARNING: Solver returned a result that Pyomo could not load "
                f"(termination={_solver_term(results)}): {exc}"
            )
    return results


def _solve_master(
    model, args, run_dir: Path, iteration: int, remaining_seconds: float,
    requested_gap: float, force_full_time: bool = False, use_mip_start: bool = False,
    certified_lb: float = -math.inf, global_upper_bound: float = math.inf,
):
    full_iterations = max(0, int(args.master_full_solve_iterations))
    use_full_time = bool(force_full_time) or iteration <= full_iterations
    requested_limit = int(args.master_time_limit) if use_full_time else int(args.master_late_time_limit)
    available = max(1, int(float(remaining_seconds) - float(args.finalization_reserve)))
    solve_limit = max(1, min(requested_limit, available))
    default_focus = (
        int(args.master_mip_focus_early)
        if iteration < int(args.master_bound_focus_after)
        else int(args.master_mip_focus_late)
    )
    outer_gap_before = (
        _rel_gap(float(global_upper_bound), float(certified_lb))
        if math.isfinite(float(global_upper_bound)) and math.isfinite(float(certified_lb))
        else math.inf
    )
    polish_trigger = float(
        args.bound_polish_trigger_gap
        if args.bound_polish_trigger_gap is not None
        else max(0.001, 4.0 * float(args.lbbd_gap))
    )
    polish_active = (
        bool(getattr(args, "bound_polish", False))
        and math.isfinite(outer_gap_before)
        and outer_gap_before <= polish_trigger
    )
    if bool(getattr(args, "bound_polish", False)) and math.isfinite(float(certified_lb)):
        focus = 3 if polish_active else 1
        phase_name = "best-bound polishing" if polish_active else "incumbent improvement"
        print(
            f"Adaptive bound-polish master: outer gap {100.0 * outer_gap_before:.6f}% "
            f"vs trigger {100.0 * polish_trigger:.6f}% -> {phase_name} (MIPFocus={focus})."
        )
    else:
        focus = default_focus
    opt = pyo.SolverFactory(args.solver)
    first_solution_limit = 0
    if iteration == 1 and args.first_master_solution_limit is not None:
        first_solution_limit = max(0, int(args.first_master_solution_limit))
    first_heuristics = (
        float(args.first_master_heuristics)
        if iteration == 1 and args.first_master_heuristics is not None
        else None
    )
    best_bound_stop = None
    objective_cutoff = None
    if math.isfinite(float(certified_lb)) and float(certified_lb) > 0.0:
        # A master solution whose relaxed objective is already below the certified
        # exact incumbent cannot improve that incumbent.  This cutoff is useful in
        # both the incumbent-improvement and bound-polishing phases.
        objective_cutoff = float(certified_lb) - max(
            1.0, 1.0e-9 * abs(float(certified_lb))
        )
    if (
        polish_active
        and math.isfinite(float(certified_lb))
        and float(certified_lb) > 0.0
        and 0.0 < float(args.lbbd_gap) < 1.0
    ):
        # For the implemented maximization gap g=(UB-LB)/UB, g<=eps is
        # guaranteed once UB <= LB/(1-eps). Ask Gurobi to stop a little
        # *inside* that threshold to protect against numerical round-off.
        target_ub = float(certified_lb) / (1.0 - float(args.lbbd_gap))
        best_bound_stop = target_ub - max(1.0, 1.0e-8 * abs(target_ub))
        print(
            f"Bound-polish master targets: certified LB {certified_lb:,.3f}; "
            f"Cutoff {objective_cutoff:,.3f}; BestBdStop {best_bound_stop:,.3f} SEK/year."
        )
    _configure_solver(
        opt, args, run_dir, f"lbbd_master_{iteration:03d}.log",
        int(args.threads), float(requested_gap), solve_limit, True, mip_focus=focus,
        solution_limit=(first_solution_limit if first_solution_limit > 0 else None),
        heuristics_override=(0.05 if polish_active else first_heuristics),
        cuts_override=(2 if polish_active else None),
        # After iteration 1 the previous certified investment is available as a
        # partial start, so NoRel is unnecessary.  In the tight-bound phase we
        # also disable ImproveStart* controls because primal improvement is no
        # longer the bottleneck.
        enable_norel=(iteration == 1 and not math.isfinite(float(certified_lb))),
        suppress_improve_start=polish_active,
        best_bound_stop=best_bound_stop,
        objective_cutoff=objective_cutoff,
    )
    started = time.time()
    results = _solve_and_load(
        opt, model, tee=bool(args.tee),
        warmstart=(iteration > 1 or bool(use_mip_start)),
    )
    return results, solve_limit, focus, time.time() - started

def _solver_term(results) -> str:
    try:
        return str(results.solver.termination_condition).replace("_", "").replace(" ", "").lower()
    except Exception:
        return "unknown"


def _is_optimal_lp(results) -> bool:
    return getattr(results.solver, "termination_condition", None) == TerminationCondition.optimal


def _finite_component_value(component) -> float:
    """Return a finite Pyomo scalar value or NaN without raising."""
    try:
        value = pyo.value(component, exception=False)
        if value is None:
            return math.nan
        value = float(value)
        return value if math.isfinite(value) else math.nan
    except Exception:
        return math.nan


def _has_loaded_objective(model) -> bool:
    """Check whether an active objective can be evaluated from loaded primals.

    The monolithic/exact model names its objective ``obj``, while the LBBD master
    names it ``Objective`` and maximizes ``Eta``.  Checking only ``model.obj``
    therefore falsely rejected a correctly loaded full-master LP bootstrap.
    Inspecting active Objective components makes this helper model-name agnostic.
    """
    try:
        for objective in model.component_data_objects(
            pyo.Objective, active=True, descend_into=True
        ):
            if math.isfinite(_finite_component_value(objective.expr)):
                return True
    except Exception:
        pass
    return False


def _loaded_master_eta(model) -> float:
    """Return the loaded LBBD master Eta value, or NaN when unavailable."""
    if not hasattr(model, "Eta"):
        return math.nan
    return _finite_component_value(model.Eta)


def _is_usable_mip(results, model) -> bool:
    if not getattr(model, "_last_solve_loaded_incumbent", False) or not _has_loaded_objective(model):
        return False
    term = _solver_term(results)
    bad = ("infeasible" in term) or ("unbounded" in term and "infeasibleorunbounded" not in term)
    return not bad


def _master_bound(results, model) -> float:
    value = getattr(results.problem, "upper_bound", None)
    try:
        value = float(value)
    except Exception:
        value = math.nan
    if math.isfinite(value):
        return value
    if getattr(results.solver, "termination_condition", None) == TerminationCondition.optimal:
        try:
            return float(pyo.value(model.Eta))
        except Exception:
            return math.inf
    return math.inf


def _rel_gap(ub: float, lb: float) -> float:
    if not math.isfinite(ub) or not math.isfinite(lb):
        return math.inf
    return max(0.0, float(ub) - float(lb)) / max(1.0, abs(float(ub)))


def _fix_investments(model, inv: InvestmentPoint):
    for i in model.I:
        ii = int(i)
        for c in model.C_pub:
            model.x[i, c].fix(int(inv.x.get((ii, str(c)), 0)))
        model.PV[i].fix(int(inv.pv.get(ii, 0)))
        model.Batt[i].fix(int(inv.batt.get(ii, 0)))


def _add_investment_fix_equalities(model, inv: InvestmentPoint):
    model.dual = pyo.Suffix(direction=pyo.Suffix.IMPORT)
    model.RecourseFixX = pyo.Constraint(
        model.I, model.C_pub,
        rule=lambda m, i, c: m.x[i, c] == float(inv.x.get((int(i), str(c)), 0.0)),
    )
    model.RecourseFixPV = pyo.Constraint(
        model.I,
        rule=lambda m, i: m.PV[i] == float(inv.pv.get(int(i), 0.0)),
    )
    model.RecourseFixBatt = pyo.Constraint(
        model.I,
        rule=lambda m, i: m.Batt[i] == float(inv.batt.get(int(i), 0.0)),
    )



def _initialize_exact_recourse_discrete_start(model) -> None:
    """Set a trivial internally feasible discrete recourse pattern.

    Investments are already fixed by ``_fix_investments``.  Zero redirection,
    zero trip counts, and no battery charging mode leave the continuous recourse
    completion free to satisfy demand with the model's penalized slack variables.
    This is an internal current-model start, not an external warm start.
    """
    for i in model.I:
        for mon in model.M:
            for t in model.H:
                model.delta[i, mon, t].value = 0
    for a in model.A:
        model.Yarc[a].value = 0
        model.n_trip[a].value = 0


def _solve_fixed_exact(data: dict, cfg: dict, args, run_dir: Path, inv: InvestmentPoint, iteration: int):
    model = build_model(data, cfg)
    apply_technology_switches(model, args.disable_pv, args.disable_bess, verbose=False)
    apply_scenario(model, args.scenario)
    _fix_investments(model, inv)
    opt = pyo.SolverFactory(args.solver)
    _initialize_exact_recourse_discrete_start(model)
    _configure_solver(
        opt, args, run_dir, f"lbbd_exact_annual_{iteration:03d}.log",
        int(args.subproblem_threads), float(args.subproblem_gap), int(args.subproblem_time_limit), True,
    )
    results = _solve_and_load(opt, model, tee=bool(args.tee), warmstart=True)
    if not _is_usable_mip(results, model):
        if "infeasibleorunbounded" in _solver_term(results):
            opt.options["DualReductions"] = 0
            results = _solve_and_load(opt, model, tee=bool(args.tee), warmstart=True)
        if not _is_usable_mip(results, model):
            raise RuntimeError(
                f"Exact fixed-investment annual MIP failed at iteration {iteration}: "
                f"termination={_solver_term(results)}"
            )
    objective = float(pyo.value(model.obj))
    upper = getattr(results.problem, "upper_bound", None)
    try:
        upper = float(upper)
    except Exception:
        upper = math.nan
    if not math.isfinite(upper):
        # The incumbent is a fixed-layout upper bound only after optimality.
        upper = objective if getattr(results.solver, "termination_condition", None) == TerminationCondition.optimal else math.inf
    upper = max(objective, upper)
    gap = _rel_gap(upper, objective)
    return model, results, objective, upper, gap


def _solve_fixed_annual_lp_cut(
    data: dict, cfg: dict, args, run_dir: Path, inv: InvestmentPoint, iteration: int,
    probe_name: str = "candidate", cut_id: int | None = None,
):
    """Linked 12-month LP cut retaining the exact monolithic BESS chronology."""
    model = build_model(data, cfg)
    apply_technology_switches(model, args.disable_pv, args.disable_bess, verbose=False)
    apply_scenario(model, args.scenario)
    _add_investment_fix_equalities(model, inv)
    pyo.TransformationFactory("core.relax_integer_vars").apply_to(model)

    opt = pyo.SolverFactory(args.solver)
    _configure_solver(
        opt, args, run_dir, f"lbbd_linked_annual_lp_{iteration:03d}_{probe_name}.log",
        int(args.subproblem_threads), None, int(args.annual_lp_time_limit), False,
    )
    results = _solve_lp_and_load(opt, model, tee=bool(args.tee))
    if not _is_optimal_lp(results):
        if "infeasibleorunbounded" in _solver_term(results):
            opt.options["DualReductions"] = 0
            results = _solve_lp_and_load(opt, model, tee=bool(args.tee))
        if not _is_optimal_lp(results):
            return model, results, None, math.nan

    lp_obj = float(pyo.value(model.obj))
    x_coeff: dict[tuple[int, str], float] = {}
    pv_coeff: dict[int, float] = {}
    batt_coeff: dict[int, float] = {}
    for i in model.I:
        ii = int(i)
        for c in model.C_pub:
            cc = str(c)
            x_coeff[(ii, cc)] = float(model.dual.get(model.RecourseFixX[i, c], 0.0) or 0.0)
        pv_coeff[ii] = float(model.dual.get(model.RecourseFixPV[i], 0.0) or 0.0)
        batt_coeff[ii] = float(model.dual.get(model.RecourseFixBatt[i], 0.0) or 0.0)

    constant = lp_obj
    constant -= sum(x_coeff[k] * float(inv.x.get(k, 0)) for k in x_coeff)
    constant -= sum(pv_coeff[i] * float(inv.pv.get(i, 0)) for i in pv_coeff)
    constant -= sum(batt_coeff[i] * float(inv.batt.get(i, 0)) for i in batt_coeff)
    reconstructed = constant
    reconstructed += sum(x_coeff[k] * float(inv.x.get(k, 0)) for k in x_coeff)
    reconstructed += sum(pv_coeff[i] * float(inv.pv.get(i, 0)) for i in pv_coeff)
    reconstructed += sum(batt_coeff[i] * float(inv.batt.get(i, 0)) for i in batt_coeff)
    tolerance = max(1000.0, 1e-5 * max(1.0, abs(lp_obj)))
    if abs(reconstructed - lp_obj) > tolerance:
        raise RuntimeError(
            f"Linked annual LP cut reconstruction failed at iteration {iteration}: "
            f"lp={lp_obj:.6f}, reconstructed={reconstructed:.6f}, tolerance={tolerance:.6f}"
        )
    cut = AnnualLPDualCut(
        cut_id=int(iteration if cut_id is None else cut_id),
        constant=float(constant),
        x_coefficients=x_coeff,
        pv_coefficients=pv_coeff,
        batt_coefficients=batt_coeff,
        lp_objective=float(lp_obj),
        source_kind=f"linked_annual_lp_{probe_name}",
    )
    return model, results, cut, lp_obj


def _investment_totals(inv: InvestmentPoint) -> dict[str, int]:
    return {
        "slow": sum(v for (_, c), v in inv.x.items() if c == "slow"),
        "medium": sum(v for (_, c), v in inv.x.items() if c == "medium"),
        "fast": sum(v for (_, c), v in inv.x.items() if c == "fast"),
        "PV": sum(inv.pv.values()),
        "BESS": sum(inv.batt.values()),
    }


def _investment_signature(inv: InvestmentPoint) -> tuple:
    """Exact, deterministic signature for candidate caching and stagnation checks."""
    return (
        tuple(sorted((int(i), str(c), int(round(float(v)))) for (i, c), v in inv.x.items())),
        tuple(sorted((int(i), int(round(float(v)))) for i, v in inv.pv.items())),
        tuple(sorted((int(i), int(round(float(v)))) for i, v in inv.batt.items())),
    )


def _signature_label(signature: tuple) -> str:
    # A compact stable identifier without importing a nonstandard hash package.
    import hashlib
    return hashlib.sha1(repr(signature).encode("utf-8")).hexdigest()[:12]


def _blend_investments(previous: InvestmentPoint | None, current: InvestmentPoint, weight: float) -> InvestmentPoint:
    if previous is None:
        return InvestmentPoint(dict(current.x), dict(current.pv), dict(current.batt))
    w = min(0.99, max(0.01, float(weight)))
    return InvestmentPoint(
        x={k: w * float(previous.x.get(k, 0.0)) + (1.0 - w) * float(current.x.get(k, 0.0)) for k in current.x},
        pv={i: w * float(previous.pv.get(i, 0.0)) + (1.0 - w) * float(current.pv.get(i, 0.0)) for i in current.pv},
        batt={i: w * float(previous.batt.get(i, 0.0)) + (1.0 - w) * float(current.batt.get(i, 0.0)) for i in current.batt},
    )


def _annual_lp_cut_rhs(cut: AnnualLPDualCut, inv: InvestmentPoint) -> float:
    value = float(cut.constant)
    value += sum(float(v) * float(inv.x.get(k, 0.0)) for k, v in cut.x_coefficients.items())
    value += sum(float(v) * float(inv.pv.get(i, 0.0)) for i, v in cut.pv_coefficients.items())
    value += sum(float(v) * float(inv.batt.get(i, 0.0)) for i, v in cut.batt_coefficients.items())
    return float(value)


def _write_history(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_investment_csv(path: Path, data: dict, inv: InvestmentPoint) -> None:
    rows = []
    for i in data["hex_ids"]:
        ii = int(i)
        rows.append({
            "HexID": ii,
            "slow_chargers": inv.x.get((ii, "slow"), 0),
            "medium_chargers": inv.x.get((ii, "medium"), 0),
            "fast_chargers": inv.x.get((ii, "fast"), 0),
            "PV_panels": inv.pv.get(ii, 0),
            "Battery_units": inv.batt.get(ii, 0),
        })
    pd.DataFrame(rows).to_csv(path, index=False)


def _model_counts(model) -> tuple[int, int]:
    variables = sum(1 for _ in model.component_data_objects(pyo.Var, active=True, descend_into=True))
    constraints = sum(1 for _ in model.component_data_objects(pyo.Constraint, active=True, descend_into=True))
    return int(variables), int(constraints)


def _add_hall_cuts(master, data: dict, screen) -> int:
    return sum(int(add_hall_profit_cut(master, data, cert)) for cert in screen.certificates)


def _solve_component_lps(month_models, master, data: dict, components: dict, candidate: InvestmentPoint, args, run_dir: Path, iteration: int):
    all_cuts = []
    results_by_month = {}
    for month in data["MONTHS"]:
        result = solve_monthly_recourse_lp(
            month_models[str(month)], data, components, candidate.x, iteration,
            args.solver, int(args.subproblem_threads), bool(args.tee), run_dir / "logs" / "component_lp",
            source_kind="lbbd_master_candidate", time_limit=int(args.component_lp_time_limit),
            solver_options=args._solver_cfg,
        )
        results_by_month[str(month)] = result
        all_cuts.extend(result.cuts)

    scored = []
    for cut in all_cuts:
        violation = component_lp_cut_violation(master, cut, candidate.x)
        key = (str(cut.month), int(cut.time_index), int(cut.component_id))
        scale = max(1.0, abs(float(master._component_cap[key])))
        threshold = max(float(args.lp_cut_abs_tol), float(args.lp_cut_rel_tol) * scale)
        if violation > threshold:
            scored.append((violation / scale, violation, cut))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    limit = max(0, int(args.lp_cut_limit))
    selected = scored if limit == 0 else scored[:limit]
    added = sum(int(add_component_lp_cut(master, cut)) for _, _, cut in selected)
    max_violation = max((v for _, v, _ in scored), default=0.0)
    return results_by_month, int(added), int(len(scored)), float(max_violation)


def _solve_logic_mips(month_models, lp_results, master, data: dict, cfg: dict, components: dict, candidate: InvestmentPoint, args, run_dir: Path, iteration: int):
    candidates: list[tuple[float, ComponentLogicOptimalityCut]] = []
    for month in data["MONTHS"]:
        mon = str(month)
        lp_upper = float(lp_results[mon].objective)
        result = solve_monthly_recourse_mip(
            month_models[mon], data, cfg, components, candidate.x,
            args.solver, int(args.subproblem_threads), bool(args.tee), run_dir / "logs" / "logic_mip",
            iteration, float(args.logic_mip_gap), int(args.logic_mip_time_limit), lp_upper,
            source_kind="lbbd_exact_baseline",
            solver_options=args._solver_cfg,
        )
        for key, upper in result.component_upper_bounds.items():
            cut = ComponentLogicOptimalityCut(
                month=str(key[0]), time_index=int(key[1]), component_id=int(key[2]),
                operation_upper_bound=float(upper), x_values=dict(candidate.x),
                source_iteration=int(iteration), source_kind="exact_monthly_baseline_mip",
            )
            violation = partial_logic_cut_violation(master, cut)
            if violation > float(args.logic_cut_abs_tol):
                scale = max(1.0, abs(float(master._component_cap[(str(key[0]), int(key[1]), int(key[2]))])))
                candidates.append((violation / scale, cut))
    candidates.sort(key=lambda item: item[0], reverse=True)
    limit = max(0, int(args.logic_cut_limit))
    selected = candidates if limit == 0 else candidates[:limit]
    added = sum(int(add_partial_component_logic_cut(master, cut)) for _, cut in selected)
    return int(added), int(len(candidates))




def _set_binary_expansion_start(value: int, bit_var, indexes: list[int], *prefix) -> None:
    value = int(max(0, value))
    for k in indexes:
        bit_var[(*prefix, int(k))].value = 1 if ((value >> int(k)) & 1) else 0


def _initialize_master_slack_start(master, data: dict, cfg: dict) -> float:
    """Populate a complete feasible MIP start for the LBBD master.

    The start is generated only from the current data/config.  It installs no
    infrastructure and satisfies demand via the existing penalized slack variables.
    This is intentionally not an external warm start: it is a trivial feasible
    master point that gives Gurobi an incumbent before the expensive root
    relaxation on full data.  The solver is free to improve or discard it.
    """
    # Investment variables and exact-configuration bit encodings.
    for i in master.I:
        ii = int(i)
        for c in master.C:
            cc = str(c)
            master.x[ii, cc].value = 0
            _set_binary_expansion_start(0, master.xbit, master._bits_x[(ii, cc)], ii, cc)
        master.PV[ii].value = 0
        _set_binary_expansion_start(0, master.pvbit, master._bits_pv[ii], ii)
        master.Batt[ii].value = 0
        _set_binary_expansion_start(0, master.battbit, master._bits_batt[ii], ii)

    # Continuous redirection/service relaxation: no charging service, all demand
    # is assigned to the model's own slack variables.
    for i in master.I:
        ii = int(i)
        for mon in master.M:
            mm = str(mon)
            for t in master.H:
                tt = int(t)
                for c in master.C:
                    master.Service[ii, mm, tt, str(c)].value = 0.0
                master.HomeServed[ii, mm, tt].value = 0.0
                master.PublicLocal[ii, mm, tt].value = 0.0
                master.SlackHome[ii, mm, tt].value = float(data["demand_event_annual"][(ii, mm, tt, "home")])
                master.SlackPublic[ii, mm, tt].value = float(data["demand_event_annual"][(ii, mm, tt, "public")])
                master.PVDir[ii, mm, tt].value = 0.0
                master.PVBatt[ii, mm, tt].value = 0.0
                master.GridBatt[ii, mm, tt].value = 0.0
                master.BattDis[ii, mm, tt].value = 0.0
            for h in master.HSOC:
                master.SOC[ii, mm, int(h)].value = 0.0
    for a in master.A:
        master.Redirect[a].value = 0.0

    penalty = float(cfg["penalty_per_kwh_slack"])
    eta_start = 0.0
    for key in master.COMP:
        mon, t, cid = str(key[0]), int(key[1]), int(key[2])
        theta = -float(data["N_MONTH"][mon]) * penalty * float(master._component_demand[(mon, t, cid)])
        master.Theta[mon, t, cid].value = theta
        eta_start += theta
    # This value satisfies EmbeddedRelaxation and GlobalRevenueCap for the zero
    # investment/slack-only point.
    master.Eta.value = float(eta_start)
    return float(eta_start)



def _relax_master_integrality(master) -> list[tuple[object, object]]:
    """Temporarily relax every active discrete master variable in-place.

    The initial full-data LBBD master has a very large continuous block and a
    comparatively small discrete investment block.  Solving its continuous
    relaxation first provides both a rigorous upper bound and a high-quality
    investment direction without duplicating the multi-million-variable model in
    memory.  Domains are restored by ``_restore_master_integrality``.
    """
    saved: list[tuple[object, object]] = []
    for var in master.component_data_objects(pyo.Var, active=True, descend_into=True):
        if var.is_binary():
            saved.append((var, var.domain))
            var.domain = pyo.UnitInterval
        elif var.is_integer():
            saved.append((var, var.domain))
            var.domain = pyo.Reals
    return saved


def _restore_master_integrality(saved: list[tuple[object, object]]) -> None:
    for var, domain in saved:
        var.domain = domain


def _round_master_relaxation_investment(master) -> InvestmentPoint:
    """Round a fractional master investment point without violating site resources.

    Charger counts are floored first, which always preserves the resource
    constraint.  Remaining site resources are then used to round up charger types
    with the largest fractional parts.  PV and BESS units have independent upper
    bounds in the master and are rounded to the nearest feasible integer.
    """
    x: dict[tuple[int, str], int] = {}
    pv: dict[int, int] = {}
    batt: dict[int, int] = {}

    for i in master.I:
        ii = int(i)
        base: dict[str, int] = {}
        frac: list[tuple[float, float, str]] = []
        used = 0.0
        for c in master.C:
            cc = str(c)
            raw = pyo.value(master.x[ii, cc], exception=False)
            raw = 0.0 if raw is None or not math.isfinite(float(raw)) else max(0.0, float(raw))
            ub = int(master._x_upper[(ii, cc)])
            floor_value = min(ub, max(0, int(math.floor(raw + 1e-9))))
            base[cc] = floor_value
            resource = float(pyo.value(master.Resource[cc])) if hasattr(master, "Resource") else 1.0
            used += resource * floor_value
            if floor_value < ub:
                frac.append((raw - math.floor(raw), resource, cc))

        remaining = max(0.0, float(pyo.value(master.CL[ii])) - used)
        # Preserve closeness to the LP point while remaining deterministically feasible.
        for fractional, resource, cc in sorted(frac, key=lambda item: (-item[0], item[1], item[2])):
            if fractional <= 1e-9:
                continue
            if resource <= remaining + 1e-9:
                base[cc] += 1
                remaining -= resource
        for cc, value in base.items():
            x[(ii, cc)] = int(value)

        raw_pv = pyo.value(master.PV[ii], exception=False)
        raw_pv = 0.0 if raw_pv is None or not math.isfinite(float(raw_pv)) else max(0.0, float(raw_pv))
        pv[ii] = min(int(master._pv_upper[ii]), max(0, int(math.floor(raw_pv + 0.5))))

        raw_batt = pyo.value(master.Batt[ii], exception=False)
        raw_batt = 0.0 if raw_batt is None or not math.isfinite(float(raw_batt)) else max(0.0, float(raw_batt))
        batt[ii] = min(int(master._batt_upper[ii]), max(0, int(math.floor(raw_batt + 0.5))))

    return InvestmentPoint(x=x, pv=pv, batt=batt)


def _fix_master_discrete_configuration(master, inv: InvestmentPoint) -> list[object]:
    """Fix all discrete variables implied by an investment point.

    This includes the reusable binary expansions and any threshold indicators
    introduced by partial logic cuts.  Given fixed investments, each threshold
    indicator has a deterministic value.
    """
    fixed: list[object] = []
    for i in master.I:
        ii = int(i)
        for c in master.C:
            cc = str(c)
            value = int(inv.x.get((ii, cc), 0))
            master.x[ii, cc].fix(value)
            fixed.append(master.x[ii, cc])
            for k in master._bits_x[(ii, cc)]:
                bit = 1 if ((value >> int(k)) & 1) else 0
                master.xbit[ii, cc, int(k)].fix(bit)
                fixed.append(master.xbit[ii, cc, int(k)])

        pv_value = int(inv.pv.get(ii, 0))
        master.PV[ii].fix(pv_value)
        fixed.append(master.PV[ii])
        for k in master._bits_pv[ii]:
            bit = 1 if ((pv_value >> int(k)) & 1) else 0
            master.pvbit[ii, int(k)].fix(bit)
            fixed.append(master.pvbit[ii, int(k)])

        batt_value = int(inv.batt.get(ii, 0))
        master.Batt[ii].fix(batt_value)
        fixed.append(master.Batt[ii])
        for k in master._bits_batt[ii]:
            bit = 1 if ((batt_value >> int(k)) & 1) else 0
            master.battbit[ii, int(k)].fix(bit)
            fixed.append(master.battbit[ii, int(k)])

    for (i, c, threshold), indicator in getattr(master, "_partial_threshold_cache", {}).items():
        value = 1 if int(inv.x.get((int(i), str(c)), 0)) >= int(threshold) + 1 else 0
        indicator.fix(value)
        fixed.append(indicator)
    return fixed


def _unfix_master_variables(fixed: list[object]) -> None:
    for var in fixed:
        var.unfix()


def _solve_master_lp_bootstrap(
    master, args, run_dir: Path, log_name: str = "lbbd_master_bootstrap_lp.log"
) -> tuple[InvestmentPoint | None, float, float]:
    """Solve the continuous initial master and round it to an integer investment point.

    Returns ``(investment, LP upper bound, solve seconds)``.  The LP objective is
    a rigorous upper bound because it relaxes only integrality from an already
    valid LBBD master relaxation.  No external solution information is used.
    """
    saved_domains = _relax_master_integrality(master)
    opt = pyo.SolverFactory(args.solver)
    limit = max(1, int(args.first_master_lp_time_limit))
    _configure_solver(
        opt, args, run_dir, str(log_name),
        int(args.threads), None, limit, False,
    )
    started = time.time()
    try:
        results = _solve_lp_and_load(opt, master, tee=bool(args.tee))
        elapsed = time.time() - started
        term = _solver_term(results)
        eta_value = _loaded_master_eta(master)
        if not _is_optimal_lp(results) or not getattr(master, "_last_solve_loaded_incumbent", False) or not math.isfinite(eta_value):
            print(
                "LP bootstrap solution-load check failed: "
                f"termination={term}, eta_loaded={math.isfinite(eta_value)}, "
                f"objective_loaded={_has_loaded_objective(master)}."
            )
            return None, math.inf, elapsed
        upper = float(eta_value)
        candidate = _round_master_relaxation_investment(master)
        print(
            f"LP bootstrap solved and loaded successfully: termination={term}, "
            f"upper_bound={upper:,.3f} SEK/year, elapsed={elapsed:.1f}s."
        )
        return candidate, upper, elapsed
    finally:
        _restore_master_integrality(saved_domains)


def _complete_master_start(
    master, inv: InvestmentPoint, args, run_dir: Path, label: str,
    time_limit: int | None = None,
) -> tuple[bool, float, float]:
    """Complete a full feasible master solution for fixed integer investments.

    The solve is an LP after the master discrete configuration is fixed and
    temporarily relaxed.  The resulting Pyomo variable values form a complete,
    internally generated MIP start for the next master solve.
    """
    fixed = _fix_master_discrete_configuration(master, inv)
    saved_domains = _relax_master_integrality(master)
    opt = pyo.SolverFactory(args.solver)
    limit = max(1, int(time_limit or args.master_start_completion_time_limit))
    _configure_solver(
        opt, args, run_dir, f"lbbd_master_start_{label}.log",
        int(args.threads), None, limit, False,
    )
    started = time.time()
    try:
        results = _solve_lp_and_load(opt, master, tee=bool(args.tee))
        elapsed = time.time() - started
        eta_value = _loaded_master_eta(master)
        if not _is_optimal_lp(results) or not getattr(master, "_last_solve_loaded_incumbent", False) or not math.isfinite(eta_value):
            print(
                "Fixed-investment master LP completion failed: "
                f"termination={_solver_term(results)}, "
                f"eta_loaded={math.isfinite(eta_value)}, "
                f"objective_loaded={_has_loaded_objective(master)}."
            )
            return False, math.nan, elapsed
        return True, float(eta_value), elapsed
    finally:
        _restore_master_integrality(saved_domains)
        _unfix_master_variables(fixed)


def _copy_investment(inv: InvestmentPoint) -> InvestmentPoint:
    return InvestmentPoint(dict(inv.x), dict(inv.pv), dict(inv.batt))


def _site_capacity_gain_repair(
    inv: InvestmentPoint,
    data: dict,
    hex_id: int,
    required_gain_kwh_slot: float,
) -> tuple[InvestmentPoint, float, list[str]]:
    """Increase one site's installed kWh/slot without violating its resource limit.

    Free resource is used first.  If less than one unit of the most resource-efficient
    charger is free, the routine can replace a lower capacity-per-resource charger by
    several higher-efficiency chargers using no additional resource.  This is a
    candidate-generation heuristic only; the exact annual MIP re-certifies every result.
    """
    repaired = _copy_investment(inv)
    i = int(hex_id)
    required = max(0.0, float(required_gain_kwh_slot))
    if required <= 1e-9:
        return repaired, 0.0, []

    resources = {str(c): float(data["charger_resources"][str(c)]) for c in data["PUB_TYPES"]}
    capacity = {str(c): float(data["charger_capacity_pub"][str(c)]) for c in data["PUB_TYPES"]}
    type_order = sorted(
        (str(c) for c in data["PUB_TYPES"]),
        key=lambda c: (-capacity[c] / max(1e-12, resources[c]), c),
    )
    limit = float(data["cl"][i])

    def used() -> float:
        return sum(resources[c] * float(repaired.x.get((i, c), 0)) for c in type_order)

    actions: list[str] = []
    gained = 0.0

    # First use truly free site resource.
    for c in type_order:
        free = max(0.0, limit - used())
        max_add = int(math.floor((free + 1e-9) / resources[c]))
        if max_add <= 0:
            continue
        need = max(1, int(math.ceil((required - gained) / max(1e-12, capacity[c]) - 1e-12)))
        add = min(max_add, need)
        if add > 0:
            repaired.x[(i, c)] = int(repaired.x.get((i, c), 0)) + int(add)
            delta = float(add) * capacity[c]
            gained += delta
            actions.append(f"hex {i}: +{add} {c} ({delta:.3f} kWh/slot)")
        if gained + 1e-9 >= required:
            return repaired, gained, actions

    # If the site is effectively full, perform a resource-neutral efficiency swap.
    # Lower-efficiency installed types are considered first.  For the current model,
    # this naturally permits medium -> several slow chargers where slow offers more
    # charging capacity per scarce resource unit.
    outgoing_order = sorted(
        type_order,
        key=lambda c: (capacity[c] / max(1e-12, resources[c]), c),
    )
    safety = 0
    while gained + 1e-9 < required and safety < 1000:
        safety += 1
        best_move = None
        free = max(0.0, limit - used())
        for out_c in outgoing_order:
            if int(repaired.x.get((i, out_c), 0)) <= 0:
                continue
            for in_c in type_order:
                if in_c == out_c:
                    continue
                available = free + resources[out_c]
                max_add = int(math.floor((available + 1e-9) / resources[in_c]))
                if max_add <= 0:
                    continue
                # Removing one outgoing charger loses its capacity. Choose the
                # smallest number of incoming chargers that creates a positive gain
                # and, when possible, covers the remaining deficit.
                min_positive = int(math.floor(capacity[out_c] / capacity[in_c])) + 1
                desired = int(math.ceil((capacity[out_c] + (required - gained)) / capacity[in_c] - 1e-12))
                add = max(min_positive, desired)
                if add > max_add:
                    add = max_add
                net_gain = float(add) * capacity[in_c] - capacity[out_c]
                if net_gain <= 1e-9:
                    continue
                resource_after = used() - resources[out_c] + float(add) * resources[in_c]
                if resource_after > limit + 1e-8:
                    continue
                # Prefer the move that covers the deficit with least excess; otherwise
                # take the largest gain. Deterministic tie-breakers keep runs repeatable.
                covers = net_gain + 1e-9 >= (required - gained)
                score = (
                    0 if covers else 1,
                    abs(net_gain - (required - gained)) if covers else -net_gain,
                    float(add) * resources[in_c] - resources[out_c],
                    out_c,
                    in_c,
                )
                if best_move is None or score < best_move[0]:
                    best_move = (score, out_c, in_c, add, net_gain)
        if best_move is None:
            break
        _, out_c, in_c, add, net_gain = best_move
        repaired.x[(i, out_c)] = int(repaired.x.get((i, out_c), 0)) - 1
        repaired.x[(i, in_c)] = int(repaired.x.get((i, in_c), 0)) + int(add)
        gained += float(net_gain)
        actions.append(
            f"hex {i}: -1 {out_c}, +{add} {in_c} (net +{net_gain:.3f} kWh/slot)"
        )

    return repaired, gained, actions


def _repair_candidate_from_exact_slack(
    data: dict,
    candidate: InvestmentPoint,
    exact_model,
    passes: int,
    tolerance_kwh_annual: float,
) -> tuple[InvestmentPoint, float, list[str]]:
    """Build a better trial investment from exact recourse slack diagnostics.

    The maximum simultaneous slack at a cell is interpreted as a local capacity
    increment target.  This is particularly valuable for residual home demand,
    which cannot be spatially redirected.  The result is only a heuristic candidate
    and must be solved again by the exact annual MIP before it affects the LB.
    """
    repaired = _copy_investment(candidate)
    all_actions: list[str] = []

    def annual_slack(model) -> float:
        total = 0.0
        for i in model.I:
            for mon in model.M:
                nd = float(data["N_MONTH"][str(mon)])
                for t in model.H:
                    for b in model.B:
                        v = pyo.value(model.slack[i, mon, t, b], exception=False)
                        if v is not None and math.isfinite(float(v)) and float(v) > 0:
                            total += nd * float(v)
        return total

    current_annual = annual_slack(exact_model)
    if current_annual <= float(tolerance_kwh_annual) or int(passes) <= 0:
        return repaired, current_annual, all_actions

    # One exact solve supplies the slack pattern. Multiple repair passes allow
    # several site upgrades in one candidate, but do not pretend to re-optimize
    # operations between passes; exact recertification follows immediately.
    simultaneous: dict[int, float] = {}
    for i in exact_model.I:
        ii = int(i)
        max_slot = 0.0
        for mon in exact_model.M:
            for t in exact_model.H:
                slot = 0.0
                for b in exact_model.B:
                    v = pyo.value(exact_model.slack[i, mon, t, b], exception=False)
                    if v is not None and math.isfinite(float(v)) and float(v) > 1e-9:
                        slot += float(v)
                max_slot = max(max_slot, slot)
        if max_slot > 1e-9:
            simultaneous[ii] = max_slot

    for i, deficit in sorted(simultaneous.items(), key=lambda kv: (-kv[1], kv[0])):
        upgraded, gain, actions = _site_capacity_gain_repair(repaired, data, i, deficit)
        if gain > 1e-9:
            repaired = upgraded
            all_actions.extend(actions)

    return repaired, current_annual, all_actions


def _install_integer_only_master_start(master, inv: InvestmentPoint) -> None:
    """Install a partial MIP start containing only integer/binary master variables.

    Gurobi can complete a partial start.  Leaving continuous variables undefined is
    more robust than exporting a complete LP solution that can violate a newly added
    cut by a small numerical amount.
    """
    # Clear all continuous values so Pyomo omits them from the MIP start.
    for component in master.component_objects(pyo.Var, active=True):
        for var in component.values():
            try:
                if not var.is_integer():
                    var.set_value(None, skip_validation=True)
            except Exception:
                pass

    for i in master.I:
        ii = int(i)
        for c in master.C:
            cc = str(c)
            value = int(inv.x.get((ii, cc), 0))
            master.x[i, c].value = value
            for k in master._bits_x[(ii, cc)]:
                master.xbit[i, c, int(k)].value = 1 if ((value >> int(k)) & 1) else 0
        pv_value = int(inv.pv.get(ii, 0))
        batt_value = int(inv.batt.get(ii, 0))
        master.PV[i].value = pv_value
        master.Batt[i].value = batt_value
        for k in master._bits_pv[ii]:
            master.pvbit[i, int(k)].value = 1 if ((pv_value >> int(k)) & 1) else 0
        for k in master._bits_batt[ii]:
            master.battbit[i, int(k)].value = 1 if ((batt_value >> int(k)) & 1) else 0

    for (i, c, threshold), indicator in getattr(master, "_partial_threshold_cache", {}).items():
        value = 1 if int(inv.x.get((int(i), str(c)), 0)) >= int(threshold) + 1 else 0
        indicator.value = value

def _bootstrap_hall_repair(
    master,
    oracle,
    data: dict,
    candidate: InvestmentPoint,
    args,
) -> tuple[InvestmentPoint, float, int, int]:
    """Fast deterministic capacity repair for the rounded LP-bootstrap layout.

    Hall/min-cut certificates are valid recourse diagnostics but the full-data
    continuous master becomes expensive to re-solve after adding them.  Instead of
    spending hours on another LP before obtaining any exact certificate, add the
    valid Hall profit cuts to the master and *heuristically* repair the trial layout
    by adding resource-efficient chargers in certificate destination cells.

    The repair never removes or fixes a master-feasible solution and is never used
    as a bound.  It only generates a better integer trial point; the exact annual MIP
    remains responsible for certification.  Per-cell resource limits are preserved.
    """
    passes = max(0, int(args.bootstrap_hall_repair_passes or 0))
    if passes <= 0:
        screen = oracle.screen(
            candidate.x, source_iteration=0, certificate_kind="bootstrap_pre_exact"
        )
        added_cuts = int(_add_hall_cuts(master, data, screen))
        return candidate, float(screen.annual_unavoidable_slack_kwh), added_cuts, 0

    repaired = _copy_investment(candidate)
    resources = {str(c): float(data["charger_resources"][str(c)]) for c in data["PUB_TYPES"]}
    capacity = {str(c): float(data["charger_capacity_pub"][str(c)]) for c in data["PUB_TYPES"]}
    # Highest capacity per scarce resource first; deterministic tie-break by type name.
    type_order = sorted(
        (str(c) for c in data["PUB_TYPES"]),
        key=lambda c: (-capacity[c] / max(1e-12, resources[c]), c),
    )
    total_cuts = 0
    total_added_chargers = 0
    target = float(args.screen_skip_exact_slack_kwh)

    def used_resource(i: int) -> float:
        return sum(resources[c] * float(repaired.x.get((int(i), c), 0)) for c in type_order)

    def destination_capacity(nodes) -> float:
        return sum(
            capacity[c] * float(repaired.x.get((int(j), c), 0))
            for j in nodes for c in type_order
        )

    for pass_no in range(1, passes + 1):
        screen = oracle.screen(
            repaired.x,
            source_iteration=0,
            certificate_kind=f"bootstrap_hall_repair_{pass_no}",
        )
        total_cuts += int(_add_hall_cuts(master, data, screen))
        shortage_before = float(screen.annual_unavoidable_slack_kwh)
        if shortage_before <= target:
            print(
                f"Bootstrap Hall repair {pass_no - 1}: screen passed; unavoidable "
                f"slack {shortage_before:,.6f} kWh/year."
            )
            return repaired, shortage_before, total_cuts, total_added_chargers

        changed = 0
        # Larger deficiencies first. Earlier additions are accounted for explicitly
        # when each subsequent certificate is processed.
        certificates = sorted(
            screen.certificates,
            key=lambda cert: float(cert.unavoidable_slack_kwh_day),
            reverse=True,
        )
        for cert in certificates:
            nodes = tuple(int(j) for j in cert.destination_nodes)
            deficit = max(
                0.0,
                float(cert.origin_demand_kwh_day) - destination_capacity(nodes),
            )
            if deficit <= 1e-8:
                continue

            # Prefer cells with the most free resource.  Only additions are made;
            # no charger-type swaps are attempted in order to keep the heuristic
            # conservative and reproducible.
            for j in sorted(
                nodes,
                key=lambda jj: (-(float(data["cl"][int(jj)]) - used_resource(int(jj))), int(jj)),
            ):
                free = max(0.0, float(data["cl"][int(j)]) - used_resource(int(j)))
                if free <= 1e-9:
                    continue
                for c in type_order:
                    max_add = int(math.floor((free + 1e-9) / resources[c]))
                    if max_add <= 0:
                        continue
                    need = max(1, int(math.ceil(deficit / max(1e-12, capacity[c]) - 1e-12)))
                    add = min(max_add, need)
                    if add <= 0:
                        continue
                    repaired.x[(int(j), c)] = int(repaired.x.get((int(j), c), 0)) + int(add)
                    changed += int(add)
                    total_added_chargers += int(add)
                    deficit = max(0.0, deficit - float(add) * capacity[c])
                    free -= float(add) * resources[c]
                    if deficit <= 1e-8:
                        break
                if deficit <= 1e-8:
                    break

        # If pure additions cannot progress because sites have fractional/free
        # resource below one slow-charger unit, try a resource-neutral type swap.
        swap_actions = []
        if changed <= 0:
            for cert in certificates:
                nodes = tuple(int(j) for j in cert.destination_nodes)
                deficit = max(
                    0.0,
                    float(cert.origin_demand_kwh_day) - destination_capacity(nodes),
                )
                if deficit <= 1e-8:
                    continue
                for j in nodes:
                    upgraded, gain, actions = _site_capacity_gain_repair(repaired, data, int(j), deficit)
                    if gain > 1e-9:
                        repaired = upgraded
                        deficit = max(0.0, deficit - gain)
                        swap_actions.extend(actions)
                        if deficit <= 1e-8:
                            break
            if swap_actions:
                print(
                    f"Bootstrap Hall repair {pass_no}: add-only repair was blocked; "
                    f"performed {len(swap_actions)} resource-neutral/local capacity upgrades."
                )
                for action in swap_actions[:20]:
                    print(f"  {action}")
                changed = len(swap_actions)

        print(
            f"Bootstrap Hall repair {pass_no}: initial shortage "
            f"{shortage_before:,.3f} kWh/year; repair actions {changed}."
        )
        if changed <= 0:
            print(
                "Bootstrap Hall repair stopped because no resource-feasible addition or "
                "capacity-improving charger-type swap was available."
            )
            break

    final_screen = oracle.screen(
        repaired.x, source_iteration=0, certificate_kind="bootstrap_hall_repair_final"
    )
    total_cuts += int(_add_hall_cuts(master, data, final_screen))
    return (
        repaired,
        float(final_screen.annual_unavoidable_slack_kwh),
        int(total_cuts),
        int(total_added_chargers),
    )


def _save_bootstrap_checkpoint(
    path: Path,
    args,
    candidate: InvestmentPoint,
    upper_bound: float,
    master_eta: float,
) -> None:
    """Persist an explicitly reusable *development* warm start.

    The checkpoint is intentionally opt-in on reuse.  It stores only the trial
    investment vector and a previously proved valid upper bound; exact
    recourse solutions/cuts are not assumed.  This is useful while debugging the
    full instance and can be disabled for the eventual cold-start benchmark.
    """
    payload = {
        "dataset": str(args.dataset),
        "vipv_scenario": str(args.vipv_scenario),
        "problem_hash": args._problem_hash,
        "scenario": str(args.scenario),
        "disable_pv": bool(args.disable_pv),
        "disable_bess": bool(args.disable_bess),
        "upper_bound": float(upper_bound),
        "master_eta": float(master_eta) if math.isfinite(float(master_eta)) else None,
        "x": {f"{int(i)}|{str(c)}": int(v) for (i, c), v in candidate.x.items()},
        "pv": {str(int(i)): int(v) for i, v in candidate.pv.items()},
        "batt": {str(int(i)): int(v) for i, v in candidate.batt.items()},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _load_bootstrap_checkpoint(path: Path, args) -> tuple[InvestmentPoint, float, float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert_restart_identity(payload, args)
    expected = {
        "dataset": str(args.dataset),
        "vipv_scenario": str(args.vipv_scenario),
        "problem_hash": args._problem_hash,
        "scenario": str(args.scenario),
        "disable_pv": bool(args.disable_pv),
        "disable_bess": bool(args.disable_bess),
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise ValueError(
                f"Bootstrap checkpoint mismatch for {key}: file={payload.get(key)!r}, "
                f"current={value!r}."
            )
    upper = float(payload["upper_bound"])
    if not math.isfinite(upper):
        raise ValueError("Bootstrap checkpoint does not contain a finite upper bound.")
    x = {}
    for key, value in payload.get("x", {}).items():
        i, c = str(key).split("|", 1)
        x[(int(i), str(c))] = int(value)
    inv = InvestmentPoint(
        x=x,
        pv={int(i): int(v) for i, v in payload.get("pv", {}).items()},
        batt={int(i): int(v) for i, v in payload.get("batt", {}).items()},
    )
    eta = payload.get("master_eta")
    return inv, upper, (float(eta) if eta is not None else math.nan)


def _load_certified_run(run_path: Path, args) -> tuple[InvestmentPoint, float, float]:
    """Load a development warm start from a previously certified LBBD run.

    The previous global UB is reusable only for the same dataset/scenario/technology.
    The previous LB is informational: the investment is always re-certified by the
    exact annual MIP in the new process before it can become the new run's LB.
    """
    run_path = run_path.expanduser().resolve()
    meta_path = run_path / "run_metadata.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"Certified resume metadata not found: {meta_path}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert_restart_identity(meta, args)
    expected = {
        "dataset": str(args.dataset),
        "vipv_scenario": str(args.vipv_scenario),
        "problem_hash": args._problem_hash,
        "scenario": str(args.scenario),
    }
    for key, value in expected.items():
        if str(meta.get(key)) != str(value):
            raise ValueError(
                f"Certified resume mismatch for {key}: previous={meta.get(key)!r}, current={value!r}."
            )
    settings = dict(meta.get("effective_settings") or {})
    for key, value in {"disable_pv": bool(args.disable_pv), "disable_bess": bool(args.disable_bess)}.items():
        if key in settings and bool(settings.get(key)) != bool(value):
            raise ValueError(
                f"Certified resume mismatch for {key}: previous={settings.get(key)!r}, current={value!r}."
            )

    csv_path = run_path / "results" / "lbbd_best_infrastructure_by_hex.csv"
    if not csv_path.exists():
        csv_path = run_path / "results" / "infrastructure_by_hex.csv"
    if not csv_path.exists():
        raise FileNotFoundError(
            "Certified resume infrastructure not found. Expected "
            "results/lbbd_best_infrastructure_by_hex.csv or results/infrastructure_by_hex.csv."
        )
    df = pd.read_csv(csv_path)
    required = {"HexID", "slow_chargers", "medium_chargers", "fast_chargers", "PV_panels", "Battery_units"}
    missing = sorted(required.difference(df.columns))
    if missing:
        raise ValueError(f"Certified resume infrastructure is missing columns: {missing}")
    x, pv, batt = {}, {}, {}
    for row in df.itertuples(index=False):
        i = int(getattr(row, "HexID"))
        x[(i, "slow")] = int(round(float(getattr(row, "slow_chargers"))))
        x[(i, "medium")] = int(round(float(getattr(row, "medium_chargers"))))
        x[(i, "fast")] = int(round(float(getattr(row, "fast_chargers"))))
        pv[i] = int(round(float(getattr(row, "PV_panels"))))
        batt[i] = int(round(float(getattr(row, "Battery_units"))))
    ub = float(meta.get("global_ub_SEK", math.inf))
    old_lb = float(meta.get("best_lb_SEK", math.nan))
    if not math.isfinite(ub):
        raise ValueError("Previous certified run does not contain a finite global_ub_SEK.")
    return InvestmentPoint(x=x, pv=pv, batt=batt), ub, old_lb


def _load_development_investment_run(
    run_path: Path, args, data: dict
) -> tuple[InvestmentPoint, float, float]:
    """Load an investment-only development seed from a compatible completed run.

    This is intentionally weaker than ``_load_certified_run``: only the per-cell
    integer investment layout is reused.  The external objective and slack metrics
    are informational diagnostics and NEVER enter the LBBD bound calculation.  The
    loaded investment must be re-certified by the exact annual LBBD MIP before it
    can improve ``best_lb``.

    This allows, for example, a monolithic incumbent to be used to test whether the
    LBBD exact recourse formulation reproduces the same high-quality solution while
    preserving the integrity of the LBBD certificate.
    """
    run_path = run_path.expanduser().resolve()
    csv_path = run_path / "results" / "infrastructure_by_hex.csv"
    if not csv_path.exists():
        raise FileNotFoundError(
            f"Development investment file not found: {csv_path}"
        )
    df = pd.read_csv(csv_path)
    required = {
        "HexID", "slow_chargers", "medium_chargers", "fast_chargers",
        "PV_panels", "Battery_units",
    }
    missing = sorted(required.difference(df.columns))
    if missing:
        raise ValueError(
            "Development investment run is missing required columns in "
            f"results/infrastructure_by_hex.csv: {missing}"
        )

    expected_hex = {int(i) for i in data["hex_ids"]}
    supplied_hex = {int(v) for v in df["HexID"].tolist()}
    missing_hex = sorted(expected_hex.difference(supplied_hex))
    extra_hex = sorted(supplied_hex.difference(expected_hex))
    if missing_hex or extra_hex:
        raise ValueError(
            "Development investment HexID set does not match the current dataset. "
            f"Missing={missing_hex[:10]}{'...' if len(missing_hex) > 10 else ''}; "
            f"extra={extra_hex[:10]}{'...' if len(extra_hex) > 10 else ''}."
        )

    x, pv, batt = {}, {}, {}
    for row in df.itertuples(index=False):
        i = int(getattr(row, "HexID"))
        x[(i, "slow")] = int(round(float(getattr(row, "slow_chargers"))))
        x[(i, "medium")] = int(round(float(getattr(row, "medium_chargers"))))
        x[(i, "fast")] = int(round(float(getattr(row, "fast_chargers"))))
        pv[i] = int(round(float(getattr(row, "PV_panels"))))
        batt[i] = int(round(float(getattr(row, "Battery_units"))))

    reference_obj = math.nan
    reference_slack = math.nan
    summary_path = run_path / "results" / "model_summary.csv"
    if summary_path.exists():
        try:
            summary = pd.read_csv(summary_path)
            if {"Metric", "Value"}.issubset(summary.columns):
                values = dict(zip(summary["Metric"].astype(str), summary["Value"]))
                if "dataset" in values and str(values["dataset"]) != str(args.dataset):
                    raise ValueError(
                        "Development investment dataset mismatch: "
                        f"previous={values['dataset']!r}, current={args.dataset!r}."
                    )
                if "annual_profit_SEK" in values:
                    reference_obj = float(values["annual_profit_SEK"])
                if "annual_slack_kWh" in values:
                    reference_slack = float(values["annual_slack_kWh"])
                elif "slack_penalty_SEK" in values and float(values["slack_penalty_SEK"]) == 0.0:
                    reference_slack = 0.0
        except ValueError:
            raise
        except Exception as exc:
            print(
                "WARNING: Could not parse development run model_summary.csv for "
                f"reference diagnostics: {exc}"
            )

    return InvestmentPoint(x=x, pv=pv, batt=batt), reference_obj, reference_slack


def _save_certified_resume_checkpoint(
    run_dir: Path, args, inv: InvestmentPoint, certified_lb: float,
    fixed_ub: float, global_ub: float,
) -> Path:
    out = run_dir / "results" / "lbbd_certified_resume.json"
    payload = {
        "dataset": str(args.dataset),
        "vipv_scenario": str(args.vipv_scenario),
        "problem_hash": args._problem_hash,
        "scenario": str(args.scenario),
        "disable_pv": bool(args.disable_pv),
        "disable_bess": bool(args.disable_bess),
        "certified_lb_SEK": float(certified_lb),
        "fixed_investment_ub_SEK": float(fixed_ub),
        "global_ub_SEK": float(global_ub),
        "x": {f"{int(i)}|{str(c)}": int(v) for (i, c), v in inv.x.items()},
        "pv": {str(int(i)): int(v) for i, v in inv.pv.items()},
        "batt": {str(int(i)): int(v) for i, v in inv.batt.items()},
    }
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out


def _refine_bootstrap_with_hall_cuts(
    master,
    oracle,
    data: dict,
    candidate: InvestmentPoint,
    upper_bound: float,
    master_eta: float,
    args,
    run_dir: Path,
) -> tuple[InvestmentPoint, float, float, float, float, int]:
    """Absorb Hall/min-cut profit cuts before entering the integer master loop.

    The full-data LP bootstrap can round to an investment vector with a small
    reachability-capacity shortage.  These layouts are still feasible because the
    formulation contains penalized slack, but immediately handing the *pre-cut*
    completed point to the integer master creates a stale MIP start.  This routine
    adds the valid slack-preserving Hall profit cuts, re-solves the continuous
    master, re-rounds, and re-completes the candidate a few times first.

    The continuous-master objective remains a rigorous global upper bound.  The
    rounded point is only a trial configuration; exact annual MIP certification is
    still required for the lower bound.
    """
    rounds = max(0, int(args.bootstrap_hall_refinement_rounds or 0))
    if rounds <= 0:
        return candidate, float(upper_bound), float(master_eta), 0.0, 0.0, 0

    total_lp_seconds = 0.0
    total_completion_seconds = 0.0
    total_added = 0
    target = float(args.screen_skip_exact_slack_kwh)

    for refinement in range(1, rounds + 1):
        screen = oracle.screen(
            candidate.x,
            source_iteration=0,
            certificate_kind=f"bootstrap_refinement_{refinement}",
        )
        shortage = float(screen.annual_unavoidable_slack_kwh)
        if shortage <= target:
            print(
                f"Bootstrap Hall refinement {refinement - 1}: screen passed; "
                f"unavoidable slack {shortage:,.6f} kWh/year."
            )
            break

        added = int(_add_hall_cuts(master, data, screen))
        total_added += added
        print(
            f"Bootstrap Hall refinement {refinement}: unavoidable slack "
            f"{shortage:,.3f} kWh/year; added {added} new slack-preserving cuts."
        )
        if added <= 0:
            print(
                "Bootstrap Hall refinement stopped because the current screen "
                "produced no new separating cuts."
            )
            break

        refined_candidate, refined_upper, lp_seconds = _solve_master_lp_bootstrap(
            master,
            args,
            run_dir,
            log_name=f"lbbd_master_bootstrap_refine_{refinement:02d}.log",
        )
        total_lp_seconds += float(lp_seconds)
        if refined_candidate is None or not math.isfinite(float(refined_upper)):
            print(
                f"WARNING: Bootstrap Hall refinement {refinement} LP did not "
                "finish optimally. Retaining the last completed bootstrap point."
            )
            break

        candidate = refined_candidate
        upper_bound = min(float(upper_bound), float(refined_upper))
        completed, refined_eta, completion_seconds = _complete_master_start(
            master,
            candidate,
            args,
            run_dir,
            f"bootstrap_refine_{refinement:02d}",
        )
        total_completion_seconds += float(completion_seconds)
        master_eta = float(refined_eta) if completed else math.nan
        totals = _investment_totals(candidate)
        print(
            f"Bootstrap Hall refinement {refinement} candidate: UB "
            f"{upper_bound:,.3f} SEK/year; "
            f"slow={totals['slow']}, medium={totals['medium']}, "
            f"fast={totals['fast']}, PV={totals['PV']}, BESS={totals['BESS']}; "
            f"completion={'ok' if completed else 'not completed'}."
        )

    return (
        candidate,
        float(upper_bound),
        float(master_eta),
        float(total_lp_seconds),
        float(total_completion_seconds),
        int(total_added),
    )

def _resolve_adaptive_control_defaults(args) -> None:
    """Resolve adaptive LBBD controls even with an older run profile.

    The convergence-control patch introduced four profile keys.  Existing project
    folders may still contain a valid older ``run_profiles.json`` without those
    keys.  Keeping the fallback here makes the runner backward-compatible and
    prevents ``float(None)`` failures after a partial file replacement.
    """
    master_gap = float(args.master_gap)
    lbbd_gap = float(args.lbbd_gap)

    if args.master_gap_tight is None:
        # Tight enough to prove the requested outer gap, while avoiding an
        # unnecessarily tiny trial-master tolerance.
        args.master_gap_tight = min(master_gap, max(1.0e-6, 0.5 * lbbd_gap))
    if args.adaptive_master_gap_factor is None:
        args.adaptive_master_gap_factor = 0.25
    if args.stagnation_patience is None:
        args.stagnation_patience = 1
    if args.stagnation_max_rounds is None:
        args.stagnation_max_rounds = 4

    args.master_gap_tight = min(master_gap, max(1.0e-9, float(args.master_gap_tight)))
    args.adaptive_master_gap_factor = min(
        0.95, max(0.05, float(args.adaptive_master_gap_factor))
    )
    args.stagnation_patience = max(1, int(args.stagnation_patience))
    args.stagnation_max_rounds = max(1, int(args.stagnation_max_rounds))

def _run_spatial_case(root, run_dir, paths, data, cfg, args, monitor, phase_timing, total_started):
    phase_started = time.perf_counter()
    model, certificate, metadata = solve_spatial_exact(data, cfg, args, run_dir, args._solver_cfg)
    phase_timing["decomposition_solve_seconds"] = time.perf_counter() - phase_started
    metadata.update(method="LBBD", run_profile=args._run_profile, dataset=args.dataset,
                    vipv_scenario=args.vipv_scenario, problem_hash=args._problem_hash,
                    scenario=args.scenario, effective_settings={k:v for k,v in vars(args).items() if not k.startswith("_")},
                    linked_annual_bess=cfg.get("bess_boundary") == "legacy_linked_months",
                    cyclic_day_bess=cfg.get("bess_boundary") == "cyclic_day",
                    notes="The LBBD entry point solves independent exact annual site MILPs without redirection. No Benders iterations are performed.")
    (run_dir / "run_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    (run_dir / "results" / "solver_certificate.json").write_text(json.dumps(certificate, indent=2), encoding="utf-8")
    print(f"Aggregate certificate: {certificate}")
    stats = {"assembled_export_model": model_statistics(model)} if model is not None else {}
    if model is not None:
        phase_started = time.perf_counter()
        export_all(model, data, cfg, run_dir)
        phase_timing["export_seconds"] = time.perf_counter() - phase_started
    phase_timing["total_runtime_seconds"] = time.perf_counter() - total_started
    write_run_complexity(run_dir, "LBBD", data, phase_timing=phase_timing,
                         model_stats=stats, resource_monitor=monitor)
    if model is not None and not args.skip_figures:
        phase_started = time.perf_counter()
        try:
            generate_run_figures(run_dir=run_dir, project_root=root, dataset=args.dataset,
                                 parking_shapefile=paths.get("parking_shapefile"),
                                 dpi=max(100, int(args.figures_dpi)))
        except Exception as exc:
            print(f"WARNING: Figure generation failed without invalidating the solution: {exc}")
        phase_timing["figure_generation_seconds"] = time.perf_counter() - phase_started
    monitor.stop()
    phase_timing["total_runtime_seconds"] = time.perf_counter() - total_started
    write_run_complexity(run_dir, "LBBD", data, phase_timing=phase_timing,
                         model_stats=stats, resource_monitor=monitor)
    print(f"Run directory: {run_dir}")
    return (0 if metadata["termination"] == "certified_gap" else 3) if model is not None else 2


def main() -> int:
    total_started = time.perf_counter()
    monitor = ResourceMonitor().start()
    phase_timing: dict[str, float] = {}
    args = parse_args()
    root = Path(args.project_root).resolve()
    resolve_input_selection(args, root)
    paths, cfg, solver_cfg = _load_configs(root, args.dataset, args.vipv_scenario)
    run_profile = load_run_profile(root, "lbbd", args.dataset)
    apply_profile_defaults(args, run_profile)
    args._run_profile = f"lbbd.{args.dataset}"
    if args.mip_gap is not None:
        args.subproblem_gap = float(args.mip_gap)
        args.lbbd_gap = float(args.mip_gap)
        args.logic_mip_gap = min(float(args.logic_mip_gap), float(args.mip_gap))
    _resolve_adaptive_control_defaults(args)
    args.solver = str(args.solver or solver_cfg.get("solver", "gurobi"))
    # Solver-control fields that are intentionally kept in run_profiles.json
    # rather than exposed as standard command-line arguments.  Without this
    # merge, the full LBBD profile's root_method/node_method/pre_sparsify values
    # are silently ignored and Gurobi may use the memory-intensive concurrent
    # barrier root algorithm.
    solver_profile_keys = {
        "root_method", "node_method", "heuristics", "cuts", "numeric_focus",
        "pre_sparsify", "aggregate", "agg_fill", "sub_mip_nodes", "pump_passes",
        "improve_start_gap", "improve_start_time", "integrality_focus",
        "start_time_limit", "start_work_limit", "start_node_limit",
        "master_norel_heur_time", "master_norel_heur_work", "mip_focus",
    }
    merged_solver_cfg = dict(solver_cfg)
    for key in solver_profile_keys:
        if key in run_profile:
            merged_solver_cfg[key] = run_profile[key]
    # --bound-polish is intentionally applied per master solve rather than here.
    # A cold run first needs good incumbents; best-bound focus is activated only
    # after the certified outer gap falls below --bound-polish-trigger-gap.
    args._solver_cfg = merged_solver_cfg
    check_input_paths(paths)
    runs_root = Path(paths["runs_root"])
    ensure_dir(runs_root)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    technology = ("noPV" if args.disable_pv else "withPV") + "_" + ("noBESS" if args.disable_bess else "withBESS")
    run_name = args.run_name or f"{timestamp}_{args.dataset}_{args.vipv_scenario}_{args.scenario}_LBBD_{technology}"
    run_dir = runs_root / run_name
    if run_dir.exists():
        raise FileExistsError(f"Run directory already exists: {run_dir}")
    for sub in ["logs", "results", "model", "nodefiles"]:
        ensure_dir(run_dir / sub)

    transcript = (run_dir / "README_RUN.txt").open("w", encoding="utf-8")
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout = TeeStream(old_stdout, transcript)
    sys.stderr = TeeStream(old_stderr, transcript)
    try:
        print("LBBD optimization")
        print("=================")
        print(f"Project root: {root}")
        print(f"Dataset: {args.dataset}")
        print(f"Run profile: {args._run_profile}")
        print(f"Scenario: {args.scenario}")
        print(f"Technology: {technology}")
        print("Method: embedded continuous recourse relaxation with LP cuts and exact annual MIP certification")
        print(f"Run directory: {run_dir}")
        root_method = str(args._solver_cfg.get("root_method", "auto"))
        node_method = str(args._solver_cfg.get("node_method", "auto"))
        print(
            "Master solver memory mode: "
            f"threads={int(args.threads)}, root_method={root_method}, node_method={node_method}, "
            f"nodefile_start={float(args.nodefile_start):.3g} GB, "
            f"soft_mem_limit={args.soft_mem_limit_gb if args.soft_mem_limit_gb is not None else 'none'} GB"
        )

        phase_started = time.perf_counter()
        raw = load_inputs(paths)
        phase_timing["input_load_seconds"] = time.perf_counter() - phase_started
        phase_started = time.perf_counter()
        data = preprocess(raw, cfg)
        phase_timing["preprocessing_seconds"] = time.perf_counter() - phase_started
        data["dataset"] = args.dataset
        data["vipv_scenario"] = args.vipv_scenario
        record_run_context(root, run_dir, data, cfg, args, "LBBD")
        data["disable_pv"] = bool(args.disable_pv)
        data["disable_bess"] = bool(args.disable_bess)
        if args.scenario == "no_redirection":
            data["allowed"] = []
            data["T_dict"] = {}
            data["allowed_st"] = []
            data["OUT"] = {}
            data["IN"] = {}
            data["ORIGIN_ST"] = []
            data["DEST_ST"] = []
        print(f"Hex cells: {len(data['hex_ids'])}")
        print(f"Active redirection arc-slots: {len(data['allowed_st']):,}")

        if args.scenario == "no_redirection" and args.no_redirection_mode != "master":
            if any(getattr(args, key, None) for key in ("bootstrap_checkpoint", "resume_certified_run", "development_investment_run")):
                raise ValueError("LBBD checkpoint options require --no-redirection-mode master; spatial mode solves independent annual MILPs.")
            return _run_spatial_case(root, run_dir, paths, data, cfg, args, monitor,
                                     phase_timing, total_started)
        if args.regularize_infrastructure or args.hard_no_slack:
            raise ValueError("--regularize-infrastructure and --hard-no-slack require the no-redirection spatial mode.")

        phase_started = time.perf_counter()
        components = build_slot_components(data)
        global_components = build_global_components(data)
        oracle = FeasibilityNetworkOracle(data, components)
        phase_timing["component_preparation_seconds"] = time.perf_counter() - phase_started
        phase_started = time.perf_counter()
        master = build_lbbd_master(data, cfg, components, global_components)
        phase_timing["master_build_seconds"] = time.perf_counter() - phase_started
        initial_master_stats = model_statistics(master)
        static_origin_added = 0
        if not args.skip_static_origin_cuts:
            static_origin_added = add_static_origin_profit_cuts(master, data)
        master_vars, master_cons = _model_counts(master)
        print(f"Slot components: {len(components['keys']):,}")
        print(f"Global redirection components: {len(global_components['ids']):,}")
        print(f"Static origin-neighbourhood profit cuts: {static_origin_added:,}")
        print(f"Initial master size: {master_vars:,} variables; {master_cons:,} constraints")
        print(
            "Adaptive master-gap control: "
            f"initial {100.0 * float(args.master_gap):.6f}% -> "
            f"tight {100.0 * float(args.master_gap_tight):.6f}%"
        )
        first_master_solution_limit = max(
            0, int(args.first_master_solution_limit or 0)
        )
        lp_bootstrap_enabled = bool(args.first_master_lp_bootstrap)
        master_mip_start_enabled = (
            not bool(args.no_master_mip_start)
            and not lp_bootstrap_enabled
            and first_master_solution_limit <= 0
        )
        if lp_bootstrap_enabled:
            print(
                "First-master LP bootstrap enabled: solve the continuous master relaxation, "
                "round investments resource-feasibly, complete them with a fixed-investment LP, "
                "then start LBBD cut generation without waiting for a cold master MIP incumbent."
            )
        elif first_master_solution_limit > 0:
            print(
                "First-master feasibility bootstrap: "
                f"SolutionLimit={first_master_solution_limit}, "
                f"Heuristics={float(args.first_master_heuristics) if args.first_master_heuristics is not None else 'profile/default'}, "
                f"NoRel={float(args.master_heuristic_time) if args.master_heuristic_time is not None else float(args._solver_cfg.get('master_norel_heur_time', 0.0) or 0.0):g}s."
            )
        if master_mip_start_enabled:
            phase_started = time.perf_counter()
            start_eta = _initialize_master_slack_start(master, data, cfg)
            phase_timing["master_mip_start_seconds"] = time.perf_counter() - phase_started
            print(
                "Internal master MIP start: slack-only feasible point "
                f"loaded (Eta {start_eta:,.3f}; "
                f"setup {phase_timing['master_mip_start_seconds']:.1f}s)."
            )
        else:
            phase_timing["master_mip_start_seconds"] = 0.0
            if not lp_bootstrap_enabled and first_master_solution_limit <= 0:
                print("Internal master MIP start disabled by command.")

        zero = InvestmentPoint(
            x={(int(i), str(c)): 0 for i in data["hex_ids"] for c in data["PUB_TYPES"]},
            pv={int(i): 0 for i in data["hex_ids"]},
            batt={int(i): 0 for i in data["hex_ids"]},
        )
        root_hall_added = 0
        if not args.skip_root_hall:
            root_screen = oracle.screen(zero.x, source_iteration=0, certificate_kind="root_zero_capacity")
            root_hall_added = _add_hall_cuts(master, data, root_screen)
            print(
                f"Root Hall profit cuts: {root_hall_added:,}; zero-layout unavoidable slack "
                f"{root_screen.annual_unavoidable_slack_kwh:,.3f} kWh/year"
            )

        phase_started = time.perf_counter()
        monthly_lp_models = {}
        if not args.skip_component_lp:
            monthly_lp_models = {
                str(month): build_monthly_recourse_model(data, cfg, str(month), exact_mip=False)
                for month in data["MONTHS"]
            }
        monthly_mip_models = {}
        if not args.skip_logic_mip and int(args.logic_mip_frequency) > 0:
            monthly_mip_models = {
                str(month): build_monthly_recourse_model(data, cfg, str(month), exact_mip=True)
                for month in data["MONTHS"]
            }

        phase_timing["oracle_model_build_seconds"] = time.perf_counter() - phase_started

        bootstrap_candidate = None
        bootstrap_upper_bound = math.inf
        bootstrap_master_eta = math.nan
        bootstrap_pending = False
        development_reference_objective = math.nan
        development_reference_slack = math.nan
        development_investment_source = None
        development_investment_signature = None
        phase_timing["first_master_lp_bootstrap_seconds"] = 0.0
        phase_timing["master_start_completion_seconds"] = 0.0
        if lp_bootstrap_enabled:
            resume_run_path = (
                Path(args.resume_certified_run).expanduser().resolve()
                if args.resume_certified_run
                else None
            )
            checkpoint_path = (
                Path(args.bootstrap_checkpoint).expanduser().resolve()
                if args.bootstrap_checkpoint
                else None
            )
            development_run_path = (
                Path(args.development_investment_run).expanduser().resolve()
                if args.development_investment_run
                else None
            )
            if resume_run_path is not None:
                print(f"Loading certified development resume run: {resume_run_path}")
                bootstrap_candidate, previous_upper_bound, previous_certified_lb = _load_certified_run(
                    resume_run_path, args
                )
                bootstrap_master_eta = math.nan
                _, bootstrap_upper_bound, bootstrap_lp_seconds = _solve_master_lp_bootstrap(
                    master, args, run_dir, log_name="lbbd_master_resume_bound_lp.log"
                )
                print(
                    f"Previous UB {previous_upper_bound:,.3f} and LB {previous_certified_lb:,.3f} "
                    "are informational; the current master LP reproves the UB and the annual MIP re-certifies the investment."
                )
            elif checkpoint_path is not None:
                print(f"Loading development bootstrap checkpoint: {checkpoint_path}")
                bootstrap_candidate, previous_upper_bound, _ = _load_bootstrap_checkpoint(
                    checkpoint_path, args
                )
                _, bootstrap_upper_bound, bootstrap_lp_seconds = _solve_master_lp_bootstrap(
                    master, args, run_dir, log_name="lbbd_master_checkpoint_bound_lp.log"
                )
                bootstrap_master_eta = math.nan
                print(
                    f"Previous checkpoint UB {previous_upper_bound:,.3f} is informational; "
                    "the current master LP reproves the UB before the candidate is used."
                )
            else:
                print("Solving continuous initial-master relaxation for the full-data bootstrap...")
                bootstrap_candidate, bootstrap_upper_bound, bootstrap_lp_seconds = _solve_master_lp_bootstrap(
                    master, args, run_dir, log_name="lbbd_master_bootstrap_lp.log"
                )
            phase_timing["first_master_lp_bootstrap_seconds"] = float(bootstrap_lp_seconds)

            # Development-only candidate override: retain the valid LBBD upper
            # bound obtained above, but test a stronger investment layout from a
            # compatible completed run (for example the monolithic benchmark).
            # Only the investment vector is imported; its objective is diagnostic
            # and is never accepted as an LB without exact annual LBBD certification.
            if development_run_path is not None:
                (
                    development_candidate,
                    development_reference_objective,
                    development_reference_slack,
                ) = _load_development_investment_run(
                    development_run_path, args, data
                )
                bootstrap_candidate = development_candidate
                bootstrap_master_eta = math.nan
                development_investment_source = str(development_run_path)
                development_investment_signature = _investment_signature(bootstrap_candidate)
                dev_totals = _investment_totals(bootstrap_candidate)
                ref_obj_text = (
                    f"{development_reference_objective:,.3f} SEK/year"
                    if math.isfinite(development_reference_objective)
                    else "not available"
                )
                ref_slack_text = (
                    f"{development_reference_slack:,.6f} kWh/year"
                    if math.isfinite(development_reference_slack)
                    else "not available"
                )
                print(
                    "Development investment override loaded. Only the investment "
                    "layout is reused; LBBD will exact-certify it before it can "
                    "improve the lower bound."
                )
                print(
                    f"  Source: {development_run_path}\n"
                    f"  Reference objective (informational only): {ref_obj_text}\n"
                    f"  Reference slack (informational only): {ref_slack_text}\n"
                    f"  Totals: slow={dev_totals['slow']}, medium={dev_totals['medium']}, "
                    f"fast={dev_totals['fast']}, PV={dev_totals['PV']}, BESS={dev_totals['BESS']}"
                )

            if bootstrap_candidate is None or not math.isfinite(float(bootstrap_upper_bound)):
                print(
                    "WARNING: Initial-master LP bootstrap did not finish optimally; "
                    "falling back to the configured first master MIP."
                )
            else:
                totals_bootstrap = _investment_totals(bootstrap_candidate)
                print(
                    "LP bootstrap upper bound: "
                    f"{bootstrap_upper_bound:,.3f} SEK/year; rounded investments "
                    f"slow={totals_bootstrap['slow']}, medium={totals_bootstrap['medium']}, "
                    f"fast={totals_bootstrap['fast']}, PV={totals_bootstrap['PV']}, "
                    f"BESS={totals_bootstrap['BESS']}."
                )

                # For the production-size instance, do not spend another multi-hour
                # continuous solve merely to absorb Hall cuts. Add the valid cuts and
                # repair the trial layout directly within existing resource limits.
                bootstrap_candidate, repaired_slack, repair_hall_added, repair_chargers = _bootstrap_hall_repair(
                    master, oracle, data, bootstrap_candidate, args
                )
                phase_timing["bootstrap_hall_cuts_added"] = int(repair_hall_added)
                print(
                    f"Bootstrap Hall repair result: unavoidable slack {repaired_slack:,.3f} "
                    f"kWh/year; added {repair_chargers} trial chargers; "
                    f"Hall cuts in master={repair_hall_added}."
                )

                completed, bootstrap_master_eta, completion_seconds = _complete_master_start(
                    master, bootstrap_candidate, args, run_dir, "bootstrap_001"
                )
                phase_timing["master_start_completion_seconds"] += float(completion_seconds)
                bootstrap_pending = True
                if completed:
                    print(
                        "Bootstrap investment point completed to a feasible integer-master "
                        f"solution (Eta {bootstrap_master_eta:,.3f} SEK/year). "
                        "LBBD iteration 1 will evaluate this point directly."
                    )
                else:
                    bootstrap_master_eta = math.nan
                    print(
                        "WARNING: Rounded/repaired bootstrap investments could not be completed by the "
                        "fixed-investment master LP. LBBD iteration 1 will still evaluate the "
                        "resource-feasible investment point with the exact annual oracle."
                    )

                # Persist an opt-in development warm start immediately.  This makes
                # later debugging retries independent of whether the exact oracle or a
                # subsequent master is interrupted.
                bootstrap_checkpoint_out = run_dir / "results" / "lbbd_bootstrap_checkpoint.json"
                _save_bootstrap_checkpoint(
                    bootstrap_checkpoint_out, args, bootstrap_candidate,
                    bootstrap_upper_bound, bootstrap_master_eta,
                )
                _write_investment_csv(
                    run_dir / "results" / "lbbd_bootstrap_investment.csv", data, bootstrap_candidate
                )
                print(f"Bootstrap checkpoint saved: {bootstrap_checkpoint_out}")

                # Legacy optional LP refinement remains available for experiments,
                # but it is deliberately off in the calibrated full profile.
                if int(args.bootstrap_hall_refinement_rounds or 0) > 0:
                    print(
                        "Optional LP Hall refinement requested after the fast repair..."
                    )
                    (
                        bootstrap_candidate, bootstrap_upper_bound, bootstrap_master_eta,
                        refinement_lp_seconds, refinement_completion_seconds, refinement_hall_added,
                    ) = _refine_bootstrap_with_hall_cuts(
                        master, oracle, data, bootstrap_candidate, bootstrap_upper_bound,
                        bootstrap_master_eta, args, run_dir,
                    )
                    phase_timing["first_master_lp_bootstrap_seconds"] += float(refinement_lp_seconds)
                    phase_timing["master_start_completion_seconds"] += float(refinement_completion_seconds)
                    phase_timing["bootstrap_hall_cuts_added"] = int(
                        phase_timing.get("bootstrap_hall_cuts_added", 0)
                    ) + int(refinement_hall_added)
                    bootstrap_pending = bootstrap_candidate is not None

        if args.write_lp:
            master.write(str(run_dir / "model" / "lbbd_master_initial.lp"), io_options={"symbolic_solver_labels": True})

        history: list[dict] = []
        best_lb = -math.inf
        best_model = None
        best_inv = None
        best_fixed_ub = math.inf
        best_global_ub = float(bootstrap_upper_bound) if bootstrap_pending else math.inf
        annual_core_point = None
        exact_cache: dict[tuple, dict[str, float]] = {}
        previous_signature = None
        repeat_count = 0
        tight_stagnation_rounds = 0
        active_master_gap = float(args.master_gap)
        initial_master_gap = float(args.master_gap)
        tight_master_gap = min(float(args.master_gap), float(args.master_gap_tight))
        adaptive_factor = min(0.95, max(0.05, float(args.adaptive_master_gap_factor)))
        last_global_gap = math.inf
        start = time.time()
        termination = "max_iterations"

        for iteration in range(1, int(args.max_iterations) + 1):
            elapsed_before = time.time() - start
            remaining = float(args.time_limit) - elapsed_before
            if remaining <= float(args.finalization_reserve):
                termination = "time_limit"
                break

            # A trial master gap larger than the remaining LBBD gap can legally return
            # the same incumbent forever. Tighten the master progressively whenever the
            # certificate is already inside the current master tolerance or candidates repeat.
            near_certificate = math.isfinite(last_global_gap) and last_global_gap <= max(
                active_master_gap, 5.0 * float(args.lbbd_gap)
            )
            repeat_pressure = repeat_count >= max(1, int(args.stagnation_patience))
            if near_certificate or repeat_pressure:
                certificate_target = (
                    max(tight_master_gap, 0.5 * last_global_gap)
                    if math.isfinite(last_global_gap)
                    else active_master_gap * adaptive_factor
                )
                active_master_gap = max(
                    tight_master_gap,
                    min(active_master_gap * adaptive_factor, certificate_target),
                )
            force_full_master_time = active_master_gap < initial_master_gap - 1e-15 or repeat_pressure

            if iteration == 1 and bootstrap_pending:
                master_results = None
                master_limit_used = int(args.first_master_lp_time_limit)
                master_focus_used = -1
                master_solve_seconds = float(phase_timing.get("first_master_lp_bootstrap_seconds", 0.0)) + float(
                    phase_timing.get("master_start_completion_seconds", 0.0)
                )
                candidate = bootstrap_candidate
                master_eta = float(bootstrap_master_eta)
                current_bound = float(bootstrap_upper_bound)
                master_term = "lp_bootstrap_candidate"
                # This is not a MIP primal/dual gap: it compares the continuous-master
                # bound with the completed rounded bootstrap candidate. Keep it as a
                # candidate-to-bound diagnostic and leave the achieved MIP gap undefined.
                master_internal_gap = math.nan
                master_candidate_bound_gap = _rel_gap(current_bound, master_eta)
                candidate_source = "lp_bootstrap"
                completion_text = (
                    "completed fixed-investment master point"
                    if math.isfinite(master_eta)
                    else "resource-feasible rounded LP point"
                )
                print(
                    f"Iteration {iteration:02d} uses the {completion_text}; "
                    f"valid continuous-master UB {current_bound:,.3f} SEK/year."
                )
                bootstrap_pending = False
            else:
                # Per-iteration diagnostic state. ``master_internal_gap`` is reserved
                # for a genuine Gurobi MIP incumbent-vs-bound gap from the same solve.
                # Bootstrap/fallback candidate-to-bound differences are tracked
                # separately so they cannot be misread as master optimality gaps.
                master_internal_gap = math.nan
                master_candidate_bound_gap = math.nan
                candidate_source = "master_mip_incumbent"
                refreshed_start = False
                if best_inv is not None and bool(args.integer_only_master_start):
                    _install_integer_only_master_start(master, best_inv)
                    refreshed_start = True
                    print(
                        f"Installed integer-only partial master start for iteration {iteration:02d} "
                        "from the best certified investment; continuous values are left for Gurobi to complete."
                    )
                elif bool(args.refresh_master_start) and best_inv is not None:
                    print(
                        f"Refreshing a feasible master start for iteration {iteration:02d} "
                        "with the best certified investments fixed..."
                    )
                    refreshed_start, refreshed_eta, refresh_seconds = _complete_master_start(
                        master, best_inv, args, run_dir, f"refresh_{iteration:03d}"
                    )
                    phase_timing["master_start_completion_seconds"] += float(refresh_seconds)
                    if refreshed_start:
                        print(f"Refreshed master start Eta: {refreshed_eta:,.3f} SEK/year.")
                    else:
                        print(
                            "WARNING: Fixed-investment start refresh did not solve optimally; "
                            "continuing with the standard master solve."
                        )

                master_results, master_limit_used, master_focus_used, master_solve_seconds = _solve_master(
                    master, args, run_dir, iteration, remaining,
                    requested_gap=active_master_gap,
                    force_full_time=force_full_master_time,
                    use_mip_start=(
                        (iteration == 1 and master_mip_start_enabled)
                        or refreshed_start
                    ),
                    certified_lb=best_lb,
                    global_upper_bound=best_global_ub,
                )
                eta_value = pyo.value(master.Eta, exception=False)
                has_result_solution = bool(getattr(master, "_last_solve_loaded_incumbent", False))
                if (not has_result_solution) or eta_value is None or not math.isfinite(float(eta_value)):
                    bound_without_incumbent = _master_bound(master_results, master)
                    if math.isfinite(bound_without_incumbent):
                        best_global_ub = min(best_global_ub, float(bound_without_incumbent))
                        print(
                            f"Master iteration {iteration} returned no incumbent but retained "
                            f"a valid best bound {bound_without_incumbent:,.3f} SEK/year."
                        )

                    fallback_used = False

                    # If the new master bound already closes the certified outer gap,
                    # no fallback candidate or additional exact solve is required.  Use
                    # the existing best certified infrastructure only as the history
                    # anchor for this bound-only convergence iteration.  This avoids
                    # wasting hours on a poor fallback candidate after convergence has
                    # already been proved by the master bound.
                    if (
                        math.isfinite(best_lb)
                        and best_model is not None
                        and best_inv is not None
                        and math.isfinite(best_global_ub)
                    ):
                        gap_from_bound = _rel_gap(max(best_lb, best_global_ub), best_lb)
                        if gap_from_bound <= float(args.lbbd_gap):
                            candidate = best_inv
                            master_eta = math.nan
                            current_bound = float(bound_without_incumbent) if math.isfinite(bound_without_incumbent) else float(best_global_ub)
                            master_term = "mip_bound_only_certified"
                            master_internal_gap = math.nan
                            master_candidate_bound_gap = math.nan
                            candidate_source = "best_certified_incumbent_bound_only"
                            fallback_used = True
                            print(
                                f"Master bound alone certifies convergence at iteration {iteration}: "
                                f"global gap {100.0 * gap_from_bound:.6f}% <= target "
                                f"{100.0 * float(args.lbbd_gap):.6f}%. Skipping LP fallback."
                            )

                    if (not fallback_used) and bool(args.lp_fallback_on_master_no_incumbent):
                        print(
                            f"Using continuous-master fallback at iteration {iteration} to "
                            "generate another exact-certification candidate instead of aborting."
                        )
                        fallback_candidate, fallback_lp_ub, fallback_lp_seconds = _solve_master_lp_bootstrap(
                            master, args, run_dir,
                            log_name=f"lbbd_master_lp_fallback_{iteration:03d}.log",
                        )
                        phase_timing["first_master_lp_bootstrap_seconds"] += float(fallback_lp_seconds)
                        if fallback_candidate is not None and math.isfinite(float(fallback_lp_ub)):
                            fallback_completed, fallback_eta, fallback_completion_seconds = _complete_master_start(
                                master, fallback_candidate, args, run_dir,
                                f"fallback_{iteration:03d}",
                            )
                            phase_timing["master_start_completion_seconds"] += float(fallback_completion_seconds)
                            candidate = fallback_candidate
                            master_eta = float(fallback_eta) if fallback_completed else math.nan
                            current_bound = min(
                                float(v) for v in (bound_without_incumbent, fallback_lp_ub)
                                if math.isfinite(float(v))
                            ) if any(
                                math.isfinite(float(v)) for v in (bound_without_incumbent, fallback_lp_ub)
                            ) else math.inf
                            master_term = "mip_no_incumbent_lp_fallback"
                            master_internal_gap = math.nan
                            master_candidate_bound_gap = (
                                _rel_gap(fallback_lp_ub, master_eta)
                                if math.isfinite(float(fallback_lp_ub)) and math.isfinite(float(master_eta))
                                else math.nan
                            )
                            candidate_source = "lp_fallback"
                            fallback_used = True
                            totals_fallback = _investment_totals(candidate)
                            print(
                                f"LP fallback candidate ready: UB {current_bound:,.3f}; "
                                f"slow={totals_fallback['slow']} medium={totals_fallback['medium']} "
                                f"fast={totals_fallback['fast']} PV={totals_fallback['PV']} "
                                f"BESS={totals_fallback['BESS']}; "
                                f"completion={'ok' if fallback_completed else 'not completed'}."
                            )

                    if not fallback_used:
                        if math.isfinite(best_lb) and best_model is not None:
                            gap_without_incumbent = _rel_gap(
                                max(best_lb, best_global_ub), best_lb
                            )
                            termination = (
                                "certified_gap_master_bound_only"
                                if gap_without_incumbent <= float(args.lbbd_gap)
                                else "master_no_incumbent"
                            )
                            print(
                                f"Master returned no new incumbent at iteration {iteration}: "
                                f"termination={_solver_term(master_results)}. Certified incumbent "
                                f"retained; current global gap {100.0 * gap_without_incumbent:.6f}%."
                            )
                            break
                        raise RuntimeError(
                            f"Master returned no usable incumbent at iteration {iteration}: "
                            f"termination={_solver_term(master_results)}. "
                            "Enable the LP bootstrap/fallback or increase the master limit."
                        )
                else:
                    candidate = extract_investment(master)
                    master_eta = float(pyo.value(master.Eta))
                    current_bound = _master_bound(master_results, master)
                    master_term = _solver_term(master_results)
                    # Gurobi MIPGap uses the incumbent denominator; the outer
                    # LBBD gap intentionally uses the global UB denominator.
                    master_internal_gap = (
                        max(0.0, current_bound - master_eta) / max(1.0, abs(master_eta))
                        if math.isfinite(current_bound) else math.nan
                    )
                    master_candidate_bound_gap = _rel_gap(current_bound, master_eta)
                    candidate_source = "master_mip_incumbent"

                # Candidate is supplied by the bootstrap, a genuine master-MIP
                # incumbent, a fallback LP, or (when the bound itself proves the outer
                # target) the already certified best incumbent.

            signature = _investment_signature(candidate)
            signature_label = _signature_label(signature)
            if signature == previous_signature:
                repeat_count += 1
            else:
                repeat_count = 0
            previous_signature = signature
            candidate_cached = signature in exact_cache
            totals = _investment_totals(candidate)
            if math.isfinite(current_bound):
                best_global_ub = min(best_global_ub, current_bound)

            screen = oracle.screen(candidate.x, source_iteration=iteration, certificate_kind="dynamic_min_cut")
            hall_added = _add_hall_cuts(master, data, screen)

            component_lp_added = 0
            component_lp_violated = 0
            max_component_lp_violation = 0.0
            lp_results = {}
            # Exact repetition of an investment vector cannot reveal a new component
            # recourse function value. Avoid rebuilding the same 12 monthly LP evaluations.
            if not args.skip_component_lp and not candidate_cached:
                lp_results, component_lp_added, component_lp_violated, max_component_lp_violation = _solve_component_lps(
                    monthly_lp_models, master, data, components, candidate, args, run_dir, iteration
                )

            annual_lp_added = 0
            annual_lp_obj = math.nan
            annual_lp_violation = 0.0
            annual_core_cut_added = 0
            annual_core_lp_obj = math.nan
            annual_core_violation = 0.0
            exact_config_added = 0
            logic_added = 0
            logic_violated = 0
            exact_obj = math.nan
            exact_ub = math.nan
            exact_gap = math.nan
            status = "screen_shortage"

            screen_shortage = float(screen.annual_unavoidable_slack_kwh)
            fallback_frequency = max(0, int(args.exact_fallback_frequency))
            forced_exact = fallback_frequency > 0 and iteration % fallback_frequency == 0
            no_new_separation = (hall_added + component_lp_added) == 0
            bootstrap_needs_first_certificate = (
                iteration == 1
                and master_term == "lp_bootstrap_candidate"
                and not math.isfinite(best_lb)
            )
            lp_fallback_needs_certificate = master_term == "mip_no_incumbent_lp_fallback"
            should_evaluate_exact = (
                screen_shortage <= float(args.screen_skip_exact_slack_kwh)
                or forced_exact
                or no_new_separation
                or bootstrap_needs_first_certificate
                or lp_fallback_needs_certificate
            )
            if should_evaluate_exact:
                status = "evaluated_cached" if candidate_cached else (
                    "evaluated" if screen_shortage <= float(args.screen_skip_exact_slack_kwh)
                    else "evaluated_with_screen_shortage"
                )
                if not candidate_cached:
                    if (
                        not args.skip_annual_lp
                        and int(args.annual_lp_frequency) > 0
                        and iteration % int(args.annual_lp_frequency) == 0
                    ):
                        _, _, annual_cut, annual_lp_obj = _solve_fixed_annual_lp_cut(
                            data, cfg, args, run_dir, candidate, iteration,
                            probe_name="candidate", cut_id=iteration * 10,
                        )
                        if (
                            annual_cut is not None
                            and math.isfinite(annual_lp_obj)
                            and math.isfinite(float(master_eta))
                        ):
                            annual_lp_violation = float(master_eta) - float(annual_lp_obj)
                            annual_threshold = max(
                                float(args.lp_cut_abs_tol),
                                float(args.lp_cut_rel_tol) * max(1.0, abs(float(annual_lp_obj))),
                            )
                            if annual_lp_violation > annual_threshold:
                                annual_lp_added = int(add_annual_lp_cut(master, annual_cut))

                        previous_core = annual_core_point
                        annual_core_point = _blend_investments(
                            annual_core_point, candidate, float(args.core_point_weight)
                        )
                        if (
                            previous_core is not None
                            and int(args.annual_core_cut_frequency) > 0
                            and iteration % int(args.annual_core_cut_frequency) == 0
                        ):
                            _, _, core_cut, annual_core_lp_obj = _solve_fixed_annual_lp_cut(
                                data, cfg, args, run_dir, annual_core_point, iteration,
                                probe_name="core", cut_id=iteration * 10 + 1,
                            )
                            if (
                                core_cut is not None
                                and math.isfinite(annual_core_lp_obj)
                                and math.isfinite(float(master_eta))
                            ):
                                annual_core_violation = float(master_eta) - _annual_lp_cut_rhs(core_cut, candidate)
                                core_threshold = max(
                                    float(args.lp_cut_abs_tol),
                                    float(args.lp_cut_rel_tol) * max(1.0, abs(float(master_eta))),
                                )
                                # Do not enlarge the master with a core cut that does not
                                # separate the current trial solution.
                                if annual_core_violation > core_threshold:
                                    annual_core_cut_added = int(add_annual_lp_cut(master, core_cut))

                    try:
                        exact_model, _exact_results, exact_obj, exact_ub, exact_gap = _solve_fixed_exact(
                            data, cfg, args, run_dir, candidate, iteration
                        )
                    except RuntimeError as exc:
                        termination = "exact_oracle_no_incumbent"
                        print(f"Exact annual certification stopped without an incumbent: {exc}")
                        if best_model is None:
                            raise
                        break
                    if (
                        development_investment_source is not None
                        and development_investment_signature is not None
                        and signature == development_investment_signature
                        and math.isfinite(development_reference_objective)
                    ):
                        reference_delta = float(exact_obj) - float(development_reference_objective)
                        reference_rel = reference_delta / max(
                            1.0, abs(float(development_reference_objective))
                        )
                        print(
                            "Development-seed exact-equivalence check: "
                            f"LBBD exact objective {exact_obj:,.3f} vs external reference "
                            f"{development_reference_objective:,.3f} SEK/year; "
                            f"delta {reference_delta:+,.3f} SEK ({100.0 * reference_rel:+.6f}%)."
                        )
                        if exact_ub + max(1.0, 1.0e-8 * abs(exact_ub)) < float(development_reference_objective):
                            print(
                                "WARNING: The LBBD fixed-investment exact upper bound is below "
                                "the external feasible reference objective. This suggests the "
                                "two formulations/configurations are not equivalent or the "
                                "development seed was taken from a different model version."
                            )
                    exact_cache[signature] = {
                        "objective": float(exact_obj),
                        "upper_bound": float(exact_ub),
                        "gap": float(exact_gap),
                    }
                    if exact_obj > best_lb:
                        best_lb = exact_obj
                        best_model = exact_model
                        best_inv = candidate
                        best_fixed_ub = exact_ub

                    # Full-data incumbent repair: exact recourse often reveals a tiny
                    # quantity of highly penalized local slack.  Build a resource-feasible
                    # neighboring investment (including charger-type swaps when a site is
                    # full) and re-certify it immediately.  The heuristic itself never
                    # changes LB/UB; only the second exact annual MIP can do so.
                    repair_passes = max(0, int(args.exact_slack_repair_passes or 0))
                    if repair_passes > 0:
                        repaired_candidate, exact_slack_before, repair_actions = _repair_candidate_from_exact_slack(
                            data, candidate, exact_model, repair_passes,
                            float(args.screen_skip_exact_slack_kwh),
                        )
                        repaired_signature = _investment_signature(repaired_candidate)
                        if repair_actions and repaired_signature != signature:
                            print(
                                f"Exact-slack incumbent repair: exact candidate had "
                                f"{exact_slack_before:,.3f} kWh/year slack; applying "
                                f"{len(repair_actions)} resource-feasible investment changes and re-certifying."
                            )
                            for action in repair_actions[:30]:
                                print(f"  {action}")
                            try:
                                repaired_model, repaired_results, repaired_obj, repaired_ub, repaired_gap = _solve_fixed_exact(
                                    data, cfg, args, run_dir, repaired_candidate, iteration * 100 + 1
                                )
                            except RuntimeError as exc:
                                print(f"Exact-slack repair could not be certified; retaining original candidate: {exc}")
                                repaired_model, repaired_obj, repaired_ub, repaired_gap = None, -math.inf, math.inf, math.inf
                            if repaired_model is not None:
                                exact_cache[repaired_signature] = {
                                    "objective": float(repaired_obj),
                                    "upper_bound": float(repaired_ub),
                                    "gap": float(repaired_gap),
                                }
                            # Preserve a valid configuration cut for the original exact
                            # point before moving the reported candidate to the repaired one.
                            if math.isfinite(exact_ub):
                                exact_config_added += int(add_exact_config_cut(
                                    master, ExactConfigCut(iteration * 100, candidate, exact_ub, exact_obj, exact_gap)
                                ))
                            if repaired_obj > best_lb:
                                best_lb = repaired_obj
                                best_model = repaired_model
                                best_inv = repaired_candidate
                                best_fixed_ub = repaired_ub
                            if repaired_obj > exact_obj:
                                candidate = repaired_candidate
                                signature = repaired_signature
                                signature_label = _signature_label(signature)
                                totals = _investment_totals(candidate)
                                exact_model = repaired_model
                                exact_obj = repaired_obj
                                exact_ub = repaired_ub
                                exact_gap = repaired_gap
                                screen = oracle.screen(
                                    candidate.x, source_iteration=iteration,
                                    certificate_kind="post_exact_slack_repair",
                                )
                                screen_shortage = float(screen.annual_unavoidable_slack_kwh)
                else:
                    cached = exact_cache[signature]
                    exact_obj = float(cached["objective"])
                    exact_ub = float(cached["upper_bound"])
                    exact_gap = float(cached["gap"])

                if (
                    master_term != "mip_bound_only_certified"
                    and math.isfinite(exact_ub)
                    and (
                        not math.isfinite(float(master_eta))
                        or float(master_eta) > float(exact_ub) + float(args.lp_cut_abs_tol)
                    )
                ):
                    exact_config_added += int(add_exact_config_cut(
                        master,
                        ExactConfigCut(iteration, candidate, exact_ub, exact_obj, exact_gap),
                    ))

                if (
                    not candidate_cached
                    and not args.skip_logic_mip
                    and int(args.logic_mip_frequency) > 0
                    and iteration % int(args.logic_mip_frequency) == 0
                    and lp_results
                ):
                    logic_added, logic_violated = _solve_logic_mips(
                        monthly_mip_models, lp_results, master, data, cfg, components,
                        candidate, args, run_dir, iteration,
                    )

            global_ub = max(best_lb, best_global_ub) if math.isfinite(best_lb) else best_global_ub
            gap = _rel_gap(global_ub, best_lb)
            last_global_gap = gap
            new_cuts_total = (
                hall_added + component_lp_added + annual_lp_added + annual_core_cut_added
                + exact_config_added + logic_added
            )
            at_tight_gap = active_master_gap <= tight_master_gap * (1.0 + 1e-9)
            if candidate_cached and new_cuts_total == 0 and at_tight_gap:
                tight_stagnation_rounds += 1
            else:
                tight_stagnation_rounds = 0

            best_totals = _investment_totals(best_inv) if best_inv is not None else {
                "slow": math.nan, "medium": math.nan, "fast": math.nan, "PV": math.nan, "BESS": math.nan
            }
            row = {
                "iteration": iteration,
                "status": status,
                "candidate_source": candidate_source,
                "candidate_signature": signature_label,
                "candidate_repeat_count": repeat_count,
                "candidate_cached": int(candidate_cached),
                "master_gap_requested": active_master_gap,
                "tight_stagnation_round": tight_stagnation_rounds,
                "new_cuts_total": new_cuts_total,
                "master_eta_SEK": master_eta,
                "master_bound_SEK": current_bound if math.isfinite(current_bound) else "",
                "master_termination": master_term,
                # Backward-compatible column: now populated only for a genuine MIP
                # incumbent-vs-bound gap from the same master solve.
                "master_internal_gap": master_internal_gap if math.isfinite(master_internal_gap) else "",
                "master_mip_gap": master_internal_gap if math.isfinite(master_internal_gap) else "",
                "master_gap_is_mip": int(math.isfinite(master_internal_gap)),
                "master_candidate_bound_gap": (
                    master_candidate_bound_gap if math.isfinite(master_candidate_bound_gap) else ""
                ),
                "master_time_limit_seconds": master_limit_used,
                "master_mip_focus": master_focus_used,
                "master_solve_seconds": master_solve_seconds,
                "global_ub_SEK": global_ub if math.isfinite(global_ub) else "",
                "best_lb_SEK": best_lb if math.isfinite(best_lb) else "",
                "lbbd_gap": gap if math.isfinite(gap) else "",
                "screen_unavoidable_slack_kWh": screen_shortage,
                "hall_profit_cuts_added": hall_added,
                "component_lp_cuts_added": component_lp_added,
                "component_lp_cuts_violated": component_lp_violated,
                "max_component_lp_violation_SEK": max_component_lp_violation,
                "annual_lp_cut_added": annual_lp_added,
                "annual_lp_upper_SEK": annual_lp_obj if math.isfinite(annual_lp_obj) else "",
                "annual_lp_violation_SEK": annual_lp_violation if math.isfinite(annual_lp_violation) else "",
                "annual_core_cut_added": annual_core_cut_added,
                "annual_core_lp_upper_SEK": annual_core_lp_obj if math.isfinite(annual_core_lp_obj) else "",
                "annual_core_violation_at_candidate_SEK": annual_core_violation if math.isfinite(annual_core_violation) else "",
                "exact_config_cut_added": exact_config_added,
                "partial_logic_cuts_added": logic_added,
                "partial_logic_cuts_violated": logic_violated,
                "candidate_exact_objective_SEK": exact_obj if math.isfinite(exact_obj) else "",
                "candidate_fixed_upper_bound_SEK": exact_ub if math.isfinite(exact_ub) else "",
                "candidate_fixed_gap": exact_gap if math.isfinite(exact_gap) else "",
                **totals,
                "best_slow": best_totals["slow"],
                "best_medium": best_totals["medium"],
                "best_fast": best_totals["fast"],
                "best_PV": best_totals["PV"],
                "best_BESS": best_totals["BESS"],
                "best_fixed_upper_bound_SEK": best_fixed_ub if math.isfinite(best_fixed_ub) else "",
                "elapsed_seconds": time.time() - start,
            }
            history.append(row)

            if status.startswith("evaluated"):
                cache_text = " cached" if candidate_cached else ""
                print(
                    f"Iteration {iteration:02d} | UB {global_ub:,.3f} | LB {best_lb:,.3f} | "
                    f"gap {100.0 * gap:.6f}% | candidate {exact_obj:,.3f}{cache_text} | "
                    f"fixed gap {100.0 * exact_gap:.6f}% | master {master_term} "
                    f"{(f'MIP gap {100.0 * master_internal_gap:.4f}%' if math.isfinite(master_internal_gap) else 'MIP gap n/a')} "
                    f"(requested {100.0 * active_master_gap:.4f}%) | "
                    f"cuts +{hall_added} Hall +{component_lp_added} comp-LP "
                    f"+{annual_lp_added + annual_core_cut_added} annual-LP "
                    f"+{exact_config_added} config-MIP +{logic_added} partial-MIP | "
                    f"slow {totals['slow']} medium {totals['medium']} "
                    f"fast {totals['fast']} PV {totals['PV']} BESS {totals['BESS']}"
                )
            else:
                lb_text = "-inf" if not math.isfinite(best_lb) else f"{best_lb:,.3f}"
                ub_text = "inf" if not math.isfinite(global_ub) else f"{global_ub:,.3f}"
                print(
                    f"Iteration {iteration:02d} | Hall-screen shortage | UB {ub_text} | LB {lb_text} | "
                    f"unavoidable slack {screen_shortage:,.3f} kWh/year | cuts +{hall_added} Hall "
                    f"+{component_lp_added} comp-LP | slow {totals['slow']} medium {totals['medium']} "
                    f"fast {totals['fast']} PV {totals['PV']} BESS {totals['BESS']}"
                )

            _write_history(run_dir / "results" / "lbbd_history.csv", history)
            if math.isfinite(best_lb) and math.isfinite(global_ub) and gap <= float(args.lbbd_gap):
                termination = "certified_gap"
                break
            if tight_stagnation_rounds >= max(1, int(args.stagnation_max_rounds)):
                termination = "stagnation_no_new_cuts_at_tight_master_gap"
                print(
                    "Stopping after repeated identical candidates with no separating cuts "
                    f"at the tight master gap {100.0 * active_master_gap:.6f}%."
                )
                break

        phase_timing["decomposition_solve_seconds"] = time.time() - start
        if best_model is not None:
            print("\nBest certified incumbent")
            print("------------------------")
            print(f"Objective: {best_lb:,.3f} SEK/year")
            print(f"Best fixed-investment upper bound: {best_fixed_ub:,.3f} SEK/year")
            print(f"Global master upper bound: {best_global_ub:,.3f} SEK/year")
            print(f"Certified gap: {100.0 * _rel_gap(max(best_lb, best_global_ub), best_lb):.6f}%")
            print(f"Termination: {termination}")
            print(f"Output: {run_dir}")
            phase_started = time.perf_counter()
            export_all(best_model, data, cfg, run_dir)
            _write_investment_csv(run_dir / "results" / "lbbd_best_infrastructure_by_hex.csv", data, best_inv)
            resume_file = _save_certified_resume_checkpoint(
                run_dir, args, best_inv, best_lb, best_fixed_ub, best_global_ub
            )
            print(f"Certified resume checkpoint written to: {resume_file}")
            phase_timing["export_seconds"] = time.perf_counter() - phase_started
        else:
            print("\nNo exact annual incumbent was certified. Inspect Hall and component-LP cut diagnostics.")

        final_vars, final_cons = _model_counts(master)
        metadata = {
            "method": "LBBD",
            "run_profile": args._run_profile,
            "architecture": "embedded_continuous_redirection_network_linked_energy_corepoint_multicut",
            "dataset": args.dataset,
            "vipv_scenario": args.vipv_scenario,
            "problem_hash": args._problem_hash,
            "scenario": args.scenario,
            "termination": termination,
            "best_lb_SEK": best_lb if math.isfinite(best_lb) else None,
            "global_ub_SEK": best_global_ub if math.isfinite(best_global_ub) else None,
            "certified_gap": _rel_gap(max(best_lb, best_global_ub), best_lb) if math.isfinite(best_lb) else None,
            "static_origin_profit_cuts": static_origin_added,
            "root_hall_profit_cuts": root_hall_added,
            "initial_master_variables": master_vars,
            "initial_master_constraints": master_cons,
            "final_master_variables": final_vars,
            "final_master_constraints": final_cons,
            "linked_annual_bess": cfg.get("bess_boundary") == "legacy_linked_months",
            "cyclic_day_bess": cfg.get("bess_boundary") == "cyclic_day",
            "elapsed_seconds": time.time() - start,
            "max_iterations": int(args.max_iterations),
            "effective_settings": {
                key: value for key, value in vars(args).items() if not key.startswith("_")
            },
            "notes": (
                "The master embeds a continuous public-redirection network with exact reachability and distance cost, "
                "while trip, activation, and type-pair integer logic remain in the MIP oracle. Linked annual LP cuts are "
                "generated at the candidate and a running internal core point. Partial logic cuts reuse pooled threshold "
                "indicators. Exact annual MIPs certify incumbents."
            ),
        }
        (run_dir / "run_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        phase_timing["total_runtime_seconds"] = time.perf_counter() - total_started
        early_stats = {"initial_master": initial_master_stats, "final_master": model_statistics(master)}
        if best_model is not None:
            early_stats["best_exact_annual_oracle"] = model_statistics(best_model)
        write_run_complexity(run_dir, "LBBD", data, phase_timing=phase_timing,
                             model_stats=early_stats, resource_monitor=monitor)
        phase_started = time.perf_counter()
        if best_model is not None and not args.skip_figures:
            print("Generating result figures...")
            try:
                generate_run_figures(
                    run_dir=run_dir,
                    project_root=root,
                    dataset=args.dataset,
                    parking_shapefile=paths.get("parking_shapefile"),
                    dpi=max(100, int(args.figures_dpi)),
                    max_flow_arcs=max(1, int(args.max_redirection_arcs_plot)),
                    redirection_map_month=str(args.redirection_map_month),
                    basemap_alpha=min(1.0, max(0.0, float(args.basemap_alpha))),
                )
            except Exception as exc:
                print(f"WARNING: Figure generation failed without invalidating LBBD results: {exc}")
        elif best_model is not None:
            print("Figure generation skipped by configuration/command.")
        phase_timing["figure_generation_seconds"] = time.perf_counter() - phase_started
        monitor.stop()
        phase_timing["total_runtime_seconds"] = time.perf_counter() - total_started
        final_master_stats = model_statistics(master)
        model_stats = {
            "initial_master": initial_master_stats,
            "final_master": final_master_stats,
        }
        if best_model is not None:
            model_stats["best_exact_annual_oracle"] = model_statistics(best_model)
        write_run_complexity(
            run_dir, "LBBD", data,
            phase_timing=phase_timing,
            model_stats=model_stats,
            resource_monitor=monitor,
            extra_scalars={
                "trial_master_gap_initial": float(args.master_gap),
                "trial_master_gap_tight": float(args.master_gap_tight),
                "certified_lbbd_gap_requested": float(args.lbbd_gap),
                "unique_exact_candidates": len(exact_cache),
                "iterations_completed": len(history),
            },
        )

        return (0 if termination == "certified_gap" else 3) if best_model is not None else 2
    finally:
        monitor.stop()
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        transcript.close()


if __name__ == "__main__":
    raise SystemExit(main())
