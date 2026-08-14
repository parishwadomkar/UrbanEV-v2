from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import pyomo.environ as pyo
from pyomo.opt import TerminationCondition

from decomposition_types import LPBendersCut


@dataclass
class MonthlyLPResult:
    month: str
    objective: float
    component_objectives: dict[tuple[str, int, int], float]
    cuts: list[LPBendersCut]


@dataclass
class MonthlyMIPResult:
    month: str
    objective: float
    upper_bound: float
    component_objectives: dict[tuple[str, int, int], float]
    component_upper_bounds: dict[tuple[str, int, int], float]
    revenue: float
    grid_cost: float
    slack_penalty: float
    redirection_distance_cost: float
    redirection_price_cost: float
    grid_kwh: float
    slack_kwh: float
    redirected_kwh: float
    trip_bundles: float
    service_rows: list[dict]
    slack_rows: list[dict]
    redirection_rows: list[dict]
    redirection_type_rows: list[dict]
    origin_type_rows: list[dict]
    status: str
    termination: str


def _month_structures(data: dict, month: str):
    arcs = [(int(i), int(j), int(t)) for (i, j, mon, t) in data["allowed_st"] if str(mon) == str(month)]
    out: dict[tuple[int, int], list[int]] = {}
    incoming: dict[tuple[int, int], list[int]] = {}
    for i, j, t in arcs:
        out.setdefault((i, t), []).append(j)
        incoming.setdefault((j, t), []).append(i)
    origin_st = sorted(out)
    dest_st = sorted(incoming)
    return arcs, out, incoming, origin_st, dest_st


