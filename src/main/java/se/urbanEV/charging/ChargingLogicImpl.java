/*
File originally created, published and licensed by contributors of the org.matsim.* project.
Please consider the original license notice below.
This is a modified version of the original source code!

Modified 2020 by Lennart Adenaw, Technical University Munich, Chair of Automotive Technology
email	:	lennart.adenaw@tum.de
*/

/* ORIGINAL LICENSE
* *********************************************************************** *
 * project: org.matsim.*
 *                                                                         *
 * *********************************************************************** *
 *                                                                         *
 * copyright       : (C) 2016 by the members listed in the COPYING,        *
 *                   LICENSE and WARRANTY file.                            *
 * email           : info at matsim dot org                                *
 *                                                                         *
 * *********************************************************************** *
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *   See also COPYING, LICENSE and WARRANTY file                           *
 *                                                                         *
 * *********************************************************************** */

package se.urbanEV.charging;

import se.urbanEV.fleet.ElectricVehicle;
import se.urbanEV.infrastructure.Charger;
import org.matsim.api.core.v01.Id;
import org.matsim.core.api.experimental.events.EventsManager;

import java.util.*;

public class ChargingLogicImpl implements ChargingLogic {
	private final Charger charger;
	private final ChargingStrategy chargingStrategy;
	private final EventsManager eventsManager;

	private final Map<Id<ElectricVehicle>, ElectricVehicle> pluggedVehicles = new LinkedHashMap<>();
	private final Map<Id<ElectricVehicle>, Double> plugInTimestamps = new LinkedHashMap<>();
	private final Map<Id<ElectricVehicle>, ElectricVehicle> chargingVehicles = new LinkedHashMap<>();
	private final Map<Id<ElectricVehicle>, ChargingListener> listeners = new LinkedHashMap<>();

	// Actual energy accepted from the charger/grid during the active charging session [J].
	// This is deliberately tracked separately from battery SoC change because rooftop PV may increase SoC simultaneously.
	private final Map<Id<ElectricVehicle>, Double> gridEnergy_J = new LinkedHashMap<>();

	public ChargingLogicImpl(Charger charger, ChargingStrategy chargingStrategy, EventsManager eventsManager) {
		this.chargingStrategy = Objects.requireNonNull(chargingStrategy);
		this.charger = Objects.requireNonNull(charger);
		this.eventsManager = Objects.requireNonNull(eventsManager);
	}

	@Override
	public void chargeVehicles(double chargePeriod, double now) {
		Iterator<ElectricVehicle> evIter = chargingVehicles.values().iterator();

		while (evIter.hasNext()) {
			ElectricVehicle ev = evIter.next();

			double socBefore_J = ev.getBattery().getSoc();

			double chargingPower_W = ev.getChargingPower().calcChargingPower(charger);
			double requestedEnergy_J = chargingPower_W * chargePeriod;

			ev.getBattery().changeSoc(requestedEnergy_J);

			double socAfter_J = ev.getBattery().getSoc();

			// Energy actually accepted from this charger call.
			// BatteryImpl.changeSoc() already prevents charging above battery capacity.
			double acceptedGridEnergy_J = Math.max(0.0, socAfter_J - socBefore_J);

			gridEnergy_J.merge(
					ev.getId(),
					acceptedGridEnergy_J,
					Double::sum
			);

			if (chargingStrategy.isChargingCompleted(ev)) {

				double sessionGridEnergy_J =
						gridEnergy_J.getOrDefault(ev.getId(), 0.0);

				eventsManager.processEvent(
						new ChargingEndEvent(
								now,
								charger.getId(),
								ev.getId(),
								ev.getBattery().getSoc() / ev.getBattery().getCapacity(),
								now - plugInTimestamps.get(ev.getId()),
								sessionGridEnergy_J
						)
				);

				gridEnergy_J.remove(ev.getId());
				evIter.remove();
			}
		}
	}

	@Override
	public void addVehicle(ElectricVehicle ev, double now) {
		addVehicle(ev, new ChargingListener() {}, now);
	}

	@Override
	public void addVehicle(ElectricVehicle ev, ChargingListener chargingListener, double now) {
		listeners.put(ev.getId(), chargingListener);
		if (pluggedVehicles.size() < charger.getPlugCount()) {
			plugVehicle(ev, now);
		}
	}

	@Override
	public void removeVehicle(ElectricVehicle ev, double now) {
		if (pluggedVehicles.remove(ev.getId()) != null) { // successfully removed
			if (chargingVehicles.remove(ev.getId()) != null) {
				double sessionGridEnergy_J = gridEnergy_J.getOrDefault(ev.getId(), 0.0);

				eventsManager.processEvent(
						new ChargingEndEvent(
								now,
								charger.getId(),
								ev.getId(),
								ev.getBattery().getSoc() / ev.getBattery().getCapacity(),
								now - plugInTimestamps.get(ev.getId()),
								sessionGridEnergy_J
						)
				);
				gridEnergy_J.remove(ev.getId());
			}
			eventsManager.processEvent(new UnpluggingEvent(now, charger.getId(), ev.getId(), now-plugInTimestamps.get(ev.getId())));
			listeners.remove(ev.getId()).notifyChargingEnded(ev, now);

		} else { // not plugged
			throw new IllegalArgumentException(
					"Vehicle: " + ev.getId() + " is not plugged at charger: " + charger.getId());
		}
	}

	private void plugVehicle(ElectricVehicle ev, double now) {
		if (pluggedVehicles.put(ev.getId(), ev) != null) {
			throw new IllegalArgumentException();
		}
		if (chargingVehicles.put(ev.getId(), ev) != null) {
			throw new IllegalArgumentException();
		}
		gridEnergy_J.put(ev.getId(), 0.0);
		eventsManager.processEvent(
				new ChargingStartEvent(
						now,
						charger.getId(),
						ev.getId(),
						charger.getChargerType()
				)
		);
		listeners.get(ev.getId()).notifyChargingStarted(ev, now);
		plugInTimestamps.put(ev.getId(), now);
	}

	private final Collection<ElectricVehicle> unmodifiablePluggedVehicles = Collections.unmodifiableCollection(
			pluggedVehicles.values());

	@Override
	public Collection<ElectricVehicle> getPluggedVehicles() {
		return unmodifiablePluggedVehicles;
	}

	@Override
	public ChargingStrategy getChargingStrategy() {
		return chargingStrategy;
	}
}
