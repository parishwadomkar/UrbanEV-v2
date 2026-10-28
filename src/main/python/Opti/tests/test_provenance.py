import json
from types import SimpleNamespace

import pytest
from provenance import assert_restart_identity, build_identity, validate_comparison
from conftest import ROOT


def test_identity_changes_when_seasonal_data_change(cfg):
    args = SimpleNamespace(dataset="full",vipv_scenario="noVIPV",scenario="no_redirection",disable_pv=False,disable_bess=False)
    data = {"provenance":{"files":{"demand_shapefile":{"sha256":"a"}},"source_verified":False}}
    first = build_identity(ROOT,data,cfg,args)
    data['provenance']['files']['demand_shapefile']['sha256']='b'
    second = build_identity(ROOT,data,cfg,args)
    assert first['problem_hash'] != second['problem_hash']
    assert first['comparison_hash'] == second['comparison_hash']
    args._problem_hash=first['problem_hash']
    with pytest.raises(ValueError): assert_restart_identity(second,args)
    assert_restart_identity(first,args)


def test_comparison_rejects_partial_and_incompatible(tmp_path):
    folders=[]
    for name in ['a','b']:
        root=tmp_path/name; (root/'results').mkdir(parents=True)
        (root/'run_context.json').write_text(json.dumps({'problem_hash':'same','source_verified':False}))
        (root/'results/solver_certificate.json').write_text(json.dumps({'has_loaded_incumbent':True,'gurobi_mip_gap':0.02,'requested_mip_gap':0.001}))
        folders.append(root)
    with pytest.raises(ValueError,match="convergence"): validate_comparison(folders)
    validate_comparison(folders,allow_partial=True)
    (folders[1]/'run_context.json').write_text(json.dumps({'problem_hash':'different','source_verified':False}))
    with pytest.raises(ValueError,match="incompatible"): validate_comparison(folders,allow_partial=True)
