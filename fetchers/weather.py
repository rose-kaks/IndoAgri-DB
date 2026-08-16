import time
from utils import PROCESSED_DIR, safe_get, save_json, utc_now, log

MAJOR_LOCATIONS = {
    "delhi": (28.6139, 77.2090),
    "mumbai": (19.0760, 72.8777),
    "kolkata": (22.5726, 88.3639),
    "chennai": (13.0827, 80.2707),
    "bengaluru": (12.9716, 77.5946),
    "hyderabad": (17.3850, 78.4867),
    "ahmedabad": (23.0225, 72.5714),
    "jaipur": (26.9124, 75.7873),
    "lucknow": (26.8467, 80.9462),
    "patna": (25.5941, 85.1376),
    "bhopal": (23.2599, 77.4126),
    "chandigarh": (30.7333, 76.7794),
    "guwahati": (26.1445, 91.7362),
    "thiruvananthapuram": (8.5241, 76.9366),
    "nagpur": (21.1458, 79.0882),
    "indore": (22.7196, 75.8577),
}

def fetch_weather_pan_india():
    log.info("Fetching Pan-India weather (Open-Meteo)...")
    res = {}

    for loc_name, (lat, lon) in MAJOR_LOCATIONS.items():
        url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}"
            f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,et0_fao_evapotranspiration"
            f"&timezone=Asia%2FKolkata&forecast_days=7"
        )
        r = safe_get(url, timeout=15)
        if r:
            try:
                data = r.json()
                res[loc_name] = {
                    "lat": lat,
                    "lon": lon,
                    "forecast": data.get("daily", {})
                }
                log.info(f"  ✓ {loc_name}")
            except Exception as err:
                log.error(f"  Parse error {loc_name}: {err}")
        time.sleep(0.35)

    rec = {
        "source": "Open-Meteo",
        "data_type": "weather_forecast_pan_india",
        "fetched_at": utc_now(),
        "locations": res
    }
    out_file = PROCESSED_DIR / "weather" / "pan_india_weather.json"
    save_json(out_file, rec)
    log.info(f"Weather saved → {out_file}")