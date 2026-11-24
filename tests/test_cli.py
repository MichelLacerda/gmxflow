import json
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from gmxflow.api import GmxFlowProject
from gmxflow.cli import app
from gmxflow.config import to_toml
from gmxflow.executor import WorkflowStepResult, WorkflowStepStatus


def test_cli_startproject_creates_project(tmp_path: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["startproject", "cli_project", "--destination", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert "Projeto criado em:" in result.output
    assert (tmp_path / "cli_project" / "project.toml").is_file()
    assert "Notebook Jupyter:" in result.output
    assert (tmp_path / "cli_project" / "project.ipynb").is_file()


def test_solvate_system_preserves_original_topology(
    tmp_path: Path, monkeypatch
) -> None:
    runner = CliRunner()
    created = runner.invoke(
        app,
        ["startproject", "solvate_project", "--destination", str(tmp_path)],
    )
    assert created.exit_code == 0
    project = tmp_path / "solvate_project"
    topology_dir = project / "work" / "topo"
    topology_dir.mkdir(parents=True, exist_ok=True)
    original = topology_dir / "topol.top"
    original.write_text(
        "[ molecules ]\nProtein 1\nSOL 4\n",
        encoding="utf-8",
    )
    original_content = original.read_text(encoding="utf-8")
    output_topology = topology_dir / "topol_solvated.top"
    commands: list[list[str]] = []

    def fake_subprocess_run(command, **kwargs):
        commands.append(command)
        output_path = Path(command[command.index("-p") + 1])
        output_path.write_text(output_path.read_text(encoding="utf-8") + "; solvated\n")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("gmxflow.cli.subprocess.run", fake_subprocess_run)
    result = runner.invoke(
        app,
        [
            "solvate-system",
            "--project",
            str(project / "project.toml"),
            "--topology-output",
            str(output_topology),
        ],
    )

    assert result.exit_code == 0, result.output
    assert original.read_text(encoding="utf-8") == original_content
    assert "SOL 4" not in output_topology.read_text(encoding="utf-8")
    assert "; solvated" in output_topology.read_text(encoding="utf-8")
    assert commands[0][commands[0].index("-p") + 1] == str(output_topology)


def test_genion_system_preserves_solvated_topology(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    created = runner.invoke(
        app,
        ["startproject", "ions_project", "--destination", str(tmp_path)],
    )
    assert created.exit_code == 0
    project = tmp_path / "ions_project"
    topology_dir = project / "work" / "topo"
    topology_dir.mkdir(parents=True, exist_ok=True)
    solvated = topology_dir / "topol_solvated.top"
    solvated.write_text("[ molecules ]\nProtein 1\nSOL 25\n", encoding="utf-8")
    solvated_content = solvated.read_text(encoding="utf-8")
    ionized = topology_dir / "topol_ions.top"
    commands: list[list[str]] = []
    inputs: list[str | None] = []

    def fake_subprocess_run(command, *, input=None, **kwargs):
        commands.append(command)
        inputs.append(input)
        output_path = Path(command[command.index("-p") + 1])
        output_path.write_text(output_path.read_text(encoding="utf-8") + "; ions\n")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("gmxflow.cli.subprocess.run", fake_subprocess_run)
    result = runner.invoke(
        app,
        [
            "genion-system",
            "--project",
            str(project / "project.toml"),
            "--topology-input",
            str(solvated),
            "--topology-output",
            str(ionized),
        ],
    )

    assert result.exit_code == 0, result.output
    assert solvated.read_text(encoding="utf-8") == solvated_content
    assert "; ions" in ionized.read_text(encoding="utf-8")
    assert commands[0][commands[0].index("-p") + 1] == str(ionized)
    assert inputs == ["SOL\n"]


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
    config_text = (tmp_path / "cli_project" / "project.toml").read_text(
        encoding="utf-8"
    )
    assert 'ligand_kind = "small_molecule"' in config_text
    assert 'gpu = "off"' in config_text
    assert 'profile = "smoke"' in config_text


def test_cli_startproject_rejects_invalid_initial_pipeline_option(
    tmp_path: Path,
) -> None:
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

    config_path = tmp_path / "cli_project" / "project.toml"
    validate_result = runner.invoke(app, ["validate", "--project", str(config_path)])

    assert validate_result.exit_code == 0
    assert "project.toml" in validate_result.output
    assert "Projeto: cli_project" in validate_result.output
    assert "50000000" in validate_result.output


def test_cli_validate_rejects_renamed_config_option(tmp_path: Path) -> None:
    project_result = CliRunner().invoke(
        app,
        ["startproject", "cli_project", "--destination", str(tmp_path)],
    )
    assert project_result.exit_code == 0

    config_path = tmp_path / "cli_project" / "project.toml"
    result = CliRunner().invoke(app, ["validate", "--config", str(config_path)])

    assert result.exit_code != 0
    assert "--config" in result.output


def test_cli_validate_defaults_to_project_toml(tmp_path: Path, monkeypatch) -> None:
    project_dir = tmp_path / "cli_project"
    project_result = CliRunner().invoke(
        app,
        ["startproject", "cli_project", "--destination", str(tmp_path)],
    )
    assert project_result.exit_code == 0
    monkeypatch.chdir(project_dir)

    validate_result = CliRunner().invoke(app, ["validate"])

    assert validate_result.exit_code == 0
    assert "Configuração válida: project.toml" in validate_result.output


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
            "--project",
            str(project / "project.toml"),
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

    config_path = tmp_path / "cli_project" / "project.toml"
    result = runner.invoke(app, ["run", "--project", str(config_path), "--dry-run"])

    assert result.exit_code == 0
    assert "DRY-RUN" in result.output
    assert "gmxflow prepare-complex" in result.output
    assert "gmx pdb2gmx" in result.output
    assert "gmx mdrun" in result.output
    assert "depende de: prepare" in result.output
    assert not (config_path.parent / "work" / "state.json").exists()
    assert not (config_path.parent / "work" / "logs" / "01_prepare.log").exists()


def test_cli_run_without_until_executes_full_pipeline(
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

    def fake_run_workflow(self, workflow, **kwargs):
        calls["project_root"] = self.root
        calls["step_ids"] = [step.id for step in workflow.items]
        calls["state_name"] = kwargs["state_name"]
        for step in workflow.items:
            kwargs["on_step_start"](step)
            kwargs["on_step_done"](
                WorkflowStepResult(
                    step_id=step.id,
                    status=WorkflowStepStatus.SUCCEEDED,
                    log_path=self.root / "work" / "logs" / f"{step.id}.log",
                )
            )
        return SimpleNamespace()

    monkeypatch.setattr("gmxflow.cli.GmxFlowProject.run_workflow", fake_run_workflow)

    result = runner.invoke(app, ["run", "--project", str(project / "project.toml")])

    assert result.exit_code == 0
    assert calls["project_root"] == project
    assert calls["state_name"] == "state.json"
    assert calls["step_ids"] == [
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
        "thermodynamics",
        "plots",
        "report",
    ]
    assert "Etapa concluída: report" in result.output


def test_cli_run_until_analysis_is_allowed(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    project_result = runner.invoke(
        app,
        ["startproject", "cli_project", "--destination", str(tmp_path)],
    )
    assert project_result.exit_code == 0

    project = tmp_path / "cli_project"
    calls: dict[str, object] = {}

    def fake_run_workflow(self, workflow, **kwargs):
        calls["step_ids"] = [step.id for step in workflow.items]
        for step in workflow.items:
            kwargs["on_step_start"](step)
            kwargs["on_step_done"](
                WorkflowStepResult(
                    step_id=step.id,
                    status=WorkflowStepStatus.SUCCEEDED,
                    log_path=self.root / "work" / "logs" / f"{step.id}.log",
                )
            )
        return SimpleNamespace()

    monkeypatch.setattr("gmxflow.cli.GmxFlowProject.run_workflow", fake_run_workflow)

    result = runner.invoke(
        app,
        [
            "run",
            "--project",
            str(project / "project.toml"),
            "--until",
            "analysis",
        ],
    )

    assert result.exit_code == 0
    assert calls["step_ids"] == [
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
    state_path = project / "work" / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text('{"old_state": true}\n', encoding="utf-8")

    result = runner.invoke(
        app, ["run", "--project", str(project / "project.toml"), "--until", "prepare"]
    )

    assert result.exit_code == 0
    assert "Preparando workspace do projeto:" in result.output
    assert "Etapa concluída: prepare" in result.output
    assert (project / "work" / "logs" / "00_workspace.log").is_file()
    assert (project / "work" / "logs" / "01_prepare.log").is_file()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["steps"]["prepare"]["workflow_step"] is True
    assert (project / "work" / "prep" / "complexo.pdb").is_file()


def test_cli_run_dry_run_strict_inputs_rejects_missing_files(tmp_path: Path) -> None:
    runner = CliRunner()
    project_result = runner.invoke(
        app,
        ["startproject", "cli_project", "--destination", str(tmp_path)],
    )
    assert project_result.exit_code == 0

    config_path = tmp_path / "cli_project" / "project.toml"
    result = runner.invoke(
        app,
        ["run", "--project", str(config_path), "--dry-run", "--strict-inputs"],
    )

    assert result.exit_code != 0
    assert "Arquivo de entrada" in result.output


def test_cli_run_strict_inputs_requires_small_molecule_parameters(
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    created = runner.invoke(
        app,
        ["startproject", "ligand_project", "--destination", str(tmp_path)],
    )
    assert created.exit_code == 0

    project_dir = tmp_path / "ligand_project"
    config_path = project_dir / "project.toml"
    project = GmxFlowProject.open(config_path)
    project.config.input.ligand_kind = "small_molecule"
    project.config.input.ligand_mol2 = "inputs/ligand.mol2"
    project.config.input.ligand_str = "inputs/ligand.str"
    (project_dir / "inputs" / "receptor.pdb").write_text("ATOM\n", encoding="utf-8")
    (project_dir / "inputs" / "ligante.pdb").write_text("HETATM\n", encoding="utf-8")
    (project_dir / "inputs" / "ligand.str").write_text("RESI LIG\n", encoding="utf-8")
    config_path.write_text(to_toml(project.config), encoding="utf-8")

    result = runner.invoke(
        app,
        ["run", "--project", str(config_path), "--dry-run", "--strict-inputs"],
    )

    assert result.exit_code != 0
    assert "ligand.mol2" in result.output


def test_cli_render_templates_writes_mdp_files(tmp_path: Path) -> None:
    runner = CliRunner()
    project_result = runner.invoke(
        app,
        ["startproject", "cli_project", "--destination", str(tmp_path)],
    )
    assert project_result.exit_code == 0

    config_path = tmp_path / "cli_project" / "project.toml"
    result = runner.invoke(
        app, ["render-templates", "--project", str(config_path), "--force"]
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
    config_path = project / "project.toml"
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

    result = runner.invoke(app, ["prepare-ligand", "--project", str(config_path)])

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

    result = runner.invoke(app, ["clean", "--project", str(project / "project.toml")])

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
        app, ["setup-workspace", "--project", str(project / "project.toml")]
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
