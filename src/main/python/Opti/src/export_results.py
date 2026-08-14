from __future__ import annotations

from pathlib import Path
import pandas as pd

from utils import sv


def compute_core_metrics(model, data: dict, cfg: dict) -> dict:
    N_MONTH = data["N_MONTH"]
    DAYS = data["DAYS"]
    PUB_TYPES = data["PUB_TYPES"]

    rev_total = sum(
        N_MONTH[mon] * sv(model.Price[c]) * sv(model.edisp[i, mon, t, c, b])
        for i in model.I for mon in model.M for t in model.H for b in model.B for c in model.C_pub
    )
    grid_direct_cost = sum(
        N_MONTH[mon] * sv(model.tou[mon, t]) * sv(model.grid_dir[i, mon, t])
        for i in model.I for mon in model.M for t in model.H
    )
    grid_battery_cost = sum(
        N_MONTH[mon] * sv(model.tou[mon, t]) * sv(model.grid_batt[i, mon, t])
        for i in model.I for mon in model.M for t in model.H
    )
    grid_cost = grid_direct_cost + grid_battery_cost
    redir_distance_cost = sum(
        N_MONTH[mon] * (
            sv(model.T[i, j]) * sv(model.n_trip[i, j, mon, t])
            + (sv(model.T[i, j]) / sv(model.x_kWh)) * sv(model.r_tail[i, j, mon, t])
        )
        for (i, j, mon, t) in model.A
    )
    redir_price_cost = sum(
        N_MONTH[mon] * sv(model.DeltaPrice[co, cd]) * sv(model.z_od[i, j, mon, t, co, cd])
        for (i, j, mon, t) in model.A for co in model.C_pub for cd in model.C_pub
    )
    slack_pen = float(cfg["penalty_per_kwh_slack"]) * sum(
        N_MONTH[mon] * sv(model.slack[i, mon, t, b])
        for i in model.I for mon in model.M for t in model.H for b in model.B
    )
    capex_chargers = DAYS * sum(sv(model.PVF_cost[c]) * sv(model.x[i, c]) for i in model.I for c in model.C_pub)
    capex_pv = DAYS * sum(sv(model.PVF_PV) * sv(model.PV[i]) for i in model.I)
    capex_bess = DAYS * sum(sv(model.PVF_Batt) * sv(model.Batt[i]) for i in model.I)
    capex_energy = capex_pv + capex_bess
    ann_redir = sum(N_MONTH[mon] * sv(model.z[i, j, mon, t]) for (i, j, mon, t) in model.A)

    ann_grid_direct = sum(N_MONTH[mon] * sv(model.grid_dir[i, mon, t]) for i in model.I for mon in model.M for t in model.H)
    ann_grid_batt = sum(N_MONTH[mon] * sv(model.grid_batt[i, mon, t]) for i in model.I for mon in model.M for t in model.H)
    ann_pv_direct = sum(N_MONTH[mon] * sv(model.pv_dir[i, mon, t]) for i in model.I for mon in model.M for t in model.H)
    ann_pv_batt = sum(N_MONTH[mon] * sv(model.pv_batt[i, mon, t]) for i in model.I for mon in model.M for t in model.H)
    batt_dis = sum(N_MONTH[mon] * sv(model.batt_discharge[i, mon, t]) for i in model.I for mon in model.M for t in model.H)
    annual_public_demand = sum(
        N_MONTH[mon] * sv(model.Demand[i, mon, t, "public"])
        for i in model.I for mon in model.M for t in model.H
    )
    annual_residual_home_demand = sum(
        N_MONTH[mon] * sv(model.Demand[i, mon, t, "home"])
        for i in model.I for mon in model.M for t in model.H
    )
    annual_total_home_demand = sum(
        N_MONTH[mon] * float(data["home_demand_total_event"].get((int(i), str(mon), int(t)), 0.0))
        for i in model.I for mon in model.M for t in model.H
    )
    annual_private_home_served = sum(
        N_MONTH[mon] * float(data["home_private_served_event"].get((int(i), str(mon), int(t)), 0.0))
        for i in model.I for mon in model.M for t in model.H
    )
    home_chargers_exogenous = sum(
        float(data["home_avail"].get(int(i), 0.0))
        for i in model.I
    )
    annual_slack = sum(
        N_MONTH[mon] * sv(model.slack[i, mon, t, b])
        for i in model.I for mon in model.M for t in model.H for b in model.B
    )
    public_capacity_slot = sum(
        sv(model.K[c]) * sv(model.x[i, c]) for i in model.I for c in model.C_pub
    )
    active_redirection_arcs = sum(
        1 for a in model.A if sv(model.z[a]) > 1e-8
    )

    rows = {
        "dataset": data.get("dataset", "unknown"),
        "vipv_scenario": data.get("vipv_scenario", "unknown"),
        "annual_profit_SEK": sv(model.obj),
        "revenue_all_chargers_SEK": rev_total,
        "grid_cost_SEK": grid_cost,
        "grid_direct_cost_SEK": grid_direct_cost,
        "grid_to_battery_cost_SEK": grid_battery_cost,
        "redirection_distance_cost_SEK": redir_distance_cost,
        "redirection_price_compensation_SEK": redir_price_cost,
        "redirection_total_cost_SEK": redir_distance_cost + redir_price_cost,
        "slack_penalty_SEK": slack_pen,
        "capex_chargers_SEK": capex_chargers,
        "capex_PV_SEK": capex_pv,
        "capex_BESS_SEK": capex_bess,
        "capex_PV_BESS_SEK": capex_energy,
        "grid_direct_kWh": ann_grid_direct,
        "grid_to_battery_kWh": ann_grid_batt,
        "grid_total_kWh": ann_grid_direct + ann_grid_batt,
        "pv_direct_kWh": ann_pv_direct,
        "pv_to_battery_kWh": ann_pv_batt,
        "pv_used_total_kWh": ann_pv_direct + ann_pv_batt,
        "battery_discharge_kWh": batt_dis,
        "annual_public_demand_kWh": annual_public_demand,
        "annual_home_demand_total_kWh": annual_total_home_demand,
        "annual_home_private_served_kWh": annual_private_home_served,
        "home_chargers_exogenous": home_chargers_exogenous,
        "annual_home_residual_demand_kWh": annual_residual_home_demand,
        "annual_optimizer_boundary_demand_kWh": annual_public_demand + annual_residual_home_demand,
        "annual_total_MATSim_charging_demand_kWh": annual_public_demand + annual_total_home_demand,
        "implied_stationary_PV_yield_kWh_per_kWp_year": float(data["pv_diag"]["annualized_kwh_per_kwp"].sum()) if not data["pv_diag"].empty else 0.0,
        "pvgis_detected_input_unit": str(data["pv_diag"]["detected_input_unit"].iloc[0]) if not data["pv_diag"].empty else "unknown",
        "energy_redirected_kWh": ann_redir,
        "share_redirected_public_demand": ann_redir / annual_public_demand if annual_public_demand > 0 else 0.0,
        "active_redirection_arcs": active_redirection_arcs,
        "public_charger_capacity_kWh_per_slot": public_capacity_slot,
        "annual_slack_kWh": annual_slack,
        "redirection_trip_equivalents_annual": ann_redir / sv(model.x_kWh) if sv(model.x_kWh) > 0 else 0.0,
        "redirection_full_trip_bundles_annual": sum(
            N_MONTH[mon] * sv(model.n_trip[i, j, mon, t]) for (i, j, mon, t) in model.A
        ),
        "PV_panels_installed": sum(sv(model.PV[i]) for i in model.I),
        "battery_units_installed": sum(sv(model.Batt[i]) for i in model.I),
    }
    for c in PUB_TYPES:
        installed = sum(sv(model.x[i, c]) for i in model.I)
        energy_c = sum(N_MONTH[mon] * sv(model.edisp[i, mon, t, c, b]) for i in model.I for mon in model.M for t in model.H for b in model.B)
        annual_cap_c = installed * sv(model.K[c]) * len(list(model.H)) * DAYS
        revenue_c = sum(
            N_MONTH[mon] * sv(model.Price[c]) * sv(model.edisp[i, mon, t, c, b])
            for i in model.I for mon in model.M for t in model.H for b in model.B
        )
        capex_c = DAYS * sum(sv(model.PVF_cost[c]) * sv(model.x[i, c]) for i in model.I)
        rows[f"chargers_{c}_installed"] = installed
        rows[f"energy_{c}_kWh"] = energy_c
        rows[f"revenue_{c}_SEK"] = revenue_c
        rows[f"capex_chargers_{c}_SEK"] = capex_c
        rows[f"capacity_upper_bound_{c}_kWh"] = annual_cap_c
        rows[f"capacity_ratio_{c}"] = energy_c / annual_cap_c if annual_cap_c > 0 else 0.0
    rows["max_abs_soc_gap_Jan0_Dec48_kWh"] = max(abs(sv(model.soc[i, "December", max(model.H)]) - sv(model.soc[i, "January", 0])) for i in model.I)
    return rows


