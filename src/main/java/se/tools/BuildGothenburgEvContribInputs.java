package se.tools;

import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.network.Network;
import org.matsim.api.core.v01.population.*;
import org.matsim.contrib.ev.strategic.StrategicChargingUtils;
import org.matsim.contrib.ev.withinday.WithinDayEvUtils;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.network.NetworkUtils;
import org.matsim.core.network.algorithms.TransportModeNetworkFilter;
import org.matsim.core.network.io.MatsimNetworkReader;
import org.matsim.core.population.algorithms.XY2Links;
import org.matsim.core.population.io.PopulationReader;
import org.matsim.core.population.io.PopulationWriter;
import org.matsim.core.population.routes.NetworkRoute;
import org.matsim.core.population.routes.RouteFactories;
import org.matsim.core.router.DijkstraFactory;
import org.matsim.core.router.costcalculators.OnlyTimeDependentTravelDisutility;
import org.matsim.core.router.util.LeastCostPathCalculator;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.core.trafficmonitoring.FreeSpeedTravelTime;
import org.matsim.core.utils.geometry.CoordUtils;
import org.matsim.facilities.ActivityFacility;
import org.matsim.facilities.ActivityFacilities;
import org.matsim.facilities.FacilitiesUtils;
import org.matsim.facilities.FacilitiesWriter;
import org.matsim.vehicles.MatsimVehicleWriter;
import org.matsim.vehicles.Vehicle;
import org.matsim.vehicles.VehicleType;
import org.matsim.vehicles.VehicleUtils;
import org.matsim.vehicles.Vehicles;
import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.NodeList;
import org.xml.sax.InputSource;
import se.got.config.GothenburgBehaviorConfigGroup;
import se.got.config.GothenburgPricingConfigGroup;

import javax.xml.parsers.DocumentBuilder;
import javax.xml.parsers.DocumentBuilderFactory;
import javax.xml.transform.OutputKeys;
import javax.xml.transform.Transformer;
import javax.xml.transform.TransformerFactory;
import javax.xml.transform.dom.DOMSource;
import javax.xml.transform.stream.StreamResult;
import java.io.BufferedWriter;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.StringReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.*;
import java.util.zip.GZIPOutputStream;
import java.util.stream.Collectors;

public final class BuildGothenburgEvContribInputs {
    private static final String IN_CONFIG = "C:\\Users\\omkarp\\IdeaProjects\\VIPVnew\\scenarios\\sweden\\config0.xml";
    private static final String IN_PLANS = "C:\\Users\\omkarp\\IdeaProjects\\VIPVnew\\scenarios\\sweden\\1pct\\GOTplans_1pct7Days.xml.gz";
    private static final String IN_NETWORK = "C:\\Users\\omkarp\\IdeaProjects\\VIPVnew\\scenarios\\sweden\\got_network.xml.gz";
    private static final String IN_LEGACY_EV = "C:\\Users\\omkarp\\IdeaProjects\\VIPVnew\\scenarios\\sweden\\1pct\\evehicles1pct.xml";
    private static final String IN_PUBLIC_CHARGERS = "C:\\Users\\omkarp\\IdeaProjects\\VIPVnew\\scenarios\\sweden\\chargers.xml";

    private static final String OUT_PLANS = "C:\\Users\\omkarp\\IdeaProjects\\VIPVnew\\scenarios\\sweden\\1pct\\GOTplans_1pct7Days_sevc_behavior.xml.gz";
    private static final String OUT_VEHICLES = "C:\\Users\\omkarp\\IdeaProjects\\VIPVnew\\scenarios\\sweden\\1pct\\vehicles_ev.xml.gz";
    private static final String OUT_FACILITIES = "C:\\Users\\omkarp\\IdeaProjects\\VIPVnew\\scenarios\\sweden\\1pct\\facilities_work.xml.gz";
    private static final String OUT_CHARGERS_ALL = "C:\\Users\\omkarp\\IdeaProjects\\VIPVnew\\scenarios\\sweden\\chargers_all.xml";
    private static final String OUT_CHARGERS_PRICED = "C:\\Users\\omkarp\\IdeaProjects\\VIPVnew\\scenarios\\sweden\\chargers_all_priced.xml";

    private static final String OUT_POPULATION_DTD = "../dtd/population_v6.dtd";
    private static final String OUT_CHARGERS_DTD = "../dtd/chargers_v1.dtd";

    private static final String ATTR_WEVC_ACTIVE = "wevc:active";
    private static final String ATTR_WEVC_MAX_SOC = "wevc:maximumSoc";

    private static final String ATTR_MIN_SOC = "sevc:minimumSoc";
    private static final String ATTR_MIN_END_SOC = "sevc:minimumEndSoc";
    private static final String ATTR_TARGET_SOC = "sevc:targetSoc";

    private static final String ATTR_HOME_POWER = "homeChargerPower";
    private static final String ATTR_WORK_POWER = "workChargerPower";

    private static final String ATTR_CHARGER_TYPES = "chargerTypes";
    private static final String ATTR_INITIAL_SOC = "initialSoc";
    private static final String ATTR_DRIVE_CONS_WH_KM = "driveEnergyConsumption_Wh_km";

    private static final String ATTR_COST_PER_USE = "secv:costPerUse";
    private static final String ATTR_COST_PER_ENERGY = "secv:costPerEnergy_kWh";
    private static final String ATTR_COST_PER_DURATION = "secv:costPerDuration_min";
    private static final String ATTR_COST_PER_BLOCKING_DURATION = "secv:costPerBlockingDuration_min";
    private static final String ATTR_BLOCKING_DURATION = "secv:blockingDuration_min";
    private static final String ATTR_COST_PER_RESERVATION = "secv:costPerReservation";
    private static final String ATTR_DYNAMIC_COST_PER_ENERGY = "sevc:dynamicCostPerEnergy_kWh";

    private static final String DEFAULT_NON_EV_CAR_TYPE_ID = "carDefaultNonEv";
    private static final double DEFAULT_MAX_SNAP_METERS = 1500.0;

    private static final Map<String, Double> CONSUMPTION_KWH_PER_100KM = new LinkedHashMap<>();

    private BuildGothenburgEvContribInputs() {
    }

