"""Modified for the UrbanEV seasonal integration, 2026-10-22. See SOURCE_PROVENANCE.json."""
from __future__ import annotations
from energy_accounting import energy_boundary_metrics

from pathlib import Path
import pandas as pd
import pyomo.environ as pyo


def sv(x, default=0.0):
    try:
        v = pyo.value(x)
        return default if v is None else float(v)
    except Exception:
        try:
            return float(x)
        except Exception:
            return default


def core_metrics(m, data, cfg, type_rows=None, certified_lb=None):
    N, days = data["N_MONTH"], data["DAYS"]
    rev = sum(N[mon] * sv(m.Price[c]) * sv(m.edisp[i, mon, t, c, b]) for i in m.I for mon in m.M for t in m.H for b in m.B for c in m.C_pub)
    grid_direct_cost = sum(N[mon] * sv(m.tou[mon, t]) * sv(m.grid_dir[i, mon, t]) for i in m.I for mon in m.M for t in m.H)
    grid_battery_cost = sum(N[mon] * sv(m.tou[mon, t]) * sv(m.grid_batt[i, mon, t]) for i in m.I for mon in m.M for t in m.H)
    grid = grid_direct_cost + grid_battery_cost
    dist = sum(N[mon] * (sv(m.T[i, j]) * sv(m.n_trip[i, j, mon, t]) + (sv(m.T[i, j]) / sv(m.x_kWh)) * sv(m.r_tail[i, j, mon, t])) for (i, j, mon, t) in m.A)
    theta_model = sum(sv(m.ThetaType[mon, t]) for mon in m.M for t in m.H)
    theta_reconstructed = None
    if type_rows:
        try:
            theta_reconstructed = float(sum(float(r.get("PriceComp_SEK_annual", 0.0)) for r in type_rows))
        except Exception:
            theta_reconstructed = None
    theta = theta_reconstructed if theta_reconstructed is not None else theta_model
    slack = float(cfg["penalty_per_kwh_slack"]) * sum(N[mon] * sv(m.slack[i, mon, t, b]) for i in m.I for mon in m.M for t in m.H for b in m.B)
    cap_ch = days * sum(sv(m.PVF_cost[c]) * sv(m.x[i, c]) for i in m.I for c in m.C_pub)
    cap_pv = days * sum(sv(m.PVF_PV) * sv(m.PV[i]) for i in m.I)
    cap_bess = days * sum(sv(m.PVF_Batt) * sv(m.Batt[i]) for i in m.I)
    cap_en = cap_pv + cap_bess
    redir = sum(N[mon] * sv(m.G[i, j, mon, t]) for (i, j, mon, t) in m.A)
    out_r = sum(N[mon] * sv(m.R[i, mon, t, c]) for i in m.I for mon in m.M for t in m.H for c in m.C_pub)
    in_w = sum(N[mon] * sv(m.W[i, mon, t, c]) for i in m.I for mon in m.M for t in m.H for c in m.C_pub)
    grid_dir = sum(N[mon] * sv(m.grid_dir[i, mon, t]) for i in m.I for mon in m.M for t in m.H)
    grid_batt = sum(N[mon] * sv(m.grid_batt[i, mon, t]) for i in m.I for mon in m.M for t in m.H)
    pv_dir = sum(N[mon] * sv(m.pv_dir[i, mon, t]) for i in m.I for mon in m.M for t in m.H)
    pv_batt = sum(N[mon] * sv(m.pv_batt[i, mon, t]) for i in m.I for mon in m.M for t in m.H)
    batt_dis = sum(N[mon] * sv(m.batt_discharge[i, mon, t]) for i in m.I for mon in m.M for t in m.H)
    annual_public_demand = sum(
        N[mon] * sv(m.Demand[i, mon, t, "public"])
        for i in m.I for mon in m.M for t in m.H
    )
    annual_slack = sum(
        N[mon] * sv(m.slack[i, mon, t, b])
        for i in m.I for mon in m.M for t in m.H for b in m.B
    )
    public_capacity_slot = sum(sv(m.K[c]) * sv(m.x[i, c]) for i in m.I for c in m.C_pub)
    active_arcs = sum(1 for a in m.A if sv(m.G[a]) > 1e-8)
    out = {
        "dataset": data.get("dataset", "unknown"),
        "vipv_scenario": data.get("vipv_scenario", "unknown"),
        "annual_profit_SEK": (certified_lb if certified_lb is not None else rev - grid - dist - theta - slack - cap_ch - cap_en),
        "master_objective_SEK": sv(m.obj),
        "revenue_all_chargers_SEK": rev,
        "grid_cost_SEK": grid,
        "grid_direct_cost_SEK": grid_direct_cost,
        "grid_to_battery_cost_SEK": grid_battery_cost,
        "redirection_distance_cost_SEK": dist,
        "redirection_price_compensation_SEK": theta,
        "theta_master_variable_SEK": theta_model,
        "redirection_total_cost_SEK": dist + theta,
        "slack_penalty_SEK": slack,
        "capex_chargers_SEK": cap_ch,
        "capex_PV_SEK": cap_pv,
        "capex_BESS_SEK": cap_bess,
        "capex_PV_BESS_SEK": cap_en,
        "grid_direct_kWh": grid_dir,
        "grid_to_battery_kWh": grid_batt,
        "grid_total_kWh": grid_dir + grid_batt,
        "pv_direct_kWh": pv_dir,
        "pv_to_battery_kWh": pv_batt,
        "pv_used_total_kWh": pv_dir + pv_batt,
        "battery_discharge_kWh": batt_dis,
        "annual_public_demand_kWh": annual_public_demand,
        "energy_redirected_kWh": redir,
        "share_redirected_public_demand": redir / annual_public_demand if annual_public_demand > 0 else 0.0,
        "public_charger_capacity_kWh_per_slot": public_capacity_slot,
        "annual_slack_kWh": annual_slack,
        "redirection_trip_equivalents_annual": redir / sv(m.x_kWh) if sv(m.x_kWh) > 0 else 0.0,
        "redirection_full_trip_bundles_annual": sum(N[mon] * sv(m.n_trip[i, j, mon, t]) for (i, j, mon, t) in m.A),
        "R_outgoing_kWh": out_r,
        "W_incoming_kWh": in_w,
        "active_redirection_arcs": active_arcs,
        "PV_panels_installed": sum(sv(m.PV[i]) for i in m.I),
        "battery_units_installed": sum(sv(m.Batt[i]) for i in m.I),
        "max_abs_soc_gap_Jan0_Dec48_kWh": max(abs(sv(m.soc[i, "December", max(m.H)]) - sv(m.soc[i, "January", 0])) for i in m.I),
    }
    out.update(energy_boundary_metrics(m, data, cfg))
    residual_home = sum(N[mon] * sv(m.Demand[i, mon, t, "home"]) for i in m.I for mon in m.M for t in m.H)
    total_home = sum(N[mon] * data["home_demand_total_event"].get((int(i), str(mon), int(t)), 0.0) for i in m.I for mon in m.M for t in m.H)
    private_home = sum(N[mon] * data["home_private_served_event"].get((int(i), str(mon), int(t)), 0.0) for i in m.I for mon in m.M for t in m.H)
    out.update(annual_home_residual_demand_kWh=residual_home, annual_home_demand_total_kWh=total_home,
               annual_home_private_served_kWh=private_home, annual_optimizer_boundary_demand_kWh=annual_public_demand + residual_home,
               annual_total_MATSim_charging_demand_kWh=annual_public_demand + total_home,
               home_chargers_exogenous=sum(data["home_avail"].get(int(i), 0.0) for i in m.I))
    for c in data["PUB_TYPES"]:
        installed = sum(sv(m.x[i, c]) for i in m.I)
        energy = sum(N[mon] * sv(m.edisp[i, mon, t, c, b]) for i in m.I for mon in m.M for t in m.H for b in m.B)
        cap = installed * sv(m.K[c]) * len(list(m.H)) * days
        revenue_c = sum(N[mon] * sv(m.Price[c]) * sv(m.edisp[i, mon, t, c, b]) for i in m.I for mon in m.M for t in m.H for b in m.B)
        capex_c = days * sum(sv(m.PVF_cost[c]) * sv(m.x[i, c]) for i in m.I)
        out[f"chargers_{c}_installed"] = installed
        out[f"energy_{c}_kWh"] = energy
        out[f"revenue_{c}_SEK"] = revenue_c
        out[f"capex_chargers_{c}_SEK"] = capex_c
        out[f"capacity_upper_bound_{c}_kWh"] = cap
        out[f"capacity_ratio_{c}"] = energy / cap if cap > 0 else 0.0
        out[f"R_outgoing_{c}_kWh"] = sum(N[mon] * sv(m.R[i, mon, t, c]) for i in m.I for mon in m.M for t in m.H)
        out[f"W_incoming_{c}_kWh"] = sum(N[mon] * sv(m.W[i, mon, t, c]) for i in m.I for mon in m.M for t in m.H)
        out[f"q_origin_{c}_kWh"] = sum(N[mon] * sv(m.q[i, mon, t, c]) for i in m.I for mon in m.M for t in m.H)
    return out


