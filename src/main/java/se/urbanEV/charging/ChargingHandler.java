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
 * copyright       : (C) 2015 by the members listed in the COPYING,        *
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


import com.google.inject.Inject;
import se.urbanEV.infrastructure.Charger;
import se.urbanEV.infrastructure.ChargingInfrastructure;
import org.matsim.contrib.ev.EvConfigGroup;
import org.matsim.core.config.Config;
import org.matsim.core.mobsim.framework.events.MobsimAfterSimStepEvent;
import org.matsim.core.mobsim.framework.events.MobsimBeforeCleanupEvent;
import org.matsim.core.mobsim.framework.listeners.MobsimAfterSimStepListener;
import org.matsim.core.mobsim.framework.listeners.MobsimBeforeCleanupListener;
import se.urbanEV.pv.PvGenerationHandler;

import java.util.ArrayList;

public class ChargingHandler implements MobsimAfterSimStepListener, MobsimBeforeCleanupListener {
	private final Iterable<Charger> chargers;
	private final int chargeTimeStep;
	private final PvGenerationHandler pvGenerationHandler;
	private final double qsimEndTime;
	private boolean finalized;

	@Inject
	public ChargingHandler(
			ChargingInfrastructure chargingInfrastructure,
			EvConfigGroup evConfig,
			PvGenerationHandler pvGenerationHandler,
			Config config) {
		this.chargers = chargingInfrastructure.getChargers().values();
		this.chargeTimeStep = evConfig.getChargeTimeStep();
		this.pvGenerationHandler = pvGenerationHandler;
		this.qsimEndTime = config.qsim().getEndTime().seconds();
	}

	@Override
	public void notifyMobsimAfterSimStep(@SuppressWarnings("rawtypes") MobsimAfterSimStepEvent e) {
		if ((e.getSimulationTime() + 1) % chargeTimeStep == 0) {
			for (Charger c : chargers) {
				// Revision (2026): update VIPV only for vehicles that are about to
				// receive grid energy.  Other vehicles are integrated analytically at
				// mobility-state transitions, avoiding a full-fleet loop every second.
				pvGenerationHandler.integrateVehiclesTo(
						c.getLogic().getChargingVehicles(), e.getSimulationTime());
				c.getLogic().chargeVehicles(chargeTimeStep, e.getSimulationTime());
			}
		}

		if (!finalized && Double.isFinite(qsimEndTime) && e.getSimulationTime() >= qsimEndTime) {
			finalizeAtHorizon();
		}
	}

	@Override
	public void notifyMobsimBeforeCleanup(MobsimBeforeCleanupEvent event) {
		if (!finalized && Double.isFinite(qsimEndTime)) {
			finalizeAtHorizon();
		}
	}

	/**
	 * Closes sessions at the configured QSim horizon.  The operation is
	 * idempotent so terminal SoC scoring can force completion before reading
	 * final battery states, independently of QSim listener ordering.
	 */
	public void finalizeAtHorizon() {
		if (finalized || !Double.isFinite(qsimEndTime)) {
			return;
		}
		double time = qsimEndTime;
		finalized = true;
		for (Charger c : chargers) {
			pvGenerationHandler.integrateVehiclesTo(c.getLogic().getChargingVehicles(), time);
			// Close partial sessions at the QSim horizon so their measured grid
			// energy is scored and written even when the final activity has no end.
			for (se.urbanEV.fleet.ElectricVehicle ev
					: new ArrayList<>(c.getLogic().getPluggedVehicles())) {
				c.getLogic().removeVehicleAtSimulationHorizon(ev, time);
			}
		}
	}
}
