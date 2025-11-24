package se.urbanEV.scoring;

import se.urbanEV.config.UrbanEVConfigGroup;
import org.matsim.api.core.v01.Scenario;
import org.matsim.core.api.internal.MatsimParameters;

public class ChargingBehaviourScoringParameters implements MatsimParameters {

    public final double marginalUtilityOfRangeAnxiety_soc;
    public final double utilityOfEmptyBattery;
    public final double marginalUtilityOfWalking_m;
    public final double utilityOfHomeCharging;
    public final double marginalUtilityOfSocDifference;

    //added spatio-temporal components for charging costs- OmkarP.(2025)
    public final double betaMoney;
    public final double homeChargingCost;
    public final double workChargingCost;
    public final double publicChargingCost;
    public final double alphaScaleCost;   // cost scaling

    private ChargingBehaviourScoringParameters(
            final double marginalUtilityOfRangeAnxiety_soc,
            final double utilityOfEmptyBattery,
            final double marginalUtilityOfWalking_m,
            final double utilityOfHomeCharging,
            final double marginalUtilityOfSocDifference,

            final double betaMoney,
            final double alphaScaleCost,
            final double homeChargingCost,
            final double workChargingCost,
            final double publicChargingCost) {
        this.marginalUtilityOfRangeAnxiety_soc = marginalUtilityOfRangeAnxiety_soc;
        this.utilityOfEmptyBattery = utilityOfEmptyBattery;
        this.marginalUtilityOfWalking_m = marginalUtilityOfWalking_m;
        this.utilityOfHomeCharging = utilityOfHomeCharging;
        this.marginalUtilityOfSocDifference = marginalUtilityOfSocDifference;

        this.betaMoney = betaMoney;
        this.alphaScaleCost = alphaScaleCost;
        this.homeChargingCost = homeChargingCost;
        this.workChargingCost = workChargingCost;
        this.publicChargingCost = publicChargingCost;
    }

    public static final class Builder {
        private double marginalUtilityOfRangeAnxiety_soc;
        private double utilityOfEmptyBattery;
        private double marginalUtilityOfWalking_m;
        private double utilityOfHomeCharging;
        private double marginalUtilityOfSocDifference;

        private double betaMoney;
        private double alphaScaleCost;
        private double homeChargingCost;
        private double workChargingCost;
        private double publicChargingCost;

        public Builder(final Scenario scenario) {
            this((UrbanEVConfigGroup) scenario.getConfig().getModules().get(UrbanEVConfigGroup.GROUP_NAME));
        }

        public Builder(final UrbanEVConfigGroup configGroup) {
            marginalUtilityOfRangeAnxiety_soc = configGroup.getRangeAnxietyUtility();
            utilityOfEmptyBattery = configGroup.getEmptyBatteryUtility();
            marginalUtilityOfWalking_m = configGroup.getWalkingUtility();
            utilityOfHomeCharging = configGroup.getHomeChargingUtility();
            marginalUtilityOfSocDifference = configGroup.getSocDifferenceUtility();

            // Cost and ToU-related parameters: OmkarP.(2025)
            betaMoney = configGroup.getBetaMoney();
            alphaScaleCost = configGroup.getAlphaScaleCost();
            homeChargingCost = configGroup.getHomeChargingCost();
            workChargingCost = configGroup.getWorkChargingCost();
            publicChargingCost = configGroup.getPublicChargingCost();
        }

        public ChargingBehaviourScoringParameters build() {
            return new ChargingBehaviourScoringParameters(
                    marginalUtilityOfRangeAnxiety_soc,
                    utilityOfEmptyBattery,
                    marginalUtilityOfWalking_m,
                    utilityOfHomeCharging,
                    marginalUtilityOfSocDifference,

                    betaMoney,
                    alphaScaleCost,
                    homeChargingCost,
                    workChargingCost,
                    publicChargingCost
            );
        }
    }
}
