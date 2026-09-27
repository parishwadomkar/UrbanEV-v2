package org.matsim.core.events;

import com.google.common.collect.ImmutableList;
import com.google.common.collect.ImmutableMap;
import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.events.VehicleEntersTrafficEvent;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.vehicles.Vehicle;
import se.urbanEV.MobsimScopeEventHandling;
import se.urbanEV.charging.ChargingPower;
import se.urbanEV.config.UrbanEVConfigGroup;
import se.urbanEV.discharging.AuxEnergyConsumption;
import se.urbanEV.discharging.DriveEnergyConsumption;
import se.urbanEV.fleet.Battery;
import se.urbanEV.fleet.BatteryImpl;
import se.urbanEV.fleet.ElectricFleet;
import se.urbanEV.fleet.ElectricFleetSpecification;
import se.urbanEV.fleet.ElectricVehicle;
import se.urbanEV.fleet.ElectricVehicleSpecification;
import se.urbanEV.fleet.ElectricVehicleType;
import se.urbanEV.pv.PvChargingIntervalEvent;
import se.urbanEV.pv.PvChargingIntervalEventHandler;
import se.urbanEV.pv.PvGenerationHandler;
import se.urbanEV.pv.PvVehicleRegistry;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

class PvGenerationEventOrderingTest {
    private static final double SUNSET_S = 17.0 * 3600.0;
    private static final double TRIGGER_S = SUNSET_S + 5.0;

    @Test
    void analyticalIntervalClosureDoesNotBackdateParallelMatsimEvent() {
        Id<ElectricVehicle> evId = Id.create("ev-ordering", ElectricVehicle.class);
        TestVehicle vehicle = new TestVehicle(evId);

        Config config = ConfigUtils.createConfig();
        config.global().setRandomSeed(4711L);
        config.qsim().setEndTime(24.0 * 3600.0);

        UrbanEVConfigGroup cfg = new UrbanEVConfigGroup();
        cfg.setSeason("WINTER");
        cfg.setPvShare(1.0);
        cfg.setPvWp(700.0);
        cfg.setPvParkedOpenShare(0.0);

        ElectricFleet fleet = () -> ImmutableMap.of(evId, vehicle);
        ElectricFleetSpecification fleetSpecification = specificationWith(evId);
        PvVehicleRegistry registry = new PvVehicleRegistry(cfg, fleetSpecification, config);
        registry.notifyStartup(null);

        SimStepParallelEventsManagerImpl events = new SimStepParallelEventsManagerImpl(1);
        MobsimScopeEventHandling mobsimScope = new MobsimScopeEventHandling(events);
        PvGenerationHandler pv = new PvGenerationHandler(
                fleet,
                cfg,
                registry,
                events,
                config,
                () -> 0,
                mobsimScope);

        AtomicReference<PvChargingIntervalEvent> captured = new AtomicReference<>();
        events.addHandler((PvChargingIntervalEventHandler) captured::set);
        events.addHandler((BasicEventHandler) event -> {
            if ("pvIntegrationTrigger".equals(event.getEventType())) {
                pv.integrateVehicleTo(vehicle, TRIGGER_S);
            }
        });

        events.initProcessing();
        events.processEvent(new VehicleEntersTrafficEvent(
                0.0,
                Id.createPersonId("person-ordering"),
                Id.createLinkId("link-ordering"),
                Id.create("ev-ordering", Vehicle.class),
                "car",
                1.0));
        events.processEvent(new Event(TRIGGER_S) {
            @Override
            public String getEventType() {
                return "pvIntegrationTrigger";
            }
        });

        assertDoesNotThrow(() -> events.afterSimStep(TRIGGER_S));
        assertDoesNotThrow(events::finishProcessing);

        PvChargingIntervalEvent interval = captured.get();
        assertNotNull(interval);
        assertEquals(TRIGGER_S, interval.getTime(), 0.0);
        assertEquals(SUNSET_S, interval.getIntervalEnd_s(), 0.0);
    }

    private static ElectricFleetSpecification specificationWith(Id<ElectricVehicle> evId) {
        return new ElectricFleetSpecification() {
            private final Map<Id<ElectricVehicle>, ElectricVehicleSpecification> specifications =
                    new LinkedHashMap<>();

            {
                specifications.put(evId, null);
            }

            @Override
            public Map<Id<ElectricVehicle>, ElectricVehicleSpecification> getVehicleSpecifications() {
                return specifications;
            }

            @Override
            public void addVehicleSpecification(ElectricVehicleSpecification specification) {
                specifications.put(specification.getId(), specification);
            }

            @Override
            public void replaceVehicleSpecification(ElectricVehicleSpecification specification) {
                specifications.put(specification.getId(), specification);
            }

            @Override
            public void removeVehicleSpecification(Id<ElectricVehicle> vehicleId) {
                specifications.remove(vehicleId);
            }
        };
    }

    private static final class TestVehicle implements ElectricVehicle {
        private final Id<ElectricVehicle> id;
        private final Battery battery = new BatteryImpl(100_000_000.0, 0.0);

        private TestVehicle(Id<ElectricVehicle> id) {
            this.id = id;
        }

        @Override public Id<ElectricVehicle> getId() { return id; }
        @Override public DriveEnergyConsumption getDriveEnergyConsumption() { return null; }
        @Override public AuxEnergyConsumption getAuxEnergyConsumption() { return null; }
        @Override public ChargingPower getChargingPower() { return null; }
        @Override public Battery getBattery() { return battery; }
        @Override public ElectricVehicleType getVehicleType() { return null; }
        @Override public ImmutableList<String> getChargerTypes() { return ImmutableList.of(); }
    }
}
