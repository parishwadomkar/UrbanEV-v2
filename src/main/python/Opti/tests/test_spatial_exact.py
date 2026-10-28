from __future__ import annotations

import sys
from argparse import Namespace
from pathlib import Path

import pandas as pd
import pytest
import pyomo.environ as pyo

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from model_builder import build_model
from solve_model import solver_certificate
from spatial_exact import solve_spatial_exact


def synthetic_problem():
    months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    days = dict(zip(months, [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]))
    types = ["slow", "medium", "fast"]
    cfg = dict(x_kwh_per_trip=20.0, battery_cell_cap_kwh=10.0,
               eta_charge=0.95, eta_discharge=0.95, rho_half_hours_per_hour=2,
               initial_soc_fraction=0.1, soc_min_fraction=0.1, soc_max_fraction=0.9,
               redir_min_kwh=0.1, battery_max_units_per_hex=2,
               penalty_per_kwh_slack=18500.0, bess_boundary="legacy_linked_months")
    demand = {(i, m, t, b): (1.0 + (j % 4) / 10) * (i + t + (2 if b == "public" else 0))
              for i in [1, 2] for j, m in enumerate(months) for t in [1, 2, 3] for b in ["home", "public"]}
    data = dict(hex_ids=[1, 2], MONTHS=months, N_MONTH=days, DAYS=365,
                INTERVALS=[1, 2, 3], HSOC=[0, 1, 2, 3], time_indices=[1, 2, 3],
                PUB_TYPES=types, DEMAND_CLASSES=["home", "public"],
                allowed=[], allowed_st=[], ORIGIN_ST=[], DEST_ST=[], OUT={}, IN={}, T_dict={}, dist_dict={},
                charger_price=dict(zip(types, [5.5, 6.0, 6.5])),
                delta_price={(a, b): max(0, [5.5, 6.0, 6.5][types.index(b)] - [5.5, 6.0, 6.5][types.index(a)]) for a in types for b in types},
                demand_event_annual=demand, demand_event=demand,
                charger_capacity_pub=dict(zip(types, [5.5, 11.0, 25.0])),
                charger_resources=dict(zip(types, [1, 5, 150])),
                daily_cost=dict(slow=0.01, medium=0.04, fast=0.2, PV=0.001, Batt=0.003),
                cl={1: 25.0, 2: 180.0}, pv_upper={1: 4, 2: 4},
                pv_kwh_per_panel_slot_at_cf1=0.25, K_BATT=2.5,
                M_BATT={1: 5.0, 2: 5.0}, M_REDIR={1: 137.5, 2: 990.0},
                prev_month={m: months[j - 1] for j, m in enumerate(months)},
                tou={m: {1: -0.3, 2: 3.0, 3: 1.8} for m in months},
                pv_cf={m: {1: 0, 2: 0.8, 3: 0} for m in months},
                eligible={"home": types[:], "public": types[:]}, home_avail={1: 1, 2: 1},
                home_demand_total_event={(i, m, t): demand[i, m, t, "home"] for i in [1, 2] for m in months for t in [1, 2, 3]},
                home_private_served_event={})
    return data, cfg


def settings(regularize=False):
    return Namespace(scenario="no_redirection", threads=1, subproblem_threads=1,
                     soft_mem_limit_gb=55, nodefile_start=0.5, nodefile_dir=None,
                     disable_pv=False, disable_bess=False, hard_no_slack=True,
                     time_limit=90, mip_gap=1e-5, lbbd_gap=1e-5,
                     regularize_infrastructure=regularize, regularization_profit_tolerance=0.01,
                     regularization_time_limit=20, spatial_site_time_limit=20)


def highs_solve(model, config, run_dir):
    solver = pyo.SolverFactory("highs")
    solver.options.update({"mip_rel_gap": config.get("mip_gap", 1e-9),
                           "mip_abs_gap": 1e-8, "time_limit": config.get("time_limit_seconds", 30)})
    result = solver.solve(model)
    model._last_solve_loaded_incumbent = True
    return result


