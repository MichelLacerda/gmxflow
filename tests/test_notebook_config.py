from __future__ import annotations

from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Any

from gmxflow import notebook_config
from gmxflow.api import GmxFlowProject
from gmxflow.config import GmxFlowConfig, default_config, to_toml


def _project(tmp_path: Path) -> GmxFlowProject:
    project_dir = tmp_path / "form_project"
    project_dir.mkdir()
    config_path = project_dir / "project.toml"
    config_path.write_text(to_toml(default_config("form_project")), encoding="utf-8")
    return GmxFlowProject.open(config_path)


def _config_with_description(config: GmxFlowConfig, description: str) -> GmxFlowConfig:
    data = config.model_dump(mode="python")
    data["project"]["description"] = description
    return GmxFlowConfig.model_validate(data)


def test_edit_config_form_saves_validated_values_and_preserves_toml(
    tmp_path: Path, monkeypatch
) -> None:
    project = _project(tmp_path)
    original = project.config_path.read_text(encoding="utf-8")
    original += "\n# User note that should survive the form.\n[custom]\nkeep = \"yes\"\n"
    project.config_path.write_text(original, encoding="utf-8")
    project = GmxFlowProject.open(project.config_path)
    displayed: list[Any] = []

    class FakeMarkdown:
        def __init__(self, text: str) -> None:
            self.text = text

    display_module = ModuleType("IPython.display")
    display_module.Markdown = FakeMarkdown
    display_module.display = displayed.append
    real_import_module = notebook_config.import_module

    def fake_import_module(name: str) -> Any:
        if name == "IPython.display":
            return display_module
        return real_import_module(name)

    monkeypatch.setattr(notebook_config, "import_module", fake_import_module)
    form = project.edit_config()
    accordion = form.children[1]
    description_control = next(
        widget
        for section in accordion.children
        for row in section.children
        for widget in getattr(row, "children", ())
        if getattr(widget, "description", "") == "Descrição"
    )
    description_control.value = "Configuração atualizada pelo formulário"
    save_button = form.children[2]
    save_button.click()

    saved = project.config_path.read_text(encoding="utf-8")
    assert 'description = "Configuração atualizada pelo formulário"' in saved
    assert "# User note that should survive the form." in saved
    assert '[custom]\nkeep = "yes"' in saved
    assert project.config.project.description == "Configuração atualizada pelo formulário"
    assert displayed
    assert "validada e salva" in displayed[-1].text


def test_write_config_updates_refuses_external_edits(tmp_path: Path) -> None:
    project = _project(tmp_path)
    original = project.config_path.read_bytes()
    project.config_path.write_bytes(original + b"\n# concurrent edit\n")

    try:
        notebook_config._write_config_updates(
            project.config_path,
            expected_content=original,
            config=_config_with_description(project.config, "new description"),
            updates={"project": {"description": "new description"}},
            tomlkit=import_module("tomlkit"),
        )
    except RuntimeError as error:
        assert "foi alterado enquanto o formulário estava aberto" in str(error)
    else:
        raise AssertionError("A edição concorrente deveria impedir o salvamento.")

    assert project.config_path.read_bytes().endswith(b"# concurrent edit\n")


def test_write_config_updates_keeps_existing_comments_and_custom_keys(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    original = project.config_path.read_bytes()
    original = original.replace(
        b'description = "Simula\xc3\xa7\xc3\xa3o de din\xc3\xa2mica molecular com GROMACS"',
        b'description = "Simula\xc3\xa7\xc3\xa3o de din\xc3\xa2mica molecular com GROMACS" # inline note',
    )
    original += b"\n# User note.\n[custom]\nkey = \"retained\"\n"
    project.config_path.write_bytes(original)
    config = _config_with_description(project.config, "Saved from form")

    notebook_config._write_config_updates(
        project.config_path,
        expected_content=original,
        config=config,
        updates={"project": {"description": "Saved from form"}},
        tomlkit=import_module("tomlkit"),
    )

    saved = project.config_path.read_text(encoding="utf-8")
    assert 'description = "Saved from form"' in saved
    assert "# User note." in saved
    assert "# inline note" in saved
    assert '[custom]\nkey = "retained"' in saved
