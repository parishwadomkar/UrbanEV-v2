import math

import pytest

from input_validation import align_pvgis_clock
from preprocessing import preprocess, build_pvgis_monthly_hourly_cf


def test_four_seasons_annual_energy(raw, cfg):
    data = preprocess(raw, cfg)
    expected = {"WINTER":90, "SPRING":92, "SUMMER":92, "AUTUMN":91}
    diag = data["seasonal_demand_diagnostics"].set_index("Season")
    assert diag["Days"].to_dict() == expected
    annual = sum(expected[s] * raw["gdf"].loc[raw["gdf"]["Season"] == s,"Demand"].sum() for s in expected)
    assert diag["SeasonAnnualized_TotalMATSim_kWh"].sum() == pytest.approx(annual)
    assert data["demand_event_annual"][(1,"January",1,"public")] == 4
    assert data["demand_event_annual"][(1,"July",1,"public")] == 2
    boundary = sum(data["N_MONTH"][m] * v for (i,m,t,b),v in data["demand_event_annual"].items())
    private = sum(data["N_MONTH"][m] * v for (i,m,t),v in data["home_private_served_event"].items())
    assert boundary + private == pytest.approx(annual)


@pytest.mark.parametrize("failure", ["season", "slot", "negative", "infinite", "duplicate", "fractional_id", "parking", "crs", "category"])
def test_bad_inputs_rejected(raw, cfg, failure):
    if failure == "season": raw["gdf"] = raw["gdf"].drop(columns="Season")
    if failure == "slot": raw["gdf"] = raw["gdf"].iloc[1:].copy()
    if failure == "negative": raw["gdf"].loc[0,"Demand"] = -1
    if failure == "infinite": raw["gdf"].loc[0,"Demand"] = math.inf
    if failure == "duplicate": raw["gdf"].loc[1,["charType","Demand"]] = ["home",2]
    if failure == "fractional_id": raw["gdf"]["HexID"] = raw["gdf"]["HexID"].astype(float); raw["gdf"].loc[0,"HexID"] = 1.5
    if failure == "parking": raw["parking_gdf"] = raw["parking_gdf"].iloc[:1].copy()
    if failure == "crs": raw["parking_gdf"] = raw["parking_gdf"].to_crs("EPSG:4326")
    if failure == "category": raw["gdf"].loc[0,"charType"] = "unknown"
    with pytest.raises(ValueError): preprocess(raw, cfg)


def test_work_policy_explicit(raw,cfg):
    raw["gdf"].loc[raw["gdf"]["charType"] == "public","charType"] = "work"
    with pytest.raises(ValueError): preprocess(raw,cfg)
    cfg["work_charging_policy"] = "merge_public"
    assert preprocess(raw,cfg)["demand_event_annual"][(1,"January",1,"public")] == 4


def test_missing_pv_hour_fails(raw,cfg):
    with pytest.raises(ValueError, match="12 months"):
        build_pvgis_monthly_hourly_cf(raw["pvgis_df"].iloc[1:], cfg)


def test_fractional_pvgis_hour_fails(raw, cfg):
    raw["pvgis_df"]["hour"] = raw["pvgis_df"]["hour"].astype(float)
    raw["pvgis_df"].loc[0,"hour"] = 0.5
    with pytest.raises(ValueError, match="integer"):
        build_pvgis_monthly_hourly_cf(raw["pvgis_df"], cfg)


def test_clock_conversion_preserves_samples_and_energy(raw,cfg):
    cfg["pvgis_input_timezone"] = "UTC"
    aligned = align_pvgis_clock(raw["pvgis_df"],cfg)
    assert aligned["500W_P"].sum() == raw["pvgis_df"]["500W_P"].sum()
    assert aligned.loc[0,"hour"] == 1
    assert aligned.loc[6*24,"hour"] == 2
    assert len(aligned) == len(raw["pvgis_df"])


def test_explicit_sparse_zero_policy(raw,cfg):
    raw["gdf"] = raw["gdf"].iloc[1:].copy()
    cfg["missing_demand_policy"] = "explicit_zero"
    assert preprocess(raw,cfg)["home_demand_total_event"][(1,"January",1)] == 0
