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
    public static double getHourlyCostMultiplier(double timeSeconds, UrbanEVConfigGroup cfg) {
        UrbanEVConfigGroup.Season season =
                (cfg != null && cfg.getSeason() != null) ? cfg.getSeason() : UrbanEVConfigGroup.Season.SUMMER;
        return getHourlyCostMultiplier(timeSeconds, season);
    }

    public static double getHourlyCostMultiplier(double timeSeconds, UrbanEVConfigGroup.Season season) {
        int hour = hourOfDay(timeSeconds);

        UrbanEVConfigGroup.Season s =
                (season != null) ? season : UrbanEVConfigGroup.Season.SUMMER;

        double m;
        switch (s) {
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

    public static String getChargerAccessType(String chargerId) {
        if (chargerId == null) {
            return "other";
        }

        String id = chargerId.toLowerCase(java.util.Locale.ROOT);

        if (id.contains("home")) {
            return "home";
        }

        if (id.contains("work")) {
            return "work";
        }

        if (id.contains("public")) {
            return "public";
        }

        return "other";
    }

    public static double getBasePricePerKWh(
            String chargerAccessType,
            UrbanEVConfigGroup cfg) {

        if (cfg == null || chargerAccessType == null) {
            return 0.0;
        }

        switch (chargerAccessType.toLowerCase(java.util.Locale.ROOT)) {
            case "home":
                return Math.max(0.0, cfg.getHomeChargingCost());

            case "work":
                return Math.max(0.0, cfg.getWorkChargingCost());

            case "public":
                return Math.max(0.0, cfg.getPublicChargingCost());

            default:
                return 0.0;
        }
    }

    /**
     * Integral of the applicable ToU multiplier over an active charging interval.
     *
     * Units: multiplier-seconds.
     *
     * Home charging uses the configured seasonal ToU profile.
     * Work/public/other charging is treated as temporally flat.
     */
    public static double integrateTouMultiplierSeconds(double startTime, double endTime, String chargerAccessType, UrbanEVConfigGroup cfg) {

        if (!Double.isFinite(startTime)
                || !Double.isFinite(endTime)
                || endTime <= startTime) {
            return 0.0;
        }

        if (!"home".equalsIgnoreCase(chargerAccessType)) {
            return endTime - startTime;
        }

        double weightedSeconds = 0.0;
        double t = startTime;

        while (t < endTime - 1e-9) {

            double nextHourBoundary =
                    (Math.floor(t / 3600.0) + 1.0) * 3600.0;

            double intervalEnd =
                    Math.min(endTime, nextHourBoundary);

            double dt = intervalEnd - t;

            if (dt <= 0.0) {
                t += 1e-6;
                continue;
            }

            double multiplier =
                    getHourlyCostMultiplier(t, cfg);

            weightedSeconds += multiplier * dt;
            t = intervalEnd;
        }

        return weightedSeconds;
    }

    public static double getAverageTouMultiplier(double startTime, double endTime, String chargerAccessType, UrbanEVConfigGroup cfg) {

        if (!"home".equalsIgnoreCase(chargerAccessType)) {
            return 1.0;
        }

        double duration = endTime - startTime;

        if (!Double.isFinite(duration) || duration <= 0.0) {
            return getHourlyCostMultiplier(startTime, cfg);
        }

        double weightedSeconds =
                integrateTouMultiplierSeconds(
                        startTime,
                        endTime,
                        chargerAccessType,
                        cfg
                );

        return weightedSeconds / duration;
    }

    public static double getEffectivePricePerKWh(double startTime, double endTime, String chargerAccessType, UrbanEVConfigGroup cfg) {

        double basePrice =
                getBasePricePerKWh(
                        chargerAccessType,
                        cfg
                );

        double avgMultiplier =
                getAverageTouMultiplier(
                        startTime,
                        endTime,
                        chargerAccessType,
                        cfg
                );

        return basePrice * avgMultiplier;
    }

    public static double calculateChargingCost(
            double energyKWh,
            double startTime,
            double endTime,
            String chargerAccessType,
            UrbanEVConfigGroup cfg) {

        if (!Double.isFinite(energyKWh) || energyKWh <= 0.0) {
            return 0.0;
        }

        double effectivePrice =
                getEffectivePricePerKWh(
                        startTime,
                        endTime,
                        chargerAccessType,
                        cfg
                );

        return energyKWh * effectivePrice;
    }

    /*
     * Backward-compatible overload for any existing caller using the previous parameter order.
     */
    public static double calculateChargingCost(
            double energyKWh,
            double startTime,
            String chargerAccessType,
            UrbanEVConfigGroup cfg,
            double endTime) {

        return calculateChargingCost(
                energyKWh,
                startTime,
                endTime,
                chargerAccessType,
                cfg
        );
    }

    private static int hourOfDay(double timeSeconds) {
        int secOfDay = ((int) Math.floor(timeSeconds)) % 86400;
        if (secOfDay < 0) secOfDay += 86400;
        return secOfDay / 3600;
    }
}