def quality_checks(m, data):
    OUT, IN = data["OUT"], data["IN"]
    max_energy = max(abs(sv(m.grid_dir[i, mon, t]) + sv(m.pv_dir[i, mon, t]) + sv(m.batt_discharge[i, mon, t]) - sum(sv(m.edisp[i, mon, t, c, b]) for c in m.C_pub for b in m.B)) for i in m.I for mon in m.M for t in m.H)
    max_out = max(abs(sum(sv(m.G[i, int(j), mon, t]) for j in OUT.get((int(i), mon, int(t)), [])) - sum(sv(m.R[i, mon, t, c]) for c in m.C_pub)) for i in m.I for mon in m.M for t in m.H)
    max_in = max(abs(sum(sv(m.G[int(i), j, mon, t]) for i in IN.get((int(j), mon, int(t)), [])) - sum(sv(m.W[j, mon, t, c]) for c in m.C_pub)) for j in m.I for mon in m.M for t in m.H)
    max_soc = max(abs(sv(m.soc[i, mon, t]) - sv(m.soc[i, mon, t - 1]) - sv(m.eta_ch) * (sv(m.grid_batt[i, mon, t]) + sv(m.pv_batt[i, mon, t])) + (1.0 / sv(m.eta_dis)) * sv(m.batt_discharge[i, mon, t])) for i in m.I for mon in m.M for t in m.H)
    max_trip = max(abs(sv(m.G[i, j, mon, t]) - sv(m.x_kWh) * sv(m.n_trip[i, j, mon, t]) - sv(m.r_tail[i, j, mon, t])) for (i, j, mon, t) in m.A) if len(m.A) else 0.0
    demand_public = []
    demand_home = []
    q_resid = []
    for i in m.I:
        for mon in m.M:
            for t in m.H:
                demand_home.append(abs(sum(sv(m.edisp[i, mon, t, c, "home"]) for c in m.C_pub) + sv(m.slack[i, mon, t, "home"]) - sv(m.Demand[i, mon, t, "home"])))
                demand_public.append(abs(sum(sv(m.edisp[i, mon, t, c, "public"]) for c in m.C_pub) + sv(m.slack[i, mon, t, "public"]) - sv(m.Demand[i, mon, t, "public"]) + sum(sv(m.R[i, mon, t, c]) for c in m.C_pub) - sum(sv(m.W[i, mon, t, c]) for c in m.C_pub)))
                q_resid.append(abs(sum(sv(m.q[i, mon, t, c]) for c in m.C_pub) + sv(m.slack[i, mon, t, "public"]) - sv(m.Demand[i, mon, t, "public"])))
    total_slack = sum(data["N_MONTH"][mon] * sv(m.slack[i, mon, t, b]) for i in m.I for mon in m.M for t in m.H for b in m.B)
    return pd.DataFrame([
        {"check": "max_energy_balance_abs_kWh", "value": max_energy},
        {"check": "max_aggregate_outflow_abs_kWh", "value": max_out},
        {"check": "max_aggregate_inflow_abs_kWh", "value": max_in},
        {"check": "max_trip_decomposition_abs_kWh", "value": max_trip},
        {"check": "max_home_demand_cover_abs_kWh", "value": max(demand_home) if demand_home else 0.0},
        {"check": "max_public_demand_cover_abs_kWh", "value": max(demand_public) if demand_public else 0.0},
        {"check": "max_q_origin_allocation_abs_kWh", "value": max(q_resid) if q_resid else 0.0},
        {"check": "max_soc_dynamics_abs_kWh", "value": max_soc},
        {"check": "annual_slack_kWh", "value": total_slack},
    ])



