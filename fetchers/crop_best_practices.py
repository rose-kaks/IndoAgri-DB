"""
crop_best_practices.py — Crop advisories from Hugging Face.

Sources:
  1. phoenix28/fasal-mitra-sft-v1
     Text field is `advisory`. Fields: query, crop, disease_class,
     language, advisory.
  2. CABInternational/Plant-Health-Content
     Raw .txt files under data/pmdg, data/pfff, data/phc. India-only
     filter applied. Metadata flattened. Picture captions stripped.

Output: one flat document per advisory with only RAG-relevant fields.
"""

import json
import re
import time
from pathlib import Path

import requests

from utils import (
    BASE_DIR,
    HEADERS,
    PROCESSED_DIR,
    cache_age_days,
    is_cache_fresh,
    load_api_key,
    log,
    save_json,
    utc_now,
)

OUTPUT_FILE = PROCESSED_DIR / "crop_best_practices" / "advisories.json"
MAX_CACHE_AGE_DAYS = 90

HF_ROWS_API = "https://datasets-server.huggingface.co/rows"
RAW_DIR = BASE_DIR / "raw" / "crop_advisories"
RAW_DIR.mkdir(parents=True, exist_ok=True)

PAGE_SIZE = 100
REQUEST_DELAY = 1.5
READ_TIMEOUT = 90

FASAL_MITRA_MAX_ROWS = 3000
KCC_KRISHI_MAX_ROWS = 5000

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
CROPS = [
    "maize", "rice", "paddy", "wheat", "tomato", "chilli", "chili",
    "onion", "banana", "mango", "cotton", "sugarcane", "groundnut",
    "soybean", "potato", "brinjal", "eggplant", "okra", "bhindi",
    "cabbage", "cauliflower", "citrus", "yam", "coconut", "tea",
    "coffee", "pepper", "cucumber", "gourd", "melon", "mustard",
    "pulses", "lentil", "chickpea", "pigeonpea", "sesame", "castor",
]

# Languages by Unicode block
_LANG_BLOCKS = {
    "hi": ("\u0900", "\u097F"),    # Devanagari
    "ta": ("\u0B80", "\u0BFF"),    # Tamil
    "te": ("\u0C00", "\u0C7F"),    # Telugu
    "pa": ("\u0A00", "\u0A7F"),    # Gurmukhi
    "bn": ("\u0980", "\u09FF"),    # Bengali
    "gu": ("\u0A80", "\u0AFF"),    # Gujarati
    "or": ("\u0B00", "\u0B7F"),    # Odia
    "kn": ("\u0C80", "\u0CFF"),    # Kannada
    "ml": ("\u0D00", "\u0D7F"),    # Malayalam
}


def _detect_language(text: str) -> str:
    """Return dominant script code, or 'en' if no Indian script dominates."""
    if not text:
        return "en"
    counts = {
        code: sum(1 for c in text if lo <= c <= hi)
        for code, (lo, hi) in _LANG_BLOCKS.items()
    }
    top = max(counts, key=counts.get)
    return top if counts[top] > 0 else "en"


def _extract_crop(*texts) -> str:
    """Match a known crop name against one or more text fragments."""
    combined = " ".join(str(t or "") for t in texts).lower()
    for crop in CROPS:
        if crop in combined:
            return crop
    return ""


def _strip_pictures_section(body: str) -> str:
    """Remove the `## Pictures ##` block from CABI markdown."""
    # Matches from "## Pictures" up to the next "##" header
    return re.sub(
        r"##\s*Pictures\s*##.*?(?=^##\s|\Z)",
        "",
        body,
        flags=re.DOTALL | re.MULTILINE,
    ).strip()


