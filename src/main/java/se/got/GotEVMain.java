package se.got;

import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.api.core.v01.population.PlanElement;
import org.matsim.contrib.ev.EvConfigGroup;
import org.matsim.contrib.ev.strategic.StrategicChargingConfigGroup;
import org.matsim.contrib.ev.strategic.StrategicChargingUtils;
import org.matsim.contrib.ev.strategic.costs.AttributeBasedChargingCostsParameters;
import org.matsim.contrib.ev.strategic.costs.DefaultChargingCostsParameters;
import org.matsim.contrib.ev.strategic.costs.TariffBasedChargingCostsParameters;
import org.matsim.contrib.ev.strategic.replanning.innovator.RandomChargingPlanInnovator;
import org.matsim.contrib.ev.withinday.WithinDayEvConfigGroup;
import org.matsim.contrib.ev.withinday.WithinDayEvUtils;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.QSimConfigGroup;
import org.matsim.core.config.groups.RoutingConfigGroup;
import org.matsim.core.controler.Controler;
import org.matsim.core.controler.OutputDirectoryHierarchy.OverwriteFileSetting;
import org.matsim.vehicles.Vehicle;
import org.matsim.vehicles.VehicleType;
import org.matsim.vehicles.VehicleUtils;
import se.got.config.GothenburgBehaviorConfigGroup;
import se.got.config.GothenburgPricingConfigGroup;

import java.util.ArrayList;
import java.util.Map;

public final class GotEVMain {

    private static final String INITIAL_SOC_ATTRIBUTE = "initialSoc";
    private static final String CHARGER_TYPES_ATTRIBUTE = "chargerTypes";
    private static final String ENERGY_CAPACITY_ATTRIBUTE = "energyCapacityInKWhOrLiters";
    private static final String DEFAULT_NON_EV_CAR_TYPE_ID = "carDefaultNonEv";

    private GotEVMain() {
    }

    public static void main(String[] args) {
        if (args == null || args.length == 0 || args[0] == null || args[0].isBlank()) {
            throw new IllegalArgumentException("Usage: GotEVMain </scenarios/sweden/config.xml>");
        }

        String configPath = args[0];

        Config config = ConfigUtils.loadConfig(
                configPath,
                new EvConfigGroup(),
                new WithinDayEvConfigGroup(),
                new StrategicChargingConfigGroup(),
                new GothenburgPricingConfigGroup(),
                new GothenburgBehaviorConfigGroup()
        );

        config.routing().setNetworkRouteConsistencyCheck(
                RoutingConfigGroup.NetworkRouteConsistencyCheck.disable
        );
        config.controller().setOverwriteFileSetting(OverwriteFileSetting.deleteDirectoryIfExists);
        config.controller().setWritePlansUntilIteration(0);
        config.qsim().setVehiclesSource(QSimConfigGroup.VehiclesSource.fromVehiclesData);
        config.qsim().setUsePersonIdForMissingVehicleId(false);
        config.replanning().setMaxAgentPlanMemorySize(1);

        WithinDayEvConfigGroup wevcCfg = ConfigUtils.addOrGetModule(config, WithinDayEvConfigGroup.class);
        wevcCfg.setCarMode(TransportMode.car);
        wevcCfg.setWalkMode(TransportMode.walk);
        wevcCfg.setAbortAgents(false);

        StrategicChargingUtils.configureScoring(config);
        StrategicChargingUtils.configureStandaloneReplanning(config);

        StrategicChargingConfigGroup sevcCfg = ConfigUtils.addOrGetModule(config, StrategicChargingConfigGroup.class);

        for (var ps : new ArrayList<>(sevcCfg.getParameterSets(DefaultChargingCostsParameters.SET_NAME))) {
            sevcCfg.removeParameterSet(ps);
        }
        for (var ps : new ArrayList<>(sevcCfg.getParameterSets(AttributeBasedChargingCostsParameters.SET_NAME))) {
            sevcCfg.removeParameterSet(ps);
        }
        for (var ps : new ArrayList<>(sevcCfg.getParameterSets(TariffBasedChargingCostsParameters.SET_NAME))) {
            sevcCfg.removeParameterSet(ps);
        }
        sevcCfg.addParameterSet(new AttributeBasedChargingCostsParameters());

        if (sevcCfg.getInnovationParameters() == null) {
            sevcCfg.addParameterSet(new RandomChargingPlanInnovator.Parameters());
        }

        sevcCfg.setUseProactiveOnlineSearch(false);
        sevcCfg.setMaximumAlternatives(1);

        Scenario scenario = StrategicChargingUtils.loadScenario(config);

        ensureVehiclesForAllCarUsers(scenario);
        validateUniqueCarVehicleIds(scenario);
        validateCarRouteVehicleIds(scenario);
        validateEvPopulation(scenario);

        Controler controler = new Controler(scenario);
        StrategicChargingUtils.configureController(controler);
        controler.run();
    }

