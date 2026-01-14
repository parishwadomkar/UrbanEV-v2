package se.urbanEV.charging;

import org.apache.log4j.Logger;
import se.urbanEV.config.UrbanEVConfigGroup;
import se.urbanEV.fleet.ElectricVehicle;
import se.urbanEV.infrastructure.Charger;
import org.matsim.core.gbl.MatsimRandom;

public final class SmartChargingTouHelper {

    private static final Logger log = Logger.getLogger(SmartChargingTouHelper.class);
    private static final double STEP = 15.0 * 60.0; // 15 min
    private static final double MAX_SHIFT_SEC = 5.0 * 3600.0; // max earlier shift
    private static final double MAX_SIGMA_SEC = 2.0 * 3600.0; // max dispersion (std-dev) for deferred starts

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

        // Global toggle + per-person awareness
        if (!cfg.isEnableSmartCharging() || !isAware) {
            if (log.isDebugEnabled()) {
                log.debug(String.format(
                        "ToU: smart disabled or person not aware → start=arrival=%.0f (aware=%s)",
                        arrivalTime, isAware
                ));
            }
            return arrivalTime;
        }

        // Feasibility need both a positive duration and a non-empty window
        if (chargingDuration <= 0 || departureTime <= arrivalTime + chargingDuration) {
            if (log.isDebugEnabled()) {
                log.debug(String.format(
                        "ToU: insufficient window or zero duration " +
                                "(arr=%.0f dep=%.0f dur=%.0f) → start=arrival",
                        arrivalTime, departureTime, chargingDuration
                ));
            }
            return arrivalTime;
        }

        final double latestStart = departureTime - chargingDuration;

        double bestStart = arrivalTime;
        double bestCost = Double.POSITIVE_INFINITY;
        final double alphaTemporal = cfg.getAlphaScaleTemporal();
        final double shiftSec = (1.0 - alphaTemporal) * MAX_SHIFT_SEC;

        // Scan candidate start times in 15-min steps within the feasible window
        for (double t = arrivalTime; t <= latestStart + 1e-3; t += STEP) {
            double cost = 0.0;
            double end = t + chargingDuration;

            for (double tt = t; tt < end - 1e-3; tt += STEP) {
                double m = ChargingCostUtils.getHourlyCostMultiplier(tt + shiftSec);
                double dt = Math.min(STEP, end - tt);
                cost += m * dt;
            }

            if (cost + 1e-9 < bestCost) {
                bestCost = cost;
                bestStart = t;
            }
        }

        // Coincidence as dispersion (std-dev) for deferred starts
        if (bestStart > arrivalTime + 1.0) {
            double cf = cfg.getCoincidenceFactor();
            if (cf > 0.0) {
                double maxSigma = Math.min(MAX_SIGMA_SEC, (latestStart - arrivalTime) / 2.0);
                double sigma = cf * maxSigma;
                if (sigma > 1.0) {
                    double jitter = MatsimRandom.getLocalInstance().nextGaussian() * sigma;
                    double jittered = bestStart + jitter;
                    if (jittered < arrivalTime) jittered = arrivalTime;
                    if (jittered > latestStart) jittered = latestStart;
                    bestStart = jittered;
                }
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
