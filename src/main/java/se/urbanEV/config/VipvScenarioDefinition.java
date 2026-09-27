package se.urbanEV.config;

import org.matsim.core.config.Config;

import java.io.BufferedReader;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Immutable definition and fail-fast validation for one VIPV experiment.
 *
 * <p>Revision (2026): the scenario id, treatment parameters, cohort path and
 * output path are checked together before MATSim loads the population.  This
 * prevents an output folder labelled, for example, noVIPV from containing an
 * active PV cohort.</p>
 */
public final class VipvScenarioDefinition {
    public static final Path DEFAULT_MATRIX =
            Paths.get("scenarios/sweden/vipv-scenario-matrix.csv");

    private static final String EXPECTED_HEADER =
            "scenarioName,sample,baseConfig,season,pvShare,pvWp,pvParkedOpenShare,pvVehiclesFile,outputDirectory";
    private static final Pattern SCENARIO_NAME = Pattern.compile(
            "^(1pct|10pct)_(SPRING|SUMMER|AUTUMN|WINTER)_"
                    + "(noVIPV|VIPV(20|50|80))_Wp(0|400|700|1000)_open([0-9]{1,3})$");
    private static final double EPSILON = 1e-9;

    public enum RunPhase {
        MAIN("", "main"),
        SOC_INITIALIZATION("/init", "soc-initialization"),
        TRAINING("/train", "training");

        private final String outputSuffix;
        private final String manifestValue;

        RunPhase(String outputSuffix, String manifestValue) {
            this.outputSuffix = outputSuffix;
            this.manifestValue = manifestValue;
        }

        public String getOutputSuffix() {
            return outputSuffix;
        }

        public String getManifestValue() {
            return manifestValue;
        }
    }

    private final String scenarioName;
    private final String sample;
    private final String baseConfig;
    private final UrbanEVConfigGroup.Season season;
    private final double pvShare;
    private final double pvWp;
    private final double pvParkedOpenShare;
    private final String pvVehiclesFile;
    private final String outputDirectory;

    private VipvScenarioDefinition(String[] columns, int lineNumber) {
        scenarioName = columns[0].trim();
        sample = columns[1].trim();
        baseConfig = columns[2].trim();
        season = parseSeason(columns[3], lineNumber);
        pvShare = parseDouble(columns[4], "pvShare", lineNumber);
        pvWp = parseDouble(columns[5], "pvWp", lineNumber);
        pvParkedOpenShare = parseDouble(columns[6], "pvParkedOpenShare", lineNumber);
        pvVehiclesFile = columns[7].trim();
        outputDirectory = columns[8].trim();
        validateDefinition(lineNumber);
    }

    public static VipvScenarioDefinition load(Path matrix, String requestedScenario) {
        if (requestedScenario == null || requestedScenario.trim().isEmpty()) {
            throw new IllegalArgumentException("A non-empty scenarioName is required.");
        }

        Map<String, VipvScenarioDefinition> definitions = loadAll(matrix);
        VipvScenarioDefinition definition = definitions.get(requestedScenario.trim());
        if (definition == null) {
            throw new IllegalArgumentException(
                    "Unknown scenarioName='" + requestedScenario + "' in " + matrix
                            + ". Available scenarios: " + definitions.keySet());
        }
        return definition;
    }

    public static Map<String, VipvScenarioDefinition> loadAll(Path matrix) {
        Map<String, VipvScenarioDefinition> definitions = new LinkedHashMap<>();
        try (BufferedReader reader = Files.newBufferedReader(matrix, StandardCharsets.UTF_8)) {
            String header = reader.readLine();
            if (!EXPECTED_HEADER.equals(header)) {
                throw new IllegalArgumentException(
                        "Unexpected VIPV scenario matrix header in " + matrix
                                + ". Expected: " + EXPECTED_HEADER);
            }

            String line;
            int lineNumber = 1;
            while ((line = reader.readLine()) != null) {
                lineNumber++;
                String trimmed = line.trim();
                if (trimmed.isEmpty() || trimmed.startsWith("#")) {
                    continue;
                }

                String[] columns = line.split(",", -1);
                if (columns.length != 9) {
                    throw new IllegalArgumentException(
                            "Expected 9 columns in " + matrix + " at line " + lineNumber
                                    + " but found " + columns.length + ".");
                }
                VipvScenarioDefinition definition =
                        new VipvScenarioDefinition(columns, lineNumber);
                if (definitions.put(definition.scenarioName, definition) != null) {
                    throw new IllegalArgumentException(
                            "Duplicate scenarioName='" + definition.scenarioName
                                    + "' in " + matrix + " at line " + lineNumber + ".");
                }
            }
        } catch (IOException e) {
            throw new IllegalArgumentException(
                    "Could not read VIPV scenario matrix: " + matrix, e);
        }
        if (definitions.isEmpty()) {
            throw new IllegalArgumentException("VIPV scenario matrix is empty: " + matrix);
        }
        return definitions;
    }

