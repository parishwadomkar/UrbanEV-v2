from __future__ import annotations

import math
from pyomo.environ import (
    Any,
    Binary,
    ConcreteModel,
    Constraint,
    NonNegativeIntegers,
    NonNegativeReals,
    Objective,
    Param,
    Set,
    Var,
    maximize,
    quicksum,
)


def build_model(data: dict, cfg: dict):
    """Build the June-14 type-aware EV CPO MILP from the uploaded notebook."""
    model = ConcreteModel()

    I = data["hex_ids"]
    M = data["MONTHS"]
    H = data["INTERVALS"]
    Hsoc = data["HSOC"]
    C_pub = data["PUB_TYPES"]
    B = data["DEMAND_CLASSES"]
    A = data["allowed_st"]

    model.I = Set(initialize=I)
    model.M = Set(initialize=M)
    model.H = Set(initialize=H)
    model.Hsoc = Set(initialize=Hsoc)
    model.A = Set(dimen=4, initialize=A)
    model.ORIGIN_ST = Set(dimen=3, initialize=data["ORIGIN_ST"])
    model.DEST_ST = Set(dimen=3, initialize=data["DEST_ST"])
    model.D = Set(within=model.I * model.I, initialize=data["allowed"])
    model.C = Set(initialize=C_pub)
    model.C_pub = Set(initialize=C_pub)
    model.B = Set(initialize=B)

    model.Price = Param(model.C_pub, initialize=data["charger_price"])
    model.DeltaPrice = Param(model.C_pub, model.C_pub, initialize=data["delta_price"], within=NonNegativeReals)
    model.Demand = Param(model.I, model.M, model.H, model.B, initialize=data["demand_event_annual"], within=NonNegativeReals)
    model.K = Param(model.C_pub, initialize=data["charger_capacity_pub"])
    model.ResourceUse = Param(model.C_pub, initialize=data["charger_resources"])
    model.PVF_cost = Param(model.C_pub, initialize=lambda m, c: data["daily_cost"][c])
    model.PVF_PV = Param(initialize=data["daily_cost"]["PV"])
    model.PVF_Batt = Param(initialize=data["daily_cost"]["Batt"])
    model.CL = Param(model.I, initialize=data["cl"])
    model.T = Param(model.D, initialize=data["T_dict"])
    model.tou = Param(model.M, model.H, initialize=lambda m, mon, t: data["tou"][mon][t], mutable=False)
    model.PV_panel_cap = Param(initialize=data["pv_kwh_per_panel_slot_at_cf1"])
    model.p_pv = Param(model.M, model.H, initialize=lambda m, mon, t: data["pv_cf"][mon][t])
    model.PV_upper = Param(model.I, initialize=data["pv_upper"])
    model.x_kWh = Param(initialize=float(cfg["x_kwh_per_trip"]))
    model.Batt_cell_cap = Param(initialize=float(cfg["battery_cell_cap_kwh"]))
    model.eta_ch = Param(initialize=float(cfg["eta_charge"]))
    model.eta_dis = Param(initialize=float(cfg["eta_discharge"]))
    model.rho = Param(initialize=float(cfg["rho_half_hours_per_hour"]))
    model.alpha_soc = Param(initialize=float(cfg["initial_soc_fraction"]))
    model.beta_min_soc = Param(initialize=float(cfg["soc_min_fraction"]))
    model.beta_max_soc = Param(initialize=float(cfg["soc_max_fraction"]))
    model.K_batt = Param(initialize=data["K_BATT"])
    model.M_batt = Param(model.I, initialize=lambda m, i: data["M_BATT"][int(i)], within=NonNegativeReals)
    model.M_redir = Param(model.I, initialize=lambda m, j: data["M_REDIR"][int(j)], within=NonNegativeReals)
    model.prev_mon = Param(model.M, initialize=data["prev_month"], within=Any)
    model.Ndays = Param(model.M, initialize=lambda m, mon: data["N_MONTH"][mon])

    def x_bounds(m, i, c):
        return (0, int(math.floor(data["cl"][int(i)] / data["charger_resources"][c])))

    def pv_bounds(m, i):
        return (0, data["pv_upper"][int(i)])

    def batt_bounds(m, i):
        return (0, int(cfg["battery_max_units_per_hex"]))

    model.x = Var(model.I, model.C_pub, domain=NonNegativeIntegers, bounds=x_bounds)
    model.PV = Var(model.I, domain=NonNegativeIntegers, bounds=pv_bounds)
    model.Batt = Var(model.I, domain=NonNegativeIntegers, bounds=batt_bounds)
    model.edisp = Var(model.I, model.M, model.H, model.C_pub, model.B, domain=NonNegativeReals)
    model.grid_dir = Var(model.I, model.M, model.H, domain=NonNegativeReals)
    model.grid_batt = Var(model.I, model.M, model.H, domain=NonNegativeReals)
    model.pv_dir = Var(model.I, model.M, model.H, domain=NonNegativeReals)
    model.pv_batt = Var(model.I, model.M, model.H, domain=NonNegativeReals)
    model.batt_discharge = Var(model.I, model.M, model.H, domain=NonNegativeReals)
    model.soc = Var(model.I, model.M, model.Hsoc, domain=NonNegativeReals)
    model.delta = Var(model.I, model.M, model.H, domain=Binary)
    model.slack = Var(model.I, model.M, model.H, model.B, domain=NonNegativeReals)
    model.z = Var(model.A, domain=NonNegativeReals)
    model.z_od = Var(model.A, model.C_pub, model.C_pub, domain=NonNegativeReals)
    model.q = Var(model.I, model.M, model.H, model.C_pub, domain=NonNegativeReals)
    model.Yarc = Var(model.A, domain=Binary)
    model.n_trip = Var(model.A, domain=NonNegativeIntegers)
    model.r_tail = Var(model.A, domain=NonNegativeReals)

    OUT = data["OUT"]
    IN = data["IN"]
    eligible = data["eligible"]
    redir_min = float(cfg["redir_min_kwh"])

    def site_util_rule(m, i, mon, t, c):
        return quicksum(m.edisp[i, mon, t, c, b] for b in m.B) <= m.K[c] * m.x[i, c]

    model.SiteUtil = Constraint(model.I, model.M, model.H, model.C_pub, rule=site_util_rule)

    def redir_aggregate_rule(m, i, j, mon, t):
        return m.z[i, j, mon, t] == quicksum(m.z_od[i, j, mon, t, co, cd] for co in m.C_pub for cd in m.C_pub)

    model.RedirAggregate = Constraint(model.A, rule=redir_aggregate_rule)

    def redir_min_rule(m, i, j, mon, t):
        return m.z[i, j, mon, t] >= redir_min * m.Yarc[i, j, mon, t]

    model.RedirMin = Constraint(model.A, rule=redir_min_rule)

    def redir_cap_install_rule(m, i, j, mon, t):
        return m.z[i, j, mon, t] <= quicksum(m.K[c] * m.x[j, c] for c in m.C_pub)

    model.RedirCapInstall = Constraint(model.A, rule=redir_cap_install_rule)

    def redir_cap_binary_rule(m, i, j, mon, t):
        return m.z[i, j, mon, t] <= m.M_redir[j] * m.Yarc[i, j, mon, t]

    model.RedirCapBinary = Constraint(model.A, rule=redir_cap_binary_rule)

    def resource_limit(m, i):
        return quicksum(m.ResourceUse[c] * m.x[i, c] for c in m.C_pub) <= m.CL[i]

    model.ResourceLimit = Constraint(model.I, rule=resource_limit)

    def demand_cover_rule(m, i, mon, t, b):
        served = quicksum(m.edisp[i, mon, t, c, b] for c in eligible[b])
        if b == "home":
            rhs = m.Demand[i, mon, t, "home"]
        else:
            outflow = quicksum(
                m.z_od[i, j, mon, t, co, cd]
                for j in OUT.get((i, mon, t), []) for co in m.C_pub for cd in m.C_pub
            )
            inflow = quicksum(
                m.z_od[j, i, mon, t, co, cd]
                for j in IN.get((i, mon, t), []) for co in m.C_pub for cd in m.C_pub
            )
            rhs = m.Demand[i, mon, t, "public"] - outflow + inflow
        return served + m.slack[i, mon, t, b] == rhs

    model.DemandCover = Constraint(model.I, model.M, model.H, model.B, rule=demand_cover_rule)

    def origin_type_allocation_rule(m, i, mon, t):
        return quicksum(m.q[i, mon, t, co] for co in m.C_pub) + m.slack[i, mon, t, "public"] == m.Demand[i, mon, t, "public"]

    model.OriginTypeAllocation = Constraint(model.I, model.M, model.H, rule=origin_type_allocation_rule)

    def origin_type_consistency_rule(m, i, mon, t, c):
        incoming_as_dest_type = quicksum(m.z_od[j, i, mon, t, co, c] for j in IN.get((i, mon, t), []) for co in m.C_pub)
        outgoing_as_origin_type = quicksum(m.z_od[i, j, mon, t, c, cd] for j in OUT.get((i, mon, t), []) for cd in m.C_pub)
        return m.q[i, mon, t, c] == m.edisp[i, mon, t, c, "public"] - incoming_as_dest_type + outgoing_as_origin_type

    model.OriginTypeConsistency = Constraint(model.I, model.M, model.H, model.C_pub, rule=origin_type_consistency_rule)

    def outgoing_by_origin_type_rule(m, i, mon, t, co):
        return quicksum(m.z_od[i, j, mon, t, co, cd] for j in OUT.get((i, mon, t), []) for cd in m.C_pub) <= m.q[i, mon, t, co]

    model.OutgoingByOriginType = Constraint(model.ORIGIN_ST, model.C_pub, rule=outgoing_by_origin_type_rule)

    def trip_decomposition(m, i, j, mon, t):
        return m.z[i, j, mon, t] == m.x_kWh * m.n_trip[i, j, mon, t] + m.r_tail[i, j, mon, t]

    model.TripDecomp = Constraint(model.A, rule=trip_decomposition)

    def tail_upper(m, i, j, mon, t):
        return m.r_tail[i, j, mon, t] <= (m.x_kWh - 1e-6) * m.Yarc[i, j, mon, t]

    model.TailUpper = Constraint(model.A, rule=tail_upper)

    def energy_balance_rule(m, i, mon, t):
        supply = m.grid_dir[i, mon, t] + m.pv_dir[i, mon, t] + m.batt_discharge[i, mon, t]
        demand = quicksum(m.edisp[i, mon, t, c, b] for b in m.B for c in m.C_pub)
        return supply == demand

    model.EnergyBalance = Constraint(model.I, model.M, model.H, rule=energy_balance_rule)

    def pv_generation_rule(m, i, mon, t):
        return m.pv_dir[i, mon, t] + m.pv_batt[i, mon, t] <= m.PV_panel_cap * m.PV[i] * m.p_pv[mon, t]

    model.PVGeneration = Constraint(model.I, model.M, model.H, rule=pv_generation_rule)

    last_h = max(data["INTERVALS"])

    def battery_initial_january_rule(m, i):
        return m.soc[i, "January", 0] == m.alpha_soc * m.Batt_cell_cap * m.Batt[i]

    model.BatteryInitialJanuary = Constraint(model.I, rule=battery_initial_january_rule)

    def battery_month_link_rule(m, i, mon):
        if mon == "January":
            return Constraint.Skip
        return m.soc[i, mon, 0] == m.soc[i, m.prev_mon[mon], last_h]

    model.BatteryMonthLink = Constraint(model.I, model.M, rule=battery_month_link_rule)

    def battery_dynamics_rule(m, i, mon, t):
        charge = m.eta_ch * (m.grid_batt[i, mon, t] + m.pv_batt[i, mon, t])
        discharge = (1.0 / m.eta_dis) * m.batt_discharge[i, mon, t]
        return m.soc[i, mon, t] == m.soc[i, mon, t - 1] + charge - discharge

    model.BatteryDynamics = Constraint(model.I, model.M, model.H, rule=battery_dynamics_rule)

    def batt_cap_rule(m, i):
        return m.Batt[i] <= int(cfg["battery_max_units_per_hex"])

    model.BattCap = Constraint(model.I, rule=batt_cap_rule)

    def pv_upper_bound_rule(m, i):
        return m.PV[i] <= m.PV_upper[i]

    model.PVUpperBound = Constraint(model.I, rule=pv_upper_bound_rule)

    def batt_charge_throughput_rule(m, i, mon, t):
        return m.grid_batt[i, mon, t] + m.pv_batt[i, mon, t] <= m.K_batt * m.Batt[i]

    model.BattChargeThroughput = Constraint(model.I, model.M, model.H, rule=batt_charge_throughput_rule)

    def batt_discharge_throughput_rule(m, i, mon, t):
        return m.batt_discharge[i, mon, t] <= m.K_batt * m.Batt[i]

    model.BattDischargeThroughput = Constraint(model.I, model.M, model.H, rule=batt_discharge_throughput_rule)

    def charge_only(m, i, mon, t):
        return m.grid_batt[i, mon, t] + m.pv_batt[i, mon, t] <= m.M_batt[i] * m.delta[i, mon, t]

    model.ChargeOnly = Constraint(model.I, model.M, model.H, rule=charge_only)

    def discharge_only(m, i, mon, t):
        return m.batt_discharge[i, mon, t] <= m.M_batt[i] * (1 - m.delta[i, mon, t])

    model.DischargeOnly = Constraint(model.I, model.M, model.H, rule=discharge_only)

    def battery_capacity_rule_sub(m, i, mon, ell):
        return m.soc[i, mon, ell] <= m.beta_max_soc * m.Batt_cell_cap * m.Batt[i]

    model.BatteryCapacitySub = Constraint(model.I, model.M, model.Hsoc, rule=battery_capacity_rule_sub)

    def battery_lower_bound_rule(m, i, mon, ell):
        return m.soc[i, mon, ell] >= m.beta_min_soc * m.Batt_cell_cap * m.Batt[i]

    model.BatteryLowerBound = Constraint(model.I, model.M, model.Hsoc, rule=battery_lower_bound_rule)

    def origin_outflow_bound(m, i, mon, t):
        return quicksum(m.z_od[i, j, mon, t, co, cd] for j in OUT.get((i, mon, t), []) for co in m.C_pub for cd in m.C_pub) <= m.Demand[i, mon, t, "public"]

    model.OriginOutflowBound = Constraint(model.ORIGIN_ST, rule=origin_outflow_bound)

    def incoming_destination_type_rule(m, i, mon, t, cd):
        return quicksum(m.z_od[j, i, mon, t, co, cd] for j in IN.get((i, mon, t), []) for co in m.C_pub) <= m.edisp[i, mon, t, cd, "public"]

    model.IncomingRedirDestinationType = Constraint(model.DEST_ST, model.C_pub, rule=incoming_destination_type_rule)

    def dest_incoming_type_capacity_rule(m, i, mon, t, cd):
        return quicksum(m.z_od[j, i, mon, t, co, cd] for j in IN.get((i, mon, t), []) for co in m.C_pub) <= m.K[cd] * m.x[i, cd]

    model.DestIncomingTypeCapacity = Constraint(model.DEST_ST, model.C_pub, rule=dest_incoming_type_capacity_rule)

    days = data["DAYS"]
    penalty = float(cfg["penalty_per_kwh_slack"])

    def annual_profit(m):
        rev_charge = quicksum(
            m.Ndays[mon] * m.Price[c] * m.edisp[i, mon, t, c, b]
            for i in m.I for mon in m.M for t in m.H for b in m.B for c in m.C_pub
        )
        cost_grid = quicksum(
            m.Ndays[mon] * m.tou[mon, t] * (m.grid_dir[i, mon, t] + m.grid_batt[i, mon, t])
            for i in m.I for mon in m.M for t in m.H
        )
        cost_incentive_distance = quicksum(
            m.Ndays[mon] * (m.T[i, j] * m.n_trip[i, j, mon, t] + (m.T[i, j] / m.x_kWh) * m.r_tail[i, j, mon, t])
            for (i, j, mon, t) in m.A
        )
        cost_incentive_price = quicksum(
            m.Ndays[mon] * m.DeltaPrice[co, cd] * m.z_od[i, j, mon, t, co, cd]
            for (i, j, mon, t) in m.A for co in m.C_pub for cd in m.C_pub
        )
        cost_slack = penalty * quicksum(
            m.Ndays[mon] * m.slack[i, mon, t, b]
            for i in m.I for mon in m.M for t in m.H for b in m.B
        )
        capex = days * (
            quicksum(m.PVF_cost[c] * m.x[i, c] for i in m.I for c in m.C_pub)
            + quicksum(m.PVF_PV * m.PV[i] for i in m.I)
            + quicksum(m.PVF_Batt * m.Batt[i] for i in m.I)
        )
        return rev_charge - cost_grid - cost_incentive_distance - cost_incentive_price - cost_slack - capex

    model.obj = Objective(rule=annual_profit, sense=maximize)
    return model


def apply_scenario(model, scenario: str) -> None:
    if scenario == "no_redirection":
        print("Applying no-redirection benchmark: fixing z, z_od, Yarc, n_trip and r_tail to zero.")
        for k in model.z:
            model.z[k].fix(0.0)
        for k in model.z_od:
            model.z_od[k].fix(0.0)
        for k in model.Yarc:
            model.Yarc[k].fix(0)
        for k in model.n_trip:
            model.n_trip[k].fix(0)
        for k in model.r_tail:
            model.r_tail[k].fix(0.0)


def apply_hard_no_slack(model) -> None:
    """Hard feasibility mode: all unmet-demand slack variables are fixed to zero."""
    print("Applying hard no-slack feasibility mode: fixing all slack variables to zero.")
    for k in model.slack:
        model.slack[k].fix(0.0)
