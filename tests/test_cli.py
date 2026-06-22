from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from gmxflow.cli import app


def test_cli_startproject_creates_project(tmp_path: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["startproject", "cli_project", "--destination", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert "Projeto criado em:" in result.output
    assert (tmp_path / "cli_project" / "config.toml").is_file()


def test_cli_startproject_accepts_initial_pipeline_options(tmp_path: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "startproject",
            "cli_project",
            "--destination",
            str(tmp_path),
            "--ligand-kind",
            "small_molecule",
            "--gpu",
            "off",
            "--profile",
            "smoke",
        ],
    )

    assert result.exit_code == 0
    config_text = (tmp_path / "cli_project" / "config.toml").read_text(encoding="utf-8")
    assert 'ligand_kind = "small_molecule"' in config_text
    assert 'gpu = "off"' in config_text
    assert 'profile = "smoke"' in config_text


def test_cli_startproject_rejects_invalid_initial_pipeline_option(tmp_path: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "startproject",
            "cli_project",
            "--destination",
            str(tmp_path),
            "--profile",
            "quick",
        ],
    )

    assert result.exit_code != 0
    assert "profile inválido" in result.output


def test_cli_validate_accepts_generated_config(tmp_path: Path) -> None:
    runner = CliRunner()
    project_result = runner.invoke(
        app,
        ["startproject", "cli_project", "--destination", str(tmp_path)],
    )
    assert project_result.exit_code == 0

    config_path = tmp_path / "cli_project" / "config.toml"
    validate_result = runner.invoke(app, ["validate", "--config", str(config_path)])

    assert validate_result.exit_code == 0
    assert "config.toml" in validate_result.output
    assert "Projeto: cli_project" in validate_result.output
    assert "50000000" in validate_result.output


