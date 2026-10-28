"""Modified for the UrbanEV seasonal integration, 2026-10-22. See SOURCE_PROVENANCE.json."""
from __future__ import annotations

from pathlib import Path
import geopandas as gpd
import pandas as pd
from provenance import read_provenance


def _read_pvgis(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        # The project PVGIS export uses a semicolon delimiter and European
        # decimal commas (e.g. 4,655 W). sep=None keeps delimiter detection
        # flexible, while decimal="," ensures the PV power columns are
        # loaded as numeric values rather than strings.
        df = pd.read_csv(
            path,
            sep=None,
            engine="python",
            decimal=",",
            encoding="utf-8-sig",
        )
        df.columns = [str(c).strip().lstrip("\ufeff") for c in df.columns]
        return df
    if suffix in {".xlsx", ".xls"}:
        df = pd.read_excel(path)
        df.columns = [str(c).strip().lstrip("\ufeff") for c in df.columns]
        return df
    raise ValueError(
        f"Unsupported PVGIS input format '{path.suffix}'. Use CSV, XLSX, or XLS."
    )


def load_inputs(paths: dict) -> dict:
    demand_shapefile = Path(paths["demand_shapefile"])
    parking_shapefile = Path(paths["parking_shapefile"])
    distance_csv = Path(paths["distance_csv"])
    spot_price_csv = Path(paths["spot_price_csv"])
    pvgis_file = Path(paths.get("pvgis_file", paths.get("pvgis_excel", "")))

    if not str(pvgis_file):
        raise KeyError("Resolved paths must contain 'pvgis_file' (or legacy 'pvgis_excel').")

    required = [demand_shapefile, parking_shapefile, distance_csv, spot_price_csv, pvgis_file]
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(f"Missing input file: {path}")
        with path.open("rb") as handle:
            head = handle.read(256)
        if head.startswith(b"version https://git-lfs.github.com/spec/"):
            raise ValueError(f"Git LFS pointer instead of input data: {path}")
        if path.suffix.lower() == ".gpkg" and not head.startswith(b"SQLite format 3\x00"):
            raise ValueError(f"Invalid GeoPackage container: {path}")
    provenance = read_provenance(paths)
    return {
        "paths": dict(paths),
        "provenance": provenance,
        "gdf": gpd.read_file(demand_shapefile),
        "parking_gdf": gpd.read_file(parking_shapefile),
        "dist_df": pd.read_csv(distance_csv),
        "spot_df": pd.read_csv(spot_price_csv),
        "pvgis_df": _read_pvgis(pvgis_file),
    }


def check_input_paths(paths: dict):
    keys = ["demand_shapefile", "distance_csv", "parking_shapefile", "spot_price_csv"]
    pvgis_key = "pvgis_file" if "pvgis_file" in paths else "pvgis_excel"
    keys.append(pvgis_key)
    return [(str(Path(paths[k])), Path(paths[k]).exists()) for k in keys]
