import json
from pathlib import Path

import pytest

from gmxflow.config import default_config
from gmxflow.report import generate_report


def test_generate_report_writes_summary_and_html(tmp_path: Path) -> None:
    analysis = tmp_path / "work" / "analysis"
    analysis.mkdir(parents=True)
    _write_xvg(analysis / "rmsd_backbone.xvg", [0.1, 0.2, 0.3])
    _write_xvg(analysis / "rmsd_ligante.xvg", [0.2, 0.3, 0.4])
    _write_xvg(analysis / "rmsf_residuos.xvg", [0.1, 0.1, 0.2])
    _write_xvg(analysis / "gyrate.xvg", [1.0, 1.1, 1.2])
    _write_xvg(analysis / "mindist.xvg", [0.2, 0.3, 0.4])
    _write_xvg(analysis / "numcont.xvg", [0.0, 2.0, 4.0])
    _write_xvg(analysis / "hbond.xvg", [0.0, 1.0, 1.0])
    _write_xvg(analysis / "sasa_receptor.xvg", [10.0, 11.0, 12.0])
    _write_xvg(analysis / "sasa_ligante.xvg", [2.0, 3.0, 4.0])
    _write_xvg(analysis / "sasa_complexo.xvg", [9.0, 10.0, 11.0])
    _write_xvg(analysis / "bsa.xvg", [3.0, 4.0, 5.0])
    _write_interaction_xvg(analysis / "interaction_energy.xvg")
    (analysis / "painel_completo.png").write_bytes(b"png")
    log_path = tmp_path / "work" / "logs" / "01_analysis.log"
    log_path.parent.mkdir(parents=True)
    log_path.write_text("analysis log", encoding="utf-8")
    (tmp_path / "work" / "state.json").write_text(
        json.dumps(
            {
                "steps": {
                    "analysis": {
                        "status": "success",
                        "skipped": False,
                        "elapsed_seconds": 1.25,
                        "returncode": 0,
                        "log_path": str(log_path),
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    result = generate_report(default_config("report_test"), project_root=tmp_path)

    assert result.summary_json.is_file()
    assert result.summary_txt.is_file()
    assert result.report_html.is_file()

    payload = json.loads(result.summary_json.read_text(encoding="utf-8"))
    assert payload["project"]["name"] == "report_test"
    assert payload["summaries"]["rmsd_backbone"]["mean"] == pytest.approx(0.2)
    assert payload["summaries"]["numcont"]["fraction_positive"] == pytest.approx(2 / 3)
    assert payload["summaries"]["bsa"]["mean"] == pytest.approx(4.0)
    assert payload["summaries"]["interaction_total"]["mean"] == pytest.approx(-15.0)
    assert payload["executive_summary"]["metrics"][0] == {
        "label": "Perfil",
        "value": "standard",
    }
    assert {
        "label": "BSA aproximado",
        "value": "4.000 +/- 0.816 nm^2",
    } in payload["executive_summary"]["metrics"]
    assert payload["plots"] == ["figures/painel_completo.png"]
    assert "data/rmsd_backbone.xvg" in payload["data_files"]
    assert "data/bsa.xvg" in payload["data_files"]
    assert payload["execution"]["total_steps"] == 1
    assert payload["execution"]["completed_steps"] == 1
    assert payload["execution"]["failed_steps"] == []
    assert payload["execution"]["steps"][0]["log_path"] == "logs/01_analysis.log"
    assert (tmp_path / "outputs" / "figures" / "painel_completo.png").is_file()
    assert (tmp_path / "outputs" / "data" / "rmsd_backbone.xvg").is_file()
    assert (tmp_path / "outputs" / "data" / "bsa.xvg").is_file()
    assert (tmp_path / "outputs" / "logs" / "01_analysis.log").is_file()

    text = result.summary_txt.read_text(encoding="utf-8")
    assert "Resumo executivo" in text
    assert "Perfil: standard" in text
    assert "BSA aproximado: 4.000 +/- 0.816 nm^2" in text
    assert "Execução" in text
    assert "Etapas: 1/1 concluídas" in text
    assert "Estabilidade" in text
    assert "Interação receptor-ligante" in text
    assert "Energia de interação" in text
    assert "Superfície" in text
    assert "RMSD do backbone: 0.200 +/-" in text
    assert "BSA aproximado receptor-ligante: 4.000 +/-" in text
    assert "Energia total aproximada receptor-ligante: -15.000 +/-" in text
    assert "fração > 0: 0.667" in text

    html = result.report_html.read_text(encoding="utf-8")
    assert "<h2>Resumo executivo</h2>" in html
    assert "<h2>Execução</h2>" in html
    assert "logs/01_analysis.log" in html
    assert "summary-card" in html
    assert "<table>" in html
    assert "<h3>Estabilidade</h3>" in html
    assert "<h3>Interação receptor-ligante</h3>" in html
    assert "<h3>Energia de interação</h3>" in html
    assert "<h3>Superfície</h3>" in html
    assert "RMSD do backbone" in html
    assert "BSA aproximado receptor-ligante" in html
    assert "figures/painel_completo.png" in html
    assert "data/rmsd_backbone.xvg" in html


def test_generate_report_ignores_missing_analysis_files(tmp_path: Path) -> None:
    analysis = tmp_path / "work" / "analysis"
    analysis.mkdir(parents=True)
    _write_xvg(analysis / "rmsd_backbone.xvg", [0.1, 0.2])

    result = generate_report(default_config("partial_report_test"), project_root=tmp_path)

    payload = json.loads(result.summary_json.read_text(encoding="utf-8"))
    assert list(payload["summaries"]) == ["rmsd_backbone"]


def test_generate_report_includes_single_interaction_energy_series(tmp_path: Path) -> None:
    analysis = tmp_path / "work" / "analysis"
    analysis.mkdir(parents=True)
    (analysis / "interaction_energy.xvg").write_text(
        "# synthetic interaction energy XVG\n"
        '@ s0 legend "LJ-SR:Receptor-Ligante"\n'
        "0.0 -10.0\n"
        "1.0 -12.0\n",
        encoding="utf-8",
    )

    result = generate_report(default_config("single_energy_test"), project_root=tmp_path)

    payload = json.loads(result.summary_json.read_text(encoding="utf-8"))
    assert payload["summaries"]["interaction_lj_1"]["label"] == (
        "Energia Lennard-Jones Receptor-Ligante"
    )
    assert payload["summaries"]["interaction_lj_1"]["mean"] == pytest.approx(-11.0)
    assert "interaction_total" not in payload["summaries"]

    html = result.report_html.read_text(encoding="utf-8")
    assert "Energia Lennard-Jones Receptor-Ligante" in html


def test_generate_report_warns_for_smoke_profile(tmp_path: Path) -> None:
    analysis = tmp_path / "work" / "analysis"
    analysis.mkdir(parents=True)
    _write_xvg(analysis / "rmsd_backbone.xvg", [0.1, 0.2])
    config = default_config("smoke_report_test")
    config.simulation.profile = "smoke"

    result = generate_report(config, project_root=tmp_path)

    payload = json.loads(result.summary_json.read_text(encoding="utf-8"))
    assert payload["executive_summary"]["warnings"] == [
        "Perfil smoke: resultados servem apenas para validar a pipeline, "
        "não para interpretação científica."
    ]
    assert "Perfil smoke" in result.summary_txt.read_text(encoding="utf-8")
    assert "Perfil smoke" in result.report_html.read_text(encoding="utf-8")


def _write_xvg(path: Path, values: list[float]) -> None:
    lines = ["# synthetic XVG", "@ title \"test\""]
    lines.extend(f"{index:.1f} {value:.3f}" for index, value in enumerate(values))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_interaction_xvg(path: Path) -> None:
    path.write_text(
        "# synthetic interaction energy XVG\n"
        "@ title \"interaction\"\n"
        "0.0 -10.0 -5.0\n"
        "1.0 -12.0 -4.0\n"
        "2.0 -8.0 -6.0\n",
        encoding="utf-8",
    )
