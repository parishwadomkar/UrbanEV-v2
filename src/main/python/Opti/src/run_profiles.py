"""Modified for the UrbanEV seasonal integration, 2026-10-22. See SOURCE_PROVENANCE.json."""
from __future__ import annotations

from pathlib import Path
import os
import math
import psutil
from typing import Any

from utils import load_json


def load_run_profile(project_root: Path, method: str, dataset: str) -> dict[str, Any]:
    """Load starting defaults for one method and dataset.

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
    """Populate only unset argparse attributes from a run profile."""
    user_threads = getattr(args, "threads", None)
    user_soft_memory = getattr(args, "soft_mem_limit_gb", None)
    for key, value in profile.items():
        if hasattr(args, key) and getattr(args, key) is None:
            setattr(args, key, value)

    if user_threads is None and hasattr(args, "threads") and args.threads is not None:
        args.threads = min(int(args.threads), 4, os.cpu_count() or 1)
    if hasattr(args, "soft_mem_limit_gb") and args.soft_mem_limit_gb is None:
        args.soft_mem_limit_gb = min(55.0, max(0.5, round(psutil.virtual_memory().available / 1e9 * 0.70, 2)))
    if user_soft_memory is None and getattr(args, "soft_mem_limit_gb", None) is not None:
        args.soft_mem_limit_gb = min(55.0, float(args.soft_mem_limit_gb))
    for key in ("mip_gap", "master_gap", "subproblem_gap", "logic_mip_gap", "lbbd_gap", "benders_gap"):
        value = getattr(args, key, None)
        if value is not None and (not math.isfinite(float(value)) or not 0 <= value < 1):
            raise ValueError(f"{key} must be a finite fraction in [0,1).")
