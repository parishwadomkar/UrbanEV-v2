package se.urbanEV.charging;

import org.apache.log4j.Logger;
import se.urbanEV.config.UrbanEVConfigGroup;
import se.urbanEV.fleet.ElectricVehicle;
import se.urbanEV.infrastructure.Charger;

public final class SmartChargingTouHelper {

    private static final Logger log = Logger.getLogger(SmartChargingTouHelper.class);
    private static final double STEP = 15.0 * 60.0; // 15 min

    private SmartChargingTouHelper() {
        // utility class created by OmkarP.(2025)
    }

    /**
     * Implemented by omkarp, 10.01.2025
     * Compute a cost-minimising start time within [arrivalTime, departureTime - chargingDuration],
     * assuming the agent is already marked as ToU-aware at the person level.
     *
     * If:
     *  - smart charging is disabled, or
     *  - isAware == false, or
     *  - there is no feasible window,
     * we simply return arrivalTime.
     *
     * Coincidence is still modelled here: even aware agents may ignore the optimum with
     * probability (1 - coincidenceFactor).
     */
    public static double computeOptimalStartTime(
            double arrivalTime,
            double departureTime,
            double chargingDuration,
            UrbanEVConfigGroup cfg,
            Charger charger,
            ElectricVehicle ev,
            boolean isAware) {

        // Global toggle + per-person awareness:
        if (!cfg.isEnableSmartCharging() || !isAware) {
            if (log.isDebugEnabled()) {
                log.debug(String.format(
                        "ToU: smart disabled or person not aware → start=arrival=%.0f (aware=%s)",
                        arrivalTime, isAware
                ));
            }
            return arrivalTime;
        }

        if (chargingDuration <= 0 || departureTime <= arrivalTime + chargingDuration) {
            // Not enough window or nothing to charge
            if (log.isDebugEnabled()) {
                log.debug(String.format(
                        "ToU: insufficient window or zero duration " +
                                "(arr=%.0f dep=%.0f dur=%.0f) → start=arrival",
                        arrivalTime, departureTime, chargingDuration
                ));
            }
            return arrivalTime;
        }

        double latestStart = departureTime - chargingDuration;

        double bestStart = arrivalTime;
        double bestCost = Double.POSITIVE_INFINITY;

        // We assume energyRequired is fixed across candidates → only ToU pattern matters
        double pseudoEnergyKWh = 1.0;

        for (double t = arrivalTime; t <= latestStart + 1e-3; t += STEP) {
            double tou = ChargingCostUtils.getHourlyCostMultiplier(t);
            double cost = pseudoEnergyKWh * tou;
            if (cost < bestCost) {
                bestCost = cost;
                bestStart = t;
            }
        }

        // Coincidence: not all aware agents actually shift to the optimum
        double coincidence = cfg.getCoincidenceFactor();
        if (coincidence < 1.0) {
            double r = Math.random();
            if (r > coincidence) {
                if (log.isDebugEnabled()) {
                    log.debug(String.format(
                            "ToU: aware but not shifting due to coincidence: r=%.3f > c=%.2f " +
                                    "(arr=%.0f dep=%.0f dur=%.0f → bestStart=%.0f cost=%.3f → returning arrival)",
                            r, coincidence, arrivalTime, departureTime, chargingDuration, bestStart, bestCost
                    ));
                }
                return arrivalTime;
            }
        }

        if (log.isDebugEnabled()) {
            log.debug(String.format(
                    "ToU advisory: aware=true, arrival=%.0f dep=%.0f dur=%.0f → bestStart=%.0f (cost=%.3f)",
                    arrivalTime, departureTime, chargingDuration, bestStart, bestCost
            ));
        }

        return bestStart;
    }
}