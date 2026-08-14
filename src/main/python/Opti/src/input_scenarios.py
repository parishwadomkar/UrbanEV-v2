from __future__ import annotations

import argparse
import json
from pathlib import Path

DATASETS = ("small", "full")
VIPV_SCENARIOS = (
    "noVIPV",
    "VIPV20_Wp400",
    "VIPV20_Wp700",
    "VIPV20_Wp1000",
    "VIPV50_Wp400",
    "VIPV50_Wp700",
    "VIPV50_Wp1000",
    "VIPV80_Wp400",
    "VIPV80_Wp700",
    "VIPV80_Wp1000",
)


def _load_paths_config(project_root: Path) -> dict:
    path = project_root / "config" / "paths.json"
    return json.loads(path.read_text(encoding="utf-8"))


def add_input_selection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "dataset_positional",
        nargs="?",
        choices=DATASETS,
        help="Optional dataset shortcut: small or full. Example: --VIPV50_Wp700 full",
    )

    dataset_group = parser.add_mutually_exclusive_group()
    dataset_group.add_argument(
        "--dataset",
        choices=DATASETS,
        default=None,
        help="Input dataset size.",
    )
    dataset_group.add_argument(
        "--small",
        dest="dataset_shortcut",
        action="store_const",
        const="small",
        help="Shortcut for --dataset small.",
    )
    dataset_group.add_argument(
        "--full",
        dest="dataset_shortcut",
        action="store_const",
        const="full",
        help="Shortcut for --dataset full.",
    )

    vipv_group = parser.add_mutually_exclusive_group()
    vipv_group.add_argument(
        "--vipv-scenario",
        choices=VIPV_SCENARIOS,
        default=None,
        help="VIPV demand-input scenario.",
    )
    for scenario in VIPV_SCENARIOS:
        vipv_group.add_argument(
            f"--{scenario}",
            dest="vipv_scenario_shortcut",
            action="store_const",
            const=scenario,
            help=f"Shortcut for --vipv-scenario {scenario}.",
        )


def resolve_input_selection(args: argparse.Namespace, project_root: Path) -> tuple[str, str]:
    raw = _load_paths_config(project_root)
    default_dataset = str(raw.get("default_dataset", "small"))
    default_vipv = str(raw.get("default_vipv_scenario", "noVIPV"))

    dataset_values = [
        value for value in (
            getattr(args, "dataset", None),
            getattr(args, "dataset_shortcut", None),
            getattr(args, "dataset_positional", None),
        ) if value is not None
    ]
    if len(set(dataset_values)) > 1:
        raise SystemExit(
            "Conflicting dataset selections were supplied. Use only one of "
            "'--dataset full', '--full', or positional 'full' (analogously for small)."
        )
    dataset = dataset_values[0] if dataset_values else default_dataset

    vipv_values = [
        value for value in (
            getattr(args, "vipv_scenario", None),
            getattr(args, "vipv_scenario_shortcut", None),
        ) if value is not None
    ]
    if len(set(vipv_values)) > 1:
        raise SystemExit("Conflicting VIPV scenario selections were supplied.")
    vipv_scenario = vipv_values[0] if vipv_values else default_vipv

    available_datasets = tuple(raw.get("datasets", {}).keys())
    configured_scenarios = tuple(raw.get("vipv_scenarios", VIPV_SCENARIOS))
    if dataset not in available_datasets:
        raise SystemExit(
            f"Dataset '{dataset}' is not configured. Available datasets: {list(available_datasets)}"
        )
    if vipv_scenario not in configured_scenarios:
        raise SystemExit(
            f"VIPV scenario '{vipv_scenario}' is not configured. "
            f"Available scenarios: {list(configured_scenarios)}"
        )

    args.dataset = dataset
    args.vipv_scenario = vipv_scenario
    return dataset, vipv_scenario


def resolve_scenario_paths(project_root: Path, dataset: str, vipv_scenario: str) -> dict:
    raw = _load_paths_config(project_root)
    if dataset not in raw.get("datasets", {}):
        raise KeyError(f"Dataset '{dataset}' not found in config/paths.json")
    if vipv_scenario not in raw.get("vipv_scenarios", VIPV_SCENARIOS):
        raise KeyError(f"VIPV scenario '{vipv_scenario}' not found in config/paths.json")

    template_paths = dict(raw["datasets"][dataset])
    paths = {
        key: str(value).format(dataset=dataset, vipv_scenario=vipv_scenario)
        for key, value in template_paths.items()
    }
    paths["dataset"] = dataset
    paths["vipv_scenario"] = vipv_scenario
    paths["pvgis_file"] = raw.get("pvgis_file", raw.get("pvgis_excel"))
    paths["spot_price_csv"] = raw["spot_price_csv"]
    paths["runs_root"] = raw["runs_root"]

    if not paths["pvgis_file"]:
        raise KeyError("config/paths.json must define 'pvgis_file' (or legacy 'pvgis_excel').")

    for key in (
        "demand_shapefile",
        "distance_csv",
        "parking_shapefile",
        "pvgis_file",
        "spot_price_csv",
        "runs_root",
    ):
        path = Path(paths[key])
        paths[key] = str(path if path.is_absolute() else project_root / path)

    return paths
