#!/usr/bin/env python
"""Modified for the UrbanEV seasonal integration, 2026-10-22. See SOURCE_PROVENANCE.json."""
from __future__ import annotations

import argparse
import gc
import json
import math
import re
import sys
import time
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime
from pathlib import Path

import pandas as pd
import pyomo.environ as pyo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from input_scenarios import add_input_selection_arguments, resolve_input_selection, resolve_scenario_paths
from provenance import record_run_context
from input_validation import disable_redirection
from src.data_loader import load_inputs
from src.preprocessing import preprocess
from src.solve_model import solve_model, solver_certificate
from src.utils import ensure_dir, load_json
from src_benders.benders_master import build_benders_master, apply_hard_no_slack
from src_benders.benders_export import export_all, print_summary
from src_benders.benders_subproblem import extract_interface, solve_type_assignment_lp, add_type_assignment_cut
from src.visualize_results import generate_run_figures
from src.run_profiles import apply_profile_defaults, load_run_profile
from src.computational_complexity import ResourceMonitor, model_statistics, write_run_complexity


class TeeStream:
    def __init__(self, *streams):
        self.streams = [s for s in streams if s is not None]
    def write(self, msg):
        for s in self.streams:
            s.write(msg)
        self.flush()
        return len(msg)
    def flush(self):
        for s in self.streams:
            s.flush()


def parse_args():
    p = argparse.ArgumentParser(
        description="Arc-witness Benders decomposition for the EV charging infrastructure model."
    )
    add_input_selection_arguments(p)
    p.add_argument("--scenario", choices=["no_redirection", "with_redirection"], default="no_redirection")
    p.add_argument("--project-root", default=str(PROJECT_ROOT))
    p.add_argument("--threads", type=int, default=None)
    p.add_argument(
        "--mip-gap", type=float, default=None,
        help="Convenience override for the master and certified Benders gaps."
    )
    p.add_argument("--master-gap", type=float, default=None)
    p.add_argument("--benders-gap", type=float, default=None)
    p.add_argument("--max-iterations", type=int, default=None)
    p.add_argument("--time-limit", type=int, default=None)
    p.add_argument("--overall-time-limit", type=int, default=None,
                   help="Overall wall-clock budget in seconds, including all master and slot LP solves.")
    p.add_argument("--disable-pv", action="store_true")
    p.add_argument("--disable-bess", action="store_true")
    p.add_argument("--hard-no-slack", action="store_true")
    p.add_argument("--write-lp", action="store_true")
    p.add_argument("--cut-strategy", choices=["standard", "corepoint", "mw", "pareto"], default=None)
    p.add_argument("--max-cuts-per-iteration", type=int, default=None)
    p.add_argument("--min-cut-violation", type=float, default=None)
    p.add_argument("--core-weight", type=float, default=None)
    p.add_argument("--core-floor-kwh", type=float, default=None)
    p.add_argument("--pareto-tolerance", type=float, default=None)
    p.add_argument("--root-method", choices=["auto", "primal", "dual", "barrier", "concurrent", "deterministic-concurrent"], default=None)
    p.add_argument("--node-method", choices=["auto", "primal", "dual", "barrier"], default=None)
    p.add_argument("--nodefile-start", type=float, default=None)
    p.add_argument("--nodefile-dir", default=None, help="Optional directory for Gurobi branch-and-bound node files.")
    p.add_argument("--soft-mem-limit-gb", type=float, default=None)
    p.add_argument("--pre-sparsify", type=int, choices=[-1, 0, 1, 2], default=None)
    p.add_argument("--aggregate", type=int, choices=[-1, 0, 1, 2], default=None)
    p.add_argument("--pre-passes", type=int, default=None)
    p.add_argument("--solver-cuts", type=int, choices=[-1, 0, 1, 2, 3], default=None)
    p.add_argument("--no-rel-heur-time", type=float, default=None)
    p.add_argument("--skip-figures", action="store_true", default=None)
    p.add_argument("--figures-dpi", type=int, default=300)
    p.add_argument("--max-redirection-arcs-plot", type=int, default=150)
    return p.parse_args()

