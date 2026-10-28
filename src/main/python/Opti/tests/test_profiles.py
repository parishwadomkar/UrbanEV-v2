import sys

import pytest

from conftest import ROOT
from run_profiles import apply_profile_defaults, load_run_profile
from src_lbbd.run_lbbd import parse_args


@pytest.mark.parametrize("switch,expected", [([], True), (["--no-bound-polish"], False)])
def test_full_profile_respects_polishing_override(monkeypatch,switch,expected):
    monkeypatch.setattr(sys,"argv",["run_lbbd.py", "--dataset", "full", *switch])
    args=parse_args()
    apply_profile_defaults(args,load_run_profile(ROOT,"lbbd","full"))
    assert args.bound_polish is expected
    assert args.first_master_lp_bootstrap is True
    assert args.integer_only_master_start is True
    assert args.soft_mem_limit_gb > 0
