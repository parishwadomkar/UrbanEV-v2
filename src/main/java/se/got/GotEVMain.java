package se.got;

import se.urbanEV.EvModule;
import se.urbanEV.charging.VehicleChargingHandler;
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
import org.matsim.core.mobsim.qsim.AbstractQSimModule;
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

        // Sanity-check UrbanEV monetary params on config
        UrbanEVConfigGroup urbanEvCfg = (UrbanEVConfigGroup) config.getModules().get(UrbanEVConfigGroup.GROUP_NAME);
        if (urbanEvCfg != null) {
            urbanEvCfg.logIfSuspicious();
        }

        if (initIterations > 0) {
            Config initConfig = ConfigUtils.loadConfig(configPath, configGroups);

            UrbanEVConfigGroup initUrbanEvCfg =
                    (UrbanEVConfigGroup) initConfig.getModules().get(UrbanEVConfigGroup.GROUP_NAME);
            if (initUrbanEvCfg != null) {
                initUrbanEvCfg.logIfSuspicious();
            }

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

        final Scenario scenario = ScenarioUtils.loadScenario(config);
        Controler controler = new Controler(scenario);
        controler.addOverridingModule(new EvModule());
        controler.addOverridingModule(new AbstractModule() {
            public void install() {
                this.installQSimModule(new AbstractQSimModule() {
                    protected void configureQSim() {
                        this.bind(VehicleChargingHandler.class).asEagerSingleton();
                    }
                });
            }
        });

        controler.configureQSimComponents((components) -> {
            components.addNamedComponent("EV_COMPONENT");
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
                ChargingBehaviourScoringParameters chargingBehaviourScoringParameters = new ChargingBehaviourScoringParameters.Builder(scenario).build();
                SumScoringFunction sumScoringFunction = new SumScoringFunction();
                sumScoringFunction.addScoringFunction(new ChargingBehaviourScoring(chargingBehaviourScoringParameters, person));
                return sumScoringFunction;
            }
        });

        Population population = controler.getScenario().getPopulation();
        population.getPersons().entrySet().forEach(entry->{entry.getValue().getAttributes().putAttribute("subpopulation", "nonCriticalSOC");});

        controler.run();
    }
}