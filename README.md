# IndoAgri-KB

A unified, versioned agricultural knowledge base for India. Combines eight public data sources into a single research-ready resource with a shared location key, provenance on every record, and dual structured + semantic access.

---

## Data Sources

Every fetcher writes to `data/processed/<source>/`. The LGD layer runs first because weather and soil depend on its district coordinates.

| # | Fetcher | Source | What It Fetches | Typical Size | Cache |
|---|---|---|---|---|---|
| 1 | `lgd.py` | [VijaySamant4368/India-Locations-Dataset](https://github.com/VijaySamant4368/India-Locations-Dataset) | All 747 Indian districts with lat/lon centroids | ~332 KB JSON | 30 days |
| 2 | `weather.py` | [Open-Meteo](https://open-meteo.com) | 7-day daily forecast per district | 744 locations × 7 days | 1 day |
| 3 | `soil.py` | [India Data Portal (CKAN)](https://ckan.indiadataportal.com) | District-level soil nutrient analysis | 1.1 GB CSV → 738 districts | 30 days |
| 4 | `agmarknet.py` | [data.gov.in Agmarknet API](https://data.gov.in) | Daily mandi prices for all markets | ~10,000 records/run | 1 day |
| 5 | `disasters.py` | [GDACS RSS](https://www.gdacs.org/xml/rss.xml) | Disaster alerts, filtered to India | ~15 alerts/run | 1 day |
| 6 | `news.py` | [PIB RSS](https://pib.gov.in) | Agriculture-related press releases | ~15 items/run | 1 day |
| 7 | `schemes.py` | [myScheme.gov.in](https://www.myscheme.gov.in) | Central + state agricultural schemes | Varies by category | 30 days |
| 8 | `kcc.py` | [data.gov.in KCC API](https://data.gov.in) | Farmer Q&A in 7 Indian languages | 2,000 Q&As/run | 7 days |

### Detailed Notes per Source

**1. LGD (`lgd.py`)**
- Downloads `india_locations_with_coords_small.json` from GitHub.
- Coordinates come from OpenStreetMap via Photon/Nominatim, truncated to 2 decimal places (~1.1 km precision).
- Covers all states, UTs, and 747 districts.
- This is the shared location layer — every other source is joined through it.

**2. Weather (`weather.py`)**
- Open-Meteo counts each coordinate as one API call. Free tier allows 600 calls/minute.
- Batches 20 districts per request with a 3-second delay → ~2.5 minutes for all 747 districts.
- Variables: `temperature_2m_max`, `temperature_2m_min`, `precipitation_sum`, `et0_fao_evapotranspiration`, `relative_humidity_2m_mean`.
- Timezone: Asia/Kolkata.

**3. Soil (`soil.py`)**
- Downloads the full Soil Nutrient Analysis CSV (~1.1 GB) from CKAN.
- Aggregates 10.8 million rows to 738 districts using a chunked pandas read (500k rows/chunk).
- Two-level cache: output JSON (30 days) then raw CSV (30 days).
- Re-aggregates without re-downloading if only the output is stale.
- The old endpoint `ckandev.indiadataportal.com` is dead; the new host is `ckan.indiadataportal.com`.

**4. Agmarknet (`agmarknet.py`)**
- Uses data.gov.in resource `9ef84268-d588-465a-a308-a864a43d0070`.
- Paginates at 1,000 records per request.
- Requires `DATA_GOV_IN_API_KEY` in `.env` or `config.json`.
- Fields: state, district, market, commodity, variety, min/max/modal price, arrival_date.

**5. Disasters (`disasters.py`)**
- GDACS RSS feed filtered by 16 India-region keywords (cyclone, flood, monsoon, Bay of Bengal, etc.).
- Streams with a 5 MB cap and a (10s, 20s) timeout so a slow feed cannot hang the pipeline.
- Keeps the top 15 most recent alerts.

**6. News (`news.py`)**
- Tries PIB RSS feeds first, falls back to homepage scrape if fewer than 5 items.
- Filters by 30 agriculture keywords (kisan, mandi, MSP, crop names, etc.).

**7. Schemes (`schemes.py`)**
- Uses the myScheme v6 API (public key embedded in the frontend).
- Paginates 50 schemes per request.
- Normalises nested JSON (basicDetails, eligibilityCriteria, schemeBenefits, etc.) into flat fields.

**8. KCC (`kcc.py`)**
- Uses data.gov.in resource `cef25fe2-9231-4128-8aec-2c948fedd43f`.
- Language detected from Unicode script (Devanagari, Tamil, Telugu, Gurmukhi, Bengali, Gujarati).
- Splits embedded Q&A from the `KccAns` field when present (Tamil: கேள்வி / பதில்; English: Query / Answer).
- Requires `DATA_GOV_IN_API_KEY`.

---

## Setup

### Prerequisites
- Python 3.10+
- A free API key from [data.gov.in](https://data.gov.in/user/register)

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
  "DATA_GOV_IN_API_KEY": "your_key_here",
  "AGMARKNET_API_KEY": "same_key_here"
}
```
or set an environment variable.

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
python -c "from fetchers.kcc import fetch_kcc; fetch_kcc()"
```

### Test with a small batch
``` bash
python -c "from fetchers.kcc import fetch_kcc; fetch_kcc(total_to_fetch=100)"
```
## Caching
Every fetcher checks the age of its output file before doing any work. If the file is fresher than the source's cache window, the fetcher logs ... is fresh (X.X days old). Skipping fetch. and returns immediately.

Source	(Cache Window)	Rationale
LGD	(30 days)	District boundaries change rarely
Weather	(1 day)	Forecasts refresh daily
Soil	(30 days)	Source updates yearly
Agmarknet	(1 day)	Prices change daily
Disasters	(1 day)	Alerts are time-sensitive
News	(1 day)	News updates frequently
Schemes	(30 days)	Scheme details rarely change
KCC	(7 days)	Bulk corpus, slow-moving

To override a single fetcher without touching the whole pipeline, pass force=True:
``` bash
fetch_weather_pan_india(force=True)
```
        
## Data Handling
What goes into git: processed JSON outputs (small, ~5–20 MB total) and reference files.
What stays out: raw downloads (regenerable in one command). The 1.1 GB soil CSV is gitignored.

Provenance: every output JSON includes a source, fetched_at, and data_type header.

Failure behaviour:

- Weather: batches skip on HTTP 429 with doubled backoff.
- Soil: probes the endpoint once before iterating; aborts after 5 consecutive failures.
- Disasters: streams with a 5 MB cap so a stalled feed cannot hang the pipeline.
- KCC: stops early if the API returns an empty batch.

## Known Limitations
- Weather and soil use district centroids — a single point per district, not an average over the district area. Accurate enough for district-level joins but not for sub-district analysis.
- Soil data is yearly. The CKAN resource updates roughly once a year. data_last_updated: 26-08-2025.
- KCC QueryText is an operator summary, not the farmer's spoken words. Actual questions are extracted from the KccAns field when embedded.
- GDACS filters by keyword, not by precise geography. Alerts near India's borders may be missed or over-included.
- No canonical crop dictionary yet. Commodity names in Agmarknet and KCC are not yet normalised across sources.
- No cross-source linkage table yet. The data is collected and cleaned but not yet joined on (district, week, crop).

## Roadmap
☑ LGD reference layer
☑ Weather (all districts)
☑ Soil (all districts)
☑ Mandi prices
☑ Disaster alerts
☑ PIB news
☑ Government schemes
☑ Kisan Call Centre Q&A
□ Canonical crop dictionary (synonym mapping across sources)
□ Cross-source linkage: district_week_panel joining all sources on (district_code, iso_week)
□ IndoAgri-Bench: 100+ multi-source evaluation queries with ground truth
□ Vector embeddings for unstructured tables (KCC, schemes, news)
□ Zenodo DOI + Hugging Face mirror
