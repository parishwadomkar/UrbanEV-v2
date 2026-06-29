package se.urbanEV.pv;

import se.urbanEV.config.UrbanEVConfigGroup;

/**
 * Vehicle Integrated Photovoltaic (VIPV)
 * created by OmkarP.(2026)
 * Takes agg. hourly PV potential factors (PVGIS) input for generating PV electricity
 */
public final class PvPotentialUtils {
    private PvPotentialUtils() {}

    // Hourly mean P/Wp factors derived from PVGIS [0..23] for Gothenburg, Sweden (2023)
    // Spring = Mar–May
    private static final double[] PV_SPRING = {
            0.000000, 0.000000, 0.000000, 0.000069, 0.006223, 0.021895,
            0.100943, 0.233823, 0.361494, 0.461787, 0.513890, 0.551742,
            0.534771, 0.488988, 0.405419, 0.291691, 0.143697, 0.037408,
            0.006413, 0.000059, 0.000000, 0.000000, 0.000000, 0.000000
    };

    // Summer = Jun–Aug
    private static final double[] PV_SUMMER = {
            0.000000, 0.000000, 0.000000, 0.000819, 0.013348, 0.038032,
            0.116793, 0.218149, 0.332354, 0.380945, 0.434282, 0.452355,
            0.442750, 0.430413, 0.369740, 0.291962, 0.180375, 0.077546,
            0.019328, 0.003316, 0.000000, 0.000000, 0.000000, 0.000000
    };

    // Autumn = Sep–Nov
    private static final double[] PV_AUTUMN = {
            0.000000, 0.000000, 0.000000, 0.000000, 0.000000, 0.000624,
            0.015130, 0.068454, 0.139992, 0.174675, 0.243744, 0.251490,
            0.248657, 0.202789, 0.139589, 0.069603, 0.023747, 0.001666,
            0.000000, 0.000000, 0.000000, 0.000000, 0.000000, 0.000000
    };

    // Winter = Dec–Feb
    private static final double[] PV_WINTER = {
            0.000000, 0.000000, 0.000000, 0.000000, 0.000000, 0.000000,
            0.000000, 0.006584, 0.047616, 0.109365, 0.142002, 0.154014,
            0.143179, 0.117851, 0.080779, 0.028645, 0.000000, 0.000000,
            0.000000, 0.000000, 0.000000, 0.000000, 0.000000, 0.000000
    };

    public static double getPotentialFactor(double timeSeconds, UrbanEVConfigGroup cfg) {
        int hour = hourOfDay(timeSeconds);

        UrbanEVConfigGroup.Season season =
                (cfg != null && cfg.getSeason() != null) ? cfg.getSeason() : UrbanEVConfigGroup.Season.SUMMER;

        double f;
        switch (season) {
            case WINTER:
                f = PV_WINTER[hour];
                break;
            case AUTUMN:
                f = PV_AUTUMN[hour];
                break;
            case SPRING:
                f = PV_SPRING[hour];
                break;
            case SUMMER:
            default:
                f = PV_SUMMER[hour];
                break;
        }

        if (!Double.isFinite(f)) return 0.0;
        return Math.max(0.0, Math.min(1.0, f));
    }

    private static int hourOfDay(double timeSeconds) {
        int secOfDay = ((int) Math.floor(timeSeconds)) % 86400;
        if (secOfDay < 0) secOfDay += 86400;
        return secOfDay / 3600;
    }
}