# ---------------------------------------------------------------------------
# 1. Fasal Mitra
# ---------------------------------------------------------------------------
def _page_rows(dataset, config, split, max_rows, token=""):
    offset = 0
    fetched = 0
    page_num = 0

    headers = dict(HEADERS)
    if token:
        headers["Authorization"] = f"Bearer {token}"

    while fetched < max_rows:
        page_num += 1
        params = {
            "dataset": dataset,
            "config": config,
            "split": split,
            "offset": offset,
            "length": PAGE_SIZE,
        }

        body = None
        for attempt in range(4):
            try:
                r = requests.get(
                    HF_ROWS_API, params=params, headers=headers,
                    timeout=(15, READ_TIMEOUT),
                )
                if r.status_code == 429:
                    wait = 20 * (attempt + 1)
                    log.warning(f"  429 page {page_num}; waiting {wait}s")
                    time.sleep(wait)
                    continue
                if r.status_code in (500, 502, 503, 504):
                    wait = 5 * (attempt + 1)
                    log.warning(f"  {r.status_code} page {page_num}; retry {attempt+1}/4")
                    time.sleep(wait)
                    continue
                if r.status_code == 401:
                    log.error(f"  401 for {dataset} — accept terms at huggingface.co/datasets/{dataset}")
                    return
                r.raise_for_status()
                body = r.json()
                break
            except requests.Timeout:
                log.warning(f"  Timeout page {page_num}; retry {attempt+1}/4")
                time.sleep(3)
            except requests.RequestException as err:
                log.warning(f"  Request failed page {page_num}: {err}")
                time.sleep(3)

        if body is None:
            return

        rows = body.get("rows", [])
        if not rows:
            return

        for entry in rows:
            yield entry.get("row", {})

        fetched += len(rows)
        offset += len(rows)

        if page_num % 5 == 0:
            log.info(f"    page {page_num} — {fetched}/{max_rows} rows")

        if offset >= body.get("num_rows_total", 0) or fetched >= max_rows:
            return

        time.sleep(REQUEST_DELAY)


def _load_fasal_mitra():
    docs = []
    ds = "phoenix28/fasal-mitra-sft-v1"

    for row in _page_rows(ds, "default", "train", FASAL_MITRA_MAX_ROWS):
        text = row.get("advisory") or ""
        if not isinstance(text, str) or not text.strip():
            continue

        crop = (row.get("crop") or "").strip()
        if not crop:
            # Fallback: infer from the query text
            crop = _extract_crop(row.get("query"), text[:200])

        docs.append({
            "text": text.strip(),
            "query": (row.get("query") or "").strip() if isinstance(row.get("query"), str) else "",
            "crop": crop,
            "disease_class": (row.get("disease_class") or "").strip(),
            "language": (row.get("language") or "").strip() or _detect_language(text),
            "source": "fasal_mitra",
        })

    return docs


# ---------------------------------------------------------------------------
# 2. CABI — India-only, flattened metadata
# ---------------------------------------------------------------------------
def _load_cabi(token):
    docs = []
    ds = "CABInternational/Plant-Health-Content"

    if not token:
        log.warning("  HF_TOKEN missing — skipping CABI.")
        return docs

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        log.error("  huggingface_hub not installed. Run: pip install huggingface_hub")
        return docs

    local_dir = RAW_DIR / "cabi"
    local_dir.mkdir(parents=True, exist_ok=True)

    log.info("  Downloading CABI .txt files (this may take a few minutes)...")
    try:
        snapshot_download(
            repo_id=ds,
            repo_type="dataset",
            local_dir=str(local_dir),
            allow_patterns=["data/*/*.txt"],
            token=token,
        )
    except Exception as err:
        log.error(f"  CABI download failed: {err}")
        return docs

    txt_files = list(local_dir.rglob("*.txt"))
    log.info(f"  Found {len(txt_files)} CABI .txt files")

    skipped_country = 0

    for path in txt_files:
        try:
            raw = path.read_text(encoding="utf-8")
        except Exception:
            continue
        if not raw.strip():
            continue

        # ---- Parse YAML front matter ----
        meta = {}
        body = raw
        if raw.startswith("---"):
            parts = raw.split("---", 2)
            if len(parts) >= 3:
                for line in parts[1].strip().splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        meta[k.strip()] = v.strip()
                body = parts[2].strip()

        # ---- India-only filter ----
        country = meta.get("country", "").strip()
        if country and country not in ("India", "IN"):
            skipped_country += 1
            continue

        # ---- Strip Pictures section (useless for text RAG) ----
        body = _strip_pictures_section(body)
        if not body:
            continue

        # ---- Flatten to only what RAG needs ----
        title = meta.get("title", "").strip()
        crop = _extract_crop(title, body[:300])

        docs.append({
            "text": body,
            "query": "",
            "crop": crop,
            "disease_class": meta.get("subtitle", "").strip(),
            "language": _detect_language(body),
            "title": title,
            "country": country or "India",
            "year": meta.get("year", "").strip("'\"") or "",
            "source": f"cabi_{path.parent.name}",   # cabi_pmdg / cabi_pfff / cabi_phc
        })

    log.info(f"  CABI India docs kept: {len(docs)} (dropped {skipped_country} non-India)")
    return docs


