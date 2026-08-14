package se.urbanEV.stats;

import org.apache.commons.csv.CSVFormat;
import org.apache.commons.csv.CSVParser;
import org.apache.commons.csv.CSVPrinter;
import org.apache.commons.csv.CSVRecord;
import org.apache.log4j.Logger;
import org.jfree.chart.ChartFactory;
import org.jfree.chart.JFreeChart;
import org.jfree.chart.axis.NumberAxis;
import org.jfree.chart.axis.NumberTickUnit;
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
import se.urbanEV.charging.ChargingCostUtils;
import se.urbanEV.config.UrbanEVConfigGroup;

import javax.inject.Inject;
import java.awt.Color;
import java.io.Reader;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * @author Omkar Parishwad (omkarp, 2026)
 */

public final class ChargingCostAndTimeProfilePlotter implements IterationEndsListener {

    private static final Logger log =
            Logger.getLogger(ChargingCostAndTimeProfilePlotter.class);

    private static final double BIN_SEC = 300.0;
    private static final double SEC_PER_HOUR = 3600.0;
    private static final double SEC_PER_MIN = 60.0;
    private static final double SEC_PER_DAY = 24.0 * SEC_PER_HOUR;

    private static final int HOURS_PER_DAY = 24;
    private static final int BINS_PER_HOUR =
            (int) (SEC_PER_HOUR / BIN_SEC);
    private static final int BINS_PER_DAY =
            HOURS_PER_DAY * BINS_PER_HOUR;

    private static final int TYPE_HOME = 0;
    private static final int TYPE_WORK = 1;
    private static final int TYPE_PUBLIC = 2;
    private static final int TYPE_OTHER = 3;
    private static final int N_TYPES = 4;

    private static final String[] TYPE_NAMES = {
            "home",
            "work",
            "public",
            "other"
    };

    private static final Color HOME_COLOR =
            new Color(0, 0, 255);

    private static final Color WORK_COLOR =
            new Color(0, 128, 0);

    private static final Color PUBLIC_COLOR =
            new Color(255, 165, 0);

    private static final Color OTHER_COLOR =
            new Color(128, 128, 128);

    private static final Color PLOT_BACKGROUND =
            new Color(192, 192, 192);

    private static final Color GRID_COLOR =
            new Color(208, 208, 208);

    private final OutputDirectoryHierarchy io;
    private final UrbanEVConfigGroup cfg;

    @Inject
    public ChargingCostAndTimeProfilePlotter(
            OutputDirectoryHierarchy io,
            UrbanEVConfigGroup cfg) {

        this.io = io;
        this.cfg = cfg;
    }

