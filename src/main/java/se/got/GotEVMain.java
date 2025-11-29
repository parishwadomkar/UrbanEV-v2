package se.got;

import se.urbanEV.EvModule;
import se.urbanEV.config.UrbanEVConfigGroup;
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
import java.io.IOException;

public class GotEVMain {
    private static final Logger log = Logger.getLogger(se.got.GotEVMain.class);

    public GotEVMain() {
    }

    public static void main(String[] args) throws IOException {

        String configPath = "";
        int initIterations = 0;
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

        ConfigGroup[] configGroups = new ConfigGroup[]{new EvConfigGroup(), new UrbanEVConfigGroup()};
        Config config = ConfigUtils.loadConfig(configPath, configGroups);

        if (initIterations > 0) {
            Config initConfig = ConfigUtils.loadConfig(configPath, configGroups);
            initConfig.controler().setLastIteration(initIterations);
            initConfig.controler().setOutputDirectory(initConfig.controler().getOutputDirectory() + "/init");
            loadConfigAndRun(initConfig);

            EvConfigGroup evConfigGroup = (EvConfigGroup) config.getModules().get("ev");
            evConfigGroup.setVehiclesFile("output/init/output_evehicles.xml");
            config.controler().setOutputDirectory(config.controler().getOutputDirectory() + "/train");
        }
        loadConfigAndRun(config);
    }

    private static void loadConfigAndRun(Config config) {

        config.parallelEventHandling().setNumberOfThreads(1);
        final Scenario scenario = ScenarioUtils.loadScenario(config);
        Controler controler = new Controler(scenario);

        UrbanEVConfigGroup urbanEvCfg =
                (UrbanEVConfigGroup) controler.getConfig().getModules().get(UrbanEVConfigGroup.GROUP_NAME);
        if (urbanEvCfg != null) {
            urbanEvCfg.logIfSuspicious();
        }

        controler.addOverridingModule(new EvModule());
        controler.configureQSimComponents(components ->
                components.addNamedComponent(EvModule.EV_COMPONENT)
        );

        // QSim binding for the VehicleChargingHandler
        controler.addOverridingModule(new AbstractModule() {
            @Override
            public void install() {
                installQSimModule(new org.matsim.core.mobsim.qsim.AbstractQSimModule() {
                    @Override
                    protected void configureQSim() {
                        bind(se.urbanEV.charging.VehicleChargingHandler.class).asEagerSingleton();
                    }
                });
            }
        });

        controler.addOverridingModule(new AbstractModule() {
            @Override
            public void install() {
                addPlanStrategyBinding("ChangeChargingBehaviour").toProvider(ChangeChargingBehaviour.class);
            }
        });

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
        java.util.Random rng = new java.util.Random(controler.getConfig().global().getRandomSeed());

        int awareCount = 0;
        int total = 0;
        for (Person person : population.getPersons().values()) {
            person.getAttributes().putAttribute("subpopulation", "nonCriticalSOC");
            boolean aware = rng.nextDouble() <= awareness;
            person.getAttributes().putAttribute("smartChargingAware", aware);
            total++;
            if (aware) {
                awareCount++;
            }
        }

        log.info(String.format(
                "Smart charging awareness assignment: %.1f%% configured → %d / %d persons marked smartChargingAware=true",
                awareness * 100.0, awareCount, total
        ));
        controler.run();
    }
}
