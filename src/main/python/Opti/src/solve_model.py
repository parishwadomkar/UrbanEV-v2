from __future__ import annotations

from pathlib import Path
import math
import re

from pyomo.environ import SolverFactory
from pyomo.opt import SolverStatus, TerminationCondition


def _gurobi_log_has_soft_memory_stop(log_path: Path) -> bool:
    """Return True when the Gurobi log shows a graceful SoftMemLimit stop.

    Older/classic Pyomo Gurobi interfaces may map the newer Gurobi MEM_LIMIT
    status to SolverStatus.error even though Gurobi has retained a valid MIP
    incumbent.  Detect the solver-native message so that the incumbent can be
    loaded and exported instead of being lost at the Pyomo boundary.
    """
    try:
        if not log_path.exists():
            return False
        # The end of a Gurobi log contains the termination reason.  Reading
        # only the tail avoids loading a multi-megabyte log into memory.
        with log_path.open("rb") as fh:
            try:
                fh.seek(-131072, 2)
            except OSError:
                fh.seek(0)
            tail = fh.read().decode("utf-8", errors="replace").lower()
        return (
            "memory limit reached" in tail
            or "soft memory limit" in tail
            or "mem_limit" in tail
        )
    except Exception:
        return False


def solver_certificate(results, model, log_path: Path) -> dict:
    """Record only bounds justified by the returned solve, including limit exits."""
    term = str(results.solver.termination_condition)
    has_incumbent = bool(getattr(model, "_last_solve_loaded_incumbent", False))
    objective = math.nan
    if has_incumbent:
        from pyomo.environ import Objective, value
        active = list(model.component_data_objects(Objective, active=True))
        if len(active) == 1:
            try:
                objective = float(value(active[0]))
            except (TypeError, ValueError):
                pass
    try:
        bound = float(results.problem.upper_bound)
    except (AttributeError, TypeError, ValueError):
        bound = math.nan
    soft_memory_stop = _gurobi_log_has_soft_memory_stop(log_path)
    if not math.isfinite(bound) and log_path.exists():
        with log_path.open("rb") as fh:
            try:
                fh.seek(-131072, 2)
            except OSError:
                fh.seek(0)
            tail = fh.read().decode("utf-8", errors="replace")
        matches = re.findall(r"Best objective\s+[-+0-9.eE]+,\s+best bound\s+([-+0-9.eE]+),", tail)
        if matches:
            bound = float(matches[-1])
    if not math.isfinite(bound) and has_incumbent and results.solver.termination_condition == TerminationCondition.optimal:
        bound = objective
    if math.isfinite(bound) and math.isfinite(objective):
        bound = max(bound, objective)
    gap = (max(0.0, bound - objective) / max(1.0, abs(objective))) if math.isfinite(bound) and math.isfinite(objective) else None
    lower = term.replace("_", "").replace(" ", "").lower()
    if soft_memory_stop:
        reason = "memory_limit"
    elif "time" in lower:
        reason = "time_limit"
    elif "userobjective" in lower or "objective" in lower and "limit" in lower:
        reason = "objective_limit"
    elif "optimal" in lower:
        reason = "gap_converged"
    elif "infeasible" in lower:
        reason = "infeasible"
    elif not has_incumbent:
        reason = "no_feasible_solution" if "limit" in lower or "interrupt" in lower else "solver_error"
    else:
        reason = "other_usable_termination" if str(results.solver.status).lower() != "error" else "solver_error"
    if reason == "solver_error":
        # An error exit has no documented proof status even if the interface
        # happens to expose a stale numeric bound.
        bound = math.nan
        gap = None
    return {
        "termination_reason": reason,
        "pyomo_termination": term,
        "pyomo_status": str(results.solver.status),
        "has_loaded_incumbent": has_incumbent,
        "objective_SEK": objective if math.isfinite(objective) else None,
        "valid_bound_SEK": bound if math.isfinite(bound) else None,
        "gurobi_mip_gap": gap,
    }


