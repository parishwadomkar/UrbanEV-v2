package se.urbanEV.pv;

import org.apache.log4j.Logger;
import org.matsim.core.controler.OutputDirectoryHierarchy;
import org.matsim.core.controler.events.IterationEndsEvent;
import org.matsim.core.controler.listener.IterationEndsListener;

import javax.inject.Inject;
import java.io.BufferedWriter;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

/**
 * Vehicle Integrated Photovoltaic (VIPV)
 * created by OmkarP.(2026)
 */
public final class PvChargingStatsWriter implements IterationEndsListener {
    private static final Logger log = Logger.getLogger(PvChargingStatsWriter.class);

    private final OutputDirectoryHierarchy io;
    private final PvChargingIntervalCollector collector;

    @Inject
    public PvChargingStatsWriter(OutputDirectoryHierarchy io, PvChargingIntervalCollector collector) {
        this.io = io;
        this.collector = collector;
    }

    @Override
    public void notifyIterationEnds(IterationEndsEvent event) {
        // Revision (2026): retain the in-memory snapshot until the complete
        // file is written; an output failure now fails the research run.
        List<PvChargingIntervalEvent> rows = collector.snapshot();

        String fn = io.getIterationFilename(event.getIteration(), "pv_charging_instances.csv");
        Path out = Path.of(fn);

        try (BufferedWriter w = Files.newBufferedWriter(out)) {
            w.write("vehicleId,pvChargeStart_s,pvChargeEnd_s,mode,pvEnergyProduced_kWh,pvEnergyStored_kWh,pvEnergyWasted_kWh,startSoc_frac,endSoc_frac\n");
            for (PvChargingIntervalEvent r : rows) {
                w.write(r.getVehicleId() + "," + r.getIntervalStart_s() + "," + r.getIntervalEnd_s() + ","
                        + r.getMode() + "," + r.getEnergyProduced_kWh() + "," + r.getEnergyStored_kWh() + ","
                        + r.getEnergyWasted_kWh() + "," + r.getStartSoc_frac() + "," + r.getEndSoc_frac() + "\n");
            }
        } catch (IOException ex) {
            throw new UncheckedIOException("Failed writing PV charging instances: " + out, ex);
        }

        collector.clear();
        log.info("PV stats: wrote " + rows.size() + " PV charging intervals to " + out);
    }
}
