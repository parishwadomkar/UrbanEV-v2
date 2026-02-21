package se.urbanEV.stats;

import org.apache.log4j.Logger;
import org.jfree.chart.ChartFactory;
import org.jfree.chart.JFreeChart;
import org.jfree.chart.plot.PlotOrientation;
import org.jfree.chart.plot.XYPlot;
import org.jfree.chart.renderer.xy.StackedXYAreaRenderer2;
import org.jfree.chart.renderer.xy.XYLineAndShapeRenderer;
import org.jfree.data.xy.DefaultTableXYDataset;
import org.jfree.data.xy.XYSeries;
import org.jfree.data.xy.XYSeriesCollection;
import org.matsim.core.controler.OutputDirectoryHierarchy;
import org.matsim.core.controler.events.IterationEndsEvent;
import org.matsim.core.controler.listener.IterationEndsListener;
import javax.inject.Inject;
import java.awt.Color;
import java.io.BufferedReader;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;

/**
 * Plots added by OmkarP.(2025)
 */
public final class AggregatedDailyDemandProfilePlotter implements IterationEndsListener {
    private static final Logger log = Logger.getLogger(AggregatedDailyDemandProfilePlotter.class);

    private static final int MIN_PER_DAY = 24 * 60;
    private static final double SEC_PER_MIN = 60.0;

    private static final Color HOME = new Color(0, 0, 255);
    private static final Color WORK = new Color(0, 128, 0);
    private static final Color PUBLIC = new Color(255, 165, 0);

    private final OutputDirectoryHierarchy io;

    @Inject
    public AggregatedDailyDemandProfilePlotter(OutputDirectoryHierarchy io) {
        this.io = io;
    }

    @Override
    public void notifyIterationEnds(IterationEndsEvent event) {
        int it = event.getIteration();

        // file naming matches your observed pattern: "<it>.chargingStats.csv"
        String csv = io.getIterationFilename(it, "chargingStats.csv");
        Path csvPath = Path.of(csv);

        if (!Files.exists(csvPath)) {
            log.warn("AggregatedDailyDemandProfilePlotter: missing file " + csvPath);
            return;
        }

        try {
            AggregationResult r = aggregate(csvPath);

            String outMinuteLine = io.getIterationFilename(it, "aggregated_daily_demand_profile_minute_lines.png");
            String outHourlyStacked = io.getIterationFilename(it, "aggregated_daily_demand_profile_hourly_stacked_area.png");

            writeMinuteLineChart(r.avgKwhPerMinByMinuteOfDay, outMinuteLine);
            writeHourlyStackedAreaChart(r.avgKwhPerHourByHourOfDay, outHourlyStacked);

            log.info("AggregatedDailyDemandProfilePlotter: wrote plots for it." + it);
        } catch (Exception e) {
            log.error("AggregatedDailyDemandProfilePlotter failed for it." + it, e);
        }
    }

    private static final class Session {
        final int type; // 0 home, 1 work, 2 public
        final int sMin;
        final int eMinExcl;
        final double ePerMin;

        Session(int type, int sMin, int eMinExcl, double ePerMin) {
            this.type = type;
            this.sMin = sMin;
            this.eMinExcl = eMinExcl;
            this.ePerMin = ePerMin;
        }
    }

    private static final class AggregationResult {
        final double[][] avgKwhPerMinByMinuteOfDay; // [1440][3]
        final double[][] avgKwhPerHourByHourOfDay;  // [24][3]

        AggregationResult(double[][] avgKwhPerMinByMinuteOfDay, double[][] avgKwhPerHourByHourOfDay) {
            this.avgKwhPerMinByMinuteOfDay = avgKwhPerMinByMinuteOfDay;
            this.avgKwhPerHourByHourOfDay = avgKwhPerHourByHourOfDay;
        }
    }