def export_model_summary(model, data: dict, cfg: dict, results_dir: Path) -> pd.DataFrame:
    metrics = compute_core_metrics(model, data, cfg)
    df = pd.DataFrame([{"Metric": k, "Value": v} for k, v in metrics.items()])
    df.to_csv(results_dir / "model_summary.csv", index=False)
    return df


def export_infrastructure(model, data: dict, results_dir: Path) -> pd.DataFrame:
    rows = []
    for i in model.I:
        row = {"HexID": int(i)}
        for c in model.C_pub:
            row[f"{c}_chargers"] = sv(model.x[i, c])
            row[f"{c}_resources"] = sv(model.ResourceUse[c]) * sv(model.x[i, c])
            row[f"{c}_capacity_kWh_slot"] = sv(model.K[c]) * sv(model.x[i, c])
        row["PV_panels"] = sv(model.PV[i])
        row["Battery_units"] = sv(model.Batt[i])
        row["Total_charger_resources"] = sum(sv(model.ResourceUse[c]) * sv(model.x[i, c]) for c in model.C_pub)
        row["Total_public_capacity_kWh_slot"] = sum(sv(model.K[c]) * sv(model.x[i, c]) for c in model.C_pub)
        rows.append(row)
    df = pd.DataFrame(rows).sort_values("HexID")
    df.to_csv(results_dir / "infrastructure_by_hex.csv", index=False)
    return df


