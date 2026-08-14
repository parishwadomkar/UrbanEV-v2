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
from preprocessing import preprocess
from utils import ensure_dir, load_json, resolve_project_path
from run_profiles import apply_profile_defaults, load_run_profile
from technology_switches import apply_technology_switches
from visualize_results import generate_run_figures
from computational_complexity import ResourceMonitor, model_statistics, write_run_complexity
from input_scenarios import add_input_selection_arguments, resolve_input_selection, resolve_scenario_paths
from decomposition_types import ComponentLogicOptimalityCut, build_slot_components
from network_feasibility import FeasibilityNetworkOracle
from operational_recourse import (
    build_monthly_recourse_model,
    solve_monthly_recourse_lp,
    solve_monthly_recourse_mip,
)
from lbbd_master import (
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
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--scenario", choices=["with_redirection", "no_redirection"], default="with_redirection")
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
    enable_norel: bool = True,
):
    base = dict(getattr(args, "_solver_cfg", {}) or {})
    options = {
        "Threads": int(max(1, threads)),
        "TimeLimit": int(max(1, time_limit)),
        "Presolve": base.get("presolve"),
        "NumericFocus": base.get("numeric_focus"),
        "Heuristics": (base.get("heuristics") if heuristics_override is None else float(heuristics_override)),
        "Cuts": base.get("cuts"),
        "NodefileStart": float(args.nodefile_start),
        "SoftMemLimit": args.soft_mem_limit_gb,
        "PreSparsify": base.get("pre_sparsify"),
        "Aggregate": base.get("aggregate"),
        "AggFill": base.get("agg_fill"),
        "SubMIPNodes": base.get("sub_mip_nodes"),
        "PumpPasses": base.get("pump_passes"),
        "ImproveStartGap": base.get("improve_start_gap"),
        "ImproveStartTime": base.get("improve_start_time"),
        "IntegralityFocus": base.get("integrality_focus"),
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
        finally:
            logger.removeFilter(filter_)
    return results


def _solve_master(
    model, args, run_dir: Path, iteration: int, remaining_seconds: float,
    requested_gap: float, force_full_time: bool = False, use_mip_start: bool = False,
):
    full_iterations = max(0, int(args.master_full_solve_iterations))
    use_full_time = bool(force_full_time) or iteration <= full_iterations
    requested_limit = int(args.master_time_limit) if use_full_time else int(args.master_late_time_limit)
    available = max(1, int(float(remaining_seconds) - float(args.finalization_reserve)))
    solve_limit = max(1, min(requested_limit, available))
    focus = int(args.master_mip_focus_early) if iteration < int(args.master_bound_focus_after) else int(args.master_mip_focus_late)
    opt = pyo.SolverFactory(args.solver)
    first_solution_limit = 0
    if iteration == 1 and args.first_master_solution_limit is not None:
        first_solution_limit = max(0, int(args.first_master_solution_limit))
    first_heuristics = (
        float(args.first_master_heuristics)
        if iteration == 1 and args.first_master_heuristics is not None
        else None
    )
    _configure_solver(
        opt, args, run_dir, f"lbbd_master_{iteration:03d}.log",
        int(args.threads), float(requested_gap), solve_limit, True, mip_focus=focus,
        solution_limit=(first_solution_limit if first_solution_limit > 0 else None),
        heuristics_override=first_heuristics,
        # After iteration 1 the previous master incumbent is warm-started and
        # NoRel is normally unnecessary overhead.
        enable_norel=(iteration == 1),
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


def _has_loaded_objective(model) -> bool:
    try:
        value = pyo.value(model.obj, exception=False)
        return value is not None and math.isfinite(float(value))
    except Exception:
        return False


def _is_usable_mip(results, model) -> bool:
    if not _has_loaded_objective(model):
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


def _solve_fixed_exact(data: dict, cfg: dict, args, run_dir: Path, inv: InvestmentPoint, iteration: int):
    model = build_model(data, cfg)
    apply_technology_switches(model, args.disable_pv, args.disable_bess, verbose=False)
    apply_scenario(model, args.scenario)
    _fix_investments(model, inv)
    opt = pyo.SolverFactory(args.solver)
    _configure_solver(
        opt, args, run_dir, f"lbbd_exact_annual_{iteration:03d}.log",
        int(args.threads), float(args.subproblem_gap), int(args.subproblem_time_limit), True,
    )
    results = _solve_and_load(opt, model, tee=bool(args.tee))
    if not _is_usable_mip(results, model):
        if "infeasibleorunbounded" in _solver_term(results):
            opt.options["DualReductions"] = 0
            results = _solve_and_load(opt, model, tee=bool(args.tee))
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
        upper = objective
    upper = max(objective, upper)
    gap = max(0.0, upper - objective) / max(1.0, abs(upper))
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
        int(args.threads), None, int(args.annual_lp_time_limit), False,
    )
    results = _solve_and_load(opt, model, tee=bool(args.tee))
    if not _is_optimal_lp(results):
        if "infeasibleorunbounded" in _solver_term(results):
            opt.options["DualReductions"] = 0
            results = _solve_and_load(opt, model, tee=bool(args.tee))
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
        "master_norel_heur_time", "master_norel_heur_work", "mip_focus",
    }
    merged_solver_cfg = dict(solver_cfg)
    for key in solver_profile_keys:
        if key in run_profile:
            merged_solver_cfg[key] = run_profile[key]
    args._solver_cfg = merged_solver_cfg
    check_input_paths(paths)
    runs_root = Path(paths["runs_root"])
    ensure_dir(runs_root)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    technology = ("noPV" if args.disable_pv else "withPV") + "_" + ("noBESS" if args.disable_bess else "withBESS")
    run_name = args.run_name or f"{timestamp}_{args.dataset}_{args.vipv_scenario}_{args.scenario}_LBBD_{technology}"
    run_dir = runs_root / run_name
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
        print(f"VIPV scenario: {args.vipv_scenario}")
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
        data["disable_pv"] = bool(args.disable_pv)
        data["disable_bess"] = bool(args.disable_bess)
        if args.scenario == "no_redirection":
            data["allowed"] = []
            data["allowed_st"] = []
            data["OUT"] = {}
            data["IN"] = {}
            data["ORIGIN_ST"] = []
            data["DEST_ST"] = []
        print(f"Hex cells: {len(data['hex_ids'])}")
        print(f"Active redirection arc-slots: {len(data['allowed_st']):,}")

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
        # Do not combine SolutionLimit=1 with the deliberately poor slack-only
        # start: if Gurobi accepted that start it would immediately satisfy the
        # solution limit and stop on an uninformative investment layout.
        master_mip_start_enabled = (
            not bool(args.no_master_mip_start)
            and first_master_solution_limit <= 0
        )
        if first_master_solution_limit > 0:
            print(
                "First-master feasibility bootstrap: "
                f"SolutionLimit={first_master_solution_limit}, "
                f"Heuristics={float(args.first_master_heuristics) if args.first_master_heuristics is not None else 'profile/default'}, "
                f"NoRel={float(args.master_heuristic_time) if args.master_heuristic_time is not None else float(args._solver_cfg.get('master_norel_heur_time', 0.0) or 0.0):g}s."
            )
            print(
                "Internal slack-only MIP start disabled during the bootstrap so it "
                "cannot consume the first-solution limit."
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
            if first_master_solution_limit <= 0:
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

        if args.write_lp:
            master.write(str(run_dir / "model" / "lbbd_master_initial.lp"), io_options={"symbolic_solver_labels": True})

        history: list[dict] = []
        best_lb = -math.inf
        best_model = None
        best_inv = None
        best_fixed_ub = math.inf
        best_global_ub = math.inf
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

            master_results, master_limit_used, master_focus_used, master_solve_seconds = _solve_master(
                master, args, run_dir, iteration, remaining,
                requested_gap=active_master_gap,
                force_full_time=force_full_master_time,
                use_mip_start=(iteration == 1 and master_mip_start_enabled),
            )
            eta_value = pyo.value(master.Eta, exception=False)
            if eta_value is None or not math.isfinite(float(eta_value)):
                raise RuntimeError(
                    f"Master returned no usable incumbent at iteration {iteration}: "
                    f"termination={_solver_term(master_results)}. "
                    "For the full data master, increase --master-time-limit or leave the "
                    "internal slack-only MIP start enabled. Also consider increasing "
                    "--master-heuristic-time/--master-heuristic-work on HPC."
                )
            candidate = extract_investment(master)
            signature = _investment_signature(candidate)
            signature_label = _signature_label(signature)
            if signature == previous_signature:
                repeat_count += 1
            else:
                repeat_count = 0
            previous_signature = signature
            candidate_cached = signature in exact_cache
            totals = _investment_totals(candidate)
            master_eta = float(pyo.value(master.Eta))
            current_bound = _master_bound(master_results, master)
            master_term = _solver_term(master_results)
            master_internal_gap = _rel_gap(current_bound, master_eta)
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
            should_evaluate_exact = (
                screen_shortage <= float(args.screen_skip_exact_slack_kwh)
                or forced_exact
                or no_new_separation
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
                        if annual_cut is not None and math.isfinite(annual_lp_obj):
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
                            if core_cut is not None and math.isfinite(annual_core_lp_obj):
                                annual_core_violation = float(master_eta) - _annual_lp_cut_rhs(core_cut, candidate)
                                core_threshold = max(
                                    float(args.lp_cut_abs_tol),
                                    float(args.lp_cut_rel_tol) * max(1.0, abs(float(master_eta))),
                                )
                                # Do not enlarge the master with a core cut that does not
                                # separate the current trial solution.
                                if annual_core_violation > core_threshold:
                                    annual_core_cut_added = int(add_annual_lp_cut(master, core_cut))

                    exact_model, exact_results, exact_obj, exact_ub, exact_gap = _solve_fixed_exact(
                        data, cfg, args, run_dir, candidate, iteration
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
                else:
                    cached = exact_cache[signature]
                    exact_obj = float(cached["objective"])
                    exact_ub = float(cached["upper_bound"])
                    exact_gap = float(cached["gap"])

                if float(master_eta) > float(exact_ub) + float(args.lp_cut_abs_tol):
                    exact_config_added = int(add_exact_config_cut(
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

            row = {
                "iteration": iteration,
                "status": status,
                "candidate_signature": signature_label,
                "candidate_repeat_count": repeat_count,
                "candidate_cached": int(candidate_cached),
                "master_gap_requested": active_master_gap,
                "tight_stagnation_round": tight_stagnation_rounds,
                "new_cuts_total": new_cuts_total,
                "master_eta_SEK": master_eta,
                "master_bound_SEK": current_bound if math.isfinite(current_bound) else "",
                "master_termination": master_term,
                "master_internal_gap": master_internal_gap if math.isfinite(master_internal_gap) else "",
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
                "elapsed_seconds": time.time() - start,
            }
            history.append(row)

            if status.startswith("evaluated"):
                cache_text = " cached" if candidate_cached else ""
                print(
                    f"Iteration {iteration:02d} | UB {global_ub:,.3f} | LB {best_lb:,.3f} | "
                    f"gap {100.0 * gap:.6f}% | candidate {exact_obj:,.3f}{cache_text} | "
                    f"fixed gap {100.0 * exact_gap:.6f}% | master {master_term} "
                    f"{100.0 * master_internal_gap:.4f}% (requested {100.0 * active_master_gap:.4f}%) | "
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
            "linked_annual_bess": True,
            "cyclic_day_bess": False,
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

        return 0
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        transcript.close()


if __name__ == "__main__":
    raise SystemExit(main())