def build_monthly_recourse_model(data: dict, cfg: dict, month: str, exact_mip: bool) -> pyo.ConcreteModel:
    arcs, out, incoming, origin_st, dest_st = _month_structures(data, month)
    model = pyo.ConcreteModel(name=f"monthly_recourse_{'MIP' if exact_mip else 'LP'}_{month}")
    model.I = pyo.Set(initialize=[int(i) for i in data["hex_ids"]], ordered=True)
    model.H = pyo.Set(initialize=[int(t) for t in data["INTERVALS"]], ordered=True)
    model.C = pyo.Set(initialize=list(data["PUB_TYPES"]), ordered=True)
    model.B = pyo.Set(initialize=list(data["DEMAND_CLASSES"]), ordered=True)
    model.A = pyo.Set(dimen=3, initialize=arcs, ordered=True)
    model.D = pyo.Set(dimen=2, initialize=data["allowed"], ordered=True)
    model.ORIGIN_ST = pyo.Set(dimen=2, initialize=origin_st, ordered=True)
    model.DEST_ST = pyo.Set(dimen=2, initialize=dest_st, ordered=True)

    model.K = pyo.Param(model.C, initialize=data["charger_capacity_pub"])
    model.Price = pyo.Param(model.C, initialize=data["charger_price"])
    model.DeltaPrice = pyo.Param(model.C, model.C, initialize=data["delta_price"], within=pyo.NonNegativeReals)
    model.Tou = pyo.Param(model.H, initialize={int(t): float(data["tou"][month][t]) for t in data["INTERVALS"]})
    model.Demand = pyo.Param(
        model.I, model.H, model.B,
        initialize={(int(i), int(t), str(b)): float(data["demand_event_annual"][(i, month, t, b)])
                    for i in data["hex_ids"] for t in data["INTERVALS"] for b in data["DEMAND_CLASSES"]},
        within=pyo.NonNegativeReals,
    )
    model.Xhat = pyo.Param(model.I, model.C, initialize=0.0, mutable=True, within=pyo.NonNegativeReals)
    model.Mredir = pyo.Param(model.I, initialize={int(i): float(data["M_REDIR"][int(i)]) for i in data["hex_ids"]})
    model.T = pyo.Param(model.D, initialize=data["T_dict"])
    model.Ndays = pyo.Param(initialize=float(data["N_MONTH"][month]))
    model.Penalty = pyo.Param(initialize=float(cfg["penalty_per_kwh_slack"]))
    model.Kappa = pyo.Param(initialize=float(cfg["x_kwh_per_trip"]))

    model.e = pyo.Var(model.I, model.H, model.C, model.B, domain=pyo.NonNegativeReals)
    model.slack = pyo.Var(model.I, model.H, model.B, domain=pyo.NonNegativeReals)
    model.z = pyo.Var(model.A, domain=pyo.NonNegativeReals)
    model.zod = pyo.Var(model.A, model.C, model.C, domain=pyo.NonNegativeReals)
    model.q = pyo.Var(model.I, model.H, model.C, domain=pyo.NonNegativeReals)
    model.y = pyo.Var(model.A, domain=pyo.Binary if exact_mip else pyo.NonNegativeReals)
    model.ntrip = pyo.Var(model.A, domain=pyo.NonNegativeIntegers if exact_mip else pyo.NonNegativeReals)
    model.tail = pyo.Var(model.A, domain=pyo.NonNegativeReals)

    model.Capacity = pyo.Constraint(
        model.I, model.H, model.C,
        rule=lambda m, i, t, c: pyo.quicksum(m.e[i, t, c, b] for b in m.B) <= m.K[c] * m.Xhat[i, c],
    )
    model.RedirAggregate = pyo.Constraint(
        model.A,
        rule=lambda m, i, j, t: m.z[i, j, t] == pyo.quicksum(m.zod[i, j, t, co, cd] for co in m.C for cd in m.C),
    )
    if not exact_mip:
        model.YUpper = pyo.Constraint(model.A, rule=lambda m, i, j, t: m.y[i, j, t] <= 1.0)
    redir_min = float(cfg["redir_min_kwh"])
    model.RedirMin = pyo.Constraint(model.A, rule=lambda m, i, j, t: m.z[i, j, t] >= redir_min * m.y[i, j, t])
    model.RedirCapInstall = pyo.Constraint(
        model.A,
        rule=lambda m, i, j, t: m.z[i, j, t] <= pyo.quicksum(m.K[c] * m.Xhat[j, c] for c in m.C),
    )
    model.RedirCapBinary = pyo.Constraint(model.A, rule=lambda m, i, j, t: m.z[i, j, t] <= m.Mredir[j] * m.y[i, j, t])

    def demand_cover(m, i, t, b):
        served = pyo.quicksum(m.e[i, t, c, b] for c in m.C)
        if str(b) == "home":
            rhs = m.Demand[i, t, "home"]
        else:
            outflow = pyo.quicksum(m.zod[i, j, t, co, cd] for j in out.get((int(i), int(t)), []) for co in m.C for cd in m.C)
            inflow = pyo.quicksum(m.zod[j, i, t, co, cd] for j in incoming.get((int(i), int(t)), []) for co in m.C for cd in m.C)
            rhs = m.Demand[i, t, "public"] - outflow + inflow
        return served + m.slack[i, t, b] == rhs

    model.DemandCover = pyo.Constraint(model.I, model.H, model.B, rule=demand_cover)
    model.OriginTypeAllocation = pyo.Constraint(
        model.I, model.H,
        rule=lambda m, i, t: pyo.quicksum(m.q[i, t, c] for c in m.C) + m.slack[i, t, "public"] == m.Demand[i, t, "public"],
    )

    def origin_consistency(m, i, t, c):
        inc = pyo.quicksum(m.zod[j, i, t, co, c] for j in incoming.get((int(i), int(t)), []) for co in m.C)
        outc = pyo.quicksum(m.zod[i, j, t, c, cd] for j in out.get((int(i), int(t)), []) for cd in m.C)
        return m.q[i, t, c] == m.e[i, t, c, "public"] - inc + outc

    model.OriginTypeConsistency = pyo.Constraint(model.I, model.H, model.C, rule=origin_consistency)
    model.OutgoingByOriginType = pyo.Constraint(
        model.ORIGIN_ST, model.C,
        rule=lambda m, i, t, co: pyo.quicksum(m.zod[i, j, t, co, cd] for j in out.get((int(i), int(t)), []) for cd in m.C) <= m.q[i, t, co],
    )
    model.TripDecomp = pyo.Constraint(model.A, rule=lambda m, i, j, t: m.z[i, j, t] == m.Kappa * m.ntrip[i, j, t] + m.tail[i, j, t])
    model.TailUpper = pyo.Constraint(model.A, rule=lambda m, i, j, t: m.tail[i, j, t] <= (m.Kappa - 1e-6) * m.y[i, j, t])
    model.OriginOutflowBound = pyo.Constraint(
        model.ORIGIN_ST,
        rule=lambda m, i, t: pyo.quicksum(m.zod[i, j, t, co, cd] for j in out.get((int(i), int(t)), []) for co in m.C for cd in m.C) <= m.Demand[i, t, "public"],
    )
    model.IncomingRedirDestinationType = pyo.Constraint(
        model.DEST_ST, model.C,
        rule=lambda m, i, t, cd: pyo.quicksum(m.zod[j, i, t, co, cd] for j in incoming.get((int(i), int(t)), []) for co in m.C) <= m.e[i, t, cd, "public"],
    )
    model.DestIncomingTypeCapacity = pyo.Constraint(
        model.DEST_ST, model.C,
        rule=lambda m, i, t, cd: pyo.quicksum(m.zod[j, i, t, co, cd] for j in incoming.get((int(i), int(t)), []) for co in m.C) <= m.K[cd] * m.Xhat[i, cd],
    )

    model.obj = pyo.Objective(
        expr=model.Ndays * (
            pyo.quicksum((model.Price[c] - model.Tou[t]) * model.e[i, t, c, b]
                         for i in model.I for t in model.H for c in model.C for b in model.B)
            - model.Penalty * pyo.quicksum(model.slack[i, t, b] for i in model.I for t in model.H for b in model.B)
            - pyo.quicksum(model.T[i, j] * model.ntrip[i, j, t] + (model.T[i, j] / model.Kappa) * model.tail[i, j, t]
                           for i, j, t in model.A)
            - pyo.quicksum(model.DeltaPrice[co, cd] * model.zod[i, j, t, co, cd]
                           for i, j, t in model.A for co in model.C for cd in model.C)
        ),
        sense=pyo.maximize,
    )
    if not exact_mip:
        model.dual = pyo.Suffix(direction=pyo.Suffix.IMPORT)
    model._month = str(month)
    model._exact_mip = bool(exact_mip)
    model._out = out
    model._incoming = incoming
    return model


