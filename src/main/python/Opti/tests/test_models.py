import math

import pyomo.environ as pyo
import pytest

from model_builder import build_model, apply_scenario
from technology_switches import apply_technology_switches
from input_validation import disable_redirection
from src_benders.benders_master import build_benders_master
from src_lbbd.lbbd_master import build_lbbd_master, build_global_components, add_annual_lp_cut, AnnualLPDualCut
from src_lbbd.decomposition_types import build_slot_components
from src_lbbd.run_lbbd import _has_loaded_objective, _round_master_relaxation_investment, _fix_investments


def solve(model):
    from pyomo.contrib.appsi.solvers import Highs
    from pyomo.contrib.appsi.base import TerminationCondition
    solver = Highs()
    if not solver.available():
        pytest.skip("Optional HiGHS validation dependency is unavailable")
    result = solver.solve(model)
    assert result.termination_condition == TerminationCondition.optimal
    return next(pyo.value(obj) for obj in model.component_data_objects(pyo.Objective, active=True))


@pytest.mark.parametrize("boundary", ["legacy_linked_months", "cyclic_day"])
@pytest.mark.parametrize("pv,bess", [(False,False),(True,False),(False,True),(True,True)])
def test_no_redirection_formulation_equivalence(tiny,cfg,boundary,pv,bess):
    cfg["bess_boundary"] = boundary
    tiny.update(disable_pv=not pv, disable_bess=not bess)
    disable_redirection(tiny)
    mono = build_model(tiny,cfg)
    apply_technology_switches(mono,not pv,not bess,verbose=False)
    reference = solve(mono)
    witness = build_benders_master(tiny,cfg,scenario="no_redirection")
    apply_technology_switches(witness,not pv,not bess,verbose=False)
    assert solve(witness) == pytest.approx(reference,abs=0.01)
    master = build_lbbd_master(tiny,cfg,build_slot_components(tiny),build_global_components(tiny))
    upper = solve(master)
    assert upper + 0.01 >= reference
    assert _has_loaded_objective(master)
    assert _has_loaded_objective(mono)
    inv = _round_master_relaxation_investment(master)
    exact = build_model(tiny,cfg)
    apply_technology_switches(exact,not pv,not bess,verbose=False)
    _fix_investments(exact,inv)
    assert solve(exact) <= reference + 0.01
    if boundary == "cyclic_day":
        for i in exact.I:
            for month in exact.M:
                assert pyo.value(exact.soc[i,month,0]) == pytest.approx(pyo.value(exact.soc[i,month,2]))


def test_removing_redirection_variables_preserves_solution(tiny,cfg):
    cfg["battery_max_units_per_hex"] = 0
    old = build_model(tiny,cfg)
    apply_scenario(old,"no_redirection")
    reference = solve(old)
    disable_redirection(tiny)
    sparse = build_model(tiny,cfg)
    assert solve(sparse) == pytest.approx(reference,abs=0.01)
    assert len(sparse.A) == 0


def test_redirection_relaxation_is_upper_bound(tiny,cfg):
    tiny.update(disable_pv=True, disable_bess=True)
    original = build_model(tiny,cfg)
    apply_technology_switches(original,True,True,verbose=False)
    lower = solve(original)
    master = build_lbbd_master(tiny,cfg,build_slot_components(tiny),build_global_components(tiny))
    assert solve(master) + 0.01 >= lower


def test_exact_cut_rejects_nonfinite(tiny,cfg):
    from src_lbbd.lbbd_master import add_exact_config_cut, ExactConfigCut, InvestmentPoint
    master = build_lbbd_master(tiny,cfg,build_slot_components(tiny),build_global_components(tiny))
    inv = InvestmentPoint(x={(i,c):0 for i in tiny['hex_ids'] for c in tiny['PUB_TYPES']},pv={i:0 for i in tiny['hex_ids']},batt={i:0 for i in tiny['hex_ids']})
    with pytest.raises(ValueError,match="finite"):
        add_exact_config_cut(master,ExactConfigCut(cut_id=1,investment=inv,upper_bound=math.inf,objective=0,gap=math.inf))


def test_small_positive_cut_coefficient_is_retained(tiny, cfg):
    from pyomo.repn import generate_standard_repn
    master = build_lbbd_master(tiny,cfg,build_slot_components(tiny),build_global_components(tiny))
    cut = AnnualLPDualCut(1, 1000, {(1, "slow"): 1e-12}, {}, {}, 1000)
    assert add_annual_lp_cut(master, cut)
    expression = generate_standard_repn(master.AnnualLPCuts[1].body)
    coefficients = {var.name: coefficient for var, coefficient in zip(expression.linear_vars, expression.linear_coefs)}
    assert coefficients[master.x[1,"slow"].name] == -1e-12
    with pytest.raises(ValueError, match="finite"):
        add_annual_lp_cut(master, AnnualLPDualCut(2, math.nan, {}, {}, {}, 1000))


def test_forced_battery_and_solar_energy_accounting(tiny, cfg):
    from energy_accounting import energy_boundary_metrics
    cfg["bess_boundary"] = "cyclic_day"
    disable_redirection(tiny)
    for mon in tiny["MONTHS"]:
        tiny["tou"][mon].update({1:0.01,2:4.0})
        tiny["pv_cf"][mon].update({1:0.8,2:0.0})
    models = [build_model(tiny,cfg), build_benders_master(tiny,cfg,scenario="no_redirection")]
    objectives = []
    for model in models:
        for i in model.I:
            model.PV[i].fix(1)
            model.Batt[i].fix(1)
        objectives.append(solve(model))
        metrics = energy_boundary_metrics(model,tiny,cfg)
        assert metrics["annual_stationary_battery_losses_kWh"] > 0
        assert metrics["annual_stationary_PV_available_kWh"] > 0
        assert metrics["annual_weighted_storage_change_kWh"] == pytest.approx(0,abs=1e-6)
        assert metrics["annual_optimizer_energy_balance_residual_kWh"] == pytest.approx(0,abs=1e-6)
    assert objectives[0] == pytest.approx(objectives[1],abs=0.01)
