from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import numpy as np
from jinja2 import Environment, PackageLoader, select_autoescape
from pydantic import BaseModel

from gmxflow.config import GmxFlowConfig


class SeriesSummary(BaseModel):
    label: str
    path: str
    points: int
    time_start_ns: float | None
    time_end_ns: float | None
    mean: float
    std: float
    minimum: float
    maximum: float
    unit: str
    fraction_positive: float | None = None


class ReportResult(BaseModel):
    summary_json: Path
    summary_txt: Path
    report_html: Path


class ExecutiveMetric(BaseModel):
    label: str
    value: str


class ExecutiveSummary(BaseModel):
    metrics: list[ExecutiveMetric]
    warnings: list[str]


class ExecutionStep(BaseModel):
    name: str
    status: str
    skipped: bool
    elapsed_seconds: float
    returncode: int
    log_path: str | None = None


class ExecutionSummary(BaseModel):
    total_steps: int
    completed_steps: int
    failed_steps: list[str]
    steps: list[ExecutionStep]


SERIES = {
    "rmsd_backbone": {
        "label": "RMSD do backbone",
        "path": "rmsd_backbone.xvg",
        "unit": "nm",
    },
    "rmsd_ligante": {
        "label": "RMSD do ligante",
        "path": "rmsd_ligante.xvg",
        "unit": "nm",
    },
    "rmsf_residuos": {
        "label": "RMSF por resíduo",
        "path": "rmsf_residuos.xvg",
        "unit": "nm",
    },
    "gyrate": {
        "label": "Raio de giro",
        "path": "gyrate.xvg",
        "unit": "nm",
    },
    "mindist": {
        "label": "Distância mínima receptor-ligante",
        "path": "mindist.xvg",
        "unit": "nm",
    },
    "numcont": {
        "label": "Contatos receptor-ligante",
        "path": "numcont.xvg",
        "unit": "átomos",
    },
    "hbond": {
        "label": "Pontes de hidrogênio receptor-ligante",
        "path": "hbond.xvg",
        "unit": "ligações",
    },
    "sasa_receptor": {
        "label": "SASA do receptor",
        "path": "sasa_receptor.xvg",
        "unit": "nm^2",
    },
    "sasa_ligante": {
        "label": "SASA do ligante",
        "path": "sasa_ligante.xvg",
        "unit": "nm^2",
    },
    "sasa_complexo": {
        "label": "SASA do complexo receptor-ligante",
        "path": "sasa_complexo.xvg",
        "unit": "nm^2",
    },
    "bsa": {
        "label": "BSA aproximado receptor-ligante",
        "path": "bsa.xvg",
        "unit": "nm^2",
    },
    "catalytic_distance": {
        "label": "Distância mínima ligante-tríade catalítica",
        "path": "catalytic_distance.xvg",
        "unit": "nm",
    },
    "catalytic_occupancy": {
        "label": "Ocupação da tríade catalítica",
        "path": "catalytic_occupancy.xvg",
        "unit": "contatos",
    },
}

PLOTS = [
    "painel_completo.png",
    "rmsd_bb.png",
    "rmsd_lig.png",
    "rmsf.png",
    "rg.png",
    "ncont.png",
    "hbond.png",
    "sasa_complexo.png",
    "sasa_ligante.png",
    "bsa.png",
    "catalytic_distance.png",
    "catalytic_occupancy.png",
]

DATA_FILES = [
    "rmsd_backbone.xvg",
    "rmsd_ligante.xvg",
    "rmsf_residuos.xvg",
    "gyrate.xvg",
    "mindist.xvg",
    "numcont.xvg",
    "hbond.xvg",
    "interaction_energy.xvg",
    "sasa_receptor.xvg",
    "sasa_ligante.xvg",
    "sasa_complexo.xvg",
    "bsa.xvg",
    "catalytic_distance.xvg",
    "catalytic_occupancy.xvg",
]

REPORT_SECTIONS = [
    (
        "Estabilidade",
        (
            "rmsd_backbone",
            "rmsd_ligante",
            "rmsf_residuos",
            "gyrate",
        ),
    ),
    (
        "Interação receptor-ligante",
        (
            "mindist",
            "numcont",
            "hbond",
        ),
    ),
    (
        "Energia de interação",
        (
            "interaction_coulomb",
            "interaction_lj",
            "interaction_energy",
            "interaction_total",
        ),
    ),
    (
        "Superfície",
        (
            "sasa_receptor",
            "sasa_ligante",
            "sasa_complexo",
            "bsa",
        ),
    ),
]


