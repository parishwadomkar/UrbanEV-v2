from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyomo.environ as pyo


def sv(x, default=0.0):
    try:
        v = pyo.value(x)
        return default if v is None else float(v)
    except Exception:
        try:
            return float(x)
        except Exception:
            return default


@dataclass
class TypeAssignmentResult:
    mon: str
    t: int
    objective: float
    theta: float
    violation: float
    flows: list[dict[str, Any]]
    dual_R: dict[tuple[int, str], float]
    dual_W: dict[tuple[int, str], float]
    dual_G: dict[tuple[int, int], float]
    dual_selection: str
    dual_rhs_current: float
    n_arcs: int
    n_vars: int
    status: str
    termination: str


def extract_interface(model, data: dict, tol: float = 1e-9) -> dict:
    return {
        "R": {(int(i), str(mon), int(t), str(c)): max(0.0, sv(model.R[i, mon, t, c])) for i in model.I for mon in model.M for t in model.H for c in model.C_pub},
        "W": {(int(i), str(mon), int(t), str(c)): max(0.0, sv(model.W[i, mon, t, c])) for i in model.I for mon in model.M for t in model.H for c in model.C_pub},
        "G": {(int(i), int(j), str(mon), int(t)): max(0.0, sv(model.G[i, j, mon, t])) for (i, j, mon, t) in model.A},
        "theta": {(str(mon), int(t)): max(0.0, sv(model.ThetaType[mon, t])) for mon in model.M for t in model.H},
    }


def slot_has_redirection(data: dict, mon: str, t: int, interface: dict, tol: float = 1e-8) -> bool:
    return any(interface["G"].get((int(i), int(j), str(mon), int(t)), 0.0) > tol for (i, j, m2, t2) in data["allowed_st"] if m2 == mon and int(t2) == int(t))




def _select_corepoint_dual(
    data: dict,
    solver_cfg: dict,
    mon: str,
    t: int,
    pubs: list[str],
    slot_arcs: list[tuple[int, int]],
    current: dict,
    core_interface: dict | None,
    primal_obj: float,
    run_dir: Path | None,
    iteration: int,
    pareto_tolerance: float,
) -> tuple[dict[tuple[int, str], float], dict[tuple[int, str], float], dict[tuple[int, int], float], str, float] | None:
    if core_interface is None or primal_obj <= 1e-9:
        return None
    origins = sorted({i for i, _ in slot_arcs})
    dests = sorted({j for _, j in slot_arcs})
    nd = float(data["N_MONTH"][mon])
    delta = data["delta_price"]

    dm = pyo.ConcreteModel()
    dm.O = pyo.Set(dimen=2, initialize=[(i, c) for i in origins for c in pubs])
    dm.D = pyo.Set(dimen=2, initialize=[(j, c) for j in dests for c in pubs])
    dm.A = pyo.Set(dimen=2, initialize=slot_arcs)
    dm.Z = pyo.Set(dimen=4, initialize=[(i, j, co, cd) for (i, j) in slot_arcs for co in pubs for cd in pubs])

    B = 1.0e6
    dm.alpha = pyo.Var(dm.O, bounds=(-B, B))
    dm.beta = pyo.Var(dm.D, bounds=(-B, B))
    dm.gamma = pyo.Var(dm.A, bounds=(-B, B))

    def dual_feas(mm, i, j, co, cd):
        return mm.alpha[i, co] + mm.beta[j, cd] + mm.gamma[i, j] <= nd * float(delta[(str(co), str(cd))])
    dm.DualFeas = pyo.Constraint(dm.Z, rule=dual_feas)

    def expr_for(intf: dict):
        return (
            sum(float(intf["R"].get((i, mon, int(t), c), 0.0)) * dm.alpha[i, c] for i in origins for c in pubs)
            + sum(float(intf["W"].get((j, mon, int(t), c), 0.0)) * dm.beta[j, c] for j in dests for c in pubs)
            + sum(float(intf["G"].get((i, j, mon, int(t)), 0.0)) * dm.gamma[i, j] for (i, j) in slot_arcs)
        )

    current_expr = expr_for(current)
    eps = max(1e-6, float(pareto_tolerance) * max(1.0, abs(float(primal_obj))))
    dm.CurrentOptimalFace = pyo.Constraint(expr=current_expr >= float(primal_obj) - eps)
    dm.obj = pyo.Objective(expr=expr_for(core_interface), sense=pyo.maximize)

    opt = pyo.SolverFactory(solver_cfg.get("solver", "gurobi"))
    opt.options["Threads"] = max(1, min(int(solver_cfg.get("threads", 1)), 2))
    opt.options["Presolve"] = int(solver_cfg.get("presolve", 2))
    opt.options["NumericFocus"] = int(solver_cfg.get("numeric_focus", 2))
    if solver_cfg.get("soft_mem_limit_gb") is not None:
        opt.options["SoftMemLimit"] = float(solver_cfg["soft_mem_limit_gb"])
    opt.options["OutputFlag"] = 0
    opt.options["TimeLimit"] = max(30, min(int(solver_cfg.get("time_limit_seconds", 300)), 900))
    if run_dir is not None:
        sp_dir = Path(run_dir) / "subproblems"
        sp_dir.mkdir(parents=True, exist_ok=True)
        opt.options["LogFile"] = str((sp_dir / f"type_dual_core_it{iteration:03d}_{mon}_{int(t):02d}.log").resolve()).replace("\\", "/")
    try:
        res = opt.solve(dm, tee=False, load_solutions=False)
        term = str(res.solver.termination_condition).lower()
        if "optimal" not in term:
            return None
        dm.solutions.load_from(res)
        alpha = {(int(i), str(c)): float(pyo.value(dm.alpha[i, c], exception=False) or 0.0) for i in origins for c in pubs}
        beta = {(int(j), str(c)): float(pyo.value(dm.beta[j, c], exception=False) or 0.0) for j in dests for c in pubs}
        gamma = {(int(i), int(j)): float(pyo.value(dm.gamma[i, j], exception=False) or 0.0) for (i, j) in slot_arcs}
        rhs_current = (
            sum(float(current["R"].get((i, mon, int(t), c), 0.0)) * alpha[(i, c)] for i in origins for c in pubs)
            + sum(float(current["W"].get((j, mon, int(t), c), 0.0)) * beta[(j, c)] for j in dests for c in pubs)
            + sum(float(current["G"].get((i, j, mon, int(t)), 0.0)) * gamma[(i, j)] for (i, j) in slot_arcs)
        )
        return alpha, beta, gamma, "corepoint_pareto_dual", float(rhs_current)
    except Exception:
        return None


