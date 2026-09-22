"""
lgd.py — Local Government Directory (LGD) reference fetcher.

Downloads the canonical list of Indian states and districts with
latitude/longitude centroids. This is the shared location layer that
lets weather, soil, and KCC be joined on a common district key.

Source: VijaySamant4368/India-Locations-Dataset (MIT licensed)
Output:
    data/reference/lgd_districts.json   (structured)
    data/reference/lgd_districts.csv    (human-readable)
"""

import csv
import json
from pathlib import Path

from utils import BASE_DIR, log, safe_get, save_json, utc_now

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
LGD_JSON_URL = (
    "https://raw.githubusercontent.com/VijaySamant4368/"
    "India-Locations-Dataset/main/india_locations_with_coords_small.json"
)

REFERENCE_DIR = BASE_DIR / "reference"
REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
LGD_CSV_PATH = REFERENCE_DIR / "lgd_districts.csv"
LGD_JSON_PATH = REFERENCE_DIR / "lgd_districts.json"


def _flatten(raw):
    """
    Flatten the nested VijaySamant JSON into a flat list of districts.

    Raw structure:
        [{"s": "State", "c": {"a": lat, "o": lon},
          "d": [{"n": "District", "c": {"a": lat, "o": lon}, "sd": [...]}]}]

    Falls back to the state centroid if a district lacks its own coords.
    """
    districts = []
    for state in raw:
        state_name = str(state.get("s", "")).strip()
        if not state_name:
            continue

        state_coords = state.get("c") or {}

        for dist in state.get("d", []):
            d_name = str(dist.get("n", "")).strip()
            if not d_name:
                continue

            d_coords = dist.get("c") or {}
            lat = d_coords.get("a")
            lon = d_coords.get("o")

            # Fallback to state centroid
            if lat is None or lon is None:
                lat = state_coords.get("a")
                lon = state_coords.get("o")

            if lat is None or lon is None:
                continue

            districts.append({
                "state": state_name,
                "district": d_name,
                "latitude": float(lat),
                "longitude": float(lon),
            })
    return districts


def fetch_lgd_reference():
    """
    Download the LGD district list and save it locally.

    Returns a list of dicts:
        [{"state": ..., "district": ..., "latitude": ..., "longitude": ...}]
    """
    log.info("Fetching LGD district reference data...")

    res = safe_get(LGD_JSON_URL, timeout=90)
    if not res:
        log.error("Failed to download LGD JSON.")
        return []

    try:
        raw = res.json()
    except Exception as err:
        log.error(f"Failed to parse LGD JSON: {err}")
        return []

    districts = _flatten(raw)
    if not districts:
        log.error("No districts parsed from LGD JSON.")
        return []

    # Save CSV (human-readable)
    with open(LGD_CSV_PATH, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["state", "district", "latitude", "longitude"]
        )
        writer.writeheader()
        writer.writerows(districts)

    # Save JSON (programmatic)
    save_json(LGD_JSON_PATH, {
        "source": "India-Locations-Dataset (GitHub)",
        "data_type": "lgd_reference",
        "fetched_at": utc_now(),
        "total_districts": len(districts),
        "districts": districts,
    })

    log.info(
        f"LGD reference saved → {LGD_JSON_PATH} "
        f"({len(districts)} districts across all states)"
    )
    return districts


def load_lgd_districts():
    """
    Load the LGD district list from the cached JSON file.

    Call this from weather.py, soil.py, etc. after fetch_lgd_reference()
    has run at least once.

    Returns a list of dicts (same shape as fetch_lgd_reference).
    """
    if not LGD_JSON_PATH.exists():
        log.warning(
            "LGD reference not found. Run fetch_lgd_reference() first."
        )
        return []

    with open(LGD_JSON_PATH, encoding="utf-8") as fh:
        data = json.load(fh)

    return data.get("districts", [])


if __name__ == "__main__":
    fetch_lgd_reference()