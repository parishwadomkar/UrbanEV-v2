# UrbanEV-v2 (`VIPVmain`) - Cost-aware, Adaptive and VIPV-enabled EV Charging in MATSim

UrbanEV-v2 is a research-oriented extension of the UrbanEV framework for **spatiotemporal EV charging-demand estimation** in MATSim. The `VIPVmain` branch extends the cost-aware and ToU-aware charging framework with **vehicle-integrated photovoltaics (VIPV)**, including seasonal solar generation, battery SoC updates, open-parking exposure, and tracking of produced, stored, and curtailed PV energy.

This branch is developed from the cost-aware and adaptive smart-charging implementation available in the [`master`](https://github.com/parishwadomkar/UrbanEV-v2/tree/master) branch.

![Simulated EV Charging User Behavior](https://github.com/user-attachments/assets/6b031a4d-e4e2-49a3-995c-f0d29c4a3032)

---

## What this repository adds (vs. UrbanEV)

UrbanEV-v2 preserves UrbanEV's **multi-criteria charging behavior** and charging-infrastructure logic while extending the framework in three main directions:

1. **Cost-aware charging scoring**  
   Charging decisions internalize monetary charging costs through additional utility terms, allowing different tariffs for home, work, and public charging.

2. **Adaptive ToU-aware smart charging**  
   For eligible home-charging activities, charging can be deferred within the available parking window toward lower-cost periods. The response is controlled through configurable awareness, temporal-shift, and coincidence parameters.

3. **Vehicle-integrated photovoltaic generation**  
   A configurable share or explicit list of EVs can be equipped with VIPV. Solar electricity is generated during driving and during probabilistically selected open-parking episodes. Generated energy is added directly to vehicle battery SoC subject to battery-capacity limits, while excess energy is recorded as wasted/curtailed PV energy.

The selected simulation `season` controls both the **seasonal ToU profile** and the **seasonal PV potential profile**.

---

## Key features

- Multi-day MATSim simulations, including 7+ day / 170+ hour activity plans.
- Public charger infrastructure from `chargers.xml`.
- Home/work charging access through person attributes.
- Battery SoC evolution from driving consumption, grid charging, and VIPV generation.
- UrbanEV charging-choice behavior with range-anxiety, empty-battery, walking-distance, and SoC-balance utilities.
- Charger-type-specific monetary charging costs.
- Optional ToU-aware home-charging rescheduling.
- Seasonal profiles for **SPRING, SUMMER, AUTUMN, and WINTER**.
- VIPV assignment through an explicit vehicle CSV or a configurable fleet share.
- VIPV generation while driving and during open-parking episodes.
- Explicit accounting of **PV energy produced, stored, and wasted**.
- Iteration-level VIPV charging-instance outputs for validation and post-processing.

---

## Inputs

### 1) Population plans (MATSim population v6)

EV charging behavior uses person attributes including:

- `rangeAnxietyThreshold`
- `homeChargerPower` (kW)
- `workChargerPower` (kW)
- `smartChargingAware` (boolean; assigned at runtime from `awarenessFactor` unless already provided)

### 2) Electric vehicles (UrbanEV / EV DTD)

Electric vehicles are provided through the UrbanEV EV XML and contain battery capacity, initial SoC, vehicle type, and compatible charger types.

### 3) Vehicle types (`vehicletypes.xml`)

Vehicle types define energy consumption and charging-relevant vehicle parameters used by UrbanEV.

### 4) Chargers (`chargers_v1.dtd`)

Public chargers are defined by location/link, charger type, plug power, and plug count.

### 5) VIPV vehicle list (optional CSV)

VIPV-equipped vehicles can be specified using `pvVehiclesFile`.

Example:

```csv
vehicle_id,pv_wp,pv_area_m2,pv_eff
1838887,400.0,2.0,0.20
1839223,400.0,2.0,0.20
1839970,400.0,2.0,0.20
```

The first column is interpreted as the EV ID. Additional columns may be retained for scenario documentation, but the current loader uses the vehicle ID only. VIPV rated power is controlled globally through `pvWp`.

If the CSV is missing or cannot provide valid fleet IDs, `pvShare` is used as the fallback assignment share.

---

## Repository layout (Gothenburg, Sweden)

- `src/main/java/se/urbanEV/` — UrbanEV-v2 Java sources
  - `charging/` — charging logic, ToU cost handling, and smart charging
  - `discharging/` — driving and auxiliary energy consumption
  - `fleet/` — EV fleet and battery representation
  - `scoring/` — EV-specific and charging-cost scoring
  - `stats/` — charging and SoC statistics
  - `pv/` — VIPV generation and statistics
    - `PvModule`
    - `PvVehicleRegistry`
    - `PvVehicleCsvLoader`
    - `PvPotentialUtils`
    - `PvGenerationHandler`
    - `PvChargingIntervalEvent`
    - `PvChargingIntervalCollector`
    - `PvChargingStatsWriter`
- `scenarios/` — MATSim scenario inputs and outputs
- `pom.xml` — Maven configuration

A scenario typically contains:

- MATSim config (`config.xml`)
- network (`network.xml(.gz)`)
- population (`plans.xml(.gz)`)
- chargers (`chargers.xml`)
- electric vehicles (`electric_vehicles.xml`)
- vehicle types (`vehicletypes.xml`)
- optional VIPV vehicle CSV

---

## Configuration: `urban_ev` module

The `urban_ev` config group contains the inherited UrbanEV parameters together with the cost-aware, smart-charging, seasonal, and VIPV controls.

### Example: seasonal smart charging + VIPV

```xml
<module name="urban_ev">
    <param name="parkingSearchRadius" value="500"/>
    <param name="defaultRangeAnxietyThreshold" value="0.2"/>
    <param name="vehicleTypesFile" value="vehicletypes.xml"/>
    <param name="rangeAnxietyUtility" value="-8"/>
    <param name="emptyBatteryUtility" value="-12"/>
    <param name="walkingUtility" value="-1"/>
    <param name="homeChargingUtility" value="0"/>
    <param name="socDifferenceUtility" value="-10"/>
    <param name="maxNumberSimultaneousPlanChanges" value="2"/>
    <param name="timeAdjustmentProbability" value="0.2"/>
    <param name="maxTimeFlexibility" value="600"/>

    <param name="generateHomeChargersByPercentage" value="false"/>
    <param name="homeChargerPercentage" value="80"/>
    <param name="defaultHomeChargerPower" value="11"/>
    <param name="generateWorkChargersByPercentage" value="false"/>
    <param name="workChargerPercentage" value="20"/>
    <param name="defaultWorkChargerPower" value="11"/>

    <!-- Charger costs -->
    <param name="homeChargingCost" value="2.5"/>
    <param name="workChargingCost" value="4.0"/>
    <param name="publicChargingCost" value="5.5"/>
    <param name="betaMoney" value="-0.06"/>          <!-- 0.0 disables monetary charging-cost scoring -->
    <param name="alphaScaleCost" value="0.5"/>

    <!-- Smart charging -->
    <param name="enableSmartCharging" value="true"/> <!-- false disables smart rescheduling -->
    <param name="alphaScaleTemporal" value="0.2"/>
    <param name="awarenessFactor" value="0.3"/>
    <param name="coincidenceFactor" value="0.7"/>    <!-- higher = lower dispersion -->

    <!-- Seasonal ToU + VIPV -->
    <param name="season" value="AUTUMN"/>            <!-- SPRING, SUMMER, AUTUMN, WINTER -->
    <param name="pvVehiclesFile" value="scenarios/sweden/10pct/50VIPV_10pct.csv"/>
    <param name="pvParkedOpenShare" value="0.50"/>  <!-- probability per parking episode -->
    <param name="pvShare" value="0.80"/>            <!-- fallback only if CSV loading does not provide PV vehicles -->
    <param name="pvWp" value="400.0"/>              <!-- Wp per VIPV; 0 disables VIPV generation -->
</module>
```

### Parameter interpretation

#### Charging cost and smart charging

- `homeChargingCost`, `workChargingCost`, `publicChargingCost`: base charging tariffs by charging context. Sweden scenarios interpret these as SEK/kWh.
- `betaMoney`: marginal utility of money used to convert charging expenditure into utility. `0.0` removes charging cost from EV scoring.
- `alphaScaleCost`: multiplicative calibration factor applied to the monetary utility term.
- `enableSmartCharging`: enables ToU-aware home-charging start-time rescheduling.
- `alphaScaleTemporal`: controls the temporal shift applied when searching for preferred low-ToU charging periods.
- `awarenessFactor`: share/probability of agents assigned as ToU-aware.
- `coincidenceFactor`: controls dispersion of deferred charging starts; higher values produce less spread around preferred start times.

#### Seasonal and VIPV controls

- `season`: selects the seasonal ToU and PV profiles. Supported values are `SPRING`, `SUMMER`, `AUTUMN`, and `WINTER`.
- `pvVehiclesFile`: CSV containing explicitly selected VIPV vehicle IDs. When successfully loaded, this list takes precedence over `pvShare`.
- `pvShare`: fallback fraction `[0,1]` of the EV fleet assigned VIPV if the configured CSV cannot provide a valid vehicle set.
- `pvWp`: rated VIPV capacity in Wp applied to each equipped vehicle. Set to `0` to disable VIPV generation.
- `pvParkedOpenShare`: probability `[0,1]` that each parking episode of a VIPV is exposed to open-sky solar conditions. For example, `0.50` means that approximately half of parking episodes are treated as solar-exposed.

---

## VIPV simulation logic

For a VIPV-equipped vehicle, the instantaneous PV power is calculated from the configured rated power and the selected seasonal PV potential. The seasonal hourly factors are stored in `PvPotentialUtils` and are based on the PVGIS profiles used for the Gothenburg scenarios:

```text
PV power = pvWp × seasonal PV potential factor(hour)
PV energy = PV power × simulation time step
```

VIPV generation is applied:

- continuously while the vehicle is **driving**;
- while **parked** only when the current parking episode is sampled as open according to `pvParkedOpenShare`;
- independently of plug-in charging, so solar generation can also contribute while a solar-exposed vehicle is parked and charging.

The generated energy is added directly to the vehicle battery. Battery capacity is enforced, therefore:

```text
PV produced = PV stored + PV wasted
```

Energy that cannot be stored because the battery is full is recorded as wasted/curtailed VIPV energy.

---

## Outputs

UrbanEV-v2 produces the standard MATSim outputs together with EV and VIPV-specific statistics.

Typical outputs include:

- charging-demand time series;
- spatial charging demand by charger/link/location;
- home, work, and public charging demand;
- individual EV SoC time profiles;
- charging times and charging costs;
- ToU load-shifting and peak-demand effects;
- VIPV generation during driving and open-parking episodes.

For VIPV-enabled runs, each iteration additionally produces:

```text
<iteration>.pv_charging_instances.csv
```

The file records contiguous VIPV generation intervals with fields including:

- vehicle ID;
- PV interval start and end time;
- mode (`DRIVING` or `PARKED_OPEN`);
- PV energy produced;
- PV energy stored in the EV battery;
- PV energy wasted because of the battery-capacity limit;
- battery SoC at the start and end of the interval.

These outputs allow direct comparison of no-VIPV and VIPV scenarios in terms of battery SoC, grid charging demand, charging timing, and seasonal solar contribution.

For the original cost-aware and adaptive smart-charging branch and associated results, see the [`master`](https://github.com/parishwadomkar/UrbanEV-v2/tree/master) branch.

---

## Requirements

- **Java 11 / MATSim 12.0-compatible toolchain**
- **Maven**

Memory requirements depend strongly on the simulated population sample and number of iterations.

---

## Run from console

Clone the VIPV branch and build the executable jar:

```bash
git clone --branch VIPVmain --single-branch https://github.com/parishwadomkar/UrbanEV-v2.git
cd UrbanEV-v2
mvn clean install
```

Run a scenario by supplying its MATSim configuration file:

```bash
java -Xms16g -Xmx16g -jar target/*jar-with-dependencies.jar <path-to-config.xml>
```

For larger 10% scenarios, increase the JVM memory allocation as required by the available hardware.

---

## License

GPL-3.0, consistent with UrbanEV / MATSim licensing constraints. See `LICENSE`.

The project builds on contributions from the MATSim community. Classes adapted from upstream projects retain the corresponding author information, modification notices, and original license text where applicable.

---

## Contact / support

**Omkar Parishwad**  
Urban Mobility Research Group  
Chalmers University of Technology  
mail: omkarp@chalmers.se

For bugs, questions, or collaboration, please open a GitHub Issue in this repository. For MATSim-core or MATSim-EV questions, consult the MATSim documentation and community channels.

---

## Associated Articles

The cost-aware and adaptive charging framework underlying this VIPV branch is described in:

- **Parishwad, Omkar; Gao, Kun; Najafi, Arsalan** — *Integrated and Agent-Based Charging Demand Prediction Considering Cost-Aware and Adaptive Charging Behavior*. **Transportation Research Part D: Transport and Environment**, 154 (2026) 105285.  
  DOI: https://doi.org/10.1016/j.trd.2026.105285

UrbanEV-v2 is rooted in the original UrbanEV framework:

- **Adenaw, L.; Lienkamp, M.** — *Multi-Criteria, Co-Evolutionary Charging Behavior: An Agent-Based Simulation of Urban Electromobility*. **World Electric Vehicle Journal**, 12(1), 18 (2021).  
  DOI: https://doi.org/10.3390/wevj12010018
- Upstream UrbanEV codebase: https://github.com/TUMFTM/UrbanEV

Related downstream infrastructure-planning work uses charging-demand outputs from this simulation in a separate codebase:

- **Parishwad, Omkar; Najafi, Arsalan; Gao, Kun** — *Joint optimization of charging infrastructure and renewable energies with battery storage considering user redirection incentives*. SSRN preprint.  
  DOI: https://doi.org/10.2139/ssrn.5395539  
  Code: https://github.com/parishwadomkar/Large-scale-LBBD-Optimization

Additional project context:

- **Omkar Parishwad — PhD Thesis / Chalmers publication page**  
  https://research.chalmers.se/publication/547894

---
