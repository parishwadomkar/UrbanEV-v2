from __future__ import annotations

import math
from dataclasses import dataclass

import pyomo.environ as pyo

from network_feasibility import HallCertificate
from decomposition_types import ComponentLogicOptimalityCut, LPBendersCut


@dataclass(frozen=True)
class InvestmentPoint:
    x: dict[tuple[int, str], float]
    pv: dict[int, float]
    batt: dict[int, float]


@dataclass(frozen=True)
class ExactConfigCut:
    cut_id: int
    investment: InvestmentPoint
    upper_bound: float
    objective: float
    gap: float


@dataclass(frozen=True)
class AnnualLPDualCut:
    cut_id: int
    constant: float
    x_coefficients: dict[tuple[int, str], float]
    pv_coefficients: dict[int, float]
    batt_coefficients: dict[int, float]
    lp_objective: float
    source_kind: str = "linked_annual_lp"


def _x_upper_bounds(data: dict) -> dict[tuple[int, str], int]:
    return {
        (int(i), str(c)): int(math.floor(float(data["cl"][int(i)]) / float(data["charger_resources"][str(c)])))
        for i in data["hex_ids"] for c in data["PUB_TYPES"]
    }


def _bits_for_upper(upper: int) -> list[int]:
    return [] if int(upper) <= 0 else list(range(int(math.ceil(math.log2(int(upper) + 1)))))


def build_global_components(data: dict) -> dict:
    """Connected components of the time-independent eligible redirection graph.

    These components are used only for structural consistency checks and reporting.
    The revised energy relaxation itself is cell-local.
    """
    nodes = [int(i) for i in data["hex_ids"]]
    parent = {i: i for i in nodes}

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        if ra < rb:
            parent[rb] = ra
        else:
            parent[ra] = rb

    for i, j in data["allowed"]:
        union(int(i), int(j))

    groups: dict[int, list[int]] = {}
    for i in nodes:
        groups.setdefault(find(i), []).append(i)
    ordered = sorted((tuple(sorted(v)) for v in groups.values()), key=lambda v: (v[0], len(v)))
    component_nodes = {int(g): comp for g, comp in enumerate(ordered)}
    node_to_component = {int(i): int(g) for g, comp in component_nodes.items() for i in comp}
    return {"ids": list(component_nodes), "nodes": component_nodes, "node_to_component": node_to_component}


def _annual_capex_expr(model):
    return model.Days * (
        pyo.quicksum(model.DailyCostCharger[c] * model.x[i, c] for i in model.I for c in model.C)
        + pyo.quicksum(model.DailyCostPV * model.PV[i] for i in model.I)
        + pyo.quicksum(model.DailyCostBatt * model.Batt[i] for i in model.I)
    )


def _annual_revenue_cap(data: dict) -> float:
    max_price = max(float(data["charger_price"][str(c)]) for c in data["PUB_TYPES"])
    return float(sum(
        float(data["N_MONTH"][str(mon)])
        * float(data["demand_event_annual"][(int(i), str(mon), int(t), str(b))])
        * max_price
        for i in data["hex_ids"] for mon in data["MONTHS"]
        for t in data["INTERVALS"] for b in data["DEMAND_CLASSES"]
    ))


