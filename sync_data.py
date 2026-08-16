"""
Offline Edge RAG - Final Stage 1 Acquisition
Generic, reliable, multi-source
"""

import os
import json
import time
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

import requests
from bs4 import BeautifulSoup

try:
    import pymupdf as fitz
except ImportError:
    import fitz

# ------------------------------------------------------------
# CONFIG & SECRETS
# ------------------------------------------------------------
BASE = Path("./data")
RAW = BASE / "raw"
PROCESSED = BASE / "processed"
MANIFEST = BASE / "sources.txt"
CONFIG_FILE = Path("./config.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("sync")

def load_api_key() -> str:
    """Load API key from environment variable or local config.json file."""
    if os.getenv("AGMARKNET_API_KEY"):
        return os.getenv("AGMARKNET_API_KEY")
    
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            return cfg.get("AGMARKNET_API_KEY", "")
        except Exception as err:
            log.warning(f"Failed to read config.json: {err}")
            
    return ""

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def content_hash(txt: str) -> str:
    return hashlib.sha256(txt.encode("utf-8")).hexdigest()[:12]

def ensure_dirs():
    RAW.mkdir(parents=True, exist_ok=True)
    PROCESSED.mkdir(parents=True, exist_ok=True)

def safe_get(url: str, params: Optional[Dict] = None, timeout: int = 30, retries: int = 2) -> Optional[requests.Response]:
    for idx in range(retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=timeout)
            if r.status_code == 200:
                return r
            log.warning(f"HTTP {r.status_code} → {url}")
        except Exception as err:
            log.warning(f"Attempt {idx+1} failed: {err}")
        time.sleep(1.5)
    return None

def save_json(path: Path, obj: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")

def save_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

# ------------------------------------------------------------
# 1. PAN-INDIA WEATHER (Open-Meteo)
# ------------------------------------------------------------
MAJOR_LOCATIONS = {
    "delhi": (28.6139, 77.2090),
    "mumbai": (19.0760, 72.8777),
    "kolkata": (22.5726, 88.3639),
    "chennai": (13.0827, 80.2707),
    "bengaluru": (12.9716, 77.5946),
    "hyderabad": (17.3850, 78.4867),
    "ahmedabad": (23.0225, 72.5714),
    "jaipur": (26.9124, 75.7873),
    "lucknow": (26.8467, 80.9462),
    "patna": (25.5941, 85.1376),
    "bhopal": (23.2599, 77.4126),
    "chandigarh": (30.7333, 76.7794),
    "guwahati": (26.1445, 91.7362),
    "thiruvananthapuram": (8.5241, 76.9366),
    "nagpur": (21.1458, 79.0882),
    "indore": (22.7196, 75.8577),
}

def fetch_weather_pan_india():
    log.info("Fetching pan-India weather (Open-Meteo)...")
    res = {}

    for loc_name, (lat, lon) in MAJOR_LOCATIONS.items():
        url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}"
            f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,et0_fao_evapotranspiration"
            f"&timezone=Asia%2FKolkata&forecast_days=7"
        )
        r = safe_get(url, timeout=15)
        if r:
            try:
                data = r.json()
                res[loc_name] = {
                    "lat": lat,
                    "lon": lon,
                    "forecast": data.get("daily", {})
                }
                log.info(f"   ✓ {loc_name}")
            except Exception as err:
                log.error(f"   Parse error {loc_name}: {err}")
        time.sleep(0.35)

    rec = {
        "source": "Open-Meteo",
        "data_type": "weather_forecast_pan_india",
        "fetched_at": utc_now(),
        "locations": res
    }
    out_file = PROCESSED / "weather" / "pan_india_weather.json"
    save_json(out_file, rec)
    log.info(f"Weather saved → {out_file} ({len(res)} cities)")

