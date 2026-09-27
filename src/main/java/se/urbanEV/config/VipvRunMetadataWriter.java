package se.urbanEV.config;

import org.matsim.contrib.ev.EvConfigGroup;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigWriter;
import org.matsim.core.controler.events.StartupEvent;
import org.matsim.core.controler.listener.StartupListener;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.time.Instant;

/** Writes the effective configuration and a compact provenance manifest. */
public final class VipvRunMetadataWriter implements StartupListener {
    private final Config config;
    private final String sourceConfig;
    private final VipvScenarioDefinition.RunPhase phase;

    public VipvRunMetadataWriter(
            Config config,
            String sourceConfig,
            VipvScenarioDefinition.RunPhase phase) {
        this.config = config;
        this.sourceConfig = sourceConfig;
        this.phase = phase;
    }

    @Override
    public void notifyStartup(StartupEvent event) {
        Path output = Paths.get(config.controler().getOutputDirectory());
        Path resolvedConfig = output.resolve("resolved-config.xml");
        Path manifest = output.resolve("vipv-run-manifest.json");

        try {
            Files.createDirectories(output);
            new ConfigWriter(config).write(resolvedConfig.toString());
            Files.write(
                    manifest,
                    manifestJson().getBytes(StandardCharsets.UTF_8),
                    StandardOpenOption.CREATE,
                    StandardOpenOption.TRUNCATE_EXISTING,
                    StandardOpenOption.WRITE);
        } catch (IOException | RuntimeException e) {
            throw new IllegalStateException(
                    "Could not write VIPV run metadata to " + output, e);
        }
    }

    private String manifestJson() {
        UrbanEVConfigGroup urbanEv = (UrbanEVConfigGroup)
                config.getModules().get(UrbanEVConfigGroup.GROUP_NAME);
        EvConfigGroup ev = EvConfigGroup.get(config);
        String newline = System.lineSeparator();
        StringBuilder json = new StringBuilder(1024);
        json.append("{").append(newline);
        append(json, "schemaVersion", "1", false, newline);
        append(json, "createdUtc", Instant.now().toString(), true, newline);
        append(json, "scenarioName", urbanEv.getScenarioName(), true, newline);
        append(json, "runPhase", phase.getManifestValue(), true, newline);
        append(json, "sourceConfig", sourceConfig, true, newline);
        append(json, "resolvedConfig", "resolved-config.xml", true, newline);
        append(json, "outputDirectory", config.controler().getOutputDirectory(), true, newline);
        append(json, "season", urbanEv.getSeason().name(), true, newline);
        append(json, "pvVehiclesFile", urbanEv.getPvVehiclesFile(), true, newline);
        append(json, "pvShare", Double.toString(urbanEv.getPvShare()), false, newline);
        append(json, "pvWp", Double.toString(urbanEv.getPvWp()), false, newline);
        append(json, "pvParkedOpenShare",
                Double.toString(urbanEv.getPvParkedOpenShare()), false, newline);
        append(json, "randomSeed", Long.toString(config.global().getRandomSeed()), false, newline);
        append(json, "firstIteration",
                Integer.toString(config.controler().getFirstIteration()), false, newline);
        append(json, "lastIteration",
                Integer.toString(config.controler().getLastIteration()), false, newline);
        append(json, "qsimStartTimeSeconds",
                Double.toString(config.qsim().getStartTime().seconds()), false, newline);
        append(json, "qsimEndTimeSeconds",
                Double.toString(config.qsim().getEndTime().seconds()), false, newline);
        append(json, "plansFile", config.plans().getInputFile(), true, newline);
        append(json, "evVehiclesFile", ev.getVehiclesFile(), true, newline);
        append(json, "networkFile", config.network().getInputFile(), true, newline);
        append(json, "enableSmartCharging",
                Boolean.toString(urbanEv.isEnableSmartCharging()), false, newline);
        append(json, "rangeAnxietyUtility",
                Double.toString(urbanEv.getRangeAnxietyUtility()), false, newline);
        append(json, "emptyBatteryUtility",
                Double.toString(urbanEv.getEmptyBatteryUtility()), false, newline);
        append(json, "socDifferenceUtility",
                Double.toString(urbanEv.getSocDifferenceUtility()), false, newline);
        append(json, "betaMoney", Double.toString(urbanEv.getBetaMoney()), false, newline);
        append(json, "alphaScaleCost",
                Double.toString(urbanEv.getAlphaScaleCost()), false, newline);
        append(json, "alphaScaleTemporal",
                Double.toString(urbanEv.getAlphaScaleTemporal()), false, newline);
        append(json, "awarenessFactor",
                Double.toString(urbanEv.getAwarenessFactor()), false, newline);
        appendLast(json, "coincidenceFactor",
                Double.toString(urbanEv.getCoincidenceFactor()), false, newline);
        json.append("}").append(newline);
        return json.toString();
    }

    private static void append(
            StringBuilder json,
            String key,
            String value,
            boolean quoted,
            String newline) {
        appendValue(json, key, value, quoted);
        json.append(',').append(newline);
    }

    private static void appendLast(
            StringBuilder json,
            String key,
            String value,
            boolean quoted,
            String newline) {
        appendValue(json, key, value, quoted);
        json.append(newline);
    }

    private static void appendValue(
            StringBuilder json,
            String key,
            String value,
            boolean quoted) {
        json.append("  \"").append(escape(key)).append("\": ");
        if (quoted) {
            json.append('"').append(escape(value)).append('"');
        } else {
            json.append(value);
        }
    }

    private static String escape(String value) {
        if (value == null) {
            return "";
        }
        return value
                .replace("\\", "\\\\")
                .replace("\"", "\\\"")
                .replace("\n", "\\n")
                .replace("\r", "\\r")
                .replace("\t", "\\t");
    }
}