def build_lbbd_master(data: dict, cfg: dict, slot_components: dict, global_components: dict) -> pyo.ConcreteModel:
    """Compact LBBD master with an embedded valid recourse relaxation.

    The recourse approximation is split into:
      1. component-slot grid-baseline profit Theta;
      2. a cell-local linked 12-month PV/BESS energy-credit relaxation;
      3. slack-preserving Hall/min-cut cuts and component-slot LP cuts;
      4. exact fixed-investment annual MIP configuration cuts.

    The energy model preserves the monolithic January initial SoC and all
    month-to-month links. It does not impose cyclic-day operation. Redirection,
    type-pair assignment, trip integrality, and charge/discharge exclusivity remain
    relaxed in the master and are restored by the exact annual MIP oracle.
    """
    model = pyo.ConcreteModel(name="lbbd_master")
    model.I = pyo.Set(initialize=[int(i) for i in data["hex_ids"]], ordered=True)
    model.C = pyo.Set(initialize=[str(c) for c in data["PUB_TYPES"]], ordered=True)
    model.M = pyo.Set(initialize=[str(m) for m in data["MONTHS"]], ordered=True)
    model.H = pyo.Set(initialize=[int(t) for t in data["INTERVALS"]], ordered=True)
    model.HSOC = pyo.Set(initialize=[int(t) for t in data["HSOC"]], ordered=True)
    model.COMP = pyo.Set(dimen=3, initialize=slot_components["keys"], ordered=True)
    model.G = pyo.Set(initialize=global_components["ids"], ordered=True)

    x_ub = _x_upper_bounds(data)
    pv_ub = {int(i): (0 if data.get("disable_pv", False) else int(data["pv_upper"].get(int(i), 0))) for i in data["hex_ids"]}
    batt_ub = {int(i): (0 if data.get("disable_bess", False) else int(cfg["battery_max_units_per_hex"])) for i in data["hex_ids"]}

    model.K = pyo.Param(model.C, initialize={str(c): float(data["charger_capacity_pub"][str(c)]) for c in data["PUB_TYPES"]})
    model.ResourceUse = pyo.Param(model.C, initialize={str(c): float(data["charger_resources"][str(c)]) for c in data["PUB_TYPES"]})
    model.Price = pyo.Param(model.C, initialize={str(c): float(data["charger_price"][str(c)]) for c in data["PUB_TYPES"]})
    model.CL = pyo.Param(model.I, initialize={int(i): float(data["cl"][int(i)]) for i in data["hex_ids"]})
    model.Days = pyo.Param(initialize=float(data["DAYS"]))
    model.DailyCostCharger = pyo.Param(model.C, initialize={str(c): float(data["daily_cost"][str(c)]) for c in data["PUB_TYPES"]})
    model.DailyCostPV = pyo.Param(initialize=float(data["daily_cost"].get("PV", 0.0)))
    model.DailyCostBatt = pyo.Param(initialize=float(data["daily_cost"].get("Batt", 0.0)))
    model.Penalty = pyo.Param(initialize=float(cfg["penalty_per_kwh_slack"]))
    model.PVPanelCap = pyo.Param(initialize=float(data["pv_kwh_per_panel_slot_at_cf1"]))
    model.BattCellCap = pyo.Param(initialize=float(cfg["battery_cell_cap_kwh"]))
    model.KBatt = pyo.Param(initialize=float(data["K_BATT"]))
    model.EtaCh = pyo.Param(initialize=float(cfg["eta_charge"]))
    model.EtaDis = pyo.Param(initialize=float(cfg["eta_discharge"]))
    model.AlphaSoc = pyo.Param(initialize=float(cfg["initial_soc_fraction"]))
    model.BetaMinSoc = pyo.Param(initialize=float(cfg["soc_min_fraction"]))
    model.BetaMaxSoc = pyo.Param(initialize=float(cfg["soc_max_fraction"]))

    model.x = pyo.Var(model.I, model.C, domain=pyo.NonNegativeIntegers,
                      bounds=lambda m, i, c: (0, x_ub[(int(i), str(c))]))
    model.PV = pyo.Var(model.I, domain=pyo.NonNegativeIntegers,
                       bounds=lambda m, i: (0, pv_ub[int(i)]))
    model.Batt = pyo.Var(model.I, domain=pyo.NonNegativeIntegers,
                         bounds=lambda m, i: (0, batt_ub[int(i)]))

    bit_x: list[tuple[int, str, int]] = []
    bit_pv: list[tuple[int, int]] = []
    bit_batt: list[tuple[int, int]] = []
    bits_x: dict[tuple[int, str], list[int]] = {}
    bits_pv: dict[int, list[int]] = {}
    bits_batt: dict[int, list[int]] = {}
    for i in data["hex_ids"]:
        ii = int(i)
        for c in data["PUB_TYPES"]:
            cc = str(c)
            ks = _bits_for_upper(x_ub[(ii, cc)])
            bits_x[(ii, cc)] = ks
            bit_x.extend((ii, cc, k) for k in ks)
        ks = _bits_for_upper(pv_ub[ii])
        bits_pv[ii] = ks
        bit_pv.extend((ii, k) for k in ks)
        ks = _bits_for_upper(batt_ub[ii])
        bits_batt[ii] = ks
        bit_batt.extend((ii, k) for k in ks)

    model.XBIT = pyo.Set(dimen=3, initialize=bit_x, ordered=True)
    model.PVBIT = pyo.Set(dimen=2, initialize=bit_pv, ordered=True)
    model.BATTBIT = pyo.Set(dimen=2, initialize=bit_batt, ordered=True)
    model.xbit = pyo.Var(model.XBIT, domain=pyo.Binary)
    model.pvbit = pyo.Var(model.PVBIT, domain=pyo.Binary)
    model.battbit = pyo.Var(model.BATTBIT, domain=pyo.Binary)

    def x_link(m, i, c):
        ks = bits_x[(int(i), str(c))]
        return m.x[i, c] == pyo.quicksum((2 ** k) * m.xbit[i, c, k] for k in ks) if ks else m.x[i, c] == 0

    def pv_link(m, i):
        ks = bits_pv[int(i)]
        return m.PV[i] == pyo.quicksum((2 ** k) * m.pvbit[i, k] for k in ks) if ks else m.PV[i] == 0

    def batt_link(m, i):
        ks = bits_batt[int(i)]
        return m.Batt[i] == pyo.quicksum((2 ** k) * m.battbit[i, k] for k in ks) if ks else m.Batt[i] == 0

    model.XBitLink = pyo.Constraint(model.I, model.C, rule=x_link)
    model.PVBitLink = pyo.Constraint(model.I, rule=pv_link)
    model.BattBitLink = pyo.Constraint(model.I, rule=batt_link)
    model.ResourceLimit = pyo.Constraint(
        model.I,
        rule=lambda m, i: pyo.quicksum(m.ResourceUse[c] * m.x[i, c] for c in m.C) <= m.CL[i],
    )

    component_demand: dict[tuple[str, int, int], float] = {}
    component_nodes: dict[tuple[str, int, int], tuple[int, ...]] = {}
    component_global: dict[tuple[str, int, int], int] = {}
    component_margin: dict[tuple[str, int, int, str], float] = {}
    component_cap: dict[tuple[str, int, int], float] = {}
    for raw_key in slot_components["keys"]:
        key = (str(raw_key[0]), int(raw_key[1]), int(raw_key[2]))
        nodes = tuple(int(i) for i in slot_components["nodes"][raw_key])
        gids = {int(global_components["node_to_component"][i]) for i in nodes}
        if len(gids) != 1:
            raise RuntimeError(f"Slot component {key} crosses global components: {sorted(gids)}")
        component_nodes[key] = nodes
        component_global[key] = next(iter(gids))
        demand = sum(
            float(data["demand_event_annual"][(i, key[0], key[1], str(b))])
            for i in nodes for b in data["DEMAND_CLASSES"]
        )
        component_demand[key] = float(demand)
        ndays = float(data["N_MONTH"][key[0]])
        tou = float(data["tou"][key[0]][key[1]])
        for c in data["PUB_TYPES"]:
            component_margin[(key[0], key[1], key[2], str(c))] = float(data["charger_price"][str(c)]) - tou
        component_cap[key] = ndays * max(
            0.0, max(component_margin[(key[0], key[1], key[2], str(c))] for c in data["PUB_TYPES"])
        ) * demand

    # Embedded continuous redirection network. This is a valid LP relaxation of
    # the exact operational MIP: public demand may move only on configured arcs;
    # home demand remains local; trip-bundle integrality, arc activation, and
    # type-pair compensation remain relaxed and are restored by the exact oracle.
    arc_index = [
        (int(i), int(j), str(mon), int(t))
        for i, j, mon, t in data["allowed_st"]
    ]
    model.A = pyo.Set(dimen=4, initialize=arc_index, ordered=True)
    model.Service = pyo.Var(model.I, model.M, model.H, model.C, domain=pyo.NonNegativeReals)
    model.HomeServed = pyo.Var(model.I, model.M, model.H, domain=pyo.NonNegativeReals)
    model.PublicLocal = pyo.Var(model.I, model.M, model.H, domain=pyo.NonNegativeReals)
    model.Redirect = pyo.Var(model.A, domain=pyo.NonNegativeReals)
    model.SlackHome = pyo.Var(model.I, model.M, model.H, domain=pyo.NonNegativeReals)
    model.SlackPublic = pyo.Var(model.I, model.M, model.H, domain=pyo.NonNegativeReals)
    model.Theta = pyo.Var(model.COMP, domain=pyo.Reals)

    home_demand = {
        (int(i), str(mon), int(t)): float(
            data["demand_event_annual"][(int(i), str(mon), int(t), "home")]
        )
        for i in data["hex_ids"] for mon in data["MONTHS"] for t in data["INTERVALS"]
    }
    public_demand = {
        (int(i), str(mon), int(t)): float(
            data["demand_event_annual"][(int(i), str(mon), int(t), "public")]
        )
        for i in data["hex_ids"] for mon in data["MONTHS"] for t in data["INTERVALS"]
    }
    outgoing: dict[tuple[int, str, int], tuple[tuple[int, int, str, int], ...]] = {}
    incoming: dict[tuple[int, str, int], tuple[tuple[int, int, str, int], ...]] = {}
    tmp_out: dict[tuple[int, str, int], list[tuple[int, int, str, int]]] = {}
    tmp_in: dict[tuple[int, str, int], list[tuple[int, int, str, int]]] = {}
    redir_cost: dict[tuple[int, int, str, int], float] = {}
    x_kwh = float(cfg["x_kwh_per_trip"])
    for arc in arc_index:
        i, j, mon, t = arc
        tmp_out.setdefault((i, mon, t), []).append(arc)
        tmp_in.setdefault((j, mon, t), []).append(arc)
        redir_cost[arc] = float(data["T_dict"][(i, j)]) / x_kwh
    for i in data["hex_ids"]:
        ii = int(i)
        for mon in data["MONTHS"]:
            mm = str(mon)
            for t in data["INTERVALS"]:
                tt = int(t)
                outgoing[(ii, mm, tt)] = tuple(tmp_out.get((ii, mm, tt), ()))
                incoming[(ii, mm, tt)] = tuple(tmp_in.get((ii, mm, tt), ()))

    model.SiteTypeCapacity = pyo.Constraint(
        model.I, model.M, model.H, model.C,
        rule=lambda m, i, mon, t, c: m.Service[i, mon, t, c] <= m.K[c] * m.x[i, c],
    )
    model.HomeDemandBalance = pyo.Constraint(
        model.I, model.M, model.H,
        rule=lambda m, i, mon, t: m.HomeServed[i, mon, t] + m.SlackHome[i, mon, t]
        == home_demand[(int(i), str(mon), int(t))],
    )
    model.PublicOriginBalance = pyo.Constraint(
        model.I, model.M, model.H,
        rule=lambda m, i, mon, t: m.PublicLocal[i, mon, t]
        + pyo.quicksum(m.Redirect[a] for a in outgoing[(int(i), str(mon), int(t))])
        + m.SlackPublic[i, mon, t]
        == public_demand[(int(i), str(mon), int(t))],
    )
    model.DestinationServiceBalance = pyo.Constraint(
        model.I, model.M, model.H,
        rule=lambda m, i, mon, t: pyo.quicksum(m.Service[i, mon, t, c] for c in m.C)
        == m.HomeServed[i, mon, t] + m.PublicLocal[i, mon, t]
        + pyo.quicksum(m.Redirect[a] for a in incoming[(int(i), str(mon), int(t))]),
    )

    def theta_relaxation(m, mon, t, cid):
        key = (str(mon), int(t), int(cid))
        ndays = float(data["N_MONTH"][key[0]])
        nodes = component_nodes[key]
        gross = pyo.quicksum(
            component_margin[(key[0], key[1], key[2], str(c))] * m.Service[i, mon, t, c]
            for i in nodes for c in m.C
        )
        shortage = float(cfg["penalty_per_kwh_slack"]) * pyo.quicksum(
            m.SlackHome[i, mon, t] + m.SlackPublic[i, mon, t] for i in nodes
        )
        distance = pyo.quicksum(
            redir_cost[a] * m.Redirect[a]
            for i in nodes for a in outgoing[(int(i), key[0], key[1])]
        )
        return m.Theta[mon, t, cid] <= ndays * (gross - shortage - distance)

    model.ThetaRelaxation = pyo.Constraint(model.COMP, rule=theta_relaxation)
    model.ThetaCap = pyo.Constraint(
        model.COMP,
        rule=lambda m, mon, t, cid: m.Theta[mon, t, cid]
        <= component_cap[(str(mon), int(t), int(cid))],
    )

    # Cell-local linked annual PV/BESS relaxation. Charge/discharge exclusivity is
    # relaxed, but the monolithic January initial SoC and all month links are kept.
    model.PVDir = pyo.Var(model.I, model.M, model.H, domain=pyo.NonNegativeReals)
    model.PVBatt = pyo.Var(model.I, model.M, model.H, domain=pyo.NonNegativeReals)
    model.GridBatt = pyo.Var(model.I, model.M, model.H, domain=pyo.NonNegativeReals)
    model.BattDis = pyo.Var(model.I, model.M, model.H, domain=pyo.NonNegativeReals)
    model.SOC = pyo.Var(model.I, model.M, model.HSOC, domain=pyo.NonNegativeReals)

    model.PVGeneration = pyo.Constraint(
        model.I, model.M, model.H,
        rule=lambda m, i, mon, t: m.PVDir[i, mon, t] + m.PVBatt[i, mon, t]
        <= float(data["pv_kwh_per_panel_slot_at_cf1"])
        * float(data["pv_cf"][str(mon)][int(t)]) * m.PV[i],
    )
    model.DirectEnergyUse = pyo.Constraint(
        model.I, model.M, model.H,
        rule=lambda m, i, mon, t: m.PVDir[i, mon, t] + m.BattDis[i, mon, t]
        <= pyo.quicksum(m.Service[i, mon, t, c] for c in m.C),
    )
    model.BattChargePower = pyo.Constraint(
        model.I, model.M, model.H,
        rule=lambda m, i, mon, t: m.GridBatt[i, mon, t] + m.PVBatt[i, mon, t]
        <= float(data["K_BATT"]) * m.Batt[i],
    )
    model.BattDischargePower = pyo.Constraint(
        model.I, model.M, model.H,
        rule=lambda m, i, mon, t: m.BattDis[i, mon, t]
        <= float(data["K_BATT"]) * m.Batt[i],
    )

    last_h = max(int(t) for t in data["INTERVALS"])
    model.BatteryInitialJanuary = pyo.Constraint(
        model.I,
        rule=lambda m, i: m.SOC[i, "January", 0]
        == float(cfg["initial_soc_fraction"]) * float(cfg["battery_cell_cap_kwh"]) * m.Batt[i],
    )

    def month_link(m, i, mon):
        if str(mon) == "January":
            return pyo.Constraint.Skip
        prev = str(data["prev_month"][str(mon)])
        return m.SOC[i, mon, 0] == m.SOC[i, prev, last_h]

    model.BatteryMonthLink = pyo.Constraint(model.I, model.M, rule=month_link)
    model.BatteryDynamics = pyo.Constraint(
        model.I, model.M, model.H,
        rule=lambda m, i, mon, t: m.SOC[i, mon, t]
        == m.SOC[i, mon, int(t) - 1]
        + float(cfg["eta_charge"]) * (m.GridBatt[i, mon, t] + m.PVBatt[i, mon, t])
        - (1.0 / float(cfg["eta_discharge"])) * m.BattDis[i, mon, t],
    )
    model.BatteryUpper = pyo.Constraint(
        model.I, model.M, model.HSOC,
        rule=lambda m, i, mon, t: m.SOC[i, mon, t]
        <= float(cfg["soc_max_fraction"]) * float(cfg["battery_cell_cap_kwh"]) * m.Batt[i],
    )
    model.BatteryLower = pyo.Constraint(
        model.I, model.M, model.HSOC,
        rule=lambda m, i, mon, t: m.SOC[i, mon, t]
        >= float(cfg["soc_min_fraction"]) * float(cfg["battery_cell_cap_kwh"]) * m.Batt[i],
    )

    energy_credit = pyo.quicksum(
        float(data["N_MONTH"][str(mon)]) * float(data["tou"][str(mon)][int(t)])
        * (model.PVDir[i, mon, t] + model.BattDis[i, mon, t] - model.GridBatt[i, mon, t])
        for i in model.I for mon in model.M for t in model.H
    )
    surrogate_profit = (
        pyo.quicksum(model.Theta[k] for k in model.COMP)
        + energy_credit
        - _annual_capex_expr(model)
    )

    model.Eta = pyo.Var(domain=pyo.Reals)
    model.EmbeddedRelaxation = pyo.Constraint(expr=model.Eta <= surrogate_profit)
    revenue_cap = _annual_revenue_cap(data)
    model.GlobalRevenueCap = pyo.Constraint(expr=model.Eta <= revenue_cap)

    model.HallCuts = pyo.ConstraintList()
    model.ComponentLPCuts = pyo.ConstraintList()
    model.PartialLogicCuts = pyo.ConstraintList()
    model.PartialCutLinks = pyo.ConstraintList()
    model.PartialCutIndicators = pyo.VarList(domain=pyo.Binary)
    model.AnnualLPCuts = pyo.ConstraintList()
    model.ExactConfigCuts = pyo.ConstraintList()
    model.Objective = pyo.Objective(expr=model.Eta, sense=pyo.maximize)

    model._slot_components = slot_components
    model._global_components = global_components
    model._component_nodes = component_nodes
    model._component_global = component_global
    model._component_demand = component_demand
    model._component_cap = component_cap
    model._component_margin = component_margin
    model._x_upper = x_ub
    model._pv_upper = pv_ub
    model._batt_upper = batt_ub
    model._bits_x = bits_x
    model._bits_pv = bits_pv
    model._bits_batt = bits_batt
    model._eta_upper = float(revenue_cap)
    model._hall_signatures: set[tuple] = set()
    model._component_lp_signatures: set[tuple] = set()
    model._partial_logic_signatures: set[tuple] = set()
    model._partial_threshold_cache: dict[tuple[int, str, int], object] = {}
    model._annual_lp_signatures: set[tuple] = set()
    model._exact_config_signatures: set[tuple] = set()
    return model


