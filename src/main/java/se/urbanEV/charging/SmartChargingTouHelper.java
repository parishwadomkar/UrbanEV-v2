package se.urbanEV.charging;

import org.apache.log4j.Logger;
import org.matsim.core.gbl.MatsimRandom;
import se.urbanEV.config.UrbanEVConfigGroup;
import se.urbanEV.fleet.ElectricVehicle;
import se.urbanEV.infrastructure.Charger;
import java.util.ArrayList;
import java.util.List;
import java.util.Random;

/**
 * utility class created by OmkarP.(2025)
 */
public final class SmartChargingTouHelper {

    private static final Logger log = Logger.getLogger(SmartChargingTouHelper.class);
    private static final double STEP = 15.0 * 60.0;            // 15 min
    private static final double MAX_SHIFT_SEC = 5.0 * 3600.0;  // max earlier shift
    private static final double MAX_SIGMA_SEC = 4.0 * 3600.0;  // max dispersion
    private static final double EPS_COST = 1e-6;               // tolerance
    private static final int PREFERRED_MINUTE_OF_DAY = 0;     // 60 for 01:00, 0 for midnight

    private SmartChargingTouHelper() {}

    /**
     * Compute a cost-minimising start time within [arrivalTime, departureTime - chargingDuration],
     * assuming the agent is already marked as ToU-aware at the person level.
     *
     * If:
     *  - smart charging is disabled, or
     *  - isAware == false, or
     *  - there is no feasible window,
     * we simply return arrivalTime.
     *
     * Coincidence is still modelled here: even aware agents may ignore the optimum
     */

    public static double computeOptimalStartTime(
            double arrivalTime,
            double departureTime,
            double chargingDuration,
            UrbanEVConfigGroup cfg,
            Charger charger,
            ElectricVehicle ev,
            boolean isAware) {

        if (!cfg.isEnableSmartCharging() || !isAware) {
            return arrivalTime;
        }

        if (chargingDuration <= 0 || departureTime <= arrivalTime + chargingDuration) {
            return arrivalTime;
        }

        final double latestStart = departureTime - chargingDuration;

        final double alphaTemporal = cfg.getAlphaScaleTemporal();
        final double shiftSec = (1.0 - alphaTemporal) * MAX_SHIFT_SEC;

        double bestCost = Double.POSITIVE_INFINITY;
        List<Double> bestStarts = new ArrayList<>(32);

        for (double t = arrivalTime; t <= latestStart + 1e-3; t += STEP) {
            double cost = 0.0;
            double end = t + chargingDuration;

            for (double tt = t; tt < end - 1e-3; tt += STEP) {
                double m = ChargingCostUtils.getHourlyCostMultiplier(tt - shiftSec);
                double dt = Math.min(STEP, end - tt);
                cost += m * dt;
            }

            if (cost + EPS_COST < bestCost) {
                bestCost = cost;
                bestStarts.clear();
                bestStarts.add(t);
            } else if (Math.abs(cost - bestCost) <= EPS_COST) {
                bestStarts.add(t);
            }
        }

        if (bestStarts.isEmpty()) {
            return arrivalTime;
        }

        // choice of deep night among equal minima
        double preferred = nextOccurrenceOfMinuteOfDay(arrivalTime, PREFERRED_MINUTE_OF_DAY);
        if (preferred < arrivalTime) preferred = arrivalTime;
        if (preferred > latestStart) preferred = 0.5 * (arrivalTime + latestStart);

        double bestStart = bestStarts.get(0);
        double bestDist = Math.abs(bestStart - preferred);
        for (int i = 1; i < bestStarts.size(); i++) {
            double cand = bestStarts.get(i);
            double d = Math.abs(cand - preferred);
            if (d < bestDist) {
                bestDist = d;
                bestStart = cand;
            }
        }

        if (bestStart > arrivalTime + 1.0) {
            double coincidence = cfg.getCoincidenceFactor(); // 0..1
            if (coincidence > 0.0) {
                double maxSigma = Math.min(MAX_SIGMA_SEC, (latestStart - arrivalTime) / 2.0);
                double sigma = (1.0 - coincidence) * maxSigma;

                if (sigma > 1.0) {
                    Random rnd = MatsimRandom.getLocalInstance();
                    double jitter = rnd.nextGaussian() * sigma;
                    double jittered = bestStart + jitter;
                    if (jittered < arrivalTime) jittered = arrivalTime;
                    if (jittered > latestStart) jittered = latestStart;
                    jittered = snapToGrid(jittered, STEP);
                    if (jittered < arrivalTime) jittered = arrivalTime;
                    if (jittered > latestStart) jittered = latestStart;
                    bestStart = jittered;
                }
            }
        }

        if (log.isDebugEnabled()) {
            log.debug(String.format(
                    "ToU: arr=%.0f dep=%.0f dur=%.0f shiftSec=%.0f bestStart=%.0f bestCost=%.3f nBest=%d pref=%.0f",
                    arrivalTime, departureTime, chargingDuration, shiftSec, bestStart, bestCost, bestStarts.size(), preferred
            ));
        }

        return bestStart;
    }

    private static double nextOccurrenceOfMinuteOfDay(double timeSeconds, int minuteOfDay) {
        double dayStart = Math.floor(timeSeconds / 86400.0) * 86400.0;
        double t = dayStart + minuteOfDay * 60.0;
        if (t < timeSeconds) t += 86400.0;
        return t;
    }

    private static double snapToGrid(double t, double step) {
        return Math.round(t / step) * step;
    }
}
