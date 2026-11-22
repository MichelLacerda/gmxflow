from pathlib import Path

from gmxflow.config import default_config
from gmxflow.plots import create_analysis_figures, generate_analysis_plots


def test_generate_analysis_plots_writes_panel_and_individual_pngs(tmp_path: Path) -> None:
    analysis = tmp_path / "work" / "analysis"
    analysis.mkdir(parents=True)
    _write_xvg(analysis / "rmsd_backbone.xvg")
    _write_xvg(analysis / "rmsd_ligante.xvg")
    _write_xvg(analysis / "rmsf_residuos.xvg")
    _write_xvg(analysis / "gyrate.xvg")
    _write_xvg(analysis / "numcont.xvg")
    _write_xvg(analysis / "hbond.xvg")
    _write_xvg(analysis / "sasa_receptor.xvg")
    _write_xvg(analysis / "sasa_complexo.xvg")
    _write_xvg(analysis / "sasa_ligante.xvg")
    _write_xvg(analysis / "bsa.xvg")
    _write_xvg(analysis / "catalytic_distance.xvg")
    _write_xvg(analysis / "catalytic_occupancy.xvg")

    results = generate_analysis_plots(default_config("plots_test"), project_root=tmp_path)

    assert [result.name for result in results] == [
        "painel_completo",
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
    for result in results:
        assert result.output_path.is_file()
        assert result.output_path.stat().st_size > 0


def test_create_analysis_figures_returns_matplotlib_objects_without_saving(
    tmp_path: Path,
) -> None:
    analysis = tmp_path / "work" / "analysis"
    analysis.mkdir(parents=True)
    _write_xvg(analysis / "rmsd_backbone.xvg")

    figures = create_analysis_figures(
        default_config("plots_test"),
        project_root=tmp_path,
        names={"rmsd_bb"},
    )

    assert [name for name, _ in figures] == ["rmsd_bb"]
    figure = figures[0][1]
    assert figure.axes[0].lines
    assert not list(analysis.glob("*.png"))


def test_protein_only_plots_exclude_ligand_figures(tmp_path: Path) -> None:
    analysis = tmp_path / "work" / "analysis"
    analysis.mkdir(parents=True)
    for name in ("rmsd_backbone", "rmsd_reference", "rmsf_residuos", "gyrate"):
        _write_xvg(analysis / f"{name}.xvg")
    config = default_config("protein_only_plots")
    config.input.ligand_kind = "none"

    results = generate_analysis_plots(config, project_root=tmp_path)

    assert [result.name for result in results] == [
        "rmsd_bb",
        "rmsd_reference",
        "rmsf",
        "rg",
    ]
    assert all(result.output_path.is_file() for result in results)


def test_thermodynamic_series_generate_individual_figures(tmp_path: Path) -> None:
    analysis = tmp_path / "work" / "analysis"
    analysis.mkdir(parents=True)
    for name in (
        "em_potential",
        "nvt_temperature",
        "npt_pressure",
        "npt_density",
    ):
        _write_xvg(analysis / f"{name}.xvg")
    config = default_config("thermodynamic_plots")
    config.input.ligand_kind = "none"

    results = generate_analysis_plots(config, project_root=tmp_path)

    assert [result.name for result in results] == [
        "em_potential",
        "nvt_temperature",
        "npt_pressure",
        "npt_density",
    ]


def _write_xvg(path: Path) -> None:
    path.write_text(
        "# synthetic XVG\n"
        "@ title \"test\"\n"
        "0.0 0.1\n"
        "1.0 0.2\n"
        "2.0 0.3\n"
        "3.0 0.2\n"
        "4.0 0.1\n",
        encoding="utf-8",
    )
