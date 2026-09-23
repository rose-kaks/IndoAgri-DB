# IndoAgri-KB

A unified, versioned agricultural knowledge base for India. Combines
eight public data sources under a shared location key, with per-source
caching, provenance on every record, and dual structured + semantic
access.

Built as the offline RAG backend for farmer advisory systems.

---

## Data Sources

Every fetcher writes to `data/processed/<source>/`. The LGD layer runs
first because weather and soil depend on its district coordinates.

| # | Fetcher | Source | Content | Typical Size | Cache |
|---|---|---|---|---|---|
| 1 | `lgd.py` | [India-Locations-Dataset](https://github.com/VijaySamant4368/India-Locations-Dataset) | 747 districts with lat/lon centroids | ~330 KB | 30d |
| 2 | `weather.py` | [Open-Meteo](https://open-meteo.com) | 7-day forecast per district | 744 × 7 daily | 1d |
| 3 | `soil.py` | [India Data Portal (CKAN)](https://ckan.indiadataportal.com) | District soil nutrient levels | 1.1 GB → 738 districts | 30d |
| 4 | `agmarknet.py` | [data.gov.in Agmarknet](https://data.gov.in) | Daily mandi prices | ~10K records/run | 1d |
| 5 | `disasters.py` | [GDACS RSS](https://www.gdacs.org/xml/rss.xml) | India-only alerts, last 7 days | 5–15 alerts | 1d |
| 6 | `schemes.py` | [myScheme.gov.in](https://www.myscheme.gov.in) | Central + state agri schemes | ~50–500 | 30d |
| 7 | `kcc.py` | [Kaggle KCC dataset](https://www.kaggle.com/datasets/daskoushik/farmers-call-query-data-qa) | Farmer Q&A, ~100K pairs | ~100K docs | 30d |
| 8 | `crop_best_practices.py` | [HF: Fasal Mitra](https://huggingface.co/datasets/phoenix28/fasal-mitra-sft-v1) + [HF: CABI](https://huggingface.co/datasets/CABInternational/Plant-Health-Content) | Multilingual crop disease advisories | 3,032 docs | 90d |

### Detailed Notes

**1. LGD (`lgd.py`)**
- Downloads `india_locations_with_coords_small.json` from GitHub.
- Coordinates from OpenStreetMap (Photon/Nominatim), 2-decimal precision (~1.1 km).
- This is the shared location layer every other source joins on.

**2. Weather (`weather.py`)**
- Open-Meteo batches 20 coordinates per call. 3s delay respects the 600/min limit.
- Variables: temp_max, temp_min, precipitation_sum, ET0, relative humidity.
- 7-day horizon, Asia/Kolkata timezone.

**3. Soil (`soil.py`)**
- Downloads the Soil Nutrient Analysis CSV from CKAN (~1.1 GB).
- Aggregates 10.8M rows to 738 districts using chunked pandas.
- Two-level cache: output JSON then raw CSV.

**4. Agmarknet (`agmarknet.py`)**
- data.gov.in resource `9ef84268-d588-465a-a308-a864a43d0070`.
- Paginates at 1,000 records per call. Requires `DATA_GOV_IN_API_KEY`.

**5. Disasters (`disasters.py`)**
- GDACS RSS filtered to India via the `gdacs:country` tag and a strict
  `\bIndia\b` regex fallback.
- Time-filtered to the last 7 days. Streamed with a 5 MB cap.

**6. Schemes (`schemes.py`)**
- myScheme v6 public API. Paginates 50 per call.
- Normalises nested JSON into flat eligibility / benefits / documents fields.

**7. KCC (`kcc.py`)**
- Loads a Kaggle CSV placed manually at `data/raw/kcc/questionsv4.csv`.
- Static corpus; not live.

**8. Crop advisories (`crop_best_practices.py`)**
- **Fasal Mitra** — 3,000 multilingual advisories via the HF rows API.
  Text field is `advisory` (not `text`). Metadata: crop, disease_class,
  language.
- **CABI Plant Health** — India-only filter applied. 346 raw `.txt` files
  reduce to ~32 India-relevant IPM decision guides.
- Strips CABI `## Pictures ##` sections (image captions useless for
  text-only RAG).
- Auto-detects language from Unicode script.

---

## Setup

### Prerequisites
- Python 3.10+
- A free [data.gov.in API key](https://data.gov.in/user/register)
- A [Hugging Face token](https://huggingface.co/settings/tokens) with read scope

### Install

```bash
git clone https://github.com/rose-kaks/offline-edge-llm.git
cd offline-edge-llm
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Configure

Create a config.json in the project root:
```bash
{
  "DATA_GOV_IN_API_KEY": "your_data_gov_in_key",
  "AGMARKNET_API_KEY": "same_key_ok",
  "HF_TOKEN": "hf_your_hf_token"
}
```
or set an environment variable.

### One-time manual setups
1. KCC dataset - Download the CSV from [Farmers Call Query Dataset](https://www.kaggle.com/datasets/daskoushik/farmers-call-query-data-qa) and place it at:
``` bash
data/raw/kcc/questionsv4.csv
```
2. CABI terms - Accept at
https://huggingface.co/datasets/CABInternational/Plant-Health-Content
(click "Agree and access repository").

## Usage

### Run the full pipeline: 
```bash
python main.py
```
Each fetcher checks its cache first. Fresh data is skipped automatically.

### Force a full refresh:
```bash
python main.py --force
```
Ignores all caches. Re-downloads and re-processes everything. Use before publishing a snapshot.

### Run a single fetcher
```bash
python -c "from fetchers.weather import fetch_weather_pan_india; fetch_weather_pan_india()"
python -c "from fetchers.soil import fetch_soil; fetch_soil()"
python -c "from fetchers.disasters import fetch_disaster_alerts; fetch_disaster_alerts()"
python -c "from fetchers.kcc import fetch_kcc; fetch_kcc()"
python -c "from fetchers.crop_best_practices import fetch_crop_best_practices; fetch_crop_best_practices(force=True)"
```

## Caching
Every fetcher checks the age of its output file before doing any work. If the file is fresher than the source's cache window, the fetcher logs ... is fresh (X.X days old). Skipping fetch. and returns immediately.


| Source | Cache Window | Rationale |
| :--- | :--- | :--- |
| LGD | 30 days | District boundaries change rarely |
| Weather | 1 day | Forecasts refresh daily |
| Soil | 30 days | Source updates yearly |
| Agmarknet | 1 day | Prices change daily |
| Disasters | 1 day | Alerts are time-sensitive |
| Schemes | 30 days | Scheme details rarely change |
| KCC | 30 days | Bulk corpus, slow-moving |
| Crop advisories	| 90 days |	HF datasets, slow-moving |

To override a single fetcher without touching the whole pipeline, pass force=True:
``` bash
fetch_weather_pan_india(force=True)
```
        
## Data Handling
What goes into git: processed JSON outputs (small, ~5–20 MB total) and reference files.
What stays out: raw downloads (regenerable in one command). The GB-heavy soil and kcc CSV, with separate scheme files, are all gitignored.

Provenance: every output JSON includes a source, fetched_at, and data_type header.

Failure behaviour:

- Weather: batches skip on HTTP 429 with doubled backoff.
- Soil: probes the endpoint once before iterating; aborts after 5 consecutive failures.
- Disasters: streams with a 5 MB cap so a stalled feed cannot hang the pipeline.
- KCC: logs a download instruction and skips if the CSV is missing.
- Schemes: paginates 50 at a time with a 0.35s delay between requests.

## Known Limitations
- Weather and soil use district centroids — a single point per district, not an average over the district area. Accurate enough for district-level joins but not for sub-district analysis.
- Soil data is yearly. The CKAN resource updates roughly once a year. data_last_updated: 26-08-2025.
- KCC data is a static Kaggle dump, not a live feed. The source is a snapshot of the Kisan Call Centre corpus; it does not update in real time.
- Disasters filtered by GDACS country tag + description regex. Alerts affecting India's neighbours that don't mention "India" are discarded by design.
- No canonical crop dictionary yet. Commodity names in Agmarknet and KCC are not yet normalised across sources.
- No cross-source linkage table yet. The data is collected and cleaned but not yet joined on (district, week, crop).

## Roadmap
☑ LGD reference layer
☑ Weather (all districts)
☑ Soil (all districts)
☑ Mandi prices
☑ Disaster alerts (India-only)
☑ Government schemes
☑ Kisan Call Centre Q&A
☑ Crop advisories (Fasal Mitra + CABI)
□ Canonical crop dictionary (synonym mapping across sources)
□ Cross-source linkage: district_week_panel joining all sources on (district_code, iso_week)
□ IndoAgri-Bench: 100+ multi-source evaluation queries with ground truth
□ Vector embeddings for unstructured sources
□ Zenodo DOI + Hugging Face mirror
