"""
Publish IndoAgri dataset to Zenodo.

IMPORTANT:
This script creates a NEW VERSION of the existing Zenodo record.
It does NOT create an unrelated new Zenodo record.

Existing record family:
https://zenodo.org/records/23294725

Each published version can have its own version-specific record ID,
but all versions remain connected to the same Zenodo record/concept.
"""

import os
import sys
import json
import zipfile
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

import requests


# ============================================================
# CONFIG
# ============================================================

ZENODO_API = "https://zenodo.org/api"

# Your ORIGINAL Zenodo record / concept ID.
# We use this to find the correct version family.
ZENODO_CONCEPT_ID = "23294725"

ZENODO_TOKEN = os.environ.get("ZENODO_TOKEN")

if not ZENODO_TOKEN:
    print("[ERROR] ZENODO_TOKEN environment variable is not set.")
    sys.exit(1)

HEADERS = {
    "Authorization": f"Bearer {ZENODO_TOKEN}",
    "User-Agent": "IndoAgri-KB/1.0",
}

API_HEADERS = {
    **HEADERS,
    "Content-Type": "application/json",
}


# ============================================================
# HELPERS
# ============================================================

def api_get(url, **kwargs):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=60,
        **kwargs,
    )

    if not response.ok:
        print(f"[ERROR] GET {url}")
        print(f"[ERROR] Status: {response.status_code}")
        print(f"[ERROR] Response: {response.text}")
        response.raise_for_status()

    return response.json()


def api_post(url, **kwargs):
    response = requests.post(
        url,
        headers=API_HEADERS,
        timeout=120,
        **kwargs,
    )

    if not response.ok:
        print(f"[ERROR] POST {url}")
        print(f"[ERROR] Status: {response.status_code}")
        print(f"[ERROR] Response: {response.text}")
        response.raise_for_status()

    return response.json()


def api_put(url, **kwargs):
    response = requests.put(
        url,
        headers=API_HEADERS,
        timeout=120,
        **kwargs,
    )

    if not response.ok:
        print(f"[ERROR] PUT {url}")
        print(f"[ERROR] Status: {response.status_code}")
        print(f"[ERROR] Response: {response.text}")
        response.raise_for_status()

    return response.json()


# ============================================================
# VERSION HELPERS
# ============================================================

def parse_version(version):
    """
    Convert version string such as:

        1.0.4

    into:

        (1, 0, 4)
    """

    try:
        parts = str(version).strip().split(".")

        if len(parts) != 3:
            return None

        return tuple(int(x) for x in parts)

    except Exception:
        return None


def increment_patch_version(version):
    """
    1.0.4 -> 1.0.5
    """

    parsed = parse_version(version)

    if parsed is None:
        raise ValueError(
            f"Invalid semantic version: {version}"
        )

    major, minor, patch = parsed

    return f"{major}.{minor}.{patch + 1}"


def get_version_from_metadata(deposition):
    """
    Extract version from Zenodo metadata.

    Your existing records use the version field.
    """

    metadata = deposition.get("metadata", {})

    version = metadata.get("version")

    if version:
        return str(version)

    return None


# ============================================================
# FIND EXISTING RECORD FAMILY
# ============================================================