def add_static_origin_profit_cuts(model: pyo.ConcreteModel, data: dict) -> int:
    """Add singleton Hall/reachability cuts before the first master solve.

    For each home origin, only its own cell is reachable. For each public origin,
    the origin and all active outgoing destinations are reachable. If the capacity
    in this neighbourhood is below that origin's demand, the exact recourse must
    incur at least the corresponding slack. The cut uses the configured slack
    penalty and therefore remains valid without imposing zero slack as a hard rule.
    """
    outgoing: dict[tuple[str, int, int], set[int]] = {}
    for i, j, mon, t in data["allowed_st"]:
        outgoing.setdefault((str(mon), int(t), int(i)), set()).add(int(j))

    added = 0
    for key in model.COMP:
        mon, t, cid = str(key[0]), int(key[1]), int(key[2])
        total = float(model._component_demand[(mon, t, cid)])
        for i in model._component_nodes[(mon, t, cid)]:
            home = float(data["demand_event_annual"][(int(i), mon, t, "home")])
            if home > 1e-10:
                cert = HallCertificate(
                    month=mon, time_index=t, component_id=cid,
                    origin_demand_kwh_day=home, destination_nodes=(int(i),),
                    origin_labels=(f"home:{int(i)}",), total_demand_kwh_day=total,
                    max_served_kwh_day=0.0, unavoidable_slack_kwh_day=home,
                    source_iteration=0, certificate_kind="static_home_neighbourhood",
                )
                added += int(add_hall_profit_cut(model, data, cert))

            public = float(data["demand_event_annual"][(int(i), mon, t, "public")])
            if public > 1e-10:
                destinations = {int(i)}
                destinations.update(outgoing.get((mon, t, int(i)), set()))
                cert = HallCertificate(
                    month=mon, time_index=t, component_id=cid,
                    origin_demand_kwh_day=public, destination_nodes=tuple(sorted(destinations)),
                    origin_labels=(f"public:{int(i)}",), total_demand_kwh_day=total,
                    max_served_kwh_day=0.0, unavoidable_slack_kwh_day=public,
                    source_iteration=0, certificate_kind="static_public_neighbourhood",
                )
                added += int(add_hall_profit_cut(model, data, cert))
    return int(added)


