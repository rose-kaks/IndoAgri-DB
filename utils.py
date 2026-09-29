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
METADATA_DIR = BASE_DIR / "metadata"
FETCH_STATUS_FILE = METADATA_DIR / "fetch_status.json"
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
    METADATA_DIR.mkdir(parents=True, exist_ok=True)

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

    path.write_text(
        json.dumps(obj, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    # Record successful fetch time
    _record_fetch(path)


def _cache_key(path: Path) -> str:
    """Convert a data path into a stable metadata key."""
    try:
        return str(path.resolve().relative_to(BASE_DIR.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _load_fetch_status() -> dict:
    """Load persistent fetch timestamps."""
    if not FETCH_STATUS_FILE.exists():
        return {}

    try:
        return json.loads(
            FETCH_STATUS_FILE.read_text(encoding="utf-8")
        )
    except Exception as err:
        log.warning(f"Failed to read fetch metadata: {err}")
        return {}


def _save_fetch_status(status: dict):
    """Persist fetch timestamps."""
    METADATA_DIR.mkdir(parents=True, exist_ok=True)

    FETCH_STATUS_FILE.write_text(
        json.dumps(status, indent=2),
        encoding="utf-8"
    )


def _record_fetch(path: Path):
    """Record the successful fetch time for a data file."""
    status = _load_fetch_status()

    status[_cache_key(path)] = utc_now()

    _save_fetch_status(status)


def cache_age_days(path: Path) -> float:
    """
    Return the age of the last successful fetch.

    On GitHub Actions this comes from persistent metadata.
    Locally it also uses the same metadata when available.
    """
    if not path.exists():
        return -1.0

    status = _load_fetch_status()
    key = _cache_key(path)

    timestamp = status.get(key)

    if timestamp:
        try:
            fetched_at = datetime.fromisoformat(timestamp)
            age_seconds = (
                datetime.now(timezone.utc) - fetched_at
            ).total_seconds()

            return age_seconds / 86400

        except Exception as err:
            log.warning(
                f"Invalid fetch timestamp for {path}: {err}"
            )

    # If no metadata exists yet, fall back to filesystem age.
    return (time.time() - path.stat().st_mtime) / 86400


def is_cache_fresh(path: Path, max_age_days: float) -> bool:
    """Return True if cached data is within its freshness window."""
    age = cache_age_days(path)

    return age >= 0 and age < max_age_days

  
