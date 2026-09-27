package se.urbanEV.pv;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class PvRandomUtilsTest {
    @Test
    void keyedDrawIsRepeatableAndIndependentOfCallOrder() {
        long first = PvRandomUtils.seedFor(42L, "parking", "vehicle-1", "3");
        PvRandomUtils.seedFor(42L, "unrelated");
        long repeated = PvRandomUtils.seedFor(42L, "parking", "vehicle-1", "3");

        assertEquals(first, repeated);
        assertNotEquals(first, PvRandomUtils.seedFor(42L, "parking", "vehicle-2", "3"));
    }

    @Test
    void probabilityThresholdsAreNestedForSameEpisode() {
        for (int vehicle = 0; vehicle < 100; vehicle++) {
            for (int episode = 0; episode < 10; episode++) {
                String id = "vehicle-" + vehicle;
                boolean p20 = PvRandomUtils.parkingIsOpen(0.2, 42L, 7, id, episode);
                boolean p50 = PvRandomUtils.parkingIsOpen(0.5, 42L, 7, id, episode);
                boolean p80 = PvRandomUtils.parkingIsOpen(0.8, 42L, 7, id, episode);
                assertTrue(!p20 || p50);
                assertTrue(!p50 || p80);
            }
        }
    }
}