def solve_model(model, solver_cfg: dict, run_dir: Path):
    log_dir = run_dir / "logs"
    configured_node_dir = solver_cfg.get("nodefile_dir")
    if configured_node_dir:
        node_dir = Path(str(configured_node_dir)).expanduser()
        if not node_dir.is_absolute():
            node_dir = (Path.cwd() / node_dir).resolve()
    else:
        node_dir = run_dir / "nodefiles"
    log_dir.mkdir(parents=True, exist_ok=True)
    node_dir.mkdir(parents=True, exist_ok=True)

    opt = SolverFactory(solver_cfg.get("solver", "gurobi"))
    base = {
        "Threads": solver_cfg.get("threads"),
        "Presolve": solver_cfg.get("presolve"),
        "NumericFocus": solver_cfg.get("numeric_focus"),
        "Heuristics": solver_cfg.get("heuristics"),
        "MIPGap": solver_cfg.get("mip_gap"),
        "NodefileStart": solver_cfg.get("nodefile_start_gb"),
        "Cuts": solver_cfg.get("cuts"),
        "TimeLimit": solver_cfg.get("time_limit_seconds"),
        "MIPFocus": solver_cfg.get("mip_focus"),
        "Method": solver_cfg.get("method"),
        "NodeMethod": solver_cfg.get("node_method"),
        "PreSparsify": solver_cfg.get("pre_sparsify"),
        "Aggregate": solver_cfg.get("aggregate"),
        "PrePasses": solver_cfg.get("pre_passes"),
        "SoftMemLimit": solver_cfg.get("soft_mem_limit_gb"),
        "NoRelHeurTime": solver_cfg.get("no_rel_heur_time"),
    }
    for name, value in base.items():
        if value is not None:
            opt.options[name] = value
    for name, value in dict(solver_cfg.get("extra_options", {})).items():
        if value is not None:
            opt.options[str(name)] = value

    gurobi_log = (log_dir / solver_cfg.get("log_name", "gurobi_run.log")).resolve()
    opt.options["LogFile"] = str(gurobi_log).replace("\\", "/")
    opt.options["NodefileDir"] = str(node_dir.resolve()).replace("\\", "/")

    kwargs = {
        "tee": bool(solver_cfg.get("tee", True)),
        "logfile": str(log_dir / ("pyomo_solve.log" if "log_name" not in solver_cfg else solver_cfg["log_name"].removesuffix(".log") + ".pyomo.log")),
        # Inspect termination before loading.  This is essential for graceful
        # limits such as Gurobi SoftMemLimit, where a valid incumbent exists
        # even though the classic Pyomo interface can report status=error.
        "load_solutions": False,
    }
    model._last_solve_loaded_incumbent = False
    results = opt.solve(model, **kwargs)

    n_solutions = len(results.solution)
    soft_memory_stop = _gurobi_log_has_soft_memory_stop(gurobi_log)

    if soft_memory_stop and n_solutions > 0:
        # Gurobi guarantees that SoftMemLimit is a graceful termination and
        # solution information remains available.  Some classic Pyomo/Gurobi
        # versions do not yet map Gurobi status 17 (MEM_LIMIT), leaving the
        # SolverResults status as `error`.  Reclassify only this explicitly
        # detected case as a resource interrupt so Pyomo will load the valid
        # incumbent rather than rejecting it.
        if results.solver.status == SolverStatus.error:
            results.solver.status = SolverStatus.aborted
        results.solver.termination_condition = TerminationCondition.resourceInterrupt
        print(
            "Gurobi reached SoftMemLimit but returned a feasible incumbent; "
            "loading and exporting the incumbent/bound as a partial solve."
        )

    if n_solutions > 0 and results.solver.status != SolverStatus.error:
        model.solutions.load_from(results)
        model._last_solve_loaded_incumbent = True

    return results
