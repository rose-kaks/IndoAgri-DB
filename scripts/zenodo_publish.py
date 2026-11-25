import os
import sys
import json
import zipfile
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

ZENODO_API = "https://zenodo.org/api"

# Stable all-versions DOI (always resolves to the latest version)
ZENODO_DOI = "10.5281/zenodo.23043350"

# Concept record ID = the number at the end of the all-versions DOI.
# (23294725 was a *version* record ID, not the concept ID.)
ZENODO_CONCEPT_ID = "23043350"

ZENODO_TOKEN = os.environ.get("ZENODO_TOKEN")

if not ZENODO_TOKEN:
    print("[ERROR] ZENODO_TOKEN is not set.")
    sys.exit(1)

# No Content-Type here: used for empty-body POST/GET/DELETE calls.
AUTH_HEADERS = {
    "Authorization": f"Bearer {ZENODO_TOKEN}",
    "User-Agent": "IndoAgri-DB/1.0",
}

# Only for requests that actually send a JSON body.
JSON_HEADERS = {
    **AUTH_HEADERS,
    "Content-Type": "application/json",
}

ROOT_DIR = Path(__file__).resolve().parent.parent

DATA_DIRS = [
    ROOT_DIR / "data" / "processed",
    ROOT_DIR / "data" / "reference",
    ROOT_DIR / "data" / "metadata",
]

DATASET_TITLE = "IndoAgri-DB"


# ============================================================
# HELPERS
# ============================================================

def print_error(response, operation):
    print(f"[ERROR] {operation} failed")
    print(f"[ERROR] HTTP {response.status_code}")
    try:
        print(json.dumps(response.json(), indent=2))
    except Exception:
        print(response.text[:5000])


def check_response(response, operation):
    if response.ok:
        return
    print_error(response, operation)
    sys.exit(1)


def version_tuple(version):
    try:
        return tuple(int(x) for x in str(version).split(".")[:3])
    except Exception:
        return (0, 0, 0)


# ============================================================
# CREATE DATASET ZIP
# ============================================================

def create_dataset_zip():
    print("\n" + "=" * 60)
    print("CREATING DATASET ZIP")
    print("=" * 60)

    temp_dir = Path(tempfile.mkdtemp(prefix="indoagri_zenodo_"))
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    zip_path = temp_dir / f"indoagri-db-{timestamp}.zip"

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for data_dir in DATA_DIRS:
            if not data_dir.exists():
                print(f"[WARNING] Missing directory: {data_dir}")
                continue

            print(f"[INFO] Including: {data_dir}")

            for file_path in data_dir.rglob("*"):
                if not file_path.is_file():
                    continue
                zf.write(file_path, file_path.relative_to(ROOT_DIR))

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"[OK] Created ZIP: {zip_path}")
    print(f"[INFO] ZIP size: {size_mb:.2f} MB")

    return zip_path, temp_dir


# ============================================================
# FIND LATEST PUBLISHED VERSION
# ============================================================

def find_latest_version():
    print("\n" + "=" * 60)
    print("FINDING EXISTING ZENODO DATASET")
    print("=" * 60)

    print(f"[INFO] All-versions DOI: {ZENODO_DOI}")
    print(f"[INFO] Zenodo concept record ID: {ZENODO_CONCEPT_ID}")

    response = requests.get(
        f"{ZENODO_API}/records",
        headers=AUTH_HEADERS,
        params={
            "q": f"conceptrecid:{ZENODO_CONCEPT_ID}",
            "all_versions": "true",
            "size": 100,
            "sort": "-mostrecent",
        },
        timeout=60,
    )
    check_response(response, "Searching Zenodo records")

    hits = response.json().get("hits", {}).get("hits", [])

    if hits:
        print(f"[OK] Found {len(hits)} published version(s)")
        print("\n[INFO] Published versions:")
        for record in hits:
            md = record.get("metadata", {})
            print(
                f"  record={record.get('id')} "
                f"| version={md.get('version')} "
                f"| created={record.get('created')}"
            )

        latest = max(
            hits,
            key=lambda r: (
                version_tuple(r.get("metadata", {}).get("version", "0.0.0")),
                r.get("created", ""),
            ),
        )

        md = latest.get("metadata", {})
        print("\n[OK] Latest Zenodo version found")
        print(f"[INFO] Version    : {md.get('version')}")
        print(f"[INFO] Record ID  : {latest.get('id')}")
        print(f"[INFO] Concept ID : {latest.get('conceptrecid')}")
        print(f"[INFO] DOI        : {latest.get('doi')}")
        return latest

    # Fallback: resolve the all-versions DOI (redirects to latest version)
    print("[WARNING] No versions found using conceptrecid search.")
    print("[INFO] Trying DOI lookup...")

    doi_response = requests.get(
        f"https://doi.org/{ZENODO_DOI}",
        allow_redirects=True,
        timeout=30,
    )
    final_url = doi_response.url
    print(f"[INFO] DOI resolved to: {final_url}")

    if "/records/" not in final_url:
        print("[ERROR] DOI did not resolve to a Zenodo record.")
        return None

    record_id = (
        final_url.split("/records/")[1]
        .split("?")[0]
        .split("#")[0]
        .strip("/")
    )
    print(f"[INFO] DOI record ID: {record_id}")

    record_response = requests.get(
        f"{ZENODO_API}/records/{record_id}",
        headers=AUTH_HEADERS,
        timeout=30,
    )
    check_response(record_response, "Fetching DOI record")

    record = record_response.json()
    print("[OK] Found dataset through DOI.")
    print(f"[INFO] Actual version record ID: {record.get('id')}")
    print(f"[INFO] Concept record ID: {record.get('conceptrecid')}")
    print(f"[INFO] Current dataset version: {record.get('metadata', {}).get('version')}")
    return record