def extract_investment(model: pyo.ConcreteModel) -> InvestmentPoint:
    return InvestmentPoint(
        x={(int(i), str(c)): int(round(float(pyo.value(model.x[i, c])))) for i in model.I for c in model.C},
        pv={int(i): int(round(float(pyo.value(model.PV[i])))) for i in model.I},
        batt={int(i): int(round(float(pyo.value(model.Batt[i])))) for i in model.I},
    )


def _configuration_mismatch(model: pyo.ConcreteModel, investment: InvestmentPoint):
    terms = []
    for (i, c), ks in model._bits_x.items():
        val = int(investment.x.get((int(i), str(c)), 0))
        for k in ks:
            bit = (val >> int(k)) & 1
            terms.append((1 - model.xbit[int(i), str(c), int(k)]) if bit else model.xbit[int(i), str(c), int(k)])
    for i, ks in model._bits_pv.items():
        val = int(investment.pv.get(int(i), 0))
        for k in ks:
            bit = (val >> int(k)) & 1
            terms.append((1 - model.pvbit[int(i), int(k)]) if bit else model.pvbit[int(i), int(k)])
    for i, ks in model._bits_batt.items():
        val = int(investment.batt.get(int(i), 0))
        for k in ks:
            bit = (val >> int(k)) & 1
            terms.append((1 - model.battbit[int(i), int(k)]) if bit else model.battbit[int(i), int(k)])
    return pyo.quicksum(terms) if terms else 0.0


