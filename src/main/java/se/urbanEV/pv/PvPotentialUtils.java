package se.urbanEV.pv;

import se.urbanEV.config.UrbanEVConfigGroup;

/**
 * Vehicle Integrated Photovoltaic (VIPV)
 * created by OmkarP.(2026)
 * Takes agg. hourly PV potential factors (PVGIS) input for generating PV electricity.
 */
public final class PvPotentialUtils {
    private PvPotentialUtils() {}

    // Hourly mean P/Wp factors for Gothenburg, Sweden (2023), indexed by
    // Europe/Stockholm local civil hour [0..23]. PVGIS
    // timestamps were parsed as UTC and converted to Europe/Stockholm before
    // aggregation, including the 2023 daylight-saving transitions.

    // Spring = Mar–May
    private static final double[] PV_SPRING = {
            0.000000, 0.000000, 0.000000, 0.000000, 0.000000, 0.000069,
            0.006223, 0.022926, 0.128637, 0.257263, 0.377863, 0.473494,
            0.525545, 0.546998, 0.519925, 0.478235, 0.389012, 0.255197,
            0.135047, 0.037408, 0.006413, 0.000059, 0.000000, 0.000000
    };
    // Summer = Jun–Aug
    private static final double[] PV_SUMMER = {
            0.000000, 0.000000, 0.000000, 0.000000, 0.000000, 0.000819,
            0.013349, 0.038033, 0.116793, 0.218150, 0.332354, 0.380946,
            0.434282, 0.452355, 0.442750, 0.430413, 0.369741, 0.291962,
            0.180374, 0.077546, 0.019328, 0.003316, 0.000000, 0.000000
    };

    // Autumn = Sep–Nov
    private static final double[] PV_AUTUMN = {
            0.000000, 0.000000, 0.000000, 0.000000, 0.000000, 0.000000,
            0.000000, 0.000624, 0.016989, 0.084132, 0.156143, 0.192195,
            0.253659, 0.238457, 0.234789, 0.175565, 0.132592, 0.069603,
            0.023747, 0.001666, 0.000000, 0.000000, 0.000000, 0.000000
    };

    // Winter = Dec–Feb
    private static final double[] PV_WINTER = {
            0.000000, 0.000000, 0.000000, 0.000000, 0.000000, 0.000000,
            0.000000, 0.000000, 0.006584, 0.047616, 0.109366, 0.142002,
            0.154014, 0.143179, 0.117852, 0.080779, 0.028646, 0.000000,
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

    /**
     * Exact integral of the piecewise-constant hourly factor over an interval.
     * Units are factor-seconds, so multiplying the result by installed Wp
     * yields generated energy in joules.
     */
    public static double integratePotentialFactorSeconds(
            double startTimeSeconds,
            double endTimeSeconds,
            UrbanEVConfigGroup cfg) {

        if (!Double.isFinite(startTimeSeconds)
                || !Double.isFinite(endTimeSeconds)
                || endTimeSeconds <= startTimeSeconds) {
            return 0.0;
        }

        double integral = 0.0;
        double time = startTimeSeconds;
        while (time < endTimeSeconds - 1e-9) {
            double nextHour = (Math.floor(time / 3600.0) + 1.0) * 3600.0;
            double intervalEnd = Math.min(endTimeSeconds, nextHour);
            integral += getPotentialFactor(time, cfg) * (intervalEnd - time);
            time = intervalEnd;
        }
        return integral;
    }

    private static int hourOfDay(double timeSeconds) {
        int secOfDay = ((int) Math.floor(timeSeconds)) % 86400;
        if (secOfDay < 0) secOfDay += 86400;
        return secOfDay / 3600;
    }
}
