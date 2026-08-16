from utils import PROCESSED_DIR, load_api_key, safe_get, save_json, utc_now, log

def fetch_agmarknet_complete():
    log.info("Fetching complete Agmarknet dataset via Data.gov.in API...")
    api_key = load_api_key("AGMARKNET_API_KEY")

    if not api_key:
        log.error("API key missing. Set AGMARKNET_API_KEY in environment or config.json.")
        return

    url = "https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070"
    page_size = 1000
    curr_offset = 0
    all_records = []

    while True:
        params = {
            "api-key": api_key,
            "format": "json",
            "limit": page_size,
            "offset": curr_offset
        }

        log.info(f"Fetching records {curr_offset} to {curr_offset + page_size}...")
        r = safe_get(url, params=params, timeout=30)
        
        if not r:
            log.error(f"Failed batch at offset {curr_offset}.")
            break

        try:
            raw_data = r.json()
            records = raw_data.get("records", [])

            if not records:
                log.info("No more Agmarknet records found.")
                break

            for row in records:
                all_records.append({
                    "state": row.get("state"),
                    "district": row.get("district"),
                    "market": row.get("market"),
                    "commodity": row.get("commodity"),
                    "variety": row.get("variety"),
                    "min_price": row.get("min_price"),
                    "max_price": row.get("max_price"),
                    "modal_price": row.get("modal_price"),
                    "arrival_date": row.get("arrival_date"),
                    "fetched_at": utc_now()
                })

            curr_offset += len(records)
            if len(records) < page_size:
                break

        except Exception as err:
            log.error(f"Failed to parse batch at offset {curr_offset}: {err}")
            break

    if all_records:
        rec_data = {
            "source": "Data.gov.in (Agmarknet API)",
            "data_type": "mandi_prices",
            "fetched_at": utc_now(),
            "total_count": len(all_records),
            "records": all_records
        }
        out_file = PROCESSED_DIR / "agmarknet" / "agmarknet_today.json"
        save_json(out_file, rec_data)
        log.info(f"Agmarknet saved → {out_file} ({len(all_records)} total records)")