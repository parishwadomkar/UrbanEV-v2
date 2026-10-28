from __future__ import annotations

import gc
import math
import time

import pandas as pd
import pyomo.environ as pyo

from model_builder import apply_hard_no_slack, build_model
from solve_model import solve_model, solver_certificate
from technology_switches import apply_technology_switches


def add_spatial_arguments(parser):
    parser.add_argument("--regularize-infrastructure", action="store_true")
    parser.add_argument("--regularization-profit-tolerance", type=float, default=1.0)
    parser.add_argument("--regularization-time-limit", type=int, default=120)
    parser.add_argument("--spatial-site-time-limit", type=int, default=300)


def site_data(data, site):
    if data.get("allowed_st"):
        raise ValueError("Independent-site optimization requires an empty redirection network.")
    i = int(site)
    result = dict(data)
    result["hex_ids"] = [i]
    for key in ("cl", "home_avail", "pv_upper", "M_BATT", "M_REDIR"):
        result[key] = {i: data[key][i]}
    result["demand_event_annual"] = {
        (i, mon, t, b): data["demand_event_annual"][(i, mon, t, b)]
        for mon in data["MONTHS"] for t in data["INTERVALS"] for b in data["DEMAND_CLASSES"]
    }
    result["demand_event"] = result["demand_event_annual"]
    for key in ("home_demand_total_event", "home_private_served_event"):
        result[key] = {
            (i, mon, t): data.get(key, {}).get((i, mon, t), 0.0)
            for mon in data["MONTHS"] for t in data["INTERVALS"]
        }
    for key in ("allowed", "allowed_st", "ORIGIN_ST", "DEST_ST"):
        result[key] = []
    for key in ("OUT", "IN", "dist_dict", "T_dict"):
        result[key] = {}
    return result


def copy_site_solution(source, destination, site):
    i = int(site)
    for component in source.component_objects(pyo.Var, active=True):
        target = destination.find_component(component.local_name)
        indexes = component if len(component) <= len(target) else target
        for index in indexes:
            variable = component[index]
            first = index[0] if isinstance(index, tuple) else index
            if first == i:
                value = variable.value
                target[index].set_value(0.0 if value is None else float(value))


def _snapshot(model):
    return [(v, v.value) for v in model.component_data_objects(pyo.Var)]


def _restore(snapshot):
    for variable, value in snapshot:
        variable.set_value(value)


def _profit(model):
    return float(pyo.value(model.obj))


def _capex(model, data):
    return float(data["DAYS"]) * (
        pyo.quicksum(model.PVF_cost[c] * model.x[i, c] for i in model.I for c in model.C_pub)
        + pyo.quicksum(model.PVF_PV * model.PV[i] + model.PVF_Batt * model.Batt[i] for i in model.I)
    )


def _site_solver_config(base, args, name, gap, limit):
    config = dict(base)
    config.update(
        threads=int(getattr(args, "subproblem_threads", None) or args.threads or 2),
        time_limit_seconds=max(1, int(limit)), mip_gap=float(gap),
        soft_mem_limit_gb=args.soft_mem_limit_gb,
        nodefile_start_gb=float(args.nodefile_start or 0.5),
        method=1, node_method=1, pre_sparsify=1,
        no_rel_heur_time=None, log_name=name,
        nodefile_dir=str(getattr(args, "nodefile_dir", None) or "" ) or None,
    )
    config["extra_options"] = {"Seed": 0, "MIPGapAbs": 1e-7}
    config["tee"] = False
    return config


