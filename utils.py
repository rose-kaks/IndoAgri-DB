import os
import json
import time
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

BASE_DIR = Path("./data")
RAW_DIR = BASE_DIR / "raw"
PROCESSED_DIR = BASE_DIR / "processed"
CONFIG_FILE = Path("./config.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("agri_rag")

def load_api_key(key_name: str = "AGMARKNET_API_KEY") -> str:
    if os.getenv(key_name):
        return os.getenv(key_name)
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            return cfg.get(key_name, "")
        except Exception as err:
            log.warning(f"Failed to read config.json: {err}")
    return ""

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]

def ensure_dirs():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

def safe_get(url: str, params: Optional[Dict] = None, timeout: int = 30, retries: int = 2) -> Optional[Any]:
    import requests
    for idx in range(retries + 1):
        try:
            res = requests.get(url, headers=HEADERS, params=params, timeout=timeout)
            if res.status_code == 200:
                return res
            log.warning(f"HTTP {res.status_code} → {url}")
        except Exception as err:
            log.warning(f"Attempt {idx+1} failed for {url}: {err}")
        time.sleep(1.5)
    return None

def save_json(path: Path, obj: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")