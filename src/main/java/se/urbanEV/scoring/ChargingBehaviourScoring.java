package se.urbanEV.scoring;

import com.google.inject.Inject;
import se.urbanEV.stats.ChargingBehaviorScoresCollector;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.scoring.SumScoringFunction;
import se.urbanEV.charging.ChargingCostUtils;

public class ChargingBehaviourScoring implements SumScoringFunction.ArbitraryEventScoring {

    public enum ScoreComponents {
        RANGE_ANXIETY,
        EMPTY_BATTERY,
        WALKING_DISTANCE,
        HOME_CHARGING,
        ENERGY_BALANCE,
        CHARGING_COST   // OmkarP.(2025): cost term from charging prices
    }

    private double score;
    private static final String CHARGING_IDENTIFIER = " charging";
    private ChargingBehaviorScoresCollector chargingBehaviorScoresCollector = ChargingBehaviorScoresCollector.getInstance();

    final ChargingBehaviourScoringParameters params;
    Person person;

    @Inject
    public ChargingBehaviourScoring(final ChargingBehaviourScoringParameters params, Person person) {
        this.params = params;
        this.person = person;
    }

    @Override
    public void handleEvent(Event event) {
        if (event.getEventType().equals("scoring")) {
            ChargingBehaviourScoringEvent chargingBehaviourScoringEvent = (ChargingBehaviourScoringEvent) event;

            boolean costOnly = chargingBehaviourScoringEvent.isCostOnly();
            double soc = chargingBehaviourScoringEvent.getSoc();
            String activityType = chargingBehaviourScoringEvent.getActivityType();

            // Revision (2026): score the actual battery state after all charging,
            // discharging and VIPV processing at the QSim horizon.  The previous
            // "activity type contains end" convention was not present in the
            // Gothenburg plans, leaving socDifferenceUtility completely inactive.
            if (chargingBehaviourScoringEvent.isTerminalSocOnly()) {
                double startSoc = chargingBehaviourScoringEvent.getStartSoc();
                double deficit = Math.max(0.0, startSoc - soc);
                double deltaScore = params.marginalUtilityOfSocDifference * deficit;
                chargingBehaviorScoresCollector.addScoringComponentValue(
                        ScoreComponents.ENERGY_BALANCE, deltaScore);
                chargingBehaviorScoresCollector.addScoringPerson(
                        ScoreComponents.ENERGY_BALANCE, person.getId());
                score += deltaScore;
                return;
            }

            if (!costOnly) {

                // punish soc below threshold
                Object thrObj = person.getAttributes().getAttribute("rangeAnxietyThreshold");
                double rangeAnxietyThreshold = (thrObj != null)
                        ? Double.parseDouble(thrObj.toString())
                        : params.defaultRangeAnxietyThreshold;

                if (soc > 0 && soc < rangeAnxietyThreshold) {
                    double delta_score = params.marginalUtilityOfRangeAnxiety_soc * (rangeAnxietyThreshold - soc) / rangeAnxietyThreshold;
                    chargingBehaviorScoresCollector.addScoringComponentValue(ScoreComponents.RANGE_ANXIETY, delta_score);
                    chargingBehaviorScoresCollector.addScoringPerson(ScoreComponents.RANGE_ANXIETY, person.getId());
                    score += delta_score;
                }

                // severely punish empty battery
                if (soc == 0) {
                    double delta_score = params.utilityOfEmptyBattery;
                    chargingBehaviorScoresCollector.addScoringComponentValue(ScoreComponents.EMPTY_BATTERY, delta_score);
                    chargingBehaviorScoresCollector.addScoringPerson(ScoreComponents.EMPTY_BATTERY, person.getId());
                    score += delta_score;
                }

                // punish walking distance (only when charging)
                double walkingDistance = chargingBehaviourScoringEvent.getWalkingDistance();
                if (activityType.contains(CHARGING_IDENTIFIER)) {
                    // inverted utility based on Geurs, van Wee 2004 Equation (1)
                    double beta = 0.005;
                    double delta_score = params.marginalUtilityOfWalking_m * (1 - Math.exp(-beta * walkingDistance));
                    chargingBehaviorScoresCollector.addScoringComponentValue(ScoreComponents.WALKING_DISTANCE, delta_score);
                    chargingBehaviorScoresCollector.addScoringPerson(ScoreComponents.WALKING_DISTANCE, person.getId());
                    score += delta_score;
                }

                // reward charging at home
                boolean hasChargerAtHome = person.getAttributes().getAttribute("homeChargerPower") != null;
                if (activityType.equals("home" + CHARGING_IDENTIFIER) && hasChargerAtHome) {
                    double delta_score = params.utilityOfHomeCharging;
                    chargingBehaviorScoresCollector.addScoringComponentValue(ScoreComponents.HOME_CHARGING, delta_score);
                    chargingBehaviorScoresCollector.addScoringPerson(ScoreComponents.HOME_CHARGING, person.getId());
                    score += delta_score;
                }

            }


            // OmkarP.(2025): charging cost (price * ToU multiplier * betaMoney * etc.)
            Double energyChargedKWh = chargingBehaviourScoringEvent.getEnergyChargedKWh();
            String chargerType = chargingBehaviourScoringEvent.getChargerType();

            if (energyChargedKWh != null && energyChargedKWh > 0.0 && chargerType != null) {
                double unitPricePerKWh;
                switch (chargerType) {
                    case "home":
                        unitPricePerKWh = params.homeChargingCost;
                        break;
                    case "work":
                        unitPricePerKWh = params.workChargingCost;
                        break;
                    case "public":
                        unitPricePerKWh = params.publicChargingCost;
                        break;
                    default:
                        unitPricePerKWh = 0.0;
                }

                double effectiveBetaMoney = params.betaMoney * params.alphaScaleCost;
                if (unitPricePerKWh > 0.0 && effectiveBetaMoney != 0.0) {
                    double touMultiplier = 1.0;
                    if ("home".equalsIgnoreCase(chargerType)) {
                        Double pricingTime = chargingBehaviourScoringEvent.getPricingTime();
                        double tForPricing = (pricingTime != null) ? pricingTime : event.getTime();

                        // Revision (2026): the cost event now carries measured grid energy
                        // and the real session start time.  Price the actual interval instead
                        // of reconstructing a duration from energy and nominal charger power.
                        touMultiplier = ChargingCostUtils.getAverageTouMultiplier(
                                tForPricing,
                                event.getTime(),
                                chargerType,
                                params.season
                        );
                    }

                    double baseChargingCost = energyChargedKWh * unitPricePerKWh * touMultiplier;
                    double delta_score = effectiveBetaMoney * baseChargingCost;
                    chargingBehaviorScoresCollector.addScoringComponentValue(ScoreComponents.CHARGING_COST, delta_score);
                    chargingBehaviorScoresCollector.addScoringPerson(ScoreComponents.CHARGING_COST, person.getId());
                    score += delta_score;
                }
            }
        }
    }

    @Override public void finish() {}

    @Override
    public double getScore() {
        return score;
    }
}
