import warnings
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from utils import PROCESSED_DIR, safe_get, save_json, utc_now, log

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

def fetch_pib_agri_news():
    log.info("Fetching Press Information Bureau (PIB) press releases...")
    
    # Try active PIB RSS endpoints first
    url = "https://pib.gov.in/rss/RssFilter.aspx"
    res = safe_get(url, timeout=15)
    news_items = []

    if res:
        try:
            soup = BeautifulSoup(res.content, "html.parser")
            items = soup.find_all("item")

            for item in items[:25]:
                title = item.find("title").get_text(strip=True) if item.find("title") else ""
                link = item.find("link").get_text(strip=True) if item.find("link") else ""
                pub_date = item.find("pubdate").get_text(strip=True) if item.find("pubdate") else ""
                
                desc_tag = item.find("description")
                raw_desc = desc_tag.get_text(strip=True) if desc_tag else ""
                clean_desc = BeautifulSoup(raw_desc, "html.parser").get_text(strip=True) if raw_desc else ""

                if title and len(title) > 10:
                    news_items.append({
                        "title": title,
                        "link": link,
                        "pub_date": pub_date,
                        "summary": clean_desc or title,
                        "fetched_at": utc_now()
                    })
        except Exception as err:
            log.error(f"Error parsing PIB RSS feed: {err}")

    # Direct homepage fallback if RSS returns 0 items
    if not news_items:
        log.info("RSS feed empty or failed, scraping direct releases from PIB main portal...")
        portal_url = "https://pib.gov.in/indexd.aspx"
        res_portal = safe_get(portal_url, timeout=15)
        if res_portal:
            try:
                soup = BeautifulSoup(res_portal.text, "html.parser")
                # PIB lists releases inside <li> tags with links pointing to PressReleasePage or PressReleaseIframePage
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    title = a.get_text(strip=True)
                    if ("PRID=" in href or "PressRelease" in href) and len(title) > 15:
                        full_link = href if href.startswith("http") else f"https://pib.gov.in/{href}"
                        
                        # Avoid duplicate entries
                        if not any(item["link"] == full_link for item in news_items):
                            news_items.append({
                                "title": title,
                                "link": full_link,
                                "pub_date": utc_now(),
                                "summary": title,
                                "fetched_at": utc_now()
                            })
                            if len(news_items) >= 20:
                                break
            except Exception as err:
                log.error(f"Fallback scraping failed: {err}")

    rec = {
        "source": "Press Information Bureau",
        "data_type": "agri_news",
        "fetched_at": utc_now(),
        "total_count": len(news_items),
        "articles": news_items
    }
    out_file = PROCESSED_DIR / "news" / "pib_agri_news.json"
    save_json(out_file, rec)
    log.info(f"Agri news saved → {out_file} ({len(news_items)} items)")