    private static AggregationResult aggregate(Path csvPath) throws Exception {
        List<Session> sessions = new ArrayList<>(1 << 14);
        int maxEndMin = 0;

        try (BufferedReader br = Files.newBufferedReader(csvPath)) {
            String header = br.readLine();
            if (header == null) throw new IllegalStateException("Empty chargingStats.csv");

            String[] h = header.split(";");
            Map<String, Integer> idx = new HashMap<>();
            for (int i = 0; i < h.length; i++) idx.put(h[i].trim().toLowerCase(Locale.ROOT), i);

            int iChargerId = findIdx(idx, "chargerid");
            int iStartTime = findIdx(idx, "starttime");
            int iChargingDuration = findIdx(idx, "chargingduration");
            int iEnergy = findIdx(idx, "transmittedenergy_kwh");
            Integer iEndTime = idx.get("endtime");

            String line;
            while ((line = br.readLine()) != null) {
                if (line.isEmpty()) continue;
                String[] a = line.split(";");
                if (a.length <= Math.max(Math.max(iChargerId, iStartTime), Math.max(iChargingDuration, iEnergy))) continue;

                String chargerId = a[iChargerId];
                int type = chargerType(chargerId);
                if (type < 0) continue;

                double startSec = parseDouble(a[iStartTime]);
                double durSec = parseDouble(a[iChargingDuration]);
                if (!Double.isFinite(startSec) || !Double.isFinite(durSec) || durSec <= 0) continue;

                double endSec = startSec + durSec;
                if (iEndTime != null && iEndTime < a.length) {
                    double e = parseDouble(a[iEndTime]);
                    if (Double.isFinite(e) && e > startSec) endSec = e;
                }

                double eKwh = parseDouble(a[iEnergy]);
                if (!Double.isFinite(eKwh) || eKwh <= 0) continue;

                int sMin = (int) Math.floor(startSec / SEC_PER_MIN);
                int eMinExcl = (int) Math.ceil(endSec / SEC_PER_MIN);
                if (eMinExcl <= sMin) continue;

                int durMinFull = Math.max(1, eMinExcl - sMin);
                double ePerMin = eKwh / (double) durMinFull;

                sessions.add(new Session(type, sMin, eMinExcl, ePerMin));
                if (eMinExcl > maxEndMin) maxEndMin = eMinExcl;
            }
        }

        if (maxEndMin <= 0 || sessions.isEmpty()) {
            double[][] zMin = new double[MIN_PER_DAY][3];
            double[][] zHr = new double[24][3];
            return new AggregationResult(zMin, zHr);
        }

        double[][] diff = new double[3][maxEndMin + 1];
        for (Session s : sessions) {
            int t = s.type;
            diff[t][s.sMin] += s.ePerMin;
            if (s.eMinExcl <= maxEndMin) diff[t][s.eMinExcl] -= s.ePerMin;
        }

        // absolute-minute reconstructed (kWh/min) then folded to minute-of-day
        double[][] sumMod = new double[MIN_PER_DAY][3];
        int fullCycles = maxEndMin / MIN_PER_DAY;
        int remainder = maxEndMin % MIN_PER_DAY;
        int[] counts = new int[MIN_PER_DAY];
        Arrays.fill(counts, fullCycles);
        for (int i = 0; i < remainder; i++) counts[i]++;

        for (int t = 0; t < 3; t++) {
            double run = 0.0;
            for (int m = 0; m < maxEndMin; m++) {
                run += diff[t][m];
                int mod = m % MIN_PER_DAY;
                sumMod[mod][t] += run;
            }
        }

        double[][] avgMin = new double[MIN_PER_DAY][3];
        for (int mod = 0; mod < MIN_PER_DAY; mod++) {
            int c = counts[mod];
            if (c <= 0) continue;
            avgMin[mod][0] = sumMod[mod][0] / c;
            avgMin[mod][1] = sumMod[mod][1] / c;
            avgMin[mod][2] = sumMod[mod][2] / c;
        }

        double[][] avgHr = new double[24][3];
        for (int h = 0; h < 24; h++) {
            int base = h * 60;
            for (int k = 0; k < 60; k++) {
                avgHr[h][0] += avgMin[base + k][0];
                avgHr[h][1] += avgMin[base + k][1];
                avgHr[h][2] += avgMin[base + k][2];
            }
        }

        return new AggregationResult(avgMin, avgHr);
    }

    private static int findIdx(Map<String, Integer> idx, String key) {
        Integer i = idx.get(key);
        if (i == null) throw new IllegalStateException("Missing column '" + key + "' in chargingStats.csv");
        return i;
    }

    private static double parseDouble(String s) {
        try {
            return Double.parseDouble(s.trim());
        } catch (Exception e) {
            return Double.NaN;
        }
    }

    // returns 0 home, 1 work, 2 public, -1 ignore
    private static int chargerType(String chargerId) {
        String s = String.valueOf(chargerId).toLowerCase(Locale.ROOT);
        if (s.contains("home")) return 0;
        if (s.contains("work")) return 1;
        if (s.contains("public")) return 2;
        return -1;
    }

