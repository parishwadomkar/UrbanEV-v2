package se.urbanEV.charging;

public final class ChargingCostUtils {

    private ChargingCostUtils() {
    }

    /**
     * created by omkarp, 10.01.2025
     * Returns the hourly ToU multiplier M_temporal(t) for a given simulation time.
     *
     * @param timeSeconds simulation time in seconds (MATSim standard)
     * @return multiplier (dimensionless)
     */
    public static double getHourlyCostMultiplier(double timeSeconds) {
        int minuteOfDay = (int) Math.floorMod((long) Math.floor(timeSeconds / 60.0), 1440L);

        if (minuteOfDay < 360) {                               // 00:00–06:00
            return 0.7;
        } else if (minuteOfDay < 480) {                        // 06:00–08:00
            return 1.6;
        } else if (minuteOfDay < 600) {                        // 08:00–10:00
            return 1.47;
        } else if (minuteOfDay < 1020) {                       // 10:00–17:00
            return 0.92;
        } else if (minuteOfDay < 1200) {                       // 17:00–20:00
            return 1.14;
        } else if (minuteOfDay < 1320) {                       // 20:00–22:00
            return 1.0;
        } else {                                               // 22:00–24:00
            return 0.7;
        }
    }
}