def generate_report(config: GmxFlowConfig, project_root: Path) -> ReportResult:
    project_root = project_root.expanduser().resolve()
    analysis_dir = project_root / "work" / "analysis"
    output_dir = project_root / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    summaries = _summaries(analysis_dir)
    executive_summary = _executive_summary(config, summaries)
    figures = _publish_files(
        source_dir=analysis_dir,
        output_dir=output_dir / "figures",
        names=PLOTS,
    )
    data_files = _publish_files(
        source_dir=analysis_dir,
        output_dir=output_dir / "data",
        names=DATA_FILES,
    )
    execution = _execution_summary(
        state_path=project_root / "work" / "state.json",
        output_dir=output_dir,
    )
    payload = {
        "project": config.project.model_dump(),
        "input": {
            "ligand_kind": config.input.ligand_kind,
            "ligand_resname": config.input.ligand_resname,
        },
        "simulation": {
            "profile": config.simulation.profile,
            "production_ns": config.simulation.production_ns,
            "production_steps": config.simulation.production_steps,
        },
        "analysis": {
            "contact_cutoff_nm": config.analysis.contact_cutoff_nm,
        },
        "summaries": {
            name: summary.model_dump() for name, summary in summaries.items()
        },
        "executive_summary": executive_summary.model_dump(),
        "execution": execution.model_dump(),
        "plots": [_relative_to_output(path, output_dir) for path in figures],
        "data_files": [_relative_to_output(path, output_dir) for path in data_files],
    }

    summary_json = output_dir / "summary.json"
    summary_txt = output_dir / "summary.txt"
    report_html = output_dir / "report.html"

    summary_json.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    summary_txt.write_text(_render_text(payload), encoding="utf-8")
    report_html.write_text(_render_html(payload), encoding="utf-8")

    return ReportResult(
        summary_json=summary_json,
        summary_txt=summary_txt,
        report_html=report_html,
    )


def _summaries(analysis_dir: Path) -> dict[str, SeriesSummary]:
    summaries: dict[str, SeriesSummary] = {}
    for name, spec in SERIES.items():
        path = analysis_dir / spec["path"]
        data = _load_xvg(path)
        if data is None:
            continue
        values = data[:, 1]
        summaries[name] = SeriesSummary(
            label=spec["label"],
            path=str(path),
            points=int(values.size),
            time_start_ns=float(data[0, 0]) if data.size else None,
            time_end_ns=float(data[-1, 0]) if data.size else None,
            mean=float(values.mean()),
            std=float(values.std()),
            minimum=float(values.min()),
            maximum=float(values.max()),
            unit=spec["unit"],
            fraction_positive=_fraction_positive(values)
            if name in {"numcont", "hbond"}
            else None,
        )
    summaries.update(_interaction_energy_summaries(analysis_dir))
    return summaries


def _interaction_energy_summaries(analysis_dir: Path) -> dict[str, SeriesSummary]:
    path = analysis_dir / "interaction_energy.xvg"
    parsed = _load_xvg_with_legends(path)
    if parsed is None:
        return {}
    data, legends = parsed
    if data.shape[1] < 2:
        return {}

    summaries: dict[str, SeriesSummary] = {}
    energy_values: list[np.ndarray] = []
    for index in range(1, data.shape[1]):
        legend = legends[index - 1] if index - 1 < len(legends) else f"Série {index}"
        key, label = _interaction_energy_label(legend, index)
        values = data[:, index]
        energy_values.append(values)
        summaries[key] = _series_summary(
            label=label,
            path=path,
            data=data,
            values=values,
            unit="kJ/mol",
        )

    if len(energy_values) > 1:
        summaries["interaction_total"] = _series_summary(
            label="Energia total aproximada receptor-ligante",
            path=path,
            data=data,
            values=sum(energy_values),  # pyright: ignore[reportArgumentType]
            unit="kJ/mol",
        )
    return summaries


