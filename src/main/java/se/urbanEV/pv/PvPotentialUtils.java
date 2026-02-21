package se.urbanEV.pv;

import se.urbanEV.config.UrbanEVConfigGroup;

/**
 * Vehicle Integrated Photovoltaic (VIPV)
 * created by OmkarP.(2026)
 * Takes agg. hourly PV potential factors (PVGIS) input for generating PV electricity
 */
public final class PvPotentialUtils {
    private PvPotentialUtils() {}

    // Derived from PVGIS [0..23]
    private static final double[] PV_SPRING = {
            0.000000, 0.000000, 0.000000, 0.000000, 0.000000, 0.009396,
            0.046507, 0.121369, 0.225117, 0.327089, 0.413765, 0.484986,
            0.515860, 0.518022, 0.490159, 0.430955, 0.341099, 0.244147,
            0.150983, 0.069954, 0.017469, 0.000833, 0.000000, 0.000000
    };

    private static final double[] PV_SUMMER = {
            0.000000, 0.000000, 0.000000, 0.000000, 0.001787, 0.028613,
            0.087511, 0.169374, 0.269795, 0.367274, 0.449858, 0.515663,
            0.549388, 0.570492, 0.539950, 0.490955, 0.423345, 0.329052,
            0.231642, 0.135511, 0.056352, 0.009792, 0.000000, 0.000000
    };

    private static final double[] PV_AUTUMN = {
            0.000000, 0.000000, 0.000000, 0.000000, 0.000000, 0.000000,
            0.000481, 0.013597, 0.049179, 0.109078, 0.166894, 0.211718,
            0.238066, 0.233039, 0.203305, 0.156816, 0.109158, 0.058121,
            0.020077, 0.002490, 0.000000, 0.000000, 0.000000, 0.000000
    };

    private static final double[] PV_WINTER = {
            0.000000, 0.000000, 0.000000, 0.000000, 0.000000, 0.000000,
            0.000000, 0.000416, 0.011142, 0.044747, 0.087641, 0.119612,
            0.123757, 0.107248, 0.074883, 0.035629, 0.009057, 0.000133,
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
