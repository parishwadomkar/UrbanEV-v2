# UrbanEV-v2 (v2.1): Cost-aware and Adaptive EV Charging Demand in MATSim

UrbanEV-v2 is a research oriented extension of the UrbanEV framework that enables **spatiotemporal EV charging-demand estimation** with **explicit charging cost scoring** and **ToU aware (adaptive) charging time rescheduling** in a MATSim-based simulation workflow.


---

## What this repository adds (vs. UrbanEV)

UrbanEV-v2 preserves UrbanEV’s **multi-criteria charging behavior** and infrastructure usage logic, while extending the behavioral model in two key ways:

1. **Cost-aware charging scoring**  
   Charging decisions internalize monetary charging costs via additional utility terms (scaled and converted into MATSim utility units), enabling scenario analysis under different tariff assumptions.

2. **Adaptive (ToU aware) smart charging**  
   When a feasible parking window exists (home/work), charging start times can be **shifted to lower-cost intervals** (Time-of-Use logic) subject to behavioral “awareness” and stochastic coincidence.

These additions are designed to be **config-driven** and avoid heavy restructuring (no requirement to introduce separate EV config formats beyond what UrbanEV already uses).


---

## Key features

- Multi-day simulations (plans can extend beyond 24h; 7+ days / 170+ hours).
- Public charger infrastructure from `chargers.xml`.
- Home/work charging availability via **person attributes** (per-agent access & power).
- Battery SoC evolution and charging feasibility constraints.
- Charging-choice behavior with range-anxiety and convenience considerations (UrbanEV baseline).
- **Charging-cost scoring** and **scenario switching** via `urban_ev` config parameters.
- **ToU aware rescheduling** (optional) for adaptive charging timing.


---

## Inputs

### 1) Population plans (MATSim population v6)
EV access to home/work charging is encoded as **person attributes**:

- `rangeAnxietyThreshold` (agent heterogeneity)
- `homeChargerPower` (kW)
- `workChargerPower` (kW)

### 2) Electric vehicles (UrbanEV / EV DTD)
Electric vehicles are provided via UrbanEV’s EV XML (battery capacity, initial SoC, vehicle type).

### 3) Vehicle types (UrbanEV vehicletypes.xml)
Vehicle types include consumption and max charging rate (as used by UrbanEV).

### 4) Chargers (chargers_v1.dtd)
Public chargers are defined at coordinates with plug power and plug count.


---

## Repository layout (provided data for Gothenburg, Sweden)

- `src/` — Java sources (UrbanEV-v2 modules, scoring extensions, smart charging helpers)
- `scenarios/` — Scenarios (input data and outputs)
  - Each scenario typically includes:
    - MATSim config (`config.xml`)
    - network (`network.xml(.gz)`)
    - population (`plans.xml(.gz)`)
    - chargers (`chargers.xml`)
    - electric vehicles (`electric_vehicles.xml`)
    - vehicle types (UrbanEV-style `vehicletypes.xml`)

---

## Configuration: `urban_ev` module (including cost + smart charging)

UrbanEV-v2 extends the `urban_ev` config module with additional parameters to activate and calibrate **charging cost** and **adaptive smart charging** for ToU aware behavior.

### Cost & Smart Charging parameters (Scenario 3 default: Adaptive smart charging)

```xml
<module name="urban_ev">
    <param name="parkingSearchRadius" value="500"/>
    <param name="defaultRangeAnxietyThreshold" value="0.2"/>
    <param name="vehicleTypesFile" value="vehicletypes.xml"/>

    <param name="rangeAnxietyUtility" value="-10"/>
    <param name="emptyBatteryUtility" value="-30"/>
    <param name="walkingUtility" value="-1"/>
    <param name="homeChargingUtility" value="0"/>
    <param name="socDifferenceUtility" value="-15"/>

    <param name="maxNumberSimultaneousPlanChanges" value="2"/>
    <param name="timeAdjustmentProbability" value="0.1"/>
    <param name="maxTimeFlexibility" value="600"/>

    <param name="generateHomeChargersByPercentage" value="false"/>
    <param name="homeChargerPercentage" value="80"/>
    <param name="defaultHomeChargerPower" value="11"/>

    <param name="generateWorkChargersByPercentage" value="false"/>
    <param name="workChargerPercentage" value="20"/>
    <param name="defaultWorkChargerPower" value="11"/>

    <!-- Charger Costs (OmkarP. 2025) -->
    <!-- Units for Sweden scenarios are interpreted as SEK/kWh -->
    <param name="homeChargingCost" value="2.5"/>
    <param name="workChargingCost" value="4.0"/>
    <param name="publicChargingCost" value="5.5"/>

    <!-- Converts cost into utility (negative betaMoney penalizes cost) -->
    <!-- VoT ~60 SEK/hr; set 0.0 to remove cost from scoring -->
    <param name="betaMoney" value="-0.05"/>

    <!-- Optional scaling knobs for calibration stability -->
    <param name="alphaScaleCost" value="1.0"/>
    <param name="alphaScaleTemporal" value="1.0"/>

    <!-- Smart charging (ToU aware temporal shifting) -->
    <param name="enableSmartCharging" value="true"/>
    <param name="awarenessFactor" value="0.7"/>
    <param name="coincidenceFactor" value="0.3"/>
</module>
```

