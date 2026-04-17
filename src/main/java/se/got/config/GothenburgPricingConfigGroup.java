package se.got.config;

import org.matsim.core.config.ReflectiveConfigGroup;

public class GothenburgPricingConfigGroup extends ReflectiveConfigGroup {
    public static final String GROUP_NAME = "gothenburg_pricing";

    @Parameter
    private double homeChargingCost = 2.5;

    @Parameter
    private double workChargingCost = 4.0;

    @Parameter
    private double publicChargingCost = 5.5;

    @Parameter
    private double betaMoney = -0.05;

    @Parameter
    private double alphaScaleCost = 1.0;

    @Parameter
    private boolean enableHomeTou = false;

    @Parameter
    private String homeTouMultipliers = "0.7;06:00:00=1.6;08:00:00=1.47;10:00:00=0.92;17:00:00=1.14;20:00:00=1.0;22:00:00=0.7";

    public GothenburgPricingConfigGroup() {
        super(GROUP_NAME);
    }

    public double getHomeChargingCost() {
        return homeChargingCost;
    }

    public double getWorkChargingCost() {
        return workChargingCost;
    }

    public double getPublicChargingCost() {
        return publicChargingCost;
    }

    public double getBetaMoney() {
        return betaMoney;
    }

    public double getAlphaScaleCost() {
        return alphaScaleCost;
    }

    public boolean isEnableHomeTou() {
        return enableHomeTou;
    }

    public String getHomeTouMultipliers() {
        return homeTouMultipliers;
    }
}