def add_exact_config_cut(model: pyo.ConcreteModel, cut: ExactConfigCut) -> bool:
    signature = (
        tuple(sorted((int(i), str(c), int(v)) for (i, c), v in cut.investment.x.items())),
        tuple(sorted((int(i), int(v)) for i, v in cut.investment.pv.items())),
        tuple(sorted((int(i), int(v)) for i, v in cut.investment.batt.items())),
        round(float(cut.upper_bound), 5),
    )
    if signature in model._exact_config_signatures:
        return False
    mismatch = _configuration_mismatch(model, cut.investment)
    relax = max(0.0, float(model._eta_upper) - float(cut.upper_bound))
    model.ExactConfigCuts.add(model.Eta <= float(cut.upper_bound) + relax * mismatch)
    model._exact_config_signatures.add(signature)
    return True


def component_lp_cut_rhs(cut: LPBendersCut, x_values: dict[tuple[int, str], float]) -> float:
    return float(cut.constant) + sum(
        float(v) * float(x_values.get((int(i), str(c)), 0.0))
        for (i, c), v in cut.coefficients.items()
    )


def component_lp_cut_violation(model: pyo.ConcreteModel, cut: LPBendersCut, x_values: dict[tuple[int, str], float]) -> float:
    key = (str(cut.month), int(cut.time_index), int(cut.component_id))
    theta = pyo.value(model.Theta[key], exception=False)
    if theta is None:
        theta = float(model._component_cap[key])
    return float(theta) - component_lp_cut_rhs(cut, x_values)


