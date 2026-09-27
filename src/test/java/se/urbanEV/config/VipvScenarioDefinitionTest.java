package se.urbanEV.config;

import org.junit.jupiter.api.Test;
import org.matsim.contrib.ev.EvConfigGroup;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigGroup;
import org.matsim.core.config.ConfigUtils;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class VipvScenarioDefinitionTest {
    @Test
    void matrixContainsTheCompleteControlledDesign() {
        Map<String, VipvScenarioDefinition> definitions =
                VipvScenarioDefinition.loadAll(VipvScenarioDefinition.DEFAULT_MATRIX);

        // Two population samples x four seasons x
        // (one noVIPV control + three adoption shares x three Wp levels).
        assertEquals(80, definitions.size());
    }

    @Test
    void appliesRequestedTreatmentWithoutChangingBaseFile() {
        VipvScenarioDefinition definition = VipvScenarioDefinition.load(
                VipvScenarioDefinition.DEFAULT_MATRIX,
                "1pct_SPRING_VIPV50_Wp700_open50");
        Config config = load("scenarios/sweden/config1pct.xml");

        definition.applyTo(config);

        UrbanEVConfigGroup urbanEv = (UrbanEVConfigGroup)
                config.getModules().get(UrbanEVConfigGroup.GROUP_NAME);
        assertEquals("1pct_SPRING_VIPV50_Wp700_open50", urbanEv.getScenarioName());
        assertEquals(UrbanEVConfigGroup.Season.SPRING, urbanEv.getSeason());
        assertEquals(0.50, urbanEv.getPvShare(), 0.0);
        assertEquals(700.0, urbanEv.getPvWp(), 0.0);
        assertEquals(0.50, urbanEv.getPvParkedOpenShare(), 0.0);
        assertEquals("scenarios/sweden/1pct/50VIPV_1pct.csv",
                urbanEv.getPvVehiclesFile());
        assertEquals("output/1pct/1pct_SPRING_VIPV50_Wp700_open50",
                config.controler().getOutputDirectory());
    }

    @Test
    void rejectsAConfigurationWhoseLabelAndEffectiveValuesDisagree() {
        Config config = load("scenarios/sweden/config10pct.xml");
        UrbanEVConfigGroup urbanEv = (UrbanEVConfigGroup)
                config.getModules().get(UrbanEVConfigGroup.GROUP_NAME);
        urbanEv.setPvWp(700.0);

        assertThrows(IllegalArgumentException.class,
                () -> VipvScenarioDefinition.validateResolvedConfig(
                        config,
                        VipvScenarioDefinition.RunPhase.MAIN));
    }

    @Test
    void checkedInConfigsAreExplicitValidNoVipVControls() {
        VipvScenarioDefinition.validateResolvedConfig(
                load("scenarios/sweden/config1pct.xml"),
                VipvScenarioDefinition.RunPhase.MAIN);
        VipvScenarioDefinition.validateResolvedConfig(
                load("scenarios/sweden/config10pct.xml"),
                VipvScenarioDefinition.RunPhase.MAIN);
    }

    private static Config load(String path) {
        ConfigGroup[] groups = {new EvConfigGroup(), new UrbanEVConfigGroup()};
        return ConfigUtils.loadConfig(path, groups);
    }
}
