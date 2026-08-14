package se.urbanEV.stats;

import com.google.inject.Inject;
import org.apache.log4j.Logger;
import org.matsim.api.core.v01.Id;
import org.matsim.contrib.ev.MobsimScopeEventHandler;
import org.matsim.contrib.ev.EvUnits;
import se.urbanEV.MobsimScopeEventHandling;
import se.urbanEV.charging.ChargingEndEvent;
import se.urbanEV.charging.ChargingEndEventHandler;
import se.urbanEV.charging.ChargingStartEvent;
import se.urbanEV.charging.ChargingStartEventHandler;
import se.urbanEV.charging.UnpluggingEvent;
import se.urbanEV.charging.UnpluggingEventHandler;
import se.urbanEV.charging.ChargingCostUtils;
import se.urbanEV.config.UrbanEVConfigGroup;
import se.urbanEV.infrastructure.Charger;
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
    private final UrbanEVConfigGroup cfg;

    private final HashMap<Id<ElectricVehicle>, ChargingLogEntry> activeChargingProcesses = new HashMap<>();

    // Needed for deferred smart charging: the scoring event may occur before the actual ChargingStartEvent.
    private final HashMap<Id<ElectricVehicle>, Double> pendingWalkingDistance = new HashMap<>();

    private final List<ChargingLogEntry> logList = new ArrayList<>();

    @Inject
    public ChargerPowerCollector(
            ElectricFleet fleet,
            ChargingInfrastructure chargingInfrastructure,
            MobsimScopeEventHandling events,
            UrbanEVConfigGroup cfg) {

        this.fleet = fleet;
        this.chargingInfrastructure = chargingInfrastructure;
        this.cfg = cfg;

        events.addMobsimScopeHandler(this);
    }

    @Override
    public void handleEvent(ChargingStartEvent event) {

        ElectricVehicle ev =
                fleet.getElectricVehicles().get(event.getVehicleId());

        if (ev == null) {
            log.warn("ChargingStartEvent for unknown EV " + event.getVehicleId());
            return;
        }

        Charger charger =
                chargingInfrastructure.getChargers().get(event.getChargerId());

        if (charger == null) {
            log.warn("ChargingStartEvent for unknown charger " + event.getChargerId());
            return;
        }

        ChargingLogEntry chargingProcess =
                new ChargingLogEntry(ev.getId());

        chargingProcess.setCharger(charger);

        chargingProcess.setChargerAccessType(
                ChargingCostUtils.getChargerAccessType(
                        charger.getId().toString()
                )
        );

        chargingProcess.setStartTime(event.getTime());

        chargingProcess.setStartSOC(
                ev.getBattery().getSoc()
                        / ev.getBattery().getCapacity()
        );

        chargingProcess.setStartSOC_J(
                ev.getBattery().getSoc()
        );

        Double pendingDistance =
                pendingWalkingDistance.remove(ev.getId());

        if (pendingDistance != null) {
            chargingProcess.setWalkingDistance(pendingDistance);
        }

        activeChargingProcesses.put(
                ev.getId(),
                chargingProcess
        );
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
        chargingProcess.setChargingDuration(
                event.getCharging_duration()
        );

        // Grid/charger-delivered energy only. Rooftop-PV energy is not included.
        double gridEnergy_J =
                Math.max(0.0,event.getGridEnergy_J());

        chargingProcess.setTransmittedEnergy_J(gridEnergy_J);
        double gridEnergy_kWh =EvUnits.J_to_kWh(gridEnergy_J);
        String accessType = chargingProcess.getChargerAccessType();
        double basePrice = ChargingCostUtils.getBasePricePerKWh(accessType, cfg);

        double avgTouMultiplier =
                ChargingCostUtils.getAverageTouMultiplier(
                        chargingProcess.getStartTime(),
                        chargingProcess.getEndTime(),
                        accessType,
                        cfg
                );

        double effectivePrice =
                ChargingCostUtils.getEffectivePricePerKWh(
                        chargingProcess.getStartTime(),
                        chargingProcess.getEndTime(),
                        accessType,
                        cfg
                );

        double chargingCost = gridEnergy_kWh * effectivePrice;

        chargingProcess.setBasePricePerKWh(basePrice);
        chargingProcess.setAverageTouMultiplier(avgTouMultiplier);
        chargingProcess.setEffectivePricePerKWh(effectivePrice);
        chargingProcess.setChargingCost(chargingCost);
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
//            log.warn("Non-positive pluggedDuration for EV " + ev.getId()
//                    + " (start=" + startTime + ", unplug=" + unplugTime + "); dropping entry.");
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

        // Synthetic end-of-session cost event carries walkingDistance=0.
        // It must not overwrite the actual charger-access distance.
        if (event.isCostOnly()) {
            return;
        }

        if (event.getPersonId() == null) {
            return;
        }

        Id<ElectricVehicle> evId =
                Id.create(
                        event.getPersonId().toString(),
                        ElectricVehicle.class
                );

        ElectricVehicle ev =
                fleet.getElectricVehicles().get(evId);

        if (ev == null) {return;}

        Double walkingDistance = event.getWalkingDistance();
        String activityType = event.getActivityType();

        if (walkingDistance == null
                || !Double.isFinite(walkingDistance)
                || walkingDistance < 0.0
                || activityType == null
                || !activityType.contains(" charging")) {
            return;
        }

        ChargingLogEntry chargingProcess = activeChargingProcesses.get(ev.getId());

        if (chargingProcess != null) {

            // Immediate charging: ChargingStartEvent has already occurred.
            chargingProcess.setWalkingDistance(
                    walkingDistance
            );

        } else {

            // Deferred smart charging: scoring event occurs at activity arrival, while ChargingStartEvent occurs later.
            pendingWalkingDistance.put(ev.getId(),walkingDistance);
        }
    }

    public List<ChargingLogEntry> getLogList() {
        return logList;
    }
}
