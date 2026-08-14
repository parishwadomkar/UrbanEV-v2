from __future__ import annotations


def apply_technology_switches(model, disable_pv: bool, disable_bess: bool, *, verbose: bool = True) -> None:
    """Fix disabled investment and operational technology variables to zero."""
    if disable_pv:
        if verbose:
            print("Technology switch: PV disabled.")
        if hasattr(model, "PV"):
            for i in model.I:
                model.PV[i].fix(0)
        if hasattr(model, "pv_dir"):
            for i in model.I:
                for mon in model.M:
                    for t in model.H:
                        model.pv_dir[i, mon, t].fix(0)
        if hasattr(model, "pv_batt"):
            for i in model.I:
                for mon in model.M:
                    for t in model.H:
                        model.pv_batt[i, mon, t].fix(0)

    if disable_bess:
        if verbose:
            print("Technology switch: BESS disabled.")
        if hasattr(model, "Batt"):
            for i in model.I:
                model.Batt[i].fix(0)

        soc_time_set = model.Hsoc if hasattr(model, "Hsoc") else getattr(model, "HSOC", model.H)
        if hasattr(model, "soc"):
            for i in model.I:
                for mon in model.M:
                    for t in soc_time_set:
                        model.soc[i, mon, t].fix(0)
        if hasattr(model, "grid_batt"):
            for i in model.I:
                for mon in model.M:
                    for t in model.H:
                        model.grid_batt[i, mon, t].fix(0)
        if hasattr(model, "pv_batt"):
            for i in model.I:
                for mon in model.M:
                    for t in model.H:
                        model.pv_batt[i, mon, t].fix(0)
        if hasattr(model, "batt_discharge"):
            for i in model.I:
                for mon in model.M:
                    for t in model.H:
                        model.batt_discharge[i, mon, t].fix(0)
        if hasattr(model, "delta"):
            for i in model.I:
                for mon in model.M:
                    for t in model.H:
                        model.delta[i, mon, t].fix(0)
