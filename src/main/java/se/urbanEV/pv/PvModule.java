package se.urbanEV.pv;

import com.google.inject.Inject;
import org.matsim.core.controler.AbstractModule;
import org.matsim.core.mobsim.qsim.AbstractQSimModule;
import se.urbanEV.EvModule;
import se.urbanEV.config.UrbanEVConfigGroup;

/**
 * Vehicle Integrated Photovoltaic (VIPV)
 * created by OmkarP.(2026)
 */
public final class PvModule extends AbstractModule {

    @Inject private UrbanEVConfigGroup cfg;

    @Override
    public void install() {

        boolean pvEnabled =
                cfg != null &&
                        cfg.getPvWp() > 0.0 &&
                        (
                                (cfg.getPvVehiclesFile() != null && !cfg.getPvVehiclesFile().trim().isEmpty())
                                        || cfg.getPvShare() > 0.0
                        );

        if (!pvEnabled) {
            return;
        }

        bind(PvVehicleRegistry.class).asEagerSingleton();
        addControlerListenerBinding().to(PvVehicleRegistry.class);

        bind(PvChargingIntervalCollector.class).asEagerSingleton();
        addEventHandlerBinding().to(PvChargingIntervalCollector.class);

        bind(PvChargingStatsWriter.class).asEagerSingleton();
        addControlerListenerBinding().to(PvChargingStatsWriter.class);

        installQSimModule(new AbstractQSimModule() {
            @Override
            protected void configureQSim() {
                bind(PvGenerationHandler.class).asEagerSingleton();
                addQSimComponentBinding(EvModule.EV_COMPONENT).to(PvGenerationHandler.class);
            }
        });
    }
}
