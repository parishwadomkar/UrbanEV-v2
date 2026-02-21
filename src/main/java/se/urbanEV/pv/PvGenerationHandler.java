package se.urbanEV.pv;

import org.apache.log4j.Logger;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.events.VehicleEntersTrafficEvent;
import org.matsim.api.core.v01.events.VehicleLeavesTrafficEvent;
import org.matsim.api.core.v01.events.handler.VehicleEntersTrafficEventHandler;
import org.matsim.api.core.v01.events.handler.VehicleLeavesTrafficEventHandler;
import org.matsim.core.api.experimental.events.EventsManager;
import org.matsim.core.config.Config;
import org.matsim.core.gbl.MatsimRandom;
import org.matsim.core.mobsim.framework.events.MobsimAfterSimStepEvent;
import org.matsim.core.mobsim.framework.listeners.MobsimAfterSimStepListener;
import org.matsim.contrib.ev.MobsimScopeEventHandler;
import se.urbanEV.MobsimScopeEventHandling;
import se.urbanEV.config.UrbanEVConfigGroup;
import se.urbanEV.fleet.ElectricFleet;
import se.urbanEV.fleet.ElectricVehicle;
import javax.inject.Inject;
import java.util.HashMap;
import java.util.Map;
import java.util.Random;

/**
 * Vehicle Integrated Photovoltaic (VIPV)
 * created by OmkarP.(2026)
 */
