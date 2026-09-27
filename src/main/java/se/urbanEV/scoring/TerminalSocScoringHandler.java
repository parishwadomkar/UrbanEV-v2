package se.urbanEV.scoring;

import org.apache.log4j.Logger;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Population;
import org.matsim.core.api.experimental.events.EventsManager;
import org.matsim.core.config.Config;
import org.matsim.core.mobsim.framework.events.MobsimBeforeCleanupEvent;
import org.matsim.core.mobsim.framework.listeners.MobsimBeforeCleanupListener;
import se.urbanEV.charging.ChargingHandler;
import se.urbanEV.fleet.ElectricFleet;
import se.urbanEV.fleet.ElectricVehicle;
import se.urbanEV.pv.PvGenerationHandler;

import javax.inject.Inject;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/**
 * Emits one terminal SoC scoring event per EV after all energy flows have been
 * finalized at the simulation horizon.
 */
public final class TerminalSocScoringHandler implements MobsimBeforeCleanupListener {
    private static final Logger log = Logger.getLogger(TerminalSocScoringHandler.class);

    private final ElectricFleet fleet;
    private final Population population;
    private final EventsManager eventsManager;
    private final ChargingHandler chargingHandler;
    private final PvGenerationHandler pvGenerationHandler;
    private final double horizon_s;
    private boolean emitted;

    @Inject
    public TerminalSocScoringHandler(
            ElectricFleet fleet,
            Population population,
            EventsManager eventsManager,
            ChargingHandler chargingHandler,
            PvGenerationHandler pvGenerationHandler,
            Config config) {
        this.fleet = fleet;
        this.population = population;
        this.eventsManager = eventsManager;
        this.chargingHandler = chargingHandler;
        this.pvGenerationHandler = pvGenerationHandler;
        this.horizon_s = config.qsim().getEndTime().seconds();
    }

    @Override
    public void notifyMobsimBeforeCleanup(MobsimBeforeCleanupEvent event) {
        emitTerminalSocScores();
    }

    /**
     * Finalizes all energy flows and emits the terminal events exactly once.
     * Exposed so the statistics listener can guarantee same-iteration output
     * without depending on QSim listener registration order.
     */
    public void emitTerminalSocScores() {
        if (emitted) {
            return;
        }
        if (!Double.isFinite(horizon_s) || horizon_s <= 0.0) {
            throw new IllegalStateException(
                    "A finite positive qsim endTime is required for terminal SoC scoring.");
        }

        // Ensure terminal scores observe all grid and VIPV energy.  Both calls
        // are idempotent and normally have already completed at the final step.
        chargingHandler.finalizeAtHorizon();
        pvGenerationHandler.finalizeAtHorizon();

        List<ElectricVehicle> vehicles =
                new ArrayList<>(fleet.getElectricVehicles().values());
        vehicles.sort(Comparator.comparing(ev -> ev.getId().toString()));

        int deficitVehicles = 0;
        double startSocSum = 0.0;
        double endSocSum = 0.0;

        for (ElectricVehicle ev : vehicles) {
            Id<Person> personId = Id.create(ev.getId().toString(), Person.class);
            if (!population.getPersons().containsKey(personId)) {
                throw new IllegalStateException(
                        "EV " + ev.getId() + " has no matching person for terminal SoC scoring.");
            }

            double capacity = ev.getBattery().getCapacity();
            if (!Double.isFinite(capacity) || capacity <= 0.0) {
                throw new IllegalStateException(
                        "EV " + ev.getId() + " has invalid battery capacity " + capacity);
            }

            double startSoc = ev.getBattery().getStartSoc() / capacity;
            double endSoc = ev.getBattery().getSoc() / capacity;
            if (endSoc + 1e-12 < startSoc) {
                deficitVehicles++;
            }
            startSocSum += startSoc;
            endSocSum += endSoc;

            eventsManager.processEvent(
                    ChargingBehaviourScoringEvent.terminalSoc(
                            horizon_s, personId, endSoc, startSoc));
        }

        emitted = true;
        int n = vehicles.size();
        log.info(String.format(
                "Terminal SoC scoring: vehicles=%d deficitVehicles=%d meanStartSoc=%.6f meanEndSoc=%.6f",
                n,
                deficitVehicles,
                n == 0 ? 0.0 : startSocSum / n,
                n == 0 ? 0.0 : endSocSum / n));
    }
}
