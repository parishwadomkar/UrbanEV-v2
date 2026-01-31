package se.urbanEV.charging;

import org.apache.log4j.Logger;
import org.matsim.api.core.v01.Id;
import se.urbanEV.fleet.ElectricFleet;
import se.urbanEV.fleet.ElectricVehicle;
import se.urbanEV.infrastructure.Charger;
import se.urbanEV.infrastructure.ChargingInfrastructure;

import java.util.HashMap;
import java.util.Iterator;
import java.util.Map;

/**
 * created by OmkarP.(2025)
 * Scheduler for deferred smart charging.
 *
 * This is now a pure helper class, NOT an EventHandler.
 * It is driven explicitly by VehicleChargingHandler, which calls processDueTasks(now)
 * from its own event callbacks. This avoids interfering with the MATSim
 * SimStepParallelEventsManager ordering.
 */
public class SmartChargingScheduler {
    private static final Logger log = Logger.getLogger(SmartChargingScheduler.class);
    private long nScheduled = 0;
    private long nPlugged = 0;
    private long nMissing = 0;

    private final ChargingInfrastructure infra;
    private final ElectricFleet fleet;
    private final VehicleChargingHandler chargingHandler;
    private final Map<Id<ElectricVehicle>, ScheduledCharge> scheduled = new HashMap<>();

    public SmartChargingScheduler(ChargingInfrastructure infra,
                                  ElectricFleet fleet,
                                  VehicleChargingHandler chargingHandler) {
        this.infra = infra;
        this.fleet = fleet;
        this.chargingHandler = chargingHandler;
    }

    /**
     * Schedule a deferred plug-in for an EV at a specific charger and time.
     */
    public synchronized void schedule(Id<ElectricVehicle> evId, Id<Charger> chargerId, double startTime) {
        double clampedStart = Math.max(0.0, startTime);
        scheduled.put(evId, new ScheduledCharge(evId, chargerId, clampedStart));
        nScheduled++;
        log.info("SmartChargingScheduler: scheduled EV " + evId + " at t=" + (int) clampedStart + " on charger " + chargerId);
    }

    /**
     * Cancel a scheduled plug-in (e.g. when the charging activity ends before it happens).
     */
    public synchronized void cancelIfScheduled(Id<ElectricVehicle> evId) {
        scheduled.remove(evId);
    }

    /**
     * Called explicitly from VehicleChargingHandler whenever we have a well-defined simulation time.
     * Any scheduled charging whose startTime <= now will be executed at 'now'.
     *
     * This is the critical change: we do NOT hook into the EventsManager anymore,
     * we only act from inside an already-running event handler.
     */
    public synchronized void processDueTasks(double now) {
        if (scheduled.isEmpty()) return;

        Iterator<Map.Entry<Id<ElectricVehicle>, ScheduledCharge>> it = scheduled.entrySet().iterator();
        while (it.hasNext()) {
            Map.Entry<Id<ElectricVehicle>, ScheduledCharge> e = it.next();
            ScheduledCharge sc = e.getValue();

            if (sc.startTime <= now + 1e-3) {
                it.remove();

                ElectricVehicle ev = fleet.getElectricVehicles().get(sc.evId);
                Charger charger = infra.getChargers().get(sc.chargerId);
                if (ev == null || charger == null) {
                    nMissing++;
                    continue;
                }
                int plugged = charger.getLogic().getPluggedVehicles().size();
                int plugs = charger.getPlugCount();
                if (plugged >= plugs) {
                    log.warn("SmartChargingScheduler: charger FULL at plug time; ev=" + sc.evId
                            + " charger=" + sc.chargerId + " now=" + (int) now
                            + " scheduled=" + (int) sc.startTime + " plugged=" + plugged + "/" + plugs
                            + " -> retry in 300s");
                    scheduled.put(sc.evId, new ScheduledCharge(sc.evId, sc.chargerId, now + 300.0));
                    continue;
                }

                charger.getLogic().addVehicle(ev, now);
                chargingHandler.onSmartChargePlugged(sc.evId, sc.chargerId, now);
                nPlugged++;
            }
        }
    }

    public synchronized String consumeStatsLine(int iteration) {
        String s = "SmartChargingScheduler stats: it=" + iteration
                + " scheduled=" + nScheduled
                + " plugged=" + nPlugged
                + " missing=" + nMissing
                + " pending=" + scheduled.size();
        nScheduled = 0; nPlugged = 0; nMissing = 0;
        return s;
    }

    public synchronized void reset() {
        scheduled.clear();
    }

    private static class ScheduledCharge {
        final Id<ElectricVehicle> evId;
        final Id<Charger> chargerId;
        final double startTime;
        ScheduledCharge(Id<ElectricVehicle> evId, Id<Charger> chargerId, double startTime) {
            this.evId = evId;
            this.chargerId = chargerId;
            this.startTime = startTime;
        }
    }
}