def type_assignment_marginal_residuals(m, type_rows):
    origin = {}
    dest = {}
    arc = {}
    for r in type_rows or []:
        val = float(r.get("Energy_kWh_day", 0.0) or 0.0)
        i = int(r["from_HexID"]); j = int(r["to_HexID"])
        mon = str(r["Month"]); t = int(r["TimeIndex"])
        co = str(r["OriginType"]); cd = str(r["DestinationType"])
        origin[(i, mon, t, co)] = origin.get((i, mon, t, co), 0.0) + val
        dest[(j, mon, t, cd)] = dest.get((j, mon, t, cd), 0.0) + val
        arc[(i, j, mon, t)] = arc.get((i, j, mon, t), 0.0) + val
    max_r = max((abs(origin.get((int(i), str(mon), int(t), str(c)), 0.0) - sv(m.R[i, mon, t, c])) for i in m.I for mon in m.M for t in m.H for c in m.C_pub), default=0.0)
    max_w = max((abs(dest.get((int(j), str(mon), int(t), str(c)), 0.0) - sv(m.W[j, mon, t, c])) for j in m.I for mon in m.M for t in m.H for c in m.C_pub), default=0.0)
    max_g = max((abs(arc.get((int(i), int(j), str(mon), int(t)), 0.0) - sv(m.G[i, j, mon, t])) for (i, j, mon, t) in m.A), default=0.0)
    return max_r, max_w, max_g