    public static void main(String[] args) throws Exception {
        Path configPath = Paths.get(args.length > 0 ? args[0] : IN_CONFIG);
        Path plansIn = Paths.get(args.length > 1 ? args[1] : IN_PLANS);
        Path networkIn = Paths.get(args.length > 2 ? args[2] : IN_NETWORK);
        Path legacyEvIn = Paths.get(args.length > 3 ? args[3] : IN_LEGACY_EV);
        Path publicChargersIn = Paths.get(args.length > 4 ? args[4] : IN_PUBLIC_CHARGERS);
        Path plansOut = Paths.get(args.length > 5 ? args[5] : OUT_PLANS);
        Path vehiclesOut = Paths.get(args.length > 6 ? args[6] : OUT_VEHICLES);
        Path facilitiesOut = Paths.get(args.length > 7 ? args[7] : OUT_FACILITIES);
        Path chargersAllOut = Paths.get(args.length > 8 ? args[8] : OUT_CHARGERS_ALL);
        Path chargersPricedOut = Paths.get(args.length > 9 ? args[9] : OUT_CHARGERS_PRICED);
        double maxSnapMeters = args.length > 10 && !args[10].isBlank()
                ? Double.parseDouble(args[10])
                : DEFAULT_MAX_SNAP_METERS;

        Config runConfig = ConfigUtils.loadConfig(
                configPath.toString(),
                new GothenburgBehaviorConfigGroup(),
                new GothenburgPricingConfigGroup()
        );
        GothenburgBehaviorConfigGroup behaviorCfg =
                ConfigUtils.addOrGetModule(runConfig, GothenburgBehaviorConfigGroup.class);
        GothenburgPricingConfigGroup pricingCfg =
                ConfigUtils.addOrGetModule(runConfig, GothenburgPricingConfigGroup.class);

        double maximumSoc = clamp01(behaviorCfg.getDefaultMaximumSoc());
        if (maximumSoc < behaviorCfg.getDefaultMinimumEndSoc()) {
            throw new IllegalStateException(
                    "defaultMaximumSoc must be >= defaultMinimumEndSoc; found "
                            + maximumSoc + " < " + behaviorCfg.getDefaultMinimumEndSoc()
            );
        }

        List<LegacyEv> legacyEvs = readLegacyEvVehicles(legacyEvIn);
        validateLegacyVehicleIds(legacyEvs);
        Set<String> legacyEvIds = legacyEvs.stream().map(v -> v.id).collect(Collectors.toSet());

        Scenario scenario = ScenarioUtils.createScenario(ConfigUtils.createConfig());
        new MatsimNetworkReader(scenario.getNetwork()).readFile(networkIn.toString());
        new PopulationReader(scenario).readFile(plansIn.toString());

        Network carNetwork = NetworkUtils.createNetwork();
        new TransportModeNetworkFilter(scenario.getNetwork()).filter(carNetwork, Set.of(TransportMode.car));

        int personsTotal = scenario.getPopulation().getPersons().size();
        int actsWithoutLinkBefore = countActivitiesWithoutLink(scenario);

        int evPersonsFound = 0;
        int wevcActivated = 0;
        int vehicleIdsInserted = 0;

        for (Person person : scenario.getPopulation().getPersons().values()) {
            if (!legacyEvIds.contains(person.getId().toString())) {
                continue;
            }

            evPersonsFound++;
            WithinDayEvUtils.activate(person);
            wevcActivated++;

            Id<Vehicle> vehicleId = Id.createVehicleId(person.getId());
            VehicleUtils.insertVehicleIdsIntoPersonAttributes(person, Map.of(TransportMode.car, vehicleId));
            vehicleIdsInserted++;
        }

        new XY2Links(carNetwork, scenario.getActivityFacilities()).run(scenario.getPopulation());
        sanitizeCarLegAdjacentActivityLinks(scenario, carNetwork);
        validateCarLegEndpointsOnCarLinks(scenario, carNetwork);
        int actsWithoutLinkAfter = countActivitiesWithoutLink(scenario);

        applySevcBehaviorAttributes(scenario, behaviorCfg, maximumSoc);

        repairOrRerouteBrokenCarLegs(scenario, carNetwork);
        ensureCarVehicleAssignmentsAndRouteVehicleIds(scenario);
        validateFiniteCarRouteTimesAndDistances(scenario);
        validateRunHasCarAndEvDemand(scenario);

        ActivityFacilities facilities = FacilitiesUtils.createActivityFacilities("synthetic-work-facilities");
        Map<String, WorkFacilityRecord> workFacilities = assignSyntheticWorkFacilities(scenario, carNetwork, facilities);

        writePopulationWithDoctype(scenario, plansOut);
        new FacilitiesWriter(facilities).write(facilitiesOut.toString());

        Set<String> activeEvIdsInScenario = scenario.getPopulation().getPersons().values().stream()
                .filter(WithinDayEvUtils::isActive)
                .map(p -> p.getId().toString())
                .collect(Collectors.toCollection(LinkedHashSet::new));

        Vehicles vehicles = buildVehicles(legacyEvs, activeEvIdsInScenario, maximumSoc);
        validateGeneratedVehiclesAgainstPlans(scenario, vehicles);
        new MatsimVehicleWriter(vehicles).writeFile(vehiclesOut.toString());

        writeChargers(
                publicChargersIn,
                scenario,
                carNetwork,
                workFacilities,
                chargersAllOut,
                maxSnapMeters
        );
        applyPricingToChargers(chargersAllOut, chargersPricedOut, pricingCfg);

        int evActive = 0;
        int homeEligible = 0;
        int workEligible = 0;

        for (Person person : scenario.getPopulation().getPersons().values()) {
            if (WithinDayEvUtils.isActive(person)) {
                evActive++;
                if (stringAttr(person, ATTR_HOME_POWER) != null) {
                    homeEligible++;
                }
                if (stringAttr(person, ATTR_WORK_POWER) != null) {
                    workEligible++;
                }
            }
        }

        System.out.println("Population persons total: " + personsTotal);
        System.out.println("Legacy EV entries read: " + legacyEvs.size());
        System.out.println("EV persons found in population: " + evPersonsFound);
        System.out.println("WEVC activated: " + wevcActivated);
        System.out.println("VehicleIds inserted (car): " + vehicleIdsInserted);
        System.out.println("Activities missing linkId: before=" + actsWithoutLinkBefore + " after=" + actsWithoutLinkAfter);
        System.out.println("Runnable WEVC-active persons: " + evActive);
        System.out.println("Runnable persons with home charging attribute: " + homeEligible);
        System.out.println("Runnable persons with work charging attribute: " + workEligible);
        System.out.println("Synthetic work facilities created: " + workFacilities.size());
        System.out.println("Output plans written: " + plansOut);
        System.out.println("Output vehicles written: " + vehiclesOut);
        System.out.println("Output facilities written: " + facilitiesOut);
        System.out.println("Output chargers written: " + chargersAllOut);
        System.out.println("Output priced chargers written: " + chargersPricedOut);
    }

    private static void sanitizeCarLegAdjacentActivityLinks(Scenario scenario, Network carNetwork) {
        int reassignedActs = 0;

        for (Person person : scenario.getPopulation().getPersons().values()) {
            for (Plan plan : person.getPlans()) {
                List<PlanElement> pes = plan.getPlanElements();

                for (int i = 0; i < pes.size(); i++) {
                    if (!(pes.get(i) instanceof Activity act)) {
                        continue;
                    }

                    boolean adjacentToCarLeg =
                            (i > 0 && pes.get(i - 1) instanceof Leg prev && TransportMode.car.equals(prev.getMode())) ||
                                    (i < pes.size() - 1 && pes.get(i + 1) instanceof Leg next && TransportMode.car.equals(next.getMode()));

                    if (!adjacentToCarLeg) {
                        continue;
                    }

                    boolean needsRepair = act.getLinkId() == null || !carNetwork.getLinks().containsKey(act.getLinkId());
                    if (!needsRepair) {
                        continue;
                    }

                    Coord coord = act.getCoord();
                    if (coord == null) {
                        throw new IllegalStateException(
                                "Activity adjacent to car leg has no usable coord and non-car link: person=" +
                                        person.getId() + ", actType=" + act.getType()
                        );
                    }

                    Link nearestCarLink = NetworkUtils.getNearestLink(carNetwork, coord);
                    if (nearestCarLink == null) {
                        throw new IllegalStateException(
                                "No nearest car link found for activity adjacent to car leg: person=" +
                                        person.getId() + ", actType=" + act.getType()
                        );
                    }

                    act.setLinkId(nearestCarLink.getId());
                    reassignedActs++;
                }
            }
        }

        System.out.println("Activities adjacent to car legs reassigned to car links: " + reassignedActs);
    }

