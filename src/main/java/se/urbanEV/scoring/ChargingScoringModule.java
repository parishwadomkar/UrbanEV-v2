package se.urbanEV.scoring;

import org.matsim.core.controler.AbstractModule;
import org.matsim.core.mobsim.qsim.AbstractQSimModule;
import se.urbanEV.EvModule;
import se.urbanEV.planning.ChargingSocClassificationHandler;

/** Registers terminal SoC scoring and the single charging-plan classifier. */
public final class ChargingScoringModule extends AbstractModule {
    @Override
    public void install() {
        addEventHandlerBinding()
                .to(ChargingSocClassificationHandler.class);

        installQSimModule(new AbstractQSimModule() {
            @Override
            protected void configureQSim() {
                bind(TerminalSocScoringHandler.class).asEagerSingleton();
                addQSimComponentBinding(EvModule.EV_COMPONENT)
                        .to(TerminalSocScoringHandler.class);
            }
        });
    }
}
