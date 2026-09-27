package se.urbanEV.pv;

import java.util.Random;

/**
 * Deterministic, component-specific random-number utilities for VIPV.
 * VIPV must not consume MATSim's shared random stream.  A
 * stable key also makes a shared vehicle receive the same parking-exposure
 * draw in paired adoption scenarios for a fixed seed and iteration.
 */
final class PvRandomUtils {
    private static final long FNV_OFFSET_BASIS = 0xcbf29ce484222325L;
    private static final long FNV_PRIME = 0x100000001b3L;

    private PvRandomUtils() {}

    static Random newComponentRandom(long globalSeed, String component) {
        return new Random(seedFor(globalSeed, component));
    }

    static boolean parkingIsOpen(
            double probability,
            long globalSeed,
            int iteration,
            String vehicleId,
            int parkingEpisode) {

        if (!Double.isFinite(probability) || probability < 0.0 || probability > 1.0) {
            throw new IllegalArgumentException("Parking exposure probability must be in [0,1]: " + probability);
        }
        if (probability <= 0.0) return false;
        if (probability >= 1.0) return true;

        long value = seedFor(
                globalSeed,
                "parking-exposure",
                Integer.toString(iteration),
                vehicleId,
                Integer.toString(parkingEpisode));
        double uniform = (value >>> 11) * 0x1.0p-53;
        return uniform < probability;
    }

    static long seedFor(long globalSeed, String... keys) {
        long hash = FNV_OFFSET_BASIS ^ globalSeed;
        for (String key : keys) {
            String value = key == null ? "<null>" : key;
            for (int i = 0; i < value.length(); i++) {
                hash ^= value.charAt(i);
                hash *= FNV_PRIME;
            }
            hash ^= 0xffL;
            hash *= FNV_PRIME;
        }
        return mix64(hash);
    }

    private static long mix64(long value) {
        long z = value + 0x9e3779b97f4a7c15L;
        z = (z ^ (z >>> 30)) * 0xbf58476d1ce4e5b9L;
        z = (z ^ (z >>> 27)) * 0x94d049bb133111ebL;
        return z ^ (z >>> 31);
    }
}
