"""
weather.py — Pan-India weather fetcher (Open-Meteo).

Fetches 7-day daily forecasts for every LGD district using Open-Meteo's
batch API. Coordinates are sourced from the LGD reference file.

Open-Meteo counts each coordinate as a separate call, so batch size and
inter-batch delay must respect the 600 calls/minute free-tier limit.
"""

import time

from utils import PROCESSED_DIR, log, safe_get, save_json, utc_now
from fetchers.lgd import load_lgd_districts

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BATCH_SIZE = 20          # 20 coordinates per call
REQUEST_DELAY = 3.0      # pause between batches (respects 600/min limit)
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


def fetch_weather_pan_india():
    """
    Fetch daily weather for every LGD district and save the result.

    Output: data/processed/weather/pan_india_weather.json
    """
    log.info("Fetching Pan-India weather (Open-Meteo, all districts)...")

    districts = load_lgd_districts()
    if not districts:
        log.error("No LGD districts loaded. Run fetch_lgd_reference() first.")
        return

    log.info(
        f"Loaded {len(districts)} districts. "
        f"Batch size = {BATCH_SIZE}, delay = {REQUEST_DELAY}s."
    )

    results = {}
    failed = 0
    batches = list(_chunks(districts, BATCH_SIZE))

    for batch_idx, batch in enumerate(batches, 1):
        lats = ",".join(str(d["latitude"]) for d in batch)
        lons = ",".join(str(d["longitude"]) for d in batch)

        params = {
            "latitude": lats,
            "longitude": lons,
            "daily": DAILY_VARS,
            "timezone": "Asia/Kolkata",
            "forecast_days": FORECAST_DAYS,
        }

        log.info(
            f"Batch {batch_idx}/{len(batches)} — {len(batch)} districts"
        )

        res = safe_get(BASE_URL, params=params, timeout=60, retries=1)
        if not res:
            log.warning(f"Batch {batch_idx} failed. Skipping.")
            failed += len(batch)
            # Longer backoff when we hit a rate limit
            time.sleep(REQUEST_DELAY * 2)
            continue

        try:
            data = res.json()
            payloads = data if isinstance(data, list) else [data]

            for district, payload in zip(batch, payloads):
                key = f"{district['state']}|{district['district']}"
                results[key] = {
                    "state": district["state"],
                    "district": district["district"],
                    "latitude": district["latitude"],
                    "longitude": district["longitude"],
                    "forecast": payload.get("daily", {}),
                }
        except Exception as err:
            log.error(f"Parse error in batch {batch_idx}: {err}")
            failed += len(batch)

        # Polite pause between batches
        if batch_idx < len(batches):
            time.sleep(REQUEST_DELAY)

    record = {
        "source": "Open-Meteo",
        "data_type": "weather_forecast_pan_india",
        "fetched_at": utc_now(),
        "total_locations": len(results),
        "failed_locations": failed,
        "locations": results,
    }

    out_file = PROCESSED_DIR / "weather" / "pan_india_weather.json"
    save_json(out_file, record)
    log.info(
        f"Weather saved → {out_file} "
        f"({len(results)} locations, {failed} failed)"
    )