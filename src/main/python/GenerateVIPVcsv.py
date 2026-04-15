import random
import pandas as pd
import xml.etree.ElementTree as ET
from pathlib import Path

# --- inputs ---
xml_path = Path(r"C:\Users\omkarp\IdeaProjects\UrbanEV-v2\scenarios\sweden\1pct\evehicles1pct.xml")
out_csv  = xml_path.with_name("70pctVIPV.csv")

pv_share = 0.70          # 70%
pv_wp = 400.0            # Wp
pv_area_m2 = 2.0         # m^2
pv_eff = 0.20            # 20%
seed = 42                # reproducible

# --- read XML (strip DOCTYPE if present) ---
text = xml_path.read_text(encoding="utf-8")
lines = [ln for ln in text.splitlines() if not ln.strip().upper().startswith("<!DOCTYPE")]
clean = "\n".join(lines)

root = ET.fromstring(clean)

vehicle_ids = []
for v in root.findall(".//vehicle"):
    vid = v.attrib.get("id")
    if vid is not None:
        vehicle_ids.append(vid)

if not vehicle_ids:
    raise RuntimeError(f"No <vehicle> ids found in {xml_path}")

# --- sample PV vehicles ---
random.seed(seed)
k = int(round(pv_share * len(vehicle_ids)))
pv_ids = set(random.sample(vehicle_ids, k))

df = pd.DataFrame({
    "vehicle_id": sorted(pv_ids, key=lambda x: int(x) if str(x).isdigit() else str(x)),
    "pv_wp": pv_wp,
    "pv_area_m2": pv_area_m2,
    "pv_eff": pv_eff
})

df.to_csv(out_csv, index=False)
df.head(), len(df), out_csv