def add_component_lp_cut(model: pyo.ConcreteModel, cut: LPBendersCut, tolerance: float = 1e-10) -> bool:
    key = (str(cut.month), int(cut.time_index), int(cut.component_id))
    coeff = {(int(i), str(c)): float(v) for (i, c), v in cut.coefficients.items() if abs(float(v)) > tolerance}
    signature = (
        key, round(float(cut.constant), 6),
        tuple(sorted((i, c, round(v, 6)) for (i, c), v in coeff.items())),
    )
    if signature in model._component_lp_signatures:
        return False
    rhs = float(cut.constant) + pyo.quicksum(v * model.x[i, c] for (i, c), v in coeff.items())
    model.ComponentLPCuts.add(model.Theta[key] <= rhs)
    model._component_lp_signatures.add(signature)
    return True


def add_hall_profit_cut(model: pyo.ConcreteModel, data: dict, certificate: HallCertificate) -> bool:
    """Add a slack-preserving Hall/min-cut recourse cut.

    Unlike a hard capacity inequality, this cut does not remove layouts that are
    feasible through the monolithic slack variables. It bounds the component-slot
    baseline profit by charging the same configured slack penalty for capacity that
    the min-cut proves cannot serve the selected origins.
    """
    key = (str(certificate.month), int(certificate.time_index), int(certificate.component_id))
    destinations = tuple(sorted(int(j) for j in certificate.destination_nodes))
    origins = tuple(sorted(str(v) for v in certificate.origin_labels))
    signature = (key, origins, destinations, round(float(certificate.origin_demand_kwh_day), 8))
    if signature in model._hall_signatures:
        return False
    origin_demand = float(certificate.origin_demand_kwh_day)
    if origin_demand <= 1e-10:
        return False
    ndays = float(data["N_MONTH"][key[0]])
    max_margin = max(float(model._component_margin[(key[0], key[1], key[2], str(c))]) for c in data["PUB_TYPES"])
    total_demand = float(model._component_demand[key])
    penalty = float(pyo.value(model.Penalty))
    constant = ndays * (max_margin * total_demand - (max_margin + penalty) * origin_demand)
    capacity_credit = pyo.quicksum(
        ndays * (max_margin + penalty) * float(data["charger_capacity_pub"][str(c)]) * model.x[j, str(c)]
        for j in destinations for c in data["PUB_TYPES"]
    )
    model.HallCuts.add(model.Theta[key] <= constant + capacity_credit)
    model._hall_signatures.add(signature)
    return True


