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
    private static final String LAST_ACT_IDENTIFIER = " end";
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

            if (!costOnly) {

                // punish soc below threshold
                double rangeAnxietyThreshold = Double.parseDouble(person.getAttributes().getAttribute("rangeAnxietyThreshold").toString());
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

                // punish difference between end soc and start soc to get realistic soc distribution
                if (activityType.contains(LAST_ACT_IDENTIFIER)) {
                    if (activityType.contains(CHARGING_IDENTIFIER)) {
                        // Todo: Check whether this can be replaced by an estimation regarding how high the soc would have been if charging finished.
                        // This is a workaround
                        soc = 1;
                    }
                    // Calculate SOC difference
                    Double soc_diff =  soc - chargingBehaviourScoringEvent.getStartSoc();
                    if(soc_diff<=0){
                        // Only punish soc difference if SOC is smaller than at the beginning of the cycle.
                        double delta_score = params.marginalUtilityOfSocDifference * Math.abs(soc_diff);
                        chargingBehaviorScoresCollector.addScoringComponentValue(ScoreComponents.ENERGY_BALANCE, delta_score);
                        score += delta_score;
                    } else
                    {
                        chargingBehaviorScoresCollector.addScoringComponentValue(ScoreComponents.ENERGY_BALANCE, 0);
                    }
                    chargingBehaviorScoresCollector.addScoringPerson(ScoreComponents.ENERGY_BALANCE, person.getId());
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

                // Effective βMoney = config-level βMoney * technical scaling factor
                double effectiveBetaMoney = params.betaMoney * params.alphaScaleCost;

                if (unitPricePerKWh > 0.0 && effectiveBetaMoney != 0.0) {
                    double touMultiplier = 1.0;
                    if ("home".equalsIgnoreCase(chargerType)) {
                        Double pricingTime = chargingBehaviourScoringEvent.getPricingTime();
                        double tForPricing = (pricingTime != null) ? pricingTime : event.getTime();
                        touMultiplier = ChargingCostUtils.getHourlyCostMultiplier(tForPricing);
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
