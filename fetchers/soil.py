"""
soil.py — Soil Health Card fetcher (bulk CSV download from CKAN).

Downloads the full Soil Nutrient Analysis CSV (~1.1 GB) from the
India Data Portal CKAN instance, then aggregates to district level.

Two-level caching:
    - If the aggregated output JSON is fresh, skip entirely.
    - If the output JSON is stale but the raw CSV is fresh,
      re-aggregate without re-downloading.
    - If both are stale, download then aggregate.

This replaces the dead ckandev.indiadataportal.com SQL endpoint.
"""

import time
from pathlib import Path

import pandas as pd
import requests

from utils import (
    BASE_DIR,
    PROCESSED_DIR,
    cache_age_days,
    is_cache_fresh,
    log,
    save_json,
    utc_now,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CSV_URL = (
    "https://ckan.indiadataportal.com/dataset/"
    "66049516-7ae0-47e4-98dc-056bc7a27abc/resource/"
    "66860e1a-113a-4ca8-94aa-2418bd462d28/download/"
    "soil-nutrient-analysis.csv"
)

RAW_DIR = BASE_DIR / "raw" / "soil"
RAW_DIR.mkdir(parents=True, exist_ok=True)
RAW_CSV = RAW_DIR / "soil_nutrient_analysis.csv"

OUTPUT_FILE = PROCESSED_DIR / "soil" / "district_soil.json"

# Freshness policies
OUTPUT_MAX_AGE_DAYS = 30      # Aggregated JSON — re-aggregate monthly
CSV_MAX_AGE_DAYS = 30         # Raw CSV — re-download monthly

CHUNK_SIZE = 1024 * 1024      # 1 MB chunks for streaming download


# ---------------------------------------------------------------------------
# Download (streamed, with progress)
# ---------------------------------------------------------------------------
def _download_csv(force: bool = False) -> bool:
    """
    Download the full CSV to RAW_CSV if missing or stale.

    Returns True if the file is available locally, False on failure.
    """
    if not force and is_cache_fresh(RAW_CSV, CSV_MAX_AGE_DAYS):
        age = cache_age_days(RAW_CSV)
        log.info(
            f"Using cached CSV ({age:.1f} days old, "
            f"{RAW_CSV.stat().st_size / 1e9:.2f} GB)"
        )
        return True

    if RAW_CSV.exists():
        log.info(
            f"Cached CSV is {cache_age_days(RAW_CSV):.1f} days old. "
            f"Re-downloading..."
        )

    log.info("Downloading Soil Health Card CSV (~1.1 GB) from CKAN...")
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

    USECOLS = [
        "year", "state_name", "state_code",
        "district_name", "district_code",
        "nutrient_name", "nutrient_level", "value",
    ]

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
def fetch_soil(force: bool = False):
    """
    Fetch and aggregate Soil Health Card data to district level.

    Skips entirely if the aggregated output is fresh. Re-aggregates
    without re-downloading if only the CSV is fresh.

    Output: data/processed/soil/district_soil.json
    """
    # ── Level 1: aggregated output freshness ─────────────────────────
    if not force and is_cache_fresh(OUTPUT_FILE, OUTPUT_MAX_AGE_DAYS):
        age = cache_age_days(OUTPUT_FILE)
        log.info(
            f"Soil data is fresh ({age:.1f} days old). "
            f"Skipping fetch. Use force=True to override."
        )
        return

    log.info("Fetching Soil Health Card data (bulk CSV from CKAN)...")

    # ── Level 2: raw CSV download (skipped if fresh) ─────────────────
    if not _download_csv(force=force):
        log.error("CSV download failed. Skipping soil fetch.")
        return

    # ── Aggregate ────────────────────────────────────────────────────
    try:
        districts = _aggregate_district(RAW_CSV)
    except Exception as err:
        log.error(f"Aggregation failed: {err}")
        return

    if not districts:
        log.warning("No district records produced from CSV.")
        return

    save_json(OUTPUT_FILE, {
        "source": "Soil Health Card - India Data Portal (CKAN)",
        "data_type": "soil_health_district_aggregated",
        "fetched_at": utc_now(),
        "total_districts": len(districts),
        "districts": districts,
    })

    log.info(
        f"Soil data saved → {OUTPUT_FILE} "
        f"({len(districts)} districts with nutrient data)"
    )


if __name__ == "__main__":
    fetch_soil()