def load_configs(root: Path, dataset: str, vipv_scenario: str):
    paths = resolve_scenario_paths(root, dataset, vipv_scenario)
    return paths, load_json(root / "config" / "model_config.json"), load_json(root / "config" / "solver_gurobi.json")

def make_run_dir(paths, dataset, scenario, disable_pv, disable_bess):
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    tech = ("noPV" if disable_pv else "withPV") + "_" + ("noBESS" if disable_bess else "withBESS")
    d = Path(paths["runs_root"]) / f"{stamp}_{dataset}_{paths['vipv_scenario']}_{scenario}_Benders_{tech}"
    for sub in ["logs", "results", "model", "nodefiles", "iterations", "subproblems"]:
        ensure_dir(d / sub)
    return d

def finite_gap(ub: float, lb: float) -> float:
    if not (math.isfinite(ub) and math.isfinite(lb)):
        return float("inf")
    return max(0.0, ub - lb) / max(1.0, abs(lb))



def update_core_interface(core: dict | None, interface: dict, weight: float, floor: float = 0.0) -> dict:
    # Convex averaging preserves R/W/G balance when the stored interfaces are balanced.
    if core is None:
        return {fam: dict(vals) for fam, vals in interface.items() if fam in {"R", "W", "G"}}
    w = min(1.0, max(0.0, float(weight)))
    out = {}
    for fam in ["R", "W", "G"]:
        keys = set(core.get(fam, {})) | set(interface.get(fam, {}))
        vals = {}
        for k in keys:
            v = (1.0 - w) * float(core.get(fam, {}).get(k, 0.0)) + w * float(interface.get(fam, {}).get(k, 0.0))
            vals[k] = max(float(floor), v) if floor > 0 and v > 0 else max(0.0, v)
        out[fam] = vals
    return out


def _candidate_violation(candidate) -> float:
    if hasattr(candidate, "violation"):
        return float(getattr(candidate, "violation", 0.0) or 0.0)
    if isinstance(candidate, dict):
        return float(candidate.get("violation", 0.0) or 0.0)
    return 0.0


def select_cut_candidates(candidates: list, max_cuts: int | None, min_violation: float) -> list:
    kept = [c for c in candidates if _candidate_violation(c) > float(min_violation)]
    kept.sort(key=_candidate_violation, reverse=True)
    if max_cuts is not None and int(max_cuts) > 0:
        return kept[: int(max_cuts)]
    return kept


def parse_gurobi_final_bound(log_path: Path):
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    pat = re.compile(r"Best objective\s+([-+0-9.eE]+),\s+best bound\s+([-+0-9.eE]+),\s+gap\s+([-+0-9.eE%]+)")
    matches = pat.findall(text)
    if not matches:
        return None, None, None
    obj, bound, gap = matches[-1]
    gap_val = None
    try:
        gap_val = float(gap.rstrip("%")) / (100.0 if gap.endswith("%") else 1.0)
    except Exception:
        pass
    return float(obj), float(bound), gap_val


def snapshot_vars(model):
    snap = {}
    for comp in model.component_objects(pyo.Var, active=True):
        vals = {}
        for idx in comp:
            vals[idx] = pyo.value(comp[idx], exception=False)
        snap[comp.name] = vals
    return snap


def restore_vars(model, snap):
    for name, vals in snap.items():
        comp = model.find_component(name)
        if comp is None:
            continue
        for idx, val in vals.items():
            if val is not None:
                comp[idx].set_value(val, skip_validation=True)


def solve_master(model, solver_cfg, run_dir: Path, iteration: int):
    log_path = run_dir / "logs" / f"gurobi_master_iter_{iteration:03d}.log"
    solver_cfg_iter = dict(solver_cfg)
    old_log = run_dir / "logs" / "gurobi_run.log"
    if old_log.exists():
        old_log.unlink()
    res = solve_model(model, solver_cfg_iter, run_dir)
    if old_log.exists():
        log_path.write_text(old_log.read_text(encoding="utf-8", errors="replace"), encoding="utf-8", errors="replace")
    certificate = solver_certificate(res, model, log_path)
    inc = certificate["objective_SEK"]
    bound = certificate["valid_bound_SEK"]
    return res, inc, (float(bound) if bound is not None else float("inf")), certificate["gurobi_mip_gap"]