def find_latest_dataset():
    """
    Find the latest published version belonging to the
    original Zenodo record family.

    IMPORTANT:
    Zenodo's 'newversion' endpoint requires the ID of the
    latest VERSION, not the global concept ID.
    """

    print("=" * 60)
    print("FINDING EXISTING ZENODO DATASET")
    print("=" * 60)

    print(f"[INFO] Original Zenodo record: {ZENODO_CONCEPT_ID}")

    url = f"{ZENODO_API}/deposit/depositions"

    params = {
        "q": f"conceptrecid:{ZENODO_CONCEPT_ID}",
        "status": "published",
        "all_versions": "true",
        "size": 100,
    }

    response = requests.get(
        url,
        headers=HEADERS,
        params=params,
        timeout=60,
    )

    if not response.ok:
        print(f"[ERROR] Zenodo search failed: {response.status_code}")
        print(response.text)
        response.raise_for_status()

    results = response.json()

    if not results:
        print("[WARNING] No published versions found.")
        return None

    print(f"[INFO] Found {len(results)} Zenodo version(s).")

    versions = []

    for deposition in results:

        conceptrecid = str(
            deposition.get("conceptrecid", "")
        )

        record_id = str(
            deposition.get("record_id", "")
        )

        deposition_id = str(
            deposition.get("id", "")
        )

        version = get_version_from_metadata(deposition)

        # Make sure we are actually in the desired record family.
        if conceptrecid != ZENODO_CONCEPT_ID:
            continue

        if not version:
            print(
                f"[WARNING] Skipping record {record_id}: "
                f"no version found."
            )
            continue

        parsed = parse_version(version)

        if parsed is None:
            print(
                f"[WARNING] Skipping record {record_id}: "
                f"invalid version '{version}'."
            )
            continue

        versions.append({
            "version": version,
            "parsed_version": parsed,
            "deposition_id": deposition_id,
            "record_id": record_id,
            "conceptrecid": conceptrecid,
            "metadata": deposition.get("metadata", {}),
            "links": deposition.get("links", {}),
        })

    if not versions:
        print(
            "[WARNING] No usable versions found "
            f"for concept {ZENODO_CONCEPT_ID}."
        )
        return None

    versions.sort(
        key=lambda x: x["parsed_version"],
        reverse=True,
    )

    latest = versions[0]

    print()
    print("[INFO] Latest Zenodo version:")
    print(f"       Version      : {latest['version']}")
    print(f"       Deposition ID: {latest['deposition_id']}")
    print(f"       Record ID    : {latest['record_id']}")
    print(f"       Concept ID   : {latest['conceptrecid']}")

    return latest


# ============================================================
# CREATE NEW VERSION
# ============================================================

def create_new_version(latest):
    """
    Create a new Zenodo version from the latest published version.

    Zenodo endpoint:

        POST
        /api/deposit/depositions/{LATEST_VERSION_ID}/actions/newversion

    The response is the ORIGINAL deposition.

    The new unpublished version is available through:

        response["links"]["latest_draft"]
    """

    latest_deposition_id = latest["deposition_id"]

    url = (
        f"{ZENODO_API}/deposit/depositions/"
        f"{latest_deposition_id}/actions/newversion"
    )

    print()
    print("=" * 60)
    print("CREATING NEW ZENODO VERSION")
    print("=" * 60)

    print(
        f"[INFO] Creating new version from "
        f"deposition {latest_deposition_id}"
    )

    response = requests.post(
        url,
        headers=HEADERS,
        timeout=120,
    )

    if not response.ok:
        print(
            f"[ERROR] Failed to create Zenodo new version."
        )
        print(f"[ERROR] Status: {response.status_code}")
        print(f"[ERROR] Response: {response.text}")

        response.raise_for_status()

    original_deposition = response.json()

    links = original_deposition.get("links", {})

    latest_draft_url = links.get("latest_draft")

    if not latest_draft_url:
        raise RuntimeError(
            "Zenodo created/returned the response but "
            "latest_draft was not present."
        )

    print("[OK] New Zenodo draft version created.")
    print(f"[INFO] Draft URL: {latest_draft_url}")

    # Get the actual new draft deposition.
    draft = api_get(latest_draft_url)

    draft_id = draft.get("id")

    if not draft_id:
        raise RuntimeError(
            "Zenodo latest_draft did not contain a deposition ID."
        )

    print(f"[INFO] New draft deposition ID: {draft_id}")

    return draft


# ============================================================
# UPLOAD FILE
# ============================================================

