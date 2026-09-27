package se.urbanEV.scoring;

import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.api.internal.HasPersonId;

import java.util.Map;

public class ChargingBehaviourScoringEvent extends Event implements HasPersonId {
    public static final String EVENT_TYPE = "scoring";

    private final Id<Person> personId;
    private final Double soc;
    private final Double walkingDistance;
    private final String activityType;
    private final Double startSoc;
    private final Double energyChargedKWh;
    private final String chargerType;
    private final boolean costOnly;
    private final boolean terminalSocOnly;
    private final Double pricingTime;

    // Backward-compatible constructor (no cost info): OmkarP.(2025)
    public ChargingBehaviourScoringEvent(double time,
                                         Id<Person> personId,
                                         Double soc,
                                         Double walkingDistance,
                                         String activityType,
                                         double startSoc) {
        this(time, personId, soc, walkingDistance, activityType, startSoc,
                null, null, null, false, false);
    }

    // Constructor with charging cost info: OmkarP.(2025)
    public ChargingBehaviourScoringEvent(double time,
                                         Id<Person> personId,
                                         Double soc,
                                         Double walkingDistance,
                                         String activityType,
                                         double startSoc,
                                         Double pricingTime,
                                         Double energyChargedKWh,
                                         String chargerType,
                                         boolean costOnly) {
        this(time, personId, soc, walkingDistance, activityType, startSoc,
                pricingTime, energyChargedKWh, chargerType, costOnly, false);
    }

    private ChargingBehaviourScoringEvent(double time,
                                           Id<Person> personId,
                                           Double soc,
                                           Double walkingDistance,
                                           String activityType,
                                           double startSoc,
                                           Double pricingTime,
                                           Double energyChargedKWh,
                                           String chargerType,
                                           boolean costOnly,
                                           boolean terminalSocOnly) {
        super(time);
        this.personId = personId;
        this.soc = soc;
        this.walkingDistance = walkingDistance;
        this.activityType = activityType;
        this.startSoc = startSoc;

        this.pricingTime = pricingTime;
        this.energyChargedKWh = energyChargedKWh;
        this.chargerType = chargerType;
        this.costOnly = costOnly;
        this.terminalSocOnly = terminalSocOnly;
    }

    /**
     * Creates one explicit end-of-horizon SoC event for terminal energy-balance
     * scoring.  It is intentionally separate from activity and charging-cost
     * events so the terminal penalty is applied exactly once per EV and iteration.
     */
    public static ChargingBehaviourScoringEvent terminalSoc(
            double time,
            Id<Person> personId,
            double soc,
            double startSoc) {
        return new ChargingBehaviourScoringEvent(
                time,
                personId,
                soc,
                0.0,
                "simulation end",
                startSoc,
                null,
                null,
                null,
                false,
                true);
    }

    @Override
    public Id<Person> getPersonId() {
        return personId;
    }
    public Double getSoc() {
        return soc;
    }
    public Double getWalkingDistance() {
        return walkingDistance;
    }
    public String getActivityType() { return activityType; }
    public Double getStartSoc() { return startSoc; }

    @Override
    public String getEventType() {
        return EVENT_TYPE;
    }

    //    OmkarP.(2025)
    public Double getPricingTime() { return pricingTime;  }
    public Double getEnergyChargedKWh() {
        return energyChargedKWh;
    }
    public String getChargerType() {
        return chargerType;
    }
    public boolean isCostOnly() {
        return costOnly;
    }
    public boolean isTerminalSocOnly() {
        return terminalSocOnly;
    }

    @Override
    public Map<String, String> getAttributes() {
        Map<String, String> attributes = super.getAttributes();
        if (soc != null) { attributes.put("soc", soc.toString()); }
        if (walkingDistance != null) { attributes.put("walkingDistance", walkingDistance.toString()); }
        if (activityType != null) { attributes.put("activityType", activityType); }
        if (startSoc != null) { attributes.put("startSoc", startSoc.toString()); }

        if (energyChargedKWh != null) { attributes.put("energyChargedKWh", energyChargedKWh.toString()); }
        if (chargerType != null) { attributes.put("chargerType", chargerType); }
        if (pricingTime != null) { attributes.put("pricingTime", pricingTime.toString()); }
        attributes.put("costOnly", Boolean.toString(costOnly));
        attributes.put("terminalSocOnly", Boolean.toString(terminalSocOnly));

        return attributes;
    }
}