def run_benders_loop(model, data, solver_cfg, run_dir: Path, args):
    best_lb = -float("inf")
    best_rows = []
    best_snapshot = None
    global_ub = float("inf")
    history, sp_rows, cut_rows = [], [], []
    cut_tol = float(getattr(args, "min_cut_violation", 1e-5))
    cut_strategy = str(getattr(args, "cut_strategy", "standard")).lower()
    if cut_strategy in {"mw", "pareto"}:
        cut_strategy = "corepoint"
    core_interface = None
    converged = False
    termination = "max_iterations"
    for it in range(1, int(args.max_iterations) + 1):
        deadline = getattr(args, "_overall_deadline", math.inf)
        remaining = deadline - time.perf_counter()
        if remaining <= 60:
            termination = "overall_time_limit"
            break
        print(f"\n========== Benders ITERATION {it} ==========")
        solver_cfg_iter = dict(solver_cfg)
        solver_cfg_iter["time_limit_seconds"] = max(1, min(int(solver_cfg["time_limit_seconds"]), int(remaining - 60)))
        res, master_incumbent, master_bound, master_mip_gap = solve_master(model, solver_cfg_iter, run_dir, it)
        if math.isfinite(master_bound):
            global_ub = min(global_ub, master_bound)
        term = str(res.solver.termination_condition).lower()
        if master_incumbent is None:
            termination = "master_no_incumbent_" + term
            history.append({"iteration": it, "method": "Benders", "status": termination,
                            "elapsed_seconds": time.perf_counter() - getattr(args, "_overall_started", time.perf_counter()),
                            "master_best_bound_UB_SEK": master_bound,
                            "global_best_UB_SEK": global_ub,
                            "best_LB_SEK": best_lb if math.isfinite(best_lb) else None,
                            "Benders_gap": finite_gap(global_ub, best_lb)})
            print(f"Master {it} stopped without a loaded incumbent; retained bound={master_bound:,.3f} and prior certified LB={best_lb:,.3f}.")
            break
        if "error" in str(res.solver.status).lower():
            termination = "solver_error_with_previous_incumbent"
            break
        interface = extract_interface(model, data)
        master_obj = float(pyo.value(model.obj))
        theta_total = sum(interface["theta"].values())
        true_type_cost = 0.0
        cuts_added = 0
        max_viol = 0.0
        cut_candidates = []
        iter_flows = []
        bad_slots = 0
        deadline_reached = False
        for mon in data["MONTHS"]:
            for t in data["INTERVALS"]:
                if time.perf_counter() >= deadline - 60:
                    deadline_reached = True
                    bad_slots += 1
                    break
                outg = sum(interface["G"].get((int(i), int(j), mon, int(t)), 0.0) for (i, j, m2, t2) in data["allowed_st"] if m2 == mon and int(t2) == int(t))
                if outg <= 1e-8:
                    sp_rows.append({"iteration": it, "Month": mon, "TimeIndex": int(t), "objective_SEK": 0.0, "theta_SEK": interface["theta"].get((mon, int(t)), 0.0), "violation_SEK": 0.0, "positive_rows": 0, "n_arcs": 0, "n_vars": 0, "status": "ok", "termination": "empty_zero_redirection"})
                    continue
                sp = solve_type_assignment_lp(
                    data, solver_cfg, mon, int(t), interface,
                    run_dir=run_dir, iteration=it, tol=1e-8,
                    cut_strategy=cut_strategy, core_interface=core_interface,
                    pareto_tolerance=float(getattr(args, "pareto_tolerance", 1e-7)),
                )
                sp_rows.append({"iteration": it, "Month": mon, "TimeIndex": int(t), "objective_SEK": sp.objective, "theta_SEK": sp.theta, "violation_SEK": sp.violation, "dual_rhs_current_SEK": sp.dual_rhs_current, "dual_selection": sp.dual_selection, "positive_rows": len(sp.flows), "n_arcs": sp.n_arcs, "n_vars": sp.n_vars, "status": sp.status, "termination": sp.termination})
                if not math.isfinite(sp.objective):
                    bad_slots += 1
                    continue
                true_type_cost += sp.objective
                iter_flows.extend(sp.flows)
                if sp.violation > cut_tol:
                    max_viol = max(max_viol, sp.violation)
                    cut_candidates.append(sp)
            if deadline_reached:
                break
        selected_cuts = select_cut_candidates(cut_candidates, getattr(args, "max_cuts_per_iteration", None), cut_tol)
        for sp in selected_cuts:
            nz = add_type_assignment_cut(model, sp)
            cuts_added += 1
            cut_rows.append({
                "iteration": it,
                "Month": sp.mon,
                "TimeIndex": int(sp.t),
                "cut_type": "type_assignment_LP_dual_optimality",
                "selection_rule": cut_strategy,
                "dual_selection": sp.dual_selection,
                "rhs_at_current_SEK": sp.dual_rhs_current,
                "true_objective_SEK": sp.objective,
                "theta_at_current_SEK": sp.theta,
                "violation_SEK": sp.violation,
                "nonzeros": nz,
                "n_arcs": sp.n_arcs,
                "n_vars": sp.n_vars,
                "termination": sp.termination,
            })
        certified = master_obj + theta_total - true_type_cost if bad_slots == 0 else -float("inf")
        if certified > best_lb:
            best_lb = certified
            best_rows = list(iter_flows)
            best_snapshot = snapshot_vars(model)
        gap = finite_gap(global_ub, best_lb)
        row = {
            "iteration": it, "method": "Benders",
            "elapsed_seconds": time.perf_counter() - getattr(args, "_overall_started", time.perf_counter()),
            "master_incumbent_SEK": master_incumbent,
            "master_best_bound_UB_SEK": master_bound,
            "global_best_UB_SEK": global_ub,
            "master_reported_mip_gap": master_mip_gap,
            "theta_master_SEK": theta_total,
            "true_type_assignment_cost_SEK": true_type_cost,
            "certified_LB_candidate_SEK": certified,
            "best_LB_SEK": best_lb,
            "Benders_gap": gap,
            "cuts_added": cuts_added,
            "cut_candidates": len(cut_candidates),
            "bad_slots": bad_slots,
            "max_theta_violation_SEK": max_viol,
            "positive_type_rows": len(iter_flows)
        }
        history.append(row)
        print(f"Iteration {it}: incumbent={master_incumbent:,.3f}, boundUB={master_bound:,.3f}, globalUB={global_ub:,.3f}, certified={certified:,.3f}, bestLB={best_lb:,.3f}, Benders gap={100*gap:.6f}%, type_cost={true_type_cost:,.3f}, theta={theta_total:,.3f}, cuts={cuts_added}, candidates={len(cut_candidates)}, bad_slots={bad_slots}, strategy={cut_strategy}")
        if cut_strategy == "corepoint":
            core_interface = update_core_interface(core_interface, interface, float(getattr(args, "core_weight", 0.35)), float(getattr(args, "core_floor_kwh", 0.0)))
        del interface, iter_flows, cut_candidates, selected_cuts
        gc.collect()
        if bad_slots == 0 and gap <= float(args.benders_gap):
            converged = True
            termination = "certified_gap"
            break
        if bad_slots > 0 and cuts_added == 0 and not deadline_reached:
            termination = "infeasible_type_assignment_without_feasibility_cut"
            print("Benders has an infeasible type-assignment interface and no feasibility cut; certification cannot continue.")
            break
        if deadline_reached:
            termination = "overall_time_limit"
            break
    hist = pd.DataFrame(history)
    sp = pd.DataFrame(sp_rows)
    cuts = pd.DataFrame(cut_rows)
    hist.to_csv(run_dir / "iterations" / "benders_iteration_history.csv", index=False)
    sp.to_csv(run_dir / "iterations" / "type_assignment_subproblem_summary.csv", index=False)
    cuts.to_csv(run_dir / "iterations" / "type_assignment_cuts.csv", index=False)
    if best_snapshot is not None:
        restore_vars(model, best_snapshot)
    return {"converged": converged, "termination": termination, "global_ub": global_ub,
            "history": hist, "sp": sp, "cuts": cuts, "best_rows": best_rows,
            "best_lb": best_lb, "best_snapshot_restored": best_snapshot is not None}


