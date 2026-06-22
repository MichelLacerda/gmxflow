from pathlib import Path

from gmxflow.config import default_config
from gmxflow.plots import generate_analysis_plots


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