    @Override
    public void notifyIterationEnds(
            IterationEndsEvent event) {

        int iteration = event.getIteration();

        Path chargingStats =
                Path.of(
                        io.getIterationFilename(
                                iteration,
                                "chargingStats.csv"
                        )
                );

        if (!Files.exists(chargingStats)) {

            log.warn(
                    "ChargingCostAndTimeProfilePlotter: missing "
                            + chargingStats
            );

            return;
        }

        try {

            List<Session> sessions =
                    readSessions(chargingStats);

            double maxSessionEnd = 0.0;

            for (Session s : sessions) {

                maxSessionEnd =
                        Math.max(
                                maxSessionEnd,
                                s.endTime
                        );
            }

            double horizonSec =
                    maxSessionEnd;

            try {

                double configuredEnd =
                        event
                                .getServices()
                                .getConfig()
                                .qsim()
                                .getEndTime()
                                .seconds();

                if (Double.isFinite(configuredEnd)
                        && configuredEnd > horizonSec) {

                    horizonSec =
                            configuredEnd;
                }

            } catch (Exception ignored) {
            }

            if (!Double.isFinite(horizonSec)
                    || horizonSec <= 0.0) {

                log.warn(
                        "ChargingCostAndTimeProfilePlotter: "
                                + "could not determine simulation horizon for iteration "
                                + iteration
                );

                return;
            }

            int nBins =
                    Math.max(
                            1,
                            (int) Math.ceil(
                                    horizonSec / BIN_SEC
                            )
                    );

            double[][] chargingTimeVehicleMin =
                    new double[nBins][N_TYPES];

            double[][] chargingCost =
                    new double[nBins][N_TYPES];

            aggregateSessions(
                    sessions,
                    chargingTimeVehicleMin,
                    chargingCost,
                    nBins
            );

            Path timeCsv =
                    Path.of(
                            io.getIterationFilename(
                                    iteration,
                                    "charger_type_charging_time_profiles.csv"
                            )
                    );

            Path costCsv =
                    Path.of(
                            io.getIterationFilename(
                                    iteration,
                                    "charger_type_charging_cost_time_profiles.csv"
                            )
                    );

            writeProfileCsv(
                    timeCsv,
                    chargingTimeVehicleMin
            );

            writeProfileCsv(
                    costCsv,
                    chargingCost
            );

            String timeLine =
                    io.getIterationFilename(
                            iteration,
                            "charger_type_charging_time_profiles_Line.png"
                    );

            String timeStack =
                    io.getIterationFilename(
                            iteration,
                            "charger_type_charging_time_profiles_StackedArea.png"
                    );

            String costLine =
                    io.getIterationFilename(
                            iteration,
                            "charger_type_charging_cost_time_profiles_Line.png"
                    );

            String costStack =
                    io.getIterationFilename(
                            iteration,
                            "charger_type_charging_cost_time_profiles_StackedArea.png"
                    );

            writeLineChart(
                    chargingTimeVehicleMin,
                    "Active Charging Time Profile",
                    "Time [h]",
                    "Active charging time [vehicle-min / 5 min]",
                    timeLine
            );

            writeStackedAreaChart(
                    chargingTimeVehicleMin,
                    "Active Charging Time Profile",
                    "Time [h]",
                    "Active charging time [vehicle-min / 5 min]",
                    timeStack
            );

            writeLineChart(
                    chargingCost,
                    "Charging Cost Time Profile",
                    "Time [h]",
                    "Charging cost [SEK / 5 min]",
                    costLine
            );

            writeStackedAreaChart(
                    chargingCost,
                    "Charging Cost Time Profile",
                    "Time [h]",
                    "Charging cost [SEK / 5 min]",
                    costStack
            );

            /*
             * Representative average 24-h profiles
             */

            int completeDays =
                    (int) Math.floor(
                            horizonSec / SEC_PER_DAY
                    );

            if (completeDays > 0) {

                /*
                 * Average profile retaining original five-minute resolution.
                 */
                double[][] avgDailyChargingTime5Min =
                        aggregateAverageDaily5Min(
                                chargingTimeVehicleMin,
                                completeDays
                        );

                double[][] avgDailyChargingCost5Min =
                        aggregateAverageDaily5Min(
                                chargingCost,
                                completeDays
                        );

                /*
                 * Convert representative 5-minute profile to hourly totals.
                 */
                double[][] avgDailyChargingTimeHourly =
                        aggregateDailyHourly(
                                avgDailyChargingTime5Min
                        );

                double[][] avgDailyChargingCostHourly =
                        aggregateDailyHourly(
                                avgDailyChargingCost5Min
                        );

                /*
                 * Hourly representative-day CSVs
                 */
                Path avgDailyTimeCsv =
                        Path.of(
                                io.getIterationFilename(
                                        iteration,
                                        "aggregated_daily_charging_time_profile_hourly.csv"
                                )
                        );

                Path avgDailyCostCsv =
                        Path.of(
                                io.getIterationFilename(
                                        iteration,
                                        "aggregated_daily_charging_cost_profile_hourly.csv"
                                )
                        );

                writeHourlyProfileCsv(
                        avgDailyTimeCsv,
                        avgDailyChargingTimeHourly
                );

                writeHourlyProfileCsv(
                        avgDailyCostCsv,
                        avgDailyChargingCostHourly
                );

                /*
                 * Hourly stacked representative-day plots
                 */
                String avgDailyTimeStack =
                        io.getIterationFilename(
                                iteration,
                                "aggregated_daily_charging_time_profile_hourly_stacked_area.png"
                        );

                String avgDailyCostStack =
                        io.getIterationFilename(
                                iteration,
                                "aggregated_daily_charging_cost_profile_hourly_stacked_area.png"
                        );

                writeHourlyStackedAreaChart(
                        avgDailyChargingTimeHourly,
                        "Average Daily Active Charging Time Profile",
                        "Hour of day",
                        "Active charging time [vehicle-min / h]",
                        avgDailyTimeStack
                );

                writeHourlyStackedAreaChart(
                        avgDailyChargingCostHourly,
                        "Average Daily Charging Cost Profile",
                        "Hour of day",
                        "Charging cost [SEK / h]",
                        avgDailyCostStack
                );

                /*
                 * representative-day plots
                 */
                String avgDailyTimeLines =
                        io.getIterationFilename(
                                iteration,
                                "aggregated_daily_charging_time_profile_5min_lines.png"
                        );

                String avgDailyCostLines =
                        io.getIterationFilename(
                                iteration,
                                "aggregated_daily_charging_cost_profile_5min_lines.png"
                        );

                writeDailyLineChart(
                        avgDailyChargingTime5Min,
                        "Average 24h Active Charging Time",
                        "Hour of day",
                        "Average active charging time [vehicle-min / 5 min]",
                        avgDailyTimeLines
                );

                writeDailyLineChart(
                        avgDailyChargingCost5Min,
                        "Average 24h Charging Cost",
                        "Hour of day",
                        "Average charging cost [SEK / 5 min]",
                        avgDailyCostLines
                );

                log.info(
                        "ChargingCostAndTimeProfilePlotter: generated representative 24-h profiles from "
                                + completeDays
                                + " complete simulation days."
                );
            }

            log.info(
                    "ChargingCostAndTimeProfilePlotter: iteration "
                            + iteration
                            + ", sessions="
                            + sessions.size()
                            + ", bins="
                            + nBins
            );

        } catch (Exception e) {

            log.error(
                    "ChargingCostAndTimeProfilePlotter failed for iteration "
                            + iteration,
                    e
            );
        }
    }

