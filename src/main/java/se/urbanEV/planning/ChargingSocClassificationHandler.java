package se.urbanEV.planning;

import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Population;
import org.matsim.core.config.Config;
import org.matsim.core.controler.IterationCounter;
import se.urbanEV.scoring.ChargingBehaviourScoringEvent;
import se.urbanEV.scoring.ChargingBehaviourScoringEventHandler;

import javax.inject.Inject;
import javax.inject.Singleton;
import java.util.HashSet;
import java.util.Set;

/**
 * Assigns the charging-replanning subpopulation once from the terminal SoC
 * state.  Empty-battery observations remain critical for the current iteration.
 */
@Singleton
public final class ChargingSocClassificationHandler
        implements ChargingBehaviourScoringEventHandler {

    private static final String CRITICAL = "criticalSOC";
    private static final String NON_CRITICAL = "nonCriticalSOC";

    private final Population population;
    private final IterationCounter iterationCounter;
    private final long globalSeed;
    private final Set<Id<Person>> emptyBatteryPersons = new HashSet<>();

    @Inject
    public ChargingSocClassificationHandler(
            Population population,
            IterationCounter iterationCounter,
            Config config) {
        this.population = population;
        this.iterationCounter = iterationCounter;
        this.globalSeed = config.global().getRandomSeed();
    }

    @Override
    public void handleEvent(ChargingBehaviourScoringEvent event) {
        if (event.isCostOnly() || event.getPersonId() == null || event.getSoc() == null) {
            return;
        }

        Id<Person> personId = event.getPersonId();
        Person person = population.getPersons().get(personId);
        if (person == null) {
            return;
        }

        double soc = event.getSoc();
        if (!event.isTerminalSocOnly()) {
            if (soc <= 0.0) {
                emptyBatteryPersons.add(personId);
                person.getAttributes().putAttribute("subpopulation", CRITICAL);
            }
            return;
        }

        Double startSocObject = event.getStartSoc();
        if (startSocObject == null) {
            throw new IllegalStateException(
                    "Terminal SoC event has no start SoC for person " + personId);
        }

        // Preserve the original replanning rule: the probability of being
        // classified as critical follows the absolute start/end SoC change.
        // Only its timing and handler lifetime are corrected here.
        double socDifference = Math.abs(soc - startSocObject);
        boolean critical = emptyBatteryPersons.contains(personId)
                || socDifference > deterministicDraw(
                        globalSeed,
                        iterationCounter.getIterationNumber(),
                        personId.toString());

        person.getAttributes().putAttribute(
                "subpopulation", critical ? CRITICAL : NON_CRITICAL);
    }

    @Override
    public void reset(int iteration) {
        emptyBatteryPersons.clear();
    }

    private static double deterministicDraw(long seed, int iteration, String personId) {
        long mixed = seed ^ 0x9e3779b97f4a7c15L;
        mixed ^= ((long) iteration + 0x9e3779b9L) * 0xbf58476d1ce4e5b9L;
        for (int i = 0; i < personId.length(); i++) {
            mixed ^= personId.charAt(i);
            mixed *= 0x100000001b3L;
        }
        mixed ^= mixed >>> 30;
        mixed *= 0xbf58476d1ce4e5b9L;
        mixed ^= mixed >>> 27;
        mixed *= 0x94d049bb133111ebL;
        mixed ^= mixed >>> 31;
        return (mixed >>> 11) * 0x1.0p-53;
    }
}