    private static void validateCarLegEndpointsOnCarLinks(Scenario scenario, Network carNetwork) {
        int invalidEndpoints = 0;

        for (Person person : scenario.getPopulation().getPersons().values()) {
            for (Plan plan : person.getPlans()) {
                List<PlanElement> pes = plan.getPlanElements();

                for (int i = 0; i < pes.size(); i++) {
                    if (!(pes.get(i) instanceof Leg leg) || !TransportMode.car.equals(leg.getMode())) {
                        continue;
                    }

                    if (i == 0 || i == pes.size() - 1) {
                        throw new IllegalStateException("Car leg at invalid plan boundary for person " + person.getId());
                    }

                    Activity fromAct = (Activity) pes.get(i - 1);
                    Activity toAct = (Activity) pes.get(i + 1);

                    if (fromAct.getLinkId() == null || !carNetwork.getLinks().containsKey(fromAct.getLinkId())) {
                        invalidEndpoints++;
                        throw new IllegalStateException(
                                "Car leg origin activity not on car network: person=" + person.getId() +
                                        ", link=" + fromAct.getLinkId()
                        );
                    }

                    if (toAct.getLinkId() == null || !carNetwork.getLinks().containsKey(toAct.getLinkId())) {
                        invalidEndpoints++;
                        throw new IllegalStateException(
                                "Car leg destination activity not on car network: person=" + person.getId() +
                                        ", link=" + toAct.getLinkId()
                        );
                    }
                }
            }
        }

        System.out.println("Invalid car-leg endpoints found: " + invalidEndpoints);
    }

    private static void applySevcBehaviorAttributes(
            Scenario scenario,
            GothenburgBehaviorConfigGroup behaviorCfg,
            double maximumSoc
    ) {
        int updated = 0;

        for (Person person : scenario.getPopulation().getPersons().values()) {
            if (!WithinDayEvUtils.isActive(person)) {
                continue;
            }

            double minimumSoc = readDouble(person, ATTR_MIN_SOC, behaviorCfg.getDefaultMinimumSoc());
            double minimumEndSoc = readDouble(person, ATTR_MIN_END_SOC, behaviorCfg.getDefaultMinimumEndSoc());
            double targetSoc = readDouble(person, ATTR_TARGET_SOC, behaviorCfg.getDefaultTargetSoc());

            minimumSoc = clamp01(minimumSoc);
            minimumEndSoc = Math.max(minimumSoc, clamp01(minimumEndSoc));
            targetSoc = Math.max(minimumEndSoc, Math.min(maximumSoc, clamp01(targetSoc)));

            StrategicChargingUtils.setMinimumSoc(person, minimumSoc);
            StrategicChargingUtils.setMinimumEndSoc(person, minimumEndSoc);
            StrategicChargingUtils.setTargetSoc(person, targetSoc);

            updated++;
        }

        System.out.println("Persons updated with SEVC behavior attributes: " + updated);
    }

    private static Vehicles buildVehicles(
            List<LegacyEv> legacy,
            Set<String> activeEvIdsInScenario,
            double maximumSoc
    ) {
        Vehicles vehicles = VehicleUtils.createVehiclesContainer();

        Map<String, Double> capacityPerType = new LinkedHashMap<>();
        for (LegacyEv v : legacy) {
            if (!activeEvIdsInScenario.contains(v.id)) {
                continue;
            }
            Double prev = capacityPerType.putIfAbsent(v.vehicleType, v.batteryCapacityKWh);
            if (prev != null && Math.abs(prev - v.batteryCapacityKWh) > 1e-6) {
                throw new IllegalStateException(
                        "Vehicle type '" + v.vehicleType + "' has inconsistent battery capacities: "
                                + prev + " vs " + v.batteryCapacityKWh
                );
            }
        }

        Map<String, VehicleType> types = new LinkedHashMap<>();
        int typesCreated = 0;
        int vehiclesCreated = 0;
        int initialSocClamped = 0;

        for (Map.Entry<String, Double> e : capacityPerType.entrySet()) {
            String vehicleTypeId = e.getKey();
            double batteryCapacityKWh = e.getValue();

            VehicleType type = vehicles.getFactory().createVehicleType(Id.create(vehicleTypeId, VehicleType.class));
            type.setNetworkMode(TransportMode.car);
            type.setMaximumVelocity(33.33);
            type.setLength(4.5);
            type.setWidth(1.8);

            VehicleUtils.setHbefaTechnology(type.getEngineInformation(), "electricity");
            VehicleUtils.setEnergyCapacity(type.getEngineInformation(), batteryCapacityKWh);

            LegacyEv representative = legacy.stream()
                    .filter(v -> activeEvIdsInScenario.contains(v.id) && v.vehicleType.equals(vehicleTypeId))
                    .findFirst()
                    .orElseThrow();

            type.getEngineInformation().getAttributes().putAttribute(ATTR_CHARGER_TYPES, representative.chargerTypes);

            Double kWhPer100Km = CONSUMPTION_KWH_PER_100KM.get(vehicleTypeId);
            if (kWhPer100Km != null) {
                type.getAttributes().putAttribute(ATTR_DRIVE_CONS_WH_KM, kWhPer100Km * 10.0);
            }

            vehicles.addVehicleType(type);
            types.put(vehicleTypeId, type);
            typesCreated++;
        }

        for (LegacyEv v : legacy) {
            if (!activeEvIdsInScenario.contains(v.id)) {
                continue;
            }

            VehicleType type = types.get(v.vehicleType);
            if (type == null) {
                throw new IllegalStateException("Missing vehicle type for " + v.vehicleType);
            }

            Vehicle vehicle = vehicles.getFactory().createVehicle(Id.create(v.id, Vehicle.class), type);

            double initialSoc = resolveInitialSocFraction(v.initialSocOrEnergy, v.batteryCapacityKWh);
            if (Double.isNaN(initialSoc) || Double.isInfinite(initialSoc)) {
                initialSoc = 1.0;
                initialSocClamped++;
            } else if (initialSoc < 0.0 || initialSoc > 1.0) {
                initialSoc = clamp01(initialSoc);
                initialSocClamped++;
            }

            vehicle.getAttributes().putAttribute(ATTR_INITIAL_SOC, initialSoc);
            vehicle.getAttributes().putAttribute(ATTR_WEVC_MAX_SOC, maximumSoc);
            StrategicChargingUtils.setMaximumSoc(vehicle, maximumSoc);

            vehicles.addVehicle(vehicle);
            vehiclesCreated++;
        }

        System.out.println("Vehicle types created: " + typesCreated);
        System.out.println("Vehicles created: " + vehiclesCreated);
        System.out.println("InitialSoc clamped: " + initialSocClamped);

        return vehicles;
    }

    private static void validateGeneratedVehiclesAgainstPlans(Scenario scenario, Vehicles vehicles) {
        Set<Id<Vehicle>> seenMappedVehicleIds = new HashSet<>();
        int evPersons = 0;
        int validated = 0;

        for (Person person : scenario.getPopulation().getPersons().values()) {
            if (!WithinDayEvUtils.isActive(person)) {
                continue;
            }

            evPersons++;

            if (!VehicleUtils.hasVehicleId(person, TransportMode.car)) {
                throw new IllegalStateException("WEVC-active person has no mapped car vehicle id: " + person.getId());
            }

            Id<Vehicle> vehicleId = VehicleUtils.getVehicleId(person, TransportMode.car);
            if (!seenMappedVehicleIds.add(vehicleId)) {
                throw new IllegalStateException("Duplicate mapped EV vehicle id across persons: " + vehicleId);
            }

            Vehicle vehicle = vehicles.getVehicles().get(vehicleId);
            if (vehicle == null) {
                throw new IllegalStateException("Mapped EV vehicle id not found in vehicles file: " + vehicleId);
            }

            Object maximumSoc = vehicle.getAttributes().getAttribute(ATTR_WEVC_MAX_SOC);
            if (maximumSoc == null) {
                throw new IllegalStateException("Vehicle " + vehicleId + " has no " + ATTR_WEVC_MAX_SOC + " attribute");
            }

            validated++;
        }

        System.out.println("Plans cross-check: WEVC-active persons = " + evPersons);
        System.out.println("Plans cross-check: validated mapped EV vehicles = " + validated);
    }

