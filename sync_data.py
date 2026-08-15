"""
Robust Stage-1 Acquisition Script
- Manifest driven
- Clean category folders under ./data/
- Consistent metadata + text/JSON output ready for scoring stage
"""

import os
import json
import time
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

# Prefer modern import
try:
    import pymupdf as fitz
except ImportError:
    import fitz  # fallback

# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------
BASE_DATA_DIR = Path("./data")
MANIFEST_FILE = BASE_DATA_DIR / "sources.txt"
RAW_DIR = BASE_DATA_DIR / "raw"          # all original downloads
PROCESSED_DIR = BASE_DATA_DIR / "processed"  # clean text / json ready for next stage

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AgriRAG-Bot/1.0; +offline-edge-llm)"
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("sync")

# ------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------
def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]

def ensure_dirs(*paths: Path):
    for p in paths:
        p.mkdir(parents=True, exist_ok=True)

def safe_get(url: str, timeout: int = 25, retries: int = 2) -> Optional[requests.Response]:
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            if r.status_code == 200:
                return r
            log.warning(f"HTTP {r.status_code} for {url}")
        except Exception as e:
            log.warning(f"Attempt {attempt+1} failed: {e}")
        time.sleep(1.5 * (attempt + 1))
    return None

def write_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")

# ------------------------------------------------------------
# HANDLERS
# ------------------------------------------------------------
def handle_open_meteo(url: str, save_name: str, category: str):
    r = safe_get(url)
    if not r:
        return
    raw_path = RAW_DIR / category / save_name
    write_text(raw_path, r.text)

    # also keep a processed version with metadata
    try:
        data = r.json()
        record = {
            "source": "Open-Meteo",
            "data_type": "weather_forecast",
            "fetched_at": utc_now(),
            "url": url,
            "content": data
        }
        proc_path = PROCESSED_DIR / category / save_name
        write_json(proc_path, record)
        log.info(f"[✓] Weather → {proc_path}")
    except Exception as e:
        log.error(f"Weather parse error: {e}")


def handle_vikaspedia_html(url: str, save_name: str, category: str):
    r = safe_get(url)
    if not r:
        return

    soup = BeautifulSoup(r.text, "lxml")
    # try several common content containers
    content = (
        soup.find("div", {"id": "TextContent"})
        or soup.find("div", class_="content")
        or soup.find("article")
        or soup.find("body")
    )
    text = content.get_text(separator="\n", strip=True) if content else ""

    if len(text) < 200:
        log.warning(f"Very little text extracted from {url}")
        return

    # raw
    raw_path = RAW_DIR / category / save_name
    write_text(raw_path, text)

    # processed with metadata
    record = {
        "source": "Vikaspedia",
        "data_type": category,
        "title": save_name.replace(".txt", ""),
        "url": url,
        "fetched_at": utc_now(),
        "content_hash": content_hash(text),
        "text": text
    }
    proc_path = PROCESSED_DIR / category / (save_name.replace(".txt", ".json"))
    write_json(proc_path, record)
    log.info(f"[✓] HTML scrape → {proc_path} ({len(text)} chars)")


def handle_pdf_download(url: str, save_name: str, category: str):
    r = safe_get(url, timeout=40)
    if not r:
        return

    raw_pdf = RAW_DIR / category / save_name
    raw_pdf.parent.mkdir(parents=True, exist_ok=True)
    raw_pdf.write_bytes(r.content)

    # Extract text
    try:
        doc = fitz.open(stream=r.content, filetype="pdf")
        pages = [page.get_text() for page in doc]
        text = "\n\n".join(p for p in pages if p.strip())
        doc.close()
    except Exception as e:
        log.error(f"PDF extraction failed: {e}")
        return

    if len(text) < 300:
        log.warning(f"Low text yield from PDF {save_name}")
        return

    # processed
    record = {
        "source": "ICAR/TNAU/NCIPM",
        "data_type": category,
        "title": save_name.replace(".pdf", ""),
        "url": url,
        "fetched_at": utc_now(),
        "content_hash": content_hash(text),
        "text": text[:120000]  # safety limit
    }
    proc_path = PROCESSED_DIR / category / (save_name.replace(".pdf", ".json"))
    write_json(proc_path, record)
    log.info(f"[✓] PDF → {proc_path} ({len(text)} chars)")


# ------------------------------------------------------------
# DISPATCH
# ------------------------------------------------------------
HANDLERS = {
    "open_meteo": handle_open_meteo,
    "vikaspedia_html": handle_vikaspedia_html,
    "pdf_download": handle_pdf_download,
}

def sync_pipeline():
    if not MANIFEST_FILE.exists():
        log.error(f"Manifest not found: {MANIFEST_FILE}")
        return

    ensure_dirs(RAW_DIR, PROCESSED_DIR)
    log.info(f"Starting sync from {MANIFEST_FILE}\n")

    with open(MANIFEST_FILE, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            parts = [p.strip() for p in line.split("|")]
            if len(parts) != 5:
                log.warning(f"Line {lineno}: expected 5 fields, got {len(parts)}")
                continue

            src_type, category, handler_name, save_name, target = parts

            if handler_name not in HANDLERS:
                log.warning(f"Unknown handler '{handler_name}' on line {lineno}")
                continue

            try:
                HANDLERS[handler_name](target, save_name, category)
            except Exception as e:
                log.error(f"Line {lineno} ({save_name}): {e}")

    log.info("\nSync finished.")
    log.info(f"Raw files      → {RAW_DIR}")
    log.info(f"Processed JSON → {PROCESSED_DIR}")


if __name__ == "__main__":
    sync_pipeline()