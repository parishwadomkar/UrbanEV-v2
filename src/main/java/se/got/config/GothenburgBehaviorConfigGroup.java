package se.got.config;

import org.matsim.core.config.ReflectiveConfigGroup;

public class GothenburgBehaviorConfigGroup extends ReflectiveConfigGroup {
    public static final String GROUP_NAME = "gothenburg_behavior";

    @Parameter
    private double defaultMinimumSoc = 0.20;

    @Parameter
    private double defaultMinimumEndSoc = 0.25;

    @Parameter
    private double defaultTargetSoc = 0.80;

    @Parameter
    private double defaultMaximumSoc = 0.80;

    @Parameter
    private double zeroSocPenalty = -100.0;

    @Parameter
    private double belowMinimumSocPenalty = -12.0;

    @Parameter
    private double belowMinimumEndSocPenalty = -16.0;

    @Parameter
    private double targetSocPenalty = -4.0;

    @Parameter
    private double chargingStartPenalty = -1.0;

    public GothenburgBehaviorConfigGroup() {
        super(GROUP_NAME);
    }

    public double getDefaultMinimumSoc() {
        return defaultMinimumSoc;
    }

    public double getDefaultMinimumEndSoc() {
        return defaultMinimumEndSoc;
    }

    public double getDefaultTargetSoc() {
        return defaultTargetSoc;
    }

    public double getDefaultMaximumSoc() {
        return defaultMaximumSoc;
    }

    public double getZeroSocPenalty() {
        return zeroSocPenalty;
    }

    public double getBelowMinimumSocPenalty() {
        return belowMinimumSocPenalty;
    }

    public double getBelowMinimumEndSocPenalty() {
        return belowMinimumEndSocPenalty;
    }

    public double getTargetSocPenalty() {
        return targetSocPenalty;
    }

    public double getChargingStartPenalty() {
        return chargingStartPenalty;
    }
}