    private List<Session> readSessions(
            Path csvPath)
            throws Exception {

        List<Session> sessions =
                new ArrayList<>();

        try (
                Reader reader =
                        Files.newBufferedReader(
                                csvPath
                        );

                CSVParser parser =
                        new CSVParser(
                                reader,
                                CSVFormat.DEFAULT
                                        .withDelimiter(';')
                                        .withFirstRecordAsHeader()
                        )
        ) {

            Map<String, Integer> header =
                    parser.getHeaderMap();

            boolean hasAccessType =
                    header.containsKey(
                            "chargerAccessType"
                    );

            boolean hasChargingCost =
                    header.containsKey(
                            "chargingCost_SEK"
                    );

            boolean hasEnergy =
                    header.containsKey(
                            "transmittedEnergy_kWh"
                    );

            for (CSVRecord record : parser) {

                double startTime =
                        parseDouble(
                                record.get(
                                        "startTime"
                                )
                        );

                double endTime =
                        parseDouble(
                                record.get(
                                        "endTime"
                                )
                        );

                if (!Double.isFinite(startTime)) {
                    continue;
                }

                if (!Double.isFinite(endTime)
                        || endTime <= startTime) {

                    double duration =
                            parseDouble(
                                    record.get(
                                            "chargingDuration"
                                    )
                            );

                    if (!Double.isFinite(duration)
                            || duration <= 0.0) {

                        continue;
                    }

                    endTime =
                            startTime + duration;
                }

                String chargerId =
                        record.get(
                                "chargerId"
                        );

                String accessType;

                if (hasAccessType) {

                    accessType =
                            record.get(
                                    "chargerAccessType"
                            );

                    if (accessType == null
                            || accessType
                            .trim()
                            .isEmpty()) {

                        accessType =
                                ChargingCostUtils
                                        .getChargerAccessType(
                                                chargerId
                                        );
                    }

                } else {

                    accessType =
                            ChargingCostUtils
                                    .getChargerAccessType(
                                            chargerId
                                    );
                }

                int type =
                        getTypeIndex(
                                accessType
                        );

                double chargingCost =
                        0.0;

                if (hasChargingCost) {

                    chargingCost =
                            parseDouble(
                                    record.get(
                                            "chargingCost_SEK"
                                    )
                            );
                }

                if (!Double.isFinite(chargingCost)
                        || chargingCost < 0.0) {

                    chargingCost =
                            0.0;
                }

                if (!hasChargingCost
                        && hasEnergy) {

                    double energyKWh =
                            parseDouble(
                                    record.get(
                                            "transmittedEnergy_kWh"
                                    )
                            );

                    if (Double.isFinite(energyKWh)
                            && energyKWh > 0.0) {

                        chargingCost =
                                ChargingCostUtils
                                        .calculateChargingCost(
                                                energyKWh,
                                                startTime,
                                                endTime,
                                                accessType,
                                                cfg
                                        );
                    }
                }

                sessions.add(
                        new Session(
                                type,
                                accessType,
                                startTime,
                                endTime,
                                chargingCost
                        )
                );
            }
        }

        return sessions;
    }

