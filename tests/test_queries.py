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

        value = (11_000 if department == "75" else 4_200) * surface * price_multiplier

        rows.append(
            {
                "source_row": index + 1,
                "id_mutation": f"TEST-{index:05d}",
                "raw_mutation_rows": 1,
                "raw_operation_rows": 1,
                "price_eligible": True,
                "numero_disposition": 1,
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
                "transaction_count",
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
                "source_row",
                "id_mutation",
                "numero_disposition",
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


def test_monthly_volume_counts_unique_sales() -> None:
    """Une vente sur deux lignes ne compte qu'une fois."""

    dataframe = build_transactions_dataframe()

    # Dupliquer une ligne pour simuler une vente multiligne.
    dataframe = pd.concat(
        [dataframe, dataframe.iloc[[0]]],
        ignore_index=True,
    )

    duplicated = dataframe.id_mutation.eq("TEST-00000")
    dataframe.loc[duplicated, "raw_mutation_rows"] = 2
    dataframe.loc[duplicated, "raw_operation_rows"] = 2
    dataframe.loc[duplicated, "price_eligible"] = False
    dataframe.loc[duplicated, "price_per_m2"] = None
    conn = load_to_sqlite(dataframe, ":memory:")

    try:
        result = monthly_volume(conn)
    finally:
        conn.close()

    # 161 lignes, mais seulement 160 ventes distinctes.
    assert len(dataframe) == 161
    assert result["transaction_count"].sum() == 160


PRICE_QUERIES = [
    avg_price_by_dept,
    price_distribution_by_type,
    top10_expensive_depts,
    price_vs_surface_buckets,
    yoy_comparison,
    rooms_vs_price,
    anomaly_candidates,
    paris_inner_outer,
]


@pytest.mark.parametrize("query", PRICE_QUERIES)
def test_every_price_query_excludes_unsafe_operations(query):
    baseline = build_transactions_dataframe()
    unsafe = baseline.iloc[[0]].copy()
    unsafe["id_mutation"] = "UNSAFE"
    unsafe["raw_mutation_rows"] = 2
    unsafe["raw_operation_rows"] = 2
    unsafe["price_eligible"] = False
    unsafe["price_per_m2"] = 1e9
    unsafe["valeur_fonciere"] = 1e12
    expected_conn = load_to_sqlite(baseline, ":memory:")
    actual_conn = load_to_sqlite(pd.concat([baseline, unsafe, unsafe]), ":memory:")
    try:
        pd.testing.assert_frame_equal(query(expected_conn), query(actual_conn))
    finally:
        expected_conn.close()
        actual_conn.close()


def test_department_share_counts_distinct_operations_and_multiple_dispositions():
    from dvf.clean import clean_dataframe
    from tests.test_clean import source_row

    rows = clean_dataframe(
        pd.DataFrame(
            [
                source_row("A"),
                source_row("A", type_local="Dépendance"),
                source_row("A", numero_disposition=2),
                source_row("B", code_departement="75"),
            ]
        )
    )
    conn = load_to_sqlite(rows, ":memory:")
    try:
        shares = dept_transaction_share(conn).set_index("code_departement")
        assert shares.loc["01", "transaction_count"] == 2
        assert shares.loc["75", "transaction_count"] == 1
        assert shares.loc["01", "transaction_share_pct"] == 66.67
        assert monthly_volume(conn).transaction_count.sum() == 3
    finally:
        conn.close()


def test_yoy_uses_years_when_multiple_years_are_present():
    rows = build_transactions_dataframe()
    second_year = rows.copy()
    second_year["id_mutation"] += "-2024"
    second_year["year"] = 2024
    second_year["date_mutation"] = second_year.date_mutation.str.replace("2023", "2024")
    conn = load_to_sqlite(pd.concat([rows, second_year]), ":memory:")
    try:
        result = yoy_comparison(conn)
        assert "month" not in result
        assert result.transaction_count.sum() == 320
        assert result.year.tolist() == [2023, 2023, 2024, 2024]
    finally:
        conn.close()


def test_sql_price_results_have_expected_values():
    from dvf.clean import clean_dataframe
    from tests.test_clean import source_row

    rows = clean_dataframe(
        pd.DataFrame(
            [source_row(str(i), valeur_fonciere=200000) for i in range(100)]
            + [source_row(str(i), valeur_fonciere=400000) for i in range(100, 200)]
        )
    )
    conn = load_to_sqlite(rows, ":memory:")
    try:
        stats = price_distribution_by_type(conn).iloc[0]
        assert stats.mean_price_per_m2 == 3000
        assert stats.median_price_per_m2 == 3000
        assert stats.stddev_price_per_m2 == 1002.51
        assert avg_price_by_dept(conn).transaction_count.tolist() == [200]
        assert top10_expensive_depts(conn).median_price_per_m2.tolist() == [3000]
    finally:
        conn.close()