def supply_by_demand_class_frame(m, data):
    """Accounting allocation of pooled charger-side energy by demand class."""
    total_home = data.get("home_demand_total_event", {})
    private_home = data.get("home_private_served_event", {})
    rows = []
    for i in m.I:
        ii = int(i)
        for mon in m.M:
            for t in m.H:
                tt = int(t)
                served_home = sum(sv(m.edisp[i, mon, t, c, "home"]) for c in m.C_pub)
                served_public = sum(sv(m.edisp[i, mon, t, c, "public"]) for c in m.C_pub)
                served_total = served_home + served_public
                home_share = served_home / served_total if served_total > 1e-12 else 0.0
                public_share = served_public / served_total if served_total > 1e-12 else 0.0
                grid = sv(m.grid_dir[i, mon, t])
                pv = sv(m.pv_dir[i, mon, t])
                bess = sv(m.batt_discharge[i, mon, t])
                rows.append({
                    "HexID": ii,
                    "Month": str(mon),
                    "TimeIndex": tt,
                    "DaysInMonth": int(data["N_MONTH"][mon]),
                    "Demand_home_total_kWh_day": float(total_home.get((ii, tt), sv(m.Demand[i, mon, t, "home"]) + float(private_home.get((ii, tt), 0.0)))),
                    "Demand_public_base_kWh_day": sv(m.Demand[i, mon, t, "public"]),
                    "Home_private_served_kWh_day": float(private_home.get((ii, tt), 0.0)),
                    "Home_residual_served_by_public_kWh_day": served_home,
                    "Public_served_by_public_kWh_day": served_public,
                    "Grid_to_home_residual_allocated_kWh_day": grid * home_share,
                    "PV_to_home_residual_allocated_kWh_day": pv * home_share,
                    "BESS_to_home_residual_allocated_kWh_day": bess * home_share,
                    "Grid_to_public_allocated_kWh_day": grid * public_share,
                    "PV_to_public_allocated_kWh_day": pv * public_share,
                    "BESS_to_public_allocated_kWh_day": bess * public_share,
                    "Slack_home_kWh_day": sv(m.slack[i, mon, t, "home"]),
                    "Slack_public_kWh_day": sv(m.slack[i, mon, t, "public"]),
                    "Source_allocation_reconciliation_kWh": (grid + pv + bess) - served_total,
                    "AllocationMethod": "Proportional allocation of pooled charger-side supply to served demand classes within each cell-month-slot",
                })
    return pd.DataFrame(rows)


