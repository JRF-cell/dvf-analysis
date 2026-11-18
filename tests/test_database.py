"""Database publication, audit and persistence checks."""

import sqlite3

import pandas as pd
import pytest

from dvf.clean import clean_with_audit
from dvf.database import load_to_sqlite
from tests.test_clean import source_row


def test_reload_is_idempotent_and_persists_all_excluded_source_rows(tmp_path):
    rows, audit = clean_with_audit(
        pd.DataFrame([source_row(), source_row("B", valeur_fonciere=None)])
    )
    path = tmp_path / "dvf.db"
    for _ in range(2):
        conn = load_to_sqlite(rows, path, audit=audit)
        conn.close()
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 1
        assert (
            conn.execute("SELECT COUNT(*) FROM price_transactions").fetchone()[0] == 1
        )
        assert conn.execute("SELECT COUNT(*) FROM row_audit").fetchone()[0] == 2
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert (
            conn.execute("SELECT code_departement FROM operations").fetchone()[0]
            == "01"
        )


def test_failed_publication_preserves_previous_tables_and_views(tmp_path):
    rows, audit = clean_with_audit(pd.DataFrame([source_row()]))
    path = tmp_path / "dvf.db"
    load_to_sqlite(rows, path, audit=audit).close()
    with pytest.raises(sqlite3.IntegrityError):
        load_to_sqlite(pd.concat([rows, rows]), path, audit=audit)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 1
        assert (
            conn.execute("SELECT COUNT(*) FROM price_transactions").fetchone()[0] == 1
        )
        assert conn.execute("SELECT COUNT(*) FROM row_audit").fetchone()[0] == 1
    # A failed staging table does not block the next successful load.
    load_to_sqlite(rows, path, audit=audit).close()
