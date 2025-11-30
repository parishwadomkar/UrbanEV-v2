package se.urbanEV.stats;

import com.google.inject.Inject;
import org.apache.log4j.Logger;
import org.matsim.api.core.v01.Id;
import org.matsim.contrib.ev.MobsimScopeEventHandler;
import se.urbanEV.MobsimScopeEventHandling;
import se.urbanEV.charging.ChargingEndEvent;
import se.urbanEV.charging.ChargingEndEventHandler;
import se.urbanEV.charging.ChargingStartEvent;
import se.urbanEV.charging.ChargingStartEventHandler;
import se.urbanEV.charging.UnpluggingEvent;
import se.urbanEV.charging.UnpluggingEventHandler;
import se.urbanEV.fleet.ElectricFleet;
import se.urbanEV.fleet.ElectricVehicle;
import se.urbanEV.infrastructure.ChargingInfrastructure;
import se.urbanEV.scoring.ChargingBehaviourScoringEvent;
import se.urbanEV.scoring.ChargingBehaviourScoringEventHandler;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;

public class ChargerPowerCollector
        implements ChargingStartEventHandler, ChargingEndEventHandler,
        UnpluggingEventHandler, ChargingBehaviourScoringEventHandler, MobsimScopeEventHandler {

    private static final Logger log = Logger.getLogger(ChargerPowerCollector.class);

    private final ChargingInfrastructure chargingInfrastructure;
    private final ElectricFleet fleet;

    private final HashMap<Id<ElectricVehicle>, ChargingLogEntry> activeChargingProcesses = new HashMap<>();
    private final List<ChargingLogEntry> logList = new ArrayList<>();

    @Inject
    public ChargerPowerCollector(ElectricFleet fleet,
                                 ChargingInfrastructure chargingInfrastructure,
                                 MobsimScopeEventHandling events) {
        this.fleet = fleet;
        this.chargingInfrastructure = chargingInfrastructure;
        events.addMobsimScopeHandler(this);
    }

    @Override
    public void handleEvent(ChargingStartEvent event) {
        ElectricVehicle ev = fleet.getElectricVehicles().get(event.getVehicleId());
        if (ev == null) {
            log.warn("ChargingStartEvent for unknown EV " + event.getVehicleId());
            return;
        }

        ChargingLogEntry chargingProcess = new ChargingLogEntry(ev.getId());
        chargingProcess.setCharger(chargingInfrastructure.getChargers().get(event.getChargerId()));
        chargingProcess.setStartTime(event.getTime());
        chargingProcess.setStartSOC(ev.getBattery().getSoc() / ev.getBattery().getCapacity());
        chargingProcess.setStartSOC_J(ev.getBattery().getSoc());

        activeChargingProcesses.put(ev.getId(), chargingProcess);
    }

    @Override
    public void handleEvent(ChargingEndEvent event) {
        ElectricVehicle ev = fleet.getElectricVehicles().get(event.getVehicleId());
        if (ev == null) {
            log.warn("ChargingEndEvent for unknown EV " + event.getVehicleId());
            return;
        }

        ChargingLogEntry chargingProcess = activeChargingProcesses.get(ev.getId());
        if (chargingProcess == null) {
            log.warn("ChargingEndEvent for EV " + ev.getId()
                    + " without activeChargingProcess; ignoring.");
            return;
        }

        chargingProcess.setEndTime(event.getTime());
        chargingProcess.setEndSOC_J(ev.getBattery().getSoc());
        chargingProcess.setEndSOC(ev.getBattery().getSoc() / ev.getBattery().getCapacity());
        chargingProcess.setChargingDuration(event.getCharging_duration());
        chargingProcess.setTransmittedEnergy_J(
                chargingProcess.getEndSOC_J() - chargingProcess.getStartSOC_J()
        );
    }

    @Override
    public void handleEvent(UnpluggingEvent event) {
        ElectricVehicle ev = fleet.getElectricVehicles().get(event.getVehicleId());
        if (ev == null) {
            log.warn("UnpluggingEvent for unknown EV " + event.getVehicleId());
            return;
        }

        ChargingLogEntry chargingProcess = activeChargingProcesses.remove(ev.getId());
        if (chargingProcess == null) {
            log.warn("UnpluggingEvent for EV " + ev.getId()
                    + " but no activeChargingProcess; ignoring.");
            return;
        }

        chargingProcess.setUnplugTime(event.getTime());

        double startTime = chargingProcess.getStartTime();
        double unplugTime = chargingProcess.getUnplugTime();
        double pluggedDuration = unplugTime - startTime;

        if (pluggedDuration <= 0.0) {
            log.warn("Non-positive pluggedDuration for EV " + ev.getId()
                    + " (start=" + startTime + ", unplug=" + unplugTime + "); dropping entry.");
            return;
        }

        chargingProcess.setPluggedDuration(pluggedDuration);
        double chargingDuration = chargingProcess.getChargingDuration();
        double ratio;
        if (chargingDuration <= 0.0 || chargingDuration > pluggedDuration) {
            ratio = 0.0;
        } else {
            ratio = chargingDuration / pluggedDuration;
        }
        chargingProcess.setChargingRatio(ratio);

        if (chargingProcess.complete() && chargingProcess.valid()) {
            logList.add(chargingProcess);
        } else {
            log.warn("Dropping invalid or incomplete ChargingLogEntry for EV " + ev.getId());
        }
    }

    @Override
    public void handleEvent(ChargingBehaviourScoringEvent event) {
        Id<ElectricVehicle> evId = Id.create(event.getPersonId(), ElectricVehicle.class);
        ElectricVehicle ev = fleet.getElectricVehicles().get(evId);

        if (ev == null) {
            // This can happen for purely scoring-related events; ignore safely.
            return;
        }

        ChargingLogEntry chargingProcess = activeChargingProcesses.get(ev.getId());
        if (chargingProcess != null) {
            chargingProcess.setWalkingDistance(event.getWalkingDistance());
        }
    }

    public List<ChargingLogEntry> getLogList() {
        return logList;
    }
}
