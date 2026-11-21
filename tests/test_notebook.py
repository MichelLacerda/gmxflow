from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType

from matplotlib.figure import Figure

from gmxflow.config import default_config
from gmxflow.notebook import show_report
from gmxflow import plots


def test_show_report_displays_native_tables_and_graphs(
    tmp_path: Path, monkeypatch
) -> None:
    output_dir = tmp_path / "outputs"
    output_dir.mkdir(parents=True)
    plots.plt.get_backend()
    figure = Figure()
    payload = {
        "project": {"name": "notebook-test", "description": "Demo"},
        "executive_summary": {
            "metrics": [{"label": "Perfil", "value": "standard"}],
            "warnings": ["Revisar resultado"],
        },
        "execution": {
            "completed_steps": 2,
            "total_steps": 3,
            "steps": [
                {
                    "name": "analysis",
                    "status": "success",
                    "elapsed_seconds": 1.25,
                    "returncode": 0,
                }
            ],
        },
        "summaries": {
            "rmsd_backbone": {
                "label": "RMSD do backbone",
                "mean": 0.2,
                "std": 0.03,
                "minimum": 0.1,
                "maximum": 0.3,
                "points": 10,
                "unit": "nm",
                "fraction_positive": None,
            }
        },
        "plots": ["figures/painel_completo.png", "figures/rmsd_bb.png"],
    }
    (output_dir / "summary.json").write_text(json.dumps(payload), encoding="utf-8")

    displayed: list[object] = []
    enabled_magics: list[tuple[str, str]] = []

    class FakeShell:
        class Events:
            def register(self, name: str, callback) -> None:
                pass

        events = Events()

        def run_line_magic(self, name: str, argument: str) -> None:
            enabled_magics.append((name, argument))

    class FakeMarkdown:
        def __init__(self, text: str) -> None:
            self.text = text

    class FakeDataFrame:
        def __init__(self, rows: list[dict[str, object]]) -> None:
            self.rows = rows

    display_module = ModuleType("IPython.display")
    display_module.Markdown = FakeMarkdown
    display_module.display = displayed.append
    ipython = ModuleType("IPython")
    ipython.display = display_module
    ipython.get_ipython = lambda: FakeShell()
    ipython.version_info = (9, 0)
    pandas = ModuleType("pandas")
    pandas.DataFrame = FakeDataFrame
    previous_interactive_state = plots.plt.isinteractive()
    plots.plt.ion()
    monkeypatch.setitem(sys.modules, "IPython", ipython)
    monkeypatch.setitem(sys.modules, "IPython.display", display_module)
    monkeypatch.setitem(sys.modules, "pandas", pandas)
    seen_plot_request: list[tuple[object, Path, set[str]]] = []

    def create_figures(config, project_root: Path, names: set[str]):
        assert not plots.plt.isinteractive()
        seen_plot_request.append((config, project_root, names))
        return [("rmsd_bb", figure)]

    monkeypatch.setattr(plots, "create_analysis_figures", create_figures)

    config = default_config("notebook-test")
    show_report(tmp_path, config)
    assert plots.plt.isinteractive()
    plots.plt.interactive(previous_interactive_state)

    markdown_text = [item.text for item in displayed if isinstance(item, FakeMarkdown)]
    tables = [item for item in displayed if isinstance(item, FakeDataFrame)]
    canvases = [item for item in displayed if item is figure.canvas]
    assert "# notebook-test" in markdown_text
    assert "## Gráficos" in markdown_text
    assert "Relatório distribuível: `outputs/report.html`" in markdown_text
    assert "### Painel Completo" not in markdown_text
    assert "### Rmsd Bb" in markdown_text
    assert len(tables) == 3
    assert tables[0].rows == [{"Item": "Perfil", "Valor": "standard"}]
    assert tables[2].rows[0]["Métrica"] == "RMSD do backbone"
    assert canvases == [figure.canvas]
    assert figure.canvas.toolbar_visible is True
    assert enabled_magics == [("matplotlib", "widget")]
    assert seen_plot_request == [
        (config, tmp_path, {"rmsd_bb"})
    ]


def test_show_report_without_summary_displays_guidance(
    tmp_path: Path, monkeypatch
) -> None:
    displayed: list[object] = []

    class FakeMarkdown:
        def __init__(self, text: str) -> None:
            self.text = text

    display_module = ModuleType("IPython.display")
    display_module.Markdown = FakeMarkdown
    display_module.display = displayed.append
    ipython = ModuleType("IPython")
    ipython.display = display_module
    monkeypatch.setitem(sys.modules, "IPython", ipython)
    monkeypatch.setitem(sys.modules, "IPython.display", display_module)

    show_report(tmp_path, default_config("no-report"))

    assert len(displayed) == 1
    assert "Execute o projeto primeiro" in displayed[0].text