def _load_xvg_with_legends(path: Path) -> tuple[np.ndarray, list[str]] | None:
    if not path.is_file():
        return None

    legends: list[str] = []
    rows: list[list[float]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        legend_match = re.match(r'^@\s+s\d+\s+legend\s+"(.+)"', line)
        if legend_match is not None:
            legends.append(legend_match.group(1))
            continue
        if line.startswith(("#", "@")):
            continue
        try:
            rows.append([float(value) for value in line.split()])
        except ValueError:
            continue
    if not rows:
        return None
    return np.array(rows), legends


def _interaction_energy_label(legend: str, index: int) -> tuple[str, str]:
    normalized = legend.replace("_", "-")
    if normalized.startswith("Coul-SR:"):
        return (
            f"interaction_coulomb_{index}",
            f"Energia Coulomb {normalized.removeprefix('Coul-SR:')}",
        )
    if normalized.startswith("LJ-SR:"):
        return (
            f"interaction_lj_{index}",
            f"Energia Lennard-Jones {normalized.removeprefix('LJ-SR:')}",
        )
    return f"interaction_energy_{index}", f"Energia de interação {legend}"


def _series_summary(
    label: str,
    path: Path,
    data: np.ndarray,
    values: np.ndarray,
    unit: str,
) -> SeriesSummary:
    return SeriesSummary(
        label=label,
        path=str(path),
        points=int(values.size),
        time_start_ns=float(data[0, 0]) if data.size else None,
        time_end_ns=float(data[-1, 0]) if data.size else None,
        mean=float(values.mean()),
        std=float(values.std()),
        minimum=float(values.min()),
        maximum=float(values.max()),
        unit=unit,
    )


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


def _fraction_positive(values: np.ndarray) -> float:
    if values.size == 0:
        return 0.0
    return float((values > 0).sum() / values.size)


def _executive_summary(
    config: GmxFlowConfig,
    summaries: dict[str, SeriesSummary],
) -> ExecutiveSummary:
    metrics = [
        ExecutiveMetric(label="Perfil", value=config.simulation.profile),
        ExecutiveMetric(
            label="Passos de produção",
            value=str(config.simulation.production_steps),
        ),
    ]
    for key, label in (
        ("rmsd_backbone", "RMSD backbone médio"),
        ("rmsd_ligante", "RMSD ligante médio"),
        ("numcont", "Contatos médios"),
        ("hbond", "H-bonds médios"),
        ("interaction_total", "Energia total aproximada"),
        ("bsa", "BSA aproximado"),
    ):
        summary = summaries.get(key)
        if summary is not None:
            metrics.append(
                ExecutiveMetric(
                    label=label,
                    value=f"{summary.mean:.3f} +/- {summary.std:.3f} {summary.unit}",
                )
            )

    warnings: list[str] = []
    if config.simulation.profile == "smoke":
        warnings.append(
            "Perfil smoke: resultados servem apenas para validar a pipeline, "
            "não para interpretação científica."
        )
    if config.analysis.interaction_energy and not _has_interaction_energy(summaries):
        warnings.append(
            "Energia de interação foi solicitada, mas nenhum termo foi incluído no relatório."
        )
    if config.analysis.sasa and "bsa" not in summaries:
        warnings.append(
            "SASA/BSA foi solicitado, mas BSA não foi incluído no relatório."
        )
    return ExecutiveSummary(metrics=metrics, warnings=warnings)


def _has_interaction_energy(summaries: dict[str, SeriesSummary]) -> bool:
    return any(key.startswith("interaction_") for key in summaries)


def _publish_files(source_dir: Path, output_dir: Path, names: list[str]) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    published: list[Path] = []
    for name in names:
        source = source_dir / name
        if not source.is_file():
            continue
        destination = output_dir / name
        shutil.copy2(source, destination)
        published.append(destination)
    return published


def _execution_summary(state_path: Path, output_dir: Path) -> ExecutionSummary:
    state = _load_state(state_path)
    steps_data = state.get("steps", {})
    if not isinstance(steps_data, dict):
        steps_data = {}

    log_output_dir = output_dir / "logs"
    steps: list[ExecutionStep] = []
    for name, raw_step in steps_data.items():
        if not isinstance(name, str) or not isinstance(raw_step, dict):
            continue
        log_path = _publish_log(raw_step.get("log_path"), log_output_dir)
        status = str(raw_step.get("status", "unknown"))
        returncode = raw_step.get("returncode", -1)
        elapsed = raw_step.get("elapsed_seconds", 0.0)
        steps.append(
            ExecutionStep(
                name=name,
                status=status,
                skipped=bool(raw_step.get("skipped", False)),
                elapsed_seconds=float(elapsed)
                if isinstance(elapsed, int | float)
                else 0.0,
                returncode=int(returncode) if isinstance(returncode, int) else -1,
                log_path=log_path,
            )
        )

    steps.sort(key=lambda step: step.log_path or step.name)
    failed_steps = [step.name for step in steps if step.status == "failed"]
    completed_steps = sum(1 for step in steps if step.status in {"success", "skipped"})
    return ExecutionSummary(
        total_steps=len(steps),
        completed_steps=completed_steps,
        failed_steps=failed_steps,
        steps=steps,
    )


def _load_state(state_path: Path) -> dict[str, object]:
    if not state_path.is_file():
        return {"steps": {}}
    try:
        loaded = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"steps": {}}
    return loaded if isinstance(loaded, dict) else {"steps": {}}