    private void aggregateSessions(
            List<Session> sessions,
            double[][] chargingTimeVehicleMin,
            double[][] chargingCost,
            int nBins) {

        for (Session session : sessions) {

            double duration =
                    session.endTime
                            - session.startTime;

            if (duration <= 0.0) {
                continue;
            }

            int firstBin =
                    Math.max(
                            0,
                            (int) Math.floor(
                                    session.startTime
                                            / BIN_SEC
                            )
                    );

            int lastBin =
                    Math.min(
                            nBins - 1,
                            (int) Math.floor(
                                    Math.nextDown(
                                            session.endTime
                                    ) / BIN_SEC
                            )
                    );

            double sessionCostWeight =
                    ChargingCostUtils
                            .integrateTouMultiplierSeconds(
                                    session.startTime,
                                    session.endTime,
                                    session.accessType,
                                    cfg
                            );

            if (!Double.isFinite(
                    sessionCostWeight)
                    || sessionCostWeight <= 0.0) {

                sessionCostWeight =
                        duration;
            }

            for (int bin = firstBin;
                 bin <= lastBin;
                 bin++) {

                double binStart =
                        bin * BIN_SEC;

                double binEnd =
                        binStart + BIN_SEC;

                double overlapStart =
                        Math.max(
                                session.startTime,
                                binStart
                        );

                double overlapEnd =
                        Math.min(
                                session.endTime,
                                binEnd
                        );

                double overlapSec =
                        overlapEnd
                                - overlapStart;

                if (overlapSec <= 0.0) {
                    continue;
                }

                chargingTimeVehicleMin
                        [bin]
                        [session.type] +=
                        overlapSec
                                / SEC_PER_MIN;

                if (session.chargingCost <= 0.0) {
                    continue;
                }

                double binCostWeight =
                        ChargingCostUtils
                                .integrateTouMultiplierSeconds(
                                        overlapStart,
                                        overlapEnd,
                                        session.accessType,
                                        cfg
                                );

                if (!Double.isFinite(
                        binCostWeight)
                        || binCostWeight < 0.0) {

                    binCostWeight =
                            overlapSec;
                }

                double allocatedCost =
                        session.chargingCost
                                * binCostWeight
                                / sessionCostWeight;

                chargingCost
                        [bin]
                        [session.type] +=
                        allocatedCost;
            }
        }
    }

    private double[][] aggregateAverageDaily5Min(
            double[][] values,
            int completeDays) {

        double[][] dailyAverage =
                new double[BINS_PER_DAY][N_TYPES];

        if (completeDays <= 0) {
            return dailyAverage;
        }

        for (int day = 0;
             day < completeDays;
             day++) {

            int dayOffset =
                    day * BINS_PER_DAY;

            for (int bin = 0;
                 bin < BINS_PER_DAY;
                 bin++) {

                int globalBin =
                        dayOffset + bin;

                if (globalBin
                        >= values.length) {

                    break;
                }

                for (int type = 0;
                     type < N_TYPES;
                     type++) {

                    dailyAverage
                            [bin]
                            [type] +=
                            values
                                    [globalBin]
                                    [type];
                }
            }
        }

        for (int bin = 0;
             bin < BINS_PER_DAY;
             bin++) {

            for (int type = 0;
                 type < N_TYPES;
                 type++) {

                dailyAverage
                        [bin]
                        [type] /=
                        completeDays;
            }
        }

        return dailyAverage;
    }

