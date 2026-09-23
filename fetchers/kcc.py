"""
kcc.py — Kisan Call Centre Q&A loader.

Loads the Kaggle KCC dataset (questionsv4.csv) from a local cache.
Download it once from:
    https://www.kaggle.com/datasets/daskoushik/farmers-call-query-data-qa
and place it at: data/raw/kcc/questionsv4.csv

The CSV has two columns: questions, answers.
"""

from pathlib import Path

import pandas as pd

from utils import (
    BASE_DIR,
    PROCESSED_DIR,
    cache_age_days,
    is_cache_fresh,
    log,
    save_json,
    utc_now,
)

RAW_CSV = BASE_DIR / "raw" / "kcc" / "questionsv4.csv"
OUTPUT_FILE = PROCESSED_DIR / "kcc" / "kcc_qa.json"

# KCC updates rarely; cache for 30 days.
MAX_CACHE_AGE_DAYS = 30


def fetch_kcc(force: bool = False):
    """
    Load KCC Q&A from the local Kaggle CSV and save a cleaned JSON.

    If the CSV is missing, logs a clear download instruction.
    """
    if not force and is_cache_fresh(OUTPUT_FILE, MAX_CACHE_AGE_DAYS):
        age = cache_age_days(OUTPUT_FILE)
        log.info(
            f"KCC data is fresh ({age:.1f} days old). "
            f"Skipping fetch. Use force=True to override."
        )
        return

    if not RAW_CSV.exists():
        log.error(
            f"KCC CSV not found at {RAW_CSV}.\n"
            f"Download it once from:\n"
            f"  https://www.kaggle.com/datasets/daskoushik/"
            f"farmers-call-query-data-qa\n"
            f"and place questionsv4.csv at {RAW_CSV}"
        )
        return

    log.info(f"Loading KCC data from {RAW_CSV}...")

    try:
        df = pd.read_csv(RAW_CSV)
    except Exception as err:
        log.error(f"Failed to read KCC CSV: {err}")
        return

    # Normalise column names (case-insensitive)
    df.columns = [c.strip().lower() for c in df.columns]

    if "questions" not in df.columns or "answers" not in df.columns:
        log.error(
            f"CSV must have 'questions' and 'answers' columns. "
            f"Found: {list(df.columns)}"
        )
        return

    # Drop rows with missing Q or A
    df = df.dropna(subset=["questions", "answers"])
    df["questions"] = df["questions"].astype(str).str.strip()
    df["answers"] = df["answers"].astype(str).str.strip()
    df = df[(df["questions"] != "") & (df["answers"] != "")]

    records = df.to_dict(orient="records")
    log.info(f"Loaded {len(records)} KCC Q&A pairs.")

    save_json(OUTPUT_FILE, {
        "source": "Kaggle — Farmers Call Query (KCC) Data",
        "data_type": "kcc_qa",
        "fetched_at": utc_now(),
        "total_qa": len(records),
        "kcc_transcripts": records,
    })

    log.info(f"KCC data saved → {OUTPUT_FILE}")


if __name__ == "__main__":
    fetch_kcc()