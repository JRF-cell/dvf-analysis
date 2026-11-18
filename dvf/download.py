"""Download helpers with local reuse and atomic publication of complete files."""

from __future__ import annotations

import gzip
import shutil
from pathlib import Path

import requests
from tqdm import tqdm


def download_data(url: str, dest_path: str | Path) -> Path:
    """Reuse a nonempty local CSV; otherwise download and decompress via .part."""
    destination = Path(dest_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    csv_path = (
        destination.with_suffix("")
        if destination.suffix == ".gz"
        else (destination.parent / "full.csv")
    )
    if csv_path.exists() and csv_path.stat().st_size:
        print(f"CSV already present: {csv_path}")
        return csv_path

    if destination.exists() and destination.stat().st_size:
        print(f"Archive already present: {destination}")
    else:
        partial = destination.with_name(destination.name + ".part")
        try:
            with requests.get(url, stream=True, timeout=60) as response:
                response.raise_for_status()
                total_size = int(response.headers.get("content-length", 0))
                with (
                    partial.open("wb") as handle,
                    tqdm(
                        total=total_size,
                        unit="B",
                        unit_scale=True,
                        desc="Downloading DVF",
                    ) as progress,
                ):
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            handle.write(chunk)
                            progress.update(len(chunk))
                if partial.stat().st_size == 0:
                    raise ValueError("Downloaded archive is empty")
                if total_size and partial.stat().st_size != total_size:
                    raise ValueError(
                        "Downloaded archive size does not match Content-Length"
                    )
            partial.replace(destination)
        finally:
            partial.unlink(missing_ok=True)

    partial_csv = csv_path.with_name(csv_path.name + ".part")
    try:
        with (
            gzip.open(destination, "rb") as compressed,
            partial_csv.open("wb") as output,
        ):
            shutil.copyfileobj(compressed, output)
        if partial_csv.stat().st_size == 0:
            raise ValueError("Decompressed CSV is empty")
        partial_csv.replace(csv_path)
    finally:
        partial_csv.unlink(missing_ok=True)
    print(f"Decompressed archive to: {csv_path}")
    return csv_path