    private double[][] aggregateDailyHourly(
            double[][] daily5Min) {

        double[][] hourly =
                new double[HOURS_PER_DAY][N_TYPES];

        for (int hour = 0;
             hour < HOURS_PER_DAY;
             hour++) {

            int firstBin =
                    hour * BINS_PER_HOUR;

            int lastBin =
                    firstBin
                            + BINS_PER_HOUR;

            for (int bin = firstBin;
                 bin < lastBin;
                 bin++) {

                for (int type = 0;
                     type < N_TYPES;
                     type++) {

                    hourly
                            [hour]
                            [type] +=
                            daily5Min
                                    [bin]
                                    [type];
                }
            }
        }

        return hourly;
    }

    private void writeProfileCsv(
            Path out,
            double[][] values)
            throws Exception {

        try (
                CSVPrinter printer =
                        new CSVPrinter(
                                Files.newBufferedWriter(
                                        out
                                ),
                                CSVFormat.DEFAULT
                                        .withDelimiter(';')
                                        .withHeader(
                                                "time_s",
                                                "time_h",
                                                "public",
                                                "home",
                                                "work",
                                                "other",
                                                "total"
                                        )
                        )
        ) {

            for (int bin = 0;
                 bin < values.length;
                 bin++) {

                double timeSec =
                        bin * BIN_SEC;

                double total =
                        values[bin][TYPE_PUBLIC]
                                + values[bin][TYPE_HOME]
                                + values[bin][TYPE_WORK]
                                + values[bin][TYPE_OTHER];

                printer.printRecord(
                        timeSec,
                        timeSec / SEC_PER_HOUR,
                        values[bin][TYPE_PUBLIC],
                        values[bin][TYPE_HOME],
                        values[bin][TYPE_WORK],
                        values[bin][TYPE_OTHER],
                        total
                );
            }
        }
    }

    private void writeHourlyProfileCsv(
            Path out,
            double[][] values)
            throws Exception {

        try (
                CSVPrinter printer =
                        new CSVPrinter(
                                Files.newBufferedWriter(
                                        out
                                ),
                                CSVFormat.DEFAULT
                                        .withDelimiter(';')
                                        .withHeader(
                                                "hour",
                                                "public",
                                                "home",
                                                "work",
                                                "other",
                                                "total"
                                        )
                        )
        ) {

            for (int hour = 0;
                 hour < HOURS_PER_DAY;
                 hour++) {

                double total =
                        values[hour][TYPE_PUBLIC]
                                + values[hour][TYPE_HOME]
                                + values[hour][TYPE_WORK]
                                + values[hour][TYPE_OTHER];

                printer.printRecord(
                        hour,
                        values[hour][TYPE_PUBLIC],
                        values[hour][TYPE_HOME],
                        values[hour][TYPE_WORK],
                        values[hour][TYPE_OTHER],
                        total
                );
            }
        }
    }

    private void writeLineChart(
            double[][] values,
            String title,
            String xLabel,
            String yLabel,
            String outPng)
            throws Exception {

        XYSeriesCollection dataset =
                new XYSeriesCollection();

        for (int type = 0;
             type < N_TYPES;
             type++) {

            XYSeries series =
                    new XYSeries(
                            TYPE_NAMES[type],
                            true,
                            false
                    );

            for (int bin = 0;
                 bin < values.length;
                 bin++) {

                double timeHours =
                        bin
                                * BIN_SEC
                                / SEC_PER_HOUR;

                series.add(
                        timeHours,
                        values[bin][type]
                );
            }

            dataset.addSeries(
                    series
            );
        }

        JFreeChart chart =
                ChartFactory.createXYLineChart(
                        title,
                        xLabel,
                        yLabel,
                        dataset,
                        PlotOrientation.VERTICAL,
                        true,
                        false,
                        false
                );

        XYPlot plot =
                chart.getXYPlot();

        XYLineAndShapeRenderer renderer =
                new XYLineAndShapeRenderer(
                        true,
                        false
                );

        applySeriesColors(
                renderer
        );

        plot.setRenderer(
                renderer
        );

        applyPlotStyle(
                plot
        );

        savePng(
                chart,
                Path.of(outPng),
                1400,
                700
        );
    }

