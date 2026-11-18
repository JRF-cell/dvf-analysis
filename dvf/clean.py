"""Normalize DVF source rows and keep an auditable, conservative price scope."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pandas as pd

OPERATION_KEY = ["id_mutation", "numero_disposition"]
LOT_COLUMNS = [f"lot{i}_numero" for i in range(1, 6)]
NUMERIC_COLUMNS = [
    "valeur_fonciere",
    "surface_reelle_bati",
    "nombre_pieces_principales",
    "longitude",
    "latitude",
    "code_type_local",
    "nombre_lots",
    "surface_terrain",
]
REQUIRED_COLUMNS = set(
    OPERATION_KEY
    + LOT_COLUMNS
    + [
        "date_mutation",
        "nature_mutation",
        "valeur_fonciere",
        "code_departement",
        "type_local",
        "code_type_local",
        "surface_reelle_bati",
        "nombre_pieces_principales",
        "nombre_lots",
        "numero_volume",
        "id_parcelle",
    ]
)


def load_raw_dataframe(csv_path: str | Path) -> pd.DataFrame:
    """Read identifiers as strings, including leading zeros, before conversion."""
    path = Path(csv_path)
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        sample = handle.read(4096)
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters="|,;\t").delimiter
    except csv.Error:
        delimiter = ","
    identifiers = dict.fromkeys(
        [
            *OPERATION_KEY,
            *LOT_COLUMNS,
            "code_departement",
            "code_commune",
            "code_postal",
            "id_parcelle",
            "adresse_code_voie",
            "numero_volume",
        ],
        "string",
    )
    for encoding in ("utf-8", "latin1"):
        try:
            return pd.read_csv(
                path,
                sep=delimiter,
                dtype=identifiers,
                low_memory=False,
                encoding=encoding,
            )
        except UnicodeDecodeError:
            if encoding == "latin1":
                raise
    raise AssertionError("No CSV encoding selected")


def _parse_dates(values: pd.Series) -> pd.Series:
    """Parse ISO and French dates explicitly, never guessing month/day order."""
    if pd.api.types.is_datetime64_any_dtype(values):
        return values.dt.normalize()
    text = values.astype("string").str.strip()
    iso = pd.to_datetime(
        text.where(text.str.fullmatch(r"\d{4}-\d{2}-\d{2}")),
        format="%Y-%m-%d",
        errors="coerce",
    )
    french = pd.to_datetime(
        text.where(text.str.fullmatch(r"\d{2}/\d{2}/\d{4}")),
        format="%d/%m/%Y",
        errors="coerce",
    )
    return iso.fillna(french)


def clean_with_audit(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return residential rows and one audit record per source row (1-based).

    An operation is (id_mutation, numero_disposition), not a property. Prices
    require a single source row for the entire mutation and conservative lot
    checks. Percentiles affect price eligibility only, never volume counts.
    Reasons are mutually exclusive, in the priority order below.
    """
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Missing DVF columns: {', '.join(sorted(missing))}")
    rows = df.copy().reset_index(drop=True)
    rows["source_row"] = np.arange(1, len(rows) + 1)
    for column in [
        "id_mutation",
        "code_departement",
        "id_parcelle",
        "numero_volume",
        "type_local",
        "nature_mutation",
        *LOT_COLUMNS,
    ]:
        rows[column] = rows[column].astype("string").str.strip().replace("", pd.NA)
    disposition = pd.to_numeric(rows["numero_disposition"], errors="coerce")
    valid_disposition = disposition.between(1, 999999) & disposition.eq(
        disposition.round()
    )
    rows["numero_disposition"] = (
        disposition.where(valid_disposition)
        .astype("Int64")
        .astype("string")
        .str.zfill(6)
    )
    for column in NUMERIC_COLUMNS:
        if column in rows:
            rows[column] = pd.to_numeric(rows[column], errors="coerce")
    rows["date_mutation"] = _parse_dates(rows["date_mutation"])

    # These counts must precede EVERY filter, including dates and dependencies.
    groups = rows.groupby(OPERATION_KEY, dropna=False, sort=False)
    rows["raw_operation_rows"] = groups["source_row"].transform("size")
    rows["raw_mutation_rows"] = rows.groupby("id_mutation", dropna=False, sort=False)[
        "source_row"
    ].transform("size")
    reason = pd.Series("", index=rows.index, dtype="string")

    def exclude(mask: pd.Series, label: str) -> None:
        reason.loc[reason.eq("") & mask.fillna(True)] = label

    exclude(rows[OPERATION_KEY].isna().any(axis=1), "invalid_operation_key")
    for column, label in [
        ("date_mutation", "date"),
        ("nature_mutation", "nature"),
        ("code_departement", "department"),
    ]:
        distinct = groups[column].transform("nunique", dropna=False)
        exclude(distinct.ne(1) | rows[column].isna(), f"invalid_operation_{label}")
    exclude(rows["nature_mutation"].ne("Vente"), "not_sale")
    exclude(~rows["type_local"].isin(["Maison", "Appartement"]), "non_residential")
    for column, label in [
        ("valeur_fonciere", "value"),
        ("surface_reelle_bati", "surface"),
    ]:
        exclude(
            ~np.isfinite(rows[column]) | rows[column].le(0) | rows[column].isna(),
            f"invalid_{label}",
        )
    rows["volume_exclusion_reason"] = reason
    in_volume = reason.eq("")

    # Continue the same priority list for price exclusions; no price allocation.
    exclude(rows["raw_operation_rows"].ne(1), "multiple_source_rows")
    exclude(rows["raw_mutation_rows"].ne(1), "multiple_dispositions")
    expected_type = rows["type_local"].map({"Maison": 1, "Appartement": 2})
    exclude(rows["code_type_local"].ne(expected_type), "inconsistent_property_type")
    exclude(rows["id_parcelle"].isna(), "missing_parcel")
    exclude(rows["numero_volume"].notna(), "volume_sale")
    lots = rows["nombre_lots"]
    exclude(~lots.isin([0, 1]), "multiple_or_unknown_lots")
    exclude(
        rows[LOT_COLUMNS].notna().sum(axis=1).ne(lots)
        | rows[LOT_COLUMNS[1:]].notna().any(axis=1),
        "inconsistent_lots",
    )
    rooms = rows["nombre_pieces_principales"]
    exclude(
        ~np.isfinite(rooms) | rooms.le(0) | rooms.ne(rooms.round()) | rooms.isna(),
        "invalid_rooms",
    )
    rows["candidate_price_per_m2"] = (
        rows["valeur_fonciere"].where(reason.eq("")) / rows["surface_reelle_bati"]
    )
    valid_ratio = np.isfinite(rows["candidate_price_per_m2"]) & rows[
        "candidate_price_per_m2"
    ].gt(0)
    exclude(~valid_ratio, "invalid_ratio")
    rows["candidate_price_per_m2"] = rows["candidate_price_per_m2"].where(valid_ratio)
    # Per-type trimming limits are recorded, including when the sample is empty.
    rows["price_lower_bound"] = float("nan")
    rows["price_upper_bound"] = float("nan")
    for property_type in ("Maison", "Appartement"):
        candidate = reason.eq("") & rows["type_local"].eq(property_type)
        prices = rows.loc[candidate, "candidate_price_per_m2"]
        if prices.empty:
            continue
        lower, upper = prices.quantile([0.01, 0.99])
        rows.loc[candidate, "price_lower_bound"] = lower
        rows.loc[candidate, "price_upper_bound"] = upper
        exclude(
            candidate & ~rows["candidate_price_per_m2"].between(lower, upper),
            "price_outlier",
        )
    rows["price_exclusion_reason"] = reason
    rows["price_eligible"] = reason.eq("")
    rows["price_per_m2"] = rows["candidate_price_per_m2"].where(rows["price_eligible"])
    rows["year"] = rows["date_mutation"].dt.year.astype("Int64")
    rows["month"] = rows["date_mutation"].dt.month.astype("Int64")
    audit = rows[
        [
            "source_row",
            *OPERATION_KEY,
            "raw_operation_rows",
            "raw_mutation_rows",
            "volume_exclusion_reason",
            "price_exclusion_reason",
        ]
    ].copy()
    return rows.loc[in_volume].copy(), audit


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Return retained rows; use clean_with_audit to persist all exclusions."""
    return clean_with_audit(df)[0]