def update_xhat(model: pyo.ConcreteModel, x_values: dict[tuple[int, str], int]) -> None:
    for i in model.I:
        for c in model.C:
            model.Xhat[i, c] = float(x_values[(int(i), str(c))])


def _solve(
    model, solver_name: str, threads: int, tee: bool, log_file: Path,
    mip_gap: float, time_limit: int, solver_options: dict | None = None,
):
    opt = pyo.SolverFactory(solver_name)
    base = dict(solver_options or {})
    configured = {
        "Threads": int(max(1, threads)),
        "Presolve": base.get("presolve", 2),
        "NumericFocus": base.get("numeric_focus"),
        "Heuristics": base.get("heuristics"),
        "Cuts": base.get("cuts"),
        "TimeLimit": int(time_limit),
    }
    for name, value in configured.items():
        if value is not None:
            opt.options[name] = value
    opt.options["LogFile"] = str(log_file.resolve()).replace("\\", "/")
    if model._exact_mip:
        opt.options["MIPGap"] = float(mip_gap)
        opt.options["MIPFocus"] = int(base.get("mip_focus", 1))
    else:
        opt.options["Method"] = 1
    kwargs = {"tee": tee, "load_solutions": True}
    has_start = model._exact_mip and any(
        model.e[i, t, c, b].value is not None
        for i in model.I for t in model.H for c in model.C for b in model.B
    )
    if has_start and hasattr(opt, "warm_start_capable") and opt.warm_start_capable():
        kwargs["warmstart"] = True
    results = opt.solve(model, **kwargs)
    if not model._exact_mip and results.solver.termination_condition != TerminationCondition.optimal:
        raise RuntimeError(f"Monthly recourse LP {model._month} failed: {results.solver.status}, {results.solver.termination_condition}")
    if model._exact_mip and not all(model.e[i, t, c, b].value is not None for i in model.I for t in model.H for c in model.C for b in model.B):
        raise RuntimeError(f"Monthly recourse MIP {model._month} returned no feasible incumbent: {results.solver.status}, {results.solver.termination_condition}")
    return results


