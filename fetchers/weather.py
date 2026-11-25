"""
weather.py — Pan-India weather fetcher (Open-Meteo).

Fetches 7-day daily forecasts for every LGD district using Open-Meteo's
batch API. Coordinates are sourced from the LGD reference file.

Open-Meteo counts each coordinate as a separate call, so batch size and
inter-batch delay must respect the 600 calls/minute free-tier limit.
"""

import time

from utils import (
    PROCESSED_DIR,
    log,
    safe_get,
    save_json,
    utc_now,
    is_cache_fresh,
    cache_age_days,
)

from fetchers.lgd import load_lgd_districts


OUTPUT_FILE = PROCESSED_DIR / "weather" / "pan_india_weather.json"
MAX_CACHE_AGE_DAYS = 1

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BATCH_SIZE = 20
REQUEST_DELAY = 3.0
FORECAST_DAYS = 7

DAILY_VARS = (
    "temperature_2m_max,"
    "temperature_2m_min,"
    "precipitation_sum,"
    "et0_fao_evapotranspiration,"
    "relative_humidity_2m_mean"
)

BASE_URL = "https://api.open-meteo.com/v1/forecast"


def _chunks(items, size):
    """Yield successive chunks of *size* from *items*."""
    for i in range(0, len(items), size):
        yield items[i:i + size]


def fetch_weather_pan_india(force: bool = False):

    # -----------------------------------------------------------------------
    # Cache check
    # -----------------------------------------------------------------------

    if not force and is_cache_fresh(OUTPUT_FILE, MAX_CACHE_AGE_DAYS):
        age = cache_age_days(OUTPUT_FILE)

        log.info(
            f"Weather data is fresh ({age:.1f} days old). "
            f"Skipping fetch. Use force=True to override."
        )

        return

    log.info(
        "Fetching Pan-India weather (Open-Meteo, all districts)..."
    )

    # -----------------------------------------------------------------------
    # Load LGD districts
    # -----------------------------------------------------------------------

    districts = load_lgd_districts()

    if not districts:
        log.error(
            "No LGD districts loaded. Run fetch_lgd_reference() first."
        )
        return

    log.info(
        f"Loaded {len(districts)} districts. "
        f"Batch size = {BATCH_SIZE}, delay = {REQUEST_DELAY}s."
    )

    # -----------------------------------------------------------------------
    # Fetch batches
    # -----------------------------------------------------------------------

    results = {}
    failed = 0

    batches = list(_chunks(districts, BATCH_SIZE))

    for batch_idx, batch in enumerate(batches, 1):

        lats = ",".join(
            str(d["latitude"])
            for d in batch
        )

        lons = ",".join(
            str(d["longitude"])
            for d in batch
        )

        params = {
            "latitude": lats,
            "longitude": lons,
            "daily": DAILY_VARS,
            "timezone": "Asia/Kolkata",
            "forecast_days": FORECAST_DAYS,
        }

        log.info(
            f"Batch {batch_idx}/{len(batches)} — "
            f"{len(batch)} districts"
        )

        # -------------------------------------------------------------------
        # Request
        # -------------------------------------------------------------------

        res = safe_get(
            BASE_URL,
            params=params,
            timeout=60,
            retries=1,
        )

        # Request completely failed
        if not res:

            log.warning(
                f"Batch {batch_idx} failed. Skipping."
            )

            failed += len(batch)

            # Give Open-Meteo a little more time before next batch
            time.sleep(REQUEST_DELAY * 2)

            continue

        # -------------------------------------------------------------------
        # Parse response
        # -------------------------------------------------------------------

        try:

            data = res.json()

            # Open-Meteo returns:
            #
            # - a dict for one location
            # - a list of dicts for multiple locations
            #
            payloads = (
                data
                if isinstance(data, list)
                else [data]
            )

            # ---------------------------------------------------------------
            # Validate number of responses
            # ---------------------------------------------------------------

            if len(payloads) != len(batch):

                log.error(
                    f"Batch {batch_idx}: expected "
                    f"{len(batch)} responses but received "
                    f"{len(payloads)}."
                )

                failed += len(batch)

                continue

            # ---------------------------------------------------------------
            # Validate and store each district
            # ---------------------------------------------------------------

            valid_payloads = 0

            for district, payload in zip(batch, payloads):

                # IMPORTANT:
                # Never use payload before checking that it is a dict.
                if not isinstance(payload, dict):

                    log.warning(
                        f"Batch {batch_idx}: invalid payload for "
                        f"{district['district']}. Skipping."
                    )

                    failed += 1
                    continue

                daily = payload.get("daily", {})

                if not isinstance(daily, dict):

                    log.warning(
                        f"Batch {batch_idx}: missing daily data for "
                        f"{district['district']}. Skipping."
                    )

                    failed += 1
                    continue

                if not daily.get("time"):

                    log.warning(
                        f"Batch {batch_idx}: empty forecast for "
                        f"{district['district']}. Skipping."
                    )

                    failed += 1
                    continue

                key = (
                    f"{district['state']}|"
                    f"{district['district']}"
                )

                results[key] = {
                    "state": district["state"],
                    "district": district["district"],
                    "latitude": district["latitude"],
                    "longitude": district["longitude"],
                    "forecast": daily,
                }

                valid_payloads += 1

            log.info(
                f"Batch {batch_idx} successful: "
                f"{valid_payloads}/{len(batch)} districts"
            )

        except Exception as err:

            log.error(
                f"Parse error in batch {batch_idx}: {err}"
            )

            failed += len(batch)

        # -------------------------------------------------------------------
        # Delay before next batch
        # -------------------------------------------------------------------

        if batch_idx < len(batches):

            time.sleep(REQUEST_DELAY)

    # -----------------------------------------------------------------------
    # SAFETY CHECK
    #
    # Do NOT overwrite an existing good weather file with a partial result.
    # -----------------------------------------------------------------------

    success_count = len(results)
    total_count = len(districts)

    success_ratio = (
        success_count / total_count
        if total_count
        else 0
    )

    log.info(
        f"Weather fetch complete: "
        f"{success_count}/{total_count} districts "
        f"({success_ratio * 100:.1f}%)"
    )

    # Require at least 95% successful districts
    if success_ratio < 0.95:

        log.error(
            f"Only {success_count}/{total_count} districts fetched "
            f"({success_ratio * 100:.1f}%)."
        )

        log.error(
            "Keeping existing weather file. "
            "No partial weather dataset will be saved."
        )

        raise RuntimeError(
            "Weather fetch failed validation: "
            f"only {success_count}/{total_count} districts fetched."
        )

    # -----------------------------------------------------------------------
    # Save ONLY after successful validation
    # -----------------------------------------------------------------------

    record = {
        "source": "Open-Meteo",
        "data_type": "weather_forecast_pan_india",
        "fetched_at": utc_now(),
        "total_locations": success_count,
        "failed_locations": failed,
        "locations": results,
    }

    save_json(
        OUTPUT_FILE,
        record,
    )

    log.info(
        f"Weather saved → {OUTPUT_FILE} "
        f"({success_count} locations, {failed} failed)"
    )
