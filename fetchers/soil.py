"""
soil.py — Soil Health Card fetcher (bulk CSV download from CKAN).

Downloads the full Soil Nutrient Analysis CSV (~1.1 GB) from the
India Data Portal CKAN instance, then aggregates to district level.

This replaces the dead ckandev.indiadataportal.com SQL endpoint.
"""

import time
from pathlib import Path

import pandas as pd
import requests

from utils import BASE_DIR, PROCESSED_DIR, log, save_json, utc_now

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
# The direct CSV download URL from the CKAN resource page.
# This is stable as long as the resource ID (66860e1a-...) doesn't change.
CSV_URL = (
    "https://ckan.indiadataportal.com/dataset/"
    "66049516-7ae0-47e4-98dc-056bc7a27abc/resource/"
    "66860e1a-113a-4ca8-94aa-2418bd462d28/download/"
    "soil-nutrient-analysis.csv"
)

# Cache the raw CSV locally so we don't re-download 1.1 GB every run.
RAW_DIR = BASE_DIR / "raw" / "soil"
RAW_DIR.mkdir(parents=True, exist_ok=True)
RAW_CSV = RAW_DIR / "soil_nutrient_analysis.csv"

# Only re-download if the local file is older than this many days.
CACHE_MAX_AGE_DAYS = 30

CHUNK_SIZE = 1024 * 1024  # 1 MB chunks for streaming download


# ---------------------------------------------------------------------------
# Download (streamed, with progress)
# ---------------------------------------------------------------------------
def _download_csv(force: bool = False) -> bool:
    """
    Download the full CSV to RAW_CSV if missing or stale.

    Returns True if the file is available locally, False on failure.
    """
    if RAW_CSV.exists() and not force:
        age_days = (time.time() - RAW_CSV.stat().st_mtime) / 86400
        if age_days < CACHE_MAX_AGE_DAYS:
            log.info(
                f"Using cached CSV ({age_days:.1f} days old, "
                f"{RAW_CSV.stat().st_size / 1e9:.2f} GB)"
            )
            return True
        log.info(f"Cached CSV is {age_days:.1f} days old. Re-downloading...")

    log.info(f"Downloading Soil Health Card CSV (~1.1 GB) from CKAN...")
    log.info(f"URL: {CSV_URL}")

    try:
        r = requests.get(CSV_URL, stream=True, timeout=(30, 120))
        r.raise_for_status()
    except requests.RequestException as err:
        log.error(f"Download failed: {err}")
        return False

    total = int(r.headers.get("content-length", 0))
    downloaded = 0
    last_log_pct = -1

    with open(RAW_CSV, "wb") as fh:
        for chunk in r.iter_content(chunk_size=CHUNK_SIZE):
            if not chunk:
                continue
            fh.write(chunk)
            downloaded += len(chunk)

            if total:
                pct = int(downloaded / total * 100)
                if pct >= last_log_pct + 10:
                    log.info(f"  Downloaded {pct}% ({downloaded / 1e9:.2f} GB)")
                    last_log_pct = pct

    log.info(f"CSV saved → {RAW_CSV} ({downloaded / 1e9:.2f} GB)")
    return True


# ---------------------------------------------------------------------------
# Process: aggregate to district level
# ---------------------------------------------------------------------------
def _aggregate_district(csv_path: Path):
    """
    Read the CSV in chunks and aggregate to district level.

    The full CSV is too large to load into memory at once, so we read
    it in chunks and build per-district nutrient distributions.

    Returns a list of district records.
    """
    log.info("Aggregating CSV to district level (this may take a few minutes)...")

    # Columns we need (confirmed from the CKAN data dictionary)
    USECOLS = [
        "year", "state_name", "state_code",
        "district_name", "district_code",
        "nutrient_name", "nutrient_level", "value",
    ]

    # Accumulator: {(state, district): {nutrient: {level: count}}}
    accumulator = {}
    row_count = 0
    skipped = 0

    chunk_iter = pd.read_csv(
        csv_path,
        usecols=USECOLS,
        chunksize=500_000,
        low_memory=False,
        on_bad_lines="skip",
    )

    for chunk in chunk_iter:
        row_count += len(chunk)

        # Drop rows with missing location or nutrient
        chunk = chunk.dropna(subset=["state_name", "district_name", "nutrient_name"])

        for _, row in chunk.iterrows():
            state = str(row["state_name"]).strip()
            district = str(row["district_name"]).strip()
            nutrient = str(row["nutrient_name"]).strip()
            level = str(row["nutrient_level"]).strip()
            value = row["value"]

            if not state or not district or not nutrient:
                skipped += 1
                continue

            key = (state, district)
            if key not in accumulator:
                accumulator[key] = {
                    "year": row.get("year"),
                    "state_code": row.get("state_code"),
                    "district_code": row.get("district_code"),
                    "nutrients": {},
                }

            nutrients = accumulator[key]["nutrients"]
            if nutrient not in nutrients:
                nutrients[nutrient] = {}
            nutrients[nutrient][level] = nutrients[nutrient].get(level, 0) + (
                value if pd.notna(value) else 0
            )

        log.info(f"  Processed {row_count:,} rows...")

    log.info(f"Total rows: {row_count:,} | Skipped: {skipped:,}")
    log.info(f"Districts found: {len(accumulator)}")

    # Build the output records
    results = []
    for (state, district), info in accumulator.items():
        nutrients = {}
        for nutrient, levels in info["nutrients"].items():
            if not levels:
                continue
            max_level = max(levels, key=levels.get)
            nutrients[nutrient] = {
                "distribution": levels,
                "dominant_level": max_level,
            }

        results.append({
            "state": state,
            "district": district,
            "state_code": info.get("state_code"),
            "district_code": info.get("district_code"),
            "year": info.get("year"),
            "nutrients": nutrients,
        })

    return results


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def fetch_soil(force_download: bool = False):
    """
    Download the full Soil Health Card CSV and aggregate to district level.

    Output: data/processed/soil/district_soil.json
    """
    log.info("Fetching Soil Health Card data (bulk CSV from CKAN)...")

    if not _download_csv(force=force_download):
        log.error("CSV download failed. Skipping soil fetch.")
        return

    try:
        districts = _aggregate_district(RAW_CSV)
    except Exception as err:
        log.error(f"Aggregation failed: {err}")
        return

    if not districts:
        log.warning("No district records produced from CSV.")
        return

    out_file = PROCESSED_DIR / "soil" / "district_soil.json"
    save_json(out_file, {
        "source": "Soil Health Card - India Data Portal (CKAN)",
        "data_type": "soil_health_district_aggregated",
        "fetched_at": utc_now(),
        "total_districts": len(districts),
        "districts": districts,
    })

    log.info(
        f"Soil data saved → {out_file} "
        f"({len(districts)} districts with nutrient data)"
    )


if __name__ == "__main__":
    fetch_soil()