    private void writeStackedAreaChart(
            double[][] values,
            String title,
            String xLabel,
            String yLabel,
            String outPng)
            throws Exception {

        DefaultTableXYDataset dataset =
                new DefaultTableXYDataset();

        for (int type = 0;
             type < N_TYPES;
             type++) {

            XYSeries series =
                    new XYSeries(
                            TYPE_NAMES[type],
                            true,
                            false
                    );

            for (int bin = 0;
                 bin < values.length;
                 bin++) {

                double timeHours =
                        bin
                                * BIN_SEC
                                / SEC_PER_HOUR;

                series.add(
                        timeHours,
                        values[bin][type]
                );
            }

            dataset.addSeries(
                    series
            );
        }

        JFreeChart chart =
                ChartFactory.createStackedXYAreaChart(
                        title,
                        xLabel,
                        yLabel,
                        dataset,
                        PlotOrientation.VERTICAL,
                        true,
                        false,
                        false
                );

        XYPlot plot =
                chart.getXYPlot();

        StackedXYAreaRenderer2 renderer =
                new StackedXYAreaRenderer2();

        applySeriesColors(
                renderer
        );

        plot.setRenderer(
                renderer
        );

        applyPlotStyle(
                plot
        );

        savePng(
                chart,
                Path.of(outPng),
                1400,
                700
        );
    }

    private void writeHourlyStackedAreaChart(
            double[][] values,
            String title,
            String xLabel,
            String yLabel,
            String outPng)
            throws Exception {

        DefaultTableXYDataset dataset =
                new DefaultTableXYDataset();

        for (int type = 0;
             type < N_TYPES;
             type++) {

            XYSeries series =
                    new XYSeries(
                            TYPE_NAMES[type],
                            true,
                            false
                    );

            for (int hour = 0;
                 hour < HOURS_PER_DAY;
                 hour++) {

                series.add(
                        hour,
                        values[hour][type]
                );
            }

            /*
             * Close representative daily profile at 24:00
             * using the value corresponding to 00:00.
             */
            series.add(
                    24.0,
                    values[0][type]
            );

            dataset.addSeries(
                    series
            );
        }

        JFreeChart chart =
                ChartFactory.createStackedXYAreaChart(
                        title,
                        xLabel,
                        yLabel,
                        dataset,
                        PlotOrientation.VERTICAL,
                        true,
                        false,
                        false
                );

        XYPlot plot =
                chart.getXYPlot();

        StackedXYAreaRenderer2 renderer =
                new StackedXYAreaRenderer2();

        applySeriesColors(
                renderer
        );

        plot.setRenderer(
                renderer
        );

        applyPlotStyle(
                plot
        );

        configureDailyXAxis(
                plot
        );

        savePng(
                chart,
                Path.of(outPng),
                1400,
                700
        );
    }

    private void writeDailyLineChart(
            double[][] values,
            String title,
            String xLabel,
            String yLabel,
            String outPng)
            throws Exception {

        XYSeriesCollection dataset =
                new XYSeriesCollection();

        for (int type = 0;
             type < N_TYPES;
             type++) {

            XYSeries series =
                    new XYSeries(
                            TYPE_NAMES[type],
                            true,
                            false
                    );

            for (int bin = 0;
                 bin < values.length;
                 bin++) {

                double timeHours =
                        bin
                                * BIN_SEC
                                / SEC_PER_HOUR;

                series.add(
                        timeHours,
                        values[bin][type]
                );
            }

            /*
             * Complete cyclic 24-h profile.
             */
            series.add(
                    24.0,
                    values[0][type]
            );

            dataset.addSeries(
                    series
            );
        }

        JFreeChart chart =
                ChartFactory.createXYLineChart(
                        title,
                        xLabel,
                        yLabel,
                        dataset,
                        PlotOrientation.VERTICAL,
                        true,
                        false,
                        false
                );

        XYPlot plot =
                chart.getXYPlot();

        XYLineAndShapeRenderer renderer =
                new XYLineAndShapeRenderer(
                        true,
                        false
                );

        applySeriesColors(
                renderer
        );

        plot.setRenderer(
                renderer
        );

        applyPlotStyle(
                plot
        );

        configureDailyXAxis(
                plot
        );

        savePng(
                chart,
                Path.of(outPng),
                1400,
                700
        );
    }

