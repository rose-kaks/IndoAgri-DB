from utils import ensure_dirs, PROCESSED_DIR, log

from fetchers import (
    fetch_weather_pan_india,
    fetch_soil,
    fetch_agmarknet_complete,
    fetch_disaster_alerts,
    fetch_pib_agri_news,
    fetch_farmer_schemes,
)


def main():
    ensure_dirs()

    log.info(
        "Starting Offline Edge RAG Data Acquisition Pipeline...\n"
    )

    fetch_weather_pan_india()

    fetch_soil(
        state="Bihar",
        district="Araria",
        block="Araria",
        village="Araria"
    )

    fetch_agmarknet_complete()
    fetch_disaster_alerts()
    fetch_pib_agri_news()
    fetch_farmer_schemes()

    log.info("\n" + "=" * 60)
    log.info("Pipeline Execution Complete!")
    log.info(
        f"All processed data saved under → "
        f"{PROCESSED_DIR.resolve()}"
    )
    log.info("=" * 60)


if __name__ == "__main__":
    main()
