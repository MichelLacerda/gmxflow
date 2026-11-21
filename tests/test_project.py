import json
from pathlib import Path

import pytest

from gmxflow.config import default_config
from gmxflow.project import available_templates, create_project, render_template


def test_available_templates_contains_mdp_templates() -> None:
    templates = set(available_templates())

    assert {
        "ions.mdp.j2",
        "em.mdp.j2",
        "nvt.mdp.j2",
        "npt.mdp.j2",
        "md.mdp.j2",
        "rerun.mdp.j2",
    }.issubset(templates)


def test_render_md_template_uses_computed_production_steps() -> None:
    rendered = render_template("md.mdp.j2", default_config("template_test"))

    assert "nsteps          = 50000000" in rendered
    assert "dt              = 0.002" in rendered


def test_create_project_writes_expected_files(tmp_path: Path) -> None:
    project_dir = create_project(
        name="mastoparan_dm",
        destination=tmp_path,
        receptor="inputs/receptor_ph82.pdb",
        ligand="inputs/ligante_ph82.pdb",
    )

    assert project_dir == tmp_path / "mastoparan_dm"
    assert (project_dir / "project.toml").is_file()
    assert not (project_dir / "config.toml").exists()
    notebook_path = project_dir / "project.ipynb"
    assert notebook_path.is_file()
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    notebook_code = "\n".join(
        "".join(cell["source"])
        for cell in notebook["cells"]
        if cell["cell_type"] == "code"
    )
    assert "GmxFlowProject.open('project.toml')" in notebook_code
    assert "project.validate()" in notebook_code
    assert "project.run()" in notebook_code
    assert "project.show_report()" in notebook_code
    assert all(not cell.get("outputs") for cell in notebook["cells"])
    assert (project_dir / "README.md").is_file()
    assert (project_dir / ".gitignore").is_file()
    assert not (project_dir / "templates").exists()
    assert (project_dir / "work" / "box" / "ions.mdp").is_file()
    assert (project_dir / "work" / "em" / "em.mdp").is_file()
    assert (project_dir / "work" / "nvt" / "nvt.mdp").is_file()
    assert (project_dir / "work" / "npt" / "npt.mdp").is_file()
    assert (project_dir / "work" / "prod" / "md.mdp").is_file()
    assert (project_dir / "inputs" / ".gitkeep").is_file()
    assert not (project_dir / "work" / ".gitkeep").exists()
    assert not (project_dir / "outputs" / ".gitkeep").exists()

    config_text = (project_dir / "project.toml").read_text(encoding="utf-8")
    assert 'name = "mastoparan_dm"' in config_text
    assert 'description = "Simulação de dinâmica molecular com GROMACS"' in config_text
    assert "# [paths]" in config_text
    assert 'receptor_pdb = "inputs/receptor_ph82.pdb"' in config_text
    assert 'ligand_pdb = "inputs/ligante_ph82.pdb"' in config_text
    assert "[plots]" in config_text
    assert 'ligand_color = "#C2185B"' in config_text

    readme_text = (project_dir / "README.md").read_text(encoding="utf-8")
    assert "## Como usar" in readme_text
    assert "## Configuração" in readme_text
    assert "project.show_report()" in readme_text
    assert "outputs/report.html" in readme_text
    assert "gmxflow prepare-complex --project project.toml" in readme_text
    assert "gmxflow run --project project.toml --until prepare" in readme_text
    assert "gmxflow clean --project project.toml" in readme_text
    assert "gmxflow render-templates --project project.toml" in readme_text
    assert "gmxflow report --project project.toml" in readme_text
    assert "gmxflow startproject novo_projeto --ligand-kind small_molecule --profile smoke --gpu off" in readme_text
    assert "gmxflow prepare-ligand --project project.toml" in readme_text
    assert "sudo apt install openbabel" in readme_text
    assert "obabel inputs/ligand.pdb -O inputs/ligand.mol2" in readme_text
    assert "valida a lista de átomos entre `.mol2` e `.str`" in readme_text
    assert "work/logs/00_workspace.log" in readme_text
    assert "`work/`, `outputs/`, caches Python" in readme_text
    assert 'ligand_kind = "small_molecule"' in readme_text
    assert "### `[simulation]`" in readme_text
    assert "### `[plots]`" in readme_text
    assert "vermelho cereja" in readme_text
    assert "50.000.000" in readme_text
    assert 'profile = "smoke"' in readme_text

    gitignore_text = (project_dir / ".gitignore").read_text(encoding="utf-8")
    assert "work/" in gitignore_text
    assert "!work/.gitkeep" not in gitignore_text
    assert "outputs/" in gitignore_text
    assert "!outputs/.gitkeep" not in gitignore_text


def test_create_project_accepts_initial_pipeline_options(tmp_path: Path) -> None:
    project_dir = create_project(
        name="benzamidine",
        destination=tmp_path,
        ligand_kind="small_molecule",
        gpu="off",
        profile="smoke",
    )

    config_text = (project_dir / "project.toml").read_text(encoding="utf-8")
    assert 'ligand_kind = "small_molecule"' in config_text
    assert 'gpu = "off"' in config_text
    assert 'profile = "smoke"' in config_text
    assert "nsteps          = 10" in (project_dir / "work" / "prod" / "md.mdp").read_text(
        encoding="utf-8"
    )


def test_create_project_rejects_invalid_initial_pipeline_options(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ligand_kind inválido"):
        create_project(name="invalid", destination=tmp_path, ligand_kind="drug")


def test_create_project_refuses_existing_directory_without_force(tmp_path: Path) -> None:
    create_project(name="existing", destination=tmp_path)

    with pytest.raises(FileExistsError):
        create_project(name="existing", destination=tmp_path)
