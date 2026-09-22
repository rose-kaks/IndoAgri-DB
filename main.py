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


def main(force: bool = False):
    ensure_dirs()

    log.info("Starting IndoAgri-KB Data Acquisition Pipeline...\n")

    # 1. Reference layer (must run first — weather + soil depend on it)
    fetch_lgd_reference(force=force)

    # 2. Structured sources
    fetch_weather_pan_india(force=force)
    fetch_soil(force=force)
    fetch_agmarknet_complete(force=force)

    # 3. Unstructured / semi-structured sources
    fetch_disaster_alerts(force=force)
    fetch_pib_agri_news(force=force)
    fetch_farmer_schemes(force=force)
    fetch_kcc(force=force)

    log.info("\n" + "=" * 60)
    log.info("Pipeline Execution Complete!")
    log.info(f"All processed data saved under → {PROCESSED_DIR.resolve()}")
    log.info("=" * 60)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--force", action="store_true",
        help="Ignore cache and re-fetch everything."
    )
    args = parser.parse_args()
    main(force=args.force)