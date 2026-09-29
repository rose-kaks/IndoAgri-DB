import os
import shutil
import tempfile
import zipfile
from pathlib import Path

import requests


ZENODO_API = "https://zenodo.org/api"
TOKEN = os.environ["ZENODO_TOKEN"]

TITLE = "IndoAgri-DB: Agriculture Knowledge Base Dataset for India"

DESCRIPTION = """
IndoAgri-DB is an automated, periodically updated agriculture knowledge base
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
]

KEYWORDS = [
    "agriculture",
    "India",
    "agricultural datasets",
    "agriculture knowledge base",
    "farmer queries",
    "Kisan Call Centre",
    "mandi prices",
    "soil health",
    "weather",
    "crop advisories",
    "government schemes",
    "disaster alerts",
    "retrieval augmented generation",
    "RAG",
]


def headers():
    return {
        "Authorization": f"Bearer {TOKEN}",
    }


def json_headers():
    return {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    }


def check_response(response, message):
    if not response.ok:
        print(f"\nERROR: {message}")
        print(f"Status: {response.status_code}")
        print(response.text)
        response.raise_for_status()


def create_dataset_zip(output_path):
    """
    Create a ZIP containing ONLY:
      processed/
      reference/
      metadata/
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
        compression=zipfile.ZIP_DEFLATED
    ) as zf:

        for folder in folders:
            for file in folder.rglob("*"):
                if file.is_file():
                    # data/processed/x.json
                    # becomes:
                    # processed/x.json
                    archive_path = file.relative_to("data")
                    zf.write(file, archive_path)

    print(f"Created dataset archive: {output_path}")


def find_latest_dataset():
    """
    Find the latest published IndoAgri-DB deposition.
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

    check_response(response, "Could not search Zenodo.")

    deposits = response.json()

    if not deposits:
        return None

    # Prefer an exact title match.
    exact = [
        d for d in deposits
        if d.get("metadata", {}).get("title") == TITLE
    ]

    if exact:
        return exact[0]

    return deposits[0]


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
            "language": "eng",
        }
    }

    response = requests.post(
        f"{ZENODO_API}/deposit/depositions",
        json=metadata,
        headers=json_headers(),
        timeout=60,
    )

    check_response(response, "Could not create Zenodo deposition.")

    deposition = response.json()
    deposition_id = deposition["id"]

    print(f"Created Zenodo deposition: {deposition_id}")

    upload_file(deposition, zip_path)

    publish(deposition_id)

    print("Published Zenodo version: 1.0.0")
    print(f"DOI: {deposition.get('doi', 'check Zenodo record')}")


def create_new_version(latest, zip_path):
    """
    Create the next version from the latest published version.
    """

    latest_id = latest["id"]

    print(f"Latest Zenodo deposition: {latest_id}")

    response = requests.post(
        f"{ZENODO_API}/deposit/depositions/"
        f"{latest_id}/actions/newversion",
        headers=headers(),
        timeout=60,
    )

    check_response(response, "Could not create new Zenodo version.")

    original = response.json()

    draft_link = original["links"]["latest_draft"]

    draft_response = requests.get(
        draft_link,
        headers=headers(),
        timeout=60,
    )

    check_response(
        draft_response,
        "Could not retrieve new Zenodo draft."
    )

    draft = draft_response.json()
    draft_id = draft["id"]

    print(f"Created new Zenodo draft: {draft_id}")

    # Determine next version.
    old_version = latest.get("metadata", {}).get("version", "1.0.0")

    parts = old_version.split(".")

    if len(parts) != 3:
        raise ValueError(
            f"Expected semantic version like 1.0.0, got: {old_version}"
        )

    major, minor, patch = map(int, parts)
    new_version = f"{major}.{minor}.{patch + 1}"

    # Delete inherited files.
    delete_existing_files(draft)

    # Upload the new dataset ZIP.
    upload_file(draft, zip_path)

    # Update metadata.
    metadata = {
        "metadata": {
            "title": TITLE,
            "upload_type": "dataset",
            "description": DESCRIPTION,
            "version": new_version,
            "creators": CREATORS,
            "keywords": KEYWORDS,
            "language": "eng",
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
        "Could not update Zenodo metadata."
    )

    publish(draft_id)

    published = update_response.json()

    print(f"Published Zenodo version: {new_version}")
    print(f"Zenodo deposition ID: {draft_id}")
    print(f"DOI: {published.get('doi', 'check Zenodo record')}")


def upload_file(deposition, zip_path):
    """
    Upload the dataset ZIP using Zenodo's current bucket/files API.
    """

    bucket_url = deposition["links"]["bucket"]

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
        f"Could not upload {filename}."
    )

    print("Upload complete.")


def delete_existing_files(deposition):
    """
    Delete inherited files from the new draft before uploading
    the new dataset snapshot.
    """

    deposition_id = deposition["id"]

    response = requests.get(
        f"{ZENODO_API}/deposit/depositions/{deposition_id}/files",
        headers=headers(),
        timeout=60,
    )

    check_response(
        response,
        "Could not list existing Zenodo files."
    )

    files = response.json()

    for file_info in files:
        file_id = file_info["id"]

        print(f"Deleting inherited file: {file_info.get('filename')}")

        delete_response = requests.delete(
            f"{ZENODO_API}/deposit/depositions/"
            f"{deposition_id}/files/{file_id}",
            headers=headers(),
            timeout=60,
        )

        check_response(
            delete_response,
            f"Could not delete inherited file {file_id}."
        )


def publish(deposition_id):
    """
    Publish the Zenodo deposition.
    """

    response = requests.post(
        f"{ZENODO_API}/deposit/depositions/"
        f"{deposition_id}/actions/publish",
        headers=headers(),
        timeout=120,
    )

    check_response(
        response,
        f"Could not publish Zenodo deposition {deposition_id}."
    )


def main():
    temp_dir = Path(tempfile.mkdtemp())

    try:
        zip_path = temp_dir / "indoagri-dataset.zip"

        create_dataset_zip(zip_path)

        latest = find_latest_dataset()

        if latest is None:
            print("No previous IndoAgri-DB Zenodo record found.")
            print("Creating first version: 1.0.0")
            create_first_deposition(zip_path)

        else:
            print(
                f"Found existing version: "
                f"{latest.get('metadata', {}).get('version')}"
            )
            create_new_version(latest, zip_path)

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
