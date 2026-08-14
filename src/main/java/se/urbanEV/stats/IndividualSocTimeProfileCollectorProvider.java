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

package se.urbanEV.stats;

import com.google.inject.Inject;
import com.google.inject.Provider;
import se.urbanEV.fleet.ElectricFleet;
import se.urbanEV.fleet.ElectricVehicle;
import org.matsim.contrib.ev.EvUnits;
import org.matsim.contrib.util.timeprofile.TimeProfileCollector;
import org.matsim.contrib.util.timeprofile.TimeProfileCollector.ProfileCalculator;
import org.matsim.contrib.util.timeprofile.TimeProfiles;
import org.matsim.core.controler.MatsimServices;
import org.matsim.core.mobsim.framework.listeners.MobsimListener;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Objects;
import java.util.stream.Collectors;
import org.matsim.api.core.v01.Id;

public class IndividualSocTimeProfileCollectorProvider implements Provider<MobsimListener> {
	private final ElectricFleet evFleet;
	private final MatsimServices matsimServices;

	@Inject
	public IndividualSocTimeProfileCollectorProvider(ElectricFleet evFleet, MatsimServices matsimServices) {
		this.evFleet = evFleet;
		this.matsimServices = matsimServices;
	}

	@Override
	public MobsimListener get() {
		ProfileCalculator calc = createIndividualSocCalculator(evFleet);
		return new TimeProfileCollector(calc, 300, "individual_soc_time_profiles", matsimServices);
	}

	//	Instead of plotting random EV soc profiles, we choose to output the same EV profiles for each iteration (OmkarP.2026)
//	private static final List<Id<ElectricVehicle>> FIXED_EV_IDS = List.of(
//			Id.create("4606454", ElectricVehicle.class),
//			Id.create("7326174", ElectricVehicle.class),
//			Id.create("4772272", ElectricVehicle.class),
//			Id.create("9430738", ElectricVehicle.class),
//			Id.create("4661955", ElectricVehicle.class),
//			Id.create("7379363", ElectricVehicle.class),
//			Id.create("7298683", ElectricVehicle.class),
//			Id.create("9460907", ElectricVehicle.class),
//			Id.create("4923381", ElectricVehicle.class),
//			Id.create("4604173", ElectricVehicle.class),
//			Id.create("7442665", ElectricVehicle.class),
//			Id.create("2129349", ElectricVehicle.class)
//	);
//
//		public static ProfileCalculator createIndividualSocCalculator(final ElectricFleet evFleet) {
//		List<ElectricVehicle> selectedEvs = FIXED_EV_IDS.stream()
//				.map(id -> evFleet.getElectricVehicles().get(id))
//				.filter(Objects::nonNull)
//				.collect(Collectors.toList());
//
//		String[] header = selectedEvs.stream().map(ev -> ev.getId().toString()).toArray(String[]::new);
//
//		return TimeProfiles.createProfileCalculator(header, () ->
//				selectedEvs.stream()
//						.map(ev -> EvUnits.J_to_kWh(ev.getBattery().getSoc()))
//						.toArray(Double[]::new)
//		);
//	}

	private static final int MAX_VEHICLE_COLUMNS = 10;

	public static ProfileCalculator createIndividualSocCalculator(final ElectricFleet evFleet) {
		int columns = Math.min(evFleet.getElectricVehicles().size(), MAX_VEHICLE_COLUMNS);
		List<ElectricVehicle> allEvs = new ArrayList<>();
		allEvs.addAll(evFleet.getElectricVehicles().values());
		Collections.shuffle(allEvs);
		List<ElectricVehicle> selectedEvs = allEvs.stream().limit(columns).collect(Collectors.toList());

		String[] header = selectedEvs.stream().map(ev -> ev.getId() + "").toArray(String[]::new);

		return TimeProfiles.createProfileCalculator(header, () -> {
			return selectedEvs.stream().map(ev -> EvUnits.J_to_kWh(ev.getBattery().getSoc()))/*in [kWh]*/
					.toArray(Double[]::new);
		});
	}
}
