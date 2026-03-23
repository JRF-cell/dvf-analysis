"""Download helpers for the DVF dataset."""

from __future__ import annotations

import gzip
import shutil
from pathlib import Path

import requests
from tqdm import tqdm


def download_data(url: str, dest_path: str | Path) -> Path:
    """Download the DVF archive and decompress it to a CSV file."""

    destination = Path(dest_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    csv_path = destination.with_suffix("") if destination.suffix == ".gz" else (
        destination.parent / "full.csv"
    )

    if destination.exists():
        print(f"Archive already present: {destination}")
    else:
        response = requests.get(url, stream=True, timeout=60)
        response.raise_for_status()
        total_size = int(response.headers.get("content-length", 0))

        with destination.open("wb") as file_handle:
            with tqdm(
                total=total_size,
                unit="B",
                unit_scale=True,
                desc="Downloading DVF",
            ) as progress:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    file_handle.write(chunk)
                    progress.update(len(chunk))

    if csv_path.exists():
        print(f"CSV already present: {csv_path}")
        return csv_path

    with gzip.open(destination, "rb") as compressed_handle:
        with csv_path.open("wb") as csv_handle:
            shutil.copyfileobj(compressed_handle, csv_handle)

    print(f"Decompressed archive to: {csv_path}")
    return csv_path