def solve_type_assignment_lp(
    data: dict,
    solver_cfg: dict,
    mon: str,
    t: int,
    interface: dict,
    run_dir: Path | None = None,
    iteration: int = 1,
    tol: float = 1e-8,
    cut_strategy: str = "standard",
    core_interface: dict | None = None,
    pareto_tolerance: float = 1e-7,
) -> TypeAssignmentResult:
    pubs = [str(c) for c in data["PUB_TYPES"]]
    slot_arcs = [(int(i), int(j)) for (i, j, m2, t2) in data["allowed_st"] if m2 == mon and int(t2) == int(t)]
    G = {(i, j): max(0.0, float(interface["G"].get((i, j, mon, int(t)), 0.0))) for (i, j) in slot_arcs}
    if sum(G.values()) <= tol:
        return TypeAssignmentResult(mon, int(t), 0.0, float(interface["theta"].get((mon, int(t)), 0.0)), 0.0, [], {}, {}, {}, "empty", 0.0, len(slot_arcs), 0, "ok", "empty_zero_redirection")

    origins = sorted({i for i, _ in slot_arcs})
    dests = sorted({j for _, j in slot_arcs})
    R = {(i, c): max(0.0, float(interface["R"].get((i, mon, int(t), c), 0.0))) for i in origins for c in pubs}
    W = {(j, c): max(0.0, float(interface["W"].get((j, mon, int(t), c), 0.0))) for j in dests for c in pubs}
    total_g, total_r, total_w = sum(G.values()), sum(R.values()), sum(W.values())
    scale = max(1.0, total_g, total_r, total_w)
    if abs(total_g - total_r) > 1e-6 * scale or abs(total_g - total_w) > 1e-6 * scale:
        return TypeAssignmentResult(mon, int(t), float("inf"), float(interface["theta"].get((mon, int(t)), 0.0)), float("inf"), [], {}, {}, {}, "none", float("inf"), len(slot_arcs), 0, "infeasible", "aggregate_balance_mismatch")

    m = pyo.ConcreteModel()
    m.A = pyo.Set(dimen=2, initialize=slot_arcs)
    # The recourse matrix must be independent of the current RHS.  Zero R/W
    # marginals therefore remain explicit equalities; otherwise z variables of a
    # zero-valued type can carry flow without being linked to the master.
    m.O = pyo.Set(dimen=2, initialize=[(i, c) for i in origins for c in pubs])
    m.D = pyo.Set(dimen=2, initialize=[(j, c) for j in dests for c in pubs])
    m.C = pyo.Set(initialize=pubs)
    m.ZIDX = pyo.Set(dimen=4, initialize=[(i, j, co, cd) for (i, j) in slot_arcs for co in pubs for cd in pubs])
    m.z = pyo.Var(m.ZIDX, domain=pyo.NonNegativeReals)
    nd = float(data["N_MONTH"][mon])
    delta = data["delta_price"]
    m.dual = pyo.Suffix(direction=pyo.Suffix.IMPORT)

    def r_rule(mm, i, co):
        return pyo.quicksum(mm.z[i, j, co, cd] for (ii, j) in mm.A if int(ii) == int(i) for cd in mm.C) == R[(int(i), str(co))]
    def w_rule(mm, j, cd):
        return pyo.quicksum(mm.z[i, j, co, cd] for (i, jj) in mm.A if int(jj) == int(j) for co in mm.C) == W[(int(j), str(cd))]
    def g_rule(mm, i, j):
        return pyo.quicksum(mm.z[i, j, co, cd] for co in mm.C for cd in mm.C) == G[(int(i), int(j))]
    m.Rcon = pyo.Constraint(m.O, rule=r_rule)
    m.Wcon = pyo.Constraint(m.D, rule=w_rule)
    m.Gcon = pyo.Constraint(m.A, rule=g_rule)
    m.obj = pyo.Objective(expr=pyo.quicksum(nd * float(delta[(str(co), str(cd))]) * m.z[i, j, co, cd] for (i, j, co, cd) in m.ZIDX), sense=pyo.minimize)

    opt = pyo.SolverFactory(solver_cfg.get("solver", "gurobi"))
    opt.options["Threads"] = max(1, min(int(solver_cfg.get("threads", 1)), 2))
    opt.options["Presolve"] = int(solver_cfg.get("presolve", 2))
    opt.options["NumericFocus"] = int(solver_cfg.get("numeric_focus", 2))
    if solver_cfg.get("soft_mem_limit_gb") is not None:
        opt.options["SoftMemLimit"] = float(solver_cfg["soft_mem_limit_gb"])
    opt.options["Method"] = 1
    opt.options["OutputFlag"] = 0
    opt.options["TimeLimit"] = max(30, min(int(solver_cfg.get("time_limit_seconds", 300)), 900))
    if run_dir is not None:
        sp_dir = Path(run_dir) / "subproblems"
        sp_dir.mkdir(parents=True, exist_ok=True)
        opt.options["LogFile"] = str((sp_dir / f"type_lp_it{iteration:03d}_{mon}_{int(t):02d}.log").resolve()).replace("\\", "/")
    res = opt.solve(m, tee=False, load_solutions=False)
    term = str(res.solver.termination_condition).lower()
    status = str(res.solver.status).lower()
    # Dual multipliers yield a globally valid cut only after LP optimality.
    if "optimal" not in term or not getattr(res, "solution", None) or status == "error":
        return TypeAssignmentResult(mon, int(t), float("inf"), float(interface["theta"].get((mon, int(t)), 0.0)), float("inf"), [], {}, {}, {}, "none", float("inf"), len(slot_arcs), len(m.ZIDX), status, term)
    m.solutions.load_from(res)

    flows = []
    for (i, j, co, cd) in m.ZIDX:
        val = sv(m.z[i, j, co, cd])
        if val > tol:
            dp = float(delta[(str(co), str(cd))])
            flows.append({
                "from_HexID": int(i), "to_HexID": int(j), "Month": mon, "TimeIndex": int(t),
                "OriginType": str(co), "DestinationType": str(cd),
                "Energy_kWh_day": val, "Energy_kWh_annual": nd * val,
                "DeltaPrice_SEK_per_kWh": dp,
                "PriceComp_SEK_day": dp * val,
                "PriceComp_SEK_annual": nd * dp * val,
            })
    dual_R = {(int(i), str(co)): float(m.dual.get(m.Rcon[i, co], 0.0)) for (i, co) in m.O}
    dual_W = {(int(j), str(cd)): float(m.dual.get(m.Wcon[j, cd], 0.0)) for (j, cd) in m.D}
    dual_G = {(int(i), int(j)): float(m.dual.get(m.Gcon[i, j], 0.0)) for (i, j) in m.A}
    obj = sv(m.obj)
    theta = float(interface["theta"].get((mon, int(t)), 0.0))
    selection = "standard_primal_shadow_dual"
    rhs_current = obj

    if str(cut_strategy).lower() in {"corepoint", "mw", "pareto", "magnanti_wong"}:
        chosen = _select_corepoint_dual(
            data=data,
            solver_cfg=solver_cfg,
            mon=mon,
            t=int(t),
            pubs=pubs,
            slot_arcs=slot_arcs,
            current=interface,
            core_interface=core_interface,
            primal_obj=obj,
            run_dir=run_dir,
            iteration=iteration,
            pareto_tolerance=pareto_tolerance,
        )
        if chosen is not None:
            dual_R, dual_W, dual_G, selection, rhs_current = chosen
            term = term + "+corepoint"

    return TypeAssignmentResult(mon, int(t), obj, theta, max(0.0, rhs_current - theta), flows, dual_R, dual_W, dual_G, selection, float(rhs_current), len(slot_arcs), len(m.ZIDX), status, term)


def add_type_assignment_cut(model, res: TypeAssignmentResult, tol: float = 1e-9) -> int:
    mon, t = res.mon, int(res.t)
    expr = 0
    nz = 0
    # Even a tiny *negative* dual cannot be dropped: doing so raises this
    # minimum-recourse lower cut at other interfaces and can remove an exact
    # feasible solution. Retain the complete certified dual vector.
    for (i, c), v in res.dual_R.items():
        expr += v * model.R[int(i), mon, t, str(c)]; nz += int(v != 0.0)
    for (j, c), v in res.dual_W.items():
        expr += v * model.W[int(j), mon, t, str(c)]; nz += int(v != 0.0)
    for (i, j), v in res.dual_G.items():
        expr += v * model.G[int(i), int(j), mon, t]; nz += int(v != 0.0)
    model.TypeAssignmentCuts.add(model.ThetaType[mon, t] >= expr)
    return nz
