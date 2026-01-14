package se.urbanEV.config;

import org.matsim.core.config.ReflectiveConfigGroup;

import javax.validation.constraints.NotNull;
import javax.validation.constraints.Positive;
import javax.validation.constraints.PositiveOrZero;
import java.util.Map;
import org.apache.log4j.Logger;

public final class UrbanEVConfigGroup extends ReflectiveConfigGroup {
    private static final Logger log = Logger.getLogger(UrbanEVConfigGroup.class);

    public static final String GROUP_NAME = "urban_ev";

    private static final String RANGE_ANXIETY_UTILITY = "rangeAnxietyUtility";
    static final String RANGE_ANXIETY_UTILITY_EXP = "[utils/percent_points_of_soc_under_threshold] utility for going below battery threshold. negative";

    private static final String EMPTY_BATTERY_UTILITY = "emptyBatteryUtility";
    static final String EMPTY_BATTERY_UTILITY_EXP = "[utils] utility for empty battery. should not happen. very negative";

    private static final String WALKING_UTILITY = "walkingUtility";
    static final String WALKING_UTILITY_EXP = "[utils/m] utility for walking from charger to activity. negative";

    private static final String HOME_CHARGING_UTILITY = "homeChargingUtility";
    static final String HOME_CHARGING_UTILITY_EXP = "[utils] utility for using private home charger. positive";

    private static final String SOC_DIFFERENCE_UTILITY = "socDifferenceUtility";
    static final String SOC_DIFFERENCE_UTILITY_EXP = "[utils] utility for difference between start and end soc";

    public static final String VEHICLE_TYPES_FILE = "vehicleTypesFile";
    static final String VEHICLE_TYPES_FILE_EXP = "Location of the vehicle types file";

    public static final String DEFAULT_RANGE_ANXIETY_THRESHOLD = "defaultRangeAnxietyThreshold";
    static final String DEFAULT_RANGE_ANXIETY_THRESHOLD_EXP = "Default threshold for scoring. Set person attribute to overwrite. [% soc]";

    public static final String PARKING_SEARCH_RADIUS = "parkingSearchRadius";
    static final String PARKING_SEARCH_RADIUS_EXP = "Radius around activity location in which agents looks for available chargers [m]";

    public static final String MAXNUMBERSIMULTANEOUSPLANCHANGES = "maxNumberSimultaneousPlanChanges";
    static final String MAXNUMBERSIMULTANEOUSPLANCHANGES_EXP = "The maximum number of changes to a persons charging plan that are introduced in one replanning step.";

    public static final String TIMEADJUSTMENTPROBABILITY = "timeAdjustmentProbability";
    static final String TIMEADJUSTMENTPROBABILITY_EXP = "The probability with which a persons decides to adjust their activity end times in order to increase their chances for a free charging spot at their next activity.";

    public static final String MAXTIMEFLEXIBILITY = "maxTimeFlexibility";
    static final String MAXTIMEFLEXIBILITY_EXP = "The maximum time span a person is willing to adjust their activity end times in order to increase their chances for a free charging spot at their next activity [s].";

    public static final String GENERATE_HOME_CHARGERS_BY_PERCENTAGE = "generateHomeChargersByPercentage";
    static final String GENERATE_HOME_CHARGERS_BY_PERCENTAGE_EXP = "If set to true, home charger information from the population file will be ignored. Instead home chargers will be generated randomly given the homeChargerPercentage share. [true/false]";

    public static final String GENERATE_WORK_CHARGERS_BY_PERCENTAGE = "generateWorkChargersByPercentage";
    static final String GENERATE_WORK_CHARGERS_BY_PERCENTAGE_EXP = "If set to true, work charger information from the population file will be ignored. Instead work chargers will be generated randomly given the workChargerPercentage share. [true/false]";

    public static final String HOME_CHARGER_PERCENTAGE = "homeChargerPercentage";
    static final String HOME_CHARGER_PERCENTAGE_EXP = "Share of the population that will be equipped with a home charger if generateHomeChargersByPercentage is set to true. [%]";

    public static final String WORK_CHARGER_PERCENTAGE = "workChargerPercentage";
    static final String WORK_CHARGER_PERCENTAGE_EXP = "Share of the population that will be equipped with a work charger if generateWorkChargersByPercentage is set to true. [%]";

    public static final String DEFAULT_HOME_CHARGER_POWER = "defaultHomeChargerPower";
    static final String DEFAULT_HOME_CHARGER_POWER_EXP = "The power of home chargers if generateHomeChargersByPercentage is set to true [kW].";

