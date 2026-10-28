# UrbanEV-Opti contributor guidance

These instructions apply to this directory and its descendants. The Java project and repository-level GitHub configuration are maintained at the UrbanEV-v2 root.

Preserve the seasonal demand mapping, annual objective, charger-resource interpretation, private-home boundary, and selected BESS convention unless a requested change explicitly concerns them. Read `PublicRes`, `homeChar`, and `Panels` directly; do not introduce installation allowances or capacity divisors.

Keep monolithic, Benders, and LBBD inputs, technology switches, and accounting consistent. Exact spatial mode requires the absence of inter-site coupling. Preserve certificate, fingerprint, and restart checks. Feasible objectives and global bounds must remain distinguishable.

Use synthetic fixtures for regression tests. Do not run production optimization or alter local inputs and run results as part of routine code maintenance. Keep solver logs, bytecode, environments, and generated outputs out of source-only commits. Retain source attribution and licenses.

Run checks from this directory:

```text
python scripts/check_repository.py
python -m flake8 src src_lbbd src_benders scripts tests --select=E9,F63,F7,F82,F401,F811,F841
python -m pytest -q tests
```

Refer to the [original optimization repository](https://github.com/parishwadomkar/Large-scale-LBBD-Optimization) and [paper](https://doi.org/10.1016/j.adapen.2026.100310) for method validation and reference benchmarks.
