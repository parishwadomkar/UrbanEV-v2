import copy
import json
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]


@pytest.fixture
def cfg():
    value = json.loads((ROOT / "config/model_config.json").read_text())
    value.update(battery_max_units_per_hex=2,
                 require_data_provenance=False, pvgis_input_timezone="as_supplied")
    return value


@pytest.fixture
def raw():
    records = []
    for season, level in {"WINTER": 4., "SPRING": 3., "SUMMER": 2., "AUTUMN": 3.5}.items():
        for i in [1, 2]:
            for t in range(1, 49):
                for context in ["home", "public"]:
                    records.append({"Season": season, "HexID": i, "TimeIndex": t, "charType": context,
                                    "Demand": level * (1 if context == "public" else 0.4), "geometry": Point(i*100, 0)})
    demand = gpd.GeoDataFrame(records, crs="EPSG:3006")
    parking = gpd.GeoDataFrame({"HexID": [1,2], "PublicRes": [10.,10.], "homeChar": [1,1], "Panels": [2,2]},
                               geometry=[Point(100,0), Point(200,0)], crs="EPSG:3006")
    solar = pd.DataFrame([{"year": 2023, "month": m, "date": 15, "hour": h, "500W_P": 150. if 8 <= h < 16 else 0.}
                          for m in range(1,13) for h in range(24)])
    prices = pd.DataFrame({m: [80.] * 24 for m in ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]})
    return {"gdf": demand, "parking_gdf": parking, "dist_df": pd.DataFrame({"from_HexID":[1,2], "to_HexID":[2,1], "distance":[100.,100.]}),
            "spot_df": prices, "pvgis_df": solar}


@pytest.fixture
def tiny(raw, cfg):
    from preprocessing import preprocess
    data = preprocess(raw, cfg)
    data["INTERVALS"] = [1, 2]
    data["time_indices"] = [1, 2]
    data["HSOC"] = [0, 1, 2]
    data["demand_event_annual"] = {k:v for k,v in data["demand_event_annual"].items() if k[2] <= 2}
    data["allowed_st"] = [a for a in data["allowed_st"] if a[3] <= 2]
    for key in ["OUT", "IN"]:
        data[key] = {k:v for k,v in data[key].items() if k[2] <= 2}
    for key in ["ORIGIN_ST", "DEST_ST"]:
        data[key] = [k for k in data[key] if k[2] <= 2]
    return copy.deepcopy(data)
