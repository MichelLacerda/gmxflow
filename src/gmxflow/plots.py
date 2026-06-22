from __future__ import annotations

import os
import tempfile
from pathlib import Path

import numpy as np
from pydantic import BaseModel

from gmxflow.config import GmxFlowConfig

_matplotlib_cache = Path(tempfile.gettempdir()) / "gmxflow-matplotlib"
_matplotlib_cache.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_matplotlib_cache))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402


class PlotResult(BaseModel):
    name: str
    output_path: Path


def generate_analysis_plots(
    config: GmxFlowConfig,
    project_root: Path,
) -> list[PlotResult]:
    project_root = project_root.expanduser().resolve()
    analysis = project_root / "work" / "analysis"
    title = config.project.description or config.project.name

    datasets = {
        "rmsd_bb": _load_xvg(analysis / "rmsd_backbone.xvg"),
        "rmsd_lig": _load_xvg(analysis / "rmsd_ligante.xvg"),
        "rmsf": _load_xvg(analysis / "rmsf_residuos.xvg"),
        "rg": _load_xvg(analysis / "gyrate.xvg"),
        "ncont": _load_xvg(analysis / "numcont.xvg"),
        "hbond": _load_xvg(analysis / "hbond.xvg"),
        "sasa_receptor": _load_xvg(analysis / "sasa_receptor.xvg"),
        "sasa_complexo": _load_xvg(analysis / "sasa_complexo.xvg"),
        "sasa_ligante": _load_xvg(analysis / "sasa_ligante.xvg"),
        "bsa": _load_xvg(analysis / "bsa.xvg"),
        "catalytic_distance": _load_xvg(analysis / "catalytic_distance.xvg"),
        "catalytic_occupancy": _load_xvg(analysis / "catalytic_occupancy.xvg"),
    }

    results = [_plot_panel(analysis, title, datasets, config)]
    results.extend(_plot_individuals(analysis, datasets, config))
    return results