    public static final String DEFAULT_WORK_CHARGER_POWER = "defaultWorkChargerPower";
    static final String DEFAULT_WORK_CHARGER_POWER_EXP = "The power of work chargers if generateWorkChargersByPercentage is set to true [kW].";



    // New parameters for charging costs and multipliers: OmkarP.(2025)
    private static final String HOME_CHARGING_COST = "homeChargingCost";
    static final String HOME_CHARGING_COST_EXP = "[currency/kWh] unit energy cost at home chargers. 0.0 disables monetary charging at home.";

    private static final String WORK_CHARGING_COST = "workChargingCost";
    static final String WORK_CHARGING_COST_EXP = "[currency/kWh] unit energy cost at work chargers. 0.0 disables monetary charging at work.";

    private static final String PUBLIC_CHARGING_COST = "publicChargingCost";
    static final String PUBLIC_CHARGING_COST_EXP = "[currency/kWh] unit energy cost at public chargers. 0.0 disables monetary charging at public chargers.";

    private static final String BETA_MONEY = "betaMoney";
    static final String BETA_MONEY_EXP = "[utils/currency] marginal utility of money for EV charging costs. Typically negative; 0.0 disables charging cost in scoring.";

    private static final String ALPHA_SCALE_COST = "alphaScaleCost";
    static final String ALPHA_SCALE_COST_EXP = "[dimensionless] technical scaling factor applied to betaMoney in EV scoring. 1.0 = no scaling; values << 1.0 dampen the money term.";

    private static final String ENABLE_SMART_CHARGING = "enableSmartCharging";
    private static final String ALPHA_SCALE_TEMPORAL = "alphaScaleTemporal";
    private static final String AWARENESS_FACTOR = "awarenessFactor";
    private static final String COINCIDENCE_FACTOR = "coincidenceFactor";


    // Charger parameters
    private boolean generateHomeChargersByPercentage = false;

    private boolean generateWorkChargersByPercentage = false;

    @PositiveOrZero
    private double homeChargerPercentage = 0.0;

    @PositiveOrZero
    private double workChargerPercentage = 0.0;

    @PositiveOrZero
    private double defaultHomeChargerPower = 11.0;

    @PositiveOrZero
    private double defaultWorkChargerPower = 11.0;


    // Scoring parameters
    @NotNull
    private double rangeAnxietyUtility = -5;

    @NotNull
    private double emptyBatteryUtility = -10;

    @NotNull
    private double walkingUtility = -1;

    @NotNull
    private double homeChargingUtility = +1;

    @NotNull
    private double socDifferenceUtility = -10;

    @Positive
    private double defaultRangeAnxietyThreshold = 0.2;

    @NotNull
    private String vehicleTypesFile = null;

    // Charging parameters
    @Positive
    private int parkingSearchRadius = 500;

    // Replanning parameters

    @Positive
    private int maxNumberSimultaneousPlanChanges = 2;

    @PositiveOrZero
    private Double timeAdjustmentProbability = 0.1;

    @PositiveOrZero
    private int maxTimeFlexibility = 600;



    // Charging cost and ToU-related cost parameters: OmkarP.(2025)
    @NotNull
    private double betaMoney = 0.00;   // EV-specific marginal utility of money. Utils per currency unit

    @PositiveOrZero
    private double homeChargingCost = 0.0;

    @PositiveOrZero
    private double workChargingCost = 0.0;   // currency per kWh

    @PositiveOrZero
    private double publicChargingCost = 0.0; // currency per kWh

    @PositiveOrZero
    private double alphaScaleCost = 1.0;  // scaling factor for the costing

    @PositiveOrZero
    private double alphaScaleTemporal = 1.0;

    private boolean enableSmartCharging = false;
    private double awarenessFactor = 0.0;
    private double coincidenceFactor = 0.0;




    public UrbanEVConfigGroup() {
        super(GROUP_NAME);
    }

