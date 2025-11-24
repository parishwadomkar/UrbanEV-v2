/*
File originally created, published and licensed by contributors of the org.matsim.* project.
Please consider the original license notice below.
This is a modified version of the original source code!

Modified 2020 by Lennart Adenaw, Technical University Munich, Chair of Automotive Technology
email	:	lennart.adenaw@tum.de
*/

/* ORIGINAL LICENSE
 *  *********************************************************************** *
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
/*
 * created by jbischoff, 09.10.2018
 *  This is an events based approach to trigger vehicle charging. Vehicles will be charged as soon as a person begins a charging activity.
 */

import se.urbanEV.MobsimScopeEventHandling;
import se.urbanEV.config.UrbanEVConfigGroup;
import se.urbanEV.fleet.ElectricFleet;
import se.urbanEV.fleet.ElectricVehicle;
import se.urbanEV.infrastructure.Charger;
import se.urbanEV.infrastructure.ChargingInfrastructure;
import se.urbanEV.scoring.ChargingBehaviourScoringEvent;
import org.apache.log4j.Logger;
import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.events.ActivityEndEvent;
import org.matsim.api.core.v01.events.ActivityStartEvent;
import org.matsim.api.core.v01.events.PersonLeavesVehicleEvent;
import org.matsim.api.core.v01.events.handler.ActivityEndEventHandler;
import org.matsim.api.core.v01.events.handler.ActivityStartEventHandler;
import org.matsim.api.core.v01.events.handler.PersonLeavesVehicleEventHandler;
import org.matsim.api.core.v01.network.Network;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.PlanElement;
import org.matsim.api.core.v01.population.Population;
import org.matsim.contrib.ev.MobsimScopeEventHandler;
import org.matsim.contrib.util.PartialSort;
import org.matsim.contrib.util.distance.DistanceUtils;
import org.matsim.core.api.experimental.events.EventsManager;
import org.matsim.vehicles.Vehicle;

