"""
schemes.py – Fetch all Agriculture / Rural / Environment schemes from myScheme.gov.in
Always does a full refresh (no reliable way to detect updates on existing schemes).
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from utils import PROCESSED_DIR, RAW_DIR, log, save_json, utc_now

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
API_BASE = "https://api.myscheme.gov.in"
SEARCH_URL = f"{API_BASE}/search/v6/schemes"
DETAIL_URL = f"{API_BASE}/schemes/v6/public/schemes"

API_KEY = "tYTy5eEhlu9rFjyxuCr7ra7ACp4dv1RH8gWuHTDc"

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.myscheme.gov.in",
    "Referer": "https://www.myscheme.gov.in/",
    "User-Agent": "Mozilla/5.0 (compatible; OfflineEdgeRAG/1.0; +farmer-schemes)",
    "x-api-key": API_KEY,
}

CATEGORY_FILTER = [
    {"identifier": "schemeCategory", "value": "Agriculture,Rural & Environment"}
]

PAGE_SIZE = 50
REQUEST_DELAY = 0.35
MAX_RETRIES = 4

RAW_SCHEMES_DIR = RAW_DIR / "schemes"
PROCESSED_FILE = PROCESSED_DIR / "schemes" / "schemes_agriculture.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _create_session() -> requests.Session:
    session = requests.Session()
    retries = Retry(
        total=MAX_RETRIES,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.headers.update(HEADERS)
    return session


def _extract_text(node: Any) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node.strip()
    if isinstance(node, list):
        return "\n".join(filter(None, (_extract_text(n) for n in node)))
    if isinstance(node, dict):
        if "text" in node:
            return node["text"].strip()
        if "children" in node:
            return _extract_text(node["children"])
        return " ".join(_extract_text(v) for v in node.values() if v).strip()
    return str(node).strip()


def _safe_list(value) -> list:
    return value if isinstance(value, list) else []


def _is_active(scheme_close_date: Optional[str]) -> bool:
    if not scheme_close_date:
        return True
    try:
        close = datetime.fromisoformat(scheme_close_date.replace("Z", "+00:00"))
        return close > datetime.now(timezone.utc)
    except Exception:
        return True


def _normalize_scheme(raw: Dict[str, Any], fetched_at: str) -> Dict[str, Any]:
    en = raw.get("en") or {}
    basic = en.get("basicDetails") or {}
    scheme_id = raw.get("_id") or basic.get("schemeShortTitle") or "unknown"

    close_date = basic.get("schemeCloseDate")
    active = _is_active(close_date)

    references = _safe_list(en.get("references") or en.get("officialLinks"))
    official_links = []
    for ref in references:
        if isinstance(ref, dict):
            title = ref.get("title") or ref.get("label") or "Link"
            url = ref.get("url") or ref.get("link") or ""
            if url:
                official_links.append({"title": title, "url": url})
        elif isinstance(ref, str) and ref.startswith("http"):
            official_links.append({"title": "Official", "url": ref})

    level_obj = basic.get("level") or {}
    level = level_obj.get("label") if isinstance(level_obj, dict) else str(level_obj or "")

    return {
        "source": "myscheme.gov.in",
        "data_type": "scheme",
        "fetched_at": fetched_at,
        "scheme_id": scheme_id,
        "slug": basic.get("slug") or "",
        "name": basic.get("schemeName") or "",
        "short_title": basic.get("schemeShortTitle") or "",
        "status": "Active" if active else "Inactive",
        "is_active": active,
        "level": level,
        "categories": [
            c.get("label") if isinstance(c, dict) else str(c)
            for c in _safe_list(basic.get("schemeCategory"))
        ],
        "tags": _safe_list(basic.get("tags")),
        "open_date": basic.get("schemeOpenDate"),
        "close_date": close_date,
        "brief_description": basic.get("briefDescription") or "",
        "detailed_description": _extract_text(
            en.get("detailedDescription") or en.get("description") or ""
        ),
        "eligibility": _extract_text(
            en.get("eligibilityCriteria") or en.get("eligibility") or []
        ),
        "benefits": _extract_text(
            en.get("schemeBenefits") or en.get("benefits") or []
        ),
        "application_process": _extract_text(
            en.get("applicationProcess")
            or en.get("howToApply")
            or en.get("applicationProcedure")
            or []
        ),
        "documents_required": _extract_text(
            en.get("documentsRequired") or en.get("documents") or []
        ),
        "official_links": official_links,
        "beneficiary_states": _safe_list(basic.get("beneficiaryState")),
        "target_beneficiaries": [
            t.get("label") if isinstance(t, dict) else str(t)
            for t in _safe_list(basic.get("targetBeneficiaries"))
        ],
        "raw_id": raw.get("_id"),
        "source_url": f"https://www.myscheme.gov.in/schemes/{basic.get('slug', '')}",
    }


def _fetch_all_slugs(session: requests.Session) -> List[Dict[str, Any]]:
    all_items = []
    from_offset = 0

    while True:
        params = {
            "lang": "en",
            "q": json.dumps(CATEGORY_FILTER),
            "keyword": "",
            "sort": "",
            "from": from_offset,
            "size": PAGE_SIZE,
        }
        log.info(f"Fetching scheme list offset={from_offset} ...")
        resp = session.get(SEARCH_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "Success":
            raise RuntimeError(f"Search API error: {data}")

        hits = data["data"]["hits"]
        items = hits.get("items", [])
        total = data["data"]["summary"].get("total", 0)

        if not items:
            break

        all_items.extend(items)
        log.info(f"  got {len(items)} (running total {len(all_items)} / {total})")

        from_offset += len(items)
        if from_offset >= total:
            break
        time.sleep(0.25)

    log.info(f"Total schemes discovered: {len(all_items)}")
    return all_items


def _fetch_detail(session: requests.Session, slug: str) -> Optional[Dict]:
    try:
        resp = session.get(DETAIL_URL, params={"slug": slug, "lang": "en"}, timeout=25)
        if resp.status_code == 404:
            log.warning(f"Scheme not found: {slug}")
            return None
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "Success":
            log.warning(f"Detail API non-success for {slug}: {data.get('errorDescription')}")
            return None
        return data.get("data")
    except Exception as e:
        log.error(f"Failed to fetch detail for {slug}: {e}")
        return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def fetch_farmer_schemes(limit: Optional[int] = None) -> None:
    """
    Full refresh of all Agriculture / Rural / Environment schemes.
    """
    log.info("Fetching farmer schemes from myScheme.gov.in (full refresh) ...")

    RAW_SCHEMES_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_FILE.parent.mkdir(parents=True, exist_ok=True)

    fetched_at = utc_now()
    session = _create_session()

    basic_list = _fetch_all_slugs(session)
    if limit:
        basic_list = basic_list[:limit]
        log.info(f"Limiting to first {limit} schemes")

    schemes = []
    for i, item in enumerate(basic_list, 1):
        fields = item.get("fields", {})
        slug = fields.get("slug")
        name = fields.get("schemeName", "unknown")
        if not slug:
            log.warning(f"Skipping item without slug: {name}")
            continue

        log.info(f"[{i}/{len(basic_list)}] {name} ({slug})")
        detail = _fetch_detail(session, slug)
        if detail:
            if "en" in detail and "basicDetails" in detail["en"]:
                bd = detail["en"]["basicDetails"]
                if not bd.get("slug"):
                    bd["slug"] = slug
                if not bd.get("briefDescription"):
                    bd["briefDescription"] = fields.get("briefDescription", "")

            record = _normalize_scheme(detail, fetched_at)
            schemes.append(record)

            # Keep raw copy for debugging / re-processing
            raw_path = RAW_SCHEMES_DIR / f"{slug}.json"
            with open(raw_path, "w", encoding="utf-8") as f:
                json.dump(detail, f, ensure_ascii=False, indent=2)

        time.sleep(REQUEST_DELAY)

    if not schemes:
        log.warning("No schemes were successfully fetched.")
        return

    payload = {
        "source": "myscheme.gov.in",
        "data_type": "schemes",
        "category": "Agriculture,Rural & Environment",
        "fetched_at": fetched_at,
        "total_schemes": len(schemes),
        "active_count": sum(1 for s in schemes if s["is_active"]),
        "inactive_count": sum(1 for s in schemes if not s["is_active"]),
        "schemes": schemes,
    }

    save_json(PROCESSED_FILE, payload)
    log.info(
        f"Schemes saved → {PROCESSED_FILE} "
        f"({payload['total_schemes']} total, "
        f"{payload['active_count']} active, "
        f"{payload['inactive_count']} inactive)"
    )


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    fetch_farmer_schemes(limit=args.limit)