def export_energy_by_charger_type(model, data: dict, results_dir: Path) -> pd.DataFrame:
    rows = []
    DAYS = data["DAYS"]
    for c in model.C_pub:
        installed = sum(sv(model.x[i, c]) for i in model.I)
        annual_capacity = installed * sv(model.K[c]) * len(list(model.H)) * DAYS
        for b in model.B:
            energy = sum(data["N_MONTH"][mon] * sv(model.edisp[i, mon, t, c, b]) for i in model.I for mon in model.M for t in model.H)
            rows.append({
                "ChargerType": str(c),
                "DemandClass": str(b),
                "AnnualEnergy_kWh": energy,
                "InstalledChargers": installed,
                "AnnualCapacity_kWh": annual_capacity,
                "CapacityRatio_all_classes": None,
            })
        total_energy = sum(data["N_MONTH"][mon] * sv(model.edisp[i, mon, t, c, b]) for i in model.I for mon in model.M for t in model.H for b in model.B)
        rows.append({
            "ChargerType": str(c),
            "DemandClass": "ALL",
            "AnnualEnergy_kWh": total_energy,
            "InstalledChargers": installed,
            "AnnualCapacity_kWh": annual_capacity,
            "CapacityRatio_all_classes": total_energy / annual_capacity if annual_capacity > 0 else 0.0,
        })
    df = pd.DataFrame(rows)
    df.to_csv(results_dir / "energy_by_charger_type.csv", index=False)
    return df


def export_redirections(model, data: dict, results_dir: Path) -> pd.DataFrame:
    rows = []
    for (i, j, mon, t) in model.A:
        z = sv(model.z[i, j, mon, t])
        if z <= 1e-8:
            continue
        rows.append({
            "from_HexID": int(i),
            "to_HexID": int(j),
            "Month": mon,
            "TimeIndex": int(t),
            "Distance_km": data["dist_dict"].get((int(i), int(j))),
            "Energy_kWh_day": z,
            "Energy_kWh_annual": data["N_MONTH"][mon] * z,
            "Yarc": sv(model.Yarc[i, j, mon, t]),
            "Trips": sv(model.n_trip[i, j, mon, t]),
            "Tail_kWh": sv(model.r_tail[i, j, mon, t]),
        })
    df = pd.DataFrame(rows)
    df.to_csv(results_dir / "redirections.csv", index=False)
    return df


