"""Command line interface for the DVF analysis project."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from dvf.clean import clean_dataframe, load_raw_dataframe
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
    cleaned_df = clean_dataframe(raw_df)
    connection = load_to_sqlite(cleaned_df, DB_PATH)
    print(
        f"Loaded {len(cleaned_df):,} cleaned transactions into SQLite at {DB_PATH}."
    )
    return connection


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

    with sqlite3.connect(DB_PATH) as connection:
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

    with sqlite3.connect(DB_PATH) as connection:
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
