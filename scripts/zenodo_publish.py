import os
import shutil
import tempfile
import zipfile
from pathlib import Path

import requests


ZENODO_API = "https://zenodo.org/api"
TOKEN = os.environ["ZENODO_TOKEN"]

TITLE = "IndoAgri-DB: Agriculture Dataset for India"

DESCRIPTION = """
IndoAgri-DB is an automated, periodically updated agriculture dataset
for India. This release contains the processed and reference datasets
generated from publicly available agricultural data sources.

The dataset covers administrative information, weather, soil health,
mandi prices, disaster alerts, government schemes, farmer queries,
and crop advisories.

This dataset is intended for research and development of agricultural
information systems, knowledge bases, and retrieval-augmented generation
(RAG) applications.
""".strip()

CREATORS = [
    {
        "name": "Kakrania, Rose",
        "affiliation": "Indira Gandhi Delhi Technical University for Women (IGDTUW), Delhi, India",
    },
    {
        "name": "Sharma, Harshita",
        "affiliation": "Indira Gandhi Delhi Technical University for Women (IGDTUW), Delhi, India",
    },
    {
        "name": "Vashistha, Pearl",
        "affiliation": "Indira Gandhi Delhi Technical University for Women (IGDTUW), Delhi, India",
    },
    {
        "name": "Agrasen, Priya",
        "affiliation": "Indira Gandhi Delhi Technical University for Women (IGDTUW), Delhi, India",
    },
    {
        "name": "Jain, Bhawna",
        "affiliation": "Indira Gandhi Delhi Technical University for Women (IGDTUW), Delhi, India",
    },
]

KEYWORDS = [
    "agriculture",
    "India",
    "agricultural datasets",
    "farmer queries",
    "Kisan Call Centre",
    "mandi prices",
    "soil health",
    "weather",
    "crop advisories",
    "government schemes",
    "disaster alerts",
]


# ---------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------

def headers():
    return {
        "Authorization": f"Bearer {TOKEN}",
        "User-Agent": "IndoAgri-DB/1.0",
    }


def json_headers():
    return {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": "IndoAgri-DB/1.0",
    }


def check_response(response, message):
    if not response.ok:
        print(f"\nERROR: {message}")
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")
        response.raise_for_status()


# ---------------------------------------------------------
# Dataset ZIP
# ---------------------------------------------------------