def export_redirections_by_type(model, data: dict, results_dir: Path) -> pd.DataFrame:
    rows = []
    for (i, j, mon, t) in model.A:
        for co in model.C_pub:
            for cd in model.C_pub:
                z = sv(model.z_od[i, j, mon, t, co, cd])
                if z <= 1e-8:
                    continue
                price_comp = sv(model.DeltaPrice[co, cd]) * z
                rows.append({
                    "from_HexID": int(i),
                    "to_HexID": int(j),
                    "Month": mon,
                    "TimeIndex": int(t),
                    "OriginType": str(co),
                    "DestinationType": str(cd),
                    "Energy_kWh_day": z,
                    "Energy_kWh_annual": data["N_MONTH"][mon] * z,
                    "DeltaPrice_SEK_per_kWh": sv(model.DeltaPrice[co, cd]),
                    "PriceComp_SEK_day": price_comp,
                    "PriceComp_SEK_annual": data["N_MONTH"][mon] * price_comp,
                })
    df = pd.DataFrame(rows)
    df.to_csv(results_dir / "redirections_by_type.csv", index=False)
    return df


def export_origin_type_allocation(model, data: dict, results_dir: Path) -> pd.DataFrame:
    rows = []
    for i in model.I:
        for mon in model.M:
            for t in model.H:
                for c in model.C_pub:
                    rows.append({
                        "HexID": int(i),
                        "Month": mon,
                        "TimeIndex": int(t),
                        "OriginType": str(c),
                        "q_origin_baseline_kWh_day": sv(model.q[i, mon, t, c]),
                        "q_origin_baseline_kWh_annual": data["N_MONTH"][mon] * sv(model.q[i, mon, t, c]),
                    })
    df = pd.DataFrame(rows)
    df.to_csv(results_dir / "origin_type_allocation_q.csv", index=False)
    return df


def export_hourly_energy(model, data: dict, results_dir: Path) -> pd.DataFrame:
    OUT = data["OUT"]
    IN = data["IN"]
    rows = []
    for i in model.I:
        for mon in model.M:
            for t in model.H:
                row = {
                    "HexID": int(i),
                    "Month": mon,
                    "TimeIndex": int(t),
                    "Demand_home_kWh_day": sv(model.Demand[i, mon, t, "home"]),
                    "Demand_public_base_kWh_day": sv(model.Demand[i, mon, t, "public"]),
                    "Redirect_out_kWh_day": sum(sv(model.z[i, j, mon, t]) for j in OUT.get((i, mon, t), [])),
                    "Redirect_in_kWh_day": sum(sv(model.z[j, i, mon, t]) for j in IN.get((i, mon, t), [])),
                    "Grid_direct_kWh_day": sv(model.grid_dir[i, mon, t]),
                    "Grid_batt_kWh_day": sv(model.grid_batt[i, mon, t]),
                    "PV_direct_kWh_day": sv(model.pv_dir[i, mon, t]),
                    "PV_batt_kWh_day": sv(model.pv_batt[i, mon, t]),
                    "Batt_discharge_kWh_day": sv(model.batt_discharge[i, mon, t]),
                    "SOC_start_kWh": sv(model.soc[i, mon, t - 1]),
                    "SOC_end_kWh": sv(model.soc[i, mon, t]),
                }
                for c in model.C_pub:
                    for b in model.B:
                        row[f"E_{c}_{b}_kWh_day"] = sv(model.edisp[i, mon, t, c, b])
                rows.append(row)
    df = pd.DataFrame(rows)
    df.to_csv(results_dir / "hourly_energy.csv", index=False)
    return df


