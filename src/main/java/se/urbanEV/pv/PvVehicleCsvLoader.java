package se.urbanEV.pv;

import org.apache.log4j.Logger;
import org.matsim.api.core.v01.Id;
import se.urbanEV.fleet.ElectricVehicle;
import se.urbanEV.fleet.ElectricFleetSpecification;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.*;
import java.util.stream.Stream;

/**
 * Vehicle Integrated Photovoltaic (VIPV)
 * created by OmkarP.(2026)
 */
public final class PvVehicleCsvLoader {
    private static final Logger log = Logger.getLogger(PvVehicleCsvLoader.class);
    private PvVehicleCsvLoader() {}

    public static Set<Id<ElectricVehicle>> loadOrSample(
            String csvPath,
            double pvShare,
            ElectricFleetSpecification fleetSpec,
            Random rnd
    ) {

        Set<Id<ElectricVehicle>> fromCsv = loadCsv(csvPath);
        if (!fromCsv.isEmpty()) {
            if (fleetSpec != null && fleetSpec.getVehicleSpecifications() != null) {
                int before = fromCsv.size();
                fromCsv.retainAll(fleetSpec.getVehicleSpecifications().keySet());
                int dropped = before - fromCsv.size();
                if (dropped > 0) {
                    log.warn("PvVehicleCsvLoader: dropped " + dropped + " CSV ids not present in fleet.");
                }
            }
            if (!fromCsv.isEmpty()) {
                log.info("PvVehicleCsvLoader: loaded " + fromCsv.size() + " PV vehicles from CSV.");
                return fromCsv;
            }
        }

        // Fallback
        if (fleetSpec == null || fleetSpec.getVehicleSpecifications() == null || fleetSpec.getVehicleSpecifications().isEmpty()) {
            log.warn("PvVehicleCsvLoader: fleet specification empty; PV set is empty.");
            return Collections.emptySet();
        }

        double s = clamp01(pvShare);
        if (s <= 0.0) {
            log.info("PvVehicleCsvLoader: pvShare<=0 and no CSV; PV set is empty.");
            return Collections.emptySet();
        }

        if (rnd == null) rnd = new Random(0);

        // Convert MATSim contrib EV ids -> UrbanEV EV ids (string-compatible)
        List<Id<ElectricVehicle>> ids = new ArrayList<>(fleetSpec.getVehicleSpecifications().size());
        for (org.matsim.api.core.v01.Id<?> id : fleetSpec.getVehicleSpecifications().keySet()) {
            ids.add(Id.create(id.toString(), ElectricVehicle.class));
        }

        Collections.shuffle(ids, rnd);

        int n = (int) Math.round(s * ids.size());
        n = Math.max(0, Math.min(n, ids.size()));

        Set<Id<ElectricVehicle>> out = new HashSet<>(ids.subList(0, n));
        log.info("PvVehicleCsvLoader: sampled " + out.size() + " PV vehicles (pvShare=" + s + ").");
        return out;
    }

    public static Set<Id<ElectricVehicle>> loadCsv(String path) {
        if (path == null) return Collections.emptySet();

        String trimmed = path.trim();
        if (trimmed.isEmpty()) return Collections.emptySet();

        Path p = Paths.get(trimmed);
        if (!Files.exists(p)) {
            log.warn("PvVehicleCsvLoader: CSV not found: " + trimmed);
            return Collections.emptySet();
        }

        Set<Id<ElectricVehicle>> out = new HashSet<>();
        try (Stream<String> lines = Files.lines(p)) {
            lines.map(String::trim)
                    .filter(s -> !s.isEmpty())
                    .filter(s -> !s.startsWith("#"))
                    .forEach(s -> {
                        // allow optional header
                        String low = s.toLowerCase(Locale.ROOT);
                        if (low.equals("id") || low.contains("vehicle")) return;

                        String[] parts = s.split("[,;\\t]");
                        String id = parts[0].trim();
                        if (!id.isEmpty()) out.add(Id.create(id, ElectricVehicle.class));
                    });
        } catch (IOException e) {
            log.warn("PvVehicleCsvLoader: failed reading CSV: " + trimmed + " (" + e.getMessage() + ")");
            return Collections.emptySet();
        }

        return out;
    }

    private static double clamp01(double x) {
        if (x < 0.0) return 0.0;
        if (x > 1.0) return 1.0;
        return x;
    }
}
