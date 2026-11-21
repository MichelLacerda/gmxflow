from pathlib import Path

import pytest

from gmxflow.api import GmxFlowProject
from gmxflow.config import default_config, to_toml
from gmxflow.executor import StepResult


def _write_project_config(project_dir: Path) -> Path:
    project_dir.mkdir(parents=True)
    config_path = project_dir / "project.toml"
    config_path.write_text(to_toml(default_config(project_dir.name)), encoding="utf-8")
    return config_path


def test_open_loads_and_resolves_project_config(tmp_path: Path) -> None:
    config_path = _write_project_config(tmp_path / "api_project")

    project = GmxFlowProject.open(config_path)

    assert project.config_path == config_path.resolve()
    assert project.root == config_path.parent.resolve()
    assert project.config.project.name == "api_project"


def test_open_defaults_to_project_toml_in_current_directory(
    tmp_path: Path, monkeypatch
) -> None:
    project_dir = tmp_path / "default_project"
    config_path = _write_project_config(project_dir)
    monkeypatch.chdir(project_dir)

    project = GmxFlowProject.open()

    assert project.config_path == config_path.resolve()


def test_show_report_delegates_using_project_root(
    tmp_path: Path, monkeypatch
) -> None:
    project = GmxFlowProject.open(_write_project_config(tmp_path / "api_project"))
    shown_projects: list[tuple[Path, object]] = []

    monkeypatch.setattr(
        "gmxflow.notebook.show_report",
        lambda root, config: shown_projects.append((root, config)),
    )

    project.show_report()

    assert shown_projects == [(project.root, project.config)]


def test_clean_removes_work_artifacts_and_preserves_project_data(tmp_path: Path) -> None:
    project_dir = tmp_path / "api_project"
    project = GmxFlowProject.open(_write_project_config(project_dir))
    (project_dir / "inputs").mkdir()
    input_file = project_dir / "inputs" / "receptor.pdb"
    input_file.write_text("ATOM\n", encoding="utf-8")
    outputs_dir = project_dir / "outputs"
    outputs_dir.mkdir()
    report = outputs_dir / "report.html"
    report.write_text("<html></html>", encoding="utf-8")
    artifact = project_dir / "work" / "ligand" / "ligand.itp"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("; generated\n", encoding="utf-8")
    template = project_dir / "work" / "prod" / "md.mdp"
    template.parent.mkdir(parents=True)
    template.write_text("nsteps = 10\n", encoding="utf-8")

    result = project.clean()

    assert artifact in result.removed_paths
    assert not artifact.exists()
    assert template in result.preserved_paths
    assert template.is_file()
    assert input_file.is_file()
    assert report.is_file()
    assert project.config_path.is_file()


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


def test_validate_reports_prerequisites_without_creating_project_outputs(
    tmp_path: Path, monkeypatch
) -> None:
    project_dir = tmp_path / "api_project"
    config_path = _write_project_config(project_dir)
    (project_dir / "inputs").mkdir()
    receptor = project_dir / "inputs" / "receptor.pdb"
    ligand = project_dir / "inputs" / "ligante.pdb"
    receptor.write_text("ATOM\n", encoding="utf-8")
    ligand.write_text("ATOM\n", encoding="utf-8")
    force_field = project_dir / "amber99sb-ildn.ff"
    force_field.mkdir()
    (force_field / "forcefield.itp").write_text("; test\n", encoding="utf-8")
    (force_field / "forcefield.doc").write_text("test\n", encoding="utf-8")
    monkeypatch.setattr("gmxflow.forcefields._installed_roots", lambda: [])
    monkeypatch.setenv("GMXFLOW_FORCEFIELD_DIR", str(tmp_path / "user-forcefields"))
    monkeypatch.setattr("gmxflow.api.shutil.which", lambda command: "/opt/gromacs/bin/gmx")
    project = GmxFlowProject.open(config_path)

    report = project.validate()

    assert report.config_path == config_path.resolve()
    assert report.project_root == project_dir.resolve()
    assert report.input_files == (receptor.resolve(), ligand.resolve())
    assert report.force_field_path == force_field.resolve()
    assert report.gromacs_executable == Path("/opt/gromacs/bin/gmx")
    assert report.planned_steps
    assert not (project_dir / "work").exists()
    assert not (project_dir / "outputs").exists()