def upload_file(deposition_id, file_path):
    """
    Upload the new IndoAgri database ZIP.
    """

    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(
            f"Dataset ZIP does not exist: {file_path}"
        )

    url = (
        f"{ZENODO_API}/deposit/depositions/"
        f"{deposition_id}/files"
    )

    print()
    print("=" * 60)
    print("UPLOADING DATASET")
    print("=" * 60)

    print(f"[INFO] File: {file_path}")
    print(
        f"[INFO] Size: "
        f"{file_path.stat().st_size / (1024 * 1024):.2f} MB"
    )

    # Use multipart upload.
    upload_headers = {
        "Authorization": f"Bearer {ZENODO_TOKEN}",
        "User-Agent": "IndoAgri-KB/1.0",
    }

    with open(file_path, "rb") as f:

        files = {
            "file": (
                file_path.name,
                f,
                "application/zip",
            )
        }

        data = {
            "name": file_path.name
        }

        response = requests.post(
            url,
            headers=upload_headers,
            data=data,
            files=files,
            timeout=600,
        )

    if not response.ok:
        print(
            f"[ERROR] File upload failed: "
            f"{response.status_code}"
        )
        print(response.text)
        response.raise_for_status()

    result = response.json()

    print("[OK] Dataset uploaded.")

    return result


# ============================================================
# UPDATE METADATA
# ============================================================

def update_metadata(draft, new_version):
    """
    Update the draft metadata with the new semantic version.
    """

    draft_id = draft["id"]

    current_metadata = draft.get(
        "metadata",
        {}
    ).copy()

    current_metadata["version"] = new_version

    # Make sure this remains a dataset.
    current_metadata["upload_type"] = "dataset"

    url = (
        f"{ZENODO_API}/deposit/depositions/"
        f"{draft_id}"
    )

    payload = {
        "metadata": current_metadata
    }

    print()
    print("=" * 60)
    print("UPDATING ZENODO METADATA")
    print("=" * 60)

    print(f"[INFO] Setting dataset version to {new_version}")

    response = requests.put(
        url,
        headers=API_HEADERS,
        json=payload,
        timeout=120,
    )

    if not response.ok:
        print(
            f"[ERROR] Metadata update failed: "
            f"{response.status_code}"
        )
        print(response.text)
        response.raise_for_status()

    updated = response.json()

    print("[OK] Metadata updated.")

    return updated


# ============================================================
# PUBLISH
# ============================================================

def publish(deposition_id):
    """
    Publish the new version.
    """

    url = (
        f"{ZENODO_API}/deposit/depositions/"
        f"{deposition_id}/actions/publish"
    )

    print()
    print("=" * 60)
    print("PUBLISHING ZENODO VERSION")
    print("=" * 60)

    print(
        f"[INFO] Publishing deposition {deposition_id}"
    )

    response = requests.post(
        url,
        headers=HEADERS,
        timeout=120,
    )

    if not response.ok:
        print(
            f"[ERROR] Publishing failed: "
            f"{response.status_code}"
        )
        print(response.text)
        response.raise_for_status()

    result = response.json()

    print("[OK] Zenodo version published.")

    return result


# ============================================================
# ZIP DATASET
# ============================================================

