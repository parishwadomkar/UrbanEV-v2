package se.urbanEV.pv;

import org.apache.log4j.Logger;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.events.VehicleEntersTrafficEvent;
import org.matsim.api.core.v01.events.VehicleLeavesTrafficEvent;
import org.matsim.api.core.v01.events.handler.VehicleEntersTrafficEventHandler;
import org.matsim.api.core.v01.events.handler.VehicleLeavesTrafficEventHandler;
import org.matsim.contrib.ev.MobsimScopeEventHandler;
import org.matsim.core.api.experimental.events.EventsManager;
import org.matsim.core.config.Config;
import org.matsim.core.controler.IterationCounter;
import org.matsim.core.mobsim.framework.events.MobsimAfterSimStepEvent;
import org.matsim.core.mobsim.framework.events.MobsimBeforeCleanupEvent;
import org.matsim.core.mobsim.framework.listeners.MobsimAfterSimStepListener;
import org.matsim.core.mobsim.framework.listeners.MobsimBeforeCleanupListener;
import se.urbanEV.MobsimScopeEventHandling;
import se.urbanEV.config.UrbanEVConfigGroup;
import se.urbanEV.fleet.ElectricFleet;
import se.urbanEV.fleet.ElectricVehicle;

import javax.inject.Inject;
import javax.inject.Singleton;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * Vehicle Integrated Photovoltaic (VIPV)
 * created by OmkarP.(2026)
 *
 * Revision (2026): generation is integrated analytically at vehicle-state
 * transitions and immediately before grid-charging updates.  The QSim-step
 * callback now performs only constant-time initialization/finalization checks;
 * it no longer scans every VIPV vehicle every simulation second.
 */
