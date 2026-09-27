package se.urbanEV.charging;

import se.urbanEV.fleet.ElectricVehicle;
import se.urbanEV.infrastructure.Charger;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.events.Event;

import java.util.Map;

public class UnpluggingEvent extends Event {
	public static final String EVENT_TYPE = "unplugging";
	public static final String ATTRIBUTE_CHARGER = "charger";
	public static final String ATTRIBUTE_VEHICLE = "vehicle";
	public static final String ATTRIBUTE_PLUGGEDDURATION = "connection_duration";
	public static final String ATTRIBUTE_SIMULATION_HORIZON_CLOSURE = "simulation_horizon_closure";

	private final Id<Charger> chargerId;
	private final Id<ElectricVehicle> vehicleId;
	private final Double pluggedInDuration;
	private final boolean simulationHorizonClosure;

	public UnpluggingEvent(double time, Id<Charger> chargerId, Id<ElectricVehicle> vehicleId, double pluggedInDuration) {
		this(time, chargerId, vehicleId, pluggedInDuration, false);
	}

	public UnpluggingEvent(
			double time,
			Id<Charger> chargerId,
			Id<ElectricVehicle> vehicleId,
			double pluggedInDuration,
			boolean simulationHorizonClosure) {
		super(time);
		this.chargerId = chargerId;
		this.vehicleId = vehicleId;
		this.pluggedInDuration = pluggedInDuration;
		this.simulationHorizonClosure = simulationHorizonClosure;
	}

	public double getPluggedInDuration() {
		return pluggedInDuration;
	}

	public Id<Charger> getChargerId() {
		return chargerId;
	}

	public Id<ElectricVehicle> getVehicleId() {
		return vehicleId;
	}

	public boolean isSimulationHorizonClosure() {
		return simulationHorizonClosure;
	}

	@Override
	public String getEventType() {
		return EVENT_TYPE;
	}

	@Override
	public Map<String, String> getAttributes() {
		Map<String, String> attr = super.getAttributes();
		attr.put(ATTRIBUTE_CHARGER, chargerId.toString());
		attr.put(ATTRIBUTE_VEHICLE, vehicleId.toString());
		attr.put(ATTRIBUTE_PLUGGEDDURATION, String.valueOf(pluggedInDuration));
		attr.put(ATTRIBUTE_SIMULATION_HORIZON_CLOSURE,
				Boolean.toString(simulationHorizonClosure));
		return attr;
	}
}
