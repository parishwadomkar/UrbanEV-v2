"""Modified for the UrbanEV seasonal integration, 2026-10-22. See SOURCE_PROVENANCE.json."""
from __future__ import annotations

import math
import pyomo.environ as pyo


def build_benders_master(data: dict, cfg: dict, scenario: str = "with_redirection"):
    m = pyo.ConcreteModel()
    I, M, H, Hsoc = data["hex_ids"], data["MONTHS"], data["INTERVALS"], data["HSOC"]
    C, B, A = data["PUB_TYPES"], data["DEMAND_CLASSES"], data["allowed_st"]
    m.I = pyo.Set(initialize=I)
    m.M = pyo.Set(initialize=M)
    m.H = pyo.Set(initialize=H)
    m.Hsoc = pyo.Set(initialize=Hsoc)
    m.A = pyo.Set(dimen=4, initialize=A)
    m.ORIGIN_ST = pyo.Set(dimen=3, initialize=data["ORIGIN_ST"])
    m.DEST_ST = pyo.Set(dimen=3, initialize=data["DEST_ST"])
    m.D = pyo.Set(within=m.I * m.I, initialize=data["allowed"])
    m.C_pub = pyo.Set(initialize=C)
    m.B = pyo.Set(initialize=B)

    m.Price = pyo.Param(m.C_pub, initialize=data["charger_price"])
    m.DeltaPrice = pyo.Param(m.C_pub, m.C_pub, initialize=data["delta_price"], within=pyo.NonNegativeReals)
    m.Demand = pyo.Param(m.I, m.M, m.H, m.B, initialize=data["demand_event_annual"], within=pyo.NonNegativeReals)
    m.K = pyo.Param(m.C_pub, initialize=data["charger_capacity_pub"])
    m.Resource = pyo.Param(m.C_pub, initialize=data["charger_resources"])
    m.PVF_cost = pyo.Param(m.C_pub, initialize=lambda mm, c: data["daily_cost"][c])
    m.PVF_PV = pyo.Param(initialize=data["daily_cost"]["PV"])
    m.PVF_Batt = pyo.Param(initialize=data["daily_cost"]["Batt"])
    m.CL = pyo.Param(m.I, initialize=data["cl"])
    m.T = pyo.Param(m.D, initialize=data["T_dict"])
    m.tou = pyo.Param(m.M, m.H, initialize=lambda mm, mon, t: data["tou"][mon][t])
    m.PV_panel_cap = pyo.Param(initialize=data["pv_kwh_per_panel_slot_at_cf1"])
    m.p_pv = pyo.Param(m.M, m.H, initialize=lambda mm, mon, t: data["pv_cf"][mon][t])
    m.PV_upper = pyo.Param(m.I, initialize=data["pv_upper"])
    m.x_kWh = pyo.Param(initialize=float(cfg["x_kwh_per_trip"]))
    m.Batt_cell_cap = pyo.Param(initialize=float(cfg["battery_cell_cap_kwh"]))
    m.eta_ch = pyo.Param(initialize=float(cfg["eta_charge"]))
    m.eta_dis = pyo.Param(initialize=float(cfg["eta_discharge"]))
    m.alpha_soc = pyo.Param(initialize=float(cfg["initial_soc_fraction"]))
    m.beta_min_soc = pyo.Param(initialize=float(cfg["soc_min_fraction"]))
    m.beta_max_soc = pyo.Param(initialize=float(cfg["soc_max_fraction"]))
    m.K_batt = pyo.Param(initialize=data["K_BATT"])
    m.M_batt = pyo.Param(m.I, initialize=lambda mm, i: data["M_BATT"][int(i)], within=pyo.NonNegativeReals)
    m.M_redir = pyo.Param(m.I, initialize=lambda mm, j: data["M_REDIR"][int(j)], within=pyo.NonNegativeReals)
    m.prev_mon = pyo.Param(m.M, initialize=data["prev_month"], within=pyo.Any)
    m.Ndays = pyo.Param(m.M, initialize=lambda mm, mon: data["N_MONTH"][mon])

    def x_bounds(mm, i, c):
        return (0, int(math.floor(data["cl"][int(i)] / data["charger_resources"][c])))
    def pv_bounds(mm, i):
        return (0, data["pv_upper"][int(i)])
    def batt_bounds(mm, i):
        return (0, int(cfg["battery_max_units_per_hex"]))

    m.x = pyo.Var(m.I, m.C_pub, domain=pyo.NonNegativeIntegers, bounds=x_bounds)
    m.PV = pyo.Var(m.I, domain=pyo.NonNegativeIntegers, bounds=pv_bounds)
    m.Batt = pyo.Var(m.I, domain=pyo.NonNegativeIntegers, bounds=batt_bounds)
    m.edisp = pyo.Var(m.I, m.M, m.H, m.C_pub, m.B, domain=pyo.NonNegativeReals)
    m.grid_dir = pyo.Var(m.I, m.M, m.H, domain=pyo.NonNegativeReals)
    m.grid_batt = pyo.Var(m.I, m.M, m.H, domain=pyo.NonNegativeReals)
    m.pv_dir = pyo.Var(m.I, m.M, m.H, domain=pyo.NonNegativeReals)
    m.pv_batt = pyo.Var(m.I, m.M, m.H, domain=pyo.NonNegativeReals)
    m.batt_discharge = pyo.Var(m.I, m.M, m.H, domain=pyo.NonNegativeReals)
    m.soc = pyo.Var(m.I, m.M, m.Hsoc, domain=pyo.NonNegativeReals)
    m.delta = pyo.Var(m.I, m.M, m.H, domain=pyo.Binary)
    m.slack = pyo.Var(m.I, m.M, m.H, m.B, domain=pyo.NonNegativeReals)
    m.q = pyo.Var(m.I, m.M, m.H, m.C_pub, domain=pyo.NonNegativeReals)
    m.R = pyo.Var(m.I, m.M, m.H, m.C_pub, domain=pyo.NonNegativeReals)
    m.W = pyo.Var(m.I, m.M, m.H, m.C_pub, domain=pyo.NonNegativeReals)
    m.G = pyo.Var(m.A, domain=pyo.NonNegativeReals)
    m.Yarc = pyo.Var(m.A, domain=pyo.Binary)
    m.n_trip = pyo.Var(m.A, domain=pyo.NonNegativeIntegers)
    m.r_tail = pyo.Var(m.A, domain=pyo.NonNegativeReals)
    m.ThetaType = pyo.Var(m.M, m.H, domain=pyo.NonNegativeReals)
    m.TypeAssignmentCuts = pyo.ConstraintList()

    OUT, IN = data["OUT"], data["IN"]
    eligible = data["eligible"]
    redir_min = float(cfg["redir_min_kwh"])

    m.SiteUtil = pyo.Constraint(m.I, m.M, m.H, m.C_pub, rule=lambda mm, i, mon, t, c: pyo.quicksum(mm.edisp[i, mon, t, c, b] for b in mm.B) <= mm.K[c] * mm.x[i, c])
    m.ResourceLimit = pyo.Constraint(m.I, rule=lambda mm, i: pyo.quicksum(mm.Resource[c] * mm.x[i, c] for c in mm.C_pub) <= mm.CL[i])

    def demand_cover(mm, i, mon, t, b):
        served = pyo.quicksum(mm.edisp[i, mon, t, c, b] for c in eligible[b])
        if b == "home":
            return served + mm.slack[i, mon, t, b] == mm.Demand[i, mon, t, "home"]
        return served + mm.slack[i, mon, t, b] == mm.Demand[i, mon, t, "public"] - pyo.quicksum(mm.R[i, mon, t, c] for c in mm.C_pub) + pyo.quicksum(mm.W[i, mon, t, c] for c in mm.C_pub)
    m.DemandCover = pyo.Constraint(m.I, m.M, m.H, m.B, rule=demand_cover)

    m.OriginTypeAllocation = pyo.Constraint(m.I, m.M, m.H, rule=lambda mm, i, mon, t: pyo.quicksum(mm.q[i, mon, t, c] for c in mm.C_pub) + mm.slack[i, mon, t, "public"] == mm.Demand[i, mon, t, "public"])
    m.OriginTypeConsistency = pyo.Constraint(m.I, m.M, m.H, m.C_pub, rule=lambda mm, i, mon, t, c: mm.q[i, mon, t, c] == mm.edisp[i, mon, t, c, "public"] - mm.W[i, mon, t, c] + mm.R[i, mon, t, c])
    m.OutgoingByOriginType = pyo.Constraint(m.I, m.M, m.H, m.C_pub, rule=lambda mm, i, mon, t, c: mm.R[i, mon, t, c] <= mm.q[i, mon, t, c])
    m.IncomingServedByDestType = pyo.Constraint(m.I, m.M, m.H, m.C_pub, rule=lambda mm, i, mon, t, c: mm.W[i, mon, t, c] <= mm.edisp[i, mon, t, c, "public"])
    m.DestIncomingTypeCapacity = pyo.Constraint(m.I, m.M, m.H, m.C_pub, rule=lambda mm, i, mon, t, c: mm.W[i, mon, t, c] <= mm.K[c] * mm.x[i, c])
    m.OriginOutflowBound = pyo.Constraint(m.I, m.M, m.H, rule=lambda mm, i, mon, t: pyo.quicksum(mm.R[i, mon, t, c] for c in mm.C_pub) <= mm.Demand[i, mon, t, "public"])

    def out_flow(mm, i, mon, t):
        outs = OUT.get((int(i), mon, int(t)), [])
        if not outs:
            return pyo.quicksum(mm.R[i, mon, t, c] for c in mm.C_pub) == 0
        return pyo.quicksum(mm.G[i, int(j), mon, t] for j in outs) == pyo.quicksum(mm.R[i, mon, t, c] for c in mm.C_pub)
    m.AggregateOutflowWitness = pyo.Constraint(m.I, m.M, m.H, rule=out_flow)

    def in_flow(mm, j, mon, t):
        ins = IN.get((int(j), mon, int(t)), [])
        if not ins:
            return pyo.quicksum(mm.W[j, mon, t, c] for c in mm.C_pub) == 0
        return pyo.quicksum(mm.G[int(i), j, mon, t] for i in ins) == pyo.quicksum(mm.W[j, mon, t, c] for c in mm.C_pub)
    m.AggregateInflowWitness = pyo.Constraint(m.I, m.M, m.H, rule=in_flow)

    m.RedirMin = pyo.Constraint(m.A, rule=lambda mm, i, j, mon, t: mm.G[i, j, mon, t] >= redir_min * mm.Yarc[i, j, mon, t])
    m.RedirCapInstall = pyo.Constraint(m.A, rule=lambda mm, i, j, mon, t: mm.G[i, j, mon, t] <= pyo.quicksum(mm.K[c] * mm.x[j, c] for c in mm.C_pub))
    m.RedirCapBinary = pyo.Constraint(m.A, rule=lambda mm, i, j, mon, t: mm.G[i, j, mon, t] <= mm.M_redir[j] * mm.Yarc[i, j, mon, t])
    m.TripDecomp = pyo.Constraint(m.A, rule=lambda mm, i, j, mon, t: mm.G[i, j, mon, t] == mm.x_kWh * mm.n_trip[i, j, mon, t] + mm.r_tail[i, j, mon, t])
    m.TailUpper = pyo.Constraint(m.A, rule=lambda mm, i, j, mon, t: mm.r_tail[i, j, mon, t] <= (mm.x_kWh - 1e-6) * mm.Yarc[i, j, mon, t])

    m.EnergyBalance = pyo.Constraint(m.I, m.M, m.H, rule=lambda mm, i, mon, t: mm.grid_dir[i, mon, t] + mm.pv_dir[i, mon, t] + mm.batt_discharge[i, mon, t] == pyo.quicksum(mm.edisp[i, mon, t, c, b] for c in mm.C_pub for b in mm.B))
    m.PVGeneration = pyo.Constraint(m.I, m.M, m.H, rule=lambda mm, i, mon, t: mm.pv_dir[i, mon, t] + mm.pv_batt[i, mon, t] <= mm.PV_panel_cap * mm.PV[i] * mm.p_pv[mon, t])

    last_h = max(data["INTERVALS"])
    m.BatteryInitialJanuary = pyo.Constraint(m.I, rule=lambda mm, i: mm.soc[i, "January", 0] == mm.alpha_soc * mm.Batt_cell_cap * mm.Batt[i])
    def month_link(mm, i, mon):
        if mon == "January":
            return pyo.Constraint.Skip
        return mm.soc[i, mon, 0] == mm.soc[i, mm.prev_mon[mon], last_h]
    m.BatteryMonthLink = pyo.Constraint(m.I, m.M, rule=month_link)
    if cfg.get("bess_boundary") == "cyclic_day":
        m.BatteryInitialJanuary.deactivate()
        m.BatteryMonthLink.deactivate()
        m.BatteryDailyCycle = pyo.Constraint(m.I, m.M, rule=lambda mm, i, mon: mm.soc[i, mon, 0] == mm.soc[i, mon, last_h])

    m.BatteryDynamics = pyo.Constraint(m.I, m.M, m.H, rule=lambda mm, i, mon, t: mm.soc[i, mon, t] == mm.soc[i, mon, t - 1] + mm.eta_ch * (mm.grid_batt[i, mon, t] + mm.pv_batt[i, mon, t]) - (1.0 / mm.eta_dis) * mm.batt_discharge[i, mon, t])
    m.BattCap = pyo.Constraint(m.I, rule=lambda mm, i: mm.Batt[i] <= int(cfg["battery_max_units_per_hex"]))
    m.PVUpperBound = pyo.Constraint(m.I, rule=lambda mm, i: mm.PV[i] <= mm.PV_upper[i])
    m.BattChargeThroughput = pyo.Constraint(m.I, m.M, m.H, rule=lambda mm, i, mon, t: mm.grid_batt[i, mon, t] + mm.pv_batt[i, mon, t] <= mm.K_batt * mm.Batt[i])
    m.BattDischargeThroughput = pyo.Constraint(m.I, m.M, m.H, rule=lambda mm, i, mon, t: mm.batt_discharge[i, mon, t] <= mm.K_batt * mm.Batt[i])
    m.ChargeOnly = pyo.Constraint(m.I, m.M, m.H, rule=lambda mm, i, mon, t: mm.grid_batt[i, mon, t] + mm.pv_batt[i, mon, t] <= mm.M_batt[i] * mm.delta[i, mon, t])
    m.DischargeOnly = pyo.Constraint(m.I, m.M, m.H, rule=lambda mm, i, mon, t: mm.batt_discharge[i, mon, t] <= mm.M_batt[i] * (1 - mm.delta[i, mon, t]))
    m.BatteryCapacityUpper = pyo.Constraint(m.I, m.M, m.Hsoc, rule=lambda mm, i, mon, ell: mm.soc[i, mon, ell] <= mm.beta_max_soc * mm.Batt_cell_cap * mm.Batt[i])
    m.BatteryCapacityLower = pyo.Constraint(m.I, m.M, m.Hsoc, rule=lambda mm, i, mon, ell: mm.soc[i, mon, ell] >= mm.beta_min_soc * mm.Batt_cell_cap * mm.Batt[i])

    if data.get("disable_pv", False):
        for idx in m.PV: m.PV[idx].fix(0)
        for comp in (m.pv_dir, m.pv_batt):
            for idx in comp: comp[idx].fix(0)
    if data.get("disable_bess", False):
        for idx in m.Batt: m.Batt[idx].fix(0)
        for comp in (m.grid_batt, m.pv_batt, m.batt_discharge, m.soc, m.delta):
            for idx in comp: comp[idx].fix(0)

    if scenario == "no_redirection":
        for comp in (m.R, m.W, m.G, m.Yarc, m.n_trip, m.r_tail, m.ThetaType):
            for idx in comp: comp[idx].fix(0)
    elif scenario == "with_redirection":
        pass

    days = data["DAYS"]
    penalty = float(cfg["penalty_per_kwh_slack"])
    def annual_profit(mm):
        rev = pyo.quicksum(mm.Ndays[mon] * mm.Price[c] * mm.edisp[i, mon, t, c, b] for i in mm.I for mon in mm.M for t in mm.H for b in mm.B for c in mm.C_pub)
        grid = pyo.quicksum(mm.Ndays[mon] * mm.tou[mon, t] * (mm.grid_dir[i, mon, t] + mm.grid_batt[i, mon, t]) for i in mm.I for mon in mm.M for t in mm.H)
        dist = pyo.quicksum(mm.Ndays[mon] * (mm.T[i, j] * mm.n_trip[i, j, mon, t] + (mm.T[i, j] / mm.x_kWh) * mm.r_tail[i, j, mon, t]) for (i, j, mon, t) in mm.A)
        theta = pyo.quicksum(mm.ThetaType[mon, t] for mon in mm.M for t in mm.H)
        slack = penalty * pyo.quicksum(mm.Ndays[mon] * mm.slack[i, mon, t, b] for i in mm.I for mon in mm.M for t in mm.H for b in mm.B)
        capex = days * (pyo.quicksum(mm.PVF_cost[c] * mm.x[i, c] for i in mm.I for c in mm.C_pub) + pyo.quicksum(mm.PVF_PV * mm.PV[i] for i in mm.I) + pyo.quicksum(mm.PVF_Batt * mm.Batt[i] for i in mm.I))
        return rev - grid - dist - theta - slack - capex
    m.obj = pyo.Objective(rule=annual_profit, sense=pyo.maximize)
    return m


def apply_hard_no_slack(model):
    for idx in model.slack:
        model.slack[idx].fix(0)
