package se.tools;

import org.matsim.core.config.Config;
import se.got.GotEVMain;
import se.urbanEV.config.VipvScenarioDefinition;

import java.io.IOException;

/**
 * Selects one immutable treatment from vipv-scenario-matrix.csv
 * * <p>IntelliJ arguments:</p>
 * <pre>
 * 1pct_SPRING_VIPV50_Wp700_open50
 * </pre>
 */
public final class VipvScenarioRunner {
    private VipvScenarioRunner() {
    }

    public static void main(String[] args) throws IOException {
        if (args == null || args.length < 1 || args.length > 2) {
            throw new IOException(
                    "Usage: VipvScenarioRunner <scenarioName> [socInitializationIterations]");
        }

        String scenarioName = args[0];
        int initializationIterations = args.length == 2
                ? Integer.parseInt(args[1])
                : 0;
        VipvScenarioDefinition definition = VipvScenarioDefinition.load(
                VipvScenarioDefinition.DEFAULT_MATRIX,
                scenarioName);

        GotEVMain.runWithOptionalSocInitialization(
                () -> loadResolvedConfig(definition),
                definition.getBaseConfig()
                        + " + " + VipvScenarioDefinition.DEFAULT_MATRIX
                        + "#" + definition.getScenarioName(),
                initializationIterations);
    }

    private static Config loadResolvedConfig(VipvScenarioDefinition definition) {
        Config config = GotEVMain.loadTypedConfig(definition.getBaseConfig());
        definition.applyTo(config);
        return config;
    }
}