public final class PvGenerationHandler implements
        MobsimAfterSimStepListener,
        VehicleEntersTrafficEventHandler,
        VehicleLeavesTrafficEventHandler,
        MobsimScopeEventHandler {

    private static final Logger log = Logger.getLogger(PvGenerationHandler.class);

    private static final double J_PER_KWH = 3_600_000.0;
    private final ElectricFleet fleet;
    private final UrbanEVConfigGroup cfg;
    private final PvVehicleRegistry registry;
    private final EventsManager eventsManager;
    private final double endTime_s;
    private final Random rnd;
    private final Map<Id<ElectricVehicle>, Boolean> isDriving = new HashMap<>();
    private final Map<Id<ElectricVehicle>, Boolean> parkedOpenEpisode = new HashMap<>();
    private final Map<Id<ElectricVehicle>, OpenSession> open = new HashMap<>();
    private double lastTime = Double.NaN;
    private boolean finalized = false;
    private boolean initDone = false;

    @Inject
    public PvGenerationHandler(
            ElectricFleet fleet,
            UrbanEVConfigGroup cfg,
            PvVehicleRegistry registry,
            EventsManager eventsManager,
            Config config,
            MobsimScopeEventHandling mobsimScope
    ) {
        this.fleet = fleet;
        this.cfg = cfg;
        this.registry = registry;
        this.eventsManager = eventsManager;
        this.endTime_s = config.qsim().getEndTime().seconds();
        this.rnd = MatsimRandom.getRandom();
        mobsimScope.addMobsimScopeHandler(this);
    }

    @Override
    public void handleEvent(VehicleEntersTrafficEvent event) {
        Id<ElectricVehicle> evId = Id.create(event.getVehicleId().toString(), ElectricVehicle.class);
        if (!registry.hasPv(evId)) return;
        isDriving.put(evId, true);
        parkedOpenEpisode.remove(evId);
    }

    @Override
    public void handleEvent(VehicleLeavesTrafficEvent event) {
        Id<ElectricVehicle> evId = Id.create(event.getVehicleId().toString(), ElectricVehicle.class);
        if (!registry.hasPv(evId)) return;
        isDriving.put(evId, false);
        double p = cfg.getPvParkedOpenShare();
        boolean openThisStop = p > 0.0 && (p >= 1.0 || rnd.nextDouble() < p);
        parkedOpenEpisode.put(evId, openThisStop);
    }

    @Override
    public void notifyMobsimAfterSimStep(MobsimAfterSimStepEvent e) {
        double now = e.getSimulationTime();
        if (!Double.isFinite(lastTime)) {
            lastTime = now;
            initInitialParkingEpisodesIfNeeded();
            return;
        }

        double dt = now - lastTime;
        if (dt <= 0.0) {
            lastTime = now;
            return;
        }
        lastTime = now;

        double pvWp = cfg.getPvWp();
        if (pvWp <= 0.0) return;

        for (Id<ElectricVehicle> evId : registry.getPvVehicles()) {
            ElectricVehicle ev = fleet.getElectricVehicles().get(evId);
            if (ev == null) continue;
            boolean driving = isDriving.getOrDefault(evId, false);
            boolean parkedOpen = parkedOpenEpisode.getOrDefault(evId, false);
            boolean active = driving || parkedOpen;

            if (!active) {
                closeIfOpen(evId, now, ev);
                continue;
            }

            String mode = driving ? "DRIVING" : "PARKED_OPEN";
            double pf = PvPotentialUtils.getPotentialFactor(now, cfg);
            if (pf <= 0.0) {
                closeIfOpen(evId, now, ev);
                continue;
            }

            double powerW = pvWp * pf;
            double producedJ = powerW * dt;
            double soc0 = ev.getBattery().getSoc();
            ev.getBattery().changeSoc(+producedJ);
            double soc1 = ev.getBattery().getSoc();
            double storedJ = Math.max(0.0, soc1 - soc0);
            double wastedJ = Math.max(0.0, producedJ - storedJ);

            OpenSession s = open.get(evId);
            if (s == null || !s.mode.equals(mode)) {
                if (s != null) closeIfOpen(evId, now, ev);
                s = new OpenSession(now - dt, mode, soc0);
                open.put(evId, s);
            }
            s.producedJ += producedJ;
            s.storedJ += storedJ;
            s.wastedJ += wastedJ;
        }

        if (!finalized && Double.isFinite(endTime_s) && now >= endTime_s) {
            finalized = true;
            for (Map.Entry<Id<ElectricVehicle>, OpenSession> it : new HashMap<>(open).entrySet()) {
                Id<ElectricVehicle> evId = it.getKey();
                ElectricVehicle ev = fleet.getElectricVehicles().get(evId);
                if (ev != null) closeIfOpen(evId, now, ev);
                else open.remove(evId);
            }
        }
    }

    private void initInitialParkingEpisodesIfNeeded() {
        if (initDone) return;
        double p = cfg.getPvParkedOpenShare();
        if (p <= 0.0) {
            initDone = true;
            return;
        }
        for (Id<ElectricVehicle> evId : registry.getPvVehicles()) {
            // assume parked until first enters-traffic event arrives
            boolean openThisStop = (p >= 1.0) || (rnd.nextDouble() < p);
            parkedOpenEpisode.put(evId, openThisStop);
        }
        initDone = true;
    }

    private void closeIfOpen(Id<ElectricVehicle> evId, double endTime, ElectricVehicle ev) {
        OpenSession s = open.remove(evId);
        if (s == null) return;
        double cap = ev.getBattery().getCapacity();
        double startSocFrac = cap > 0.0 ? s.startSocJ / cap : 0.0;
        double endSocFrac = cap > 0.0 ? ev.getBattery().getSoc() / cap : 0.0;
        double producedKWh = s.producedJ / J_PER_KWH;
        double storedKWh = s.storedJ / J_PER_KWH;
        double wastedKWh = s.wastedJ / J_PER_KWH;

        eventsManager.processEvent(new PvChargingIntervalEvent(
                endTime,
                evId.toString(),
                s.startTime,
                endTime,
                s.mode,
                producedKWh,
                storedKWh,
                wastedKWh,
                startSocFrac,
                endSocFrac
        ));
    }

    private static final class OpenSession {
        final double startTime;
        final String mode;
        final double startSocJ;
        double producedJ;
        double storedJ;
        double wastedJ;

        OpenSession(double startTime, String mode, double startSocJ) {
            this.startTime = startTime;
            this.mode = mode;
            this.startSocJ = startSocJ;
        }
    }
}