def main():
    total_started = time.perf_counter()
    monitor = ResourceMonitor().start()
    phase_timing: dict[str, float] = {}
    args = parse_args()
    args._overall_started = total_started
    args._overall_deadline = (time.perf_counter() + float(args.overall_time_limit)) if args.overall_time_limit else math.inf
    root = Path(args.project_root).resolve()
    resolve_input_selection(args, root)
    paths, cfg, solver_cfg = load_configs(root, args.dataset, args.vipv_scenario)
    apply_profile_defaults(args, load_run_profile(root, "benders", args.dataset))
    args._run_profile = f"benders.{args.dataset}"
    if args.mip_gap is not None:
        args.master_gap = float(args.mip_gap)
        args.benders_gap = float(args.mip_gap)
    if args.threads is not None:
        solver_cfg["threads"] = int(args.threads)
    if args.time_limit is not None:
        solver_cfg["time_limit_seconds"] = int(args.time_limit)
    solver_cfg["mip_gap"] = float(args.master_gap)
    method_map = {"auto": None, "primal": 0, "dual": 1, "barrier": 2, "concurrent": 3, "deterministic-concurrent": 4}
    node_method_map = {"auto": None, "primal": 0, "dual": 1, "barrier": 2}
    if method_map[args.root_method] is not None:
        solver_cfg["method"] = method_map[args.root_method]
    if node_method_map[args.node_method] is not None:
        solver_cfg["node_method"] = node_method_map[args.node_method]
    if args.nodefile_start is not None:
        solver_cfg["nodefile_start_gb"] = float(args.nodefile_start)
    if args.nodefile_dir is not None:
        solver_cfg["nodefile_dir"] = str(args.nodefile_dir)
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
    if args.no_rel_heur_time is not None:
        solver_cfg["no_rel_heur_time"] = float(args.no_rel_heur_time)
    run_dir = make_run_dir(paths, args.dataset, args.scenario, args.disable_pv, args.disable_bess)
    transcript = run_dir / "README_RUN.txt"
    with transcript.open("w", encoding="utf-8", errors="replace") as log_file, redirect_stdout(TeeStream(sys.__stdout__, log_file)), redirect_stderr(TeeStream(sys.__stderr__, log_file)):
        print("========== Benders TERMINAL LOG ==========")
        print(f"Project root : {root}")
        print(f"Dataset      : {args.dataset}")
        print(f"Run profile  : {args._run_profile}")
        print(f"Scenario     : {args.scenario}")
        print(f"Cut strategy : {args.cut_strategy}")
        print(f"Run folder   : {run_dir}")
        print("=======================================")
        phase_started = time.perf_counter()
        raw = load_inputs(paths)
        phase_timing["input_load_seconds"] = time.perf_counter() - phase_started
        phase_started = time.perf_counter()
        data = preprocess(raw, cfg)
        phase_timing["preprocessing_seconds"] = time.perf_counter() - phase_started
        data["dataset"] = args.dataset
        data["vipv_scenario"] = args.vipv_scenario
        args._solver_cfg = dict(solver_cfg)
        record_run_context(root, run_dir, data, cfg, args, "Benders")
        if args.scenario == "no_redirection":
            disable_redirection(data)
        data["disable_pv"] = bool(args.disable_pv)
        data["disable_bess"] = bool(args.disable_bess)
        print(f"Hex cells    : {len(data['hex_ids'])}")
        print(f"Arc-slots    : {len(data['allowed_st']):,}")
        print("Building Benders master...")
        phase_started = time.perf_counter()
        model = build_benders_master(data, cfg, scenario=args.scenario)
        phase_timing["model_build_seconds"] = time.perf_counter() - phase_started
        main_model_stats = model_statistics(model)
        if args.hard_no_slack:
            print("Hard no-slack mode: fixing slack to zero.")
            apply_hard_no_slack(model)
        if args.write_lp:
            lp = run_dir / "model" / "benders_master.lp"
            model.write(str(lp), io_options={"symbolic_solver_labels": True})
            print(f"LP written to: {lp}")
        manifest = {
            "dataset": args.dataset,
            "scenario": args.scenario,
            "method": "Benders",
            "run_profile": args._run_profile,
            "master_gap": args.master_gap,
            "benders_gap": args.benders_gap,
            "max_iterations": args.max_iterations,
            "cut_strategy": args.cut_strategy,
            "max_cuts_per_iteration": args.max_cuts_per_iteration,
            "min_cut_violation": args.min_cut_violation,
            "core_weight": args.core_weight,
            "core_floor_kwh": args.core_floor_kwh,
            "pareto_tolerance": args.pareto_tolerance,
            "root_method": args.root_method,
            "node_method": args.node_method,
            "nodefile_start_gb": solver_cfg.get("nodefile_start_gb"),
            "nodefile_dir": solver_cfg.get("nodefile_dir"),
            "soft_mem_limit_gb": solver_cfg.get("soft_mem_limit_gb"),
            "pre_sparsify": solver_cfg.get("pre_sparsify"),
            "aggregate": solver_cfg.get("aggregate"),
            "pre_passes": solver_cfg.get("pre_passes"),
            "solver_cuts": solver_cfg.get("cuts"),
            "no_rel_heur_time": solver_cfg.get("no_rel_heur_time"),
            "note": "Arc-witness Benders implementation. Type-pair assignment is solved by slot-wise LP recourse and represented by Benders optimality cuts."
        }
        (run_dir / "logs" / "benders_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        if args.scenario == "with_redirection":
            phase_started = time.perf_counter()
            out = run_benders_loop(model, data, solver_cfg, run_dir, args)
            phase_timing["decomposition_solve_seconds"] = time.perf_counter() - phase_started
            (run_dir / "run_metadata.json").write_text(json.dumps({
                "method": "Benders", "dataset": args.dataset, "scenario": args.scenario,
                "vipv_scenario": args.vipv_scenario, "problem_hash": args._problem_hash,
                "termination": out["termination"], "converged": out["converged"],
                "best_lb_SEK": out["best_lb"] if math.isfinite(out["best_lb"]) else None,
                "global_ub_SEK": out["global_ub"] if math.isfinite(out["global_ub"]) else None,
                "certified_gap": finite_gap(out["global_ub"], out["best_lb"])
                    if math.isfinite(out["global_ub"]) and math.isfinite(out["best_lb"]) else None,
            }, indent=2), encoding="utf-8")
            if not out["best_snapshot_restored"]:
                print("No certified original-problem incumbent; solver bounds and logs remain available.")
                monitor.stop()
                phase_timing["total_runtime_seconds"] = time.perf_counter() - total_started
                write_run_complexity(run_dir, "Benders", data, phase_timing=phase_timing,
                                     model_stats={"master": main_model_stats}, resource_monitor=monitor,
                                     extra_scalars={"termination_reason": out["termination"]})
                return 2
            print_summary(model, data, cfg)
            phase_started = time.perf_counter()
            export_all(model, data, cfg, run_dir, type_rows=out["best_rows"], history=out["history"], sp_summary=out["sp"], cut_records=out["cuts"], certified_lb=out["best_lb"])
            phase_timing["export_seconds"] = time.perf_counter() - phase_started
            phase_started = time.perf_counter()
            if not args.skip_figures:
                print("Generating result figures...")
                try:
                    generate_run_figures(
                        run_dir=run_dir,
                        project_root=root,
                        dataset=args.dataset,
                        parking_shapefile=paths.get("parking_shapefile"),
                        dpi=max(100, int(args.figures_dpi)),
                        max_flow_arcs=max(1, int(args.max_redirection_arcs_plot)),
                    )
                except Exception as exc:
                    print(f"WARNING: Figure generation failed without invalidating Benders results: {exc}")
            phase_timing["figure_generation_seconds"] = time.perf_counter() - phase_started
            print(f"Benders status: {'converged' if out['converged'] else 'stopped'}; best certified incumbent restored={out['best_snapshot_restored']}; best LB={out['best_lb']:,.3f} SEK")
        else:
            print("Solving no-redirection master with Gurobi...")
            phase_started = time.perf_counter()
            res = solve_model(model, solver_cfg, run_dir)
            phase_timing["solve_seconds"] = time.perf_counter() - phase_started
            print(res.solver)
            cert = solver_certificate(res, model, run_dir / "logs" / "gurobi_run.log")
            cert["requested_mip_gap"] = solver_cfg.get("mip_gap")
            (run_dir / "results" / "solver_certificate.json").write_text(json.dumps(cert, indent=2), encoding="utf-8")
            if not cert["has_loaded_incumbent"]:
                print("No feasible incumbent available; solver status/bounds were retained.")
                return 2
            print_summary(model, data, cfg)
            phase_started = time.perf_counter()
            export_all(model, data, cfg, run_dir)
            phase_timing["export_seconds"] = time.perf_counter() - phase_started
            obj_val = pyo.value(model.obj)
            upper = cert["valid_bound_SEK"]
            rows = [{"iteration": 1, "method": "Benders_no_redirection_validation", "master_obj_SEK": obj_val, "best_LB_SEK": obj_val, "global_best_UB_SEK": upper, "Benders_gap": finite_gap(upper, obj_val) if upper is not None else math.nan, "cuts_added": 0, "bad_slots": 0, "note": "No-redirection validation: redirection variables fixed to zero"}]
            pd.DataFrame(rows).to_csv(run_dir / "iterations" / "benders_iteration_history.csv", index=False)
            phase_started = time.perf_counter()
            if not args.skip_figures:
                print("Generating result figures...")
                try:
                    generate_run_figures(
                        run_dir=run_dir,
                        project_root=root,
                        dataset=args.dataset,
                        parking_shapefile=paths.get("parking_shapefile"),
                        dpi=max(100, int(args.figures_dpi)),
                        max_flow_arcs=max(1, int(args.max_redirection_arcs_plot)),
                    )
                except Exception as exc:
                    print(f"WARNING: Figure generation failed without invalidating Benders results: {exc}")
            phase_timing["figure_generation_seconds"] = time.perf_counter() - phase_started
        monitor.stop()
        phase_timing["total_runtime_seconds"] = time.perf_counter() - total_started
        write_run_complexity(
            run_dir, "Benders", data,
            phase_timing=phase_timing,
            model_stats={"master": main_model_stats},
            resource_monitor=monitor,
            extra_scalars={
                "master_mip_gap_requested": float(args.master_gap),
                "certified_benders_gap_requested": float(args.benders_gap),
                "solver_threads_requested": solver_cfg.get("threads"),
                "nodefile_start_gb": solver_cfg.get("nodefile_start_gb"),
                "nodefile_dir": solver_cfg.get("nodefile_dir"),
                "soft_mem_limit_gb": solver_cfg.get("soft_mem_limit_gb"),
                "slot_lp_calls": int(len(out["sp"])) if args.scenario == "with_redirection" else 0,
                "slot_lp_max_variables": float(pd.to_numeric(out["sp"].get("n_vars"), errors="coerce").max()) if args.scenario == "with_redirection" and not out["sp"].empty and "n_vars" in out["sp"] else 0,
                "slot_lp_max_arcs": float(pd.to_numeric(out["sp"].get("n_arcs"), errors="coerce").max()) if args.scenario == "with_redirection" and not out["sp"].empty and "n_arcs" in out["sp"] else 0,
                "iterations_completed": int(len(out["history"])) if args.scenario == "with_redirection" else 1,
            },
        )
        print(f"Run finished successfully. Run directory: {run_dir}")
        print(f"Terminal transcript written to: {transcript}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
