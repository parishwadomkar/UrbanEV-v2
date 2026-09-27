"""Regenerate the MATSim VIPV seasonal arrays from the tracked PVGIS workbook.

PVGIS hourly timestamps are UTC. They are converted to Europe/Stockholm before
the local-hour and local-season aggregation used by MATSim and its ToU tariff.
This script is independent of src/main/python/Opti.
"""

from pathlib import Path
import argparse
import pandas as pd


SEASONS = {
    "SPRING": (3, 4, 5),
    "SUMMER": (6, 7, 8),
    "AUTUMN": (9, 10, 11),
    "WINTER": (12, 1, 2),
}


def java_array(name: str, values: list[float]) -> str:
    lines = []
    for start in range(0, 24, 6):
        lines.append("            " + ", ".join(f"{v:.6f}" for v in values[start:start + 6]))
    return f"private static final double[] PV_{name} = {{\n" + ",\n".join(lines) + "\n    };"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "workbook",
        nargs="?",
        type=Path,
        default=Path(__file__).with_name(
            "PVGIS_Timeseries_57.707_11.967_SA3_0kWp_crystSi_14_41deg_5deg_2023.xlsx"
        ),
    )
    args = parser.parse_args()

    data = pd.read_excel(args.workbook, sheet_name="1000Wp")
    data["utc_time"] = pd.to_datetime(data["time"], format="%Y%m%d:%H%M", utc=True)
    data["local_time"] = data["utc_time"].dt.tz_convert("Europe/Stockholm")
    data["factor"] = pd.to_numeric(data["P"], errors="raise") / 1000.0

    if len(data) != 8760:
        raise ValueError(f"Expected 8760 hourly records, found {len(data)}")

    for season, months in SEASONS.items():
        selected = data[data["local_time"].dt.month.isin(months)]
        profile = (
            selected.groupby(selected["local_time"].dt.hour)["factor"]
            .mean()
            .reindex(range(24), fill_value=0.0)
        )
        values = profile.tolist()
        print(java_array(season, values))
        print(f"// daily equivalent: {sum(values):.6f} kWh/kWp\n")


if __name__ == "__main__":
    main()
