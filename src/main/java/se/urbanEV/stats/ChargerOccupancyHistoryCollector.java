package se.urbanEV.stats;

import com.google.inject.Inject;
import se.urbanEV.MobsimScopeEventHandling;
import se.urbanEV.charging.ChargingStartEvent;
import se.urbanEV.charging.ChargingStartEventHandler;
import se.urbanEV.charging.UnpluggingEvent;
import se.urbanEV.charging.UnpluggingEventHandler;
import se.urbanEV.infrastructure.Charger;
import se.urbanEV.infrastructure.ChargingInfrastructure;
import org.matsim.contrib.ev.MobsimScopeEventHandler;

import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;

public class ChargerOccupancyHistoryCollector
		implements ChargingStartEventHandler, UnpluggingEventHandler, MobsimScopeEventHandler {

	private final ChargingInfrastructure chargingInfrastructure;
	private Map<Charger, OccupancyHistory> occupancyHistories;


	@Inject
	public ChargerOccupancyHistoryCollector(ChargingInfrastructure chargingInfrastructure,
                                            MobsimScopeEventHandling events) {
		this.chargingInfrastructure = chargingInfrastructure;
		this.occupancyHistories = new HashMap<>();
		for (Charger charger : chargingInfrastructure.getChargers().values()) {
			occupancyHistories.put(charger, new OccupancyHistory());
		}
		events.addMobsimScopeHandler(this);
	}

	@Override
	public void handleEvent(UnpluggingEvent event) {
		Charger charger = chargingInfrastructure.getChargers().get(event.getChargerId());
		this.occupancyHistories.get(charger)
				.addEntry(event.getTime(), charger.getLogic().getPluggedVehicles().size());
	}

	@Override
	public void handleEvent(ChargingStartEvent event) {
		Charger charger = chargingInfrastructure.getChargers().get(event.getChargerId());
		this.occupancyHistories.get(charger)
				.addEntry(event.getTime(), charger.getLogic().getPluggedVehicles().size());
	}

	public Map<Charger, OccupancyHistory> getOccupancyHistories() { return occupancyHistories; }

	class OccupancyHistory {

		private LinkedHashMap<Double, Integer> pluggedVehicleCounts;

		OccupancyHistory() {

			this.pluggedVehicleCounts = new LinkedHashMap<>();
		}

		private void addEntry(double time, int plugCount) {
			pluggedVehicleCounts.put(time, plugCount);
		}

		public Map<Double, Integer> getPluggedVehicleCounts() {
			return pluggedVehicleCounts;
		}

	}

}
