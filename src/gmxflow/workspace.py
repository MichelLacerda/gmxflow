from __future__ import annotations

import shutil
from pathlib import Path

from pydantic import BaseModel

from gmxflow.config import GmxFlowConfig
from gmxflow.project import render_template


class RenderedTemplate(BaseModel):
    template_name: str
    output_path: Path


class WorkspaceSetup(BaseModel):
    work_root: Path
    directories: list[Path]
    rendered_templates: list[RenderedTemplate]
    existing_templates: list[Path]


class CleanResult(BaseModel):
    work_root: Path
    removed_paths: list[Path]
    preserved_paths: list[Path]
    directories: list[Path]


WORK_DIRS = (
    "prep",
    "topo",
    "box",
    "em",
    "nvt",
    "npt",
    "prod",
    "analysis",
    "logs",
)

TEMPLATE_TARGETS = {
    "ions.mdp.j2": Path("box") / "ions.mdp",
    "em.mdp.j2": Path("em") / "em.mdp",
    "nvt.mdp.j2": Path("nvt") / "nvt.mdp",
    "npt.mdp.j2": Path("npt") / "npt.mdp",
    "md.mdp.j2": Path("prod") / "md.mdp",
    "rerun.mdp.j2": Path("analysis") / "rerun.mdp",
}


def prepare_workspace(
    config: GmxFlowConfig,
    project_root: Path,
    force: bool = False,
) -> list[RenderedTemplate]:
    _ensure_work_dirs(project_root)
    return render_templates(config=config, project_root=project_root, force=force)


def ensure_workspace(config: GmxFlowConfig, project_root: Path) -> WorkspaceSetup:
    work_root = project_root / "work"
    directories: list[Path] = []
    rendered: list[RenderedTemplate] = []
    existing: list[Path] = []

    for path in _ensure_work_dirs(project_root):
        directories.append(path)

    for template_name, relative_output in TEMPLATE_TARGETS.items():
        output_path = work_root / relative_output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists():
            existing.append(output_path)
            continue
        output_path.write_text(render_template(template_name, config), encoding="utf-8")
        rendered.append(
            RenderedTemplate(template_name=template_name, output_path=output_path)
        )

    return WorkspaceSetup(
        work_root=work_root,
        directories=directories,
        rendered_templates=rendered,
        existing_templates=existing,
    )


def clean_workspace(
    project_root: Path,
    remove_templates: bool = False,
    all_work: bool = False,
) -> CleanResult:
    work_root = project_root / "work"
    state_path = work_root / "state.json"
    removed: list[Path] = []
    preserved: list[Path] = []

    if all_work:
        if work_root.exists():
            shutil.rmtree(work_root)
            removed.append(work_root)
        directories = _ensure_work_dirs(project_root)
        return CleanResult(
            work_root=work_root,
            removed_paths=removed,
            preserved_paths=preserved,
            directories=directories,
        )

    template_paths = _template_output_paths(project_root)
    for directory in WORK_DIRS:
        path = work_root / directory
        if not path.exists():
            continue
        for child in path.iterdir():
            if child in template_paths and not remove_templates:
                preserved.append(child)
                continue
            _remove_path(child)
            removed.append(child)

    if state_path.exists():
        _remove_path(state_path)
        removed.append(state_path)

    directories = _ensure_work_dirs(project_root)
    return CleanResult(
        work_root=work_root,
        removed_paths=removed,
        preserved_paths=preserved,
        directories=directories,
    )


def render_templates(
    config: GmxFlowConfig,
    project_root: Path,
    force: bool = False,
) -> list[RenderedTemplate]:
    work_root = project_root / "work"
    rendered: list[RenderedTemplate] = []

    for template_name, relative_output in TEMPLATE_TARGETS.items():
        output_path = work_root / relative_output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists() and not force:
            raise FileExistsError(f"O arquivo já existe: {output_path}")
        output_path.write_text(render_template(template_name, config), encoding="utf-8")
        rendered.append(
            RenderedTemplate(template_name=template_name, output_path=output_path)
        )

    return rendered


def _ensure_work_dirs(project_root: Path) -> list[Path]:
    work_root = project_root / "work"
    directories: list[Path] = []
    for directory in WORK_DIRS:
        path = work_root / directory
        path.mkdir(parents=True, exist_ok=True)
        directories.append(path)
    return directories


def _template_output_paths(project_root: Path) -> set[Path]:
    work_root = project_root / "work"
    return {work_root / relative_output for relative_output in TEMPLATE_TARGETS.values()}


def _remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
        return
    path.unlink()