def export_supply_by_demand_class(model, data: dict, results_dir: Path) -> pd.DataFrame:
    """Export an accounting allocation of pooled charger-side energy by demand class.

    Grid, direct PV, and BESS discharge are pooled in the optimization energy balance.
    They are therefore allocated ex post to residual-home and public service in
    proportion to their served energy at each cell-month-slot. This preserves all
    source and demand-class totals without changing the optimization formulation.
    """
    total_home = data.get("home_demand_total_event", {})
    private_home = data.get("home_private_served_event", {})
    rows = []
    for i in model.I:
        ii = int(i)
        for mon in model.M:
            for t in model.H:
                tt = int(t)
                served_home = sum(sv(model.edisp[i, mon, t, c, "home"]) for c in model.C_pub)
                served_public = sum(sv(model.edisp[i, mon, t, c, "public"]) for c in model.C_pub)
                served_total = served_home + served_public
                home_share = served_home / served_total if served_total > 1e-12 else 0.0
                public_share = served_public / served_total if served_total > 1e-12 else 0.0
                grid = sv(model.grid_dir[i, mon, t])
                pv = sv(model.pv_dir[i, mon, t])
                bess = sv(model.batt_discharge[i, mon, t])
                allocated_total = grid + pv + bess
                rows.append({
                    "HexID": ii,
                    "Month": str(mon),
                    "TimeIndex": tt,
                    "DaysInMonth": int(data["N_MONTH"][mon]),
                    "Demand_home_total_kWh_day": float(
                        total_home.get(
                            (ii, str(mon), tt),
                            total_home.get(
                                (ii, tt),
                                sv(model.Demand[i, mon, t, "home"])
                                + float(private_home.get((ii, str(mon), tt), private_home.get((ii, tt), 0.0))),
                            ),
                        )
                    ),
                    "Demand_public_base_kWh_day": sv(model.Demand[i, mon, t, "public"]),
                    "Home_private_served_kWh_day": float(private_home.get((ii, str(mon), tt), private_home.get((ii, tt), 0.0))),
                    "Home_residual_served_by_public_kWh_day": served_home,
                    "Public_served_by_public_kWh_day": served_public,
                    "Grid_to_home_residual_allocated_kWh_day": grid * home_share,
                    "PV_to_home_residual_allocated_kWh_day": pv * home_share,
                    "BESS_to_home_residual_allocated_kWh_day": bess * home_share,
                    "Grid_to_public_allocated_kWh_day": grid * public_share,
                    "PV_to_public_allocated_kWh_day": pv * public_share,
                    "BESS_to_public_allocated_kWh_day": bess * public_share,
                    "Slack_home_kWh_day": sv(model.slack[i, mon, t, "home"]),
                    "Slack_public_kWh_day": sv(model.slack[i, mon, t, "public"]),
                    "Source_allocation_reconciliation_kWh": allocated_total - served_total,
                    "AllocationMethod": "Proportional allocation of pooled charger-side supply to served demand classes within each cell-month-slot",
                })
    df = pd.DataFrame(rows)
    df.to_csv(results_dir / "supply_by_demand_class.csv", index=False)
    return df


def export_slack(model, data: dict, results_dir: Path) -> pd.DataFrame:
    rows = []
    for i in model.I:
        for mon in model.M:
            for t in model.H:
                for b in model.B:
                    sl = sv(model.slack[i, mon, t, b])
                    if sl > 1e-8:
                        rows.append({"HexID": int(i), "Month": mon, "TimeIndex": int(t), "DemandClass": str(b), "Slack_kWh_day": sl, "Slack_kWh_annual": data["N_MONTH"][mon] * sl})
    df = pd.DataFrame(rows)
    df.to_csv(results_dir / "slack.csv", index=False)
    return df


def export_pv_diagnostics(data: dict, results_dir: Path) -> pd.DataFrame:
    df = data["pv_diag"].copy()
    df.to_csv(results_dir / "pvgis_diagnostics.csv", index=False)
    return df


def export_input_monthly_profiles(data: dict, results_dir: Path) -> pd.DataFrame:
    df = data["input_monthly_profiles"].copy()
    df.to_csv(results_dir / "input_monthly_profiles.csv", index=False)
    return df


def export_seasonal_demand_diagnostics(data: dict, results_dir: Path) -> pd.DataFrame:
    df = data["seasonal_demand_diagnostics"].copy()
    df.to_csv(results_dir / "seasonal_demand_diagnostics.csv", index=False)
    return df