# ---------------------------------------------------------------------------
# 3. KCC-Krishi fallback
# ---------------------------------------------------------------------------
def _load_kcc_krishi():
    docs = []
    ds = "uralstech/kcc-krishi-rag-sft-advisory-corpus"

    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        log.warning("  huggingface_hub not installed; skipping KCC-Krishi.")
        return docs

    local_file = RAW_DIR / "kcc_krishi_train.jsonl"

    if not local_file.exists():
        log.info("  Downloading KCC-Krishi train.jsonl (~698 MB)...")
        try:
            path = hf_hub_download(
                repo_id=ds,
                filename="train.jsonl",
                repo_type="dataset",
                local_dir=str(RAW_DIR / "kcc_krishi"),
                token=load_api_key("HF_TOKEN") or None,
            )
            local_file = Path(path)
        except Exception as err:
            log.warning(f"  KCC-Krishi download failed: {err}")
            return docs

    log.info(f"  Parsing {local_file}...")
    try:
        with open(local_file, encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if i >= KCC_KRISHI_MAX_ROWS:
                    break
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue

                text = (
                    row.get("answer") or row.get("output")
                    or row.get("response") or row.get("advisory")
                    or row.get("text") or ""
                )
                query = (
                    row.get("question") or row.get("instruction")
                    or row.get("input") or row.get("query") or ""
                )
                if not isinstance(text, str) or not text.strip():
                    continue

                crop = (row.get("crop") or "").strip() or _extract_crop(query, text[:200])

                docs.append({
                    "text": text.strip(),
                    "query": query.strip() if isinstance(query, str) else "",
                    "crop": crop,
                    "disease_class": "",
                    "language": _detect_language(text),
                    "source": "kcc_krishi",
                })
    except Exception as err:
        log.warning(f"  KCC-Krishi parse failed: {err}")

    return docs


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def fetch_crop_best_practices(force: bool = False):
    if not force and is_cache_fresh(OUTPUT_FILE, MAX_CACHE_AGE_DAYS):
        age = cache_age_days(OUTPUT_FILE)
        log.info(f"Crop advisories are fresh ({age:.1f} days old). Skipping.")
        return

    log.info("Loading crop advisories from Hugging Face...")

    hf_token = load_api_key("HF_TOKEN")
    log.info(f"  HF token present: {bool(hf_token)}")

    fasal_docs = []
    try:
        fasal_docs = _load_fasal_mitra()
        log.info(f"  Fasal Mitra: {len(fasal_docs)} advisories")
    except Exception as err:
        log.error(f"  Fasal Mitra failed: {err}")

    cabi_docs = []
    try:
        cabi_docs = _load_cabi(hf_token)
    except Exception as err:
        log.error(f"  CABI failed: {err}")

    kcc_docs = []
    if not cabi_docs:
        try:
            kcc_docs = _load_kcc_krishi()
            log.info(f"  KCC-Krishi: {len(kcc_docs)} documents")
        except Exception as err:
            log.error(f"  KCC-Krishi failed: {err}")

    all_docs = fasal_docs + cabi_docs + kcc_docs

    if not all_docs:
        log.error("No advisory documents loaded.")
        return

    # Small stats: crop distribution
    crops = {}
    for d in all_docs:
        c = d.get("crop") or "unknown"
        crops[c] = crops.get(c, 0) + 1

    save_json(OUTPUT_FILE, {
        "source": "Hugging Face — Fasal Mitra + CABI (India) + KCC-Krishi",
        "data_type": "crop_advisories",
        "fetched_at": utc_now(),
        "total_documents": len(all_docs),
        "by_source": {
            "fasal_mitra": len(fasal_docs),
            "cabi": len(cabi_docs),
            "kcc_krishi": len(kcc_docs),
        },
        "crop_distribution": dict(
            sorted(crops.items(), key=lambda x: -x[1])[:30]
        ),
        "documents": all_docs,
    })

    log.info(f"Crop advisories saved → {OUTPUT_FILE} ({len(all_docs)} documents)")


if __name__ == "__main__":
    fetch_crop_best_practices()