def create_dataset_zip(output_path):
    """
    Create ZIP containing the processed/reference/metadata data.

    Adjust the folders here if your repository structure changes.
    """

    repo_root = Path(__file__).resolve().parent.parent

    output_path = Path(output_path)

    print()
    print("=" * 60)
    print("CREATING DATASET ZIP")
    print("=" * 60)

    folders = [
        repo_root / "data" / "processed",
        repo_root / "data" / "reference",
        repo_root / "data" / "metadata",
    ]

    existing_folders = []

    for folder in folders:

        if folder.exists():
            existing_folders.append(folder)
            print(f"[INFO] Including: {folder}")
        else:
            print(
                f"[WARNING] Folder does not exist: {folder}"
            )

    if not existing_folders:
        raise RuntimeError(
            "No dataset folders found."
        )

    with zipfile.ZipFile(
        output_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as z:

        for folder in existing_folders:

            for file in folder.rglob("*"):

                if not file.is_file():
                    continue

                arcname = file.relative_to(repo_root)

                z.write(
                    file,
                    arcname,
                )

    print(
        f"[OK] Created ZIP: {output_path}"
    )

    print(
        f"[INFO] ZIP size: "
        f"{output_path.stat().st_size / (1024 * 1024):.2f} MB"
    )

    return output_path


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 60)
    print("INDOAGRI → ZENODO DATASET PUBLISHER")
    print("=" * 60)

    print(
        f"[INFO] Zenodo concept/record family: "
        f"{ZENODO_CONCEPT_ID}"
    )

    timestamp = datetime.utcnow().strftime(
        "%Y%m%d_%H%M%S"
    )

    temp_dir = Path(
        tempfile.mkdtemp(
            prefix="indoagri_zenodo_"
        )
    )

    zip_path = (
        temp_dir /
        f"indoagri-db-{timestamp}.zip"
    )

    try:

        # ----------------------------------------------------
        # 1. Create dataset ZIP
        # ----------------------------------------------------

        create_dataset_zip(zip_path)

        # ----------------------------------------------------
        # 2. Find latest version
        # ----------------------------------------------------

        latest = find_latest_dataset()

        if latest is None:

            print()
            print(
                "[ERROR] Could not find the original "
                "Zenodo dataset."
            )

            print(
                f"[ERROR] Expected record family: "
                f"{ZENODO_CONCEPT_ID}"
            )

            print(
                "[ERROR] Refusing to create a random "
                "new Zenodo record."
            )

            sys.exit(1)

        # ----------------------------------------------------
        # 3. Calculate next version
        # ----------------------------------------------------

        current_version = latest["version"]

        new_version = increment_patch_version(
            current_version
        )

        print()
        print(
            f"[INFO] Current version: {current_version}"
        )
        print(
            f"[INFO] New version    : {new_version}"
        )

        # ----------------------------------------------------
        # 4. Create Zenodo new version
        # ----------------------------------------------------

        draft = create_new_version(
            latest
        )

        draft_id = draft["id"]

        # ----------------------------------------------------
        # 5. Upload new dataset
        # ----------------------------------------------------

        upload_file(
            draft_id,
            zip_path,
        )

        # ----------------------------------------------------
        # 6. Update metadata/version
        # ----------------------------------------------------

        update_metadata(
            draft,
            new_version,
        )

        # ----------------------------------------------------
        # 7. Publish
        # ----------------------------------------------------

        published = publish(
            draft_id
        )

        # ----------------------------------------------------
        # 8. Print result
        # ----------------------------------------------------

        print()
        print("=" * 60)
        print("ZENODO PUBLISH SUCCESS")
        print("=" * 60)

        print(
            f"[OK] Version: {new_version}"
        )

        print(
            f"[OK] Record ID: "
            f"{published.get('record_id', draft_id)}"
        )

        print(
            f"[OK] Concept ID: "
            f"{published.get('conceptrecid', ZENODO_CONCEPT_ID)}"
        )

        record_url = (
            published.get("links", {})
            .get("record_html")
        )

        if not record_url:
            record_url = (
                published.get("record_url")
            )

        if record_url:
            print(
                f"[OK] Record URL: {record_url}"
            )

        print()
        print(
            "[OK] Dataset published as a NEW VERSION "
            "of the existing Zenodo record."
        )

    except Exception as exc:

        print()
        print("=" * 60)
        print("ZENODO PUBLISH FAILED")
        print("=" * 60)

        print(f"[ERROR] {exc}")

        sys.exit(1)

    finally:

        shutil.rmtree(
            temp_dir,
            ignore_errors=True,
        )


if __name__ == "__main__":
    main()