def regularize_site(model, data, args, run_dir, solver_cfg, floor, limit, solve_fn=solve_model):
    before = _snapshot(model)
    before_profit = _profit(model)
    before_cost = float(pyo.value(_capex(model, data)))
    model.ProfitFloor = pyo.Constraint(expr=model.obj.expr >= floor)
    model.obj.deactivate()
    model.InfrastructureCost = pyo.Objective(expr=_capex(model, data), sense=pyo.minimize)
    try:
        result = solve_fn(model, solver_cfg, run_dir)
        loaded = bool(getattr(model, "_last_solve_loaded_incumbent", False))
        after_profit = float(pyo.value(model.obj.expr)) if loaded else -math.inf
        after_cost = float(pyo.value(model.InfrastructureCost)) if loaded else math.inf
        valid = loaded and after_profit >= floor - 1e-5 and after_cost <= before_cost + 1e-5
        if not valid:
            _restore(before)
        return {
            "regularization_termination": str(result.solver.termination_condition),
            "regularization_accepted": bool(valid),
            "regularization_profit_change_SEK": (_profit(model) - before_profit),
            "regularization_capex_change_SEK": float(pyo.value(_capex(model, data))) - before_cost,
        }
    finally:
        model.del_component(model.InfrastructureCost)
        model.del_component(model.ProfitFloor)
        model.obj.activate()