def _publish_log(raw_log_path: object, output_dir: Path) -> str | None:
    if not isinstance(raw_log_path, str):
        return None
    source = Path(raw_log_path)
    if not source.is_file():
        return None
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / source.name
    shutil.copy2(source, destination)
    return str(destination.relative_to(output_dir.parent))


def _relative_to_output(path: Path, output_dir: Path) -> str:
    return str(path.relative_to(output_dir))


def _render_text(payload: dict[str, object]) -> str:
    project = payload["project"]
    assert isinstance(project, dict)
    summaries = payload["summaries"]
    assert isinstance(summaries, dict)
    executive_summary = payload["executive_summary"]
    assert isinstance(executive_summary, dict)
    execution = payload["execution"]
    assert isinstance(execution, dict)
    sections = _report_sections(summaries)

    lines = [
        f"Projeto: {project.get('name', '-')}",
        f"Descrição: {project.get('description', '-')}",
        "",
        "Resumo executivo",
        "",
    ]
    for metric in executive_summary.get("metrics", []):
        assert isinstance(metric, dict)
        lines.append(f"- {metric['label']}: {metric['value']}")
    warnings = executive_summary.get("warnings", [])
    if warnings:
        lines.append("")
        lines.append("Avisos")
        lines.append("")
        for warning in warnings:
            lines.append(f"- {warning}")
    lines.extend(
        [
            "",
            "Execução",
            "",
            f"- Etapas: {execution.get('completed_steps', 0)}/{execution.get('total_steps', 0)} concluídas",
            f"- Falhas: {len(execution.get('failed_steps', []))}",
        ]
    )
    lines.extend(
        [
            "",
            "Resumo das análises",
            "",
        ]
    )
    for section in sections:
        lines.append(str(section["title"]))
        lines.append("")
        metrics = section["metrics"]
        assert isinstance(metrics, list)
        for summary in metrics:
            assert isinstance(summary, dict)
            lines.append(_summary_text_line(summary))
            if summary.get("fraction_positive") is not None:
                lines.append(f"  fração > 0: {float(summary['fraction_positive']):.3f}")
        lines.append("")
    return "\n".join(lines) + "\n"


def _render_html(payload: dict[str, object]) -> str:
    project = payload["project"]
    assert isinstance(project, dict)
    summaries = payload["summaries"]
    assert isinstance(summaries, dict)
    executive_summary = payload["executive_summary"]
    assert isinstance(executive_summary, dict)
    execution = payload["execution"]
    assert isinstance(execution, dict)
    plots = payload["plots"]
    assert isinstance(plots, list)
    data_files = payload["data_files"]
    assert isinstance(data_files, list)
    sections = _report_sections(summaries)

    return (
        _template_env()
        .get_template("report.html.j2")
        .render(
            project=project,
            executive_summary=executive_summary,
            execution=execution,
            sections=sections,
            plots=plots,
            data_files=data_files,
        )
    )


def _report_sections(summaries: dict[object, object]) -> list[dict[str, object]]:
    sections: list[dict[str, object]] = []
    used: set[str] = set()
    for title, prefixes in REPORT_SECTIONS:
        metrics = [
            summary
            for name, summary in summaries.items()
            if isinstance(name, str)
            and isinstance(summary, dict)
            and any(name.startswith(prefix) for prefix in prefixes)
        ]
        if metrics:
            sections.append({"title": title, "metrics": metrics})
            used.update(
                name
                for name, summary in summaries.items()
                if isinstance(name, str)
                and isinstance(summary, dict)
                and any(name.startswith(prefix) for prefix in prefixes)
            )
    other_metrics = [
        summary
        for name, summary in summaries.items()
        if isinstance(name, str) and isinstance(summary, dict) and name not in used
    ]
    if other_metrics:
        sections.append({"title": "Outras métricas", "metrics": other_metrics})
    return sections


def _summary_text_line(summary: dict[str, object]) -> str:
    return (
        f"- {summary['label']}: "
        f"{float(summary['mean']):.3f} +/- {float(summary['std']):.3f} {summary['unit']} "  # pyright: ignore[reportArgumentType]
        f"(min={float(summary['minimum']):.3f}, "  # pyright: ignore[reportArgumentType]
        f"max={float(summary['maximum']):.3f}, n={summary['points']})"  # pyright: ignore[reportArgumentType]
    )


def _template_env() -> Environment:
    return Environment(
        loader=PackageLoader("gmxflow", "templates"),
        autoescape=select_autoescape(enabled_extensions=("html", "j2")),
        trim_blocks=True,
        lstrip_blocks=True,
    )