def export_slack_diagnostics_by_hex(model, data: dict, results_dir: Path) -> pd.DataFrame:
    """Aggregate unmet-demand slack and base demand by cell and demand class."""
    rows = []
    for i in model.I:
        for b in model.B:
            ann_slack = sum(data["N_MONTH"][mon] * sv(model.slack[i, mon, t, b]) for mon in model.M for t in model.H)
            ann_demand = sum(data["N_MONTH"][mon] * sv(model.Demand[i, mon, t, b]) for mon in model.M for t in model.H)
            rows.append({
                "HexID": int(i),
                "DemandClass": str(b),
                "AnnualDemand_kWh": ann_demand,
                "AnnualSlack_kWh": ann_slack,
                "SlackShare": ann_slack / ann_demand if ann_demand > 1e-9 else 0.0,
            })
    df = pd.DataFrame(rows).sort_values(["AnnualSlack_kWh", "HexID"], ascending=[False, True])
    df.to_csv(results_dir / "slack_diagnostics_by_hex.csv", index=False)
    return df


def export_slack_diagnostics_by_hex_month(model, data: dict, results_dir: Path) -> pd.DataFrame:
    """Aggregate unmet-demand slack by cell, month, and class."""
    rows = []
    for i in model.I:
        for mon in model.M:
            for b in model.B:
                day_slack = sum(sv(model.slack[i, mon, t, b]) for t in model.H)
                day_demand = sum(sv(model.Demand[i, mon, t, b]) for t in model.H)
                annual_slack = data["N_MONTH"][mon] * day_slack
                if day_slack > 1e-8 or day_demand > 1e-8:
                    rows.append({
                        "HexID": int(i),
                        "Month": mon,
                        "DemandClass": str(b),
                        "RepresentativeDayDemand_kWh": day_demand,
                        "RepresentativeDaySlack_kWh": day_slack,
                        "AnnualSlack_kWh": annual_slack,
                        "SlackShare": day_slack / day_demand if day_demand > 1e-9 else 0.0,
                    })
    df = pd.DataFrame(rows).sort_values(["AnnualSlack_kWh", "HexID"], ascending=[False, True])
    df.to_csv(results_dir / "slack_diagnostics_by_hex_month.csv", index=False)
    return df