def solve_spatial_exact(data, cfg, args, run_dir, solver_cfg, *, assembled_model=None,
                        prior_certificate=None, budget=None, solve_fn=solve_model):
    if getattr(args, "scenario", "no_redirection") != "no_redirection" or data.get("allowed_st"):
        raise ValueError("Exact independent-site decomposition is valid only without spatial redirection.")
    tolerance = float(args.regularization_profit_tolerance)
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("regularization-profit-tolerance must be finite and nonnegative.")
    if min(int(args.spatial_site_time_limit), int(args.regularization_time_limit)) <= 0:
        raise ValueError("Per-site time limits must be positive.")
    started = time.perf_counter()
    budget = float(budget if budget is not None else args.time_limit)
    if not math.isfinite(budget) or budget <= 0:
        raise ValueError("The spatial solve budget must be positive and finite.")
    target_value = getattr(args, "lbbd_gap", None)
    if target_value is None:
        target_value = getattr(args, "mip_gap", None)
    target = float(1e-5 if target_value is None else target_value)
    regularize = bool(args.regularize_infrastructure)
    local_gap = min(target, 1e-9 if regularize else 1e-7)
    sites = sorted(int(i) for i in data["hex_ids"])
    had_incumbent = assembled_model is not None
    model = assembled_model if had_incumbent else build_model(data, cfg)
    apply_technology_switches(model, bool(args.disable_pv), bool(args.disable_bess), verbose=False)
    if getattr(args, "hard_no_slack", False):
        apply_hard_no_slack(model)
    rows = []
    bounds = []
    complete = True
    site_tolerance = tolerance / max(1, len(sites))
    print(f"Exact independent-site annual MILPs: {len(sites)} sites; all seasonal and battery links retained.")
    print("No Benders iterations are needed because there are no constraints coupling different sites.")
    for position, site in enumerate(sites, 1):
        remaining = budget - (time.perf_counter() - started)
        if remaining < 1:
            complete = False
            print("Spatial time budget reached; the run is not certified complete.")
            break
        local_data = site_data(data, site)
        local = build_model(local_data, cfg)
        apply_technology_switches(local, bool(args.disable_pv), bool(args.disable_bess), verbose=False)
        if getattr(args, "hard_no_slack", False):
            for variable in local.slack.values():
                variable.fix(0.0)
        reference = -math.inf
        if had_incumbent:
            copy_site_solution(model, local, site)
            reference = _profit(local)
        name = f"spatial_hex_{site}_primary.log"
        options = _site_solver_config(solver_cfg, args, name, local_gap,
                                      min(int(args.spatial_site_time_limit), remaining))
        tick = time.perf_counter()
        result = solve_fn(local, options, run_dir)
        certificate = solver_certificate(result, local, run_dir / "logs" / name)
        row = {"HexID": site, "site_position": position,
               "termination": certificate["termination_reason"],
               "primary_solve_seconds": time.perf_counter() - tick,
               "primary_gap": certificate["gurobi_mip_gap"],
               "upper_bound_SEK": certificate["valid_bound_SEK"]}
        if not certificate["has_loaded_incumbent"]:
            row["status"] = "no_new_incumbent"
            rows.append(row)
            complete = False
            if not had_incumbent:
                print(f"No feasible solution at hex {site}; aggregate results will not be exported.")
                break
            continue
        if had_incumbent and _profit(local) < reference:
            copy_site_solution(model, local, site)
        primary = _profit(local)
        row["primary_profit_SEK"] = primary
        bound = certificate["valid_bound_SEK"]
        bounds.append(float(bound) if bound is not None else math.inf)
        remaining = budget - (time.perf_counter() - started)
        if regularize and remaining >= 1:
            secondary_name = f"spatial_hex_{site}_regularization.log"
            secondary_options = _site_solver_config(
                solver_cfg, args, secondary_name, 0.0,
                min(int(args.regularization_time_limit), remaining),
            )
            tick = time.perf_counter()
            row.update(regularize_site(local, local_data, args, run_dir, secondary_options,
                                       primary - site_tolerance, remaining, solve_fn))
            row["regularization_seconds"] = time.perf_counter() - tick
        copy_site_solution(local, model, site)
        row.update(status="solved", profit_SEK=_profit(local),
                   annualized_asset_cost_SEK=float(pyo.value(_capex(local, local_data))),
                   PV=int(round(pyo.value(local.PV[site]))),
                   BESS=int(round(pyo.value(local.Batt[site]))))
        for charger in data["PUB_TYPES"]:
            row[charger] = int(round(pyo.value(local.x[site, charger])))
        row["elapsed_seconds"] = time.perf_counter() - started
        rows.append(row)
        if position == 1 or position % 20 == 0 or position == len(sites):
            print(f"Sites completed {position}/{len(sites)}; elapsed {row['elapsed_seconds']:.1f} s")
        del local, result
        if position % 25 == 0:
            gc.collect()
    results_dir = run_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(results_dir / "spatial_decomposition_history.csv", index=False)
    complete = complete and len(rows) == len(sites)
    usable = complete or had_incumbent
    objective = _profit(model) if usable else None
    upper = sum(bounds) if complete and len(bounds) == len(sites) else math.inf
    bound_source = "sum_of_independent_annual_site_MIP_bounds"
    if prior_certificate and prior_certificate.get("valid_bound_SEK") is not None:
        prior_bound = float(prior_certificate["valid_bound_SEK"])
        if prior_bound < upper:
            bound_source = "prior_monolithic_MIP_bound"
        upper = min(upper, prior_bound)
    if objective is not None and math.isfinite(upper):
        upper = max(upper, objective)
        gap = max(0.0, upper - objective) / max(1.0, abs(objective))
    else:
        gap = None
    converged = usable and gap is not None and gap <= target + 1e-10
    certificate = {
        "termination_reason": "gap_converged" if converged else "spatial_limit_or_uncertified",
        "pyomo_termination": "optimal" if converged else "other",
        "pyomo_status": "ok" if usable else "warning",
        "has_loaded_incumbent": usable, "objective_SEK": objective,
        "valid_bound_SEK": upper if math.isfinite(upper) else None,
        "gurobi_mip_gap": gap, "requested_mip_gap": target,
        "bound_source": bound_source,
        "sites_completed": sum(row.get("status") == "solved" for row in rows),
        "sites_total": len(sites), "spatial_solve_complete": complete,
        "regularization_enabled": regularize,
        "regularization_profit_tolerance_SEK": tolerance if regularize else 0.0,
        "regularization_secondary_objective": "minimum_annualized_asset_cost" if regularize else None,
        "regularization_sites_accepted": sum(bool(row.get("regularization_accepted")) for row in rows),
    }
    metadata = {
        "architecture": "exact_independent_site_annual_MILPs",
        "termination": "certified_gap" if converged else "spatial_limit_or_uncertified",
        "best_lb_SEK": objective, "global_ub_SEK": certificate["valid_bound_SEK"],
        "certified_gap": gap, "elapsed_seconds": time.perf_counter() - started,
        "benders_iterations": 0, "solver_certificate": certificate,
    }
    return model if usable else None, certificate, metadata
