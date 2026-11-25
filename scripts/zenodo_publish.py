import os
import sys
import json
import zipfile
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

import requests


ZENODO_API = "https://zenodo.org/api"

# Stable all-versions DOI
ZENODO_DOI = "10.5281/zenodo.23043350"

# Zenodo concept/family ID
ZENODO_CONCEPT_ID = "23294725"

ZENODO_TOKEN = os.environ.get("ZENODO_TOKEN")

if not ZENODO_TOKEN:
    print("[ERROR] ZENODO_TOKEN is not set.")
    sys.exit(1)

HEADERS = {
    "Authorization": f"Bearer {ZENODO_TOKEN}",
    "Content-Type": "application/json",
    "User-Agent": "IndoAgri-DB/1.0",
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

def check_response(response, operation):
    if response.ok:
        return

    print(f"[ERROR] {operation} failed")
    print(f"[ERROR] HTTP {response.status_code}")

    try:
        print(json.dumps(response.json(), indent=2))
    except Exception:
        print(response.text[:5000])

    sys.exit(1)


# ============================================================
# CREATE DATASET ZIP
# ============================================================

def create_dataset_zip():

    print("\n" + "=" * 60)
    print("CREATING DATASET ZIP")
    print("=" * 60)

    temp_dir = Path(
        tempfile.mkdtemp(prefix="indoagri_zenodo_")
    )

    timestamp = datetime.utcnow().strftime(
        "%Y%m%d_%H%M%S"
    )

    zip_path = (
        temp_dir / f"indoagri-db-{timestamp}.zip"
    )

    with zipfile.ZipFile(
        zip_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as zf:

        for data_dir in DATA_DIRS:

            if not data_dir.exists():
                print(
                    f"[WARNING] Missing directory: {data_dir}"
                )
                continue

            print(f"[INFO] Including: {data_dir}")

            for file_path in data_dir.rglob("*"):

                if not file_path.is_file():
                    continue

                arcname = file_path.relative_to(ROOT_DIR)

                zf.write(
                    file_path,
                    arcname,
                )

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
    print(
        f"[INFO] Zenodo concept/record family: "
        f"{ZENODO_CONCEPT_ID}"
    )

    url = f"{ZENODO_API}/records"

    params = {
        "q": f"parent.id:{ZENODO_CONCEPT_ID}",
        "all_versions": "true",
        "status": "published",
        "size": 100,
        "sort": "-mostrecent",
    }

    response = requests.get(
        url,
        headers=HEADERS,
        params=params,
        timeout=60,
    )

    check_response(
        response,
        "Searching Zenodo records",
    )

    data = response.json()

    hits = (
        data
        .get("hits", {})
        .get("hits", [])
    )

    if not hits:

        print(
            "[WARNING] No versions found using "
            "parent.id search."
        )

        print("[INFO] Trying DOI lookup...")

        doi_url = f"https://doi.org/{ZENODO_DOI}"

        doi_response = requests.get(
            doi_url,
            allow_redirects=True,
            timeout=30,
        )

        print(
            f"[INFO] DOI resolved to: "
            f"{doi_response.url}"
        )

        final_url = doi_response.url

        if "/records/" in final_url:

            record_id = (
                final_url
                .split("/records/")[1]
                .split("?")[0]
                .split("#")[0]
                .strip("/")
            )

            print(
                f"[INFO] DOI record ID: {record_id}"
            )

            record_url = (
                f"{ZENODO_API}/records/{record_id}"
            )

            record_response = requests.get(
                record_url,
                headers=HEADERS,
                timeout=30,
            )

            if record_response.ok:
                record = record_response.json()

                print(
                    "[OK] Found dataset through DOI."
                )

                return record

        return None

    print(
        f"[OK] Found {len(hits)} published version(s)"
    )

    print("\n[INFO] Published versions:")

    for record in hits:

        metadata = record.get(
            "metadata",
            {},
        )

        print(
            f"  record={record.get('id')} "
            f"| version={metadata.get('version')} "
            f"| created={record.get('created')}"
        )

    latest = hits[0]

    metadata = latest.get(
        "metadata",
        {},
    )

    print("\n[OK] Latest Zenodo version found")
    print(f"[INFO] Record ID : {latest.get('id')}")
    print(f"[INFO] Version   : {metadata.get('version')}")
    print(f"[INFO] DOI       : {latest.get('doi')}")

    return latest


# ============================================================
# CALCULATE NEXT VERSION
# ============================================================

def calculate_next_version(latest):

    metadata = latest.get(
        "metadata",
        {},
    )

    current = metadata.get(
        "version",
        "0.0.0",
    )

    print(
        f"[INFO] Current dataset version: {current}"
    )

    try:

        parts = current.split(".")

        major = int(parts[0])
        minor = int(parts[1])
        patch = int(parts[2])

        new_version = (
            f"{major}.{minor}.{patch + 1}"
        )

    except Exception:

        print(
            "[WARNING] Invalid version format."
        )

        new_version = "1.0.0"

    print(
        f"[INFO] New dataset version: {new_version}"
    )

    return new_version


# ============================================================
# CREATE NEW ZENODO VERSION
# ============================================================

def create_new_version(latest):

    print("\n" + "=" * 60)
    print("CREATING NEW ZENODO VERSION")
    print("=" * 60)

    latest_record_id = latest.get("id")

    if not latest_record_id:
        print(
            "[ERROR] Latest record has no ID."
        )
        sys.exit(1)

    print(
        f"[INFO] Using latest version record: "
        f"{latest_record_id}"
    )

    url = (
        f"{ZENODO_API}/deposit/depositions/"
        f"{latest_record_id}/actions/newversion"
    )

    response = requests.post(
        url,
        headers=HEADERS,
        timeout=60,
    )

    check_response(
        response,
        "Creating Zenodo new version",
    )

    result = response.json()

    draft_url = (
        result
        .get("links", {})
        .get("latest_draft")
    )

    if not draft_url:

        print(
            "[ERROR] Zenodo did not return "
            "links.latest_draft."
        )

        print(
            json.dumps(
                result,
                indent=2,
            )
        )

        sys.exit(1)

    print(
        f"[OK] New draft URL: {draft_url}"
    )

    draft_response = requests.get(
        draft_url,
        headers=HEADERS,
        timeout=60,
    )

    check_response(
        draft_response,
        "Fetching new Zenodo draft",
    )

    draft = draft_response.json()

    draft_id = draft.get("id")

    if not draft_id:

        print(
            "[ERROR] Could not determine "
            "draft deposition ID."
        )

        sys.exit(1)

    print(
        f"[OK] New draft deposition ID: "
        f"{draft_id}"
    )

    return draft


# ============================================================
# REMOVE EXISTING FILES
# ============================================================

def remove_existing_files(draft):

    files = draft.get(
        "files",
        [],
    )

    if not files:

        print(
            "[INFO] Draft has no existing files."
        )

        return

    print(
        f"[INFO] Draft contains "
        f"{len(files)} existing file(s)."
    )

    deposition_id = draft["id"]

    for file_info in files:

        file_id = file_info.get("id")
        filename = file_info.get("filename")

        if not file_id:
            continue

        print(
            f"[INFO] Removing: {filename}"
        )

        url = (
            f"{ZENODO_API}/deposit/depositions/"
            f"{deposition_id}/files/{file_id}"
        )

        response = requests.delete(
            url,
            headers=HEADERS,
            timeout=60,
        )

        check_response(
            response,
            f"Deleting {filename}",
        )

    print(
        "[OK] Existing files removed."
    )


# ============================================================
# UPLOAD ZIP
# ============================================================

def upload_zip(draft, zip_path):

    print("\n" + "=" * 60)
    print("UPLOADING DATASET ZIP")
    print("=" * 60)

    bucket_url = (
        draft
        .get("links", {})
        .get("bucket")
    )

    if not bucket_url:

        print(
            "[ERROR] Zenodo did not provide "
            "a bucket URL."
        )

        sys.exit(1)

    filename = zip_path.name

    upload_url = (
        f"{bucket_url}/{filename}"
    )

    size_mb = (
        zip_path.stat().st_size
        / (1024 * 1024)
    )

    print(
        f"[INFO] Uploading: {filename}"
    )

    print(
        f"[INFO] Size: {size_mb:.2f} MB"
    )

    upload_headers = {
        "Authorization": (
            f"Bearer {ZENODO_TOKEN}"
        ),
        "User-Agent": (
            "IndoAgri-DB/1.0"
        ),
        "Content-Type": (
            "application/octet-stream"
        ),
    }

    with open(
        zip_path,
        "rb",
    ) as f:

        response = requests.put(
            upload_url,
            headers=upload_headers,
            data=f,
            timeout=600,
        )

    check_response(
        response,
        "Uploading dataset ZIP",
    )

    print(
        "[OK] Dataset ZIP uploaded."
    )


# ============================================================
# UPDATE METADATA
# ============================================================

def update_metadata(
    draft,
    new_version,
):

    print("\n" + "=" * 60)
    print("UPDATING ZENODO METADATA")
    print("=" * 60)

    deposition_id = draft["id"]

    metadata = dict(
        draft.get(
            "metadata",
            {},
        )
    )

    metadata["title"] = DATASET_TITLE
    metadata["upload_type"] = "dataset"
    metadata["version"] = new_version

    if not metadata.get(
        "description"
    ):

        metadata["description"] = (
            "IndoAgri-DB agricultural "
            "knowledge dataset for the "
            "IndoAgri/Kisan Bot offline "
            "RAG system."
        )

    url = (
        f"{ZENODO_API}/deposit/depositions/"
        f"{deposition_id}"
    )

    payload = {
        "metadata": metadata
    }

    response = requests.put(
        url,
        headers=HEADERS,
        json=payload,
        timeout=60,
    )

    check_response(
        response,
        "Updating Zenodo metadata",
    )

    print(
        "[OK] Metadata updated."
    )

    print(
        f"[INFO] Version: {new_version}"
    )


# ============================================================
# PUBLISH
# ============================================================

def publish(draft):

    print("\n" + "=" * 60)
    print("PUBLISHING ZENODO VERSION")
    print("=" * 60)

    deposition_id = draft["id"]

    url = (
        f"{ZENODO_API}/deposit/depositions/"
        f"{deposition_id}/actions/publish"
    )

    response = requests.post(
        url,
        headers=HEADERS,
        timeout=60,
    )

    check_response(
        response,
        "Publishing Zenodo version",
    )

    published = response.json()

    record_id = published.get(
        "record_id"
    )

    if not record_id:
        record_id = published.get(
            "id"
        )

    links = published.get(
        "links",
        {}
    )

    record_url = links.get(
        "record_html"
    )

    doi = published.get(
        "doi"
    )

    print("\n" + "=" * 60)
    print("ZENODO PUBLISH SUCCESS")
    print("=" * 60)

    print(
        f"[OK] Record ID: {record_id}"
    )

    if doi:
        print(
            f"[OK] Version DOI: {doi}"
        )

    if record_url:
        print(
            f"[OK] Version URL: {record_url}"
        )

    print(
        "[OK] All-versions DOI: "
        "https://doi.org/10.5281/zenodo.23043350"
    )

    return published


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n")
    print("=" * 60)
    print("INDOAGRI → ZENODO DATASET PUBLISHER")
    print("=" * 60)

    print(
        f"[INFO] All-versions DOI: "
        f"{ZENODO_DOI}"
    )

    print(
        f"[INFO] Zenodo concept/record family: "
        f"{ZENODO_CONCEPT_ID}"
    )

    zip_path = None
    temp_dir = None

    try:

        # 1. Create ZIP
        zip_path, temp_dir = (
            create_dataset_zip()
        )

        # 2. Find latest version
        latest = (
            find_latest_version()
        )

        if latest is None:

            print(
                "\n[ERROR] Could not find "
                "existing IndoAgri Zenodo "
                "dataset."
            )

            print(
                f"[ERROR] Expected family: "
                f"{ZENODO_CONCEPT_ID}"
            )

            print(
                "[ERROR] Refusing to create "
                "an unrelated Zenodo record."
            )

            sys.exit(1)

        # 3. Calculate next version
        new_version = (
            calculate_next_version(
                latest
            )
        )

        # 4. Create new version
        draft = (
            create_new_version(
                latest
            )
        )

        # 5. Remove inherited files
        remove_existing_files(
            draft
        )

        # 6. Upload ZIP
        upload_zip(
            draft,
            zip_path
        )

        # 7. Update metadata
        update_metadata(
            draft,
            new_version
        )

        # 8. Publish
        publish(
            draft
        )

        print("\n")
        print("=" * 60)
        print("INDOAGRI DATASET UPDATE COMPLETE")
        print("=" * 60)

    finally:

        if (
            temp_dir
            and temp_dir.exists()
        ):
            shutil.rmtree(
                temp_dir,
                ignore_errors=True,
            )


if __name__ == "__main__":
    main()