def _component_objective(model, data: dict, components: dict, key: tuple[str, int, int]) -> float:
    mon, t, cid = key
    nodes = set(components["nodes"][key])
    nd = float(pyo.value(model.Ndays))
    value = sum(
        (float(pyo.value(model.Price[c])) - float(pyo.value(model.Tou[t]))) * float(pyo.value(model.e[i, t, c, b]))
        for i in nodes for c in model.C for b in model.B
    )
    value -= float(pyo.value(model.Penalty)) * sum(float(pyo.value(model.slack[i, t, b])) for i in nodes for b in model.B)
    value -= sum(
        float(pyo.value(model.T[i, j])) * float(pyo.value(model.ntrip[i, j, t]))
        + (float(pyo.value(model.T[i, j])) / float(pyo.value(model.Kappa))) * float(pyo.value(model.tail[i, j, t]))
        for i, j, tt in model.A if int(tt) == int(t) and int(i) in nodes
    )
    value -= sum(
        float(pyo.value(model.DeltaPrice[co, cd])) * float(pyo.value(model.zod[i, j, t, co, cd]))
        for i, j, tt in model.A if int(tt) == int(t) and int(i) in nodes for co in model.C for cd in model.C
    )
    return nd * value


def _global_dual_sign(model, x_values, objective: float) -> float:
    raw_constant = 0.0
    raw_coefficients: dict[tuple[int, str], float] = {
        (int(i), str(c)): 0.0 for i in model.I for c in model.C
    }

    for i in model.I:
        for t in model.H:
            for c in model.C:
                raw_coefficients[(int(i), str(c))] += (
                    float(model.dual.get(model.Capacity[i, t, c], 0.0))
                    * float(pyo.value(model.K[c]))
                )
            for b in model.B:
                raw_constant += (
                    float(model.dual.get(model.DemandCover[i, t, b], 0.0))
                    * float(pyo.value(model.Demand[i, t, b]))
                )
            raw_constant += (
                float(model.dual.get(model.OriginTypeAllocation[i, t], 0.0))
                * float(pyo.value(model.Demand[i, t, "public"]))
            )

    for i, j, t in model.A:
        if hasattr(model, "YUpper"):
            raw_constant += float(model.dual.get(model.YUpper[i, j, t], 0.0))
        dual = float(model.dual.get(model.RedirCapInstall[i, j, t], 0.0))
        for c in model.C:
            raw_coefficients[(int(j), str(c))] += dual * float(pyo.value(model.K[c]))

    for i, t in model.ORIGIN_ST:
        raw_constant += (
            float(model.dual.get(model.OriginOutflowBound[i, t], 0.0))
            * float(pyo.value(model.Demand[i, t, "public"]))
        )

    for i, t in model.DEST_ST:
        for c in model.C:
            raw_coefficients[(int(i), str(c))] += (
                float(model.dual.get(model.DestIncomingTypeCapacity[i, t, c], 0.0))
                * float(pyo.value(model.K[c]))
            )

    raw_rhs = raw_constant + sum(
        raw_coefficients[key] * float(x_values[key]) for key in raw_coefficients
    )
    flipped_rhs = -raw_rhs
    sign = 1.0 if abs(raw_rhs - objective) <= abs(flipped_rhs - objective) else -1.0
    reconstructed = sign * raw_rhs
    tolerance = 1e-5 * max(1.0, abs(objective))
    if abs(reconstructed - objective) > tolerance:
        raise RuntimeError(
            f"Monthly recourse dual reconstruction failed for {model._month}: "
            f"objective={objective:.9f}, dual_rhs={reconstructed:.9f}, "
            f"residual={reconstructed - objective:.9f}."
        )
    return sign


