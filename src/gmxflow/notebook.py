"""Notebook-specific presentation helpers for gmxflow projects."""

from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path
from typing import Any

from gmxflow.executor import WorkflowStepResult, WorkflowStepStatus

_DISPLAYED_FIGURES: list[Any] = []


def show_execution(
    results: tuple[WorkflowStepResult, ...],
) -> None:
    """Display execution statuses, durations, and log paths in a notebook."""
    try:
        display_module = import_module("IPython.display")
    except ImportError as error:
        raise RuntimeError(
            "A exibição do resumo requer IPython no ambiente do notebook."
        ) from error
    try:
        pd = import_module("pandas")
    except ImportError as error:
        raise RuntimeError(
            "A exibição do resumo requer pandas. Instale o extra `gmxflow[notebook]`."
        ) from error

    rows = []
    for result in results:
        status = {
            WorkflowStepStatus.PLANNED: "planejada",
            WorkflowStepStatus.SUCCEEDED: "concluída",
            WorkflowStepStatus.SKIPPED: "reutilizada (sem alterações)",
            WorkflowStepStatus.FAILED: "falhou",
            WorkflowStepStatus.BLOCKED: "bloqueada",
        }[result.status]
        rows.append(
            {
                "Etapa": result.step_id,
                "Status": status,
                "Duração (s)": round(result.elapsed_seconds, 3),
                "Log": str(result.log_path),
            }
        )

    display_module.display(display_module.Markdown("### Resumo da execução"))
    table = pd.DataFrame(rows, columns=["Etapa", "Status", "Duração (s)", "Log"])
    with pd.option_context("display.max_colwidth", None):
        display_module.display(table)


def show_report(project_root: Path, config: Any) -> None:
    """Display the generated report using native Jupyter outputs."""
    try:
        display_module = import_module("IPython.display")
    except ImportError as error:
        raise RuntimeError(
            "A exibição do relatório requer IPython no ambiente do notebook."
        ) from error
    markdown = display_module.Markdown
    display = display_module.display

    output_dir = project_root / "outputs"
    summary_path = output_dir / "summary.json"
    if not summary_path.is_file():
        display(markdown("Relatório ainda não encontrado. Execute o projeto primeiro."))
        return

    try:
        pd = import_module("pandas")
    except ImportError as error:
        raise RuntimeError(
            "A exibição das tabelas requer pandas. Instale o extra `gmxflow[notebook]`."
        ) from error

    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    _enable_interactive_backend()
    _display_report(payload, output_dir, config, pd, markdown, display)


def _enable_interactive_backend() -> None:
    ipython = import_module("IPython")
    shell = ipython.get_ipython()
    if shell is None:
        raise RuntimeError(
            "Os gráficos interativos requerem um kernel Jupyter/IPython ativo."
        )
    import matplotlib

    if "ipympl" in str(matplotlib.get_backend()).lower():
        return
    try:
        shell.run_line_magic("matplotlib", "widget")
    except (ImportError, RuntimeError) as error:
        raise RuntimeError(
            "Os controles Matplotlib requerem ipympl. Instale "
            "`gmxflow[notebook]` e reinicie o kernel."
        ) from error


def _display_report(
    payload: dict[str, Any],
    output_dir: Path,
    config: Any,
    pd: Any,
    markdown: Any,
    display: Any,
) -> None:
    project = payload.get("project", {})
    if not isinstance(project, dict):
        project = {}
    display(markdown(f"# {project.get('name', 'Projeto gmxflow')}"))
    description = project.get("description")
    if description:
        display(markdown(str(description)))

    summary = payload.get("executive_summary", {})
    if not isinstance(summary, dict):
        summary = {}
    display(markdown("## Resumo"))
    metrics = summary.get("metrics", [])
    if isinstance(metrics, list):
        display(
            pd.DataFrame(
                [
                    {"Item": item.get("label", ""), "Valor": item.get("value", "")}
                    for item in metrics
                    if isinstance(item, dict)
                ]
            )
        )
    warnings = summary.get("warnings", [])
    if isinstance(warnings, list) and warnings:
        display(
            markdown("### Avisos\n" + "\n".join(f"- {warning}" for warning in warnings))
        )

    execution = payload.get("execution", {})
    if not isinstance(execution, dict):
        execution = {}
    display(markdown("## Execução"))
    display(
        markdown(
            f"Etapas concluídas: {execution.get('completed_steps', 0)} / "
            f"{execution.get('total_steps', 0)}"
        )
    )
    steps = execution.get("steps", [])
    if isinstance(steps, list):
        display(
            pd.DataFrame(
                [
                    {
                        "Etapa": step.get("name", ""),
                        "Status": step.get("status", ""),
                        "Duração (s)": step.get("elapsed_seconds"),
                        "Código de saída": step.get("returncode"),
                    }
                    for step in steps
                    if isinstance(step, dict)
                ]
            )
        )

    display(markdown("## Análises"))
    summaries = payload.get("summaries", {})
    if isinstance(summaries, dict):
        rows = []
        for result in summaries.values():
            if not isinstance(result, dict):
                continue
            unit = result.get("unit", "")
            rows.append(
                {
                    "Métrica": result.get("label", ""),
                    "Média": result.get("mean"),
                    "Desvio padrão": result.get("std"),
                    "Mínimo": result.get("minimum"),
                    "Máximo": result.get("maximum"),
                    "Pontos": result.get("points"),
                    "Fração > 0": result.get("fraction_positive"),
                    "Unidade": unit,
                }
            )
        display(pd.DataFrame(rows))

    display(markdown("## Gráficos"))
    plots = payload.get("plots", [])
    displayed_plot = False
    if isinstance(plots, list):
        names = {Path(plot).stem for plot in plots if isinstance(plot, str)} - {
            "painel_completo"
        }
        from matplotlib import pyplot as plt

        from gmxflow.plots import create_analysis_figures

        for previous_figure in _DISPLAYED_FIGURES:
            plt.close(previous_figure)
        _DISPLAYED_FIGURES.clear()
        with plt.ioff():
            figures = create_analysis_figures(config, output_dir.parent, names=names)
        for name, figure in figures:
            display(markdown(f"### {name.replace('_', ' ').title()}"))
            setattr(figure.canvas, "toolbar_visible", True)
            display(figure.canvas)
            _DISPLAYED_FIGURES.append(figure)
            displayed_plot = True
    if not displayed_plot:
        display(markdown("Nenhum gráfico disponível."))

    display(markdown("Relatório distribuível: `outputs/report.html`"))
