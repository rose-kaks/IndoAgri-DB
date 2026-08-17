from utils import PROCESSED_DIR, save_json, utc_now, log
import requests


RESOURCE_ID = "024cf507-4281-4c89-a40e-37b5add3a4df"

API_URL = (
    "https://ckandev.indiadataportal.com/"
    "api/action/datastore_search_sql"
)


def fetch_soil(
    state,
    district=None,
    block=None,
    village=None
):
    """
    Fetch latest available Soil Health Card data
    for a specific location.
    """

    log.info(
        f"Fetching soil data for "
        f"{state}"
        + (f" / {district}" if district else "")
        + (f" / {block}" if block else "")
        + (f" / {village}" if village else "")
    )

    # --------------------------------------------------
    # Build location filters
    # --------------------------------------------------

    conditions = [
        f"state_name = '{state}'"
    ]

    if district:
        conditions.append(
            f"district_name = '{district}'"
        )

    if block:
        conditions.append(
            f"block_name = '{block}'"
        )

    if village:
        conditions.append(
            f"village_name = '{village}'"
        )

    where_clause = " AND ".join(conditions)

    # --------------------------------------------------
    # Find latest year
    # --------------------------------------------------

    year_sql = f'''
        SELECT MAX(year) AS latest_year
        FROM "{RESOURCE_ID}"
        WHERE {where_clause}
    '''

    try:

        response = requests.get(
            API_URL,
            params={"sql": year_sql},
            timeout=60
        )

        response.raise_for_status()

        year_data = response.json()

    except requests.RequestException as err:

        log.error(
            f"Failed to fetch latest soil year: {err}"
        )

        return None

    records = (
        year_data
        .get("result", {})
        .get("records", [])
    )

    if not records:

        log.warning(
            "No soil year found."
        )

        return None

    latest_year = records[0].get(
        "latest_year"
    )

    if not latest_year:

        log.warning(
            f"No soil data found for {state}"
        )

        return None

    log.info(
        f"Latest soil year: {latest_year}"
    )

    # --------------------------------------------------
    # Fetch soil records
    # --------------------------------------------------

    sql = f'''
        SELECT
            year,
            state_name,
            state_code,
            district_name,
            district_code,
            block_name,
            block_code,
            village_name,
            village_code,
            nutrient_type,
            nutrient_name,
            nutrient_level,
            value
        FROM "{RESOURCE_ID}"
        WHERE {where_clause}
          AND year = '{latest_year}'
        ORDER BY
            nutrient_name,
            nutrient_level
    '''

    try:

        response = requests.get(
            API_URL,
            params={"sql": sql},
            timeout=60
        )

        response.raise_for_status()

        data = response.json()

    except requests.RequestException as err:

        log.error(
            f"Failed to fetch soil records: {err}"
        )

        return None

    records = (
        data
        .get("result", {})
        .get("records", [])
    )

    if not records:

        log.warning(
            "No soil records found."
        )

        return None

    # --------------------------------------------------
    # Build normalized result
    # --------------------------------------------------

    first = records[0]

    result = {
        "source":
            "Soil Health Card - India Data Portal",

        "data_type":
            "soil_health",

        "fetched_at":
            utc_now(),

        "location": {

            "state":
                first["state_name"],

            "state_code":
                first["state_code"],

            "district":
                first["district_name"],

            "district_code":
                first["district_code"],

            "block":
                first["block_name"],

            "block_code":
                first["block_code"],

            "village":
                first["village_name"],

            "village_code":
                first["village_code"]
        },

        "year":
            latest_year,

        "soil": {}
    }

    # --------------------------------------------------
    # Group nutrient → level → count
    # --------------------------------------------------

    for record in records:

        nutrient = record[
            "nutrient_name"
        ]

        level = record[
            "nutrient_level"
        ]

        value = record[
            "value"
        ]

        if nutrient not in result["soil"]:

            result["soil"][nutrient] = {
                "distribution": {},
                "dominant_level": None,
                "total_samples": 0
            }

        result["soil"][
            nutrient
        ][
            "distribution"
        ][
            level
        ] = value

    # --------------------------------------------------
    # Derive dominant level + sample count
    # --------------------------------------------------

    for nutrient, info in result["soil"].items():

        distribution = info[
            "distribution"
        ]

        info[
            "total_samples"
        ] = sum(
            distribution.values()
        )

        if not distribution:
            continue

        max_count = max(
            distribution.values()
        )

        dominant_levels = [
            level
            for level, count
            in distribution.items()
            if count == max_count
        ]

        if len(dominant_levels) == 1:

            info[
                "dominant_level"
            ] = dominant_levels[0]

        else:

            info[
                "dominant_level"
            ] = "Tie"

            info[
                "dominant_levels"
            ] = dominant_levels

    # --------------------------------------------------
    # Save processed data
    # --------------------------------------------------

    output_dir = (
        PROCESSED_DIR / "soil"
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    filename_parts = [
        state,
        district,
        block,
        village
    ]

    filename_parts = [
        str(x)
        .lower()
        .replace(" ", "_")
        .replace("/", "_")
        for x in filename_parts
        if x
    ]

    filename = (
        "_".join(filename_parts)
        + ".json"
    )

    out_file = (
        output_dir / filename
    )

    save_json(
        out_file,
        result
    )

    log.info(
        f"Soil data saved → "
        f"{out_file}"
    )

    return result
