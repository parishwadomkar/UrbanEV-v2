# Model assumptions

## Annual structure and accounting

Infrastructure investments are shared across twelve monthly representative days with 48 half-hour intervals. Winter demand applies to December–February, spring to March–May, summer to June–August, and autumn to September–November. Month-day weights sum to 365; this is a representative-day model rather than a chronological annual simulation.

Demand is supplied as interval energy in kWh. Stationary PV energy is panel rating × interval duration × capacity factor × panel count. Hourly electricity prices apply to both half-hours, with configured taxes, fees, markup, and VAT. Capital recovery is counted once annually.

Private home demand is served first up to exogenous home-charger availability. Residual home demand and public demand enter the CPO problem. Reported grid purchases cover CPO chargers and stationary batteries; private-home electricity is outside this supply boundary. VIPV is represented in the demand inputs and is not subtracted again.

## Installation and storage

`PublicRes` limits the weighted sum of public charger counts. `homeChar` specifies available private home chargers, while `Panels` bounds stationary PV. These input values are used directly. BESS installation is limited by `battery_max_units_per_hex`.

`bess_boundary` determines the storage convention:

| Value | State-of-charge boundary |
| --- | --- |
| `legacy_linked_months` | January starts at the configured fraction of capacity; each later month starts at the previous representative day's final state; December is not linked back to January |
| `cyclic_day` | Each monthly representative day ends at its own initial state within the configured state-of-charge limits |

Use one convention consistently across compared methods and treatments. The exported energy audit includes battery losses and day-weighted storage changes.

## Methods and comparisons

Public demand may be redirected along eligible shortest-path arcs when enabled; residual home demand remains local. Without redirection or other inter-site constraints, exact spatial mode solves independent annual site MILPs and aggregates their feasible objectives and bounds. Infrastructure regularization minimizes annualized asset cost within the specified annual profit tolerance.

For decomposition methodology, validation, and benchmark execution, refer to the [original repository](https://github.com/parishwadomkar/Large-scale-LBBD-Optimization) and [paper](https://doi.org/10.1016/j.adapen.2026.100310).

Inspect the achieved gap, termination, service balance, and energy balance in exported results. Restart bounds require the same problem identity. Code/input fingerprints must match within a method comparison; scenario comparisons retain common model assumptions while allowing the declared scenario axis to differ.
