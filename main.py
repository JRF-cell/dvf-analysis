"""Command line interface for the DVF analysis project."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sqlite3
from contextlib import closing
from pathlib import Path

import pandas as pd

from dvf.clean import OPERATION_KEY, clean_with_audit, load_raw_dataframe
from dvf.database import load_to_sqlite
from dvf.download import download_data
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
from dvf.visualize import generate_all_figures

DATA_URL = "https://files.data.gouv.fr/geo-dvf/latest/csv/2023/full.csv.gz"
DATA_DIR = Path("data")
ARCHIVE_PATH = DATA_DIR / "full.csv.gz"
CSV_PATH = DATA_DIR / "full.csv"
DB_PATH = DATA_DIR / "dvf.db"


def parse_args() -> argparse.Namespace:
    """Build the CLI arguments parser."""

    parser = argparse.ArgumentParser(description="DVF analysis pipeline")
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download and decompress the DVF dataset.",
    )
    parser.add_argument(
        "--load",
        action="store_true",
        help="Clean the CSV and load it into SQLite.",
    )
    parser.add_argument(
        "--query",
        action="store_true",
        help="Run the analytical SQL queries and print samples.",
    )
    parser.add_argument(
        "--viz",
        action="store_true",
        help="Generate all figures in outputs/.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run the complete pipeline in order.",
    )
    return parser.parse_args()


def run_download() -> Path:
    """Download the DVF archive and return the CSV path."""

    return download_data(DATA_URL, ARCHIVE_PATH)


def run_load() -> sqlite3.Connection:
    """Load the cleaned DVF data into SQLite."""

    if not CSV_PATH.exists():
        if ARCHIVE_PATH.exists():
            download_data(DATA_URL, ARCHIVE_PATH)
        else:
            raise FileNotFoundError(
                "Missing raw CSV archive. Run `python main.py --download` first."
            )

    if not CSV_PATH.exists():
        raise FileNotFoundError(
            f"Missing raw CSV at {CSV_PATH}. Run `python main.py --download` first."
        )

    raw_df = load_raw_dataframe(CSV_PATH)
    cleaned_df, audit = clean_with_audit(raw_df)
    connection = load_to_sqlite(cleaned_df, DB_PATH, audit=audit)
    try:
        write_quality_report(cleaned_df, audit, connection)
    except Exception:
        connection.close()
        raise
    operation_count = connection.execute("SELECT COUNT(*) FROM operations").fetchone()[
        0
    ]
    print(
        f"Loaded {len(cleaned_df):,} residential source rows, "
        f"{operation_count:,} distinct operations and "
        f"{int(cleaned_df.price_eligible.sum()):,} eligible prices into {DB_PATH}."
    )
    return connection


def write_quality_report(
    rows: pd.DataFrame, audit: pd.DataFrame, connection: sqlite3.Connection
) -> None:
    """Publish aggregate checks and source fingerprint, without source addresses."""
    digest = hashlib.sha256()
    with CSV_PATH.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    candidates = rows[rows.candidate_price_per_m2.notna()]
    bounds = (
        candidates.groupby("type_local")
        .agg(
            candidates=("candidate_price_per_m2", "size"),
            lower_bound=("price_lower_bound", "min"),
            upper_bound=("price_upper_bound", "max"),
        )
        .reset_index()
    )
    report = {
        "source": {
            "url": DATA_URL,
            "file": str(CSV_PATH),
            "bytes": CSV_PATH.stat().st_size,
            "sha256": digest.hexdigest(),
        },
        "runtime": {
            "python": platform.python_version(),
            "pandas": pd.__version__,
            "sqlite": sqlite3.sqlite_version,
        },
        "raw_rows": len(audit),
        "raw_operations_with_valid_keys": len(
            audit.dropna(subset=OPERATION_KEY).drop_duplicates(OPERATION_KEY)
        ),
        "retained_rows": len(rows),
        "volume_operations": int(monthly_volume(connection).transaction_count.sum()),
        "price_candidates": len(candidates),
        "price_eligible_operations": int(rows.price_eligible.sum()),
        "volume_exclusions": audit.volume_exclusion_reason.replace("", "retained")
        .value_counts()
        .to_dict(),
        "price_exclusions": audit.price_exclusion_reason.replace("", "eligible")
        .value_counts()
        .to_dict(),
        "price_bounds_by_type": bounds.to_dict(orient="records"),
        "monthly_volume": monthly_volume(connection).to_dict(orient="records"),
        "price_distribution": price_distribution_by_type(connection).to_dict(
            orient="records"
        ),
        "mean_price_per_m2": connection.execute(
            "SELECT AVG(price_per_m2) FROM price_transactions"
        ).fetchone()[0],
        "sqlite_integrity": connection.execute("PRAGMA integrity_check").fetchone()[0],
    }
    destination = Path("outputs/quality_report.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(".json.part")
    partial.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    partial.replace(destination)


def run_queries() -> None:
    """Run all analytical queries and print five-row samples."""

    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Missing SQLite database at {DB_PATH}. Run `python main.py --load` first."
        )

    query_functions = {
        "avg_price_by_dept": avg_price_by_dept,
        "monthly_volume": monthly_volume,
        "price_distribution_by_type": price_distribution_by_type,
        "top10_expensive_depts": top10_expensive_depts,
        "price_vs_surface_buckets": price_vs_surface_buckets,
        "yoy_comparison": yoy_comparison,
        "dept_transaction_share": dept_transaction_share,
        "rooms_vs_price": rooms_vs_price,
        "anomaly_candidates": anomaly_candidates,
        "paris_inner_outer": paris_inner_outer,
    }

    with closing(sqlite3.connect(DB_PATH)) as connection:
        for name, function in query_functions.items():
            result = function(connection)
            print(f"\n=== {name} ===")
            if result.empty:
                print("No rows returned.")
                continue
            print(result.head(5).to_string(index=False))


def run_visualizations() -> None:
    """Generate all figures in the outputs directory."""

    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Missing SQLite database at {DB_PATH}. Run `python main.py --load` first."
        )

    with closing(sqlite3.connect(DB_PATH)) as connection:
        generated = generate_all_figures(connection, "outputs/")

    for figure_path in generated:
        print(f"Saved figure: {figure_path}")


def main() -> None:
    """Run the DVF CLI entrypoint."""

    args = parse_args()
    selected_actions = [
        args.download,
        args.load,
        args.query,
        args.viz,
        args.all,
    ]
    if not any(selected_actions):
        raise SystemExit(
            "No action selected. Use --download, --load, --query, --viz or --all."
        )

    if args.all:
        run_download()
        connection = run_load()
        connection.close()
        run_queries()
        run_visualizations()
        return

    if args.download:
        run_download()

    connection: sqlite3.Connection | None = None
    if args.load:
        connection = run_load()

    if connection is not None:
        connection.close()

    if args.query:
        run_queries()

    if args.viz:
        run_visualizations()


if __name__ == "__main__":
    main()