def _component_cut(model, data: dict, components: dict, key: tuple[str, int, int], x_values, iteration: int, value: float, dual_sign: float, source_kind: str = "incumbent") -> LPBendersCut:
    mon, t, cid = key
    nodes = set(components["nodes"][key])
    raw_constant = 0.0
    raw: dict[tuple[int, str], float] = {(int(i), str(c)): 0.0 for i in nodes for c in model.C}

    for i in nodes:
        for c in model.C:
            raw[(int(i), str(c))] += (
                float(model.dual.get(model.Capacity[i, t, c], 0.0))
                * float(pyo.value(model.K[c]))
            )
        for b in model.B:
            raw_constant += (
                float(model.dual.get(model.DemandCover[i, t, b], 0.0))
                * float(pyo.value(model.Demand[i, t, b]))
            )
        raw_constant += (
            float(model.dual.get(model.OriginTypeAllocation[i, t], 0.0))
            * float(pyo.value(model.Demand[i, t, "public"]))
        )
        if (int(i), int(t)) in model.ORIGIN_ST:
            raw_constant += (
                float(model.dual.get(model.OriginOutflowBound[i, t], 0.0))
                * float(pyo.value(model.Demand[i, t, "public"]))
            )

    for i, j, tt in model.A:
        if int(tt) != int(t) or int(i) not in nodes:
            continue
        if hasattr(model, "YUpper"):
            raw_constant += float(model.dual.get(model.YUpper[i, j, t], 0.0))
        dual = float(model.dual.get(model.RedirCapInstall[i, j, t], 0.0))
        for c in model.C:
            raw[(int(j), str(c))] = raw.get((int(j), str(c)), 0.0) + dual * float(pyo.value(model.K[c]))

    for i, tt in model.DEST_ST:
        if int(tt) != int(t) or int(i) not in nodes:
            continue
        for c in model.C:
            raw[(int(i), str(c))] += (
                float(model.dual.get(model.DestIncomingTypeCapacity[i, t, c], 0.0))
                * float(pyo.value(model.K[c]))
            )

    constant = float(dual_sign) * raw_constant
    coefficients = {k: float(dual_sign) * float(v) for k, v in raw.items()}
    tolerance = 1e-6 * max(1.0, max((abs(v) for v in coefficients.values()), default=1.0))
    minimum = min(coefficients.values(), default=0.0)
    if minimum < -tolerance:
        raise RuntimeError(
            f"Monthly recourse capacity supergradient has a negative coefficient for "
            f"{mon}, slot {t}, component {cid}: minimum={minimum:.9f}."
        )
    coefficients = {
        k: (0.0 if -tolerance <= v < 0.0 else v)
        for k, v in coefficients.items()
        if abs(v) > 1e-10
    }
    rhs_at_incumbent = constant + sum(
        float(coefficients.get(k, 0.0)) * float(x_values[k]) for k in x_values
    )
    check_tol = 1e-5 * max(1.0, abs(value))
    if abs(rhs_at_incumbent - value) > check_tol:
        raise RuntimeError(
            f"Monthly recourse component dual reconstruction failed for {mon}, slot {t}, "
            f"component {cid}: objective={value:.9f}, dual_rhs={rhs_at_incumbent:.9f}."
        )
    return LPBendersCut(
        str(mon), int(t), int(cid), float(constant), coefficients,
        int(iteration), float(value), str(source_kind)
    )