    private static void validateCarRouteVehicleIds(Scenario scenario) {
        int carLegs = 0;
        int missingVehicleRefIds = 0;
        int nullRoutes = 0;
        int nonNetworkRoutes = 0;

        for (Person person : scenario.getPopulation().getPersons().values()) {
            for (Plan plan : person.getPlans()) {
                for (PlanElement pe : plan.getPlanElements()) {
                    if (!(pe instanceof Leg leg)) {
                        continue;
                    }
                    if (!TransportMode.car.equals(leg.getMode())) {
                        continue;
                    }

                    carLegs++;

                    if (leg.getRoute() == null) {
                        nullRoutes++;
                        continue;
                    }

                    if (!(leg.getRoute() instanceof org.matsim.core.population.routes.NetworkRoute networkRoute)) {
                        nonNetworkRoutes++;
                        continue;
                    }

                    if (networkRoute.getVehicleId() == null) {
                        missingVehicleRefIds++;
                    }
                }
            }
        }

        System.out.println("[GotEVMain] car legs = " + carLegs);
        System.out.println("[GotEVMain] car legs with null route = " + nullRoutes);
        System.out.println("[GotEVMain] car legs with non-network route = " + nonNetworkRoutes);
        System.out.println("[GotEVMain] car network routes missing vehicleRefId = " + missingVehicleRefIds);

        if (nullRoutes > 0 || nonNetworkRoutes > 0 || missingVehicleRefIds > 0) {
            throw new IllegalStateException("Car-route vehicle references are not clean enough for Stage 1.");
        }
    }

    private static void ensureVehiclesForAllCarUsers(Scenario scenario) {
        var scenarioVehicles = scenario.getVehicles();

        Id<VehicleType> defaultTypeId = Id.create(DEFAULT_NON_EV_CAR_TYPE_ID, VehicleType.class);
        VehicleType defaultType = scenarioVehicles.getVehicleTypes().get(defaultTypeId);

        if (defaultType == null) {
            defaultType = scenarioVehicles.getFactory().createVehicleType(defaultTypeId);
            defaultType.setNetworkMode(TransportMode.car);
            defaultType.setMaximumVelocity(33.33);
            defaultType.setLength(4.5);
            defaultType.setWidth(1.8);
            VehicleUtils.setHbefaTechnology(defaultType.getEngineInformation(), "petrol");
            scenarioVehicles.addVehicleType(defaultType);
        }

        int carUsers = 0;
        int mappingsAdded = 0;
        int fallbackVehiclesCreated = 0;

        for (Person person : scenario.getPopulation().getPersons().values()) {
            Plan plan = person.getSelectedPlan();
            if (plan == null || !usesMode(plan, TransportMode.car)) {
                continue;
            }

            carUsers++;
            boolean isEvActive = WithinDayEvUtils.isActive(person);

            if (isEvActive) {
                if (!VehicleUtils.hasVehicleId(person, TransportMode.car)) {
                    throw new IllegalStateException(
                            "WEVC-active person " + person.getId() + " has no car vehicle mapping"
                    );
                }

                Id<Vehicle> evVid = VehicleUtils.getVehicleId(person, TransportMode.car);
                if (!scenarioVehicles.getVehicles().containsKey(evVid)) {
                    throw new IllegalStateException(
                            "WEVC-active person " + person.getId() + " maps to missing vehicle " + evVid
                    );
                }
                continue;
            }

            Id<Vehicle> vehicleId;
            if (!VehicleUtils.hasVehicleId(person, TransportMode.car)) {
                vehicleId = Id.createVehicleId(person.getId());
                VehicleUtils.insertVehicleIdsIntoPersonAttributes(person, Map.of(TransportMode.car, vehicleId));
                mappingsAdded++;
            } else {
                vehicleId = VehicleUtils.getVehicleId(person, TransportMode.car);
            }

            if (!scenarioVehicles.getVehicles().containsKey(vehicleId)) {
                scenarioVehicles.addVehicle(
                        scenarioVehicles.getFactory().createVehicle(vehicleId, defaultType)
                );
                fallbackVehiclesCreated++;
            }
        }

        System.out.println("[GotEVMain] car users = " + carUsers);
        System.out.println("[GotEVMain] added non-EV mappings = " + mappingsAdded);
        System.out.println("[GotEVMain] created fallback non-EV vehicles = " + fallbackVehiclesCreated);
    }