def create_dataset_zip(output_path):
    """
    Create a ZIP containing ONLY:

        processed/
        reference/
        metadata/

    from:

        data/processed/
        data/reference/
        data/metadata/
    """

    folders = [
        Path("data/processed"),
        Path("data/reference"),
        Path("data/metadata"),
    ]

    for folder in folders:
        if not folder.exists():
            raise FileNotFoundError(
                f"Required dataset directory does not exist: {folder}"
            )

    with zipfile.ZipFile(
        output_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as zf:

        for folder in folders:
            for file in folder.rglob("*"):

                if file.is_file():

                    # Example:
                    #
                    # data/processed/crops.json
                    #
                    # becomes:
                    #
                    # processed/crops.json

                    archive_path = file.relative_to("data")

                    zf.write(
                        file,
                        archive_path,
                    )

    print(f"Created dataset archive: {output_path}")


# ---------------------------------------------------------
# Find latest published version
# ---------------------------------------------------------

def find_latest_dataset():
    """
    Find the latest published IndoAgri-DB deposition.

    We use all_versions=true and sort by most recent.
    """

    response = requests.get(
        f"{ZENODO_API}/deposit/depositions",
        params={
            "q": f'title:"{TITLE}"',
            "status": "published",
            "sort": "-mostrecent",
            "size": 100,
            "all_versions": "true",
        },
        headers=headers(),
        timeout=60,
    )

    check_response(
        response,
        "Could not search Zenodo.",
    )

    deposits = response.json()

    if not deposits:
        return None

    # Prefer exact title match.
    exact = [
        deposition
        for deposition in deposits
        if deposition.get("metadata", {}).get("title") == TITLE
    ]

    if exact:
        return exact[0]

    return deposits[0]


# ---------------------------------------------------------
# First version
# ---------------------------------------------------------

def create_first_deposition(zip_path):
    """
    Create and publish v1.0.0.
    """

    metadata = {
        "metadata": {
            "title": TITLE,
            "upload_type": "dataset",
            "description": DESCRIPTION,
            "version": "1.0.0",
            "creators": CREATORS,
            "keywords": KEYWORDS,
        }
    }

    response = requests.post(
        f"{ZENODO_API}/deposit/depositions",
        json=metadata,
        headers=json_headers(),
        timeout=60,
    )

    check_response(
        response,
        "Could not create Zenodo deposition.",
    )

    deposition = response.json()

    deposition_id = deposition["id"]

    print(f"Created Zenodo deposition: {deposition_id}")

    upload_file(
        deposition,
        zip_path,
    )

    publish(
        deposition_id,
    )

    print("Published Zenodo version: 1.0.0")
    print(
        f"DOI: {deposition.get('doi', 'check Zenodo record')}"
    )


# ---------------------------------------------------------
# Version helpers
# ---------------------------------------------------------

def increment_patch_version(version):
    """
    Increment:

        1.0.0 -> 1.0.1
        1.0.1 -> 1.0.2
        1.2.9 -> 1.2.10
    """

    if not version:
        return "1.0.1"

    parts = version.split(".")

    if len(parts) != 3:
        raise ValueError(
            f"Expected semantic version like 1.0.0, got: {version}"
        )

    try:
        major, minor, patch = map(int, parts)
    except ValueError:
        raise ValueError(
            f"Version must contain numeric components: {version}"
        )

    return f"{major}.{minor}.{patch + 1}"


# ---------------------------------------------------------
# Create new version
# ---------------------------------------------------------

def create_new_version(latest, zip_path):
    """
    Create the next Zenodo version from the latest published version.

    IMPORTANT:
    Zenodo's current new-version workflow creates a new editable
    deposition. The new draft does NOT need us to delete files
    from the published record.

    Workflow:

        latest published record
                |
                | /actions/newversion
                v
        new draft
                |
                | upload new ZIP
                v
        update metadata
                |
                | publish
                v
        new published version
    """

    latest_id = latest["id"]

    old_version = (
        latest.get("metadata", {}).get("version")
        or "1.0.0"
    )

    new_version = increment_patch_version(
        old_version
    )

    print()
    print("========================================")
    print("Creating new Zenodo version")
    print("========================================")
    print(f"Latest version: {old_version}")
    print(f"Latest deposition ID: {latest_id}")
    print(f"New version: {new_version}")
    print()

    # -----------------------------------------------------
    # Create new version
    # -----------------------------------------------------

    response = requests.post(
        f"{ZENODO_API}/deposit/depositions/"
        f"{latest_id}/actions/newversion",
        headers=headers(),
        timeout=60,
    )

    check_response(
        response,
        "Could not create new Zenodo version.",
    )

    # IMPORTANT:
    #
    # Zenodo documentation says the response is the ORIGINAL
    # deposition, not the new draft.
    #
    # The new draft is available through:
    #
    #     response["links"]["latest_draft"]
    #

    original = response.json()

    links = original.get("links", {})

    draft_link = links.get("latest_draft")

    if not draft_link:
        raise RuntimeError(
            "Zenodo created the version request but did not "
            "return links.latest_draft."
        )

    print(f"New draft URL: {draft_link}")

    # -----------------------------------------------------
    # Retrieve new draft
    # -----------------------------------------------------

    draft_response = requests.get(
        draft_link,
        headers=headers(),
        timeout=60,
    )

    check_response(
        draft_response,
        "Could not retrieve new Zenodo draft.",
    )

    draft = draft_response.json()

    draft_id = draft["id"]

    print(f"Created new Zenodo draft: {draft_id}")

    # -----------------------------------------------------
    # Upload NEW dataset ZIP
    # -----------------------------------------------------

    #
    # IMPORTANT:
    #
    # Do NOT delete files from the published deposition.
    #
    # Do NOT call:
    #
    #     delete_existing_files(latest)
    #
    # The new version is its own editable deposition.
    #

    upload_file(
        draft,
        zip_path,
    )

    # -----------------------------------------------------
    # Update metadata
    # -----------------------------------------------------

    metadata = {
        "metadata": {
            "title": TITLE,
            "upload_type": "dataset",
            "description": DESCRIPTION,
            "version": new_version,
            "creators": CREATORS,
            "keywords": KEYWORDS,
        }
    }

    update_response = requests.put(
        f"{ZENODO_API}/deposit/depositions/{draft_id}",
        json=metadata,
        headers=json_headers(),
        timeout=60,
    )

    check_response(
        update_response,
        "Could not update Zenodo metadata.",
    )

    # -----------------------------------------------------
    # Publish
    # -----------------------------------------------------

    published = publish(
        draft_id,
    )

    print()
    print("========================================")
    print("Zenodo publication successful")
    print("========================================")
    print(f"Version: {new_version}")
    print(f"Deposition ID: {draft_id}")
    print(
        f"DOI: {published.get('doi', 'check Zenodo record')}"
    )
    print()


# ---------------------------------------------------------
# Upload
# ---------------------------------------------------------

def upload_file(deposition, zip_path):
    """
    Upload dataset ZIP using Zenodo's current bucket/files API.
    """

    links = deposition.get("links", {})

    bucket_url = links.get("bucket")

    if not bucket_url:
        raise RuntimeError(
            "Zenodo deposition does not contain a bucket URL."
        )

    filename = Path(zip_path).name

    print(f"Uploading {filename}...")

    with open(zip_path, "rb") as file:

        response = requests.put(
            f"{bucket_url}/{filename}",
            data=file,
            headers=headers(),
            timeout=600,
        )

    check_response(
        response,
        f"Could not upload {filename}.",
    )

    print("Upload complete.")


# ---------------------------------------------------------
# Publish
# ---------------------------------------------------------

def publish(deposition_id):
    """
    Publish a Zenodo deposition.
    """

    print(f"Publishing deposition {deposition_id}...")

    response = requests.post(
        f"{ZENODO_API}/deposit/depositions/"
        f"{deposition_id}/actions/publish",
        headers=headers(),
        timeout=120,
    )

    check_response(
        response,
        f"Could not publish Zenodo deposition {deposition_id}.",
    )

    return response.json()


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------

def main():

    temp_dir = Path(
        tempfile.mkdtemp()
    )

    try:

        zip_path = (
            temp_dir / "indoagri-dataset.zip"
        )

        # ---------------------------------------------
        # 1. Build dataset archive
        # ---------------------------------------------

        create_dataset_zip(
            zip_path
        )

        # ---------------------------------------------
        # 2. Find existing Zenodo version
        # ---------------------------------------------

        latest = find_latest_dataset()

        # ---------------------------------------------
        # 3. First release
        # ---------------------------------------------

        if latest is None:

            print(
                "No previous IndoAgri-DB Zenodo record found."
            )

            print(
                "Creating first version: 1.0.0"
            )

            create_first_deposition(
                zip_path
            )

        # ---------------------------------------------
        # 4. New release
        # ---------------------------------------------

        else:

            current_version = (
                latest
                .get("metadata", {})
                .get("version", "unknown")
            )

            print(
                f"Found existing version: {current_version}"
            )

            print(
                f"Latest Zenodo deposition: "
                f"{latest.get('id')}"
            )

            create_new_version(
                latest,
                zip_path
            )

    finally:

        shutil.rmtree(
            temp_dir,
            ignore_errors=True
        )


if __name__ == "__main__":
    main()
