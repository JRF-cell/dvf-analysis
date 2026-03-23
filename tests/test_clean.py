"""Tests for DVF dataframe cleaning."""

from __future__ import annotations

import pandas as pd

from dvf.clean import clean_dataframe


def build_raw_dataframe() -> pd.DataFrame:
    """Create a synthetic raw DVF-like dataframe."""

    rows: list[dict[str, object]] = []
    for index in range(20):
        rows.append(
            {
                "date_mutation": f"{(index % 28) + 1:02d}/01/2023",
                "nature_mutation": "Vente",
                "valeur_fonciere": 100_000 + (index * 5_000),
                "code_departement": "75" if index % 2 == 0 else "13",
                "type_local": "Appartement" if index % 3 else "Maison",
                "surface_reelle_bati": 25 + index,
                "nombre_pieces_principales": (index % 5) + 1,
                "longitude": 2.2 + (index * 0.01),
                "latitude": 48.8 + (index * 0.01),
            }
        )

    rows[1]["valeur_fonciere"] = None
    rows[2]["valeur_fonciere"] = 0
    rows[3]["surface_reelle_bati"] = None
    rows[4]["surface_reelle_bati"] = -10
    rows[5]["type_local"] = "Dépendance"
    rows[6]["nature_mutation"] = "Echange"

    return pd.DataFrame(rows)


def test_clean_dataframe_filters_and_enriches_rows() -> None:
    """clean_dataframe should drop invalid rows and add price_per_m2."""

    raw_df = build_raw_dataframe()
    cleaned_df = clean_dataframe(raw_df)

    assert not cleaned_df.empty
    assert cleaned_df["valeur_fonciere"].notna().all()
    assert (cleaned_df["valeur_fonciere"] > 0).all()
    assert cleaned_df["surface_reelle_bati"].notna().all()
    assert (cleaned_df["surface_reelle_bati"] > 0).all()
    assert cleaned_df["type_local"].isin(["Maison", "Appartement"]).all()
    assert (cleaned_df["nature_mutation"] == "Vente").all()
    assert "price_per_m2" in cleaned_df.columns
    assert cleaned_df["price_per_m2"].gt(0).all()
    assert {"year", "month"}.issubset(cleaned_df.columns)
