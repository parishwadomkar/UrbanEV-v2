package se.urbanEV.pv;

import org.junit.jupiter.api.Test;
import se.urbanEV.config.UrbanEVConfigGroup;

import static org.junit.jupiter.api.Assertions.assertEquals;

class PvPotentialUtilsTest {
    private static final double HOUR = 3600.0;

    @Test
    void usesStockholmLocalHourForWinterProfile() {
        UrbanEVConfigGroup config = new UrbanEVConfigGroup();
        config.setSeason("WINTER");

        assertEquals(0.0, PvPotentialUtils.getPotentialFactor(7 * HOUR, config), 1e-12);
        assertEquals(0.006584, PvPotentialUtils.getPotentialFactor(8 * HOUR, config), 1e-12);
    }

    @Test
    void integratesExactlyAcrossHourlyBoundary() {
        UrbanEVConfigGroup config = new UrbanEVConfigGroup();
        config.setSeason("WINTER");

        double integral = PvPotentialUtils.integratePotentialFactorSeconds(
                7.5 * HOUR, 8.5 * HOUR, config);
        assertEquals(0.006584 * 0.5 * HOUR, integral, 1e-6);
    }

    @Test
    void preservesSeasonalDailyEnergyAfterTimezoneConversion() {
        UrbanEVConfigGroup config = new UrbanEVConfigGroup();

        assertDailyEquivalent(config, "SPRING", 4.160314);
        assertDailyEquivalent(config, "SUMMER", 3.802509);
        assertDailyEquivalent(config, "AUTUMN", 1.580162);
        assertDailyEquivalent(config, "WINTER", 0.830037);
    }

    private static void assertDailyEquivalent(
            UrbanEVConfigGroup config,
            String season,
            double expectedKWhPerKWp) {
        config.setSeason(season);
        double factorHours = PvPotentialUtils.integratePotentialFactorSeconds(
                0.0, 24.0 * HOUR, config) / HOUR;
        // Arrays are stored to six decimals, so the 24-value sum has a small
        // deterministic rounding difference from the full-precision profile.
        assertEquals(expectedKWhPerKWp, factorHours, 5e-6);
    }
}
