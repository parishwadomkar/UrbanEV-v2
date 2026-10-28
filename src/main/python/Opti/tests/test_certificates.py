from types import SimpleNamespace

import pyomo.environ as pyo
import pytest
from pyomo.opt import SolverStatus, TerminationCondition

from solve_model import solver_certificate
from src_lbbd.lbbd_master import InvestmentPoint
from src_lbbd.run_lbbd import _load_bootstrap_checkpoint, _save_bootstrap_checkpoint


@pytest.mark.parametrize("loaded", [True, False])
def test_time_limit_certificate_uses_only_loaded_incumbent(tmp_path, loaded):
    model=pyo.ConcreteModel()
    model.x=pyo.Var(initialize=50)
    model.obj=pyo.Objective(expr=model.x,sense=pyo.maximize)
    model._last_solve_loaded_incumbent=loaded
    result=SimpleNamespace(solver=SimpleNamespace(termination_condition=TerminationCondition.maxTimeLimit,status=SolverStatus.aborted),
                           problem=SimpleNamespace(upper_bound=100))
    certificate=solver_certificate(result,model,tmp_path/'absent.log')
    assert certificate['termination_reason']=='time_limit'
    assert certificate['valid_bound_SEK']==100
    assert certificate['has_loaded_incumbent']==loaded
    assert certificate['objective_SEK']==(50 if loaded else None)
    assert certificate['gurobi_mip_gap']==(1 if loaded else None)


def test_error_does_not_certify_stale_bound(tmp_path):
    model=pyo.ConcreteModel()
    model._last_solve_loaded_incumbent=False
    result=SimpleNamespace(solver=SimpleNamespace(termination_condition=TerminationCondition.error,status=SolverStatus.error),
                           problem=SimpleNamespace(upper_bound=100))
    certificate=solver_certificate(result,model,tmp_path/'absent.log')
    assert certificate['valid_bound_SEK'] is None
    assert certificate['gurobi_mip_gap'] is None


def test_checkpoint_requires_same_treatment_and_problem(tmp_path):
    args=SimpleNamespace(dataset='full',vipv_scenario='noVIPV',scenario='no_redirection',disable_pv=False,disable_bess=False,_problem_hash='a')
    inv=InvestmentPoint({(1,'slow'):1},{1:1},{1:0})
    path=tmp_path/'synthetic_checkpoint.json'
    _save_bootstrap_checkpoint(path,args,inv,100,80)
    assert _load_bootstrap_checkpoint(path,args)==(inv,100,80)
    args.vipv_scenario='VIPV20_Wp400'
    with pytest.raises(ValueError,match='mismatch'):
        _load_bootstrap_checkpoint(path,args)
    args.vipv_scenario='noVIPV'
    args._problem_hash='b'
    with pytest.raises(ValueError,match='mismatch'):
        _load_bootstrap_checkpoint(path,args)
