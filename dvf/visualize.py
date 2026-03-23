"""Visualization helpers for the DVF analysis project."""

from __future__ import annotations

from pathlib import Path
import sqlite3

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

import dvf.queries as queries


def _save_figure(output_path: Path) -> None:
    """Apply layout optimizations and save the current matplotlib figure."""

    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()


def generate_all_figures(
    conn: sqlite3.Connection,
    output_dir: str | Path = "outputs/",
) -> list[Path]:
    """Generate all project figures and save them to disk."""

    sns.set_theme(style="whitegrid", palette="deep")
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    generated_paths: list[Path] = []

    avg_dept = queries.avg_price_by_dept(conn).head(20).sort_values(
        "avg_price_per_m2"
    )
    plt.figure(figsize=(12, 6))
    sns.barplot(data=avg_dept, x="avg_price_per_m2", y="code_departement")
    plt.title("Top 20 des départements par prix moyen au m²")
    plt.xlabel("Prix moyen au m² (EUR)")
    plt.ylabel("Code département")
    output_path = destination / "fig1_avg_price_by_dept.png"
    _save_figure(output_path)
    generated_paths.append(output_path)

    monthly = queries.monthly_volume(conn).copy()
    monthly["period"] = monthly["year"].astype(str) + "-" + monthly[
        "month"
    ].astype(str).str.zfill(2)
    plt.figure(figsize=(12, 6))
    sns.lineplot(data=monthly, x="period", y="transaction_count", marker="o")
    plt.title("Volume mensuel des transactions DVF")
    plt.xlabel("Période")
    plt.ylabel("Nombre de transactions")
    plt.xticks(rotation=45, ha="right")
    output_path = destination / "fig2_monthly_volume.png"
    _save_figure(output_path)
    generated_paths.append(output_path)

    distribution = pd.read_sql_query(
        """
        SELECT type_local, price_per_m2
        FROM transactions
        WHERE type_local IN ('Maison', 'Appartement')
        """,
        conn,
    )
    plt.figure(figsize=(12, 6))
    sns.boxplot(data=distribution, x="type_local", y="price_per_m2")
    plt.title("Distribution du prix au m² par type de bien")
    plt.xlabel("Type de bien")
    plt.ylabel("Prix au m² (EUR)")
    plt.ylim(0, 15000)
    output_path = destination / "fig3_price_distribution.png"
    _save_figure(output_path)
    generated_paths.append(output_path)

    surface_buckets = queries.price_vs_surface_buckets(conn)
    plt.figure(figsize=(12, 6))
    sns.barplot(
        data=surface_buckets,
        x="surface_bucket",
        y="avg_price_per_m2",
        hue="type_local",
    )
    plt.title("Prix moyen au m² par tranche de surface")
    plt.xlabel("Tranche de surface bâtie (m²)")
    plt.ylabel("Prix moyen au m² (EUR)")
    output_path = destination / "fig4_surface_buckets.png"
    _save_figure(output_path)
    generated_paths.append(output_path)

    paris_rooms = queries.paris_inner_outer(conn)
    paris_rooms = paris_rooms[
        paris_rooms["type_local"] == "Appartement"
    ].sort_values("nombre_pieces_principales")
    plt.figure(figsize=(12, 6))
    sns.lineplot(
        data=paris_rooms,
        x="nombre_pieces_principales",
        y="avg_price_per_m2",
        marker="o",
    )
    plt.title("Paris: prix moyen au m² des appartements par nombre de pièces")
    plt.xlabel("Nombre de pièces principales")
    plt.ylabel("Prix moyen au m² (EUR)")
    output_path = destination / "fig5_rooms_vs_price.png"
    _save_figure(output_path)
    generated_paths.append(output_path)

    return generated_paths