    private static void repairOrRerouteBrokenCarLegs(Scenario scenario, Network carNetwork) {
        List<Id<Person>> toRemove = new ArrayList<>();
        int rebuiltRoutes = 0;
        int rejectedPersons = 0;
        int keptExistingRoutes = 0;

        RouteFactories routeFactories = scenario.getPopulation().getFactory().getRouteFactories();
        FreeSpeedTravelTime travelTime = new FreeSpeedTravelTime();
        OnlyTimeDependentTravelDisutility travelDisutility = new OnlyTimeDependentTravelDisutility(travelTime);
        LeastCostPathCalculator router = new DijkstraFactory().createPathCalculator(carNetwork, travelDisutility, travelTime);

        for (Person person : scenario.getPopulation().getPersons().values()) {
            boolean reject = false;

            for (Plan plan : person.getPlans()) {
                List<PlanElement> planElements = plan.getPlanElements();

                for (int i = 0; i < planElements.size(); i++) {
                    if (!(planElements.get(i) instanceof Leg leg)) {
                        continue;
                    }
                    if (!TransportMode.car.equals(leg.getMode())) {
                        continue;
                    }

                    if (i == 0 || i == planElements.size() - 1) {
                        reject = true;
                        break;
                    }
                    if (!(planElements.get(i - 1) instanceof Activity fromAct) ||
                            !(planElements.get(i + 1) instanceof Activity toAct)) {
                        reject = true;
                        break;
                    }
                    if (fromAct.getLinkId() == null || toAct.getLinkId() == null) {
                        reject = true;
                        break;
                    }

                    Link fromLink = carNetwork.getLinks().get(fromAct.getLinkId());
                    Link toLink = carNetwork.getLinks().get(toAct.getLinkId());

                    if (fromLink == null || toLink == null) {
                        reject = true;
                        break;
                    }

                    boolean needsReroute = false;

                    if (leg.getRoute() == null) {
                        needsReroute = true;
                    } else if (!(leg.getRoute() instanceof NetworkRoute nr)) {
                        reject = true;
                        break;
                    } else {
                        if (leg.getTravelTime().isUndefined() || nr.getTravelTime().isUndefined() || !Double.isFinite(nr.getDistance())) {
                            needsReroute = true;
                        }
                    }

                    if (!needsReroute) {
                        keptExistingRoutes++;
                        continue;
                    }

                    NetworkRoute nr = (NetworkRoute) routeFactories.createRoute(NetworkRoute.class, fromLink.getId(), toLink.getId());

                    double routeDistance;
                    double routeTravelTime;

                    if (fromLink.getId().equals(toLink.getId())) {
                        nr.setLinkIds(fromLink.getId(), List.of(), toLink.getId());
                        routeDistance = fromLink.getLength();
                        routeTravelTime = routeDistance / Math.max(1.0, fromLink.getFreespeed());
                    } else {
                        LeastCostPathCalculator.Path path = router.calcLeastCostPath(
                                fromLink.getToNode(),
                                toLink.getFromNode(),
                                0.0,
                                null,
                                null
                        );

                        if (path == null) {
                            reject = true;
                            break;
                        }

                        List<Id<Link>> middleLinkIds = new ArrayList<>(path.links.size());
                        double middleDistance = 0.0;
                        for (Link l : path.links) {
                            middleLinkIds.add(l.getId());
                            middleDistance += l.getLength();
                        }

                        nr.setLinkIds(fromLink.getId(), middleLinkIds, toLink.getId());

                        routeDistance = fromLink.getLength() + middleDistance + toLink.getLength();
                        routeTravelTime =
                                fromLink.getLength() / Math.max(1.0, fromLink.getFreespeed())
                                        + path.travelTime
                                        + toLink.getLength() / Math.max(1.0, toLink.getFreespeed());
                    }

                    nr.setDistance(routeDistance);
                    nr.setTravelTime(routeTravelTime);
                    leg.setRoute(nr);
                    leg.setTravelTime(routeTravelTime);
                    rebuiltRoutes++;
                }

                if (reject) {
                    break;
                }
            }

            if (reject) {
                toRemove.add(person.getId());
                rejectedPersons++;
            }
        }

        for (Id<Person> personId : toRemove) {
            scenario.getPopulation().getPersons().remove(personId);
        }

        System.out.println("Existing valid car routes kept: " + keptExistingRoutes);
        System.out.println("Car routes rebuilt (only missing/invalid): " + rebuiltRoutes);
        System.out.println("Rejected persons after rerouting attempt: " + rejectedPersons);
    }

    private static void ensureCarVehicleAssignmentsAndRouteVehicleIds(Scenario scenario) {
        int carUsers = 0;
        int mappingsAdded = 0;
        int routeVehicleIdsAdded = 0;
        int carLegsChecked = 0;

        for (Person person : scenario.getPopulation().getPersons().values()) {
            boolean usesCar = person.getPlans().stream().anyMatch(p -> usesMode(p, TransportMode.car));
            if (!usesCar) {
                continue;
            }

            carUsers++;

            Id<Vehicle> vehicleId;
            if (!VehicleUtils.hasVehicleId(person, TransportMode.car)) {
                vehicleId = Id.createVehicleId(person.getId());
                VehicleUtils.insertVehicleIdsIntoPersonAttributes(person, Map.of(TransportMode.car, vehicleId));
                mappingsAdded++;
            } else {
                vehicleId = VehicleUtils.getVehicleId(person, TransportMode.car);
            }

            for (Plan plan : person.getPlans()) {
                for (PlanElement pe : plan.getPlanElements()) {
                    if (!(pe instanceof Leg leg)) {
                        continue;
                    }
                    if (!TransportMode.car.equals(leg.getMode())) {
                        continue;
                    }

                    carLegsChecked++;
                    if (!(leg.getRoute() instanceof NetworkRoute networkRoute)) {
                        throw new IllegalStateException("Car leg has no NetworkRoute for person " + person.getId());
                    }

                    if (networkRoute.getVehicleId() == null) {
                        networkRoute.setVehicleId(vehicleId);
                        routeVehicleIdsAdded++;
                    }
                }
            }
        }

        System.out.println("Car users with mappings checked: " + carUsers);
        System.out.println("Person car mappings added: " + mappingsAdded);
        System.out.println("Car legs checked: " + carLegsChecked);
        System.out.println("Missing route vehicleIds filled: " + routeVehicleIdsAdded);
    }

    private static void validateFiniteCarRouteTimesAndDistances(Scenario scenario) {
        int undefinedLegTimes = 0;
        int undefinedRouteTimes = 0;
        int nonFiniteRouteDistances = 0;

        for (Person person : scenario.getPopulation().getPersons().values()) {
            for (Plan plan : person.getPlans()) {
                for (PlanElement pe : plan.getPlanElements()) {
                    if (!(pe instanceof Leg leg)) {
                        continue;
                    }
                    if (!TransportMode.car.equals(leg.getMode())) {
                        continue;
                    }
                    if (!(leg.getRoute() instanceof NetworkRoute nr)) {
                        continue;
                    }

                    if (leg.getTravelTime().isUndefined()) {
                        undefinedLegTimes++;
                    }
                    if (nr.getTravelTime().isUndefined()) {
                        undefinedRouteTimes++;
                    }
                    if (!Double.isFinite(nr.getDistance())) {
                        nonFiniteRouteDistances++;
                    }
                }
            }
        }

        System.out.println("Undefined car leg travel times: " + undefinedLegTimes);
        System.out.println("Undefined car route travel times: " + undefinedRouteTimes);
        System.out.println("Non-finite car route distances: " + nonFiniteRouteDistances);

        if (undefinedLegTimes > 0 || undefinedRouteTimes > 0 || nonFiniteRouteDistances > 0) {
            throw new IllegalStateException("Car routes still contain undefined time or invalid distance.");
        }
    }