def solve_monthly_recourse_lp(
    model, data: dict, components: dict, x_values, iteration: int, solver_name: str,
    threads: int, tee: bool, log_dir: Path, source_kind: str = "incumbent",
    time_limit: int = 3600, solver_options: dict | None = None,
) -> MonthlyLPResult:
    update_xhat(model, x_values)
    log_dir.mkdir(parents=True, exist_ok=True)
    safe_kind = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(source_kind))
    _solve(
        model, solver_name, threads, tee,
        log_dir / f"lp_{iteration:03d}_{safe_kind}_{model._month}.log",
        0.0, int(time_limit), solver_options=solver_options,
    )
    objective = float(pyo.value(model.obj))
    keys = [k for k in components["keys"] if str(k[0]) == str(model._month)]
    component_values = {k: _component_objective(model, data, components, k) for k in keys}
    if abs(sum(component_values.values()) - objective) > 1e-6 * max(1.0, abs(objective)):
        raise RuntimeError(f"Monthly recourse component objective decomposition failed for {model._month}.")
    dual_sign = _global_dual_sign(model, x_values, objective)
    cuts = [
        _component_cut(
            model, data, components, k, x_values, iteration,
            component_values[k], dual_sign, source_kind
        )
        for k in keys
    ]
    return MonthlyLPResult(str(model._month), objective, component_values, cuts)


def _finite_upper_bound(results, incumbent: float, lp_upper: float) -> float:
    value = getattr(results.problem, "upper_bound", None)
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = math.nan
    if not math.isfinite(value):
        value = float(lp_upper)
    value = max(float(incumbent), float(value))
    return min(float(lp_upper), value)