    public void applyTo(Config config) {
        UrbanEVConfigGroup urbanEv = getUrbanEvConfig(config);
        urbanEv.setScenarioName(scenarioName);
        urbanEv.setSeason(season.name());
        urbanEv.setPvShare(pvShare);
        urbanEv.setPvWp(pvWp);
        urbanEv.setPvParkedOpenShare(pvParkedOpenShare);
        urbanEv.setPvVehiclesFile(pvVehiclesFile);
        config.controler().setOutputDirectory(outputDirectory);
        validateResolvedConfig(config, RunPhase.MAIN);
    }

    public static void validateResolvedConfig(Config config, RunPhase phase) {
        UrbanEVConfigGroup urbanEv = getUrbanEvConfig(config);
        ParsedName parsed = parseScenarioName(urbanEv.getScenarioName(), "resolved configuration");

        require(parsed.season == urbanEv.getSeason(),
                "scenarioName season " + parsed.season
                        + " disagrees with urban_ev season " + urbanEv.getSeason());
        requireClose(urbanEv.getPvShare(), parsed.adoptionPercent / 100.0,
                "scenarioName adoption disagrees with urban_ev pvShare");
        requireClose(urbanEv.getPvWp(), parsed.wp,
                "scenarioName Wp disagrees with urban_ev pvWp");
        requireClose(urbanEv.getPvParkedOpenShare(), parsed.openPercent / 100.0,
                "scenarioName open share disagrees with urban_ev pvParkedOpenShare");

        String expectedCohort = parsed.adoptionPercent == 0
                ? ""
                : cohortPath(parsed.sample, parsed.adoptionPercent);
        require(normalize(urbanEv.getPvVehiclesFile()).equals(normalize(expectedCohort)),
                "scenarioName requires pvVehiclesFile='" + expectedCohort
                        + "' but resolved value is '" + urbanEv.getPvVehiclesFile() + "'");

        if (parsed.adoptionPercent == 0) {
            require(urbanEv.getPvShare() == 0.0,
                    "noVIPV requires pvShare=0");
            require(urbanEv.getPvWp() == 0.0,
                    "noVIPV requires pvWp=0");
            require(urbanEv.getPvParkedOpenShare() == 0.0,
                    "noVIPV requires pvParkedOpenShare=0");
            require(urbanEv.getPvVehiclesFile().trim().isEmpty(),
                    "noVIPV requires an empty pvVehiclesFile");
        } else {
            require(urbanEv.getPvShare() > 0.0,
                    "VIPV treatment requires pvShare>0");
            require(urbanEv.getPvWp() > 0.0,
                    "VIPV treatment requires pvWp>0");
            require(!urbanEv.getPvVehiclesFile().trim().isEmpty(),
                    "VIPV treatment requires an explicit cohort CSV");
        }

        String expectedOutput = outputPath(parsed.sample, urbanEv.getScenarioName())
                + phase.getOutputSuffix();
        require(normalize(config.controler().getOutputDirectory()).equals(normalize(expectedOutput)),
                "scenarioName/phase requires outputDirectory='" + expectedOutput
                        + "' but resolved value is '" + config.controler().getOutputDirectory() + "'");

        String plansFile = normalize(config.plans().getInputFile());
        require(plansFile.contains("/" + parsed.sample + "/")
                        || plansFile.startsWith(parsed.sample + "/"),
                "scenario sample " + parsed.sample
                        + " disagrees with plans input file '" + config.plans().getInputFile() + "'");
    }

    public String getScenarioName() {
        return scenarioName;
    }

    public String getSample() {
        return sample;
    }

    public String getBaseConfig() {
        return baseConfig;
    }

    public String getOutputDirectory() {
        return outputDirectory;
    }

