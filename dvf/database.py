"""SQLite loading utilities, with separate row and operation grains."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd


def load_to_sqlite(
    df: pd.DataFrame,
    db_path: str | Path = "data/dvf.db",
    *,
    audit: pd.DataFrame | None = None,
) -> sqlite3.Connection:
    """Stage rows, then publish tables and views together in one transaction.

    Failed publication rolls back to the previous tables. A unique partial index
    also rejects duplicate eligible operations rather than double-count prices.
    """
    database_path = Path(db_path)
    if str(database_path) != ":memory:":
        database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(database_path))
    try:
        dataframe_to_store = df.copy()
        dataframe_to_store["date_mutation"] = pd.to_datetime(
            dataframe_to_store["date_mutation"], errors="raise"
        ).dt.strftime("%Y-%m-%d")
        dataframe_to_store.to_sql(
            "transactions_next",
            connection,
            if_exists="replace",
            index=False,
            chunksize=10000,
        )
        if audit is not None:
            audit.to_sql(
                "row_audit_next",
                connection,
                if_exists="replace",
                index=False,
                chunksize=10000,
            )
        with connection:
            connection.execute("BEGIN")
            connection.execute("DROP VIEW IF EXISTS price_transactions")
            connection.execute("DROP VIEW IF EXISTS operations")
            connection.execute("DROP TABLE IF EXISTS transactions")
            connection.execute("ALTER TABLE transactions_next RENAME TO transactions")
            connection.execute("DROP TABLE IF EXISTS row_audit")
            if audit is not None:
                connection.execute("ALTER TABLE row_audit_next RENAME TO row_audit")
                connection.execute(
                    "CREATE UNIQUE INDEX idx_audit_row ON row_audit(source_row)"
                )
            for name, columns in {
                "dept": "code_departement",
                "type": "type_local",
                "date": "date_mutation",
                "operation": "id_mutation, numero_disposition",
            }.items():
                connection.execute(
                    f"CREATE INDEX idx_{name} ON transactions({columns})"
                )
            connection.execute("""
                CREATE UNIQUE INDEX idx_price_operation
                ON transactions(id_mutation, numero_disposition)
                WHERE price_eligible = 1
            """)
            connection.execute("""
                CREATE VIEW operations AS
                SELECT id_mutation, numero_disposition,
                       MIN(year) AS year, MIN(month) AS month,
                       MIN(code_departement) AS code_departement,
                       COUNT(*) AS retained_rows
                FROM transactions
                WHERE id_mutation IS NOT NULL AND numero_disposition IS NOT NULL
                GROUP BY id_mutation, numero_disposition
                HAVING COUNT(DISTINCT date_mutation) = 1
                   AND COUNT(date_mutation) = COUNT(*)
                   AND COUNT(DISTINCT code_departement) = 1
                   AND COUNT(code_departement) = COUNT(*)
            """)
            connection.execute("""
                CREATE VIEW price_transactions AS
                SELECT * FROM transactions
                WHERE price_eligible = 1 AND raw_mutation_rows = 1
                  AND raw_operation_rows = 1 AND price_per_m2 > 0
            """)
        return connection
    except Exception:
        connection.close()
        raise
