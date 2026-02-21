package se.urbanEV.charging;

import se.urbanEV.config.UrbanEVConfigGroup;

public final class ChargingCostUtils {

    private ChargingCostUtils() {}

    /**
     * Developed by omkarp, 2026
     * Returns the hourly ToU multiplier M_temporal(t) for a given simulation time.
     * @param timeSeconds simulation time in seconds (MATSim)
     * @return multiplier (dimensionless)
     */
    // Hourly multipliers [0..23]
    private static final double[] TOU_SPRING = {
            0.5, 0.5, 0.5, 0.5, 0.5, 0.5,
            1.0, 1.5, 1.6, 1.6, 1.0, 1.0,
            0.7, 0.7, 0.7, 0.7, 1.0, 1.4,
            1.4, 1.4, 1.4, 1.4, 0.8, 0.8
    };

    private static final double[] TOU_SUMMER = {
            0.8, 0.8, 0.8, 0.8, 0.8, 1.0,
            1.0, 1.0, 1.15, 1.15, 0.9, 0.9,
            0.9, 0.9, 0.9, 0.9, 0.9, 1.2,
            1.2, 1.2, 1.0, 1.0, 0.8, 0.8
    };

    private static final double[] TOU_AUTUMN = {
            0.60, 0.60, 0.60, 0.60, 0.60, 0.60,
            1.00, 1.00, 1.60, 1.60, 1.60, 0.90,
            0.90, 0.90, 0.90, 1.00, 1.00, 1.00,
            1.00, 1.00, 1.00, 0.80, 0.80, 0.80
    };

    private static final double[] TOU_WINTER = {
            0.80, 0.80, 0.80, 0.80, 0.80, 0.80,
            1.00, 1.00, 1.40, 1.40, 1.40, 1.40,
            1.00, 1.00, 1.00, 1.00, 1.20, 1.20,
            1.20, 1.20, 0.80, 0.80, 0.80, 0.80
    };

    /** Backward-compatible default: SUMMER if cfg is not provided. */
    public static double getHourlyCostMultiplier(double timeSeconds) {
        return getHourlyCostMultiplier(timeSeconds, null);
    }

    public static double getHourlyCostMultiplier(double timeSeconds, UrbanEVConfigGroup cfg) {
        int hour = hourOfDay(timeSeconds);

        UrbanEVConfigGroup.Season season =
                (cfg != null && cfg.getSeason() != null) ? cfg.getSeason() : UrbanEVConfigGroup.Season.SUMMER;

        double m;
        switch (season) {
            case WINTER:
                m = TOU_WINTER[hour];
                break;
            case AUTUMN:
                m = TOU_AUTUMN[hour];
                break;
            case SPRING:
                m = TOU_SPRING[hour];
                break;
            case SUMMER:
            default:
                m = TOU_SUMMER[hour];
                break;
        }

        if (!Double.isFinite(m)) return 1.0;
        return Math.max(0.0, m);
    }

    private static int hourOfDay(double timeSeconds) {
        int secOfDay = ((int) Math.floor(timeSeconds)) % 86400;
        if (secOfDay < 0) secOfDay += 86400;
        return secOfDay / 3600;
    }
}