def _load_xvg(path: Path) -> np.ndarray | None:
    if not path.is_file():
        return None

    rows: list[list[float]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(("#", "@")):
            continue
        try:
            rows.append([float(value) for value in line.split()])
        except ValueError:
            continue
    if not rows:
        return None
    return np.array(rows)


def _plot_panel(
    analysis: Path,
    title: str,
    datasets: dict[str, np.ndarray | None],
    config: GmxFlowConfig,
) -> PlotResult:
    fig, axes = plt.subplots(4, 2, figsize=(14, 15))
    fig.suptitle(title, fontsize=14, fontweight="bold")

    rmsd_bb = datasets["rmsd_bb"]
    mean = float(rmsd_bb[:, 1].mean()) if rmsd_bb is not None else None
    _plot_line(
        axes[0, 0],
        rmsd_bb,
        ylabel="RMSD (nm)",
        color=config.plots.receptor_color,
        title="RMSD do Backbone",
        hline=mean,
        config=config,
    )
    _plot_line(
        axes[0, 1],
        datasets["rmsd_lig"],
        ylabel="RMSD (nm)",
        color=config.plots.ligand_color,
        title="RMSD do Ligante",
        config=config,
    )
    _plot_rmsf(axes[1, 0], datasets["rmsf"])
    _plot_line(
        axes[1, 1],
        datasets["rg"],
        ylabel="Rg (nm)",
        color=config.plots.receptor_color,
        title="Raio de Giro",
        config=config,
    )
    _plot_line(
        axes[2, 0],
        datasets["ncont"],
        ylabel="N. atomos",
        color=config.plots.receptor_color,
        title="Contatos receptor-ligante",
        config=config,
    )
    _plot_line(
        axes[2, 1],
        datasets["hbond"],
        ylabel="N. H-bonds",
        color=config.plots.ligand_color,
        title="Pontes de hidrogenio receptor-ligante",
        config=config,
    )
    if not _plot_sasa_receptor_ligand(axes[3, 0], datasets, config):
        _plot_missing(axes[3, 0], "(sasa nao encontrado)")
    _plot_catalytic_distance(axes[3, 1], datasets["catalytic_distance"], config)

    output = analysis / "painel_completo.png"
    fig.tight_layout()
    fig.savefig(output, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return PlotResult(name="painel_completo", output_path=output)


def _plot_individuals(
    analysis: Path,
    datasets: dict[str, np.ndarray | None],
    config: GmxFlowConfig,
) -> list[PlotResult]:
    results: list[PlotResult] = []
    specs = {
        "rmsd_bb": ("RMSD do Backbone", "RMSD (nm)", config.plots.receptor_color),
        "rmsd_lig": ("RMSD do Ligante", "RMSD (nm)", config.plots.ligand_color),
        "rg": ("Raio de Giro", "Rg (nm)", config.plots.receptor_color),
        "ncont": (
            "Contatos receptor-ligante",
            "N. atomos",
            config.plots.receptor_color,
        ),
        "hbond": (
            "Pontes de hidrogenio receptor-ligante",
            "N. H-bonds",
            config.plots.ligand_color,
        ),
        "sasa_ligante": ("SASA do ligante", "SASA (nm^2)", config.plots.ligand_color),
        "bsa": (
            "Enterramento receptor-ligante",
            "BSA (nm^2)",
            config.plots.receptor_color,
        ),
    }
    ordered_names = [
        "rmsd_bb",
        "rmsd_lig",
        "rmsf",
        "rg",
        "ncont",
        "hbond",
        "sasa_complexo",
        "sasa_ligante",
        "bsa",
        "catalytic_distance",
        "catalytic_occupancy",
    ]

    for name in ordered_names:
        data = datasets.get(name)
        if data is None and name not in {"sasa_complexo"}:
            continue
        fig, ax = plt.subplots(figsize=(9, 5))
        if name == "rmsf":
            _plot_rmsf(ax, data)
        elif name == "sasa_complexo":
            plotted = _plot_sasa_receptor_ligand(ax, datasets, config)
            if not plotted:
                plt.close(fig)
                continue
        elif name == "catalytic_distance":
            _plot_catalytic_distance(ax, data, config)
        elif name == "catalytic_occupancy":
            _plot_catalytic_occupancy(ax, data, config)
        else:
            title, ylabel, color = specs[name]
            _plot_line(ax, data, ylabel=ylabel, color=color, title=title, config=config)
        output = analysis / f"{name}.png"
        fig.savefig(output, dpi=150, bbox_inches="tight")
        plt.close(fig)
        results.append(PlotResult(name=name, output_path=output))
    return results


def _plot_line(
    ax,
    data: np.ndarray | None,
    ylabel: str,
    color: str,
    title: str,
    config: GmxFlowConfig,
    hline: float | None = None,
) -> None:
    if data is None:
        _plot_missing(ax, "(arquivo nao encontrado)")
        return

    x = data[:, 0]
    y = data[:, 1]
    mean_line, lower, upper = _rolling_band(
        y,
        window=config.plots.band_window,
        std_multiplier=config.plots.band_std,
    )
    ax.plot(x, y, lw=0.6, color=color, alpha=config.plots.raw_alpha)
    ax.fill_between(x, lower, upper, color=color, alpha=config.plots.band_alpha)
    ax.plot(x, mean_line, lw=1.4, color=color, alpha=1.0)
    ax.set_xlabel("Tempo (ns)")
    ax.set_ylabel(ylabel)
    mean = y.mean()
    std = y.std()
    ax.set_title(f"{title} (media: {mean:.3f} +/- {std:.3f})")
    if hline is not None:
        ax.axhline(hline, ls="--", color="red", alpha=0.4)
    ax.grid(alpha=0.3)


def _plot_sasa_receptor_ligand(
    ax,
    datasets: dict[str, np.ndarray | None],
    config: GmxFlowConfig,
) -> bool:
    receptor = datasets.get("sasa_receptor")
    ligand = datasets.get("sasa_ligante")
    plotted = False
    if receptor is not None:
        _plot_line(
            ax,
            receptor,
            ylabel="SASA (nm^2)",
            color=config.plots.receptor_color,
            title="SASA receptor e ligante",
            config=config,
        )
        plotted = True
    if ligand is not None:
        _plot_line(
            ax,
            ligand,
            ylabel="SASA (nm^2)",
            color=config.plots.ligand_color,
            title="SASA receptor e ligante",
            config=config,
        )
        plotted = True
    if plotted:
        ax.set_title("SASA receptor e ligante")
        ax.legend(
            handles=[
                Line2D([0], [0], color=config.plots.receptor_color, lw=1.4),
                Line2D([0], [0], color=config.plots.ligand_color, lw=1.4),
            ],
            labels=["Receptor", "Ligante"],
        )
    return plotted


def _plot_catalytic_distance(
    ax,
    data: np.ndarray | None,
    config: GmxFlowConfig,
) -> None:
    _plot_line(
        ax,
        data,
        ylabel="Distancia minima (nm)",
        color=config.plots.ligand_color,
        title="Distancia aos residuos cataliticos",
        config=config,
    )
    cutoff = config.analysis.catalytic_distance_cutoff_nm
    ax.axhline(cutoff, ls="--", lw=1.1, color="black", alpha=0.8, label="Cutoff")
    ax.axhspan(0, cutoff, color=config.plots.ligand_color, alpha=0.06)
    ax.axhspan(cutoff, cutoff * 2, color=config.plots.receptor_color, alpha=0.04)
    ax.legend()


def _plot_catalytic_occupancy(
    ax,
    data: np.ndarray | None,
    config: GmxFlowConfig,
) -> None:
    if data is None:
        _plot_missing(ax, "(ocupacao nao encontrada)")
        return

    values = data[:, 1]
    mean = float(values.mean())
    std = float(values.std())
    ax.bar(
        ["Triade"],
        [mean],
        yerr=[std],
        color=config.plots.ligand_color,
        alpha=0.9,
        capsize=10,
    )
    ax.set_ylabel("N. contatos")
    ax.set_title(f"Ocupacao da triade catalitica (media: {mean:.3f} +/- {std:.3f})")
    ax.grid(alpha=0.3, axis="y")


def _rolling_band(
    values: np.ndarray,
    window: int,
    std_multiplier: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    effective_window = max(1, min(window, len(values)))
    if effective_window <= 1:
        return values, values, values
    kernel = np.ones(effective_window)
    counts = np.convolve(np.ones_like(values), kernel, mode="same")
    mean = np.convolve(values, kernel, mode="same") / counts
    squared_mean = np.convolve(values * values, kernel, mode="same") / counts
    variance = np.maximum(squared_mean - mean * mean, 0.0)
    std = np.sqrt(variance)
    return mean, mean - (std_multiplier * std), mean + (std_multiplier * std)


def _plot_rmsf(ax, data: np.ndarray | None) -> None:
    if data is None:
        _plot_missing(ax, "(rmsf nao encontrado)")
        return

    ax.bar(data[:, 0], data[:, 1], width=1.0, color="seagreen", alpha=0.8)
    if len(data) >= 5:
        ax.bar(data[-5:, 0], data[-5:, 1], width=1.0, color="crimson")
    ax.set_xlabel("Residuo")
    ax.set_ylabel("RMSF (nm)")
    ax.set_title("Flutuacao por residuo")
    ax.grid(alpha=0.3, axis="y")


def _plot_missing(ax, message: str) -> None:
    ax.text(0.5, 0.5, message, ha="center", va="center")
    ax.set_xticks([])
    ax.set_yticks([])
