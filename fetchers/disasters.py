import warnings
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from utils import PROCESSED_DIR, safe_get, save_json, utc_now, log

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

def fetch_disaster_alerts():
    """
    Fetch disaster alerts relevant to India and the surrounding region.
    Primary source: GDACS RSS (filtered strictly for India region).
    """
    log.info("Fetching disaster alerts relevant to India (GDACS)...")

    url = "https://www.gdacs.org/xml/rss.xml"
    res = safe_get(url, timeout=15)
    alerts = []

    # Strict regional relevance
    INDIA_KEYWORDS = [
        "india", "indian", "bay of bengal", "arabian sea",
        "nepal", "bangladesh", "sri lanka", "pakistan",
        "myanmar", "andaman", "nicobar", "lakshadweep",
        "monsoon", "cyclone", "flood", "landslide"
    ]

    if res:
        try:
            soup = BeautifulSoup(res.content, "xml")  # Better for RSS
            items = soup.find_all("item")

            for idx, item in enumerate(items):
                title = item.find("title").get_text(strip=True) if item.find("title") else ""
                link = item.find("link").get_text(strip=True) if item.find("link") else ""
                pub_date = item.find("pubDate").get_text(strip=True) if item.find("pubDate") else ""
                
                desc_tag = item.find("description")
                raw_desc = desc_tag.get_text(strip=True) if desc_tag else ""
                clean_desc = BeautifulSoup(raw_desc, "html.parser").get_text(" ", strip=True)

                combined = f"{title} {clean_desc}".lower()

                # Keep only India-relevant alerts
                if any(keyword in combined for keyword in INDIA_KEYWORDS):
                    alerts.append({
                        "id": f"gdacs_{idx}",
                        "title": title,
                        "link": link,
                        "pub_date": pub_date,
                        "alert_text": clean_desc,
                        "fetched_at": utc_now()
                    })

        except Exception as err:
            log.error(f"Error parsing GDACS feed: {err}")

    # Sort by date (newest first) if possible and keep top 15
    alerts = alerts[:15]

    record = {
        "source": "GDACS (Filtered for India region)",
        "data_type": "disaster_alerts",
        "fetched_at": utc_now(),
        "total_alerts": len(alerts),
        "alerts": alerts
    }

    out_file = PROCESSED_DIR / "disasters" / "recent_alerts.json"
    save_json(out_file, record)
    log.info(f"Disaster alerts saved → {out_file} ({len(alerts)} India-relevant alerts)")