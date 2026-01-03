package se.urbanEV.charging;

import org.apache.log4j.Logger;
import org.matsim.core.mobsim.qsim.InternalInterface;
import org.matsim.core.mobsim.qsim.interfaces.MobsimEngine;
import javax.inject.Inject;

/**
 * Implemented by omkarp, 10.01.2025
 * listener class
 */

public final class SmartChargingEngine implements MobsimEngine {
    private static final Logger log = Logger.getLogger(SmartChargingEngine.class);
    private final VehicleChargingHandler vch;

    @Inject
    public SmartChargingEngine(VehicleChargingHandler vch) {
        this.vch = vch;
    }

    @Override
    public void doSimStep(double time) {
//        log.info("SmartChargingEngine tick at time=" + time);
        vch.tick(time);
    }

    @Override
    public void onPrepareSim() {
        log.info("SmartChargingEngine is ACTIVE (registered as QSim component).");
    }

    @Override
    public void afterSim() { }

    @Override
    public void setInternalInterface(InternalInterface internalInterface) { }
}