@Singleton
public final class PvGenerationHandler implements
        MobsimAfterSimStepListener,
        MobsimBeforeCleanupListener,
        VehicleEntersTrafficEventHandler,
        VehicleLeavesTrafficEventHandler,
        MobsimScopeEventHandler {

    private static final Logger log = Logger.getLogger(PvGenerationHandler.class);
    private static final double J_PER_KWH = 3_600_000.0;
    private static final double EPS_TIME = 1e-9;

    private final ElectricFleet fleet;
    private final UrbanEVConfigGroup cfg;
    private final PvVehicleRegistry registry;
    private final EventsManager eventsManager;
    private final double endTime_s;
    private final long globalSeed;
    private final int iteration;

    private final Map<Id<ElectricVehicle>, ExposureState> exposureState = new HashMap<>();
    private final Map<Id<ElectricVehicle>, Integer> parkingEpisode = new HashMap<>();
    private final Map<Id<ElectricVehicle>, Double> lastUpdateTime = new HashMap<>();
    private final Map<Id<ElectricVehicle>, OpenSession> open = new HashMap<>();

    private boolean finalized;
    private boolean initialized;

    @Inject
    public PvGenerationHandler(
            ElectricFleet fleet,
            UrbanEVConfigGroup cfg,
            PvVehicleRegistry registry,
            EventsManager eventsManager,
            Config config,
            IterationCounter iterationCounter,
            MobsimScopeEventHandling mobsimScope) {
        this.fleet = fleet;
        this.cfg = cfg;
        this.registry = registry;
        this.eventsManager = eventsManager;
        this.endTime_s = config.qsim().getEndTime().seconds();
        this.globalSeed = config.global().getRandomSeed();
        this.iteration = iterationCounter.getIterationNumber();
        mobsimScope.addMobsimScopeHandler(this);
    }

    @Override
    public void handleEvent(VehicleEntersTrafficEvent event) {
        Id<ElectricVehicle> evId = Id.create(event.getVehicleId().toString(), ElectricVehicle.class);
        if (!registry.hasPv(evId)) return;
        ensureInitialized();
        changeExposureState(evId, ExposureState.DRIVING, event.getTime());
    }

    @Override
    public void handleEvent(VehicleLeavesTrafficEvent event) {
        Id<ElectricVehicle> evId = Id.create(event.getVehicleId().toString(), ElectricVehicle.class);
        if (!registry.hasPv(evId)) return;
        ensureInitialized();

        int episode = parkingEpisode.merge(evId, 1, Integer::sum);
        boolean openThisStop = PvRandomUtils.parkingIsOpen(
                cfg.getPvParkedOpenShare(),
                globalSeed,
                iteration,
                evId.toString(),
                episode);
        changeExposureState(
                evId,
                openThisStop ? ExposureState.PARKED_OPEN : ExposureState.PARKED_CLOSED,
                event.getTime());
    }

    /**
     * Synchronizes VIPV generation for vehicles that are about to receive
     * charger/grid energy.  This preserves battery-headroom competition
     * between simultaneous VIPV and plug-in charging without a full-fleet loop.
     */
    public void integrateVehiclesTo(Collection<ElectricVehicle> vehicles, double time) {
        if (vehicles == null || vehicles.isEmpty() || cfg.getPvWp() <= 0.0) return;
        ensureInitialized();
        for (ElectricVehicle ev : vehicles) {
            integrateVehicleTo(ev, time);
        }
    }

    /** Synchronizes one vehicle before another component changes its battery. */
    public void integrateVehicleTo(ElectricVehicle ev, double time) {
        if (ev != null && cfg.getPvWp() > 0.0 && registry.hasPv(ev.getId())) {
            ensureInitialized();
            integrateVehicleTo(ev.getId(), time);
        }
    }

    @Override
    public void notifyMobsimAfterSimStep(MobsimAfterSimStepEvent event) {
        ensureInitialized();
        double now = event.getSimulationTime();
        if (!finalized && Double.isFinite(endTime_s) && now >= endTime_s) {
            finalizeAtHorizon();
        }
    }

    @Override
    public void notifyMobsimBeforeCleanup(MobsimBeforeCleanupEvent event) {
        if (!finalized && Double.isFinite(endTime_s)) {
            finalizeAtHorizon();
        }
    }

    /**
     * Integrates all remaining VIPV production to the configured QSim horizon.
     * The method is idempotent so terminal SoC scoring can request a fully
     * synchronized battery state before emitting its final scoring events.
     */
    public void finalizeAtHorizon() {
        if (finalized || !Double.isFinite(endTime_s)) {
            return;
        }
        finalizeAt(endTime_s);
    }

    private void ensureInitialized() {
        if (initialized) return;

        List<Id<ElectricVehicle>> ids = sortedPvVehicleIds();
        for (Id<ElectricVehicle> evId : ids) {
            boolean openInitially = PvRandomUtils.parkingIsOpen(
                    cfg.getPvParkedOpenShare(),
                    globalSeed,
                    iteration,
                    evId.toString(),
                    0);
            exposureState.put(
                    evId,
                    openInitially ? ExposureState.PARKED_OPEN : ExposureState.PARKED_CLOSED);
            parkingEpisode.put(evId, 0);
            lastUpdateTime.put(evId, 0.0);
        }
        initialized = true;
        log.info("PV generation state initialized deterministically for " + ids.size()
                + " vehicles at iteration " + iteration + ".");
    }

    private List<Id<ElectricVehicle>> sortedPvVehicleIds() {
        List<Id<ElectricVehicle>> ids = new ArrayList<>(registry.getPvVehicles());
        ids.sort(Comparator.comparing(Id::toString));
        return ids;
    }

    private void changeExposureState(
            Id<ElectricVehicle> evId,
            ExposureState newState,
            double time) {

        ExposureState oldState = exposureState.getOrDefault(evId, ExposureState.PARKED_CLOSED);
        integrateVehicleTo(evId, time);

        if (!Objects.equals(oldState.mode, newState.mode)) {
            ElectricVehicle ev = fleet.getElectricVehicles().get(evId);
            if (ev != null) closeIfOpen(evId, time, time, ev);
        }
        exposureState.put(evId, newState);
    }

    private void integrateVehicleTo(Id<ElectricVehicle> evId, double targetTime) {
        if (!Double.isFinite(targetTime)) {
            throw new IllegalArgumentException("VIPV integration target time is not finite: " + targetTime);
        }

        double startTime = lastUpdateTime.getOrDefault(evId, 0.0);
        if (targetTime <= startTime + EPS_TIME) return;

        ElectricVehicle ev = fleet.getElectricVehicles().get(evId);
        if (ev == null) {
            throw new IllegalStateException("VIPV vehicle is absent from electric fleet: " + evId);
        }

        ExposureState state = exposureState.getOrDefault(evId, ExposureState.PARKED_CLOSED);
        String mode = state.mode;
        double cursor = startTime;

        while (cursor < targetTime - EPS_TIME) {
            double nextHourBoundary = (Math.floor(cursor / 3600.0) + 1.0) * 3600.0;
            double intervalEnd = Math.min(targetTime, nextHourBoundary);
            double dt = intervalEnd - cursor;

            double factor = mode == null ? 0.0 : PvPotentialUtils.getPotentialFactor(cursor, cfg);
            if (factor > 0.0 && dt > 0.0) {
                addGeneration(
                        evId,
                        ev,
                        cursor,
                        mode,
                        cfg.getPvWp() * factor * dt,
                        targetTime);
            } else {
                closeIfOpen(evId, cursor, targetTime, ev);
            }
            cursor = intervalEnd;
        }

        lastUpdateTime.put(evId, targetTime);
    }

    private void addGeneration(
            Id<ElectricVehicle> evId,
            ElectricVehicle ev,
            double intervalStart,
            String mode,
            double producedJ,
            double dispatchTime) {

        if (!Double.isFinite(producedJ) || producedJ < 0.0) {
            throw new IllegalStateException("Invalid VIPV energy for EV " + evId + ": " + producedJ);
        }

        double soc0 = ev.getBattery().getSoc();
        ev.getBattery().changeSoc(producedJ);
        double soc1 = ev.getBattery().getSoc();
        double storedJ = Math.max(0.0, soc1 - soc0);
        double wastedJ = Math.max(0.0, producedJ - storedJ);

        OpenSession session = open.get(evId);
        if (session == null || !session.mode.equals(mode)) {
            if (session != null) closeIfOpen(evId, intervalStart, dispatchTime, ev);
            session = new OpenSession(intervalStart, mode, soc0);
            open.put(evId, session);
        }
        session.producedJ += producedJ;
        session.storedJ += storedJ;
        session.wastedJ += wastedJ;
    }

    private void finalizeAt(double time) {
        ensureInitialized();
        for (Id<ElectricVehicle> evId : sortedPvVehicleIds()) {
            integrateVehicleTo(evId, time);
            ElectricVehicle ev = fleet.getElectricVehicles().get(evId);
            if (ev != null) closeIfOpen(evId, time, time, ev);
        }
        finalized = true;
    }

    private void closeIfOpen(
            Id<ElectricVehicle> evId,
            double intervalEndTime,
            double dispatchTime,
            ElectricVehicle ev) {

        OpenSession session = open.remove(evId);
        if (session == null) return;

        if (!Double.isFinite(intervalEndTime)
                || !Double.isFinite(dispatchTime)
                || dispatchTime + EPS_TIME < intervalEndTime) {
            throw new IllegalStateException(
                    "Invalid VIPV interval/dispatch times for EV " + evId
                            + ": intervalEnd=" + intervalEndTime
                            + ", dispatchTime=" + dispatchTime);
        }

        double cap = ev.getBattery().getCapacity();
        double startSocFrac = cap > 0.0 ? session.startSocJ / cap : 0.0;
        double endSocFrac = cap > 0.0 ? ev.getBattery().getSoc() / cap : 0.0;
        double producedKWh = session.producedJ / J_PER_KWH;
        double storedKWh = session.storedJ / J_PER_KWH;
        double wastedKWh = session.wastedJ / J_PER_KWH;

        // Revision (2026): analytical integration may discover that a physical
        // interval ended at an earlier hourly boundary.  MATSim events cannot be
        // inserted behind the event currently being processed with that earlier
        // timestamp, because SimStepParallelEventsManager then terminates with a
        // chronological-order error and reports a secondary BrokenBarrierException.
        // Preserve the physical boundary in intervalEndTime, but dispatch the
        // event at the current synchronization time.
        eventsManager.processEvent(new PvChargingIntervalEvent(
                dispatchTime,
                evId.toString(),
                session.startTime,
                intervalEndTime,
                session.mode,
                producedKWh,
                storedKWh,
                wastedKWh,
                startSocFrac,
                endSocFrac
        ));
    }

    @Override
    public void reset(int iteration) {
        exposureState.clear();
        parkingEpisode.clear();
        lastUpdateTime.clear();
        open.clear();
        finalized = false;
        initialized = false;
    }

    private enum ExposureState {
        DRIVING("DRIVING"),
        PARKED_OPEN("PARKED_OPEN"),
        PARKED_CLOSED(null);

        private final String mode;

        ExposureState(String mode) {
            this.mode = mode;
        }
    }

    private static final class OpenSession {
        private final double startTime;
        private final String mode;
        private final double startSocJ;
        private double producedJ;
        private double storedJ;
        private double wastedJ;

        private OpenSession(double startTime, String mode, double startSocJ) {
            this.startTime = startTime;
            this.mode = mode;
            this.startSocJ = startSocJ;
        }
    }
}
