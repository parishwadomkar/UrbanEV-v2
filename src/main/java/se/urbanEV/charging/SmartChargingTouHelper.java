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
 * Smart ToU-aware charging start-time selection helper.
 * created by OmkarP.(2025)
 */
public final class SmartChargingTouHelper {

    private static final Logger log = Logger.getLogger(SmartChargingTouHelper.class);
    private static final double STEP = 5.0 * 60.0;             // 5 min
    private static final double MAX_SIGMA_SEC = 4.0 * 3600.0;  // max dispersion
    private static final double EPS_COST = 1e-6;               // tolerance
    private static final int LOW_START_MIN = 22 * 60;
    private static final int LOW_LEN_MIN = 8 * 60;             // 8 hours

    private SmartChargingTouHelper() {}

    public static double computeOptimalStartTime(
            double arrivalTime,
            double departureTime,
            double chargingDuration,
            UrbanEVConfigGroup cfg,
            Charger charger,
            ElectricVehicle ev,
            boolean isAware) {

        if (!cfg.isEnableSmartCharging() || !isAware) return arrivalTime;
        if (chargingDuration <= 0.0) return arrivalTime;
        if (departureTime <= arrivalTime + chargingDuration) return arrivalTime;
        final double latestStart = departureTime - chargingDuration;
        double alpha = cfg.getAlphaScaleTemporal();
        if (!Double.isFinite(alpha)) alpha = 1.0;
        alpha = Math.max(0.0, Math.min(2.0, alpha));
        final double frac = alpha / 2.0;
        final int preferredMinuteOfDay = (LOW_START_MIN + (int) Math.round(frac * LOW_LEN_MIN)) % (24 * 60);
        final double preferredTodSec = preferredMinuteOfDay * 60.0;

        // Check if start exists inside the low ToU window
        boolean feasibleLowExists = false;
        for (double t = arrivalTime; t <= latestStart + 1e-3; t += STEP) {
            if (isInLowToU(t)) {
                feasibleLowExists = true;
                break;
            }
        }

        // Find cost-minimizing starts (proxy = ToU multiplier at START time)
        double bestCost = Double.POSITIVE_INFINITY;
        List<Double> bestStarts = new ArrayList<>(64);
        for (double t = arrivalTime; t <= latestStart + 1e-3; t += STEP) {
            if (feasibleLowExists && !isInLowToU(t)) continue;

            double end = t + chargingDuration;
            double cost = 0.0;
            for (double tt = t; tt < end - 1e-3; tt += STEP) {
                double dt = Math.min(STEP, end - tt);
                double m = ChargingCostUtils.getHourlyCostMultiplier(mod86400(tt));
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

        if (bestStarts.isEmpty()) return arrivalTime;
        double coincidence = cfg.getCoincidenceFactor();
        if (!Double.isFinite(coincidence)) coincidence = 0.0;
        coincidence = Math.max(0.0, Math.min(1.0, coincidence));

        if (coincidence >= 0.999) {
            double chosen = bestStarts.get(0);
            double bestDist = circularTodDistance(mod86400(chosen), preferredTodSec);
            for (int i = 1; i < bestStarts.size(); i++) {
                double cand = bestStarts.get(i);
                double d = circularTodDistance(mod86400(cand), preferredTodSec);
                if (d < bestDist) {
                    bestDist = d;
                    chosen = cand;
                }
            }
            chosen = snapToGrid(chosen, STEP);
            if (chosen < arrivalTime) chosen = arrivalTime;
            if (chosen > latestStart) chosen = latestStart;
            return chosen;
        }

        double maxSigma = Math.min(MAX_SIGMA_SEC, (latestStart - arrivalTime) / 2.0);
        double sigma = (1.0 - coincidence) * maxSigma;
        sigma = Math.max(STEP, sigma);
        double[] w = new double[bestStarts.size()];
        double wSum = 0.0;
        for (int i = 0; i < bestStarts.size(); i++) {
            double s = bestStarts.get(i);
            double d = circularTodDistance(mod86400(s), preferredTodSec);
            double wi = Math.exp(-(d * d) / (2.0 * sigma * sigma));
            w[i] = wi;
            wSum += wi;
        }

        double chosen = bestStarts.get(0);
        if (wSum > 0.0) {
            Random rnd = MatsimRandom.getLocalInstance(); // thread-local RNG :contentReference[oaicite:1]{index=1}
            double r = rnd.nextDouble() * wSum;
            for (int i = 0; i < w.length; i++) {
                r -= w[i];
                if (r <= 0.0) {
                    chosen = bestStarts.get(i);
                    break;
                }
            }
        }

        chosen = snapToGrid(chosen, STEP);
        if (chosen < arrivalTime) chosen = arrivalTime;
        if (chosen > latestStart) chosen = latestStart;

        if (log.isDebugEnabled()) {
            log.debug(String.format(
                    "ToU: arr=%.0f dep=%.0f dur=%.0f alpha=%.2f prefMin=%d bestStart=%.0f bestCost=%.3f nBest=%d lowFeasible=%s",
                    arrivalTime, departureTime, chargingDuration, alpha, preferredMinuteOfDay,
                    chosen, bestCost, bestStarts.size(), feasibleLowExists
            ));
        }
        return chosen;
    }

    private static double mod86400(double t) {
        double x = t % 86400.0;
        return x < 0.0 ? x + 86400.0 : x;
    }

    private static double circularTodDistance(double a, double b) {
        double d = Math.abs(a - b);
        return Math.min(d, 86400.0 - d);
    }

    private static double snapToGrid(double t, double step) {
        return Math.round(t / step) * step;
    }

    private static boolean isInLowToU(double timeSeconds) {
        double tod = mod86400(timeSeconds);
        return (tod >= 22.0 * 3600.0) || (tod < 6.0 * 3600.0);
    }
}