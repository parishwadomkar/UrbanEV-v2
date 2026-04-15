import xml.etree.ElementTree as ET
import random
import gzip
from pathlib import Path
from xml.dom import minidom


PLANS_FILE = Path(r"C:\Users\omkarp\IdeaProjects\UrbanEV-v2\scenarios\sweden\1pct\GOTplans_1pct7Days.xml")
EV_ADOPTION_PCT = 80.0
RANDOM_SEED = 42

OUTPUT_FILE = PLANS_FILE.parent / f"evehicles1pct_{int(EV_ADOPTION_PCT)}adopt.xml"

VEHICLE_TYPES = {
    "VW_ID4": 34,
    "bmw_i3": 42,
    "Volvo": 60,
    "renault_zoe": 52,
    "tesla_model_Y": 75,
}

# weights uniform if you do not want to bias the fleet mix
VEHICLE_TYPE_WEIGHTS = {
    "VW_ID4": 1.0,
    "bmw_i3": 1.0,
    "Volvo": 1.0,
    "renault_zoe": 1.0,
    "tesla_model_Y": 1.0,
}

CHARGER_TYPES = "default"
INITIAL_SOC_MIN = 0.60
INITIAL_SOC_MAX = 0.80

# ============================================================
# Helpers
# ============================================================
def open_xml_root(path: Path):
    if path.suffix.lower() == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as f:
            tree = ET.parse(f)
    else:
        tree = ET.parse(path)
    return tree.getroot()

def generate_initial_soc_kwh(battery_capacity_kwh: float) -> float:
    return round(random.uniform(INITIAL_SOC_MIN, INITIAL_SOC_MAX) * battery_capacity_kwh, 1)

def select_vehicle_type():
    keys = list(VEHICLE_TYPES.keys())
    weights = [VEHICLE_TYPE_WEIGHTS[k] for k in keys]
    return random.choices(keys, weights=weights, k=1)[0]

def prettify_xml(elem: ET.Element) -> str:
    rough = ET.tostring(elem, encoding="utf-8")
    reparsed = minidom.parseString(rough)
    return reparsed.toprettyxml(indent="    ")

def collect_car_user_ids(pop_root: ET.Element):
    car_user_ids = set()

    for person in pop_root.findall("person"):
        person_id = person.attrib.get("id")
        if person_id is None:
            continue

        has_car_leg = False
        for plan in person.findall("plan"):
            for leg in plan.findall("leg"):
                if leg.attrib.get("mode") == "car":
                    has_car_leg = True
                    break
            if has_car_leg:
                break

        if has_car_leg:
            car_user_ids.add(person_id)

    return sorted(car_user_ids)

# ============================================================
# Main
# ============================================================

def generate_evehicles_file(plans_file: Path, output_file: Path, ev_adoption_pct: float, seed: int):
    if not plans_file.exists():
        raise FileNotFoundError(f"Plans file not found: {plans_file}")

    if not (0.0 <= ev_adoption_pct <= 100.0):
        raise ValueError("EV_ADOPTION_PCT must be between 0 and 100.")

    random.seed(seed)

    print(f"Loading plans: {plans_file}")
    root = open_xml_root(plans_file)
    print("Collecting unique car-user IDs from plans...")
    car_user_ids = collect_car_user_ids(root)
    total_car_users = len(car_user_ids)

    if total_car_users == 0:
        raise RuntimeError("No persons with car legs were found in the plans file.")

    n_evs = round((ev_adoption_pct / 100.0) * total_car_users)
    n_evs = max(0, min(n_evs, total_car_users))
    print(f"Total car users found: {total_car_users}")
    print(f"Target EV adoption: {ev_adoption_pct:.1f}%")
    print(f"Number of EVs to assign: {n_evs}")
    ev_ids = set(random.sample(car_user_ids, n_evs))
    vehicles_elem = ET.Element("vehicles")
    ev_type_counts = {k: 0 for k in VEHICLE_TYPES}

    for vehicle_id in ev_ids:
        vehicle_type = select_vehicle_type()
        battery_capacity = VEHICLE_TYPES[vehicle_type]
        initial_soc = generate_initial_soc_kwh(battery_capacity)
        ev_type_counts[vehicle_type] += 1

        ET.SubElement(
            vehicles_elem,
            "vehicle",
            id=str(vehicle_id),
            battery_capacity=str(battery_capacity),
            initial_soc=str(initial_soc),
            charger_types=CHARGER_TYPES,
            vehicle_type=vehicle_type,
        )

    xml_str = prettify_xml(vehicles_elem)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n')
        f.write('<!DOCTYPE vehicles SYSTEM "http://matsim.org/files/dtd/electric_vehicles_v1.dtd">\n')
        start = xml_str.find("<vehicles>")
        f.write(xml_str[start:])

    print(f"\nWrote EV file: {output_file}")
    print(f"Generated {len(ev_ids)} EVs out of {total_car_users} car users.")
    print("Assigned EV type counts:")
    for vt, count in ev_type_counts.items():
        print(f"  {vt}: {count}")

if __name__ == "__main__":
    generate_evehicles_file(
        plans_file=PLANS_FILE,
        output_file=OUTPUT_FILE,
        ev_adoption_pct=EV_ADOPTION_PCT,
        seed=RANDOM_SEED,
    )