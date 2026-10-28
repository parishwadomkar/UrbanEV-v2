from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path

FORMULATION_VERSION = "urbanev-seasonal-2.2-final-capacity"
FILE_ROLES = ("demand_shapefile", "parking_shapefile", "distance_csv", "pvgis_file", "spot_price_csv")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def input_hashes(paths):
    records = {}
    for role in FILE_ROLES:
        path = Path(paths[role])
        records[role] = {"sha256": file_hash(path), "bytes": path.stat().st_size}
        if path.suffix.lower() == ".shp":
            for suffix in [".dbf", ".shx", ".prj", ".cpg"]:
                sidecar = path.with_suffix(suffix)
                if sidecar.exists():
                    records[role + suffix] = {"sha256": file_hash(sidecar), "bytes": sidecar.stat().st_size}
    return records


def read_provenance(paths):
    hashes = input_hashes(paths)
    path = Path(paths["demand_shapefile"]).parent / "provenance.json"
    if not path.exists():
        return {"files": hashes, "source_verified": False, "status": "unregistered", "dataset": paths["dataset"], "vipv_scenario": paths["vipv_scenario"]}
    info = json.loads(path.read_text(encoding="utf-8"))
    for key in ["dataset", "vipv_scenario"]:
        if info.get(key) != paths[key]:
            raise ValueError(f"Provenance {key} does not match selected inputs.")
    if info.get("files") != hashes:
        raise ValueError("Input files have changed since provenance registration; regenerate provenance after reviewing the changes.")
    if info.get("iteration") != 100:
        raise ValueError("Registered MATSim inputs must use iteration 100.")
    sources = info.get("sources", [])
    valid = len(sources) == 4 and {s.get("season") for s in sources} == {"WINTER", "SPRING", "SUMMER", "AUTUMN"}
    valid = valid and all(s.get("sha256") and s.get("energy_reconciled") is True for s in sources)
    info["source_verified"] = bool(valid and info.get("matsim_commit") and info.get("pvgis_input_timezone") in {"UTC", "Europe/Stockholm"})
    return info


def source_code_hash(root):
    files = {}
    for directory in ["src", "src_lbbd", "src_benders"]:
        for path in sorted((Path(root) / directory).glob("*.py")):
            files[str(path.relative_to(root)).replace("\\", "/")] = file_hash(path)
    return digest(files)


def build_identity(root, data, cfg, args):
    provenance = data.get("provenance", {})
    assumptions = {"formulation_version": FORMULATION_VERSION, "code_hash": source_code_hash(root), "model_config": cfg,
                   "dataset": args.dataset, "scenario": args.scenario, "disable_pv": bool(args.disable_pv),
                   "disable_bess": bool(args.disable_bess), "hard_no_slack": bool(getattr(args, "hard_no_slack", False)),
                   "regularize_infrastructure": bool(getattr(args, "regularize_infrastructure", False)),
                   "regularization_profit_tolerance_SEK": float(getattr(args, "regularization_profit_tolerance", 1.0)) if getattr(args, "regularize_infrastructure", False) else 0.0}
    common = {k: v for k, v in provenance.get("files", {}).items() if not k.startswith("demand_shapefile")}
    generation = {k: provenance.get(k) for k in ["iteration", "matsim_commit", "population_sample", "scale_factor", "aggregation_rule", "aggregation_days", "pvgis_input_timezone"]}
    comparison = {**assumptions, "common_inputs": common, "generation": generation}
    problem = {**comparison, "vipv_scenario": args.vipv_scenario, "inputs": provenance.get("files", {})}
    return {"problem_hash": digest(problem), "comparison_hash": digest(comparison), "comparison_payload": comparison, "assumptions": assumptions,
            "vipv_scenario": args.vipv_scenario, "source_verified": provenance.get("source_verified", False), "provenance": provenance}


def record_run_context(root, run_dir, data, cfg, args, method):
    identity = build_identity(root, data, cfg, args)
    args._problem_hash = identity["problem_hash"]
    data["run_identity"] = identity
    versions = {"python": platform.python_version()}
    for name in ["pyomo", "gurobipy", "pandas", "geopandas", "numpy"]:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "not installed"
    payload = {**identity, "method": method, "versions": versions,
               "settings": {k: v for k, v in vars(args).items() if not k.startswith("_")},
               "input_paths": data.get("input_paths", {}),
               "solver_profile": getattr(args, "_solver_cfg", {})}
    Path(run_dir).mkdir(parents=True, exist_ok=True)
    (Path(run_dir) / "run_context.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return identity


def assert_restart_identity(payload, args):
    expected = getattr(args, "_problem_hash", None)
    if not expected or payload.get("problem_hash") != expected:
        raise ValueError("Restart problem fingerprint mismatch: seasonal inputs, VIPV treatment, code or model assumptions differ.")


def validate_comparison(run_dirs, *, across_scenarios=False, allow_partial=False, axis="vipv"):
    contexts = []
    for folder in run_dirs:
        root = Path(folder)
        path = root / "run_context.json"
        if not path.exists():
            raise ValueError(f"Run context is missing: {root}")
        context = json.loads(path.read_text(encoding="utf-8"))
        contexts.append(context)
        certificate = root / "results" / "solver_certificate.json"
        meta = root / "run_metadata.json"
        if certificate.exists():
            cert = json.loads(certificate.read_text(encoding="utf-8"))
            gap, target = cert.get("gurobi_mip_gap"), cert.get("requested_mip_gap")
            proved = cert.get("has_loaded_incumbent") and gap is not None and target is not None and gap <= target + 1e-9
        elif meta.exists():
            info = json.loads(meta.read_text(encoding="utf-8"))
            proved = info.get("termination") == "certified_gap"
        else:
            proved = False
        if not proved and not allow_partial:
            raise ValueError(f"Requested convergence is not certified: {root}. Use --allow-partial only for an explicitly provisional comparison.")
    signatures = []
    for context in contexts:
        if not across_scenarios or axis == "vipv":
            signatures.append(context.get("comparison_hash" if across_scenarios else "problem_hash"))
        else:
            payload = dict(context["comparison_payload"])
            payload["vipv_scenario"] = context["vipv_scenario"]
            payload["inputs"] = context["provenance"]["files"]
            if axis == "technology":
                payload.pop("disable_pv", None)
                payload.pop("disable_bess", None)
            elif axis == "redirection":
                payload.pop("scenario", None)
            else:
                raise ValueError("Unknown comparison axis.")
            signatures.append(digest(payload))
    if len(set(signatures)) != 1 or not all(signatures):
        raise ValueError("Comparison mixes incompatible inputs, generation rules or model assumptions.")
    if len({bool(c.get("source_verified")) for c in contexts}) > 1:
        raise ValueError("Comparison mixes registered and unregistered source provenance.")
    return contexts
