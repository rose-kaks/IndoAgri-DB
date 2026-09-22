from utils import ensure_dirs, PROCESSED_DIR, log

from fetchers import (
    fetch_lgd_reference,
    fetch_weather_pan_india,
    fetch_soil,
    fetch_agmarknet_complete,
    fetch_disaster_alerts,
    fetch_pib_agri_news,
    fetch_farmer_schemes,
    fetch_kcc,
)


def main():
    ensure_dirs()

    log.info("Starting IndoAgri-KB Data Acquisition Pipeline...\n")

    # 1. Reference layer (must run first — weather + soil depend on it)
    fetch_lgd_reference()

    # 2. Structured sources
    fetch_weather_pan_india()
    fetch_soil()
    fetch_agmarknet_complete()

    # 3. Unstructured / semi-structured sources
    fetch_disaster_alerts()
    fetch_pib_agri_news()
    fetch_farmer_schemes()
    fetch_kcc()

    log.info("\n" + "=" * 60)
    log.info("Pipeline Execution Complete!")
    log.info(f"All processed data saved under → {PROCESSED_DIR.resolve()}")
    log.info("=" * 60)


if __name__ == "__main__":
    main()