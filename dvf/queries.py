"""SQL analytics: volumes use operations; price statistics use price_transactions.

In price queries transaction_count always denotes the eligible price sample,
not the full volume of residential operations. Means are unweighted ratios.
"""

from __future__ import annotations

import math
import sqlite3

import pandas as pd


class MedianAggregate:
    """SQLite aggregate that computes a median."""

    def __init__(self) -> None:
        self.values: list[float] = []

    def step(self, value: float | None) -> None:
        if value is not None:
            self.values.append(float(value))

    def finalize(self) -> float | None:
        if not self.values:
            return None

        ordered = sorted(self.values)
        midpoint = len(ordered) // 2
        if len(ordered) % 2 == 1:
            return ordered[midpoint]
        return (ordered[midpoint - 1] + ordered[midpoint]) / 2


class StdDevAggregate:
    """SQLite aggregate that computes a standard deviation."""

    def __init__(self) -> None:
        self.count = 0
        self.mean = 0.0
        self.m2 = 0.0

    def step(self, value: float | None) -> None:
        if value is None:
            return

        self.count += 1
        delta = float(value) - self.mean
        self.mean += delta / self.count
        delta2 = float(value) - self.mean
        self.m2 += delta * delta2

    def finalize(self) -> float | None:
        if self.count == 0:
            return None
        if self.count == 1:
            return 0.0
        variance = self.m2 / (self.count - 1)
        return math.sqrt(variance)


def _ensure_sqlite_functions(conn: sqlite3.Connection) -> None:
    """Register custom SQLite aggregates required by analytical queries."""

    conn.create_aggregate("median", 1, MedianAggregate)
    conn.create_aggregate("stddev", 1, StdDevAggregate)


def avg_price_by_dept(conn: sqlite3.Connection) -> pd.DataFrame:
    """Return average price per square meter by department."""

    _ensure_sqlite_functions(conn)
    query = """
        SELECT
            code_departement,
            COUNT(*) AS transaction_count,
            ROUND(AVG(price_per_m2), 2) AS avg_price_per_m2
        FROM price_transactions
        GROUP BY code_departement
        HAVING COUNT(*) >= 100
        ORDER BY avg_price_per_m2 DESC, code_departement
    """
    return pd.read_sql_query(query, conn)


def monthly_volume(conn: sqlite3.Connection) -> pd.DataFrame:
    """Compter les ventes distinctes par mois."""

    query = """
        SELECT year, month, COUNT(*) AS transaction_count
        FROM operations
        GROUP BY year, month
        ORDER BY year, month
    """

    return pd.read_sql_query(query, conn)


def price_distribution_by_type(conn: sqlite3.Connection) -> pd.DataFrame:
    """Return descriptive statistics for price per square meter by type."""

    _ensure_sqlite_functions(conn)
    query = """
        SELECT
            type_local,
            COUNT(*) AS transaction_count,
            ROUND(MIN(price_per_m2), 2) AS min_price_per_m2,
            ROUND(MAX(price_per_m2), 2) AS max_price_per_m2,
            ROUND(AVG(price_per_m2), 2) AS mean_price_per_m2,
            ROUND(median(price_per_m2), 2) AS median_price_per_m2,
            ROUND(stddev(price_per_m2), 2) AS stddev_price_per_m2
        FROM price_transactions
        GROUP BY type_local
        ORDER BY type_local
    """
    return pd.read_sql_query(query, conn)


def top10_expensive_depts(conn: sqlite3.Connection) -> pd.DataFrame:
    """Return the 10 departments with the highest median price per square meter."""

    _ensure_sqlite_functions(conn)
    query = """
        SELECT
            code_departement,
            COUNT(*) AS transaction_count,
            ROUND(median(price_per_m2), 2) AS median_price_per_m2
        FROM price_transactions
        GROUP BY code_departement
        HAVING COUNT(*) >= 100
        ORDER BY median_price_per_m2 DESC, transaction_count DESC
        LIMIT 10
    """
    return pd.read_sql_query(query, conn)


def price_vs_surface_buckets(conn: sqlite3.Connection) -> pd.DataFrame:
    """Return average price per square meter by surface bucket and property type."""

    _ensure_sqlite_functions(conn)
    query = """
        SELECT
            surface_bucket,
            type_local,
            COUNT(*) AS transaction_count,
            ROUND(AVG(price_per_m2), 2) AS avg_price_per_m2
        FROM (
            SELECT
                type_local,
                price_per_m2,
                CASE
                    WHEN surface_reelle_bati < 30 THEN '<30'
                    WHEN surface_reelle_bati < 50 THEN '30-50'
                    WHEN surface_reelle_bati < 80 THEN '50-80'
                    WHEN surface_reelle_bati < 120 THEN '80-120'
                    ELSE '120+'
                END AS surface_bucket
            FROM price_transactions
        )
        GROUP BY surface_bucket, type_local
        ORDER BY
            CASE surface_bucket
                WHEN '<30' THEN 1
                WHEN '30-50' THEN 2
                WHEN '50-80' THEN 3
                WHEN '80-120' THEN 4
                ELSE 5
            END,
            type_local
    """
    return pd.read_sql_query(query, conn)


