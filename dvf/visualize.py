"""Visualization helpers for the DVF analysis project."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from dvf import queries


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

    avg_dept = queries.avg_price_by_dept(conn).head(20).sort_values("avg_price_per_m2")
    plt.figure(figsize=(12, 6))
    if not avg_dept.empty:
        sns.barplot(data=avg_dept, x="avg_price_per_m2", y="code_departement")
    else:
        plt.text(
            0.5, 0.5, "Aucun département avec au moins 100 observations", ha="center"
        )
    plt.title(
        "Top 20 des départements par prix moyen au m²\nÉchantillon monoligne contrôlé · au moins 100 observations"
    )
    plt.xlabel("Prix moyen au m² (EUR)")
    plt.ylabel("Code département")
    output_path = destination / "fig1_avg_price_by_dept.png"
    _save_figure(output_path)
    generated_paths.append(output_path)

    monthly = queries.monthly_volume(conn).copy()
    monthly["period"] = (
        monthly["year"].astype(str) + "-" + monthly["month"].astype(str).str.zfill(2)
    )
    plt.figure(figsize=(12, 6))
    sns.lineplot(data=monthly, x="period", y="transaction_count", marker="o")
    plt.title("Volume mensuel des opérations résidentielles retenues")
    plt.xlabel("Période")
    plt.ylabel("Nombre de mutations/dispositions distinctes")
    plt.xticks(rotation=45, ha="right")
    output_path = destination / "fig2_monthly_volume.png"
    _save_figure(output_path)
    generated_paths.append(output_path)

    distribution = pd.read_sql_query(
        """
        SELECT type_local, price_per_m2
        FROM price_transactions
        WHERE type_local IN ('Maison', 'Appartement')
        """,
        conn,
    )
    plt.figure(figsize=(12, 6))
    if not distribution.empty:
        types = sorted(distribution.type_local.unique())
        plt.boxplot(
            [
                distribution.loc[distribution.type_local.eq(kind), "price_per_m2"]
                for kind in types
            ]
        )
        plt.xticks(range(1, len(types) + 1), types)
    else:
        plt.text(0.5, 0.5, "Aucun prix éligible", ha="center")
    plt.title(
        "Distribution du prix au m² par type de bien\nÉchantillon monoligne contrôlé"
    )
    plt.xlabel("Type de bien")
    plt.ylabel("Prix au m² (EUR)")

    output_path = destination / "fig3_price_distribution.png"
    _save_figure(output_path)
    generated_paths.append(output_path)

    surface_buckets = queries.price_vs_surface_buckets(conn)
    plt.figure(figsize=(12, 6))
    if not surface_buckets.empty:
        sns.barplot(
            data=surface_buckets,
            x="surface_bucket",
            y="avg_price_per_m2",
            hue="type_local",
        )
    else:
        plt.text(0.5, 0.5, "Aucun prix éligible", ha="center")
    plt.title("Prix moyen au m² par tranche de surface\nÉchantillon monoligne contrôlé")
    plt.xlabel("Tranche de surface bâtie (m²)")
    plt.ylabel("Prix moyen au m² (EUR)")
    output_path = destination / "fig4_surface_buckets.png"
    _save_figure(output_path)
    generated_paths.append(output_path)

    paris_rooms = queries.paris_inner_outer(conn)
    paris_rooms = paris_rooms[
        (paris_rooms["type_local"] == "Appartement")
        & (paris_rooms["transaction_count"] >= 30)
    ].sort_values("nombre_pieces_principales")
    plt.figure(figsize=(12, 6))
    sns.lineplot(
        data=paris_rooms,
        x="nombre_pieces_principales",
        y="avg_price_per_m2",
        marker="o",
    )
    for row in paris_rooms.itertuples():
        plt.annotate(
            f"n={row.transaction_count}",
            (row.nombre_pieces_principales, row.avg_price_per_m2),
            xytext=(0, 10),
            textcoords="offset points",
            ha="center",
        )
    plt.xticks(paris_rooms["nombre_pieces_principales"].tolist())
    plt.margins(y=0.15)
    plt.title(
        "Paris : prix moyen au m² des appartements par nombre de pièces\n"
        "Échantillon monoligne contrôlé · groupes d’au moins 30 observations"
    )
    plt.xlabel("Nombre de pièces principales")
    plt.ylabel("Prix moyen au m² (EUR)")
    output_path = destination / "fig5_rooms_vs_price.png"
    _save_figure(output_path)
    generated_paths.append(output_path)

    return generated_paths