def partial_logic_cut_violation(model: pyo.ConcreteModel, cut: ComponentLogicOptimalityCut) -> float:
    key = (str(cut.month), int(cut.time_index), int(cut.component_id))
    theta = pyo.value(model.Theta[key], exception=False)
    if theta is None:
        theta = float(model._component_cap[key])
    return float(theta) - min(float(model._component_cap[key]), float(cut.operation_upper_bound))


def add_partial_component_logic_cut(model: pyo.ConcreteModel, cut: ComponentLogicOptimalityCut) -> bool:
    """Monotone partial-assignment cut for one slot component.

    Baseline recourse profit excludes investment capex and is nondecreasing in
    installed charger counts. Therefore, the exact MIP upper bound obtained at
    xbar is also valid for every local assignment x <= xbar. Binary indicators
    relax the cut only when at least one local charger count exceeds xbar. This
    covers all component-wise subsets and is strictly more reusable than an exact
    local-pattern no-good cut.
    """
    key = (str(cut.month), int(cut.time_index), int(cut.component_id))
    nodes = tuple(int(i) for i in model._component_nodes[key])
    local = tuple(sorted((i, str(c), int(cut.x_values[(i, str(c))])) for i in nodes for c in model.C))
    q_upper = min(float(model._component_cap[key]), float(cut.operation_upper_bound))
    signature = (key, local, round(q_upper, 6), "downset")
    if signature in model._partial_logic_signatures:
        return False

    exceed_terms = []
    for i, c, xbar in local:
        upper = int(model._x_upper[(int(i), str(c))])
        if xbar >= upper:
            continue
        threshold_key = (int(i), str(c), int(xbar))
        indicator = model._partial_threshold_cache.get(threshold_key)
        if indicator is None:
            indicator = model.PartialCutIndicators.add()
            # Exact threshold equivalence: indicator = 1 iff x[i,c] >= xbar + 1.
            model.PartialCutLinks.add(
                model.x[int(i), str(c)] <= int(xbar) + (upper - int(xbar)) * indicator
            )
            model.PartialCutLinks.add(
                model.x[int(i), str(c)] >= (int(xbar) + 1) * indicator
            )
            model._partial_threshold_cache[threshold_key] = indicator
        exceed_terms.append(indicator)
    exceed = pyo.quicksum(exceed_terms) if exceed_terms else 0.0
    cap = float(model._component_cap[key])
    model.PartialLogicCuts.add(model.Theta[key] <= q_upper + max(0.0, cap - q_upper) * exceed)
    model._partial_logic_signatures.add(signature)
    return True


