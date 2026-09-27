package se.urbanEV.charging;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Id;
import se.urbanEV.fleet.ElectricVehicle;
import se.urbanEV.infrastructure.Charger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ChargingEndEventTest {
    @Test
    void requiresAndExportsMeasuredGridEnergy() {
        Id<Charger> chargerId = Id.create("charger-1", Charger.class);
        Id<ElectricVehicle> vehicleId = Id.create("ev-1", ElectricVehicle.class);

        ChargingEndEvent event = new ChargingEndEvent(
                100.0, chargerId, vehicleId, 0.8, 50.0, 3_600_000.0);
        assertEquals(3_600_000.0, event.getGridEnergy_J(), 0.0);
        assertEquals("3600000.0", event.getAttributes().get(ChargingEndEvent.ATTRIBUTE_GRIDENERGY));
        assertFalse(event.isSimulationHorizonClosure());

        ChargingEndEvent horizonEvent = new ChargingEndEvent(
                100.0, chargerId, vehicleId, 0.8, 50.0, 3_600_000.0, true);
        assertTrue(horizonEvent.isSimulationHorizonClosure());
        assertEquals("true", horizonEvent.getAttributes().get(
                ChargingEndEvent.ATTRIBUTE_SIMULATION_HORIZON_CLOSURE));

        assertThrows(IllegalArgumentException.class,
                () -> new ChargingEndEvent(
                        100.0, chargerId, vehicleId, 0.8, 50.0, -1.0));
    }
}
