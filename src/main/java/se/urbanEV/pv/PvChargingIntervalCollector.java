package se.urbanEV.pv;

import javax.inject.Singleton;
import java.util.ArrayList;
import java.util.List;

/**
 * Vehicle Integrated Photovoltaic (VIPV)
 * created by OmkarP.(2026)
 */
@Singleton
public final class PvChargingIntervalCollector implements PvChargingIntervalEventHandler {

    private final List<PvChargingIntervalEvent> events = new ArrayList<>();

    @Override
    public synchronized void handleEvent(PvChargingIntervalEvent event) {
        events.add(event);
    }

    public synchronized List<PvChargingIntervalEvent> drain() {
        List<PvChargingIntervalEvent> out = new ArrayList<>(events);
        events.clear();
        return out;
    }
}
