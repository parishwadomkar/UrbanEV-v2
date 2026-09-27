package se.urbanEV.pv;

import org.apache.log4j.Logger;
import org.matsim.api.core.v01.Id;
import se.urbanEV.fleet.ElectricFleetSpecification;
import se.urbanEV.fleet.ElectricVehicle;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Random;
import java.util.Set;

/**
 * Vehicle Integrated Photovoltaic (VIPV)
 * created by OmkarP.(2026)
 *
 * Revision (2026): an explicitly configured cohort file is authoritative and
 * is validated strictly.  Missing, malformed, duplicate or unknown IDs now
 * stop the run instead of silently switching to a different random cohort.
 */
public final class PvVehicleCsvLoader {
    private static final Logger log = Logger.getLogger(PvVehicleCsvLoader.class);

    private PvVehicleCsvLoader() {}

    public static Set<Id<ElectricVehicle>> loadOrSample(
            String csvPath,
            double pvShare,
            ElectricFleetSpecification fleetSpec,
            Random rnd) {

        validateShare(pvShare);
        List<Id<ElectricVehicle>> fleetIds = sortedFleetIds(fleetSpec);
        String trimmedPath = csvPath == null ? "" : csvPath.trim();

        if (!trimmedPath.isEmpty()) {
            if (fleetIds.isEmpty()) {
                throw new IllegalStateException(
                        "PvVehicleCsvLoader: cannot validate an explicit cohort against an empty fleet.");
            }

            Set<Id<ElectricVehicle>> fromCsv = loadCsv(trimmedPath);
            Set<Id<ElectricVehicle>> validFleetIds = new LinkedHashSet<>(fleetIds);
            List<Id<ElectricVehicle>> unknown = new ArrayList<>();
            for (Id<ElectricVehicle> id : fromCsv) {
                if (!validFleetIds.contains(id)) unknown.add(id);
            }
            if (!unknown.isEmpty()) {
                unknown.sort(Comparator.comparing(Id::toString));
                int shown = Math.min(10, unknown.size());
                throw new IllegalArgumentException(
                        "PvVehicleCsvLoader: explicit cohort contains " + unknown.size()
                                + " IDs absent from the electric fleet; first IDs="
                                + unknown.subList(0, shown));
            }

            if (pvShare > 0.0) {
                int expected = boundedCount(fleetIds.size(), pvShare);
                if (fromCsv.size() != expected) {
                    throw new IllegalArgumentException(
                            "PvVehicleCsvLoader: explicit cohort size " + fromCsv.size()
                                    + " does not match pvShare=" + pvShare
                                    + " for fleet size " + fleetIds.size()
                                    + " (expected " + expected + ").");
                }
            }

            log.info("PvVehicleCsvLoader: loaded and validated " + fromCsv.size()
                    + " PV vehicles from " + trimmedPath + ".");
            return Collections.unmodifiableSet(new LinkedHashSet<>(fromCsv));
        }

        if (pvShare <= 0.0) {
            log.info("PvVehicleCsvLoader: no cohort file and pvShare=0; PV set is empty.");
            return Collections.emptySet();
        }
        if (fleetIds.isEmpty()) {
            throw new IllegalStateException(
                    "PvVehicleCsvLoader: cannot sample a PV cohort from an empty fleet.");
        }

        Random cohortRandom = rnd == null ? new Random(0L) : rnd;
        Collections.shuffle(fleetIds, cohortRandom);
        int count = boundedCount(fleetIds.size(), pvShare);
        List<Id<ElectricVehicle>> selected = new ArrayList<>(fleetIds.subList(0, count));
        selected.sort(Comparator.comparing(Id::toString));

        Set<Id<ElectricVehicle>> out = new LinkedHashSet<>(selected);
        log.info("PvVehicleCsvLoader: deterministically sampled " + out.size()
                + " PV vehicles (pvShare=" + pvShare + ").");
        return Collections.unmodifiableSet(out);
    }

    public static Set<Id<ElectricVehicle>> loadCsv(String path) {
        if (path == null || path.trim().isEmpty()) {
            throw new IllegalArgumentException("PvVehicleCsvLoader: CSV path is empty.");
        }

        Path csv = Paths.get(path.trim());
        if (!Files.isRegularFile(csv) || !Files.isReadable(csv)) {
            throw new IllegalArgumentException(
                    "PvVehicleCsvLoader: CSV does not exist or is not readable: " + csv);
        }

        Set<Id<ElectricVehicle>> out = new LinkedHashSet<>();
        try {
            List<String> lines = Files.readAllLines(csv, StandardCharsets.UTF_8);
            for (int lineNumber = 1; lineNumber <= lines.size(); lineNumber++) {
                String line = lines.get(lineNumber - 1).trim();
                if (lineNumber == 1 && line.startsWith("\uFEFF")) {
                    line = line.substring(1).trim();
                }
                if (line.isEmpty() || line.startsWith("#")) continue;

                String value = parseFirstColumn(line, lineNumber, csv);
                String normalized = value.toLowerCase(Locale.ROOT)
                        .replace("_", "")
                        .replace(" ", "");
                if (normalized.equals("id") || normalized.equals("vehicleid")) continue;
                if (value.isEmpty()) {
                    throw new IllegalArgumentException(
                            "PvVehicleCsvLoader: empty vehicle ID at " + csv + ":" + lineNumber);
                }

                Id<ElectricVehicle> id = Id.create(value, ElectricVehicle.class);
                if (!out.add(id)) {
                    throw new IllegalArgumentException(
                            "PvVehicleCsvLoader: duplicate vehicle ID '" + value
                                    + "' at " + csv + ":" + lineNumber);
                }
            }
        } catch (IOException e) {
            throw new UncheckedIOException("PvVehicleCsvLoader: failed reading " + csv, e);
        }

        if (out.isEmpty()) {
            throw new IllegalArgumentException(
                    "PvVehicleCsvLoader: explicit cohort contains no vehicle IDs: " + csv);
        }
        return out;
    }

    private static String parseFirstColumn(String line, int lineNumber, Path csv) {
        StringBuilder value = new StringBuilder();
        boolean quoted = false;
        for (int i = 0; i < line.length(); i++) {
            char c = line.charAt(i);
            if (c == '"') {
                if (quoted && i + 1 < line.length() && line.charAt(i + 1) == '"') {
                    value.append('"');
                    i++;
                } else {
                    quoted = !quoted;
                }
            } else if (!quoted && (c == ',' || c == ';' || c == '\t')) {
                break;
            } else {
                value.append(c);
            }
        }
        if (quoted) {
            throw new IllegalArgumentException(
                    "PvVehicleCsvLoader: unmatched quote at " + csv + ":" + lineNumber);
        }
        return value.toString().trim();
    }

    private static List<Id<ElectricVehicle>> sortedFleetIds(ElectricFleetSpecification fleetSpec) {
        List<Id<ElectricVehicle>> ids = new ArrayList<>();
        if (fleetSpec == null || fleetSpec.getVehicleSpecifications() == null) return ids;

        for (Id<?> id : fleetSpec.getVehicleSpecifications().keySet()) {
            ids.add(Id.create(id.toString(), ElectricVehicle.class));
        }
        ids.sort(Comparator.comparing(Id::toString));
        return ids;
    }

    private static int boundedCount(int size, double share) {
        return Math.max(0, Math.min((int) Math.round(share * size), size));
    }

    private static void validateShare(double share) {
        if (!Double.isFinite(share) || share < 0.0 || share > 1.0) {
            throw new IllegalArgumentException("pvShare must be finite and in [0,1]: " + share);
        }
    }
}