    @Override
    public Map<String, String> getComments() {
        Map<String, String> map = super.getComments();
        map.put(RANGE_ANXIETY_UTILITY, RANGE_ANXIETY_UTILITY_EXP);
        map.put(EMPTY_BATTERY_UTILITY, EMPTY_BATTERY_UTILITY_EXP);
        map.put(WALKING_UTILITY, WALKING_UTILITY_EXP);
        map.put(HOME_CHARGING_UTILITY, HOME_CHARGING_UTILITY_EXP);
        map.put(SOC_DIFFERENCE_UTILITY, SOC_DIFFERENCE_UTILITY_EXP);
        map.put(VEHICLE_TYPES_FILE, VEHICLE_TYPES_FILE_EXP);
        map.put(PARKING_SEARCH_RADIUS, PARKING_SEARCH_RADIUS_EXP);
        map.put(DEFAULT_RANGE_ANXIETY_THRESHOLD, DEFAULT_RANGE_ANXIETY_THRESHOLD_EXP);
        map.put(MAXNUMBERSIMULTANEOUSPLANCHANGES, MAXNUMBERSIMULTANEOUSPLANCHANGES_EXP);
        map.put(TIMEADJUSTMENTPROBABILITY, TIMEADJUSTMENTPROBABILITY_EXP);
        map.put(MAXTIMEFLEXIBILITY, MAXTIMEFLEXIBILITY_EXP);
        map.put(GENERATE_HOME_CHARGERS_BY_PERCENTAGE, GENERATE_HOME_CHARGERS_BY_PERCENTAGE_EXP);
        map.put(GENERATE_WORK_CHARGERS_BY_PERCENTAGE, GENERATE_WORK_CHARGERS_BY_PERCENTAGE_EXP);
        map.put(HOME_CHARGER_PERCENTAGE, HOME_CHARGER_PERCENTAGE_EXP);
        map.put(WORK_CHARGER_PERCENTAGE, WORK_CHARGER_PERCENTAGE_EXP);
        map.put(DEFAULT_HOME_CHARGER_POWER, DEFAULT_HOME_CHARGER_POWER_EXP);
        map.put(DEFAULT_WORK_CHARGER_POWER, DEFAULT_WORK_CHARGER_POWER_EXP);

        // New charging cost parameters  (OmkarP. 2025)
        map.put(HOME_CHARGING_COST, HOME_CHARGING_COST_EXP);
        map.put(WORK_CHARGING_COST, WORK_CHARGING_COST_EXP);
        map.put(PUBLIC_CHARGING_COST, PUBLIC_CHARGING_COST_EXP);
        map.put(BETA_MONEY, BETA_MONEY_EXP);
        map.put(ALPHA_SCALE_COST, ALPHA_SCALE_COST_EXP);
        map.put(ENABLE_SMART_CHARGING, "Enable smart charging behavior: delayed start times, ToU awareness, and coincidence effect.");
        map.put(COINCIDENCE_FACTOR, "Dispersion factor [0.0–1.0] controlling the std-dev of deferred start times within the shifted low-ToU window (truncated normal).");
        map.put(AWARENESS_FACTOR, "Probability [0.0–1.0] of an agent being aware of ToU pricing and willing to shift charging start.");
        map.put(ALPHA_SCALE_TEMPORAL, "Temporal shift controller in (0,1]. 1.0=no shift; values closer to 0 shift the low-ToU window earlier..");

        return map;
    }

    @StringGetter(MAXNUMBERSIMULTANEOUSPLANCHANGES)
    public int getMaxNumberSimultaneousPlanChanges() {
        return maxNumberSimultaneousPlanChanges;
    }

    @StringSetter(MAXNUMBERSIMULTANEOUSPLANCHANGES)
    public void setMaxNumberSimultaneousPlanChanges(int maxNumberSimultaneousPlanChanges) {
        this.maxNumberSimultaneousPlanChanges = maxNumberSimultaneousPlanChanges;
    }

    @StringGetter(TIMEADJUSTMENTPROBABILITY)
    public Double getTimeAdjustmentProbability() {
        return timeAdjustmentProbability;
    }

    @StringSetter(TIMEADJUSTMENTPROBABILITY)
    public void setTimeAdjustmentProbability(Double timeAdjustmentProbability) {
        this.timeAdjustmentProbability = timeAdjustmentProbability;
    }

    @StringGetter(MAXTIMEFLEXIBILITY)
    public int getMaxTimeFlexibility() {
        return maxTimeFlexibility;
    }

    @StringSetter(MAXTIMEFLEXIBILITY)
    public void setMaxTimeFlexibility(int maxTimeFlexibility) {
        this.maxTimeFlexibility = maxTimeFlexibility;
    }

    @StringGetter(RANGE_ANXIETY_UTILITY)
    public double getRangeAnxietyUtility() { return rangeAnxietyUtility; }

    @StringSetter(RANGE_ANXIETY_UTILITY)
    public void setRangeAnxietyUtility(double rangeAnxietyUtility) { this.rangeAnxietyUtility = rangeAnxietyUtility; }

    @StringGetter(EMPTY_BATTERY_UTILITY)
    public double getEmptyBatteryUtility() { return emptyBatteryUtility; }

    @StringSetter(EMPTY_BATTERY_UTILITY)
    public void setEmptyBatteryUtility(double emptyBatteryUtility) { this.emptyBatteryUtility = emptyBatteryUtility; }

