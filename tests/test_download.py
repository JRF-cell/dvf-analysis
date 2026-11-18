"""Offline tests for local reuse and interrupted downloads/decompression."""

import gzip
from unittest.mock import MagicMock

import pytest
import requests

from dvf.download import download_data


def test_local_csv_prevents_network_request_even_without_archive(tmp_path, monkeypatch):
    csv = tmp_path / "full.csv"
    csv.write_text("a,b\n1,2\n")
    get = MagicMock(side_effect=AssertionError("Unexpected network request"))
    monkeypatch.setattr(requests, "get", get)
    assert download_data("https://example.invalid", tmp_path / "full.csv.gz") == csv
    get.assert_not_called()


def test_local_gzip_is_decompressed(tmp_path):
    archive = tmp_path / "full.csv.gz"
    archive.write_bytes(gzip.compress(b"a,b\n1,2\n"))
    assert download_data("unused", archive).read_bytes() == b"a,b\n1,2\n"
    assert not list(tmp_path.glob("*.part"))


def test_truncated_gzip_never_publishes_partial_csv(tmp_path):
    archive = tmp_path / "full.csv.gz"
    archive.write_bytes(gzip.compress(b"a,b\n1,2\n")[:-4])
    with pytest.raises(EOFError):
        download_data("unused", archive)
    assert not archive.with_suffix("").exists()
    assert not list(tmp_path.glob("*.part"))
    assert archive.exists()


@pytest.mark.parametrize("failure", ["interrupted", "size", "empty", "http"])
def test_failed_download_never_publishes_partial_archive(
    tmp_path, monkeypatch, failure
):
    response = MagicMock()
    response.__enter__.return_value = response
    response.headers = {"content-length": "100"}
    response.iter_content.return_value = [b"partial"]
    if failure == "interrupted":

        def interrupted(*args, **kwargs):
            yield b"partial"
            raise requests.ConnectionError("interrupted")

        response.iter_content.side_effect = interrupted
    elif failure == "empty":
        response.iter_content.return_value = []
    elif failure == "http":
        response.raise_for_status.side_effect = requests.HTTPError("404")
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: response)
    archive = tmp_path / "full.csv.gz"
    with pytest.raises((requests.RequestException, ValueError)):
        download_data("https://example.invalid", archive)
    assert not archive.exists()
    assert not list(tmp_path.glob("*.part"))
