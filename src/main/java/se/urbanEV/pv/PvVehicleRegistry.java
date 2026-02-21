package se.urbanEV.pv;

import org.apache.log4j.Logger;
import org.matsim.api.core.v01.Id;
import org.matsim.core.controler.events.StartupEvent;
import org.matsim.core.controler.listener.StartupListener;
import se.urbanEV.config.UrbanEVConfigGroup;
import se.urbanEV.fleet.ElectricFleetSpecification;
import se.urbanEV.fleet.ElectricVehicle;

import javax.inject.Inject;
import javax.inject.Singleton;
import java.util.Collections;
import java.util.Random;
import java.util.Set;

import org.matsim.core.gbl.MatsimRandom;

/**
 * Vehicle Integrated Photovoltaic (VIPV)
 * created by OmkarP.(2026)
 */
@Singleton
public final class PvVehicleRegistry implements StartupListener {
    private static final Logger log = Logger.getLogger(PvVehicleRegistry.class);

    private final UrbanEVConfigGroup cfg;
    private final ElectricFleetSpecification fleetSpec;

    private Set<Id<ElectricVehicle>> pvVehicles = Collections.emptySet();

    @Inject
    public PvVehicleRegistry(UrbanEVConfigGroup cfg, ElectricFleetSpecification fleetSpec) {
        this.cfg = cfg;
        this.fleetSpec = fleetSpec;
    }

    @Override
    public void notifyStartup(StartupEvent event) {
        Random rnd = MatsimRandom.getRandom();

        pvVehicles = PvVehicleCsvLoader.loadOrSample(
                cfg.getPvVehiclesFile(),
                cfg.getPvShare(),
                fleetSpec,
                rnd
        );

        log.info("PV registry: pvVehicles=" + pvVehicles.size()
                + ", pvWp=" + cfg.getPvWp()
                + ", pvParkedOpenShare=" + cfg.getPvParkedOpenShare()
                + ", season=" + cfg.getSeason());
    }

    public boolean hasPv(Id<ElectricVehicle> evId) {
        return pvVehicles.contains(evId);
    }

    public Set<Id<ElectricVehicle>> getPvVehicles() {
        return pvVehicles;
    }
}