def test_validate_reports_missing_gromacs_executable(
    tmp_path: Path, monkeypatch
) -> None:
    project_dir = tmp_path / "api_project"
    config_path = _write_project_config(project_dir)
    (project_dir / "inputs").mkdir()
    (project_dir / "inputs" / "receptor.pdb").write_text("ATOM\n", encoding="utf-8")
    (project_dir / "inputs" / "ligante.pdb").write_text("ATOM\n", encoding="utf-8")
    monkeypatch.setattr("gmxflow.api.shutil.which", lambda command: None)
    project = GmxFlowProject.open(config_path)

    with pytest.raises(FileNotFoundError, match="Executável GROMACS 'gmx'"):
        project.validate()


def test_validate_reports_missing_force_field(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "api_project"
    config_path = _write_project_config(project_dir)
    (project_dir / "inputs").mkdir()
    (project_dir / "inputs" / "receptor.pdb").write_text("ATOM\n", encoding="utf-8")
    (project_dir / "inputs" / "ligante.pdb").write_text("ATOM\n", encoding="utf-8")
    monkeypatch.setattr("gmxflow.forcefields._installed_roots", lambda: [])
    monkeypatch.setenv("GMXFLOW_FORCEFIELD_DIR", str(tmp_path / "user-forcefields"))
    monkeypatch.setattr("gmxflow.api.shutil.which", lambda command: "/opt/gromacs/bin/gmx")
    project = GmxFlowProject.open(config_path)

    with pytest.raises(FileNotFoundError, match="Force field 'amber99sb-ildn'"):
        project.validate()


def test_run_validates_then_uses_shared_executor(
    tmp_path: Path, monkeypatch
) -> None:
    project_dir = tmp_path / "api_project"
    config_path = _write_project_config(project_dir)
    inputs_dir = project_dir / "inputs"
    inputs_dir.mkdir()
    (inputs_dir / "receptor.pdb").write_text("ATOM\n", encoding="utf-8")
    (inputs_dir / "ligante.pdb").write_text("ATOM\n", encoding="utf-8")
    force_field = project_dir / "amber99sb-ildn.ff"
    force_field.mkdir()
    (force_field / "forcefield.itp").write_text("; test\n", encoding="utf-8")
    (force_field / "forcefield.doc").write_text("test\n", encoding="utf-8")
    project = GmxFlowProject.open(config_path)
    events: list[str] = []
    workspace = StepResult(
        step_name="workspace",
        command=["<internal>", "ensure-workspace"],
        workdir=project.root / "work",
        log_path=project.root / "work" / "logs" / "00_workspace.log",
        returncode=0,
        elapsed_seconds=0.1,
    )
    step_result = StepResult(
        step_name="prepare",
        command=["gmxflow", "prepare-complex"],
        workdir=project.root / "work" / "prep",
        log_path=project.root / "work" / "logs" / "01_prepare.log",
        returncode=0,
        elapsed_seconds=0.2,
    )

    monkeypatch.setattr(
        "gmxflow.api.GmxFlowProject.validate",
        lambda self: events.append("validate"),
    )
    monkeypatch.setattr(
        "gmxflow.api.run_workspace_setup",
        lambda config, project_root: events.append("workspace") or workspace,
    )

    def fake_run_steps(steps, **kwargs):
        events.append("run_steps")
        assert [step.name for step in steps] == ["prepare"]
        assert kwargs["project_root"] == project.root
        assert kwargs["start_index"] == 1
        return [step_result]

    monkeypatch.setattr("gmxflow.api.run_steps", fake_run_steps)

    report = project.run(until="prepare")

    assert events == ["validate", "workspace", "run_steps"]
    assert report.workspace is workspace
    assert report.steps == (step_result,)
    assert report.results == (workspace, step_result)


def test_run_rejects_unreleased_steps_before_workspace_setup(
    tmp_path: Path, monkeypatch
) -> None:
    project = GmxFlowProject.open(_write_project_config(tmp_path / "api_project"))
    unreleased = project.plan(until="prepare")[0].model_copy(
        update={"name": "experimental-step"}
    )
    monkeypatch.setattr("gmxflow.api.GmxFlowProject.validate", lambda self: None)
    monkeypatch.setattr(
        "gmxflow.api.GmxFlowProject.plan", lambda self, **kwargs: [unreleased]
    )
    monkeypatch.setattr(
        "gmxflow.api.run_workspace_setup",
        lambda *args, **kwargs: pytest.fail("workspace setup must not run"),
    )

    with pytest.raises(ValueError, match="experimental-step"):
        project.run()
