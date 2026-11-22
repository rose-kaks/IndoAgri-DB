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


# =========================================================
# HTTP HELPERS
# =========================================================

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
        print()
        print(f"ERROR: {message}")
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")
        print()
        response.raise_for_status()


# =========================================================
# CREATE DATASET ZIP
# =========================================================

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

                    archive_path = file.relative_to("data")

                    zf.write(
                        file,
                        archive_path,
                    )

    print(f"Created dataset archive: {output_path}")


# =========================================================
# FIND LATEST VERSION
# =========================================================

def find_latest_dataset():
    """
    Find the latest published IndoAgri-DB dataset.

    We intentionally search all published versions and then
    select the highest semantic version.
    """

    response = requests.get(
        f"{ZENODO_API}/deposit/depositions",
        params={
            "q": f'title:"{TITLE}"',
            "status": "published",
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

    exact = [
        d
        for d in deposits
        if d.get("metadata", {}).get("title") == TITLE
    ]

    if not exact:
        exact = deposits

    def version_key(deposition):
        version = (
            deposition
            .get("metadata", {})
            .get("version", "0.0.0")
        )

        try:
            return tuple(
                int(x)
                for x in version.split(".")
            )
        except Exception:
            return (0, 0, 0)

    exact.sort(
        key=version_key,
        reverse=True,
    )

    return exact[0]


# =========================================================
# VERSION HELPERS
# =========================================================

def increment_patch_version(version):
    """
    Examples:

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

    major, minor, patch = map(int, parts)

    return f"{major}.{minor}.{patch + 1}"


# =========================================================
# CREATE FIRST DEPOSITION
# =========================================================

def create_first_deposition(zip_path):

    version = "1.0.0"

    metadata = {
        "metadata": {
            "title": TITLE,
            "upload_type": "dataset",
            "description": DESCRIPTION,
            "version": version,
            "creators": CREATORS,
            "keywords": KEYWORDS,
        }
    }

    print()
    print("========================================")
    print("Creating first Zenodo deposition")
    print("========================================")
    print(f"Version: {version}")

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

    published = publish(
        deposition_id,
    )

    print()
    print("========================================")
    print("Zenodo publication successful")
    print("========================================")
    print(f"Version: {version}")
    print(f"Deposition ID: {deposition_id}")
    print(
        f"DOI: {published.get('doi', 'check Zenodo record')}"
    )


# =========================================================
# CREATE NEW DEPOSITION
# =========================================================

def create_new_deposition(zip_path, version, previous=None):
    """
    Create a completely new Zenodo deposition.

    This is intentionally used instead of:

        /actions/newversion

    because the existing deposition 23043351 is currently
    rejected by Zenodo's API with:

        files.enabled
        Please remove all files first.

    The new deposition receives the requested dataset version.
    """

    metadata = {
        "metadata": {
            "title": TITLE,
            "upload_type": "dataset",
            "description": DESCRIPTION,
            "version": version,
            "creators": CREATORS,
            "keywords": KEYWORDS,
        }
    }

    # -----------------------------------------------------
    # Optional relationship to previous version
    # -----------------------------------------------------

    if previous:

        previous_doi = (
            previous
            .get("doi")
        )

        previous_id = (
            previous
            .get("id")
        )

        print()
        print("Previous Zenodo version:")
        print(f"  Version: {previous.get('metadata', {}).get('version')}")
        print(f"  ID: {previous_id}")

        if previous_doi:
            print(f"  DOI: {previous_doi}")

    print()
    print("========================================")
    print("Creating new Zenodo deposition")
    print("========================================")
    print(f"Version: {version}")

    response = requests.post(
        f"{ZENODO_API}/deposit/depositions",
        json=metadata,
        headers=json_headers(),
        timeout=60,
    )

    check_response(
        response,
        "Could not create new Zenodo deposition.",
    )

    deposition = response.json()

    deposition_id = deposition["id"]

    print(
        f"Created new Zenodo deposition: {deposition_id}"
    )

    # -----------------------------------------------------
    # Upload dataset
    # -----------------------------------------------------

    upload_file(
        deposition,
        zip_path,
    )

    # -----------------------------------------------------
    # Publish
    # -----------------------------------------------------

    published = publish(
        deposition_id,
    )

    print()
    print("========================================")
    print("Zenodo publication successful")
    print("========================================")
    print(f"Version: {version}")
    print(f"Deposition ID: {deposition_id}")

    doi = published.get(
        "doi",
        deposition.get(
            "doi",
            "check Zenodo record"
        ),
    )

    print(f"DOI: {doi}")

    return published


# =========================================================
# UPLOAD FILE
# =========================================================

def upload_file(deposition, zip_path):
    """
    Upload the dataset ZIP using Zenodo's bucket API.
    """

    bucket_url = (
        deposition
        .get("links", {})
        .get("bucket")
    )

    if not bucket_url:
        raise RuntimeError(
            "Zenodo deposition does not contain a bucket URL."
        )

    filename = Path(zip_path).name

    print()
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


# =========================================================
# PUBLISH
# =========================================================

def publish(deposition_id):

    print(
        f"Publishing Zenodo deposition {deposition_id}..."
    )

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


# =========================================================
# MAIN
# =========================================================

def main():

    temp_dir = Path(
        tempfile.mkdtemp()
    )

    try:

        # -------------------------------------------------
        # 1. Create dataset ZIP
        # -------------------------------------------------

        zip_path = (
            temp_dir /
            "indoagri-dataset.zip"
        )

        create_dataset_zip(
            zip_path
        )

        # -------------------------------------------------
        # 2. Find latest published dataset
        # -------------------------------------------------

        latest = find_latest_dataset()

        # -------------------------------------------------
        # 3. First-ever release
        # -------------------------------------------------

        if latest is None:

            print()
            print(
                "No previous IndoAgri-DB Zenodo record found."
            )

            print(
                "Creating first version: 1.0.0"
            )

            create_first_deposition(
                zip_path
            )

        # -------------------------------------------------
        # 4. Existing release
        # -------------------------------------------------

        else:

            old_version = (
                latest
                .get("metadata", {})
                .get("version", "1.0.0")
            )

            new_version = increment_patch_version(
                old_version
            )

            print()
            print(
                f"Found existing version: {old_version}"
            )

            print(
                f"Latest Zenodo deposition: "
                f"{latest.get('id')}"
            )

            print(
                f"Next version: {new_version}"
            )

            # IMPORTANT:
            #
            # We DO NOT call:
            #
            #   /actions/newversion
            #
            # because the existing deposition currently
            # triggers:
            #
            #   files.enabled
            #   Please remove all files first.
            #
            # Instead, create a clean new deposition.

            create_new_deposition(
                zip_path=zip_path,
                version=new_version,
                previous=latest,
            )

    finally:

        shutil.rmtree(
            temp_dir,
            ignore_errors=True
        )


if __name__ == "__main__":
    main()
