"""
disasters.py — GDACS disaster alerts for India.

Fetches the GDACS RSS feed and keeps only alerts relevant to India
and its immediate neighbourhood.

The RSS body is streamed with a 5 MB cap so a slow or oversized
response cannot hang the pipeline.
"""

import warnings

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from utils import HEADERS, PROCESSED_DIR, is_cache_fresh, cache_age_days, log, save_json, utc_now
from pathlib import Path

OUTPUT_FILE = PROCESSED_DIR / "disasters" / "recent_alerts.json"
MAX_CACHE_AGE_DAYS = 1

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

RSS_URL = "https://www.gdacs.org/xml/rss.xml"
MAX_BYTES = 5 * 1024 * 1024  # 5 MB cap

INDIA_KEYWORDS = [
    "india", "indian", "bay of bengal", "arabian sea",
    "nepal", "bangladesh", "sri lanka", "pakistan",
    "myanmar", "andaman", "nicobar", "lakshadweep",
    "monsoon", "cyclone", "flood", "landslide",
]


def fetch_disaster_alerts(force: bool = False):
    if not force and is_cache_fresh(OUTPUT_FILE, MAX_CACHE_AGE_DAYS):
        age = cache_age_days(OUTPUT_FILE)
        log.info(
            f"Disaster data is fresh ({age:.1f} days old). "
            f"Skipping fetch. Use force=True to override."
        )
        return
    """Fetch disaster alerts relevant to India (GDACS RSS)."""
    log.info("Fetching disaster alerts relevant to India (GDACS)...")

    alerts = []

    try:
        res = requests.get(
            RSS_URL,
            headers=HEADERS,
            timeout=(10, 20),   # (connect, read-per-chunk)
            stream=True,
        )
        if res.status_code != 200:
            log.warning(f"GDACS returned HTTP {res.status_code}. Skipping.")
            res.close()
            return

        # Stream with a hard cap so a slow feed cannot hang the pipeline
        content = b""
        for chunk in res.iter_content(chunk_size=16384):
            content += chunk
            if len(content) >= MAX_BYTES:
                log.warning("GDACS response exceeded 5 MB cap; truncating.")
                break
        res.close()

        soup = BeautifulSoup(content, "xml")
        items = soup.find_all("item")

        for idx, item in enumerate(items):
            title = item.find("title").get_text(strip=True) if item.find("title") else ""
            link = item.find("link").get_text(strip=True) if item.find("link") else ""
            pub_date = item.find("pubDate").get_text(strip=True) if item.find("pubDate") else ""

            desc_tag = item.find("description")
            raw_desc = desc_tag.get_text(strip=True) if desc_tag else ""
            clean_desc = BeautifulSoup(raw_desc, "html.parser").get_text(" ", strip=True)

            combined = f"{title} {clean_desc}".lower()

            if any(kw in combined for kw in INDIA_KEYWORDS):
                alerts.append({
                    "id": f"gdacs_{idx}",
                    "title": title,
                    "link": link,
                    "pub_date": pub_date,
                    "alert_text": clean_desc,
                    "fetched_at": utc_now(),
                })

    except requests.RequestException as err:
        log.error(f"GDACS fetch failed: {err}")

    alerts = alerts[:15]

    record = {
        "source": "GDACS (Filtered for India region)",
        "data_type": "disaster_alerts",
        "fetched_at": utc_now(),
        "total_alerts": len(alerts),
        "alerts": alerts,
    }

    out_file = PROCESSED_DIR / "disasters" / "recent_alerts.json"
    save_json(out_file, record)
    log.info(f"Disaster alerts saved → {out_file} ({len(alerts)} India-relevant alerts)")