    private static void validateRunHasCarAndEvDemand(Scenario scenario) {
        int carLegs = 0;
        int evPersons = 0;

        for (Person person : scenario.getPopulation().getPersons().values()) {
            if (WithinDayEvUtils.isActive(person)) {
                evPersons++;
            }
            for (Plan plan : person.getPlans()) {
                for (PlanElement pe : plan.getPlanElements()) {
                    if (pe instanceof Leg leg && TransportMode.car.equals(leg.getMode())) {
                        carLegs++;
                    }
                }
            }
        }

        System.out.println("Total car legs = " + carLegs);
        System.out.println("Total WEVC-active persons = " + evPersons);

        if (carLegs == 0 || evPersons == 0) {
            throw new IllegalStateException("Run has no car demand or no WEVC-active EV persons.");
        }
    }

    private static Map<String, WorkFacilityRecord> assignSyntheticWorkFacilities(
            Scenario scenario,
            Network carNetwork,
            ActivityFacilities facilities
    ) {
        Map<String, WorkFacilityRecord> records = new LinkedHashMap<>();
        int taggedWorkActivities = 0;

        for (Person person : scenario.getPopulation().getPersons().values()) {
            if (!WithinDayEvUtils.isActive(person)) {
                continue;
            }

            Plan plan = selectedOrFirst(person);
            if (plan == null) {
                continue;
            }

            String workPower = stringAttr(person, ATTR_WORK_POWER);
            if (workPower == null || workPower.isBlank()) {
                continue;
            }

            for (PlanElement pe : plan.getPlanElements()) {
                if (!(pe instanceof Activity act) || !"work".equals(act.getType())) {
                    continue;
                }

                Id<Link> linkId = act.getLinkId();
                Coord coord = act.getCoord();

                if (linkId == null && coord != null) {
                    Link nearest = NetworkUtils.getNearestLink(carNetwork, coord);
                    if (nearest != null) {
                        linkId = nearest.getId();
                        act.setLinkId(linkId);
                    }
                }

                if (coord == null && linkId != null) {
                    Link link = carNetwork.getLinks().get(linkId);
                    if (link != null) {
                        coord = link.getCoord();
                        act.setCoord(coord);
                    }
                }

                if (linkId == null || coord == null) {
                    continue;
                }

                String facilityKey = "person:" + person.getId();
                String facilityIdString = "workFac_person_" + person.getId();

                WorkFacilityRecord record = records.get(facilityKey);
                if (record == null) {
                    Id<ActivityFacility> facilityId = Id.create(facilityIdString, ActivityFacility.class);
                    ActivityFacility facility = facilities.getFactory().createActivityFacility(facilityId, coord, linkId);
                    facilities.addActivityFacility(facility);

                    facility.getAttributes().putAttribute("synthetic", true);
                    facility.getAttributes().putAttribute("kind", "work");
                    facility.getAttributes().putAttribute("linkId", linkId.toString());

                    var workOption = facilities.getFactory().createActivityOption("work");
                    facility.addActivityOption(workOption);

                    record = new WorkFacilityRecord(facilityId, linkId, coord, parsePower(workPower));
                    records.put(facilityKey, record);
                }

                record.personIds.add(person.getId().toString());
                record.plugCount = 1;
                record.powerKw = Math.max(record.powerKw, parsePower(workPower));

                act.setFacilityId(record.facilityId);
                taggedWorkActivities++;
            }
        }

        System.out.println("Work activities tagged with synthetic facilities: " + taggedWorkActivities);
        return records;
    }

    private static void writeChargers(
            Path chargersIn,
            Scenario scenario,
            Network carNetwork,
            Map<String, WorkFacilityRecord> workFacilities,
            Path chargersOut,
            double maxSnapMeters
    ) throws Exception {
        Document chargersDoc = parseXmlNoExternalDtd(chargersIn);
        NodeList chargerNodes = chargersDoc.getElementsByTagName("charger");

        int publicTotal = chargerNodes.getLength();
        int publicWritten = 0;
        int publicSkippedTooFar = 0;
        int publicSkippedNoPower = 0;
        int homeWritten = 0;
        int workWritten = 0;

        try (BufferedWriter w = Files.newBufferedWriter(chargersOut, StandardCharsets.UTF_8)) {
            w.write("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n");
            w.write("<!DOCTYPE chargers SYSTEM \"" + OUT_CHARGERS_DTD + "\">\n");
            w.write("<chargers>\n");

            List<SnappedPublicCharger> snappedPublic = new ArrayList<>();
            Set<String> seenPublicIds = new HashSet<>();
            Map<Id<Link>, Integer> publicObjectsPerLink = new LinkedHashMap<>();
            Map<Id<Link>, Integer> publicPlugsPerLink = new LinkedHashMap<>();
            List<Double> snapDistances = new ArrayList<>();

            for (int i = 0; i < publicTotal; i++) {
                Element c = (Element) chargerNodes.item(i);

                String id = c.getAttribute("id").trim();
                String xStr = c.getAttribute("x").trim();
                String yStr = c.getAttribute("y").trim();
                String plugPower = c.getAttribute("plug_power").trim();
                String plugCount = c.getAttribute("plug_count").trim();

                if (id.isEmpty() || xStr.isEmpty() || yStr.isEmpty()) {
                    continue;
                }
                if (!seenPublicIds.add(id)) {
                    throw new IllegalStateException("Duplicate public charger id in source file: " + id);
                }
                if (plugPower.isEmpty()) {
                    publicSkippedNoPower++;
                    continue;
                }

                int plugs = plugCount.isBlank() ? 1 : Integer.parseInt(plugCount);
                Coord coord = new Coord(Double.parseDouble(xStr), Double.parseDouble(yStr));

                Link nearest = NetworkUtils.getNearestLinkExactly(carNetwork, coord);
                if (nearest == null) {
                    continue;
                }

                double d = CoordUtils.distancePointLinesegment(
                        nearest.getFromNode().getCoord(),
                        nearest.getToNode().getCoord(),
                        coord
                );

                if (d > maxSnapMeters) {
                    publicSkippedTooFar++;
                    continue;
                }

                snappedPublic.add(new SnappedPublicCharger(id, nearest.getId(), plugPower, plugs, d));
                publicObjectsPerLink.merge(nearest.getId(), 1, Integer::sum);
                publicPlugsPerLink.merge(nearest.getId(), plugs, Integer::sum);
                snapDistances.add(d);
            }

            int linksWithMultiplePublicChargers = 0;
            int maxObjectsOnOneLink = 0;
            int maxPlugsOnOneLink = 0;

            for (var e : publicObjectsPerLink.entrySet()) {
                int objects = e.getValue();
                int plugs = publicPlugsPerLink.getOrDefault(e.getKey(), 0);

                if (objects > 1) {
                    linksWithMultiplePublicChargers++;
                }
                maxObjectsOnOneLink = Math.max(maxObjectsOnOneLink, objects);
                maxPlugsOnOneLink = Math.max(maxPlugsOnOneLink, plugs);
            }

            Collections.sort(snapDistances);
            double meanSnap = snapDistances.stream().mapToDouble(Double::doubleValue).average().orElse(0.0);
            double p95Snap = snapDistances.isEmpty() ? 0.0 : snapDistances.get((int) Math.floor(0.95 * (snapDistances.size() - 1)));
            double maxSnap = snapDistances.isEmpty() ? 0.0 : snapDistances.get(snapDistances.size() - 1);

            System.out.println("Public unique snapped links: " + publicObjectsPerLink.size());
            System.out.println("Public links with >1 charger object: " + linksWithMultiplePublicChargers);
            System.out.println("Max public charger objects on one link: " + maxObjectsOnOneLink);
            System.out.println("Max public plugs on one link: " + maxPlugsOnOneLink);
            System.out.printf(Locale.ROOT, "Public snap distance (m): mean=%.2f p95=%.2f max=%.2f%n", meanSnap, p95Snap, maxSnap);

            for (Person person : scenario.getPopulation().getPersons().values()) {
                if (!WithinDayEvUtils.isActive(person)) {
                    continue;
                }

                Plan plan = selectedOrFirst(person);
                if (plan == null) {
                    continue;
                }

                String homePower = stringAttr(person, ATTR_HOME_POWER);
                if (homePower == null || homePower.isBlank()) {
                    continue;
                }

                Activity homeAct = firstActivityOfType(plan, "home");
                if (homeAct == null) {
                    continue;
                }

                Id<Link> linkId = resolveLinkId(homeAct, carNetwork);
                if (linkId == null) {
                    continue;
                }

                w.write("  <charger id=\"home_" + escapeXml(person.getId().toString()) + "\" link=\"" + escapeXml(linkId.toString())
                        + "\" plug_power=\"" + normalizePlugPower(homePower) + "\" plug_count=\"1\" type=\"default\">\n");
                w.write("    <attributes>\n");
                w.write("      <attribute name=\"sevc:persons\" class=\"java.lang.String\">" + escapeXml(person.getId().toString()) + "</attribute>\n");
                w.write("      <attribute name=\"sevc:analysisTypes\" class=\"java.lang.String\">home</attribute>\n");
                w.write("    </attributes>\n");
                w.write("  </charger>\n");
                homeWritten++;
            }

            for (WorkFacilityRecord record : workFacilities.values()) {
                String chargerId = "work_" + record.facilityId;
                w.write("  <charger id=\"" + escapeXml(chargerId) + "\" link=\"" + escapeXml(record.linkId.toString())
                        + "\" plug_power=\"" + normalizePlugPower(Double.toString(record.powerKw)) + "\" plug_count=\""
                        + record.plugCount + "\" type=\"default\">\n");
                w.write("    <attributes>\n");
                w.write("      <attribute name=\"sevc:facilities\" class=\"java.lang.String\">" + escapeXml(record.facilityId.toString()) + "</attribute>\n");
                w.write("      <attribute name=\"sevc:analysisTypes\" class=\"java.lang.String\">work</attribute>\n");
                w.write("    </attributes>\n");
                w.write("  </charger>\n");
                workWritten++;
            }

            for (SnappedPublicCharger pc : snappedPublic) {
                publicWritten++;
                w.write("  <charger id=\"" + escapeXml(pc.id) + "\" link=\"" + escapeXml(pc.linkId.toString())
                        + "\" plug_power=\"" + normalizePlugPower(pc.plugPower) + "\" plug_count=\"" + pc.plugCount + "\" type=\"default\">\n");
                w.write("    <attributes>\n");
                w.write("      <attribute name=\"sevc:public\" class=\"java.lang.Boolean\">true</attribute>\n");
                w.write("      <attribute name=\"sevc:analysisTypes\" class=\"java.lang.String\">public</attribute>\n");
                w.write("      <attribute name=\"sourceSnapDistanceM\" class=\"java.lang.Double\">" + pc.snapDistanceM + "</attribute>\n");
                w.write("    </attributes>\n");
                w.write("  </charger>\n");
            }

            w.write("</chargers>\n");
        }

        System.out.println("Public chargers read: " + publicTotal);
        System.out.println("Public chargers written: " + publicWritten);
        System.out.println("Public chargers skipped (no power): " + publicSkippedNoPower);
        System.out.println("Public chargers skipped (too far): " + publicSkippedTooFar);
        System.out.println("Home chargers written: " + homeWritten);
        System.out.println("Work chargers written: " + workWritten);
    }

