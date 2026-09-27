package se.urbanEV.pv;

import org.matsim.core.controler.AbstractModule;
import org.matsim.core.mobsim.qsim.AbstractQSimModule;
import se.urbanEV.EvModule;

/**
 * Vehicle Integrated Photovoltaic (VIPV)
 * created by OmkarP.(2026)
 */
public final class PvModule extends AbstractModule {
    @Override
    public void install() {
        // Revision (2026): these bindings must also exist for noVIPV controls.
        // Charging and discharging handlers synchronize through
        // PvGenerationHandler unconditionally. With pvWp=0 and an empty
        // registry, the handler is an inert no-op service.
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
