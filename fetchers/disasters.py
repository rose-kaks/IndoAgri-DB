import warnings
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from utils import PROCESSED_DIR, safe_get, save_json, utc_now, log

# Suppress BeautifulSoup XML vs HTML parser warning
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

def fetch_disaster_alerts():
    log.info("Fetching real-time disaster alerts (GDACS / IMD)...")
    
    url = "https://www.gdacs.org/xml/rss.xml"
    res = safe_get(url, timeout=15)
    alerts = []

    if res:
        try:
            soup = BeautifulSoup(res.content, "html.parser")
            items = soup.find_all("item")

            for idx, item in enumerate(items):
                title = item.find("title").get_text(strip=True) if item.find("title") else ""
                link = item.find("link").get_text(strip=True) if item.find("link") else ""
                pub_date = item.find("pubdate").get_text(strip=True) if item.find("pubdate") else ""
                raw_desc = item.find("description").get_text(strip=True) if item.find("description") else ""
                clean_desc = BeautifulSoup(raw_desc, "html.parser").get_text(strip=True) if raw_desc else ""

                text_content = f"{title} {clean_desc}".lower()
                
                regional_terms = ["india", "nepal", "bangladesh", "sri lanka", "bay of bengal", "arabian sea", "monsoon", "flood", "cyclone"]
                if any(term in text_content for term in regional_terms):
                    alerts.append({
                        "id": f"gdacs_alert_{idx}",
                        "title": title,
                        "link": link,
                        "pub_date": pub_date,
                        "alert_text": clean_desc,
                        "fetched_at": utc_now()
                    })
        except Exception as err:
            log.error(f"Error parsing GDACS feed: {err}")

    rec = {
        "source": "Disaster Alerts (GDACS / IMD)",
        "data_type": "disaster_alerts",
        "fetched_at": utc_now(),
        "total_alerts": len(alerts),
        "alerts": alerts
    }
    out_file = PROCESSED_DIR / "disasters" / "recent_alerts.json"
    save_json(out_file, rec)
    log.info(f"Disaster alerts saved → {out_file} ({len(alerts)} active alerts)")