    private static void applyPricingToChargers(
            Path chargersIn,
            Path chargersOut,
            GothenburgPricingConfigGroup pricing
    ) throws Exception {
        Document doc = parseXmlNoExternalDtd(chargersIn);
        NodeList chargers = doc.getElementsByTagName("charger");

        int homeCount = 0;
        int workCount = 0;
        int publicCount = 0;
        int otherCount = 0;

        for (int i = 0; i < chargers.getLength(); i++) {
            Element charger = (Element) chargers.item(i);
            String chargerId = charger.getAttribute("id").trim();
            String type = inferChargerType(chargerId, charger);

            Element attrs = getOrCreateAttributes(doc, charger);
            removeCostAttributes(attrs);

            switch (type) {
                case "home" -> {
                    if (pricing.isEnableHomeTou()) {
                        addOrReplaceAttribute(doc, attrs, ATTR_COST_PER_ENERGY, "java.lang.Double", "0.0");
                        addOrReplaceAttribute(
                                doc,
                                attrs,
                                ATTR_DYNAMIC_COST_PER_ENERGY,
                                "java.lang.String",
                                buildDynamicHomeCostString(
                                        pricing.getHomeChargingCost(),
                                        pricing.getHomeTouMultipliers()
                                )
                        );
                    } else {
                        addOrReplaceAttribute(
                                doc,
                                attrs,
                                ATTR_COST_PER_ENERGY,
                                "java.lang.Double",
                                doubleString(pricing.getHomeChargingCost())
                        );
                    }
                    homeCount++;
                }
                case "work" -> {
                    addOrReplaceAttribute(
                            doc,
                            attrs,
                            ATTR_COST_PER_ENERGY,
                            "java.lang.Double",
                            doubleString(pricing.getWorkChargingCost())
                    );
                    workCount++;
                }
                case "public" -> {
                    addOrReplaceAttribute(
                            doc,
                            attrs,
                            ATTR_COST_PER_ENERGY,
                            "java.lang.Double",
                            doubleString(pricing.getPublicChargingCost())
                    );
                    addOrReplaceAttribute(
                            doc,
                            attrs,
                            ATTR_BLOCKING_DURATION,
                            "java.lang.Double",
                            "20.0"
                    );
                    addOrReplaceAttribute(
                            doc,
                            attrs,
                            ATTR_COST_PER_BLOCKING_DURATION,
                            "java.lang.Double",
                            "0.25"
                    );
                    publicCount++;
                }
                default -> otherCount++;
            }
        }

        writeXml(doc, chargersOut);

        ValidationSummary summary = validatePricedChargers(chargersOut, pricing.isEnableHomeTou());

        System.out.println("Home chargers priced   : " + homeCount);
        System.out.println("Work chargers priced   : " + workCount);
        System.out.println("Public chargers priced : " + publicCount);
        System.out.println("Other chargers kept    : " + otherCount);

        System.out.println("Home chargers found                 : " + summary.homeChargers);
        System.out.println("Home chargers with dynamic tariff   : " + summary.homeChargersWithDynamicTariff);
        System.out.println("Home chargers with static-only cost : " + summary.homeChargersWithStaticOnly);
        System.out.println("Work chargers with static cost      : " + summary.workChargersWithStaticCost);
        System.out.println("Public chargers with static cost    : " + summary.publicChargersWithStaticCost);
    }

    private static ValidationSummary validatePricedChargers(Path chargersOut, boolean expectHomeTou) throws Exception {
        Document doc = parseXmlNoExternalDtd(chargersOut);
        NodeList chargers = doc.getElementsByTagName("charger");

        int homeChargers = 0;
        int homeChargersWithDynamicTariff = 0;
        int homeChargersWithStaticOnly = 0;
        int workChargersWithStaticCost = 0;
        int publicChargersWithStaticCost = 0;

        for (int i = 0; i < chargers.getLength(); i++) {
            Element charger = (Element) chargers.item(i);
            String type = inferChargerType(charger.getAttribute("id").trim(), charger);
            Element attrs = getOrCreateAttributes(doc, charger);

            boolean hasStaticEnergy = findAttribute(attrs, ATTR_COST_PER_ENERGY) != null;
            boolean hasDynamicEnergy = findAttribute(attrs, ATTR_DYNAMIC_COST_PER_ENERGY) != null;

            if ("home".equals(type)) {
                homeChargers++;
                if (hasDynamicEnergy) {
                    homeChargersWithDynamicTariff++;
                }
                if (hasStaticEnergy && !hasDynamicEnergy) {
                    homeChargersWithStaticOnly++;
                }
            } else if ("work".equals(type)) {
                if (hasStaticEnergy) {
                    workChargersWithStaticCost++;
                }
            } else if ("public".equals(type)) {
                if (hasStaticEnergy) {
                    publicChargersWithStaticCost++;
                }
            }
        }

        if (expectHomeTou && homeChargers > 0 && homeChargersWithDynamicTariff == 0) {
            throw new IllegalStateException("Home ToU is enabled, but no home charger has " + ATTR_DYNAMIC_COST_PER_ENERGY);
        }

        return new ValidationSummary(
                homeChargers,
                homeChargersWithDynamicTariff,
                homeChargersWithStaticOnly,
                workChargersWithStaticCost,
                publicChargersWithStaticCost
        );
    }