# ------------------------------------------------------------
# 2. AGMARKNET (Official OGD Data API)
# ------------------------------------------------------------
def fetch_agmarknet_sample():
    log.info("Fetching Agmarknet prices via Data.gov.in API...")
    api_key = load_api_key()

    if not api_key:
        log.error("API key missing. Add your key to config.json or set AGMARKNET_API_KEY environment variable.")
        return

    url = "https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070"
    params = {
        "api-key": api_key,
        "format": "json",
        "limit": 1000  # Pull up to 1000 daily market entries
    }

    r = safe_get(url, params=params, timeout=30)
    if not r:
        log.error("Agmarknet API request failed.")
        return

    try:
        raw_data = r.json()
        records = raw_data.get("records", [])

        res_list = []
        for row in records:
            res_list.append({
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

        rec_data = {
            "source": "Data.gov.in (Agmarknet API)",
            "data_type": "mandi_prices",
            "fetched_at": utc_now(),
            "count": len(res_list),
            "records": res_list
        }
        out_file = PROCESSED / "agmarknet" / "agmarknet_today.json"
        save_json(out_file, rec_data)
        log.info(f"Agmarknet saved → {out_file} ({len(res_list)} records)")

    except Exception as err:
        log.error(f"Failed to process Agmarknet API response: {err}")

# ------------------------------------------------------------
# 3. PDF HANDLER
# ------------------------------------------------------------
def handle_pdf(url: str, save_name: str, cat_name: str):
    r = safe_get(url, timeout=50)
    if not r:
        log.error(f"PDF failed: {url}")
        return

    raw_file = RAW / cat_name / save_name
    raw_file.parent.mkdir(parents=True, exist_ok=True)
    raw_file.write_bytes(r.content)

    try:
        doc = fitz.open(stream=r.content, filetype="pdf")
        doc_text = "\n\n".join(p.get_text() for p in doc if p.get_text().strip())
        doc.close()
    except Exception as err:
        log.error(f"PDF extract failed ({save_name}): {err}")
        return

    if len(doc_text) < 400:
        log.warning(f"Low text yield: {save_name}")
        return

    rec_data = {
        "source": "ICAR / TNAU / NCIPM",
        "data_type": cat_name,
        "title": save_name.replace(".pdf", ""),
        "url": url,
        "fetched_at": utc_now(),
        "content_hash": content_hash(doc_text),
        "char_count": len(doc_text),
        "text": doc_text[:180000]
    }
    out_file = PROCESSED / cat_name / (save_name.replace(".pdf", ".json"))
    save_json(out_file, rec_data)
    log.info(f"✓ PDF → {out_file} ({len(doc_text)} chars)")

# ------------------------------------------------------------
# 4. HTML HANDLER
# ------------------------------------------------------------
def handle_html(url: str, save_name: str, cat_name: str):
    r = safe_get(url)
    if not r:
        return

    soup = BeautifulSoup(r.text, "lxml")
    container = (
        soup.find("div", id="TextContent")
        or soup.find("div", class_="content")
        or soup.find("div", class_="main-content")
        or soup.find("article")
        or soup.find("main")
        or soup.find("body")
    )
    extracted = container.get_text(separator="\n", strip=True) if container else ""
    cleaned = "\n".join(ln for ln in extracted.splitlines() if ln.strip())

    if len(cleaned) < 300:
        log.warning(f"Very little text from {url}")
        return

    rec_data = {
        "source": "Vikaspedia / Govt Portal",
        "data_type": cat_name,
        "title": Path(save_name).stem,
        "url": url,
        "fetched_at": utc_now(),
        "content_hash": content_hash(cleaned),
        "char_count": len(cleaned),
        "text": cleaned
    }
    out_file = PROCESSED / cat_name / (Path(save_name).stem + ".json")
    save_json(out_file, rec_data)
    log.info(f"✓ HTML → {out_file} ({len(cleaned)} chars)")

# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------
def main():
    ensure_dirs()
    log.info("Starting final acquisition pipeline...\n")

    # 1. Weather
    fetch_weather_pan_india()

    # 2. Mandi prices via official API
    fetch_agmarknet_sample()

    # 3. PDFs
    pdfs = [
        ("http://www.agritech.tnau.ac.in/pdf/AGRICULTURE.pdf", "tnau_agriculture.pdf", "practices"),
        ("https://nriipm.res.in/NCIPMPDFs/FOLDERS/tomato_1_.pdf", "tomato_ipm.pdf", "pest"),
        ("https://nriipm.res.in/NCIPMPDFs/FOLDERS/Maize_.pdf", "maize_ipm.pdf", "pest"),
    ]
    for target_url, fname, category in pdfs:
        handle_pdf(target_url, fname, category)
        time.sleep(1)

    # 4. HTML pages
    htmls = [
        ("https://vikaspedia.in/agriculture/policies-and-schemes/crops-related/pm-kisan-samman-nidhi", "pm_kisan.json", "schemes"),
        ("https://vikaspedia.in/agriculture/crop-production/package-of-practices/cereals/wheat-cultivation", "wheat_pop.json", "pop"),
        ("https://vikaspedia.in/agriculture/crop-production/package-of-practices/cereals/rice-cultivation", "rice_pop.json", "pop"),
    ]
    for target_url, fname, category in htmls:
        handle_html(target_url, fname, category)
        time.sleep(1)

    log.info("\n" + "="*60)
    log.info("Acquisition finished")
    log.info(f"Processed data → {PROCESSED}")
    log.info("="*60)

if __name__ == "__main__":
    main()