    @StringGetter(WALKING_UTILITY)
    public double getWalkingUtility() { return walkingUtility; }

    @StringSetter(WALKING_UTILITY)
    public void setWalkingUtility(double walkingUtility) { this.walkingUtility = walkingUtility; }

    @StringGetter(HOME_CHARGING_UTILITY)
    public double getHomeChargingUtility() { return homeChargingUtility; }

    @StringSetter(HOME_CHARGING_UTILITY)
    public void setHomeChargingUtility(double homeChargingUtility) { this.homeChargingUtility = homeChargingUtility; }

    @StringGetter(SOC_DIFFERENCE_UTILITY)
    public double getSocDifferenceUtility() { return socDifferenceUtility; }

    @StringSetter(SOC_DIFFERENCE_UTILITY)
    public void setSocDifferenceUtility(double socDifferenceUtility) { this.socDifferenceUtility = socDifferenceUtility; }

    @StringGetter(DEFAULT_RANGE_ANXIETY_THRESHOLD)
    public double getDefaultRangeAnxietyThreshold() {
        return defaultRangeAnxietyThreshold;
    }

    @StringSetter(DEFAULT_RANGE_ANXIETY_THRESHOLD)
    public void setDefaultRangeAnxietyThreshold(double defaultRangeAnxietyThreshold) {
        this.defaultRangeAnxietyThreshold = defaultRangeAnxietyThreshold;
    }

    @StringGetter(VEHICLE_TYPES_FILE)
    public String getVehicleTypesFile() {
        return vehicleTypesFile;
    }

    @StringSetter(VEHICLE_TYPES_FILE)
    public void setVehicleTypesFile(String vehicleTypesFile) {
        this.vehicleTypesFile = vehicleTypesFile;
    }

    @StringGetter(PARKING_SEARCH_RADIUS)
    public int getParkingSearchRadius() {
        return parkingSearchRadius;
    }

    @StringSetter(PARKING_SEARCH_RADIUS)
    public void setParkingSearchRadius(int parkingSearchRadius) {
        this.parkingSearchRadius = parkingSearchRadius;
    }

    @StringGetter(GENERATE_HOME_CHARGERS_BY_PERCENTAGE)
    public boolean isGenerateHomeChargersByPercentage() {
        return generateHomeChargersByPercentage;
    }

    @StringSetter(GENERATE_HOME_CHARGERS_BY_PERCENTAGE)
    public void setGenerateHomeChargersByPercentage(boolean generateHomeChargersByPercentage) {
        this.generateHomeChargersByPercentage = generateHomeChargersByPercentage;
    }

    @StringGetter(GENERATE_WORK_CHARGERS_BY_PERCENTAGE)
    public boolean isGenerateWorkChargersByPercentage() {
        return generateWorkChargersByPercentage;
    }

    @StringSetter(GENERATE_WORK_CHARGERS_BY_PERCENTAGE)
    public void setGenerateWorkChargersByPercentage(boolean generateWorkChargersByPercentage) {
        this.generateWorkChargersByPercentage = generateWorkChargersByPercentage;
    }


    @StringGetter(HOME_CHARGER_PERCENTAGE)
    public double getHomeChargerPercentage() {
        return homeChargerPercentage;
    }

    @StringSetter(HOME_CHARGER_PERCENTAGE)
    public void setHomeChargerPercentage(double homeChargerPercentage) {
        this.homeChargerPercentage = homeChargerPercentage;
    }


    @StringGetter(WORK_CHARGER_PERCENTAGE)
    public double getWorkChargerPercentage() {
        return workChargerPercentage;
    }

    @StringSetter(WORK_CHARGER_PERCENTAGE)
    public void setWorkChargerPercentage(double workChargerPercentage) {
        this.workChargerPercentage = workChargerPercentage;
    }


    @StringGetter(DEFAULT_HOME_CHARGER_POWER)
    public double getDefaultHomeChargerPower() {
        return defaultHomeChargerPower;
    }

    @StringSetter(DEFAULT_HOME_CHARGER_POWER)
    public void setDefaultHomeChargerPower(double defaultHomeChargerPower) {
        this.defaultHomeChargerPower = defaultHomeChargerPower;
    }


    @StringGetter(DEFAULT_WORK_CHARGER_POWER)
    public double getDefaultWorkChargerPower() {
        return defaultWorkChargerPower;
    }

    @StringSetter(DEFAULT_WORK_CHARGER_POWER)
    public void setDefaultWorkChargerPower(double defaultWorkChargerPower) {
        this.defaultWorkChargerPower = defaultWorkChargerPower;
    }