def yoy_comparison(conn: sqlite3.Connection) -> pd.DataFrame:
    """Return eligible-price sample counts and means, yearly or monthly by type.

    With a single year this is seasonality, not a year-over-year comparison."""

    _ensure_sqlite_functions(conn)
    distinct_years = pd.read_sql_query(
        "SELECT COUNT(DISTINCT year) AS year_count FROM price_transactions",
        conn,
    )["year_count"].iloc[0]

    if distinct_years > 1:
        query = """
            SELECT
                year,
                type_local,
                COUNT(*) AS transaction_count,
                ROUND(AVG(price_per_m2), 2) AS avg_price_per_m2
            FROM price_transactions
            GROUP BY year, type_local
            ORDER BY year, type_local
        """
    else:
        query = """
            SELECT
                year,
                month,
                type_local,
                COUNT(*) AS transaction_count,
                ROUND(AVG(price_per_m2), 2) AS avg_price_per_m2
            FROM price_transactions
            GROUP BY year, month, type_local
            ORDER BY year, month, type_local
        """

    return pd.read_sql_query(query, conn)


def dept_transaction_share(conn: sqlite3.Connection) -> pd.DataFrame:
    """Calculer la part des ventes distinctes par département."""

    query = """
        SELECT code_departement, COUNT(*) AS transaction_count,
               ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)
                   AS transaction_share_pct
        FROM operations
        GROUP BY code_departement
        ORDER BY transaction_share_pct DESC, code_departement
    """

    return pd.read_sql_query(query, conn)


def rooms_vs_price(conn: sqlite3.Connection) -> pd.DataFrame:
    """Return average price metrics by room count for apartments."""

    _ensure_sqlite_functions(conn)
    query = """
        SELECT
            nombre_pieces_principales,
            COUNT(*) AS transaction_count,
            ROUND(AVG(valeur_fonciere), 2) AS avg_price,
            ROUND(AVG(price_per_m2), 2) AS avg_price_per_m2
        FROM price_transactions
        WHERE type_local = 'Appartement'
          AND nombre_pieces_principales BETWEEN 1 AND 6
        GROUP BY nombre_pieces_principales
        ORDER BY nombre_pieces_principales
    """
    return pd.read_sql_query(query, conn)


def anomaly_candidates(conn: sqlite3.Connection) -> pd.DataFrame:
    """Return transactions priced above the 95th percentile of their segment."""

    _ensure_sqlite_functions(conn)
    query = """
        WITH ranked AS (
            SELECT
                source_row,
                id_mutation,
                numero_disposition,
                code_departement,
                type_local,
                date_mutation,
                valeur_fonciere,
                surface_reelle_bati,
                nombre_pieces_principales,
                price_per_m2,
                longitude,
                latitude,
                ROW_NUMBER() OVER (
                    PARTITION BY code_departement, type_local
                    ORDER BY price_per_m2
                ) AS rn,
                COUNT(*) OVER (
                    PARTITION BY code_departement, type_local
                ) AS cnt
            FROM price_transactions
        ),
        thresholds AS (
            SELECT
                code_departement,
                type_local,
                MIN(price_per_m2) AS p95_price_per_m2
            FROM ranked
            WHERE rn >= CAST(((cnt * 95) + 99) / 100 AS INTEGER)
            GROUP BY code_departement, type_local
        )
        SELECT
            t.source_row,
            t.id_mutation,
            t.numero_disposition,
            t.code_departement,
            t.type_local,
            t.date_mutation,
            t.valeur_fonciere,
            t.surface_reelle_bati,
            t.nombre_pieces_principales,
            ROUND(t.price_per_m2, 2) AS price_per_m2,
            ROUND(th.p95_price_per_m2, 2) AS department_type_p95,
            t.longitude,
            t.latitude
        FROM price_transactions AS t
        INNER JOIN thresholds AS th
            ON t.code_departement = th.code_departement
           AND t.type_local = th.type_local
        WHERE t.price_per_m2 > th.p95_price_per_m2
        ORDER BY t.price_per_m2 DESC
        LIMIT 50
    """
    return pd.read_sql_query(query, conn)


def paris_inner_outer(conn: sqlite3.Connection) -> pd.DataFrame:
    """Return Paris average price per square meter by type and room count."""

    _ensure_sqlite_functions(conn)
    query = """
        SELECT
            type_local,
            nombre_pieces_principales,
            COUNT(*) AS transaction_count,
            ROUND(AVG(price_per_m2), 2) AS avg_price_per_m2
        FROM price_transactions
        WHERE code_departement = '75'
          AND nombre_pieces_principales IS NOT NULL
        GROUP BY type_local, nombre_pieces_principales
        ORDER BY type_local, nombre_pieces_principales
    """
    return pd.read_sql_query(query, conn)
