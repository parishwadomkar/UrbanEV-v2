package se.urbanEV.charging;

import com.google.common.collect.ImmutableList;
import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.network.Link;
import org.matsim.core.api.experimental.events.EventsManager;
import org.matsim.core.events.EventsUtils;
import se.urbanEV.discharging.AuxEnergyConsumption;
import se.urbanEV.discharging.DriveEnergyConsumption;
import se.urbanEV.fleet.Battery;
import se.urbanEV.fleet.BatteryImpl;
import se.urbanEV.fleet.ElectricVehicle;
import se.urbanEV.fleet.ElectricVehicleType;
import se.urbanEV.infrastructure.Charger;

import java.util.Collections;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ChargingLogicImplTest {
    @Test
    void chargingEndReportsGridEnergyRatherThanNetSocIncrease() {
        EventsManager events = EventsUtils.createEventsManager();
        ChargingEndEvent[] captured = new ChargingEndEvent[1];
        UnpluggingEvent[] unplugging = new UnpluggingEvent[1];
        events.addHandler((ChargingEndEventHandler) event -> captured[0] = event);
        events.addHandler((UnpluggingEventHandler) event -> unplugging[0] = event);

        Charger charger = new TestCharger();
        ElectricVehicle vehicle = new TestVehicle();
        ChargingStrategy strategy = new ChargingStrategy() {
            @Override
            public double calcRemainingEnergyToCharge(ElectricVehicle ev) {
                return ev.getBattery().getCapacity() - ev.getBattery().getSoc();
            }

            @Override
            public double calcRemainingTimeToCharge(ElectricVehicle ev) {
                return 0.0;
            }
        };

        ChargingLogicImpl logic = new ChargingLogicImpl(charger, strategy, events);
        logic.addVehicle(vehicle, 0.0);
        vehicle.getBattery().changeSoc(2.0); // simultaneous VIPV contribution
        logic.chargeVehicles(3.0, 3.0);      // 1 W for 3 s from the grid
        logic.removeVehicle(vehicle, 4.0);

        assertEquals(5.0, vehicle.getBattery().getSoc() - 40.0, 0.0);
        assertEquals(3.0, captured[0].getGridEnergy_J(), 0.0);
        assertFalse(captured[0].isSimulationHorizonClosure());
        assertFalse(unplugging[0].isSimulationHorizonClosure());
    }

    @Test
    void horizonRemovalMarksBothSessionClosureEvents() {
        EventsManager events = EventsUtils.createEventsManager();
        ChargingEndEvent[] chargingEnd = new ChargingEndEvent[1];
        UnpluggingEvent[] unplugging = new UnpluggingEvent[1];
        events.addHandler((ChargingEndEventHandler) event -> chargingEnd[0] = event);
        events.addHandler((UnpluggingEventHandler) event -> unplugging[0] = event);

        ElectricVehicle vehicle = new TestVehicle();
        ChargingStrategy neverComplete = new ChargingStrategy() {
            @Override public double calcRemainingEnergyToCharge(ElectricVehicle ev) { return 1.0; }
            @Override public double calcRemainingTimeToCharge(ElectricVehicle ev) { return 1.0; }
        };
        ChargingLogicImpl logic = new ChargingLogicImpl(new TestCharger(), neverComplete, events);
        logic.addVehicle(vehicle, 0.0);
        logic.removeVehicleAtSimulationHorizon(vehicle, 100.0);

        assertTrue(chargingEnd[0].isSimulationHorizonClosure());
        assertTrue(unplugging[0].isSimulationHorizonClosure());
    }

    private static final class TestVehicle implements ElectricVehicle {
        private final Id<ElectricVehicle> id = Id.create("ev-1", ElectricVehicle.class);
        private final Battery battery = new BatteryImpl(100.0, 40.0);

        @Override public Id<ElectricVehicle> getId() { return id; }
        @Override public DriveEnergyConsumption getDriveEnergyConsumption() { return null; }
        @Override public AuxEnergyConsumption getAuxEnergyConsumption() { return null; }
        @Override public ChargingPower getChargingPower() { return charger -> 1.0; }
        @Override public Battery getBattery() { return battery; }
        @Override public ElectricVehicleType getVehicleType() { return null; }
        @Override public ImmutableList<String> getChargerTypes() { return ImmutableList.of("default"); }
    }

    private static final class TestCharger implements Charger {
        private final Id<Charger> id = Id.create("charger-1", Charger.class);

        @Override public Id<Charger> getId() { return id; }
        @Override public ChargingLogic getLogic() { return null; }
        @Override public Coord getCoord() { return null; }
        @Override public Link getLink() { return null; }
        @Override public String getChargerType() { return "default"; }
        @Override public double getPlugPower() { return 1.0; }
        @Override public int getPlugCount() { return 1; }
        @Override public List<Id<ElectricVehicle>> getAllowedVehicles() { return Collections.emptyList(); }
    }
}