# ============================================================
# CALCULATE NEXT VERSION
# ============================================================

def calculate_next_version(latest):
    current = latest.get("metadata", {}).get("version", "0.0.0")
    print(f"[INFO] Current dataset version: {current}")

    try:
        major, minor, patch = (int(x) for x in current.split(".")[:3])
        new_version = f"{major}.{minor}.{patch + 1}"
    except Exception:
        print("[WARNING] Invalid version format.")
        new_version = "1.0.0"

    print(f"[INFO] New dataset version: {new_version}")
    return new_version


# ============================================================
# FIND / REUSE EXISTING DRAFT
# ============================================================

def find_existing_draft():
    """Zenodo allows only one unpublished draft per record family."""
    r = requests.get(
        f"{ZENODO_API}/deposit/depositions",
        headers=AUTH_HEADERS,
        params={"status": "draft", "size": 100},
        timeout=60,
    )
    if not r.ok:
        print_error(r, "Listing draft depositions")
        return None

    for dep in r.json():
        if str(dep.get("conceptrecid")) == ZENODO_CONCEPT_ID:
            return dep
    return None


def fetch_deposition(deposition_id):
    r = requests.get(
        f"{ZENODO_API}/deposit/depositions/{deposition_id}",
        headers=AUTH_HEADERS,
        timeout=60,
    )
    check_response(r, f"Fetching deposition {deposition_id}")
    return r.json()


# ============================================================
# CREATE NEW ZENODO VERSION
# ============================================================

def create_new_version(latest):
    print("\n" + "=" * 60)
    print("CREATING NEW ZENODO VERSION")
    print("=" * 60)

    # 1. Reuse a leftover draft if one exists
    existing = find_existing_draft()
    if existing:
        print(f"[INFO] Found existing unpublished draft: {existing['id']}")
        print("[INFO] Reusing it instead of calling newversion.")
        return fetch_deposition(existing["id"])

    # 2. Otherwise create a new version (empty POST, no JSON content type)
    latest_record_id = latest.get("id")
    if not latest_record_id:
        print("[ERROR] Latest record has no ID.")
        sys.exit(1)

    print(f"[INFO] Using latest version record: {latest_record_id}")

    response = requests.post(
        f"{ZENODO_API}/deposit/depositions/{latest_record_id}/actions/newversion",
        headers=AUTH_HEADERS,
        timeout=60,
    )

    if not response.ok:
        print_error(response, "Creating Zenodo new version")

        # newversion may have partially succeeded and left a draft behind
        draft = find_existing_draft()
        if draft:
            print(f"[INFO] A draft exists after the failure: {draft['id']}. Using it.")
            return fetch_deposition(draft["id"])

        print("[ERROR] No draft available. Check https://zenodo.org/uploads")
        print("[ERROR] If the problem persists, contact Zenodo support.")
        sys.exit(1)

    result = response.json()
    draft_url = result.get("links", {}).get("latest_draft")

    if not draft_url:
        print("[ERROR] Zenodo did not return links.latest_draft.")
        print(json.dumps(result, indent=2))
        sys.exit(1)

    print(f"[OK] New draft URL: {draft_url}")

    draft_response = requests.get(draft_url, headers=AUTH_HEADERS, timeout=60)
    check_response(draft_response, "Fetching new Zenodo draft")

    draft = draft_response.json()
    if not draft.get("id"):
        print("[ERROR] Could not determine draft deposition ID.")
        sys.exit(1)

    print(f"[OK] New draft deposition ID: {draft['id']}")
    return draft


# ============================================================
# REMOVE EXISTING FILES
# ============================================================

def remove_existing_files(draft):
    deposition_id = draft["id"]

    # Re-fetch so we see the draft's current file list
    files = fetch_deposition(deposition_id).get("files", [])

    if not files:
        print("[INFO] Draft has no existing files.")
        return

    print(f"[INFO] Draft contains {len(files)} existing file(s).")

    for file_info in files:
        file_id = file_info.get("id")
        filename = file_info.get("filename")

        if not file_id:
            continue

        print(f"[INFO] Removing: {filename}")

        response = requests.delete(
            f"{ZENODO_API}/deposit/depositions/{deposition_id}/files/{file_id}",
            headers=AUTH_HEADERS,
            timeout=60,
        )
        check_response(response, f"Deleting {filename}")

    print("[OK] Existing files removed.")


