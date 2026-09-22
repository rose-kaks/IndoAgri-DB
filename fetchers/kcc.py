"""
kcc.py — Kisan Call Centre (KCC) Q&A fetcher.

Downloads farmer queries and expert answers from data.gov.in and
formats them for semantic search.

Key observations (from real data):
  1. `QueryText` is an English summary tag written by the call operator,
     NOT the farmer's spoken words. Treated as a topic label.
  2. `KccAns` may embed both the question and answer in a single string
     (Tamil: "கேள்வி : ... பதில் : ..."; English: "Query : ... Answer : ...").
     These are split before storage.
  3. Language is detected from the answer text's Unicode script and
     stored as metadata.
"""

import re
import time

from utils import PROCESSED_DIR, load_api_key, is_cache_fresh, cache_age_days, log, safe_get, save_json, utc_now
from pathlib import Path

OUTPUT_FILE = PROCESSED_DIR / "kcc" / "kcc_qa.json"
MAX_CACHE_AGE_DAYS = 7

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_URL = (
    "https://api.data.gov.in/resource/"
    "cef25fe2-9231-4128-8aec-2c948fedd43f"
)
BATCH_SIZE = 500
DEFAULT_TOTAL = 2000


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------
def detect_language(text: str) -> str:
    """Detect dominant Indian script using Unicode block ranges."""
    if not text:
        return "hi"

    scores = {
        "hi": sum(1 for c in text if "\u0900" <= c <= "\u097F"),
        "ta": sum(1 for c in text if "\u0B80" <= c <= "\u0BFF"),
        "te": sum(1 for c in text if "\u0C00" <= c <= "\u0C7F"),
        "pa": sum(1 for c in text if "\u0A00" <= c <= "\u0A7F"),
        "bn": sum(1 for c in text if "\u0980" <= c <= "\u09FF"),
        "gu": sum(1 for c in text if "\u0A80" <= c <= "\u0AFF"),
    }
    dominant = max(scores, key=scores.get)
    return "en" if scores[dominant] == 0 else dominant


# ---------------------------------------------------------------------------
# Split embedded Q&A from KccAns
# ---------------------------------------------------------------------------
def split_embedded_qa(answer_text: str):
    """Returns (embedded_question_or_None, clean_answer)."""
    tamil = re.search(
        r"கேள்வி\s*[:\-]\s*(.+?)\s*பதில்\s*[:\-]\s*(.+)",
        answer_text,
        re.DOTALL | re.IGNORECASE,
    )
    if tamil:
        return tamil.group(1).strip(), tamil.group(2).strip()

    english = re.search(
        r"[Qq]uery\s*[:\-]\s*(.+?)\s*[Aa]nswer\s*[:\-]\s*(.+)",
        answer_text,
        re.DOTALL,
    )
    if english:
        return english.group(1).strip(), english.group(2).strip()

    return None, answer_text.strip()


# ---------------------------------------------------------------------------
# API fetch
# ---------------------------------------------------------------------------
def _fetch_batch(api_key: str, limit: int, offset: int):
    url = f"{BASE_URL}?api-key={api_key}&format=json&limit={limit}&offset={offset}"
    res = safe_get(url, timeout=45)
    if not res:
        return []
    try:
        return res.json().get("records", [])
    except Exception as err:
        log.error(f"Failed to parse batch at offset {offset}: {err}")
        return []


# ---------------------------------------------------------------------------
# Format one record
# ---------------------------------------------------------------------------
def _format_record(rec: dict):
    state = str(rec.get("StateName", "Unknown")).strip()
    district = str(rec.get("DistrictName", "Unknown")).strip()
    block = str(rec.get("BlockName", "")).strip()
    sector = str(rec.get("Sector", "")).strip()
    category = str(rec.get("Category", "")).strip()
    crop = str(rec.get("Crop", "")).strip()
    query_type = str(rec.get("QueryType", "")).strip()
    op_summary = str(rec.get("QueryText", "")).strip()
    raw_answer = str(rec.get("KccAns", "")).strip()

    if not raw_answer:
        return None

    embedded_q, clean_answer = split_embedded_qa(raw_answer)
    lang = detect_language(clean_answer)

    question = embedded_q if embedded_q else op_summary
    if not question or not clean_answer:
        return None

    return {
        "state": state,
        "district": district,
        "block": block,
        "sector": sector,
        "category": category,
        "crop": crop,
        "query_type": query_type,
        "operator_summary": op_summary,
        "question": question,
        "answer": clean_answer,
        "answer_language": lang,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def fetch_kcc(total_to_fetch: int = DEFAULT_TOTAL, batch_size: int = BATCH_SIZE, force: bool = False):
    if not force and is_cache_fresh(OUTPUT_FILE, MAX_CACHE_AGE_DAYS):
        age = cache_age_days(OUTPUT_FILE)
        log.info(
            f"KCC data is fresh ({age:.1f} days old). "
            f"Skipping fetch. Use force=True to override."
        )
        return
    """
    Download and clean KCC Q&A records.

    Output: data/processed/kcc/kcc_qa.json
    """
    log.info("Fetching Kisan Call Centre (KCC) data...")

    api_key = load_api_key("DATA_GOV_IN_API_KEY")
    if not api_key:
        log.error(
            "API key missing. Set DATA_GOV_IN_API_KEY in environment "
            "or config.json."
        )
        return

    all_records = []
    for offset in range(0, total_to_fetch, batch_size):
        log.info(f"Fetching KCC records {offset} to {offset + batch_size}...")
        batch = _fetch_batch(api_key, batch_size, offset)
        if not batch:
            log.info("No more KCC records. Stopping early.")
            break
        all_records.extend(batch)
        time.sleep(1)

    log.info(f"Fetched {len(all_records)} raw KCC records.")

    cleaned = []
    skipped = 0
    lang_counts: dict[str, int] = {}

    for rec in all_records:
        result = _format_record(rec)
        if result is None:
            skipped += 1
            continue
        cleaned.append(result)
        lang = result["answer_language"]
        lang_counts[lang] = lang_counts.get(lang, 0) + 1

    log.info(
        f"Cleaned: {len(cleaned)} Q&As | Skipped: {skipped} | "
        f"Languages: {lang_counts}"
    )

    out_file = PROCESSED_DIR / "kcc" / "kcc_qa.json"
    save_json(out_file, {
        "source": "data.gov.in (Kisan Call Centre)",
        "data_type": "kcc_qa",
        "fetched_at": utc_now(),
        "total_qa": len(cleaned),
        "language_distribution": lang_counts,
        "kcc_transcripts": cleaned,
    })

    log.info(f"KCC data saved → {out_file}")


if __name__ == "__main__":
    fetch_kcc()