from __future__ import annotations

from pathlib import Path
from typing import Any

from utils import load_json


def load_run_profile(project_root: Path, method: str, dataset: str) -> dict[str, Any]:
    """Load calibrated defaults for one method and dataset.

    Command-line values remain authoritative: callers should apply this profile
    only to arguments whose parsed value is ``None``.
    """
    profiles = load_json(project_root / "config" / "run_profiles.json")
    try:
        profile = profiles[str(method)][str(dataset)]
    except KeyError as exc:
        raise KeyError(
            f"No run profile for method={method!r}, dataset={dataset!r} in "
            "config/run_profiles.json"
        ) from exc
    return dict(profile)


def apply_profile_defaults(args, profile: dict[str, Any]) -> None:
    """Populate only unset argparse attributes from a calibrated profile."""
    for key, value in profile.items():
        if hasattr(args, key) and getattr(args, key) is None:
            setattr(args, key, value)