    private static String buildDynamicHomeCostString(double baseCost, String multiplierSpec) {
        String[] tokens = multiplierSpec.split(";");
        if (tokens.length == 0) {
            throw new IllegalArgumentException("Empty ToU multiplier spec");
        }

        double initialMultiplier = parsePositiveDouble(tokens[0].trim(), "initial multiplier");
        StringBuilder sb = new StringBuilder();
        sb.append(doubleString(baseCost * initialMultiplier));

        for (int i = 1; i < tokens.length; i++) {
            String token = tokens[i].trim();
            String[] parts = token.split("=");
            if (parts.length != 2) {
                throw new IllegalArgumentException("Invalid ToU breakpoint: " + token);
            }

            String time = parts[0].trim();
            String multiplierString = parts[1].trim();

            validateTimeString(time);
            double multiplier = parsePositiveDouble(multiplierString, "multiplier at " + time);

            sb.append(";").append(time).append("=").append(doubleString(baseCost * multiplier));
        }

        return sb.toString();
    }

    private static String inferChargerType(String chargerId, Element charger) {
        String id = chargerId.toLowerCase(Locale.ROOT);

        if (id.startsWith("home_")) {
            return "home";
        }
        if (id.startsWith("work_")) {
            return "work";
        }
        if (id.startsWith("public_") || id.startsWith("publicagg_")) {
            return "public";
        }

        NodeList attrNodes = charger.getElementsByTagName("attribute");
        for (int i = 0; i < attrNodes.getLength(); i++) {
            Element a = (Element) attrNodes.item(i);
            if ("sevc:analysisTypes".equals(a.getAttribute("name"))) {
                String v = a.getTextContent().trim().toLowerCase(Locale.ROOT);
                if (v.contains("home")) {
                    return "home";
                }
                if (v.contains("work")) {
                    return "work";
                }
                if (v.contains("public")) {
                    return "public";
                }
            }
        }

        return "other";
    }

    private static Element getOrCreateAttributes(Document doc, Element charger) {
        NodeList list = charger.getElementsByTagName("attributes");
        if (list.getLength() > 0) {
            return (Element) list.item(0);
        }
        Element attrs = doc.createElement("attributes");
        charger.appendChild(attrs);
        return attrs;
    }

    private static void removeCostAttributes(Element attrs) {
        String[] names = {
                ATTR_COST_PER_USE,
                ATTR_COST_PER_ENERGY,
                ATTR_COST_PER_DURATION,
                ATTR_COST_PER_BLOCKING_DURATION,
                ATTR_BLOCKING_DURATION,
                ATTR_COST_PER_RESERVATION,
                ATTR_DYNAMIC_COST_PER_ENERGY
        };

        NodeList list = attrs.getElementsByTagName("attribute");
        for (int i = list.getLength() - 1; i >= 0; i--) {
            Element a = (Element) list.item(i);
            String name = a.getAttribute("name");
            for (String target : names) {
                if (target.equals(name)) {
                    attrs.removeChild(a);
                    break;
                }
            }
        }
    }

    private static void addOrReplaceAttribute(Document doc, Element attrs, String name, String clazz, String value) {
        Element existing = findAttribute(attrs, name);
        if (existing != null) {
            existing.setAttribute("class", clazz);
            existing.setTextContent(value);
            return;
        }

        Element a = doc.createElement("attribute");
        a.setAttribute("name", name);
        a.setAttribute("class", clazz);
        a.setTextContent(value);
        attrs.appendChild(a);
    }

    private static Element findAttribute(Element attrs, String name) {
        NodeList list = attrs.getElementsByTagName("attribute");
        for (int i = 0; i < list.getLength(); i++) {
            Element a = (Element) list.item(i);
            if (name.equals(a.getAttribute("name"))) {
                return a;
            }
        }
        return null;
    }

    private static void writePopulationWithDoctype(Scenario scenario, Path plansOut) throws IOException {
        Path tmpXml = Files.createTempFile("got_sevc_behavior_", ".xml");
        new PopulationWriter(scenario.getPopulation(), scenario.getNetwork()).write(tmpXml.toString());
        ensurePopulationDoctype(tmpXml, OUT_POPULATION_DTD);
        writeGzip(tmpXml, plansOut);
        Files.deleteIfExists(tmpXml);
    }

    private static void ensurePopulationDoctype(Path xmlFile, String localDtdRef) throws IOException {
        List<String> lines = Files.readAllLines(xmlFile, StandardCharsets.UTF_8);

        int doctypeIdx = -1;
        int xmlDeclIdx = -1;

        for (int i = 0; i < lines.size(); i++) {
            String t = lines.get(i).trim();
            if (t.startsWith("<?xml")) {
                xmlDeclIdx = i;
            }
            if (t.startsWith("<!DOCTYPE population")) {
                doctypeIdx = i;
                break;
            }
        }

        String doctypeLine = "<!DOCTYPE population SYSTEM \"" + localDtdRef + "\">";

        if (doctypeIdx >= 0) {
            lines.set(doctypeIdx, doctypeLine);
        } else {
            int insertAt = (xmlDeclIdx >= 0) ? (xmlDeclIdx + 1) : 0;
            lines.add(insertAt, doctypeLine);
        }

        Files.write(xmlFile, lines, StandardCharsets.UTF_8, StandardOpenOption.TRUNCATE_EXISTING);
    }

    private static void writeGzip(Path inXml, Path outGz) throws IOException {
        try (InputStream in = Files.newInputStream(inXml);
             OutputStream fout = Files.newOutputStream(outGz);
             GZIPOutputStream gz = new GZIPOutputStream(fout)) {
            in.transferTo(gz);
        }
    }

    private static int countActivitiesWithoutLink(Scenario scenario) {
        int count = 0;
        for (Person person : scenario.getPopulation().getPersons().values()) {
            for (Plan plan : person.getPlans()) {
                for (PlanElement pe : plan.getPlanElements()) {
                    if (pe instanceof Activity act && act.getLinkId() == null) {
                        count++;
                    }
                }
            }
        }
        return count;
    }

    private static double resolveInitialSocFraction(double initialSocOrEnergy, double batteryCapacityKWh) {
        if (batteryCapacityKWh <= 0.0) {
            return 1.0;
        }
        if (initialSocOrEnergy <= 1.000001) {
            return initialSocOrEnergy;
        }
        return initialSocOrEnergy / batteryCapacityKWh;
    }

    private static void validateLegacyVehicleIds(List<LegacyEv> legacy) {
        Set<String> ids = new HashSet<>();
        for (LegacyEv v : legacy) {
            if (!ids.add(v.id)) {
                throw new IllegalStateException("Duplicate legacy EV id found: " + v.id);
            }
        }
    }

