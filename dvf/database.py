"""SQLite loading utilities for the DVF dataset."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd


def load_to_sqlite(
    df: pd.DataFrame,
    db_path: str | Path = "data/dvf.db",
) -> sqlite3.Connection:
    """Load a cleaned dataframe into a SQLite database."""

    database_path = Path(db_path)
    if str(database_path) != ":memory:":
        database_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(str(database_path))
    if str(database_path) != ":memory:":
        connection.execute("PRAGMA journal_mode = WAL;")
    connection.execute("PRAGMA synchronous = NORMAL;")

    dataframe_to_store = df.copy()
    if "date_mutation" in dataframe_to_store.columns:
        dataframe_to_store["date_mutation"] = pd.to_datetime(
            dataframe_to_store["date_mutation"],
            errors="coerce",
        ).dt.strftime("%Y-%m-%d")

    dataframe_to_store.to_sql(
        "transactions",
        connection,
        if_exists="replace",
        index=False,
    )

    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_dept ON transactions(code_departement);"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_type ON transactions(type_local);"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_date ON transactions(date_mutation);"
    )
    connection.commit()

    return connection
