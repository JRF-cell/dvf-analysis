"""Tests for DVF analytical SQL queries."""

from __future__ import annotations

import sqlite3

import pandas as pd
import pytest

from dvf.database import load_to_sqlite
from dvf.queries import (
    anomaly_candidates,
    avg_price_by_dept,
    dept_transaction_share,
    monthly_volume,
    paris_inner_outer,
    price_distribution_by_type,
    price_vs_surface_buckets,
    rooms_vs_price,
    top10_expensive_depts,
    yoy_comparison,
)


def build_transactions_dataframe() -> pd.DataFrame:
    """Create a synthetic cleaned dataset for query tests."""

    rows: list[dict[str, object]] = []
    total_rows = 160

    for index in range(total_rows):
        is_paris = index < 120
        department = "75" if is_paris else "13"
        property_type = "Appartement" if index % 2 == 0 else "Maison"
        surface = 25 + (index % 90)
        price_multiplier = 1 + (index % 5) * 0.01
        if index in {18, 42, 118, 141, 155}:
            price_multiplier = 1.35

        value = (
            (11_000 if department == "75" else 4_200)
            * surface
            * price_multiplier
        )

        rows.append(
            {
                "date_mutation": f"2023-{(index % 12) + 1:02d}-{(index % 28) + 1:02d}",
                "nature_mutation": "Vente",
                "valeur_fonciere": round(value, 2),
                "code_departement": department,
                "type_local": property_type,
                "surface_reelle_bati": float(surface),
                "nombre_pieces_principales": (index % 6) + 1,
                "longitude": 2.3 if is_paris else 5.4,
                "latitude": 48.85 if is_paris else 43.29,
                "price_per_m2": round(value / surface, 2),
                "year": 2023,
                "month": (index % 12) + 1,
            }
        )

    return pd.DataFrame(rows)


def build_connection() -> sqlite3.Connection:
    """Create an in-memory SQLite database for query tests."""

    dataframe = build_transactions_dataframe()
    return load_to_sqlite(dataframe, ":memory:")


@pytest.mark.parametrize(
    ("query_func", "expected_columns"),
    [
        (
            avg_price_by_dept,
            ["code_departement", "transaction_count", "avg_price_per_m2"],
        ),
        (monthly_volume, ["year", "month", "transaction_count"]),
        (
            price_distribution_by_type,
            [
                "type_local",
                "min_price_per_m2",
                "max_price_per_m2",
                "mean_price_per_m2",
                "median_price_per_m2",
                "stddev_price_per_m2",
            ],
        ),
        (
            top10_expensive_depts,
            ["code_departement", "transaction_count", "median_price_per_m2"],
        ),
        (
            price_vs_surface_buckets,
            [
                "surface_bucket",
                "type_local",
                "transaction_count",
                "avg_price_per_m2",
            ],
        ),
        (
            yoy_comparison,
            ["year", "month", "type_local", "transaction_count", "avg_price_per_m2"],
        ),
        (
            dept_transaction_share,
            ["code_departement", "transaction_count", "transaction_share_pct"],
        ),
        (
            rooms_vs_price,
            [
                "nombre_pieces_principales",
                "transaction_count",
                "avg_price",
                "avg_price_per_m2",
            ],
        ),
        (
            anomaly_candidates,
            [
                "code_departement",
                "type_local",
                "date_mutation",
                "valeur_fonciere",
                "surface_reelle_bati",
                "nombre_pieces_principales",
                "price_per_m2",
                "department_type_p95",
                "longitude",
                "latitude",
            ],
        ),
        (
            paris_inner_outer,
            [
                "type_local",
                "nombre_pieces_principales",
                "transaction_count",
                "avg_price_per_m2",
            ],
        ),
    ],
)
def test_queries_return_non_empty_dataframes_with_expected_columns(
    query_func,
    expected_columns,
) -> None:
    """Every analytical query should return data with the documented schema."""

    conn = build_connection()
    try:
        result = query_func(conn)
    finally:
        conn.close()

    assert not result.empty
    assert list(result.columns) == expected_columns
