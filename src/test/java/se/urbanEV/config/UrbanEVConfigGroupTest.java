package se.urbanEV.config;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertThrows;

class UrbanEVConfigGroupTest {
    @Test
    void rejectsInvalidResearchTreatmentValues() {
        UrbanEVConfigGroup config = new UrbanEVConfigGroup();

        assertThrows(IllegalArgumentException.class, () -> config.setSeason("monsoon"));
        assertThrows(IllegalArgumentException.class, () -> config.setPvShare(1.01));
        assertThrows(IllegalArgumentException.class, () -> config.setPvParkedOpenShare(-0.01));
        assertThrows(IllegalArgumentException.class, () -> config.setPvWp(-1.0));
    }
}