def assert_feasible(model):
    for constraint in model.component_data_objects(pyo.Constraint, active=True):
        value = pyo.value(constraint.body)
        if constraint.has_lb():
            assert value >= pyo.value(constraint.lower) - 2e-5, constraint.name
        if constraint.has_ub():
            assert value <= pyo.value(constraint.upper) + 2e-5, constraint.name
    for variable in model.component_data_objects(pyo.Var):
        if variable.is_integer() and variable.value is not None:
            assert abs(variable.value - round(variable.value)) <= 1e-6


@pytest.mark.parametrize("regularize", [False, True])
def test_exact_spatial_matches_the_same_annual_monolithic_milp(tmp_path, regularize):
    data, cfg = synthetic_problem()
    global_model = build_model(data, cfg)
    for variable in global_model.slack.values():
        variable.fix(0)
    highs_solve(global_model, {"mip_gap": 1e-9}, tmp_path)
    reference = pyo.value(global_model.obj)
    model, certificate, metadata = solve_spatial_exact(
        data, cfg, settings(regularize), tmp_path, {}, solve_fn=highs_solve)
    assert model is not None
    assert_feasible(model)
    assert abs(pyo.value(model.obj) - reference) <= (0.0101 if regularize else 1e-5)
    assert certificate["valid_bound_SEK"] >= reference - 1e-5
    assert certificate["gurobi_mip_gap"] <= certificate["requested_mip_gap"]
    assert metadata["termination"] == "certified_gap"
    assert metadata["benders_iterations"] == 0
    history = pd.read_csv(tmp_path / "results" / "spatial_decomposition_history.csv")
    if regularize:
        assert (history["regularization_capex_change_SEK"] <= 1e-5).all()
    assert sum(pyo.value(v) for v in model.slack.values()) == 0


def test_monolithic_and_spatial_share_the_same_regularization(tmp_path):
    data, cfg = synthetic_problem()
    original = build_model(data, cfg)
    for variable in original.slack.values():
        variable.fix(0)
    result = highs_solve(original, {"mip_gap": 1e-9}, tmp_path)
    prior = solver_certificate(result, original, tmp_path / "absent.log")
    mono, _, _ = solve_spatial_exact(data, cfg, settings(True), tmp_path / "mono", {},
                                    assembled_model=original, prior_certificate=prior, solve_fn=highs_solve)
    spatial, _, _ = solve_spatial_exact(data, cfg, settings(True), tmp_path / "spatial", {}, solve_fn=highs_solve)
    assert_feasible(mono)
    assert_feasible(spatial)
    assert abs(pyo.value(mono.obj) - pyo.value(spatial.obj)) < 1e-5
    for key in mono.x:
        assert abs(pyo.value(mono.x[key]) - pyo.value(spatial.x[key])) < 1e-6


def test_spatial_decomposition_rejects_coupled_redirection(tmp_path):
    data, cfg = synthetic_problem()
    data["allowed_st"] = [(1, 2, "January", 1)]
    with pytest.raises(ValueError, match="only without spatial redirection"):
        solve_spatial_exact(data, cfg, settings(), tmp_path, {}, solve_fn=highs_solve)


def test_unfinished_sites_do_not_produce_an_aggregate_incumbent(tmp_path):
    from pyomo.opt import SolverResults, SolverStatus, TerminationCondition

    def stopped(model, config, run_dir):
        result = SolverResults()
        result.solver.status = SolverStatus.aborted
        result.solver.termination_condition = TerminationCondition.maxTimeLimit
        model._last_solve_loaded_incumbent = False
        return result

    data, cfg = synthetic_problem()
    model, certificate, metadata = solve_spatial_exact(data, cfg, settings(), tmp_path, {}, solve_fn=stopped)
    assert model is None
    assert certificate["objective_SEK"] is None
    assert not certificate["has_loaded_incumbent"]
    assert metadata["termination"] != "certified_gap"
