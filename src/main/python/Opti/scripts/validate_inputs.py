"""Modified for the UrbanEV seasonal integration, 2026-10-22. See SOURCE_PROVENANCE.json."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from input_scenarios import add_input_selection_arguments, resolve_input_selection, resolve_scenario_paths, VIPV_SCENARIOS
from data_loader import load_inputs
from preprocessing import preprocess


def main():
    parser = argparse.ArgumentParser(description="Validate local seasonal inputs without solving or writing run outputs.")
    add_input_selection_arguments(parser)
    parser.add_argument("--all-scenarios", action="store_true")
    parser.add_argument("--require-provenance", action="store_true")
    args = parser.parse_args()
    resolve_input_selection(args, ROOT)
    cfg = json.loads((ROOT / "config/model_config.json").read_text())
    if args.require_provenance:
        cfg["require_data_provenance"] = True
    for scenario in VIPV_SCENARIOS if args.all_scenarios else [args.vipv_scenario]:
        data = preprocess(load_inputs(resolve_scenario_paths(ROOT, args.dataset, scenario)), cfg)
        print(f"PASS {args.dataset}/{scenario}: {len(data['hex_ids'])} hexes, four seasons, 48 slots; source_verified={data['provenance']['source_verified']}")
        print(data["seasonal_demand_diagnostics"].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