def test_cli_list_residues_filters_and_prints_config_value(tmp_path: Path) -> None:
    runner = CliRunner()
    project_result = runner.invoke(
        app,
        ["startproject", "cli_project", "--destination", str(tmp_path)],
    )
    assert project_result.exit_code == 0

    project = tmp_path / "cli_project"
    prep = project / "work" / "prep"
    prep.mkdir(parents=True, exist_ok=True)
    (prep / "complexo.pdb").write_text(
        "\n".join(
            [
                _atom(1, "ND1", "HIS", "A", 57, 0.0, 0.0, 0.0, "N"),
                _atom(2, "CG", "ASP", "A", 102, 0.0, 0.0, 0.0, "C"),
                _atom(3, "OG", "SER", "A", 195, 0.0, 0.0, 0.0, "O"),
                _atom(4, "CA", "ALA", "B", 57, 0.0, 0.0, 0.0, "C"),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "list-residues",
            "--config",
            str(project / "config.toml"),
            "--chain",
            "A",
            "--resnames",
            "HIS,ASP,SER",
        ],
    )

    assert result.exit_code == 0
    assert "HIS" in result.output
    assert "ASP" in result.output
    assert "SER" in result.output
    assert 'catalytic_residues = "57,102,195"' in result.output
    assert "ALA" not in result.output


def test_cli_run_dry_run_prints_pipeline_without_executing(tmp_path: Path) -> None:
    runner = CliRunner()
    project_result = runner.invoke(
        app,
        ["startproject", "cli_project", "--destination", str(tmp_path)],
    )
    assert project_result.exit_code == 0

    config_path = tmp_path / "cli_project" / "config.toml"
    result = runner.invoke(app, ["run", "--config", str(config_path), "--dry-run"])

    assert result.exit_code == 0
    assert "DRY-RUN" in result.output
    assert "gmxflow prepare-complex" in result.output
    assert "gmx pdb2gmx" in result.output
    assert "gmx mdrun" in result.output


def test_cli_run_without_until_executes_full_pipeline(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    project_result = runner.invoke(
        app,
        ["startproject", "cli_project", "--destination", str(tmp_path)],
    )
    assert project_result.exit_code == 0

    project = tmp_path / "cli_project"
    calls: dict[str, object] = {}

    def fake_workspace_setup(loaded, project_root):
        calls["workspace_project"] = project_root
        return SimpleNamespace(
            step_name="workspace",
            elapsed_seconds=0.0,
            log_path=project_root / "work" / "logs" / "00_workspace.log",
            skipped=False,
        )

    def fake_run_steps(
        steps, project_root, start_index, on_step_start=None, on_step_done=None, global_inputs=None
    ):
        calls["step_names"] = [step.name for step in steps]
        calls["start_index"] = start_index
        results = []
        for index, step in enumerate(steps, start=start_index):
            if on_step_start is not None:
                on_step_start(index, step)
            result = SimpleNamespace(
                step_name=step.name,
                elapsed_seconds=0.0,
                log_path=project_root / "work" / "logs" / f"{index:02d}_{step.name}.log",
                skipped=False,
            )
            results.append(result)
            if on_step_done is not None:
                on_step_done(index, result)
        return results

    monkeypatch.setattr("gmxflow.cli.run_workspace_setup", fake_workspace_setup)
    monkeypatch.setattr("gmxflow.cli.run_steps", fake_run_steps)

    result = runner.invoke(app, ["run", "--config", str(project / "config.toml")])

    assert result.exit_code == 0
    assert calls["workspace_project"] == project
    assert calls["step_names"] == [
        "prepare",
        "topology",
        "box",
        "solvate",
        "ions-grompp",
        "ions",
        "em-grompp",
        "em",
        "nvt-grompp",
        "nvt",
        "npt-grompp",
        "npt",
        "production-grompp",
        "production",
        "pbc-nojump",
        "pbc-center",
        "fit",
        "analysis",
        "plots",
        "report",
    ]
    assert calls["start_index"] == 1
    assert "Etapa concluída: report" in result.output


def test_cli_run_until_analysis_is_allowed(
    tmp_path: Path, monkeypatch
) -> None:
    runner = CliRunner()
    project_result = runner.invoke(
        app,
        ["startproject", "cli_project", "--destination", str(tmp_path)],
    )
    assert project_result.exit_code == 0

    project = tmp_path / "cli_project"
    calls: dict[str, object] = {}

    def fake_workspace_setup(loaded, project_root):
        calls["workspace_project"] = project_root
        return SimpleNamespace(
            step_name="workspace",
            elapsed_seconds=0.0,
            log_path=project_root / "work" / "logs" / "00_workspace.log",
            skipped=False,
        )

    def fake_run_steps(
        steps, project_root, start_index, on_step_start=None, on_step_done=None, global_inputs=None
    ):
        calls["step_names"] = [step.name for step in steps]
        calls["start_index"] = start_index
        results = []
        for index, step in enumerate(steps, start=start_index):
            if on_step_start is not None:
                on_step_start(index, step)
            result = SimpleNamespace(
                step_name=step.name,
                elapsed_seconds=0.0,
                log_path=project_root / "work" / "logs" / f"{index:02d}_{step.name}.log",
                skipped=False,
            )
            results.append(result)
            if on_step_done is not None:
                on_step_done(index, result)
        return results

    monkeypatch.setattr("gmxflow.cli.run_workspace_setup", fake_workspace_setup)
    monkeypatch.setattr("gmxflow.cli.run_steps", fake_run_steps)

    result = runner.invoke(
        app,
        [
            "run",
            "--config",
            str(project / "config.toml"),
            "--until",
            "analysis",
        ],
    )

    assert result.exit_code == 0
    assert calls["workspace_project"] == project
    assert calls["step_names"] == [
        "prepare",
        "topology",
        "box",
        "solvate",
        "ions-grompp",
        "ions",
        "em-grompp",
        "em",
        "nvt-grompp",
        "nvt",
        "npt-grompp",
        "npt",
        "production-grompp",
        "production",
        "pbc-nojump",
        "pbc-center",
        "fit",
        "analysis",
    ]
    assert calls["start_index"] == 1
    assert "Etapa concluída: analysis" in result.output


def test_cli_run_until_prepare_sets_up_workspace_and_logs(tmp_path: Path) -> None:
    runner = CliRunner()
    project_result = runner.invoke(
        app,
        ["startproject", "cli_project", "--destination", str(tmp_path)],
    )
    assert project_result.exit_code == 0

    project = tmp_path / "cli_project"
    (project / "inputs" / "receptor.pdb").write_text(
        _atom(1, "N", "HIS", "A", 1, 0, 0, 0, "N") + "\n",
        encoding="utf-8",
    )
    (project / "inputs" / "ligante.pdb").write_text(
        _atom(1, "N", "ALA", "B", 1, 1, 1, 1, "N") + "\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["run", "--config", str(project / "config.toml"), "--until", "prepare"])

    assert result.exit_code == 0
    assert "Etapa concluída: workspace" in result.output
    assert "Etapa concluída: prepare" in result.output
    assert (project / "work" / "logs" / "00_workspace.log").is_file()
    assert (project / "work" / "logs" / "01_prepare.log").is_file()
    assert (project / "work" / "prep" / "complexo.pdb").is_file()


def test_cli_run_dry_run_strict_inputs_rejects_missing_files(tmp_path: Path) -> None:
    runner = CliRunner()
    project_result = runner.invoke(
        app,
        ["startproject", "cli_project", "--destination", str(tmp_path)],
    )
    assert project_result.exit_code == 0

    config_path = tmp_path / "cli_project" / "config.toml"
    result = runner.invoke(
        app,
        ["run", "--config", str(config_path), "--dry-run", "--strict-inputs"],
    )

    assert result.exit_code != 0
    assert "Arquivo de entrada" in result.output


def test_cli_render_templates_writes_mdp_files(tmp_path: Path) -> None:
    runner = CliRunner()
    project_result = runner.invoke(
        app,
        ["startproject", "cli_project", "--destination", str(tmp_path)],
    )
    assert project_result.exit_code == 0

    config_path = tmp_path / "cli_project" / "config.toml"
    result = runner.invoke(
        app, ["render-templates", "--config", str(config_path), "--force"]
    )

    assert result.exit_code == 0
    assert "Template renderizado:" in result.output
    assert (tmp_path / "cli_project" / "work" / "prod" / "md.mdp").is_file()


def test_cli_prepare_ligand_prints_generated_files(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    project_result = runner.invoke(
        app,
        ["startproject", "cli_project", "--destination", str(tmp_path)],
    )
    assert project_result.exit_code == 0

    project = tmp_path / "cli_project"
    config_path = project / "config.toml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        .replace('ligand_mol2 = ""', 'ligand_mol2 = "inputs/lig.mol2"')
        .replace('ligand_str = ""', 'ligand_str = "inputs/lig.str"')
        .replace('ligand_resname = "LIG"', 'ligand_resname = "JZ4"'),
        encoding="utf-8",
    )

    def fake_prepare_ligand_files(loaded, project_root, force_field_dir):
        return SimpleNamespace(
            resname=loaded.input.ligand_resname,
            itp_path=project_root / "work" / "ligand" / "jz4.itp",
            prm_path=project_root / "work" / "ligand" / "jz4.prm",
            top_path=project_root / "work" / "ligand" / "jz4.top",
            pdb_path=project_root / "work" / "ligand" / "jz4_ini.pdb",
            warnings=[],
        )

    monkeypatch.setattr("gmxflow.cli.prepare_ligand_files", fake_prepare_ligand_files)

    result = runner.invoke(app, ["prepare-ligand", "--config", str(config_path)])

    assert result.exit_code == 0
    assert "Ligante preparado: JZ4" in result.output
    assert "jz4.itp" in result.output


def test_cli_clean_removes_artifacts_and_preserves_templates(tmp_path: Path) -> None:
    runner = CliRunner()
    project_result = runner.invoke(
        app,
        ["startproject", "cli_project", "--destination", str(tmp_path)],
    )
    assert project_result.exit_code == 0

    project = tmp_path / "cli_project"
    artifact = project / "work" / "prep" / "complexo.pdb"
    artifact.write_text("pdb", encoding="utf-8")

    result = runner.invoke(app, ["clean", "--config", str(project / "config.toml")])

    assert result.exit_code == 0
    assert "Workspace limpo:" in result.output
    assert "Removido:" in result.output
    assert "Preservado:" in result.output
    assert not artifact.exists()
    assert (project / "work" / "prod" / "md.mdp").is_file()


def test_cli_setup_workspace_renders_only_missing_templates(tmp_path: Path) -> None:
    runner = CliRunner()
    project_result = runner.invoke(
        app,
        ["startproject", "cli_project", "--destination", str(tmp_path)],
    )
    assert project_result.exit_code == 0

    project = tmp_path / "cli_project"
    missing_template = project / "work" / "prod" / "md.mdp"
    missing_template.unlink()

    result = runner.invoke(
        app, ["setup-workspace", "--config", str(project / "config.toml")]
    )

    assert result.exit_code == 0
    assert "Workspace preparado:" in result.output
    assert "Template renderizado:" in result.output
    assert "Template existente:" in result.output
    assert missing_template.is_file()
    assert not (project / "templates").exists()


def _atom(
    serial: int,
    atom: str,
    residue: str,
    chain: str,
    resid: int,
    x: float,
    y: float,
    z: float,
    element: str,
) -> str:
    return (
        f"ATOM  {serial:5d} {atom:<4} {residue:<3} {chain}{resid:4d}"
        f"    {x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00           {element:>2}"
    )