    private static List<LegacyEv> readLegacyEvVehicles(Path file) throws Exception {
        Document doc = parseXmlNoExternalDtd(file);
        NodeList nodes = doc.getElementsByTagName("vehicle");

        List<LegacyEv> list = new ArrayList<>(nodes.getLength());

        for (int i = 0; i < nodes.getLength(); i++) {
            Element e = (Element) nodes.item(i);

            String id = e.getAttribute("id").trim();
            String vehicleType = e.getAttribute("vehicle_type").trim();
            String batteryCapacityStr = e.getAttribute("battery_capacity").trim();
            String initialSocStr = e.getAttribute("initial_soc").trim();
            String chargerTypesStr = e.getAttribute("charger_types").trim();

            if (id.isEmpty() || vehicleType.isEmpty() || batteryCapacityStr.isEmpty() || initialSocStr.isEmpty()) {
                continue;
            }

            double batteryCapacityKWh = Double.parseDouble(batteryCapacityStr);
            double initialSocOrEnergy = Double.parseDouble(initialSocStr);

            if (batteryCapacityKWh <= 0.0) {
                continue;
            }

            List<String> chargerTypes = parseChargerTypes(chargerTypesStr);
            if (chargerTypes.isEmpty()) {
                chargerTypes = List.of("default");
            }

            list.add(new LegacyEv(id, vehicleType, batteryCapacityKWh, initialSocOrEnergy, chargerTypes));
        }

        return list;
    }

    private static List<String> parseChargerTypes(String s) {
        if (s == null) {
            return Collections.emptyList();
        }
        s = s.trim();
        if (s.isEmpty()) {
            return Collections.emptyList();
        }

        s = s.replace("[", "").replace("]", "").replace("\"", "").replace("'", "");

        String[] parts = s.split("[,;\\s]+");
        List<String> out = new ArrayList<>();
        for (String p : parts) {
            if (!p.isBlank()) {
                out.add(p.trim());
            }
        }
        return out;
    }

    private static Document parseXmlNoExternalDtd(Path xml) throws Exception {
        DocumentBuilderFactory dbf = DocumentBuilderFactory.newInstance();
        dbf.setNamespaceAware(false);
        dbf.setValidating(false);

        try {
            dbf.setFeature("http://apache.org/xml/features/nonvalidating/load-external-dtd", false);
        } catch (Exception ignored) {
        }

        DocumentBuilder builder = dbf.newDocumentBuilder();
        builder.setEntityResolver((publicId, systemId) -> new InputSource(new StringReader("")));
        Document doc = builder.parse(xml.toFile());
        doc.getDocumentElement().normalize();
        return doc;
    }

    private static void writeXml(Document doc, Path file) throws Exception {
        Transformer tf = TransformerFactory.newInstance().newTransformer();
        tf.setOutputProperty(OutputKeys.INDENT, "yes");
        tf.setOutputProperty(OutputKeys.ENCODING, "UTF-8");
        tf.setOutputProperty("{http://xml.apache.org/xslt}indent-amount", "4");
        tf.transform(new DOMSource(doc), new StreamResult(file.toFile()));
    }

    private static String normalizePlugPower(String raw) {
        double value = Double.parseDouble(raw.trim());
        double watts = value * 1000.0;
        return stripTrailingZeros(watts);
    }

    private static String stripTrailingZeros(double value) {
        if (Math.rint(value) == value) {
            return Long.toString(Math.round(value));
        }
        return Double.toString(value);
    }

    private static double parsePower(String s) {
        return Double.parseDouble(s.trim());
    }

    private static double clamp01(double value) {
        if (Double.isNaN(value) || Double.isInfinite(value)) {
            return 0.8;
        }
        return Math.max(0.0, Math.min(1.0, value));
    }

    private static double readDouble(Person person, String attributeName, double fallback) {
        Object value = person.getAttributes().getAttribute(attributeName);
        if (value == null) {
            return fallback;
        }
        return Double.parseDouble(String.valueOf(value));
    }

    private static double parsePositiveDouble(String s, String label) {
        double value = Double.parseDouble(s);
        if (value < 0.0) {
            throw new IllegalArgumentException(label + " must be non-negative, found: " + s);
        }
        return value;
    }

    private static void validateTimeString(String time) {
        String[] p = time.split(":");
        if (p.length != 3) {
            throw new IllegalArgumentException("Invalid time breakpoint: " + time);
        }

        int h = Integer.parseInt(p[0]);
        int m = Integer.parseInt(p[1]);
        int s = Integer.parseInt(p[2]);

        if (h < 0 || h > 24 || m < 0 || m > 59 || s < 0 || s > 59) {
            throw new IllegalArgumentException("Invalid time breakpoint: " + time);
        }
    }

    private static String doubleString(double value) {
        return String.format(Locale.ROOT, "%.6f", value);
    }

    private static String escapeXml(String s) {
        return s.replace("&", "&amp;")
                .replace("\"", "&quot;")
                .replace("<", "&lt;")
                .replace(">", "&gt;");
    }

    private static Plan selectedOrFirst(Person person) {
        Plan selected = person.getSelectedPlan();
        return selected != null ? selected : (person.getPlans().isEmpty() ? null : person.getPlans().get(0));
    }

    private static boolean usesMode(Plan plan, String mode) {
        for (PlanElement pe : plan.getPlanElements()) {
            if (pe instanceof Leg leg && mode.equals(leg.getMode())) {
                return true;
            }
        }
        return false;
    }

    private static Activity firstActivityOfType(Plan plan, String type) {
        for (PlanElement pe : plan.getPlanElements()) {
            if (pe instanceof Activity act && type.equals(act.getType())) {
                return act;
            }
        }
        return null;
    }

    private static Id<Link> resolveLinkId(Activity act, Network carNetwork) {
        if (act.getLinkId() != null) {
            return act.getLinkId();
        }
        if (act.getCoord() == null) {
            return null;
        }
        Link nearest = NetworkUtils.getNearestLink(carNetwork, act.getCoord());
        if (nearest == null) {
            return null;
        }
        act.setLinkId(nearest.getId());
        return nearest.getId();
    }

    private static String stringAttr(Person person, String attrName) {
        Object o = person.getAttributes().getAttribute(attrName);
        return o == null ? null : o.toString();
    }

    private static final class LegacyEv {
        private final String id;
        private final String vehicleType;
        private final double batteryCapacityKWh;
        private final double initialSocOrEnergy;
        private final List<String> chargerTypes;

        private LegacyEv(String id, String vehicleType, double batteryCapacityKWh, double initialSocOrEnergy, List<String> chargerTypes) {
            this.id = id;
            this.vehicleType = vehicleType;
            this.batteryCapacityKWh = batteryCapacityKWh;
            this.initialSocOrEnergy = initialSocOrEnergy;
            this.chargerTypes = chargerTypes;
        }
    }

    private static final class WorkFacilityRecord {
        private final Id<ActivityFacility> facilityId;
        private final Id<Link> linkId;
        private final Coord coord;
        private double powerKw;
        private int plugCount = 1;
        private final Set<String> personIds = new LinkedHashSet<>();

        private WorkFacilityRecord(Id<ActivityFacility> facilityId, Id<Link> linkId, Coord coord, double powerKw) {
            this.facilityId = facilityId;
            this.linkId = linkId;
            this.coord = coord;
            this.powerKw = powerKw;
        }
    }

    private static final class SnappedPublicCharger {
        private final String id;
        private final Id<Link> linkId;
        private final String plugPower;
        private final int plugCount;
        private final double snapDistanceM;

        private SnappedPublicCharger(String id, Id<Link> linkId, String plugPower, int plugCount, double snapDistanceM) {
            this.id = id;
            this.linkId = linkId;
            this.plugPower = plugPower;
            this.plugCount = plugCount;
            this.snapDistanceM = snapDistanceM;
        }
    }

    private record ValidationSummary(
            int homeChargers,
            int homeChargersWithDynamicTariff,
            int homeChargersWithStaticOnly,
            int workChargersWithStaticCost,
            int publicChargersWithStaticCost
    ) {
    }
}