    private static void validateUniqueCarVehicleIds(Scenario scenario) {
        java.util.Map<Id<Vehicle>, Id<Person>> owners = new java.util.HashMap<>();

        for (Person person : scenario.getPopulation().getPersons().values()) {
            if (!VehicleUtils.hasVehicleId(person, TransportMode.car)) {
                continue;
            }

            Id<Vehicle> vid = VehicleUtils.getVehicleId(person, TransportMode.car);
            Id<Person> previous = owners.putIfAbsent(vid, person.getId());

            if (previous != null && !previous.equals(person.getId())) {
                throw new IllegalStateException(
                        "Duplicate car vehicle id " + vid + " assigned to persons "
                                + previous + " and " + person.getId()
                );
            }
        }
    }

    private static void validateEvPopulation(Scenario scenario) {
        int evPersons = 0;
        int validated = 0;
        var scenarioVehicles = scenario.getVehicles();

        for (Person person : scenario.getPopulation().getPersons().values()) {
            if (!WithinDayEvUtils.isActive(person)) {
                continue;
            }

            evPersons++;

            if (!VehicleUtils.hasVehicleId(person, TransportMode.car)) {
                throw new IllegalStateException(
                        "WEVC-active person " + person.getId() + " has no car vehicle mapping"
                );
            }

            Id<Vehicle> vehicleId = VehicleUtils.getVehicleId(person, TransportMode.car);
            Vehicle vehicle = scenarioVehicles.getVehicles().get(vehicleId);

            if (vehicle == null) {
                throw new IllegalStateException(
                        "WEVC-active person " + person.getId() + " maps to missing vehicle " + vehicleId
                );
            }

            VehicleType type = vehicle.getType();
            if (type == null) {
                throw new IllegalStateException("Vehicle " + vehicleId + " has no type");
            }

            Object tech = type.getEngineInformation().getAttributes().getAttribute("HbefaTechnology");
            if (tech == null || !"electricity".equalsIgnoreCase(String.valueOf(tech))) {
                throw new IllegalStateException(
                        "Vehicle " + vehicleId + " of person " + person.getId() + " is not electric"
                );
            }

            Object chargerTypes = type.getEngineInformation().getAttributes().getAttribute(CHARGER_TYPES_ATTRIBUTE);
            if (chargerTypes == null) {
                throw new IllegalStateException("Vehicle " + vehicleId + " has no chargerTypes attribute");
            }

            Object capacity = type.getEngineInformation().getAttributes().getAttribute(ENERGY_CAPACITY_ATTRIBUTE);
            if (capacity == null) {
                throw new IllegalStateException("Vehicle " + vehicleId + " has no energy capacity attribute");
            }

            Object initialSoc = vehicle.getAttributes().getAttribute(INITIAL_SOC_ATTRIBUTE);
            if (initialSoc == null) {
                throw new IllegalStateException("Vehicle " + vehicleId + " has no initialSoc attribute");
            }

            validated++;
        }

        System.out.println("[GotEVMain] WEVC-active persons = " + evPersons);
        System.out.println("[GotEVMain] validated EV persons = " + validated);

        if (evPersons == 0 || validated != evPersons) {
            throw new IllegalStateException("Stage 1 EV population validation failed.");
        }
    }

    private static boolean usesMode(Plan plan, String mode) {
        for (PlanElement pe : plan.getPlanElements()) {
            if (pe instanceof Leg leg && mode.equals(leg.getMode())) {
                return true;
            }
        }
        return false;
    }
}