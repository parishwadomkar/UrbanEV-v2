from __future__ import annotations

from pathlib import Path
from pyomo.environ import SolverFactory


def solve_model(model, solver_cfg: dict, run_dir: Path):
    log_dir = run_dir / "logs"
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

    opt.options["LogFile"] = str((log_dir / "gurobi_run.log").resolve()).replace("\\", "/")
    opt.options["NodefileDir"] = str(node_dir.resolve())

    kwargs = {
        "tee": bool(solver_cfg.get("tee", True)),
        "logfile": str(log_dir / "pyomo_solve.log"),
    }
    return opt.solve(model, **kwargs)