    private static void configureDailyXAxis(
            XYPlot plot) {

        if (plot.getDomainAxis()
                instanceof NumberAxis) {

            NumberAxis axis =
                    (NumberAxis)
                            plot.getDomainAxis();

            axis.setRange(
                    0.0,
                    24.0
            );

            axis.setTickUnit(
                    new NumberTickUnit(
                            1.0
                    )
            );
        }
    }

    private static void applyPlotStyle(
            XYPlot plot) {

        plot.setBackgroundPaint(
                PLOT_BACKGROUND
        );

        plot.setDomainGridlinePaint(
                GRID_COLOR
        );

        plot.setRangeGridlinePaint(
                GRID_COLOR
        );
    }

    private static void applySeriesColors(
            XYLineAndShapeRenderer renderer) {

        renderer.setSeriesPaint(
                TYPE_HOME,
                HOME_COLOR
        );

        renderer.setSeriesPaint(
                TYPE_WORK,
                WORK_COLOR
        );

        renderer.setSeriesPaint(
                TYPE_PUBLIC,
                PUBLIC_COLOR
        );

        renderer.setSeriesPaint(
                TYPE_OTHER,
                OTHER_COLOR
        );
    }

    private static void applySeriesColors(
            StackedXYAreaRenderer2 renderer) {

        renderer.setSeriesPaint(
                TYPE_HOME,
                HOME_COLOR
        );

        renderer.setSeriesPaint(
                TYPE_WORK,
                WORK_COLOR
        );

        renderer.setSeriesPaint(
                TYPE_PUBLIC,
                PUBLIC_COLOR
        );

        renderer.setSeriesPaint(
                TYPE_OTHER,
                OTHER_COLOR
        );
    }

    private static int getTypeIndex(
            String accessType) {

        if (accessType == null) {
            return TYPE_OTHER;
        }

        switch (
                accessType
                        .trim()
                        .toLowerCase(
                                Locale.ROOT
                        )
        ) {

            case "home":
                return TYPE_HOME;

            case "work":
                return TYPE_WORK;

            case "public":
                return TYPE_PUBLIC;

            default:
                return TYPE_OTHER;
        }
    }

    private static double parseDouble(
            String value) {

        try {

            return Double.parseDouble(
                    value.trim()
            );

        } catch (Exception e) {

            return Double.NaN;
        }
    }

    private static void savePng(
            JFreeChart chart,
            Path out,
            int width,
            int height)
            throws Exception {

        try {

            Class<?> chartUtils =
                    Class.forName(
                            "org.jfree.chart.ChartUtils"
                    );

            chartUtils
                    .getMethod(
                            "saveChartAsPNG",
                            java.io.File.class,
                            JFreeChart.class,
                            int.class,
                            int.class
                    )
                    .invoke(
                            null,
                            out.toFile(),
                            chart,
                            width,
                            height
                    );

        } catch (ClassNotFoundException e) {

            Class<?> chartUtilities =
                    Class.forName(
                            "org.jfree.chart.ChartUtilities"
                    );

            chartUtilities
                    .getMethod(
                            "saveChartAsPNG",
                            java.io.File.class,
                            JFreeChart.class,
                            int.class,
                            int.class
                    )
                    .invoke(
                            null,
                            out.toFile(),
                            chart,
                            width,
                            height
                    );
        }
    }

    private static final class Session {

        final int type;
        final String accessType;

        final double startTime;
        final double endTime;

        final double chargingCost;

        Session(
                int type,
                String accessType,
                double startTime,
                double endTime,
                double chargingCost) {

            this.type =
                    type;

            this.accessType =
                    accessType;

            this.startTime =
                    startTime;

            this.endTime =
                    endTime;

            this.chargingCost =
                    chargingCost;
        }
    }
}
