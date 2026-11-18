"""Regression tests for source grain, dates, exclusions and price eligibility."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from dvf.clean import LOT_COLUMNS, clean_dataframe, clean_with_audit, load_raw_dataframe


def source_row(identifier="A", **changes):
    row = {
        "id_mutation": identifier,
        "numero_disposition": "000001",
        "date_mutation": "2023-06-23",
        "nature_mutation": "Vente",
        "valeur_fonciere": 200000,
        "code_departement": "01",
        "code_commune": "01001",
        "code_postal": "01000",
        "id_parcelle": "01001000AB0001",
        "type_local": "Maison",
        "code_type_local": 1,
        "surface_reelle_bati": 100,
        "nombre_pieces_principales": 4,
        "nombre_lots": 0,
        "numero_volume": None,
        "longitude": 5.0,
        "latitude": 46.0,
        **dict.fromkeys(LOT_COLUMNS),
    }
    return row | changes


def test_clean_dataframe_filters_and_enriches_rows():
    raw = pd.DataFrame([source_row(), source_row("B", valeur_fonciere=None)])
    cleaned, audit = clean_with_audit(raw)
    assert cleaned.id_mutation.tolist() == ["A"]
    assert cleaned.price_per_m2.tolist() == [2000]
    assert cleaned.month.tolist() == [6]
    assert audit.volume_exclusion_reason.tolist() == ["", "invalid_value"]
    assert len(audit) == len(raw)
    pd.testing.assert_frame_equal(
        raw, pd.DataFrame([source_row(), source_row("B", valeur_fonciere=None)])
    )


@pytest.mark.parametrize(
    ("date", "month", "day"),
    [
        ("2023-01-05", 1, 5),
        ("2023-06-23", 6, 23),
        ("23/06/2023", 6, 23),
        (pd.Timestamp("2023-12-31"), 12, 31),
    ],
)
def test_dates_never_swap_iso_month_and_day(date, month, day):
    result = clean_dataframe(pd.DataFrame([source_row(date_mutation=date)]))
    assert result.month.tolist() == [month]
    assert result.date_mutation.dt.day.tolist() == [day]


def test_mixed_iso_french_and_invalid_dates():
    rows, audit = clean_with_audit(
        pd.DataFrame(
            [
                source_row("A", date_mutation="2023-01-05"),
                source_row("B", date_mutation="23/06/2023"),
                source_row("C", date_mutation="2023-02-30"),
            ]
        )
    )
    assert rows.month.tolist() == [1, 6]
    assert audit.iloc[2].volume_exclusion_reason == "invalid_operation_date"


@pytest.mark.parametrize(
    "companion",
    [
        {"type_local": "Dépendance", "code_type_local": 3, "surface_reelle_bati": None},
        {"type_local": "Appartement", "code_type_local": 2},
        {"valeur_fonciere": None},
        {},
    ],
)
def test_multiline_sources_cannot_become_eligible_after_filtering(companion):
    rows, audit = clean_with_audit(
        pd.DataFrame([source_row(), source_row(**companion)])
    )
    assert rows.raw_operation_rows.eq(2).all()
    assert rows.price_per_m2.isna().all()
    assert not rows.price_eligible.any()
    assert rows.price_exclusion_reason.eq("multiple_source_rows").all()
    assert audit.source_row.tolist() == [1, 2]


def test_single_line_dispositions_of_same_mutation_are_not_price_eligible():
    result = clean_dataframe(
        pd.DataFrame([source_row(), source_row(numero_disposition="000002")])
    )
    assert result.raw_operation_rows.eq(1).all()
    assert result.raw_mutation_rows.eq(2).all()
    assert result.price_exclusion_reason.eq("multiple_dispositions").all()


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"code_departement": "75"}, "invalid_operation_department"),
        ({"code_departement": None}, "invalid_operation_department"),
        ({"date_mutation": "2023-07-23"}, "invalid_operation_date"),
        ({"date_mutation": None}, "invalid_operation_date"),
        ({"nature_mutation": "Echange"}, "invalid_operation_nature"),
    ],
)
def test_conflicts_on_excluded_companion_still_quarantine_entire_operation(
    changes, reason
):
    rows, audit = clean_with_audit(
        pd.DataFrame([source_row(), source_row(type_local="Dépendance", **changes)])
    )
    assert rows.empty
    assert audit.volume_exclusion_reason.eq(reason).all()


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"id_mutation": None}, "invalid_operation_key"),
        ({"id_mutation": " "}, "invalid_operation_key"),
        ({"numero_disposition": 1.5}, "invalid_operation_key"),
        ({"numero_disposition": None}, "invalid_operation_key"),
        ({"valeur_fonciere": np.inf}, "invalid_value"),
        ({"valeur_fonciere": 0}, "invalid_value"),
        ({"surface_reelle_bati": -1}, "invalid_surface"),
        ({"surface_reelle_bati": np.inf}, "invalid_surface"),
        ({"surface_reelle_bati": None}, "invalid_surface"),
        ({"nature_mutation": "Echange"}, "not_sale"),
    ],
)
def test_invalid_rows_are_traced(changes, reason):
    rows, audit = clean_with_audit(pd.DataFrame([source_row(**changes)]))
    assert rows.empty
    assert audit.volume_exclusion_reason.tolist() == [reason]


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        (
            {"nombre_lots": 2, "lot1_numero": "1", "lot2_numero": "2"},
            "multiple_or_unknown_lots",
        ),
        ({"nombre_lots": None}, "multiple_or_unknown_lots"),
        ({"nombre_lots": 1}, "inconsistent_lots"),
        ({"lot2_numero": "2"}, "inconsistent_lots"),
        ({"code_type_local": 2}, "inconsistent_property_type"),
        ({"code_type_local": None}, "inconsistent_property_type"),
        ({"numero_volume": "1"}, "volume_sale"),
        ({"id_parcelle": ""}, "missing_parcel"),
        ({"nombre_pieces_principales": None}, "invalid_rooms"),
        ({"nombre_pieces_principales": 0}, "invalid_rooms"),
        ({"nombre_pieces_principales": 1.5}, "invalid_rooms"),
    ],
)
def test_monoline_is_not_a_guarantee_of_price_eligibility(changes, reason):
    rows, audit = clean_with_audit(pd.DataFrame([source_row(**changes)]))
    assert len(rows) == 1  # still contributes to volume
    assert rows.price_per_m2.isna().all()
    assert audit.price_exclusion_reason.tolist() == [reason]


def test_one_documented_lot_is_accepted():
    result = clean_dataframe(
        pd.DataFrame([source_row(nombre_lots=1, lot1_numero="01")])
    )
    assert result.price_eligible.all()


def test_price_outliers_do_not_reduce_volume_and_types_have_separate_bounds():
    raw = pd.DataFrame(
        [
            source_row(str(i), valeur_fonciere=100000 if i < 100 else 999000000)
            for i in range(101)
        ]
        + [
            source_row(
                "flat",
                type_local="Appartement",
                code_type_local=2,
                valeur_fonciere=800000,
            )
        ]
    )
    rows, audit = clean_with_audit(raw)
    assert len(rows) == 102
    assert rows.price_eligible.sum() == 101
    assert rows.loc[rows.id_mutation.eq("100"), "price_per_m2"].isna().all()
    assert audit.iloc[100].price_exclusion_reason == "price_outlier"
    assert rows.iloc[-1].price_per_m2 == 8000


def test_empty_frame_and_missing_schema():
    rows, audit = clean_with_audit(pd.DataFrame([source_row()]).iloc[:0])
    assert rows.empty and audit.empty
    assert "price_eligible" in rows
    with pytest.raises(ValueError, match="Missing DVF columns"):
        clean_dataframe(pd.DataFrame({"id_mutation": []}))


def test_csv_identifiers_preserve_leading_zeros_and_french_delimiter(tmp_path):
    path = tmp_path / "raw.csv"
    pd.DataFrame([source_row()]).to_csv(path, index=False, sep=";")
    raw = load_raw_dataframe(path)
    assert raw.numero_disposition.iloc[0] == "000001"
    assert raw.code_departement.iloc[0] == "01"
    assert raw.code_postal.iloc[0] == "01000"


@pytest.mark.parametrize(("value", "surface"), [(1e308, 1e-300), (1e-300, 1e308)])
def test_unrepresentable_ratio_is_excluded_without_affecting_volume(value, surface):
    rows, audit = clean_with_audit(
        pd.DataFrame([source_row(valeur_fonciere=value, surface_reelle_bati=surface)])
    )
    assert len(rows) == 1
    assert rows.candidate_price_per_m2.isna().all()
    assert rows.price_per_m2.isna().all()
    assert not rows.price_eligible.any()
    assert audit.price_exclusion_reason.tolist() == ["invalid_ratio"]
