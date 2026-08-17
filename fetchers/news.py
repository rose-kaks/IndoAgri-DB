import warnings
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from utils import PROCESSED_DIR, safe_get, save_json, utc_now, log

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

def fetch_pib_agri_news():
    """
    Fetch agriculture-related press releases.
    Strategy:
    1. Try PIB RSS
    2. Filter strictly for agriculture keywords
    3. Fallback to PIB homepage only if needed
    """
    log.info("Fetching agriculture-related PIB press releases...")

    AGRI_KEYWORDS = [
        "agriculture", "farmer", "farmers", "kisan", "crop", "crops",
        "mandi", "fertilizer", "fertiliser", "irrigation", "soil",
        "pm-kisan", "pm kisan", "msp", "minimum support price",
        "wheat", "rice", "paddy", "cotton", "sugarcane", "pulses",
        "oilseed", "horticulture", "dairy", "fisheries", "livestock",
        "krishi", "agri", "sowing", "harvest", "drought", "monsoon"
    ]

    news_items = []

    # --- Attempt 1: PIB RSS ---
    rss_urls = [
        "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3",
        "https://pib.gov.in/rss/RssFilter.aspx"
    ]

    for url in rss_urls:
        res = safe_get(url, timeout=15)
        if not res:
            continue

        try:
            soup = BeautifulSoup(res.content, "xml")
            items = soup.find_all("item")

            for item in items:
                title = item.find("title").get_text(strip=True) if item.find("title") else ""
                link = item.find("link").get_text(strip=True) if item.find("link") else ""
                pub_date = item.find("pubDate").get_text(strip=True) if item.find("pubDate") else ""
                
                desc_tag = item.find("description")
                raw_desc = desc_tag.get_text(strip=True) if desc_tag else ""
                clean_desc = BeautifulSoup(raw_desc, "html.parser").get_text(" ", strip=True)

                combined = f"{title} {clean_desc}".lower()

                if any(kw in combined for kw in AGRI_KEYWORDS) and len(title) > 15:
                    news_items.append({
                        "title": title,
                        "link": link,
                        "pub_date": pub_date,
                        "summary": clean_desc or title,
                        "fetched_at": utc_now()
                    })

            if news_items:
                break  # Successfully got relevant items

        except Exception as err:
            log.warning(f"RSS parsing failed for {url}: {err}")

    # --- Attempt 2: Homepage fallback (only if RSS gave nothing useful) ---
    if len(news_items) < 5:
        log.info("RSS yielded few agri items. Trying PIB homepage fallback...")
        portal_url = "https://pib.gov.in/indexd.aspx"
        res_portal = safe_get(portal_url, timeout=15)

        if res_portal:
            try:
                soup = BeautifulSoup(res_portal.text, "html.parser")
                for a in soup.find_all("a", href=True):
                    href = a.get("href", "")
                    title = a.get_text(strip=True)

                    if ("PRID=" in href or "PressRelease" in href) and len(title) > 20:
                        combined = title.lower()
                        if any(kw in combined for kw in AGRI_KEYWORDS):
                            full_link = href if href.startswith("http") else f"https://pib.gov.in/{href.lstrip('/')}"
                            
                            # Avoid duplicates
                            if not any(item["link"] == full_link for item in news_items):
                                news_items.append({
                                    "title": title,
                                    "link": full_link,
                                    "pub_date": utc_now(),
                                    "summary": title,
                                    "fetched_at": utc_now()
                                })

                            if len(news_items) >= 15:
                                break
            except Exception as err:
                log.error(f"Homepage fallback failed: {err}")


    record = {
        "source": "Press Information Bureau (Agriculture filtered)",
        "data_type": "agri_news",
        "fetched_at": utc_now(),
        "total_count": len(news_items),
        "articles": news_items
    }

    out_file = PROCESSED_DIR / "news" / "pib_agri_news.json"
    save_json(out_file, record)
    log.info(f"Agri news saved → {out_file} ({len(news_items)} relevant items)")