    private void validateDefinition(int lineNumber) {
        String source = "scenario matrix line " + lineNumber;
        ParsedName parsed = parseScenarioName(scenarioName, source);
        require(sample.equals(parsed.sample), source + ": sample disagrees with scenarioName");
        require(season == parsed.season, source + ": season disagrees with scenarioName");
        requireClose(pvShare, parsed.adoptionPercent / 100.0,
                source + ": pvShare disagrees with scenarioName");
        requireClose(pvWp, parsed.wp, source + ": pvWp disagrees with scenarioName");
        requireClose(pvParkedOpenShare, parsed.openPercent / 100.0,
                source + ": pvParkedOpenShare disagrees with scenarioName");

        String expectedBase = "scenarios/sweden/config" + sample + ".xml";
        require(normalize(baseConfig).equals(expectedBase),
                source + ": baseConfig must be '" + expectedBase + "'");

        String expectedCohort = parsed.adoptionPercent == 0
                ? ""
                : cohortPath(sample, parsed.adoptionPercent);
        require(normalize(pvVehiclesFile).equals(normalize(expectedCohort)),
                source + ": pvVehiclesFile must be '" + expectedCohort + "'");

        String expectedOutput = outputPath(sample, scenarioName);
        require(normalize(outputDirectory).equals(expectedOutput),
                source + ": outputDirectory must be '" + expectedOutput + "'");

        if (parsed.adoptionPercent == 0) {
            require(pvWp == 0.0 && pvParkedOpenShare == 0.0,
                    source + ": noVIPV requires pvWp=0 and pvParkedOpenShare=0");
        } else {
            require(pvWp > 0.0,
                    source + ": VIPV treatment requires pvWp>0");
        }
    }

    private static ParsedName parseScenarioName(String value, String source) {
        Matcher matcher = SCENARIO_NAME.matcher(value == null ? "" : value.trim());
        if (!matcher.matches()) {
            throw new IllegalArgumentException(
                    "Invalid scenarioName='" + value + "' in " + source
                            + ". Expected <1pct|10pct>_<SEASON>_<noVIPV|VIPV20|VIPV50|VIPV80>_"
                            + "Wp<0|400|700|1000>_open<0..100>.");
        }

        int adoptionPercent = matcher.group(4) == null
                ? 0
                : Integer.parseInt(matcher.group(4));
        int wp = Integer.parseInt(matcher.group(5));
        int openPercent = Integer.parseInt(matcher.group(6));
        require(openPercent >= 0 && openPercent <= 100,
                "scenarioName open share must be between 0 and 100: " + value);
        require((adoptionPercent == 0 && wp == 0)
                        || (adoptionPercent > 0 && wp > 0),
                "noVIPV must use Wp0 and VIPV treatments must use Wp>0: " + value);

        return new ParsedName(
                matcher.group(1),
                UrbanEVConfigGroup.Season.valueOf(matcher.group(2)),
                adoptionPercent,
                wp,
                openPercent);
    }

    private static UrbanEVConfigGroup.Season parseSeason(String value, int lineNumber) {
        try {
            return UrbanEVConfigGroup.Season.valueOf(value.trim());
        } catch (RuntimeException e) {
            throw new IllegalArgumentException(
                    "Invalid season='" + value + "' at scenario matrix line " + lineNumber, e);
        }
    }

    private static double parseDouble(String value, String column, int lineNumber) {
        try {
            double parsed = Double.parseDouble(value.trim());
            if (!Double.isFinite(parsed)) {
                throw new NumberFormatException("non-finite value");
            }
            return parsed;
        } catch (NumberFormatException e) {
            throw new IllegalArgumentException(
                    "Invalid " + column + "='" + value
                            + "' at scenario matrix line " + lineNumber, e);
        }
    }

    private static UrbanEVConfigGroup getUrbanEvConfig(Config config) {
        Object group = config.getModules().get(UrbanEVConfigGroup.GROUP_NAME);
        if (!(group instanceof UrbanEVConfigGroup)) {
            throw new IllegalArgumentException(
                    "Resolved configuration is missing the typed urban_ev module.");
        }
        return (UrbanEVConfigGroup) group;
    }

    private static String cohortPath(String sample, int adoptionPercent) {
        return "scenarios/sweden/" + sample + "/"
                + adoptionPercent + "VIPV_" + sample + ".csv";
    }

    private static String outputPath(String sample, String scenarioName) {
        return "output/" + sample + "/" + scenarioName;
    }

    private static String normalize(String path) {
        if (path == null) {
            return "";
        }
        String normalized = path.trim().replace('\\', '/');
        while (normalized.endsWith("/") && normalized.length() > 1) {
            normalized = normalized.substring(0, normalized.length() - 1);
        }
        return normalized;
    }

    private static void requireClose(double actual, double expected, String message) {
        require(Math.abs(actual - expected) <= EPSILON,
                message + " (expected " + expected + ", found " + actual + ")");
    }

    private static void require(boolean condition, String message) {
        if (!condition) {
            throw new IllegalArgumentException("VIPV scenario validation failed: " + message);
        }
    }

    private static final class ParsedName {
        private final String sample;
        private final UrbanEVConfigGroup.Season season;
        private final int adoptionPercent;
        private final int wp;
        private final int openPercent;

        private ParsedName(
                String sample,
                UrbanEVConfigGroup.Season season,
                int adoptionPercent,
                int wp,
                int openPercent) {
            this.sample = sample;
            this.season = season;
            this.adoptionPercent = adoptionPercent;
            this.wp = wp;
            this.openPercent = openPercent;
        }
    }
}
