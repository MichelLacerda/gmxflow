from pathlib import Path

import pytest

from gmxflow.config import default_config
from gmxflow.executor import run_workspace_setup
from gmxflow.workspace import clean_workspace, ensure_workspace, prepare_workspace, render_templates


def test_render_templates_writes_mdp_files_to_work(tmp_path: Path) -> None:
    config = default_config("workspace_test")
    config.simulation.profile = "smoke"

    rendered = render_templates(config=config, project_root=tmp_path)

    assert [item.output_path.relative_to(tmp_path) for item in rendered] == [
        Path("work/box/ions.mdp"),
        Path("work/em/em.mdp"),
        Path("work/nvt/nvt.mdp"),
        Path("work/npt/npt.mdp"),
        Path("work/prod/md.mdp"),
        Path("work/analysis/rerun.mdp"),
    ]
    assert "nsteps          = 10" in (tmp_path / "work/prod/md.mdp").read_text(
        encoding="utf-8"
    )
    assert "nstxout-compressed = 1" in (tmp_path / "work/prod/md.mdp").read_text(
        encoding="utf-8"
    )
    assert "energygrps      = Receptor Ligante" in (
        tmp_path / "work/analysis/rerun.mdp"
    ).read_text(encoding="utf-8")


def test_render_templates_refuses_overwrite_without_force(tmp_path: Path) -> None:
    config = default_config("overwrite_test")
    render_templates(config=config, project_root=tmp_path)

    with pytest.raises(FileExistsError):
        render_templates(config=config, project_root=tmp_path)


def test_prepare_workspace_creates_work_directories(tmp_path: Path) -> None:
    config = default_config("prepare_workspace_test")

    prepare_workspace(config=config, project_root=tmp_path)

    for directory in (
        "prep",
        "ligand",
        "topo",
        "box",
        "em",
        "nvt",
        "npt",
        "prod",
        "analysis",
        "logs",
    ):
        assert (tmp_path / "work" / directory).is_dir()


def test_ensure_workspace_renders_only_missing_templates(tmp_path: Path) -> None:
    config = default_config("ensure_workspace_test")

    first = ensure_workspace(config=config, project_root=tmp_path)
    second = ensure_workspace(config=config, project_root=tmp_path)

    assert len(first.rendered_templates) == 6
    assert first.existing_templates == []
    assert second.rendered_templates == []
    assert len(second.existing_templates) == 6


def test_run_workspace_setup_writes_log_and_mdp_files(tmp_path: Path) -> None:
    run_workspace_setup(default_config("workspace_log_test"), project_root=tmp_path)

    log_path = tmp_path / "work" / "logs" / "00_workspace.log"
    assert log_path.is_file()
    assert (tmp_path / "work" / "prod" / "md.mdp").is_file()

    log = log_path.read_text(encoding="utf-8")
    assert "step: workspace" in log
    assert "rendered_templates:" in log
    assert "md.mdp.j2" in log


def test_clean_workspace_preserves_templates_by_default(tmp_path: Path) -> None:
    ensure_workspace(config=default_config("clean_test"), project_root=tmp_path)
    artifact = tmp_path / "work" / "prep" / "complexo.pdb"
    log = tmp_path / "work" / "logs" / "02_prepare.log"
    state = tmp_path / "work" / "state.json"
    artifact.write_text("pdb", encoding="utf-8")
    log.write_text("log", encoding="utf-8")
    state.write_text("{}", encoding="utf-8")

    result = clean_workspace(project_root=tmp_path)

    assert artifact in result.removed_paths
    assert log in result.removed_paths
    assert state in result.removed_paths
    assert not artifact.exists()
    assert not log.exists()
    assert not state.exists()
    assert (tmp_path / "work" / "prod" / "md.mdp").is_file()
    assert tmp_path / "work" / "prod" / "md.mdp" in result.preserved_paths


def test_clean_workspace_removes_ligand_artifacts(tmp_path: Path) -> None:
    ligand_artifact = tmp_path / "work" / "ligand" / "jz4.itp"
    ligand_artifact.parent.mkdir(parents=True)
    ligand_artifact.write_text("; generated topology\n", encoding="utf-8")

    result = clean_workspace(project_root=tmp_path)

    assert ligand_artifact in result.removed_paths
    assert not ligand_artifact.exists()
    assert (tmp_path / "work" / "ligand").is_dir()


def test_clean_workspace_removes_templates_when_requested(tmp_path: Path) -> None:
    ensure_workspace(config=default_config("clean_templates_test"), project_root=tmp_path)

    result = clean_workspace(project_root=tmp_path, remove_templates=True)

    assert tmp_path / "work" / "prod" / "md.mdp" in result.removed_paths
    assert not (tmp_path / "work" / "prod" / "md.mdp").exists()


def test_clean_workspace_all_work_recreates_empty_work_dirs(tmp_path: Path) -> None:
    ensure_workspace(config=default_config("clean_all_test"), project_root=tmp_path)
    artifact = tmp_path / "work" / "prep" / "complexo.pdb"
    artifact.write_text("pdb", encoding="utf-8")

    result = clean_workspace(project_root=tmp_path, all_work=True)

    assert result.removed_paths == [tmp_path / "work"]
    assert (tmp_path / "work" / "prep").is_dir()
    assert not artifact.exists()
    assert not (tmp_path / "work" / "prod" / "md.mdp").exists()
