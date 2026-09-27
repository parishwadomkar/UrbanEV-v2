package se.urbanEV.charging;

import org.junit.jupiter.api.Test;
import se.urbanEV.config.UrbanEVConfigGroup;

import static org.junit.jupiter.api.Assertions.assertEquals;

class ChargingCostUtilsTest {
    @Test
    void pricesActualHomeChargingIntervalAcrossTouBoundary() {
        double average = ChargingCostUtils.getAverageTouMultiplier(
                7.5 * 3600.0,
                8.5 * 3600.0,
                "home",
                UrbanEVConfigGroup.Season.WINTER);

        assertEquals(1.2, average, 1e-12);
    }

    @Test
    void nonHomeChargingRemainsTemporallyFlat() {
        double average = ChargingCostUtils.getAverageTouMultiplier(
                7.5 * 3600.0,
                8.5 * 3600.0,
                "public",
                UrbanEVConfigGroup.Season.WINTER);

        assertEquals(1.0, average, 1e-12);
    }
}