def solve_monthly_recourse_mip(
    model, data: dict, cfg: dict, components: dict, x_values, solver_name: str,
    threads: int, tee: bool, log_dir: Path, iteration: int, mip_gap: float,
    time_limit: int, lp_upper: float, source_kind: str = "incumbent",
    solver_options: dict | None = None,
) -> MonthlyMIPResult:
    update_xhat(model, x_values)
    log_dir.mkdir(parents=True, exist_ok=True)
    safe_kind = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(source_kind))
    results = _solve(
        model, solver_name, threads, tee,
        log_dir / f"mip_{iteration:03d}_{safe_kind}_{model._month}.log",
        mip_gap, time_limit, solver_options=solver_options,
    )
    objective = float(pyo.value(model.obj))
    upper = _finite_upper_bound(results, objective, lp_upper)
    keys = [k for k in components["keys"] if str(k[0]) == str(model._month)]
    component_objectives = {k: _component_objective(model, data, components, k) for k in keys}
    if abs(sum(component_objectives.values()) - objective) > 1e-6 * max(1.0, abs(objective)):
        raise RuntimeError(f"Monthly recourse MIP component objective decomposition failed for {model._month}.")
    residual_gap = max(0.0, float(upper) - float(objective))
    # Since the monthly model is a sum of independent component-slot MIPs, the
    # total remaining optimality gap bounds the gap of every individual block.
    component_upper_bounds = {k: float(v) + residual_gap for k, v in component_objectives.items()}
    nd = float(pyo.value(model.Ndays))
    penalty = float(pyo.value(model.Penalty))
    revenue = nd * sum(float(pyo.value(model.Price[c])) * float(pyo.value(model.e[i, t, c, b])) for i in model.I for t in model.H for c in model.C for b in model.B)
    grid_cost = nd * sum(float(pyo.value(model.Tou[t])) * float(pyo.value(model.e[i, t, c, b])) for i in model.I for t in model.H for c in model.C for b in model.B)
    slack_kwh = nd * sum(float(pyo.value(model.slack[i, t, b])) for i in model.I for t in model.H for b in model.B)
    slack_penalty = penalty * slack_kwh
    distance_cost = nd * sum(float(pyo.value(model.T[i, j])) * float(pyo.value(model.ntrip[i, j, t])) + (float(pyo.value(model.T[i, j])) / float(pyo.value(model.Kappa))) * float(pyo.value(model.tail[i, j, t])) for i, j, t in model.A)
    price_cost = nd * sum(float(pyo.value(model.DeltaPrice[co, cd])) * float(pyo.value(model.zod[i, j, t, co, cd])) for i, j, t in model.A for co in model.C for cd in model.C)
    reconstructed = revenue - grid_cost - slack_penalty - distance_cost - price_cost
    if abs(reconstructed - objective) > 1e-6 * max(1.0, abs(objective)):
        raise RuntimeError(f"Monthly recourse MIP objective reconstruction failed for {model._month}: {objective} vs {reconstructed}")
    grid_kwh = nd * sum(float(pyo.value(model.e[i, t, c, b])) for i in model.I for t in model.H for c in model.C for b in model.B)
    redirected = nd * sum(float(pyo.value(model.z[i, j, t])) for i, j, t in model.A)
    trip_bundles = nd * sum(float(pyo.value(model.ntrip[i, j, t])) for i, j, t in model.A)

    service_rows=[]; slack_rows=[]; redir_rows=[]; redir_type_rows=[]; q_rows=[]
    for i in model.I:
        for t in model.H:
            for c in model.C:
                qv=float(pyo.value(model.q[i,t,c])); q_rows.append({"HexID":int(i),"Month":model._month,"TimeIndex":int(t),"OriginType":str(c),"q_origin_baseline_kWh_day":qv,"q_origin_baseline_kWh_annual":nd*qv})
                for b in model.B:
                    v=float(pyo.value(model.e[i,t,c,b])); service_rows.append({"HexID":int(i),"Month":model._month,"TimeIndex":int(t),"ChargerType":str(c),"DemandClass":str(b),"Energy_kWh_day":v,"Energy_kWh_annual":nd*v})
            for b in model.B:
                v=float(pyo.value(model.slack[i,t,b]));
                if v>1e-9: slack_rows.append({"HexID":int(i),"Month":model._month,"TimeIndex":int(t),"DemandClass":str(b),"Slack_kWh_day":v,"Slack_kWh_annual":nd*v})
    for i,j,t in model.A:
        z=float(pyo.value(model.z[i,j,t]));
        if z>1e-9:
            redir_rows.append({"from_HexID":int(i),"to_HexID":int(j),"Month":model._month,"TimeIndex":int(t),"Distance_km":data["dist_dict"].get((int(i),int(j))),"Energy_kWh_day":z,"Energy_kWh_annual":nd*z,"Yarc":float(pyo.value(model.y[i,j,t])),"Trips":float(pyo.value(model.ntrip[i,j,t])),"Tail_kWh":float(pyo.value(model.tail[i,j,t]))})
        for co in model.C:
            for cd in model.C:
                v=float(pyo.value(model.zod[i,j,t,co,cd]));
                if v>1e-9:
                    dp=float(pyo.value(model.DeltaPrice[co,cd])); redir_type_rows.append({"from_HexID":int(i),"to_HexID":int(j),"Month":model._month,"TimeIndex":int(t),"OriginType":str(co),"DestinationType":str(cd),"Energy_kWh_day":v,"Energy_kWh_annual":nd*v,"DeltaPrice_SEK_per_kWh":dp,"PriceComp_SEK_day":dp*v,"PriceComp_SEK_annual":nd*dp*v})
    return MonthlyMIPResult(
        str(model._month), objective, upper, component_objectives,
        component_upper_bounds, revenue, grid_cost, slack_penalty,
        distance_cost, price_cost, grid_kwh, slack_kwh, redirected,
        trip_bundles, service_rows, slack_rows, redir_rows,
        redir_type_rows, q_rows, str(results.solver.status),
        str(results.solver.termination_condition)
    )
