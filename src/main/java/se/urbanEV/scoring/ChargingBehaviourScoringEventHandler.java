package se.urbanEV.scoring;

import org.matsim.core.events.handler.EventHandler;

public interface ChargingBehaviourScoringEventHandler extends EventHandler {
    void handleEvent(ChargingBehaviourScoringEvent event);

}