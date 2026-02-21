package se.urbanEV.pv;

import org.matsim.api.core.v01.events.Event;

import java.util.HashMap;
import java.util.Map;

/**
 * Vehicle Integrated Photovoltaic (VIPV)
 * created by OmkarP.(2026)
 */
public final class PvChargingIntervalEvent extends Event {
    public static final String EVENT_TYPE = "pvChargingInterval";

    private final String vehicleId;
    private final double intervalStart_s;
    private final double intervalEnd_s;
    private final String mode;

    private final double energyProduced_kWh;
    private final double energyStored_kWh;
    private final double energyWasted_kWh;

    private final double startSoc_frac;
    private final double endSoc_frac;

    public PvChargingIntervalEvent(
            double time,
            String vehicleId,
            double intervalStart_s,
            double intervalEnd_s,
            String mode,
            double energyProduced_kWh,
            double energyStored_kWh,
            double energyWasted_kWh,
            double startSoc_frac,
            double endSoc_frac
    ) {
        super(time);
        this.vehicleId = vehicleId;
        this.intervalStart_s = intervalStart_s;
        this.intervalEnd_s = intervalEnd_s;
        this.mode = mode;
        this.energyProduced_kWh = energyProduced_kWh;
        this.energyStored_kWh = energyStored_kWh;
        this.energyWasted_kWh = energyWasted_kWh;
        this.startSoc_frac = startSoc_frac;
        this.endSoc_frac = endSoc_frac;
    }

    @Override
    public String getEventType() {
        return EVENT_TYPE;
    }

    public String getVehicleId() { return vehicleId; }
    public double getIntervalStart_s() { return intervalStart_s; }
    public double getIntervalEnd_s() { return intervalEnd_s; }
    public String getMode() { return mode; }
    public double getEnergyProduced_kWh() { return energyProduced_kWh; }
    public double getEnergyStored_kWh() { return energyStored_kWh; }
    public double getEnergyWasted_kWh() { return energyWasted_kWh; }
    public double getStartSoc_frac() { return startSoc_frac; }
    public double getEndSoc_frac() { return endSoc_frac; }

    @Override
    public Map<String, String> getAttributes() {
        Map<String, String> a = new HashMap<>(super.getAttributes());
        a.put("vehicleId", vehicleId);
        a.put("pvChargeStart_s", Double.toString(intervalStart_s));
        a.put("pvChargeEnd_s", Double.toString(intervalEnd_s));
        a.put("mode", mode);
        a.put("pvEnergyProduced_kWh", Double.toString(energyProduced_kWh));
        a.put("pvEnergyStored_kWh", Double.toString(energyStored_kWh));
        a.put("pvEnergyWasted_kWh", Double.toString(energyWasted_kWh));
        a.put("startSoc_frac", Double.toString(startSoc_frac));
        a.put("endSoc_frac", Double.toString(endSoc_frac));
        return a;
    }
}