import javax.inject.Inject;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public class VehicleChargingHandler
        implements ActivityStartEventHandler, ActivityEndEventHandler, PersonLeavesVehicleEventHandler,
        ChargingEndEventHandler, MobsimScopeEventHandler {

    private static final Logger log = Logger.getLogger(VehicleChargingHandler.class);

    public static final String CHARGING_IDENTIFIER = " charging";
    private Map<Id<Person>, Id<Vehicle>> lastVehicleUsed = new HashMap<>();
    private Map<Id<ElectricVehicle>, Id<Charger>> vehiclesAtChargers = new HashMap<>();

    // track SOC and time at the start of each charging session: OmkarP.(2025)
    private final Map<Id<ElectricVehicle>, Double> chargeStartSoc = new HashMap<>();
    private final Map<Id<ElectricVehicle>, Double> chargeStartTime = new HashMap<>();

	private final ChargingInfrastructure chargingInfrastructure;
	private final Network network;
	private final ElectricFleet electricFleet;
	private final Population population;
	private final int parkingSearchRadius;

	private final EventsManager eventsManager;

	@Inject
	public VehicleChargingHandler(ChargingInfrastructure chargingInfrastructure,
								  Network network,
								  ElectricFleet electricFleet,
								  Population population,
								  EventsManager eventsManager,
								  MobsimScopeEventHandling events,
								  UrbanEVConfigGroup urbanEVCfg) {
		this.chargingInfrastructure = chargingInfrastructure;
		this.network = network;
		this.electricFleet = electricFleet;
		this.population = population;
		this.eventsManager = eventsManager;
		this.parkingSearchRadius = urbanEVCfg.getParkingSearchRadius();
		events.addMobsimScopeHandler(this);
	}

	@Override
	public void handleEvent(ActivityStartEvent event) {
		String actType = event.getActType();
		Id<Person> personId = event.getPersonId();
		Id<Vehicle> vehicleId = lastVehicleUsed.get(personId);
		if (vehicleId != null) {
			Id<ElectricVehicle> evId = Id.create(vehicleId, ElectricVehicle.class);
			if (electricFleet.getElectricVehicles().containsKey(evId)) {
				ElectricVehicle ev = electricFleet.getElectricVehicles().get(evId);
				Person person = population.getPersons().get(personId);
				double walkingDistance = 0.0;

                if (event.getActType().endsWith(CHARGING_IDENTIFIER)) {
                    Activity activity = getActivity(person, event.getTime());
                    Coord activityCoord = activity != null ?
                            activity.getCoord() : network.getLinks().get(event.getLinkId()).getCoord();
                    Charger selectedCharger = findBestCharger(activityCoord, ev);

                    if (selectedCharger != null) { // if charger was found, start charging
                        selectedCharger.getLogic().addVehicle(ev, event.getTime());
                        vehiclesAtChargers.put(evId, selectedCharger.getId());
                        walkingDistance = DistanceUtils.calculateDistance(activityCoord, selectedCharger.getCoord());

                        // remember SOC and time at start of this charging session: OmkarP.(2025)
                        double socFraction = ev.getBattery().getSoc() / ev.getBattery().getCapacity(); // 0..1
                        chargeStartSoc.put(evId, socFraction);
                        chargeStartTime.put(evId, event.getTime());

                    } else {
                        // if no charger was found, mark as failed attempt in plan
                        if (activity != null) {
                            actType = activity.getType() + " failed";
                            activity.setType(actType);
                        }
                    }
                }

                double time = event.getTime();
				double soc = ev.getBattery().getSoc() / ev.getBattery().getCapacity();
				double startSoc = ev.getBattery().getStartSoc() / ev.getBattery().getCapacity();
				// if (soc <= 0) { log.error("EV " + ev.getId().toString() + " has empty battery."); }
				eventsManager.processEvent(new ChargingBehaviourScoringEvent(time, personId, soc,
						walkingDistance, actType, startSoc));
			}
		}
	}

    @Override
    public void handleEvent(ActivityEndEvent event) {
        if (event.getActType().endsWith(CHARGING_IDENTIFIER)) {
            Id<Vehicle> vehicleId = lastVehicleUsed.get(event.getPersonId());
            if (vehicleId != null) {
                Id<ElectricVehicle> evId = Id.create(vehicleId, ElectricVehicle.class);
                ElectricVehicle ev = electricFleet.getElectricVehicles().get(evId);

                // compute energy charged during this session and emit cost-only scoring event: OmkarP.(2025)
                if (ev != null) {
                    Double startSocFrac = chargeStartSoc.remove(evId);
                    Double startTime = chargeStartTime.remove(evId);

                    double energyChargedKWh = 0.0;
                    if (startSocFrac != null) {
                        double currentSocFrac = ev.getBattery().getSoc() / ev.getBattery().getCapacity();
                        double deltaSocFrac = currentSocFrac - startSocFrac;
                        if (deltaSocFrac > 0.0) {  // capacity in internal energy units; converted to kWh via 3.6e6
                            double capacityKWh = ev.getBattery().getCapacity() / 3_600_000.0;
                            energyChargedKWh = deltaSocFrac * capacityKWh;
                        }
                    }

                    if (energyChargedKWh > 0.0) {
                        double pricingTime = (startTime != null) ? startTime : event.getTime();

                        // classify charger type from activity type ("home charging", "work charging", else public)
                        String actType = event.getActType();
                        String chargerType;
                        if (actType.startsWith("home")) {
                            chargerType = "home";
                        } else if (actType.startsWith("work")) {
                            chargerType = "work";
                        } else {
                            chargerType = "public";
                        }

                        double socFrac = ev.getBattery().getSoc() / ev.getBattery().getCapacity();
                        double startSocForScore = ev.getBattery().getStartSoc() / ev.getBattery().getCapacity();

                        // cost-only event: EV scoring will skip non-cost components when costOnly == true
                        eventsManager.processEvent(new ChargingBehaviourScoringEvent(
                                event.getTime(),                // event time
                                event.getPersonId(),
                                socFrac,
                                0.0,                            // no walking component here
                                actType,
                                startSocForScore,
                                pricingTime,                    // pricingTime for ToU
                                energyChargedKWh,
                                chargerType,
                                true                            // costOnly
                        ));
                    }
                }

                // removal from charger logic
                Id<Charger> chargerId = vehiclesAtChargers.remove(evId);
                if (chargerId != null) {
                    Charger charger = chargingInfrastructure.getChargers().get(chargerId);
                    charger.getLogic().removeVehicle(electricFleet.getElectricVehicles().get(evId), event.getTime());
                }
            }
        }
    }

    @Override
	public void handleEvent(PersonLeavesVehicleEvent event) {
		lastVehicleUsed.put(event.getPersonId(), event.getVehicleId());
	}

	@Override
	public void handleEvent(ChargingEndEvent event) {
		// vehiclesAtChargers.remove(event.getVehicleId());
		// Charging has ended before activity ends
	}

	/**
	 * gets ativity from agent's plan by looking for current time
	 * @param person
	 * @param time
	 * @return
	 */
	private Activity getActivity(Person person, double time){
		Activity activity = null;
		List<PlanElement> planElements = person.getSelectedPlan().getPlanElements();
		for (int i = 0; i < planElements.size(); i++) {
			PlanElement planElement = planElements.get(i);
			if (planElement instanceof Activity) {
				if (((Activity) planElement).getEndTime().isDefined()) {
					double activityEndTime = ((Activity) planElement).getEndTime().seconds();
					if (activityEndTime > time || i == planElements.size() - 1) {
						activity = ((Activity) planElement);
						break;
					}
				}
				else if (i == planElements.size() - 1) {
					// Accept a missing end time for the last activity of a plan
					activity = ((Activity) planElement);
					break;
				}
				else{
					// There is a missing end time for an activity that is not the plan's last -> This should end in null being returned
					continue;
				}
			}
		}
		if (activity != null) {
			return activity;
		}
		else return null;
	}

	/**
	 * Tries to find closest free charger of fitting type in vicinity of activity location
	 * If a charger is private, only allowed vehicles can charge there
	 */

	private Charger findBestCharger(Coord stopCoord, ElectricVehicle electricVehicle) {

		List<Charger> filteredChargers = new ArrayList<>();
		chargingInfrastructure.getChargers().values().forEach(charger -> {
			// filter out private chargers unless vehicle is allowed
			if (charger.getAllowedVehicles().isEmpty() || charger.getAllowedVehicles().contains(electricVehicle.getId())) {
				// filter out chargers that are out of range
				if (DistanceUtils.calculateDistance(stopCoord, charger.getCoord()) < parkingSearchRadius) {
					// filter out chargers with wrong type
					if (electricVehicle.getChargerTypes().contains(charger.getChargerType())) {
						// filter out occupied chargers
						if ((charger.getLogic().getPluggedVehicles().size() < charger.getPlugCount())) {
							filteredChargers.add(charger);
						}
					}
				}
			}
		});

		List<Charger> nearestChargers = PartialSort.kSmallestElements(1, filteredChargers.stream(),
				(charger) -> DistanceUtils.calculateSquaredDistance(stopCoord, charger.getCoord()));

		if (!nearestChargers.isEmpty()) {
			return nearestChargers.get(0);
		} else {
			 log.error("No charger found for EV " + electricVehicle.getId().toString() + " at location " + stopCoord.toString());
			return null;
		}
	}
}
