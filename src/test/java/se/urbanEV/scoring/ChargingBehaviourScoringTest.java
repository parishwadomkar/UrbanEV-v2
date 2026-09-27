package se.urbanEV.scoring;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.population.PopulationUtils;
import se.urbanEV.config.UrbanEVConfigGroup;
import se.urbanEV.stats.ChargingBehaviorScoresCollector;

import static org.junit.jupiter.api.Assertions.assertEquals;

class ChargingBehaviourScoringTest {
    private final ChargingBehaviorScoresCollector collector =
            ChargingBehaviorScoresCollector.getInstance();

    @BeforeEach
    void resetBefore() {
        collector.reset();
    }

    @AfterEach
    void resetAfter() {
        collector.reset();
    }

    @Test
    void terminalEventAppliesActualSocDeficitExactlyOnce() {
        UrbanEVConfigGroup config = new UrbanEVConfigGroup();
        config.setSocDifferenceUtility(-10.0);
        ChargingBehaviourScoringParameters parameters =
                new ChargingBehaviourScoringParameters.Builder(config).build();

        Person person = PopulationUtils.getFactory().createPerson(Id.createPersonId("ev-1"));
        ChargingBehaviourScoring scoring =
                new ChargingBehaviourScoring(parameters, person);

        scoring.handleEvent(ChargingBehaviourScoringEvent.terminalSoc(
                604800.0, person.getId(), 0.50, 0.80));

        assertEquals(-3.0, scoring.getScore(), 1e-12);
        assertEquals(-3.0, collector.getComponentSum(
                ChargingBehaviourScoring.ScoreComponents.ENERGY_BALANCE), 1e-12);
        assertEquals(1.0, collector.getNumberOfScoringPersonsForComponent(
                ChargingBehaviourScoring.ScoreComponents.ENERGY_BALANCE), 0.0);
    }

    @Test
    void ordinaryEndNamedActivityDoesNotUsePreChargeSocAsTerminalSoc() {
        UrbanEVConfigGroup config = new UrbanEVConfigGroup();
        config.setSocDifferenceUtility(-10.0);
        ChargingBehaviourScoringParameters parameters =
                new ChargingBehaviourScoringParameters.Builder(config).build();

        Person person = PopulationUtils.getFactory().createPerson(Id.createPersonId("ev-2"));
        ChargingBehaviourScoring scoring =
                new ChargingBehaviourScoring(parameters, person);

        scoring.handleEvent(new ChargingBehaviourScoringEvent(
                600000.0, person.getId(), 0.40, 0.0, "home end charging", 0.80));

        assertEquals(0.0, collector.getNumberOfScoringPersonsForComponent(
                ChargingBehaviourScoring.ScoreComponents.ENERGY_BALANCE), 0.0);
    }
}
