from __future__ import annotations

import json
from pathlib import Path
from pyomo.environ import value


def project_root_from_file(file_path: str | Path) -> Path:
    return Path(file_path).resolve().parents[1]


def load_json(path: str | Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def resolve_project_path(project_root: Path, maybe_relative: str | Path) -> Path:
    p = Path(maybe_relative)
    return p if p.is_absolute() else project_root / p


def sv(obj, default: float = 0.0) -> float:
    try:
        v = value(obj)
        return default if v is None else float(v)
    except Exception:
        try:
            v = getattr(obj, "value")
            return default if v is None else float(v)
        except Exception:
            try:
                return float(obj)
            except Exception:
                return default


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p