    // Additional getters-setters for cost params: OmkarP.(2025)
    @StringGetter(HOME_CHARGING_COST)
    public double getHomeChargingCost() {
        return homeChargingCost;
    }

    @StringSetter(HOME_CHARGING_COST)
    public void setHomeChargingCost(double homeChargingCost) {
        this.homeChargingCost = homeChargingCost;
    }

    @StringGetter(WORK_CHARGING_COST)
    public double getWorkChargingCost() {
        return workChargingCost;
    }

    @StringSetter(WORK_CHARGING_COST)
    public void setWorkChargingCost(double workChargingCost) {
        this.workChargingCost = workChargingCost;
    }

    @StringGetter(PUBLIC_CHARGING_COST)
    public double getPublicChargingCost() {
        return publicChargingCost;
    }

    @StringSetter(PUBLIC_CHARGING_COST)
    public void setPublicChargingCost(double publicChargingCost) {
        this.publicChargingCost = publicChargingCost;
    }

    @StringGetter(BETA_MONEY)
    public double getBetaMoney() {
        return betaMoney;
    }

    @StringSetter(BETA_MONEY)
    public void setBetaMoney(double betaMoney) {
        this.betaMoney = betaMoney;
    }

    @StringGetter(ALPHA_SCALE_COST)
    public double getAlphaScaleCost() {
        return alphaScaleCost;
    }

    @StringSetter(ALPHA_SCALE_COST)
    public void setAlphaScaleCost(double alphaScaleCost) {
        this.alphaScaleCost = alphaScaleCost;
    }

    @StringGetter(ENABLE_SMART_CHARGING)
    public boolean isEnableSmartCharging() {
        return enableSmartCharging;
    }

    @StringSetter(ENABLE_SMART_CHARGING)
    public void setEnableSmartCharging(boolean enableSmartCharging) {
        this.enableSmartCharging = enableSmartCharging;
    }

    @StringSetter(AWARENESS_FACTOR)
    public void setAwarenessFactor(double awarenessFactor) {
        if (awarenessFactor < 0.0 || awarenessFactor > 1.0) {
            log.warn("UrbanEVConfigGroup: awarenessFactor outside [0,1] (" + awarenessFactor + "), clamping.");
        }
        this.awarenessFactor = Math.max(0.0, Math.min(1.0, awarenessFactor));
    }

    @StringSetter(COINCIDENCE_FACTOR)
    public void setCoincidenceFactor(double coincidenceFactor) {
        if (coincidenceFactor < 0.0 || coincidenceFactor > 1.0) {
            log.warn("UrbanEVConfigGroup: coincidenceFactor outside [0,1] (" + coincidenceFactor + "), clamping.");
        }
        this.coincidenceFactor = Math.max(0.0, Math.min(1.0, coincidenceFactor));
    }

    @StringGetter(AWARENESS_FACTOR)
    public double getAwarenessFactor() {
        return awarenessFactor;
    }

    @StringGetter(COINCIDENCE_FACTOR)
    public double getCoincidenceFactor() {
        return coincidenceFactor;
    }

    @StringGetter(ALPHA_SCALE_TEMPORAL)
    public double getAlphaScaleTemporal() {
        return alphaScaleTemporal;
    }

    @StringSetter(ALPHA_SCALE_TEMPORAL)
    public void setAlphaScaleTemporal(double v) {
        if (!Double.isFinite(v)) {
            log.warn("UrbanEVConfigGroup: alphaScaleTemporal is not finite (" + v + "), using 1.0.");
            this.alphaScaleTemporal = 1.0;
            return;
        }
        // Interpret as a shift factor in [0,1]: 1=no shift, 0=max shift.
        if (v < 0.0) {
            log.warn("UrbanEVConfigGroup: alphaScaleTemporal < 0 (" + v + "), clamping to 0.0.");
            this.alphaScaleTemporal = 0.0;
        } else if (v > 1.0) {
            log.warn("UrbanEVConfigGroup: alphaScaleTemporal > 1 (" + v + "), clamping to 1.0.");
            this.alphaScaleTemporal = 1.0;
        } else {
            this.alphaScaleTemporal = v;
        }
    }

    public void logIfSuspicious() {
        if (betaMoney > 0.0) {
            log.warn("UrbanEVConfigGroup: betaMoney > 0.0 detected (" + betaMoney + "). "
                    + "EV charging cost will increase utility; is that really intended?");
        }
        if (homeChargingCost < 0.0 || workChargingCost < 0.0 || publicChargingCost < 0.0) {
            log.error("UrbanEVConfigGroup: negative charging cost detected. "
                    + "Please check home/work/publicChargingCost in config.xml.");
        }
    }
}
