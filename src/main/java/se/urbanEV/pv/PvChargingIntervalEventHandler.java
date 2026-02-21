package se.urbanEV.pv;

import org.matsim.core.events.handler.EventHandler;

/**
 * Vehicle Integrated Photovoltaic (VIPV)
 * created by OmkarP.(2026)
 */
public interface PvChargingIntervalEventHandler extends EventHandler {
    void handleEvent(PvChargingIntervalEvent event);
}