def add_annual_lp_cut(model: pyo.ConcreteModel, cut: AnnualLPDualCut, tolerance: float = 1e-9) -> bool:
    signature = (
        round(float(cut.constant), 5),
        tuple(sorted((int(i), str(c), round(float(v), 5)) for (i, c), v in cut.x_coefficients.items() if abs(float(v)) > tolerance)),
        tuple(sorted((int(i), round(float(v), 5)) for i, v in cut.pv_coefficients.items() if abs(float(v)) > tolerance)),
        tuple(sorted((int(i), round(float(v), 5)) for i, v in cut.batt_coefficients.items() if abs(float(v)) > tolerance)),
    )
    if signature in model._annual_lp_signatures:
        return False
    rhs = float(cut.constant)
    rhs += pyo.quicksum(float(v) * model.x[int(i), str(c)] for (i, c), v in cut.x_coefficients.items() if abs(float(v)) > tolerance)
    rhs += pyo.quicksum(float(v) * model.PV[int(i)] for i, v in cut.pv_coefficients.items() if abs(float(v)) > tolerance)
    rhs += pyo.quicksum(float(v) * model.Batt[int(i)] for i, v in cut.batt_coefficients.items() if abs(float(v)) > tolerance)
    model.AnnualLPCuts.add(model.Eta <= rhs)
    model._annual_lp_signatures.add(signature)
    return True
