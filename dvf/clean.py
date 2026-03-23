"""Cleaning helpers for the DVF dataset."""

from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd


NUMERIC_COLUMNS = [
    "valeur_fonciere",
    "surface_reelle_bati",
    "nombre_pieces_principales",
    "longitude",
    "latitude",
]


def load_raw_dataframe(csv_path: str | Path) -> pd.DataFrame:
    """Load the raw DVF CSV with pandas and fallback encodings."""

    path = Path(csv_path)
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        sample = handle.read(4096)

    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters="|,;\t").delimiter
    except csv.Error:
        delimiter = ","

    try:
        return pd.read_csv(
            path,
            sep=delimiter,
            low_memory=False,
            encoding="utf-8",
        )
    except UnicodeDecodeError:
        return pd.read_csv(
            path,
            sep=delimiter,
            low_memory=False,
            encoding="latin1",
        )


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Clean the DVF raw dataframe and enrich it with analysis columns."""

    cleaned = df.copy()

    for column in NUMERIC_COLUMNS:
        if column in cleaned.columns:
            cleaned[column] = pd.to_numeric(cleaned[column], errors="coerce")

    cleaned["date_mutation"] = pd.to_datetime(
        cleaned["date_mutation"],
        errors="coerce",
        dayfirst=True,
    )

    cleaned = cleaned.dropna(subset=["date_mutation", "valeur_fonciere"])
    cleaned = cleaned[cleaned["valeur_fonciere"] > 0]
    cleaned = cleaned.dropna(subset=["surface_reelle_bati"])
    cleaned = cleaned[cleaned["surface_reelle_bati"] > 0]
    cleaned = cleaned[cleaned["nature_mutation"] == "Vente"]
    cleaned = cleaned[cleaned["type_local"].isin(["Maison", "Appartement"])]

    cleaned = cleaned.copy()
    cleaned["price_per_m2"] = (
        cleaned["valeur_fonciere"] / cleaned["surface_reelle_bati"]
    )

    if cleaned.empty:
        cleaned["year"] = pd.Series(dtype="int64")
        cleaned["month"] = pd.Series(dtype="int64")
        return cleaned

    lower_bound = cleaned["price_per_m2"].quantile(0.01)
    upper_bound = cleaned["price_per_m2"].quantile(0.99)
    cleaned = cleaned[
        cleaned["price_per_m2"].between(lower_bound, upper_bound, inclusive="both")
    ].copy()

    cleaned["year"] = cleaned["date_mutation"].dt.year.astype("int64")
    cleaned["month"] = cleaned["date_mutation"].dt.month.astype("int64")

    return cleaned