def export_capacity_binding_diagnostics(model, data: dict, results_dir: Path, tol: float = 1e-5) -> pd.DataFrame:
    """Site-slot charger type utilisation; useful for locating local capacity bottlenecks."""
    rows = []
    for i in model.I:
        for mon in model.M:
            for t in model.H:
                for c in model.C_pub:
                    served = sum(sv(model.edisp[i, mon, t, c, b]) for b in model.B)
                    cap = sv(model.K[c]) * sv(model.x[i, c])
                    ratio = served / cap if cap > 1e-9 else (1.0 if served > 1e-9 else 0.0)
                    if ratio >= 0.95 or served > 1e-8:
                        rows.append({
                            "HexID": int(i),
                            "Month": mon,
                            "TimeIndex": int(t),
                            "ChargerType": str(c),
                            "Served_kWh_slot": served,
                            "InstalledCapacity_kWh_slot": cap,
                            "UtilizationRatio": ratio,
                            "Binding95": ratio >= 0.95,
                        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["Binding95", "UtilizationRatio"], ascending=[False, False])
    df.to_csv(results_dir / "capacity_binding_diagnostics.csv", index=False)
    return df


def export_redirection_capacity_diagnostics(model, data: dict, results_dir: Path) -> pd.DataFrame:
    """Origin/destination redirection aggregates by hex to compare slack, redirection, and capacity."""
    OUT = data["OUT"]
    IN = data["IN"]
    rows = []
    for i in model.I:
        out_ann = sum(data["N_MONTH"][mon] * sv(model.z[i, j, mon, t]) for mon in model.M for t in model.H for j in OUT.get((i, mon, t), []))
        in_ann = sum(data["N_MONTH"][mon] * sv(model.z[j, i, mon, t]) for mon in model.M for t in model.H for j in IN.get((i, mon, t), []))
        slack_ann = sum(data["N_MONTH"][mon] * sv(model.slack[i, mon, t, b]) for mon in model.M for t in model.H for b in model.B)
        public_demand_ann = sum(data["N_MONTH"][mon] * sv(model.Demand[i, mon, t, "public"]) for mon in model.M for t in model.H)
        resources_used = sum(sv(model.ResourceUse[c]) * sv(model.x[i, c]) for c in model.C_pub)
        capacity_slot = sum(sv(model.K[c]) * sv(model.x[i, c]) for c in model.C_pub)
        rows.append({
            "HexID": int(i),
            "AnnualPublicDemand_kWh": public_demand_ann,
            "AnnualSlack_kWh": slack_ann,
            "AnnualRedirectionOut_kWh": out_ann,
            "AnnualRedirectionIn_kWh": in_ann,
            "NetRedirectionIn_kWh": in_ann - out_ann,
            "ChargerResourcesUsed": resources_used,
            "AvailableResources": sv(model.CL[i]),
            "ResourcesBinding": abs(resources_used - sv(model.CL[i])) <= 1e-5,
            "InstalledCapacity_kWh_slot": capacity_slot,
        })
    df = pd.DataFrame(rows).sort_values(["AnnualSlack_kWh", "AnnualPublicDemand_kWh"], ascending=[False, False])
    df.to_csv(results_dir / "redirection_capacity_diagnostics.csv", index=False)
    return df

def write_combined_xlsx(results_dir: Path, frames: dict[str, pd.DataFrame]) -> Path | None:
    out = results_dir / "combined_results.xlsx"
    try:
        with pd.ExcelWriter(out) as writer:
            for name, df in frames.items():
                df.to_excel(writer, sheet_name=name[:31], index=False)
        return out
    except Exception as exc:
        print(f"WARNING: Could not write combined XLSX ({exc}). CSV files were still written.")
        return None


def export_all(model, data: dict, cfg: dict, run_dir: Path) -> dict[str, pd.DataFrame]:
    results_dir = run_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    frames = {
        "model_summary": export_model_summary(model, data, cfg, results_dir),
        "infrastructure_by_hex": export_infrastructure(model, data, results_dir),
        "energy_by_type": export_energy_by_charger_type(model, data, results_dir),
        "redirections": export_redirections(model, data, results_dir),
        "redirections_by_type": export_redirections_by_type(model, data, results_dir),
        "origin_type_q": export_origin_type_allocation(model, data, results_dir),
        "hourly_energy": export_hourly_energy(model, data, results_dir),
        "supply_by_demand_class": export_supply_by_demand_class(model, data, results_dir),
        "slack": export_slack(model, data, results_dir),
        "slack_diag_hex": export_slack_diagnostics_by_hex(model, data, results_dir),
        "slack_diag_month": export_slack_diagnostics_by_hex_month(model, data, results_dir),
        "capacity_binding": export_capacity_binding_diagnostics(model, data, results_dir),
        "redir_capacity_diag": export_redirection_capacity_diagnostics(model, data, results_dir),
        "pvgis_diagnostics": export_pv_diagnostics(data, results_dir),
        "input_monthly_profiles": export_input_monthly_profiles(data, results_dir),
        "seasonal_demand_diag": export_seasonal_demand_diagnostics(data, results_dir),
    }
    xlsx_path = write_combined_xlsx(results_dir, frames)
    if xlsx_path:
        print(f"Combined XLSX written to: {xlsx_path}")
    print(f"Output files written to: {results_dir}")
    return frames


def print_summary(model, data: dict, cfg: dict) -> None:
    metrics = compute_core_metrics(model, data, cfg)
    print("\n================  OPTIMAL ANNUAL PROFIT  ================")
    print(f"Total profit : {metrics['annual_profit_SEK']:,.0f} SEK / yr\n")
    print("==================  BREAKDOWN  =================")
    print(f"Revenue (all chargers)             : {metrics['revenue_all_chargers_SEK']:>13,.0f}")
    print(f"Opex - grid purchases              : {metrics['grid_cost_SEK']:>13,.0f}")
    print(f"Opex - redirection distance        : {metrics['redirection_distance_cost_SEK']:>13,.0f}")
    print(f"Opex - redirection price comp.     : {metrics['redirection_price_compensation_SEK']:>13,.0f}")
    print(f"Opex - unmet-demand penalty        : {metrics['slack_penalty_SEK']:>13,.0f}")
    print(f"Capex - chargers                   : {metrics['capex_chargers_SEK']:>13,.0f}")
    print(f"Capex - PV & batteries             : {metrics['capex_PV_BESS_SEK']:>13,.0f}")
    print("----------------------------------------------------------")
    for c in data["PUB_TYPES"]:
        print(f"{c.capitalize():<6} chargers: {metrics[f'chargers_{c}_installed']:>10,.0f} | energy: {metrics[f'energy_{c}_kWh']:>13,.1f} | cap ratio: {metrics[f'capacity_ratio_{c}']:.3f}")
    print("==========================================================\n")
