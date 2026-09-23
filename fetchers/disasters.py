"""
disasters.py — GDACS disaster alerts for India.

Fetches the GDACS RSS feed and keeps only alerts that:
  1. Affect India (via the gdacs:country tag or a strict word-boundary
     match on "India" in the description).
  2. Were published in the last ALERT_MAX_AGE_DAYS days.

Old or non-India alerts are discarded.
"""

import re
import warnings
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from utils import (
    HEADERS,
    PROCESSED_DIR,
    cache_age_days,
    is_cache_fresh,
    log,
    save_json,
    utc_now,
)

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

OUTPUT_FILE = PROCESSED_DIR / "disasters" / "recent_alerts.json"
MAX_CACHE_AGE_DAYS = 1          # re-fetch at most once per day
ALERT_MAX_AGE_DAYS = 7          # only keep alerts from the last 7 days
RSS_URL = "https://www.gdacs.org/xml/rss.xml"
MAX_BYTES = 5 * 1024 * 1024     # 5 MB cap

# Strict word-boundary pattern — matches "India" but not "Indian Ocean"
INDIA_PATTERN = re.compile(r"\bIndia\b", re.IGNORECASE)


def fetch_disaster_alerts(force: bool = False):
    """Fetch recent disaster alerts relevant to India."""
    if not force and is_cache_fresh(OUTPUT_FILE, MAX_CACHE_AGE_DAYS):
        age = cache_age_days(OUTPUT_FILE)
        log.info(
            f"Disaster data is fresh ({age:.1f} days old). "
            f"Skipping fetch. Use force=True to override."
        )
        return

    log.info("Fetching recent India-relevant disaster alerts (GDACS)...")

    alerts = []

    try:
        res = requests.get(
            RSS_URL,
            headers=HEADERS,
            timeout=(10, 20),
            stream=True,
        )
        if res.status_code != 200:
            log.warning(f"GDACS returned HTTP {res.status_code}. Skipping.")
            res.close()
            return

        content = b""
        for chunk in res.iter_content(chunk_size=16384):
            content += chunk
            if len(content) >= MAX_BYTES:
                log.warning("GDACS response exceeded 5 MB cap; truncating.")
                break
        res.close()

        soup = BeautifulSoup(content, "xml")
        items = soup.find_all("item")

        cutoff = datetime.now(timezone.utc) - timedelta(days=ALERT_MAX_AGE_DAYS)

        for item in items:
            # ── 1. Check the GDACS country tag ──────────────────────
            country_tag = item.find("gdacs:country")
            country_text = country_tag.get_text(strip=True) if country_tag else ""

            title = item.find("title").get_text(strip=True) if item.find("title") else ""
            link = item.find("link").get_text(strip=True) if item.find("link") else ""
            pub_date_raw = item.find("pubDate").get_text(strip=True) if item.find("pubDate") else ""

            desc_tag = item.find("description")
            raw_desc = desc_tag.get_text(strip=True) if desc_tag else ""
            clean_desc = BeautifulSoup(raw_desc, "html.parser").get_text(" ", strip=True)

            # ── 2. India-only filter ────────────────────────────────
            is_india = "India" in country_text or INDIA_PATTERN.search(
                f"{title} {clean_desc}"
            )
            if not is_india:
                continue

            # ── 3. Time filter ──────────────────────────────────────
            pub_dt = _parse_rss_date(pub_date_raw)
            if pub_dt is not None and pub_dt < cutoff:
                continue   # too old, skip

            alerts.append({
                "title": title,
                "link": link,
                "pub_date": pub_date_raw,
                "alert_text": clean_desc,
                "fetched_at": utc_now(),
            })

    except requests.RequestException as err:
        log.error(f"GDACS fetch failed: {err}")

    # Keep the 15 most recent
    alerts = alerts[:15]

    record = {
        "source": "GDACS (India-only, last 7 days)",
        "data_type": "disaster_alerts",
        "fetched_at": utc_now(),
        "total_alerts": len(alerts),
        "alerts": alerts,
    }

    save_json(OUTPUT_FILE, record)
    log.info(f"Disaster alerts saved → {OUTPUT_FILE} ({len(alerts)} India alerts)")


def _parse_rss_date(text: str):
    """Parse an RFC-822 RSS date into a timezone-aware datetime."""
    if not text:
        return None
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None