# ============================================================
# UPLOAD ZIP
# ============================================================

def upload_zip(draft, zip_path):
    print("\n" + "=" * 60)
    print("UPLOADING DATASET ZIP")
    print("=" * 60)

    bucket_url = draft.get("links", {}).get("bucket")

    if not bucket_url:
        print("[ERROR] Zenodo did not provide a bucket URL.")
        sys.exit(1)

    filename = zip_path.name
    size_mb = zip_path.stat().st_size / (1024 * 1024)

    print(f"[INFO] Uploading: {filename}")
    print(f"[INFO] Size: {size_mb:.2f} MB")

    upload_headers = {
        **AUTH_HEADERS,
        "Content-Type": "application/octet-stream",
    }

    with open(zip_path, "rb") as f:
        response = requests.put(
            f"{bucket_url}/{filename}",
            headers=upload_headers,
            data=f,
            timeout=600,
        )

    check_response(response, "Uploading dataset ZIP")
    print("[OK] Dataset ZIP uploaded.")


# ============================================================
# UPDATE METADATA
# ============================================================

def update_metadata(draft, new_version):
    print("\n" + "=" * 60)
    print("UPDATING ZENODO METADATA")
    print("=" * 60)

    deposition_id = draft["id"]
    metadata = dict(draft.get("metadata", {}))

    # Fields that should not be sent back
    metadata.pop("prereserve_doi", None)

    metadata["title"] = DATASET_TITLE
    metadata["upload_type"] = "dataset"
    metadata["version"] = new_version
    metadata["publication_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if not metadata.get("description"):
        metadata["description"] = (
            "IndoAgri-DB agricultural knowledge dataset for the "
            "IndoAgri/Kisan Bot offline RAG system."
        )

    response = requests.put(
        f"{ZENODO_API}/deposit/depositions/{deposition_id}",
        headers=JSON_HEADERS,
        json={"metadata": metadata},
        timeout=60,
    )
    check_response(response, "Updating Zenodo metadata")

    print("[OK] Metadata updated.")
    print(f"[INFO] Version: {new_version}")


# ============================================================
# PUBLISH
# ============================================================

def publish(draft):
    print("\n" + "=" * 60)
    print("PUBLISHING ZENODO VERSION")
    print("=" * 60)

    deposition_id = draft["id"]

    response = requests.post(
        f"{ZENODO_API}/deposit/depositions/{deposition_id}/actions/publish",
        headers=AUTH_HEADERS,
        timeout=60,
    )
    check_response(response, "Publishing Zenodo version")

    published = response.json()
    record_id = published.get("record_id") or published.get("id")
    record_url = published.get("links", {}).get("record_html")
    doi = published.get("doi")

    print("\n" + "=" * 60)
    print("ZENODO PUBLISH SUCCESS")
    print("=" * 60)

    print(f"[OK] Record ID: {record_id}")
    if doi:
        print(f"[OK] Version DOI: {doi}")
    if record_url:
        print(f"[OK] Version URL: {record_url}")
    print(f"[OK] All-versions DOI: https://doi.org/{ZENODO_DOI}")

    return published


# ============================================================
# MAIN
# ============================================================

def main():
    print("\n" + "=" * 60)
    print("INDOAGRI → ZENODO DATASET PUBLISHER")
    print("=" * 60)

    print(f"[INFO] All-versions DOI: {ZENODO_DOI}")
    print(f"[INFO] Zenodo concept record ID: {ZENODO_CONCEPT_ID}")

    temp_dir = None

    try:
        # 1. Create ZIP
        zip_path, temp_dir = create_dataset_zip()

        # 2. Find latest published version
        latest = find_latest_version()

        if latest is None:
            print("\n[ERROR] Could not find existing IndoAgri Zenodo dataset.")
            print(f"[ERROR] Expected family: {ZENODO_CONCEPT_ID}")
            print("[ERROR] Refusing to create an unrelated Zenodo record.")
            sys.exit(1)

        # Safety check: make sure we are in the right record family
        found_concept = str(latest.get("conceptrecid", ZENODO_CONCEPT_ID))
        if found_concept != ZENODO_CONCEPT_ID:
            print(
                f"[ERROR] Record belongs to concept {found_concept}, "
                f"expected {ZENODO_CONCEPT_ID}. Aborting."
            )
            sys.exit(1)

        # 3. Next version number
        new_version = calculate_next_version(latest)

        # 4. Create (or reuse) the draft
        draft = create_new_version(latest)

        # 5. Remove inherited files
        remove_existing_files(draft)

        # 6. Upload ZIP
        upload_zip(draft, zip_path)

        # 7. Update metadata
        update_metadata(draft, new_version)

        # 8. Publish
        publish(draft)

        print("\n" + "=" * 60)
        print("INDOAGRI DATASET UPDATE COMPLETE")
        print("=" * 60)

    finally:
        if temp_dir and temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()