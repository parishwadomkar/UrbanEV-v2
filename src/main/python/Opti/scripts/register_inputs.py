from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from input_scenarios import add_input_selection_arguments, resolve_input_selection, resolve_scenario_paths, VIPV_SCENARIOS
from provenance import input_hashes, file_hash


def register(paths, args, candidates):
    sources = []
    demand = gpd.read_file(paths["demand_shapefile"])
    if not {"Season", "Demand"} <= set(demand.columns):
        raise ValueError("Demand requires Season and Demand columns.")
    values = pd.to_numeric(demand["Demand"], errors="raise")
    if not all(math.isfinite(float(v)) and v >= 0 for v in values):
        raise ValueError("Demand must be finite and nonnegative.")
    demand["Demand"] = values
    treatment = "noVIPV_Wp0" if paths["vipv_scenario"] == "noVIPV" else paths["vipv_scenario"]
    for season in ["WINTER", "SPRING", "SUMMER", "AUTUMN"]:
        sample_tag = f"{100 * args.population_sample:g}pct"
        pattern = re.compile(rf"(?:^|[/\\]){re.escape(sample_tag)}_{season}_{re.escape(treatment)}_open\d+(?:[/\\])", re.I)
        matches = [p for p in candidates if pattern.search(str(p))]
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one iteration-100 source for {sample_tag}/{season}/{treatment}; found {len(matches)}. Select one scenario matrix with --source-root.")
        path = matches[0]
        stats = pd.read_csv(path, sep=None, engine="python")
        if "transmittedEnergy_kWh" not in stats:
            raise ValueError(f"Missing transmittedEnergy_kWh in {path}")
        energy = pd.to_numeric(stats["transmittedEnergy_kWh"], errors="raise")
        if not all(math.isfinite(float(v)) and v >= 0 for v in energy):
            raise ValueError(f"Invalid charging energy in {path}")
        weekly = float(energy.sum())
        representative = weekly * args.scale_factor / 7.0
        supplied = float(demand.loc[demand["Season"].astype(str).str.strip().str.upper() == season, "Demand"].sum())
        if not math.isclose(representative, supplied, rel_tol=args.energy_rtol, abs_tol=0.01):
            raise ValueError(f"Energy reconciliation failed for {season}: generated={supplied}, source weekly*scale/7={representative}. This helper supports the full-domain seven-day mean only.")
        ancillary = {}
        for parent in path.parents:
            if parent == args.source_root.parent:
                break
            for name in ["resolved-config.xml", "vipv-run-manifest.json"]:
                candidate = parent / name
                if candidate.is_file() and name not in ancillary:
                    ancillary[name] = {"path": str(candidate), "sha256": file_hash(candidate)}
        sources.append({"season": season, "path": str(path), "sha256": file_hash(path), "weekly_energy_kwh": weekly,
                        "representative_day_kwh": supplied, "energy_reconciled": True, "ancillary": ancillary})
    return {"schema_version": 1, "dataset": paths["dataset"], "vipv_scenario": paths["vipv_scenario"],
            "iteration": 100, "matsim_commit": args.matsim_commit, "population_sample": args.population_sample,
            "scale_factor": args.scale_factor, "aggregation_rule": "seven_day_mean", "aggregation_days": list(range(1, 8)),
            "energy_unit": "kWh_per_representative_day_half_hour", "pvgis_input_timezone": args.pvgis_timezone,
            "files": input_hashes(paths), "sources": sources}


def main():
    parser = argparse.ArgumentParser(description="Register and reconcile a full-domain iteration-100 seven-day scenario matrix.")
    add_input_selection_arguments(parser)
    parser.add_argument("--all-scenarios", action="store_true")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--population-sample", type=float, required=True)
    parser.add_argument("--scale-factor", type=float, required=True)
    parser.add_argument("--matsim-commit", required=True)
    parser.add_argument("--pvgis-timezone", choices=["UTC", "Europe/Stockholm"], required=True)
    parser.add_argument("--energy-rtol", type=float, default=1e-5)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    resolve_input_selection(args, ROOT)
    if not 0 < args.population_sample <= 1 or not math.isfinite(args.scale_factor) or args.scale_factor <= 0:
        parser.error("Population sample must be in (0,1] and scale factor must be positive and finite.")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", args.matsim_commit):
        parser.error("Provide the full 40-character MATSim commit SHA.")
    if not 0 <= args.energy_rtol <= 0.001:
        parser.error("Energy relative tolerance must be between 0 and 0.001.")
    args.source_root = args.source_root.expanduser().resolve()
    candidates = list(args.source_root.rglob("100.chargingStats.csv"))
    pending = []
    for scenario in VIPV_SCENARIOS if args.all_scenarios else [args.vipv_scenario]:
        paths = resolve_scenario_paths(ROOT, args.dataset, scenario)
        target = Path(paths["demand_shapefile"]).parent / "provenance.json"
        if target.exists() and not args.overwrite:
            raise FileExistsError(f"Existing provenance requires --overwrite: {target}")
        pending.append((target, register(paths, args, candidates)))
    for target, payload in pending:
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Registered: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