def export_all(m, data, cfg, run_dir: Path, type_rows=None, history=None, sp_summary=None, cut_records=None, certified_lb=None):
    rd = run_dir / "results"
    rd.mkdir(parents=True, exist_ok=True)
    frames = {}
    metrics = core_metrics(m, data, cfg, type_rows=type_rows, certified_lb=certified_lb)
    metrics["vipv_scenario"] = data.get("vipv_scenario", "unknown")
    from export_results import export_input_monthly_profiles, export_seasonal_demand_diagnostics
    export_input_monthly_profiles(data, rd)
    export_seasonal_demand_diagnostics(data, rd)
    frames["model_summary"] = pd.DataFrame([{"Metric": k, "Value": v} for k, v in metrics.items()])
    frames["infrastructure_by_hex"] = pd.DataFrame([{**{"HexID": int(i)}, **{f"{c}_chargers": sv(m.x[i, c]) for c in m.C_pub}, **{f"{c}_capacity_kWh_slot": sv(m.K[c]) * sv(m.x[i, c]) for c in m.C_pub}, "PV_panels": sv(m.PV[i]), "Battery_units": sv(m.Batt[i]), "Total_public_capacity_kWh_slot": sum(sv(m.K[c]) * sv(m.x[i, c]) for c in m.C_pub)} for i in m.I]).sort_values("HexID")
    rows = []
    for c in m.C_pub:
        installed = sum(sv(m.x[i, c]) for i in m.I)
        annual_capacity = installed * sv(m.K[c]) * len(list(m.H)) * data["DAYS"]
        for b in list(m.B) + ["ALL"]:
            energy = sum(data["N_MONTH"][mon] * sv(m.edisp[i, mon, t, c, bb]) for i in m.I for mon in m.M for t in m.H for bb in (m.B if b == "ALL" else [b]))
            rows.append({"ChargerType": str(c), "DemandClass": str(b), "AnnualEnergy_kWh": energy, "InstalledChargers": installed, "AnnualCapacity_kWh": annual_capacity, "CapacityRatio_all_classes": energy / annual_capacity if b == "ALL" and annual_capacity > 0 else None})
    frames["energy_by_type"] = pd.DataFrame(rows)
    redir = []
    for (i, j, mon, t) in m.A:
        g = sv(m.G[i, j, mon, t])
        if g > 1e-8:
            redir.append({"from_HexID": int(i), "to_HexID": int(j), "Month": mon, "TimeIndex": int(t), "Distance_km": data["dist_dict"].get((int(i), int(j))), "Energy_kWh_day": g, "Energy_kWh_annual": data["N_MONTH"][mon] * g, "Yarc": sv(m.Yarc[i, j, mon, t]), "Trips": sv(m.n_trip[i, j, mon, t]), "Tail_kWh": sv(m.r_tail[i, j, mon, t])})
    frames["redirections"] = pd.DataFrame(redir, columns=["from_HexID", "to_HexID", "Month", "TimeIndex", "Distance_km", "Energy_kWh_day", "Energy_kWh_annual", "Yarc", "Trips", "Tail_kWh"])
    if type_rows:
        frames["redirections_by_type"] = pd.DataFrame(type_rows)
    else:
        frames["redirections_by_type"] = pd.DataFrame(columns=["from_HexID", "to_HexID", "Month", "TimeIndex", "OriginType", "DestinationType", "Energy_kWh_day", "Energy_kWh_annual", "DeltaPrice_SEK_per_kWh", "PriceComp_SEK_day", "PriceComp_SEK_annual", "note"])
    frames["origin_type_q"] = pd.DataFrame([{"HexID": int(i), "Month": mon, "TimeIndex": int(t), "OriginType": str(c), "q_origin_baseline_kWh_day": sv(m.q[i, mon, t, c]), "q_origin_baseline_kWh_annual": data["N_MONTH"][mon] * sv(m.q[i, mon, t, c]), "R_out_kWh_day": sv(m.R[i, mon, t, c]), "R_out_kWh_annual": data["N_MONTH"][mon] * sv(m.R[i, mon, t, c])} for i in m.I for mon in m.M for t in m.H for c in m.C_pub])
    frames["destination_type_w"] = pd.DataFrame([{"HexID": int(i), "Month": mon, "TimeIndex": int(t), "DestinationType": str(c), "W_in_kWh_day": sv(m.W[i, mon, t, c]), "W_in_kWh_annual": data["N_MONTH"][mon] * sv(m.W[i, mon, t, c]), "E_public_by_dest_type_kWh_day": sv(m.edisp[i, mon, t, c, "public"]), "E_public_by_dest_type_kWh_annual": data["N_MONTH"][mon] * sv(m.edisp[i, mon, t, c, "public"])} for i in m.I for mon in m.M for t in m.H for c in m.C_pub])
    type_cost_by_slot = {}
    if type_rows:
        for r in type_rows:
            key = (r.get("Month"), int(r.get("TimeIndex")))
            type_cost_by_slot[key] = type_cost_by_slot.get(key, 0.0) + float(r.get("PriceComp_SEK_annual", 0.0))
    slot_rows = []
    for mon in m.M:
        for t in m.H:
            slot_rows.append({"Month": mon, "TimeIndex": int(t), "G_kWh_day": sum(sv(m.G[i, j, mon, t]) for (i, j, mm, tt) in m.A if mm == mon and tt == t), "R_kWh_day": sum(sv(m.R[i, mon, t, c]) for i in m.I for c in m.C_pub), "W_kWh_day": sum(sv(m.W[i, mon, t, c]) for i in m.I for c in m.C_pub), "ThetaType_master_SEK": sv(m.ThetaType[mon, t]), "TypeAssignmentCost_reconstructed_SEK": type_cost_by_slot.get((mon, int(t)), 0.0)})
    frames["redirection_slot_balance"] = pd.DataFrame(slot_rows)
    frames["hourly_energy"] = pd.DataFrame([{"HexID": int(i), "Month": mon, "TimeIndex": int(t), "Demand_home_kWh_day": sv(m.Demand[i, mon, t, "home"]), "Demand_public_base_kWh_day": sv(m.Demand[i, mon, t, "public"]), "Redirect_out_kWh_day": sum(sv(m.G[i, int(j), mon, t]) for j in data["OUT"].get((int(i), mon, int(t)), [])), "Redirect_in_kWh_day": sum(sv(m.G[int(j), i, mon, t]) for j in data["IN"].get((int(i), mon, int(t)), [])), "Grid_direct_kWh_day": sv(m.grid_dir[i, mon, t]), "Grid_batt_kWh_day": sv(m.grid_batt[i, mon, t]), "PV_direct_kWh_day": sv(m.pv_dir[i, mon, t]), "PV_batt_kWh_day": sv(m.pv_batt[i, mon, t]), "Batt_discharge_kWh_day": sv(m.batt_discharge[i, mon, t]), "SOC_start_kWh": sv(m.soc[i, mon, t - 1]), "SOC_end_kWh": sv(m.soc[i, mon, t]), **{f"E_{c}_{b}_kWh_day": sv(m.edisp[i, mon, t, c, b]) for c in m.C_pub for b in m.B}} for i in m.I for mon in m.M for t in m.H])
    frames["supply_by_demand_class"] = supply_by_demand_class_frame(m, data)
    frames["slack"] = pd.DataFrame([{"HexID": int(i), "Month": mon, "TimeIndex": int(t), "DemandClass": str(b), "Slack_kWh_day": sv(m.slack[i, mon, t, b]), "Slack_kWh_annual": data["N_MONTH"][mon] * sv(m.slack[i, mon, t, b])} for i in m.I for mon in m.M for t in m.H for b in m.B if sv(m.slack[i, mon, t, b]) > 1e-8], columns=["HexID", "Month", "TimeIndex", "DemandClass", "Slack_kWh_day", "Slack_kWh_annual"])
    frames["quality_checks"] = quality_checks(m, data)
    frames["pvgis_diagnostics"] = data["pv_diag"].copy()
    if history is not None:
        frames["benders_iteration_history"] = history.copy()
    if sp_summary is not None:
        frames["type_assignment_subproblem_summary"] = sp_summary.copy()
    if cut_records is not None:
        frames["type_assignment_cuts"] = cut_records.copy()

    # Certification/export diagnostics used for certified Benders reproducibility.
    redir_energy = float(frames["redirections"].get("Energy_kWh_annual", pd.Series(dtype=float)).sum()) if "redirections" in frames else 0.0
    type_energy = float(frames["redirections_by_type"].get("Energy_kWh_annual", pd.Series(dtype=float)).sum()) if "redirections_by_type" in frames else 0.0
    type_price = float(frames["redirections_by_type"].get("PriceComp_SEK_annual", pd.Series(dtype=float)).sum()) if "redirections_by_type" in frames else 0.0
    slot_g = float(frames["redirection_slot_balance"].get("G_kWh_day", pd.Series(dtype=float)).sum()) if "redirection_slot_balance" in frames else 0.0
    slot_r = float(frames["redirection_slot_balance"].get("R_kWh_day", pd.Series(dtype=float)).sum()) if "redirection_slot_balance" in frames else 0.0
    slot_w = float(frames["redirection_slot_balance"].get("W_kWh_day", pd.Series(dtype=float)).sum()) if "redirection_slot_balance" in frames else 0.0
    theta_metric = float(metrics.get("redirection_price_compensation_SEK", 0.0) or 0.0)
    max_type_r, max_type_w, max_type_g = type_assignment_marginal_residuals(m, type_rows)
    frames["type_assignment_marginal_checks"] = pd.DataFrame([
        {"check": "max_origin_type_R_reconstruction_abs_kWh_day", "value": max_type_r},
        {"check": "max_destination_type_W_reconstruction_abs_kWh_day", "value": max_type_w},
        {"check": "max_arc_G_reconstruction_abs_kWh_day", "value": max_type_g},
    ])
    checks = [
        {"check": "annual_redirection_energy_match_G_vs_type_kWh", "value": abs(redir_energy - type_energy), "tolerance": 1e-4, "passed": abs(redir_energy - type_energy) <= 1e-4 if type_energy > 0 or redir_energy > 0 else True},
        {"check": "annual_price_compensation_match_SEK", "value": abs(theta_metric - type_price), "tolerance": 1e-4, "passed": abs(theta_metric - type_price) <= 1e-4},
        {"check": "slot_G_R_day_sum_match_kWh", "value": abs(slot_g - slot_r), "tolerance": 1e-6, "passed": abs(slot_g - slot_r) <= 1e-6},
        {"check": "slot_G_W_day_sum_match_kWh", "value": abs(slot_g - slot_w), "tolerance": 1e-6, "passed": abs(slot_g - slot_w) <= 1e-6},
        {"check": "max_origin_type_R_reconstruction_abs_kWh_day", "value": max_type_r, "tolerance": 1e-6, "passed": max_type_r <= 1e-6},
        {"check": "max_destination_type_W_reconstruction_abs_kWh_day", "value": max_type_w, "tolerance": 1e-6, "passed": max_type_w <= 1e-6},
        {"check": "max_arc_G_reconstruction_abs_kWh_day", "value": max_type_g, "tolerance": 1e-6, "passed": max_type_g <= 1e-6},
    ]
    for _, r in frames["quality_checks"].iterrows():
        tol = 1e-5 if "annual_slack" not in str(r["check"]) else 1e-4
        checks.append({"check": str(r["check"]), "value": float(r["value"]), "tolerance": tol, "passed": abs(float(r["value"])) <= tol})
    frames["export_consistency_checks"] = pd.DataFrame(checks)
    if history is not None and len(history):
        h = history.copy()
        last = h.iloc[-1]
        best_idx = h["best_LB_SEK"].astype(float).idxmax() if "best_LB_SEK" in h else h.index[-1]
        best_row = h.loc[best_idx]
        frames["benders_bounds_summary"] = pd.DataFrame([
            {"metric": "best_certified_LB_SEK", "value": float(best_row.get("best_LB_SEK", float("nan")))},
            {"metric": "global_best_UB_SEK", "value": float(last.get("global_best_UB_SEK", float("nan")))},
            {"metric": "final_Benders_gap", "value": float(last.get("Benders_gap", float("nan")))},
            {"metric": "best_certified_iteration", "value": int(best_row.get("iteration", -1))},
            {"metric": "final_iteration", "value": int(last.get("iteration", -1))},
            {"metric": "final_cuts_added", "value": int(last.get("cuts_added", 0))},
            {"metric": "final_bad_slots", "value": int(last.get("bad_slots", 0))},
            {"metric": "final_max_theta_violation_SEK", "value": float(last.get("max_theta_violation_SEK", 0.0))},
        ])

    for name, df in frames.items():
        df.to_csv(rd / f"{name if name != 'energy_by_type' else 'energy_by_charger_type'}.csv", index=False)
    try:
        with pd.ExcelWriter(rd / "combined_results.xlsx") as writer:
            for name, df in frames.items():
                df.to_excel(writer, sheet_name=name[:31], index=False)
    except Exception as exc:
        print(f"WARNING: combined_results.xlsx was not written: {exc}")
    print(f"Output files written to: {rd}")
    return frames


def print_summary(m, data, cfg):
    x = core_metrics(m, data, cfg)
    print("\n================ Benders MASTER SUMMARY ================")
    print(f"Total profit : {x['annual_profit_SEK']:,.0f} SEK / yr")
    print(f"Revenue      : {x['revenue_all_chargers_SEK']:,.0f}")
    print(f"Grid cost    : {x['grid_cost_SEK']:,.0f}")
    print(f"Redir dist   : {x['redirection_distance_cost_SEK']:,.0f}")
    print(f"Theta type   : {x['redirection_price_compensation_SEK']:,.0f}")
    print(f"Slack pen.   : {x['slack_penalty_SEK']:,.0f}")
    print(f"Charger capex: {x['capex_chargers_SEK']:,.0f}")
    print(f"PV+BESS capex: {x['capex_PV_BESS_SEK']:,.0f}")
    print(f"Redirected   : {x['energy_redirected_kWh']:,.0f} kWh/yr over {x['active_redirection_arcs']:,.0f} arc-slots")
    for c in data["PUB_TYPES"]:
        print(f"{c:<6} chargers: {x[f'chargers_{c}_installed']:,.0f}")
    print("============================================================\n")