    private static void writeMinuteLineChart(double[][] avgMin, String outPng) throws Exception {
        XYSeries home = new XYSeries("home");
        XYSeries work = new XYSeries("work");
        XYSeries pub = new XYSeries("public");

        for (int m = 0; m < MIN_PER_DAY; m++) {
            double x = m / 60.0; // hour-of-day
            home.add(x, avgMin[m][0]);
            work.add(x, avgMin[m][1]);
            pub.add(x, avgMin[m][2]);
        }

        XYSeriesCollection ds = new XYSeriesCollection();
        ds.addSeries(home);
        ds.addSeries(work);
        ds.addSeries(pub);

        JFreeChart chart = ChartFactory.createXYLineChart(
                "Average 24h Charging Demand (minute resolution)",
                "Hour of day",
                "Average transmitted energy (kWh/min)",
                ds,
                PlotOrientation.VERTICAL,
                true, false, false
        );

        XYPlot plot = chart.getXYPlot();
        XYLineAndShapeRenderer r = new XYLineAndShapeRenderer(true, false);
        r.setSeriesPaint(0, HOME);
        r.setSeriesPaint(1, WORK);
        r.setSeriesPaint(2, PUBLIC);
        plot.setRenderer(r);

        savePng(chart, Path.of(outPng), 1200, 600);
    }

    private static void writeHourlyStackedAreaChart(double[][] avgHr, String outPng) throws Exception {
        // Smooth curves via cyclic Catmull-Rom spline (piecewise cubic, degree 3).
        double step = 0.25; // 15 min grid for smoothness
        int n = (int) Math.round(24.0 / step) + 1;

        double[] x = new double[n];
        double[] yHome = new double[n];
        double[] yWork = new double[n];
        double[] yPub = new double[n];

        double[] h = new double[24];
        double[] w = new double[24];
        double[] p = new double[24];
        for (int i = 0; i < 24; i++) {
            h[i] = avgHr[i][0];
            w[i] = avgHr[i][1];
            p[i] = avgHr[i][2];
        }

        for (int i = 0; i < n; i++) {
            double xi = i * step;
            if (xi > 24.0) xi = 24.0;
            x[i] = xi;

            yHome[i] = Math.max(0.0, catmullRomCyclic(h, xi));
            yWork[i] = Math.max(0.0, catmullRomCyclic(w, xi));
            yPub[i]  = Math.max(0.0, catmullRomCyclic(p, xi));
        }

        DefaultTableXYDataset ds = new DefaultTableXYDataset();

        XYSeries sHome = new XYSeries("home", true, false);
        XYSeries sWork = new XYSeries("work", true, false);
        XYSeries sPub  = new XYSeries("public", true, false);

        for (int i = 0; i < n; i++) {
            sHome.add(x[i], yHome[i]);
            sWork.add(x[i], yWork[i]);
            sPub.add(x[i], yPub[i]);
        }

        ds.addSeries(sHome);
        ds.addSeries(sWork);
        ds.addSeries(sPub);

        JFreeChart chart = ChartFactory.createStackedXYAreaChart(
                "Average 24h Charging Demand (hourly, stacked)",
                "Hour of day",
                "Average transmitted energy (kWh/hour)",
                ds,
                PlotOrientation.VERTICAL,
                true, false, false
        );

        XYPlot plot = chart.getXYPlot();
        StackedXYAreaRenderer2 r = new StackedXYAreaRenderer2();
        r.setSeriesPaint(0, HOME);
        r.setSeriesPaint(1, WORK);
        r.setSeriesPaint(2, PUBLIC);
        plot.setRenderer(r);

        savePng(chart, Path.of(outPng), 1200, 600);
    }

    // xHours in [0,24]; data has 24 points at integer hours 0..23 (cyclic)
    private static double catmullRomCyclic(double[] y, double xHours) {
        double x = xHours;
        if (x >= 24.0) x = 0.0;

        int i1 = (int) Math.floor(x);
        double u = x - i1;

        int i0 = (i1 - 1 + 24) % 24;
        int i2 = (i1 + 1) % 24;
        int i3 = (i1 + 2) % 24;

        double p0 = y[i0];
        double p1 = y[i1];
        double p2 = y[i2];
        double p3 = y[i3];

        double u2 = u * u;
        double u3 = u2 * u;

        return 0.5 * (
                (2.0 * p1) +
                        (-p0 + p2) * u +
                        (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * u2 +
                        (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * u3
        );
    }

    private static void savePng(JFreeChart chart, Path out, int w, int h) throws Exception {
        // JFreeChart has used both ChartUtils and ChartUtilities across versions.
        try {
            Class<?> c = Class.forName("org.jfree.chart.ChartUtils");
            c.getMethod("saveChartAsPNG", java.io.File.class, JFreeChart.class, int.class, int.class)
                    .invoke(null, out.toFile(), chart, w, h);
        } catch (ClassNotFoundException e) {
            Class<?> c = Class.forName("org.jfree.chart.ChartUtilities");
            c.getMethod("saveChartAsPNG", java.io.File.class, JFreeChart.class, int.class, int.class)
                    .invoke(null, out.toFile(), chart, w, h);
        }
    }
}
