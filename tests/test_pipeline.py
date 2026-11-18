"""Exercise the actual CLI and all figures against local synthetic CSVs."""

import hashlib
import json
import sqlite3
import sys

import pandas as pd
import pytest

import main
from tests.test_clean import source_row


@pytest.mark.parametrize("empty_price_scope", [False, True])
def test_all_pipeline_offline(tmp_path, monkeypatch, empty_price_scope):
    monkeypatch.chdir(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    csv = data / "full.csv"
    if empty_price_scope:
        raw = pd.DataFrame([source_row(valeur_fonciere=None)])
    else:
        raw = pd.DataFrame(
            [
                source_row(
                    str(i),
                    code_departement="75",
                    type_local="Appartement",
                    code_type_local=2,
                    valeur_fonciere=400000,
                )
                for i in range(120)
            ]
        )
    raw.to_csv(csv, index=False)
    monkeypatch.setattr(main, "CSV_PATH", csv)
    monkeypatch.setattr(main, "ARCHIVE_PATH", data / "full.csv.gz")
    monkeypatch.setattr(main, "DB_PATH", data / "dvf.db")
    monkeypatch.setattr(sys, "argv", ["main.py", "--all"])
    main.main()
    report = json.loads((tmp_path / "outputs/quality_report.json").read_text())
    assert report["raw_rows"] == len(raw)
    assert report["source"]["sha256"] == hashlib.sha256(csv.read_bytes()).hexdigest()
    assert report["price_eligible_operations"] == (0 if empty_price_scope else 120)
    assert sum(report["volume_exclusions"].values()) == len(raw)
    assert sum(report["price_exclusions"].values()) == len(raw)
    assert report["sqlite_integrity"] == "ok"
    figures = list((tmp_path / "outputs").glob("*.png"))
    assert len(figures) == 5
    assert all(path.stat().st_size > 1000 for path in figures)
    with sqlite3.connect(data / "dvf.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM row_audit").fetchone()[0] == len(raw)