### Parameter interpretation

- `homeChargingCost` / `workChargingCost` / `publicChargingCost`: base tariffs by charging context (e.g., SEK/kWh) used to compute monetary charging expenditures.
- `betaMoney`: converts monetary cost into MATSim utility (negative values penalize cost); calibrate carefully to avoid overwhelming time/activity utilities.
- `alphaScaleCost`: additional scaling knob for cost disutility to maintain scoring stability during calibration and scenario sweeps.
- `enableSmartCharging`: enables ToU-aware temporal shifting of charging start times within feasible parking windows (Scenario 3).
- `alphaScaleTemporal`: scaling factor used in the temporal optimization objective (kept separate from realized cost scoring).
- `awarenessFactor`: share/probability of agents behaving as ToU-aware (bounded rationality / partial adoption).
- `coincidenceFactor`: probability of “charging immediately anyway” (or not perfectly optimizing) even when ToU-aware, to prevent unrealistic synchronization at tariff minima.

---
## Outputs

UrbanEV-v2 produces standard MATSim outputs (iterations, experienced plans, events) and EV-relevant artifacts depending on configuration (e.g., EV time profiles). Typical post-processing focuses on:

- Charging demand time series (kW / kWh over time)
- Spatial charging demand (by charger / link / zone)
- Charging context split (home vs. work vs. public)
- Cost outcomes (total cost, cost per charge, distributional summaries)
- Behavioral effects of ToU (load shifting metrics, peak reduction)


---
## Requirements

- **Java (MATSim 12.x toolchains)**  
- **Maven** (to build the executable jar)

You will need enough RAM for your scenario scale (1% is typically fine on a workstation; larger samples require more).

---

## Run from console

Clone and build the executable jar (with dependencies) and run by passing the scenario config path:

```bash
git clone https://github.com/parishwadomkar/UrbanEV-v2.git
cd UrbanEV-v2
mvn clean install
java -Xms16g -Xmx16g -jar target/*jar-with-dependencies.jar scenarios/gothenburg/1pct/config.xml
```
To produce an executable “jar-with-dependencies” in `target/`



---
## License

GPL-3.0 (consistent with UrbanEV / MATSim licensing constraints). See `LICENSE`.

---
## Contact / support

**Omkar Parishwad**  
Urban Mobility Research Group  
Chalmers University of Technology  
mail: omkarp@chalmers.se  

For bugs, questions, or collaboration, please open a GitHub Issue in this repository.  
For MATSim-core or MATSim-EV specifics, consult MATSim community channels and documentation.


---
## Associated Article

This repository implements the methods described in:

- **Parishwad, Omkar; Gao, Kun; Najafi, Arsalan** — *Integrated and Agent-Based Charging Demand Prediction Considering Cost-Aware and Adaptive Charging Behavior* (SSRN, Aug 16, 2025).  
  https://ssrn.com/abstract=5582536 (DOI: 10.2139/ssrn.5582536)

- **Omkar Parishwad (PhD Thesis / Chalmers publication page)**  
  https://research.chalmers.se/publication/547894

UrbanEV-v2 is rooted in the original UrbanEV framework by Adenaw & Lienkamp:

- **Adenaw, L.; Lienkamp, M.** *Multi-Criteria, Co-Evolutionary Charging Behavior: An Agent-Based Simulation of Urban Electromobility.* *World Electric Vehicle Journal* 2021, 12(1), 18.  
  https://doi.org/10.3390/wevj12010018  
- Upstream codebase (reference): https://github.com/TUMFTM/UrbanEV


---
