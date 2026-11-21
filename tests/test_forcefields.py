from pathlib import Path

import pytest
from typer.testing import CliRunner

from gmxflow.cli import app
from gmxflow.forcefields import (
    install_forcefield,
    resolve_forcefield,
    user_forcefield_root,
    validate_forcefield_directory,
)


def _make_forcefield(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "forcefield.itp").write_text("; test force field\n", encoding="utf-8")
    (path / "forcefield.doc").write_text("test force field\n", encoding="utf-8")
    return path


def test_user_forcefield_root_respects_xdg_data_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GMXFLOW_FORCEFIELD_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    assert user_forcefield_root() == tmp_path / "data" / "gmxflow" / "forcefields"


def test_user_forcefield_root_can_be_overridden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "custom forcefields"
    monkeypatch.setenv("GMXFLOW_FORCEFIELD_DIR", str(root))

    assert user_forcefield_root() == root


def test_install_forcefield_copies_without_overwriting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_forcefield(tmp_path / "source" / "custom.ff")
    root = tmp_path / "central"
    monkeypatch.setenv("GMXFLOW_FORCEFIELD_DIR", str(root))

    installed = install_forcefield(source)

    assert installed == root / "custom.ff"
    assert (installed / "forcefield.itp").is_file()
    with pytest.raises(FileExistsError, match="Nada foi sobrescrito"):
        install_forcefield(source)


def test_resolver_prefers_installed_then_central_then_legacy_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    central = _make_forcefield(tmp_path / "central" / "custom.ff")
    legacy = _make_forcefield(project / "custom.ff")
    monkeypatch.setenv("GMXFLOW_FORCEFIELD_DIR", str(central.parent))
    monkeypatch.setattr("gmxflow.forcefields._installed_roots", lambda: [])

    resolved = resolve_forcefield("custom", project)
    assert resolved is not None
    assert resolved.path == central
    assert resolved.source == "user"
    assert resolved.gmxlib == central.parent

    central.rename(tmp_path / "central" / "custom.disabled")
    resolved = resolve_forcefield("custom", project)
    assert resolved is not None
    assert resolved.path == legacy
    assert resolved.source == "project"

    installed = _make_forcefield(tmp_path / "gromacs" / "custom.ff")
    monkeypatch.setattr(
        "gmxflow.forcefields._installed_roots", lambda: [installed.parent]
    )
    resolved = resolve_forcefield("custom", project)
    assert resolved is not None
    assert resolved.path == installed
    assert resolved.source == "gromacs"
    assert resolved.gmxlib is None


def test_validate_forcefield_requires_gromacs_files(tmp_path: Path) -> None:
    incomplete = tmp_path / "incomplete.ff"
    incomplete.mkdir()

    with pytest.raises(ValueError, match="forcefield.itp, forcefield.doc"):
        validate_forcefield_directory(incomplete)


def test_forcefield_cli_installs_and_lists_forcefield(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _make_forcefield(tmp_path / "download" / "custom.ff")
    monkeypatch.setenv("GMXFLOW_FORCEFIELD_DIR", str(tmp_path / "central"))
    runner = CliRunner()

    installed = runner.invoke(app, ["forcefield", "install", str(source)])
    listed = runner.invoke(app, ["forcefield", "list"])

    assert installed.exit_code == 0
    assert "custom.ff" in installed.output
    assert listed.exit_code == 0
    assert "custom" in listed.output
