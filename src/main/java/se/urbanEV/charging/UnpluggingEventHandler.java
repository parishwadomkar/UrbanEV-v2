package se.urbanEV.charging;

import org.matsim.core.events.handler.EventHandler;

public interface UnpluggingEventHandler extends EventHandler {
    void handleEvent(UnpluggingEvent event);

}
