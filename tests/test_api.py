from pathlib import Path

import pytest

from gmxflow.api import GmxFlowProject
from gmxflow.config import default_config, to_toml


def _write_project_config(project_dir: Path) -> Path:
    project_dir.mkdir(parents=True)
    config_path = project_dir / "config.toml"
    config_path.write_text(to_toml(default_config(project_dir.name)), encoding="utf-8")
    return config_path


def test_open_loads_and_resolves_project_config(tmp_path: Path) -> None:
    config_path = _write_project_config(tmp_path / "api_project")

    project = GmxFlowProject.open(config_path)

    assert project.config_path == config_path.resolve()
    assert project.root == config_path.parent.resolve()
    assert project.config.project.name == "api_project"


def test_plan_returns_pipeline_steps_without_creating_project_outputs(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "api_project"
    config_path = _write_project_config(project_dir)
    project = GmxFlowProject.open(config_path)

    steps = project.plan(until="prepare")

    assert [step.name for step in steps] == ["prepare"]
    assert steps[0].command[:2] == ["gmxflow", "prepare-complex"]
    assert not (project_dir / "work").exists()
    assert not (project_dir / "outputs").exists()


def test_plan_can_require_input_files(tmp_path: Path) -> None:
    project = GmxFlowProject.open(_write_project_config(tmp_path / "api_project"))

    with pytest.raises(FileNotFoundError, match="receptor.pdb"):
        project.plan(strict_inputs=True)


def test_plan_rejects_unknown_step_with_valid_step_names(tmp_path: Path) -> None:
    project = GmxFlowProject.open(_write_project_config(tmp_path / "api_project"))

    with pytest.raises(ValueError, match="Etapa desconhecida: not-a-step"):
        project.plan(from_step="not-a-step")
