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

import org.matsim.core.config.Config;
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
    private final Map<Id<Person>, Id<Vehicle>> lastVehicleUsed = new HashMap<>();
    private final Map<Id<ElectricVehicle>, Id<Charger>> vehiclesAtChargers = new HashMap<>();

    // Revision (2026): retain one authoritative context per charging session.
    // Grid energy is supplied by ChargingEndEvent; battery-SOC differences are
    // not used because they may contain simultaneous rooftop-PV generation.
    private final Map<Id<ElectricVehicle>, ChargingSessionContext> chargingSessions = new HashMap<>();

    private final ChargingInfrastructure chargingInfrastructure;
    private final Network network;
    private final ElectricFleet electricFleet;
    private final Population population;
    private final int parkingSearchRadius;
    private final EventsManager eventsManager;
    private final double qsimEndTime;

    // scheduler for smart charging: OmkarP.(2025)
    private final UrbanEVConfigGroup urbanEvCfg;
    private final SmartChargingScheduler smartScheduler;

    @Inject
    public VehicleChargingHandler(ChargingInfrastructure chargingInfrastructure,
                                  Network network,
                                  ElectricFleet electricFleet,
                                  Population population,
                                  EventsManager eventsManager,
                                  MobsimScopeEventHandling events,
                                  UrbanEVConfigGroup urbanEVCfg,
                                  Config config) {
        this.chargingInfrastructure = chargingInfrastructure;
        this.network = network;
        this.electricFleet = electricFleet;
        this.population = population;
        this.eventsManager = eventsManager;
        this.parkingSearchRadius = urbanEVCfg.getParkingSearchRadius();
        this.urbanEvCfg = urbanEVCfg;

        this.qsimEndTime = config.qsim().getEndTime().seconds();
        this.smartScheduler = new SmartChargingScheduler(chargingInfrastructure, electricFleet, this);
        events.addMobsimScopeHandler(this);
    }

    /**
     * Implemented by omkarp, 10.01.2025
     * Called by SmartChargingScheduler when a deferred home-charging session actually plugs in.
     * Finalizes the pending session context with the actual plug-in time.
     */
    public void onSmartChargePlugged(Id<ElectricVehicle> evId, Id<Charger> chargerId, double time) {
        ElectricVehicle ev = electricFleet.getElectricVehicles().get(evId);
        if (ev == null) {
            log.warn("onSmartChargePlugged: EV " + evId + " not found in fleet at t=" + time);
            return;
        }

        vehiclesAtChargers.put(evId, chargerId);

        ChargingSessionContext context = chargingSessions.get(evId);
        if (context == null) {
            throw new IllegalStateException(
                    "Deferred charging started without a registered session context for EV " + evId);
        }
        context.startTime = time;
        context.chargerId = chargerId;

        if (log.isDebugEnabled()) {
            double socFraction = ev.getBattery().getSoc() / ev.getBattery().getCapacity();
            log.debug(String.format(
                    "onSmartChargePlugged: EV %s plugged at charger %s at t=%.0f, soc=%.3f",
                    evId, chargerId, time, socFraction
            ));
        }
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
                    Coord activityCoord = activity != null
                            ? activity.getCoord()
                            : network.getLinks().get(event.getLinkId()).getCoord();
                    Charger selectedCharger = findBestCharger(activityCoord, ev);

                    if (selectedCharger != null) {
                        boolean isHomeChargingAct =
                                actType.startsWith("home") && actType.endsWith(CHARGING_IDENTIFIER);

                        // Revision (2026-09): smart home-ToU rescheduling must
                        // follow the charger that will actually deliver the
                        // energy, not only the activity label.  A home charging
                        // activity can fall back to a nearby public charger;
                        // delaying that session with a home tariff while later
                        // pricing it as public charging is inconsistent.
                        String selectedChargerAccessType =
                                ChargingCostUtils.getChargerAccessType(
                                        selectedCharger.getId().toString());
                        boolean isActualHomeCharger =
                                "home".equalsIgnoreCase(selectedChargerAccessType);

                        // default: immediate charging (for non-home or smart disabled)
                        boolean smartEnabled = urbanEvCfg.isEnableSmartCharging()
                                && isHomeChargingAct
                                && isActualHomeCharger;

                        // Smart ToU aware rescheduling: OmkarP.(2025)
                        if (smartEnabled && activity != null) {
                            double arrivalTime = event.getTime();

                            double departureTime;
                            if (activity.getEndTime().isDefined()) {
                                departureTime = activity.getEndTime().seconds();
                            } else {
                                departureTime = qsimEndTime;
                            }

                            if (departureTime > arrivalTime) {
                                // Energy missing is held internally in joules and converted below to kWh.
                                double energyRequiredJ = ev.getBattery().getCapacity() - ev.getBattery().getSoc();
                                if (energyRequiredJ < 0.0) {
                                    energyRequiredJ = 0.0;
                                }
                                double energyRequiredKWh = energyRequiredJ / 3_600_000.0;

                                // approximate charging duration using person home charger power if present, else default (kW)
                                double powerKW = urbanEvCfg.getDefaultHomeChargerPower();
                                Object pHomeP = person.getAttributes().getAttribute("homeChargerPower");
                                if (pHomeP != null) {
                                    try { powerKW = Double.parseDouble(pHomeP.toString()); } catch (Exception ignored) { }
                                }

                                double effectiveKW = Math.max(0.1, 0.85 * powerKW);
                                double chargingDuration = (energyRequiredKWh / effectiveKW) * 3600.0;
                                double maxDur = Math.max(0.0, departureTime - arrivalTime);
                                chargingDuration = Math.min(chargingDuration, maxDur);

                                // Person-level awareness from attributes
                                Object awareAttr = person.getAttributes().getAttribute("smartChargingAware");
                                boolean isAware = false;
                                if (awareAttr instanceof Boolean) {
                                    isAware = (Boolean) awareAttr;
                                } else if (awareAttr instanceof String) {
                                    isAware = Boolean.parseBoolean((String) awareAttr);
                                }

                                double optimalStart = SmartChargingTouHelper.computeOptimalStartTime(
                                        arrivalTime,
                                        departureTime,
                                        chargingDuration,
                                        urbanEvCfg,
                                        selectedCharger,
                                        ev,
                                        isAware
                                );

                                if (log.isDebugEnabled()) {
                                    log.debug(String.format(
                                            "SmartCharging: person=%s aware=%s homeAct=true arr=%.0f dep=%.0f dur≈%.0fs - optimalStart=%.0f",
                                            personId, isAware, arrivalTime, departureTime, chargingDuration, optimalStart
                                    ));
                                }

                                if (optimalStart > arrivalTime + 1.0) {
                                    // schedule deferred plug-in
                                    registerChargingSession(
                                            evId, personId, actType, Double.NaN, selectedCharger.getId());
                                    smartScheduler.schedule(evId, selectedCharger.getId(), optimalStart);
                                    walkingDistance = DistanceUtils.calculateDistance(activityCoord, selectedCharger.getCoord());

                                    log.info(String.format(
                                            "Smart home charging: EV %s defers from t=%.0f to t=%.0f (window %.0f–%.0f, dur≈%.0fs)",
                                            ev.getId(), arrivalTime, optimalStart, arrivalTime, departureTime, chargingDuration
                                    ));

                                } else {
                                    // optimum is effectively "now" (or agent not aware) fall back to immediate charging
                                    registerChargingSession(
                                            evId, personId, actType, arrivalTime, selectedCharger.getId());
                                    selectedCharger.getLogic().addVehicle(ev, arrivalTime);
                                    vehiclesAtChargers.put(evId, selectedCharger.getId());
                                    walkingDistance = DistanceUtils.calculateDistance(activityCoord, selectedCharger.getCoord());
                                }
                            } else {
                                // fallback immediate
                                double t = event.getTime();
                                registerChargingSession(
                                        evId, personId, actType, t, selectedCharger.getId());
                                selectedCharger.getLogic().addVehicle(ev, t);
                                vehiclesAtChargers.put(evId, selectedCharger.getId());
                                walkingDistance = DistanceUtils.calculateDistance(activityCoord, selectedCharger.getCoord());
                            }
                        } else {
                            // non-home charging or smart disabled: legacy behaviour
                            double t = event.getTime();
                            registerChargingSession(
                                    evId, personId, actType, t, selectedCharger.getId());
                            selectedCharger.getLogic().addVehicle(ev, t);
                            vehiclesAtChargers.put(evId, selectedCharger.getId());
                            walkingDistance = DistanceUtils.calculateDistance(activityCoord, selectedCharger.getCoord());
                        }

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

                // cancel any deferred schedule if the charging act ends
                if (smartScheduler != null) {
                    smartScheduler.cancelIfScheduled(evId);
                }

                // removal from charger logic
                Id<Charger> chargerId = vehiclesAtChargers.remove(evId);
                if (chargerId != null) {
                    Charger charger = chargingInfrastructure.getChargers().get(chargerId);
                    ElectricVehicle ev = electricFleet.getElectricVehicles().get(evId);
                    if (charger == null || ev == null) {
                        throw new IllegalStateException(
                                "Cannot end charging session for EV " + evId + " at charger " + chargerId);
                    }
                    // ChargingLogic emits the authoritative ChargingEndEvent synchronously.
                    charger.getLogic().removeVehicle(ev, event.getTime());
                } else {
                    // A deferred session may be cancelled before the scheduled plug-in.
                    ChargingSessionContext context = chargingSessions.get(evId);
                    if (context != null && !Double.isFinite(context.startTime)) {
                        chargingSessions.remove(evId);
                    }
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
        Id<ElectricVehicle> evId = event.getVehicleId();
        ChargingSessionContext context = chargingSessions.remove(evId);
        if (context == null) {
            throw new IllegalStateException(
                    "ChargingEndEvent without an active session context for EV " + evId);
        }
        if (!context.chargerId.equals(event.getChargerId())) {
            throw new IllegalStateException(
                    "ChargingEndEvent charger mismatch for EV " + evId
                            + ": expected=" + context.chargerId + ", event=" + event.getChargerId());
        }
        if (!Double.isFinite(context.startTime) || event.getTime() < context.startTime) {
            throw new IllegalStateException(
                    "Invalid charging interval for EV " + evId + ": start="
                            + context.startTime + ", end=" + event.getTime());
        }

        ElectricVehicle ev = electricFleet.getElectricVehicles().get(evId);
        if (ev == null) {
            throw new IllegalStateException("ChargingEndEvent for EV not present in fleet: " + evId);
        }

        // Revision (2026): price only charger/grid-delivered energy. Rooftop-PV
        // energy is deliberately excluded from this event-level quantity.
        double gridEnergyKWh = event.getGridEnergy_J() / 3_600_000.0;
        if (gridEnergyKWh <= 0.0) {
            return;
        }

        // Revision (2026-09): price the session according to the charger that
        // actually delivered the grid energy.  A charging activity at home or
        // work can be served by a nearby public charger; inferring the access
        // type from the activity label therefore understated behavioural costs
        // and disagreed with chargingStats.csv, which already uses charger IDs.
        String chargerAccessType = ChargingCostUtils.getChargerAccessType(
                event.getChargerId().toString());
        double socFrac = ev.getBattery().getSoc() / ev.getBattery().getCapacity();
        double startSocForScore = ev.getBattery().getStartSoc() / ev.getBattery().getCapacity();

        // Cost-only event: non-cost scoring components are skipped by the scorer.
        eventsManager.processEvent(new ChargingBehaviourScoringEvent(
                event.getTime(),
                context.personId,
                socFrac,
                0.0,
                context.activityType,
                startSocForScore,
                context.startTime,
                gridEnergyKWh,
                chargerAccessType,
                true
        ));

        if (log.isDebugEnabled()) {
            double durationHours = Math.max(1e-9, (event.getTime() - context.startTime) / 3600.0);
            log.debug(String.format(
                    "Grid charging session: person=%s ev=%s access=%s start=%.0f end=%.0f grid_kWh=%.3f avg_kW=%.3f",
                    context.personId, evId, chargerAccessType, context.startTime,
                    event.getTime(), gridEnergyKWh, gridEnergyKWh / durationHours));
        }
    }

    private void registerChargingSession(
            Id<ElectricVehicle> evId,
            Id<Person> personId,
            String activityType,
            double startTime,
            Id<Charger> chargerId) {

        ChargingSessionContext context = new ChargingSessionContext(
                personId, activityType, startTime, chargerId);
        ChargingSessionContext previous = chargingSessions.putIfAbsent(evId, context);
        if (previous != null) {
            throw new IllegalStateException(
                    "Attempted to register overlapping charging sessions for EV " + evId);
        }
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
					if (electricVehicle.getChargerTypes().contains(charger.getChargerType())) {
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

    public void tick(double now) {
        if (smartScheduler != null) {
            smartScheduler.processDueTasks(now);
        }
    }

    @Override
    public void reset(int iteration) {
        lastVehicleUsed.clear();
        vehiclesAtChargers.clear();
        chargingSessions.clear();

        if (smartScheduler != null) {
            log.info(smartScheduler.consumeStatsLine(iteration));
            smartScheduler.reset();
        }
    }

    private static final class ChargingSessionContext {
        private final Id<Person> personId;
        private final String activityType;
        private double startTime;
        private Id<Charger> chargerId;

        private ChargingSessionContext(
                Id<Person> personId,
                String activityType,
                double startTime,
                Id<Charger> chargerId) {
            this.personId = personId;
            this.activityType = activityType;
            this.startTime = startTime;
            this.chargerId = chargerId;
        }
    }
}
