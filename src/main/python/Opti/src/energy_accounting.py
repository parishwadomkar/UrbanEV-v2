from __future__ import annotations

import pyomo.environ as pyo


def energy_boundary_metrics(model, data, cfg):
    def annual(component):
        return sum(data["N_MONTH"][mon] * pyo.value(component[i, mon, t])
                   for i in model.I for mon in model.M for t in model.H)

    grid = annual(model.grid_dir) + annual(model.grid_batt)
    solar = annual(model.pv_dir) + annual(model.pv_batt)
    charge = annual(model.grid_batt) + annual(model.pv_batt)
    discharge = annual(model.batt_discharge)
    losses = (1 - cfg["eta_charge"]) * charge + (1 / cfg["eta_discharge"] - 1) * discharge
    served = sum(data["N_MONTH"][mon] * pyo.value(model.edisp[i, mon, t, c, b])
                 for i in model.I for mon in model.M for t in model.H for c in model.C_pub for b in model.B)
    storage = sum(data["N_MONTH"][mon] * (pyo.value(model.soc[i, mon, max(model.H)]) - pyo.value(model.soc[i, mon, 0]))
                  for i in model.I for mon in model.M)
    available = sum(data["N_MONTH"][mon] * pyo.value(model.PV[i]) * data["pv_cf"][mon][int(t)] * data["pv_kwh_per_panel_slot_at_cf1"]
                    for i in model.I for mon in model.M for t in model.H)
    return {
        "grid_energy_boundary": "CPO_public_chargers_and_stationary_BESS",
        "bess_boundary": cfg.get("bess_boundary", "legacy_linked_months"),
        "pvgis_input_timezone": cfg.get("pvgis_input_timezone", "as_supplied"),
        "source_provenance_verified": bool(data.get("provenance", {}).get("source_verified", False)),
        "annual_optimizer_served_kWh": served,
        "annual_stationary_battery_losses_kWh": losses,
        "annual_weighted_storage_change_kWh": storage,
        "annual_stationary_PV_available_kWh": available,
        "annual_stationary_PV_curtailed_kWh": available - solar,
        "annual_optimizer_energy_balance_residual_kWh": grid + solar - served - losses - storage,
    }
