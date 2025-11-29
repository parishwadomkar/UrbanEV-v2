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

        // Feasibility: need both a positive duration and a non-empty window
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

        // Energy magnitude is irrelevant here; only the relative ToU shape matters
        final double pseudoEnergyKWh = 1.0;
        final double alphaTemporal = cfg.getAlphaScaleTemporal(); // ≥ 1.0 by setter clamp

        // Scan candidate start times in 15-min steps within the feasible window
        for (double t = arrivalTime; t <= latestStart + 1e-3; t += STEP) {
            double tou = ChargingCostUtils.getHourlyCostMultiplier(t);

            // Behaviourally amplified perception of ToU:
            //   alphaTemporal = 1.0 → perceivedTou == tou (no change)
            //   alphaTemporal > 1.0 → exaggerates high prices and deepens low ones,
            //                          pushing choices more strongly to cheap night hours.
            double perceivedTou = Math.pow(tou, alphaTemporal);
            double cost = pseudoEnergyKWh * perceivedTou;

            if (cost < bestCost - 1e-9 || (Math.abs(cost - bestCost) <= 1e-9 && t > bestStart)) {
                bestCost = cost;
                bestStart = t;
            }
        }

        // Coincidence: interpret cfg.getCoincidenceFactor() as probability of *not* shifting-  pBlock = 0.25 → 25% ignore optimum, 75% follow it.
        double pBlock = cfg.getCoincidenceFactor();
        if (pBlock > 0.0) {
            double r = Math.random();
            if (r < pBlock) {
                if (log.isDebugEnabled()) {
                    log.debug(String.format(
                            "ToU: aware but blocked by coincidence: r=%.3f < pBlock=%.2f " +
                                    "(arr=%.0f dep=%.0f dur=%.0f → bestStart=%.0f cost=%.3f → returning arrival)",
                            r, pBlock, arrivalTime, departureTime, chargingDuration, bestStart, bestCost
                    ));
                }
                return arrivalTime;  // stay with arrivalTime despite having an optimum
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