from __future__ import annotations

import copy

import geopandas as gpd
import numpy as np
import pytest

from input_validation import validate_capacity_inputs, validate_model_config
from preprocessing import preprocess


def test_fractional_public_resources_round_trip(raw, tmp_path):
    parking = raw["parking_gdf"].copy()
    parking["PublicRes"] = [10.5, 25.5]
    path = tmp_path / "capacity.shp"
    parking.to_file(path)
    restored = validate_capacity_inputs(gpd.read_file(path))
    np.testing.assert_array_equal(restored["PublicRes"], parking["PublicRes"])
    np.testing.assert_array_equal(restored["homeChar"], parking["homeChar"])


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0])
def test_invalid_public_resource_budget_is_rejected(raw, bad):
    raw["parking_gdf"].loc[0, "PublicRes"] = bad
    with pytest.raises(ValueError):
        validate_capacity_inputs(raw["parking_gdf"])


@pytest.mark.parametrize("field", ["homeChar", "Panels"])
def test_counts_must_be_integers(raw, field):
    raw["parking_gdf"][field] = raw["parking_gdf"][field].astype(float)
    raw["parking_gdf"].loc[0, field] = 1.5
    with pytest.raises(ValueError, match="integer"):
        validate_capacity_inputs(raw["parking_gdf"])


def test_public_resource_budget_is_required(raw):
    parking = raw["parking_gdf"].rename(columns={"PublicRes": "ParkingCap"})
    with pytest.raises(ValueError, match="PublicRes"):
        validate_capacity_inputs(parking)


def test_repeated_preprocessing_preserves_supplied_capacities(raw, cfg):
    raw["parking_gdf"]["PublicRes"] = [25.0, 25.5]
    raw["parking_gdf"]["homeChar"] = [5, 7]
    raw["gdf"].loc[raw["gdf"]["charType"] == "home", "Demand"] = 21.0
    original = copy.deepcopy(raw)
    first = preprocess(raw, cfg)
    second = preprocess(raw, cfg)
    assert first["cl"] == second["cl"] == {1: 25.0, 2: 25.5}
    assert first["home_avail"] == second["home_avail"] == {1: 5, 2: 7}
    assert first["demand_event_annual"][1, "January", 1, "home"] == 3.5
    assert first["demand_event_annual"][2, "January", 1, "home"] == 0.0
    for key in ["parking_gdf", "gdf"]:
        assert raw[key].equals(original[key])


@pytest.mark.parametrize("connected", [True, False])
def test_zero_resource_budget_is_not_increased(raw, cfg, connected):
    raw["parking_gdf"]["PublicRes"] = 0.0
    if not connected:
        raw["dist_df"] = raw["dist_df"].iloc[:0].copy()
    assert preprocess(raw, cfg)["cl"] == {1: 0.0, 2: 0.0}


@pytest.mark.parametrize("key", ["parking_capacity_add", "home_charger_add", "data_provisioning",
                                "gis_parking_availability_fraction", "optimizer_parking_divisor"])
def test_runtime_capacity_adjustment_settings_are_rejected(cfg, key):
    with pytest.raises(ValueError, match="Unsupported model settings"):
        validate_model_config({**cfg, key: 1})


@pytest.mark.parametrize("fast_weight", [100, 150])
def test_resource_weight_does_not_change_power_or_input_capacity(raw, cfg, fast_weight):
    cfg["charger_resources"]["fast"] = fast_weight
    validate_model_config(cfg)
    data = preprocess(raw, cfg)
    assert data["charger_resources"]["fast"] == fast_weight
    assert data["charger_capacity_pub"]["fast"] == 25.0
    assert data["cl"] == {1: 10.0, 2: 10.0}
