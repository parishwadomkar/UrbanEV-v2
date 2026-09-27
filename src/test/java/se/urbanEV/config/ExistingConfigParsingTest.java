package se.urbanEV.config;

import org.junit.jupiter.api.Test;
import org.matsim.contrib.ev.EvConfigGroup;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigGroup;
import org.matsim.core.config.ConfigUtils;

import static org.junit.jupiter.api.Assertions.assertNotNull;

class ExistingConfigParsingTest {
    @Test
    void unchangedOnePercentConfigStillParses() {
        assertParses("scenarios/sweden/config1pct.xml");
    }

    @Test
    void unchangedTenPercentConfigStillParses() {
        assertParses("scenarios/sweden/config10pct.xml");
    }

    private static void assertParses(String path) {
        ConfigGroup[] groups = {new EvConfigGroup(), new UrbanEVConfigGroup()};
        Config config = ConfigUtils.loadConfig(path, groups);
        assertNotNull(config.getModules().get(UrbanEVConfigGroup.GROUP_NAME));
    }
}
