package se.got;

import se.urbanEV.EvModule;
import se.urbanEV.config.UrbanEVConfigGroup;
import se.urbanEV.config.VipvRunMetadataWriter;
import se.urbanEV.config.VipvScenarioDefinition;
import se.urbanEV.planning.ChangeChargingBehaviour;
import se.urbanEV.scoring.ChargingBehaviourScoring;
import se.urbanEV.scoring.ChargingBehaviourScoringParameters;
import org.apache.log4j.Logger;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Population;
import org.matsim.contrib.ev.EvConfigGroup;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigGroup;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.controler.AbstractModule;
import org.matsim.core.controler.Controler;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.core.scoring.ScoringFunction;
import org.matsim.core.scoring.ScoringFunctionFactory;
import org.matsim.core.scoring.SumScoringFunction;
import org.matsim.core.events.EventsManagerImpl;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.function.Supplier;
import se.urbanEV.charging.ChargingCostUtils;
import se.urbanEV.pv.PvPotentialUtils;

public class GotEVMain {
    private static final Logger log = Logger.getLogger(se.got.GotEVMain.class);
    private static final String SMART_CHARGING_COMPONENT = "SmartChargingEngine";

    public GotEVMain() {
    }

    public static void main(String[] args) throws IOException {

        String configPath = "";
        int initIterations = 20;
        if (args != null && args.length == 2) {
            configPath = args[0];
            initIterations = Integer.parseInt(args[1]);
        } else if (args != null && args.length == 1){
            configPath = args[0];
            initIterations = 0;
        }
        else{
            System.out.println("Config file missing. Please supply a config file path as a program argument.");
            throw new IOException("Could not start simulation. Config file missing.");
        }
        log.info("Config file path: " + configPath);
        log.info("Number of iterations to initialize SOC distribution: " + initIterations);

        final String sourceConfig = configPath;
        runWithOptionalSocInitialization(
                () -> loadTypedConfig(sourceConfig),
                sourceConfig,
                initIterations);
    }

    /**
     * Runs either one scenario or the established UrbanEV SoC-initialization
     * phase followed by training.  The supplier must return a fresh, fully
     * resolved configuration on every call.
     */
    public static void runWithOptionalSocInitialization(
            Supplier<Config> configSupplier,
            String sourceConfig,
            int initIterations) {
        if (initIterations < 0) {
            throw new IllegalArgumentException("initIterations must be non-negative.");
        }

        Config config = configSupplier.get();
        if (initIterations > 0) {
            Config initConfig = configSupplier.get();
            initConfig.controler().setLastIteration(initIterations);
            String initOutput = initConfig.controler().getOutputDirectory() + "/init";
            initConfig.controler().setOutputDirectory(initOutput);
            runConfiguredScenario(
                    initConfig,
                    sourceConfig,
                    VipvScenarioDefinition.RunPhase.SOC_INITIALIZATION);

            // Revision (2026): derive this path from the selected scenario
            // output.  The previous hard-coded output/init path pointed to a
            // different directory for every 1pct/10pct scenario.
            Path initializedVehicles = Paths.get(initOutput, "output_evehicles.xml")
                    .toAbsolutePath()
                    .normalize();
            if (!Files.isRegularFile(initializedVehicles)) {
                throw new IllegalStateException(
                        "SoC initialization completed without writing " + initializedVehicles);
            }

            EvConfigGroup.get(config).setVehiclesFile(initializedVehicles.toString());
            config.controler().setOutputDirectory(
                    config.controler().getOutputDirectory() + "/train");
            runConfiguredScenario(
                    config,
                    sourceConfig,
                    VipvScenarioDefinition.RunPhase.TRAINING);
        } else {
            runConfiguredScenario(
                    config,
                    sourceConfig,
                    VipvScenarioDefinition.RunPhase.MAIN);
        }
    }

    public static Config loadTypedConfig(String configPath) {
        // New instances are required for every load; MATSim config groups are
        // mutable and must never be shared between init and training phases.
        ConfigGroup[] configGroups =
                new ConfigGroup[]{new EvConfigGroup(), new UrbanEVConfigGroup()};
        return ConfigUtils.loadConfig(configPath, configGroups);
    }

    public static void runConfiguredScenario(
            Config config,
            String sourceConfig,
            VipvScenarioDefinition.RunPhase phase) {

        // Fail before population/network loading when labels and treatments
        // disagree or when a noVIPV control still contains active PV settings.
        VipvScenarioDefinition.validateResolvedConfig(config, phase);

        final Scenario scenario = ScenarioUtils.loadScenario(config);
        Controler controler = new Controler(scenario);
        controler.addControlerListener(
                new VipvRunMetadataWriter(config, sourceConfig, phase));

        UrbanEVConfigGroup urbanEvCfg =
                (UrbanEVConfigGroup) controler.getConfig().getModules().get(UrbanEVConfigGroup.GROUP_NAME);
        if (urbanEvCfg != null) {
            urbanEvCfg.logIfSuspicious();
        }

        controler.addOverridingModule(new EvModule());
        controler.configureQSimComponents(components -> {
            components.addNamedComponent(EvModule.EV_COMPONENT);

            // activate SmartChargingEngine when enabled in urban_ev
            if (urbanEvCfg != null && urbanEvCfg.isEnableSmartCharging()) {
                components.addNamedComponent(SMART_CHARGING_COMPONENT);
            }
        });

        controler.addOverridingQSimModule(new org.matsim.core.mobsim.qsim.AbstractQSimModule() {
            @Override
            protected void configureQSim() {
                bind(se.urbanEV.charging.VehicleChargingHandler.class).asEagerSingleton();
                bind(se.urbanEV.charging.SmartChargingEngine.class).asEagerSingleton();
                addQSimComponentBinding(SMART_CHARGING_COMPONENT)
                        .to(se.urbanEV.charging.SmartChargingEngine.class);
            }
        });

        controler.addOverridingModule(new AbstractModule() {
            @Override
            public void install() {
                /*
                 * UrbanEV emits derived charging/scoring events while processing MATSim events and from after-sim-step callbacks.
                 * SimStepParallelEventsManagerImpl can consequently enqueue an older-time event behind a newer event and terminate with an
                 * event-ordering error followed by BrokenBarrierException.
                 *
                 * Synchronous dispatch preserves chronological event processing.
                 */
                bindEventsManager()
                        .to(EventsManagerImpl.class)
                        .asEagerSingleton();

                addPlanStrategyBinding("ChangeChargingBehaviour")
                        .toProvider(ChangeChargingBehaviour.class);
            }
        });


        // Mobility plans, routes and modes are treated as exogenous in this study. Only UrbanEV charging-behaviour scoring is active.
        // QSim network loading and capacity constraints remain active even though standard Charypar-Nagel activity and travel scoring is not included.
        // final ScoringFunctionFactory baseFactory = new CharyparNagelScoringFunctionFactory(scenario);
        controler.setScoringFunctionFactory(new ScoringFunctionFactory() {
            @Override
            public ScoringFunction createNewScoringFunction(Person person) {
                ChargingBehaviourScoringParameters params =
                        new ChargingBehaviourScoringParameters.Builder(scenario).build();
                SumScoringFunction sum = new SumScoringFunction();
                sum.addScoringFunction(new ChargingBehaviourScoring(params, person));
                return sum;
            }
        });

        Population population = controler.getScenario().getPopulation();
        double awareness = (urbanEvCfg != null) ? urbanEvCfg.getAwarenessFactor() : 0.0;
        long globalSeed = controler.getConfig().global().getRandomSeed();

        int awareCount = 0;
        int total = 0;
        for (Person person : population.getPersons().values()) {
            // Revision (2026): supplied plan attributes are authoritative.  Only
            // missing values are filled, preventing the runner from silently
            // changing an externally prepared experimental population.
            if (person.getAttributes().getAttribute("subpopulation") == null) {
                person.getAttributes().putAttribute("subpopulation", "nonCriticalSOC");
            }

            Object suppliedAwareness = person.getAttributes().getAttribute("smartChargingAware");
            boolean aware;
            if (suppliedAwareness != null) {
                aware = Boolean.parseBoolean(suppliedAwareness.toString());
            } else {
                aware = deterministicAwarenessDraw(globalSeed, person.getId().toString()) < awareness;
                person.getAttributes().putAttribute("smartChargingAware", aware);
            }
            total++;
            if (aware) {
                awareCount++;
            }
        }

        if (urbanEvCfg != null) {
            log.info("UrbanEV active season = " + urbanEvCfg.getSeason());

            log.info(String.format(
                    "Seasonal ToU check [%s]: h08=%.3f h12=%.3f h18=%.3f",
                    urbanEvCfg.getSeason(),
                    ChargingCostUtils.getHourlyCostMultiplier(8 * 3600.0, urbanEvCfg),
                    ChargingCostUtils.getHourlyCostMultiplier(12 * 3600.0, urbanEvCfg),
                    ChargingCostUtils.getHourlyCostMultiplier(18 * 3600.0, urbanEvCfg)
            ));

            log.info(String.format(
                    "Seasonal PV check [%s]: h08=%.6f h12=%.6f h18=%.6f",
                    urbanEvCfg.getSeason(),
                    PvPotentialUtils.getPotentialFactor(8 * 3600.0, urbanEvCfg),
                    PvPotentialUtils.getPotentialFactor(12 * 3600.0, urbanEvCfg),
                    PvPotentialUtils.getPotentialFactor(18 * 3600.0, urbanEvCfg)
            ));
        }

        log.info(String.format(
                "Smart charging awareness assignment: %.1f%% configured → %d / %d persons marked smartChargingAware=true",
                awareness * 100.0, awareCount, total
        ));
        controler.run();
    }

    private static double deterministicAwarenessDraw(long globalSeed, String personId) {
        long value = globalSeed ^ personId.hashCode() ^ 0x9e3779b97f4a7c15L;
        value = (value ^ (value >>> 30)) * 0xbf58476d1ce4e5b9L;
        value = (value ^ (value >>> 27)) * 0x94d049bb133111ebL;
        value ^= value >>> 31;
        return (value >>> 11) * 0x1.0p-53;
    }
}
