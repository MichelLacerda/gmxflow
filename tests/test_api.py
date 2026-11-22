from pathlib import Path
from types import SimpleNamespace

import pytest

from gmxflow.api import ExecutionReport, GmxFlowProject
from gmxflow.config import default_config, to_toml
from gmxflow.executor import (
    StepResult,
    WorkflowExecutionReport,
    WorkflowStepResult,
    WorkflowStepStatus,
    run_steps,
    runtime_command,
)
from gmxflow.pipeline import build_pipeline


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


def test_create_generates_and_opens_project(tmp_path: Path) -> None:
    project = GmxFlowProject.create(
        "notebook_project",
        destination=tmp_path,
        receptor="inputs/receptor.pdb",
        ligand="inputs/ligand.pdb",
        profile="smoke",
        gpu="off",
    )

    assert project.root == (tmp_path / "notebook_project").resolve()
    assert project.config_path == project.root / "project.toml"
    assert project.config.project.name == "notebook_project"
    assert project.config.input.receptor_pdb == "inputs/receptor.pdb"
    assert project.config.input.ligand_pdb == "inputs/ligand.pdb"
    assert project.config.simulation.profile == "smoke"
    assert project.config.mdrun.gpu == "off"
    assert (project.root / "project.ipynb").is_file()
    assert (project.root / "README.md").is_file()


def test_create_refuses_existing_project_without_force(tmp_path: Path) -> None:
    project_dir = tmp_path / "existing_project"
    project_dir.mkdir()
    marker = project_dir / "keep.txt"
    marker.write_text("user data", encoding="utf-8")

    with pytest.raises(FileExistsError):
        GmxFlowProject.create("existing_project", destination=tmp_path)

    assert marker.read_text(encoding="utf-8") == "user data"


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


def test_edit_config_delegates_to_notebook_form(
    tmp_path: Path, monkeypatch
) -> None:
    project = GmxFlowProject.open(_write_project_config(tmp_path / "api_project"))
    shown_projects: list[GmxFlowProject] = []
    monkeypatch.setattr(
        "gmxflow.notebook_config.edit_project_config", shown_projects.append
    )

    result = project.edit_config()

    assert result is None
    assert shown_projects == [project]


def test_show_execution_delegates_execution_results(
    tmp_path: Path, monkeypatch
) -> None:
    project = GmxFlowProject.open(_write_project_config(tmp_path / "api_project"))
    result = StepResult(
        step_name="prepare",
        command=["gmxflow", "prepare-complex"],
        workdir=project.root / "work" / "prep",
        log_path=project.root / "work" / "logs" / "01_prepare.log",
        returncode=0,
        elapsed_seconds=0.25,
    )
    report = ExecutionReport(workspace=result, steps=(result,))
    shown_results: list[tuple[StepResult, ...]] = []
    monkeypatch.setattr(
        "gmxflow.notebook.show_execution", shown_results.append
    )

    project.show_execution(report)

    assert shown_results == [(result, result)]


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


def test_validate_requires_mdanalysis_for_residue_filtering(
    tmp_path: Path, monkeypatch
) -> None:
    project_dir = tmp_path / "api_project"
    config_path = _write_project_config(project_dir)
    config_text = (
        config_path.read_text(encoding="utf-8")
        .replace('ligand_kind = "peptide"', 'ligand_kind = "none"')
        .replace('remove_resnames = []', 'remove_resnames = ["HOH"]')
    )
    config_path.write_text(config_text, encoding="utf-8")
    (project_dir / "inputs").mkdir()
    (project_dir / "inputs" / "receptor.pdb").write_text("ATOM\n", encoding="utf-8")
    force_field = project_dir / "amber99sb-ildn.ff"
    force_field.mkdir()
    (force_field / "forcefield.itp").write_text("; test\n", encoding="utf-8")
    (force_field / "forcefield.doc").write_text("test\n", encoding="utf-8")
    monkeypatch.setattr("gmxflow.forcefields._installed_roots", lambda: [])
    monkeypatch.setenv("GMXFLOW_FORCEFIELD_DIR", str(tmp_path / "user-forcefields"))
    monkeypatch.setattr(
        "gmxflow.api.shutil.which", lambda command: "/opt/gromacs/bin/gmx"
    )

    def missing_dependency(name: str) -> None:
        raise ImportError(name)

    monkeypatch.setattr("gmxflow.preparation.structure.import_module", missing_dependency)
    project = GmxFlowProject.open(config_path)

    with pytest.raises(RuntimeError, match="Instale `mdanalysis`"):
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
        command=runtime_command(
            project.plan(until="prepare")[0].command
        ),
        workdir=project.root / "work" / "prep",
        log_path=project.root / "work" / "logs" / "01_prepare.log",
        returncode=0,
        elapsed_seconds=0.2,
    )
    topology_result = StepResult(
        step_name="topology",
        command=project.plan(until="topology")[1].command,
        workdir=project.root / "work" / "topo",
        log_path=project.root / "work" / "logs" / "02_topology.log",
        returncode=0,
        elapsed_seconds=0.3,
    )
    box_result = StepResult(
        step_name="box",
        command=runtime_command(project.plan(until="box")[2].command),
        workdir=project.root / "work" / "box",
        log_path=project.root / "work" / "logs" / "03_box.log",
        returncode=0,
        elapsed_seconds=0.4,
    )
    solvate_result = StepResult(
        step_name="solvate",
        command=runtime_command(project.plan(until="solvate")[3].command),
        workdir=project.root / "work" / "box",
        log_path=project.root / "work" / "logs" / "04_solvate.log",
        returncode=0,
        elapsed_seconds=0.5,
    )
    ions_grompp_result = StepResult(
        step_name="ions-grompp",
        command=runtime_command(project.plan(until="ions-grompp")[4].command),
        workdir=project.root / "work" / "box",
        log_path=project.root / "work" / "logs" / "05_ions-grompp.log",
        returncode=0,
        elapsed_seconds=0.6,
    )
    ions_result = StepResult(
        step_name="ions",
        command=runtime_command(project.plan(until="ions")[5].command),
        workdir=project.root / "work" / "box",
        log_path=project.root / "work" / "logs" / "06_ions.log",
        returncode=0,
        elapsed_seconds=0.7,
    )

    monkeypatch.setattr(
        "gmxflow.api.GmxFlowProject.validate",
        lambda self: events.append("validate"),
    )
    monkeypatch.setattr(
        "gmxflow.api.run_workspace_setup",
        lambda config, project_root: events.append("workspace") or workspace,
    )

    def fake_run_workflow_graph(graph, **kwargs):
        events.append("workflow_graph")
        assert graph.topological_order == (
            "prepare",
            "topology",
            "box",
            "solvate",
            "ions-grompp",
        )
        assert kwargs["project_root"] == project.root
        step_results = {
            "prepare": step_result,
            "topology": topology_result,
            "box": box_result,
            "solvate": solvate_result,
            "ions-grompp": ions_grompp_result,
        }
        return WorkflowExecutionReport(
            results=tuple(
                WorkflowStepResult(
                    step_id=step_id,
                    status=WorkflowStepStatus.SUCCEEDED,
                    log_path=step_results[step_id].log_path,
                    elapsed_seconds=step_results[step_id].elapsed_seconds,
                )
                for step_id in graph.topological_order
            ),
            dependencies=graph.dependencies,
            artifact_paths=kwargs["artifact_paths"],
        )

    monkeypatch.setattr("gmxflow.api.run_workflow_graph", fake_run_workflow_graph)

    def fake_run_steps(steps, **kwargs):
        events.append("run_steps")
        assert [step.name for step in steps] == ["ions"]
        assert kwargs["project_root"] == project.root
        assert kwargs["start_index"] == 6
        return [ions_result]

    monkeypatch.setattr("gmxflow.api.run_steps", fake_run_steps)

    report = project.run(until="ions")

    assert events == ["validate", "workspace", "workflow_graph", "run_steps"]
    assert report.workspace is workspace
    assert report.steps == (
        step_result,
        topology_result,
        box_result,
        solvate_result,
        ions_grompp_result,
        ions_result,
    )
    assert report.results == (
        workspace,
        step_result,
        topology_result,
        box_result,
        solvate_result,
        ions_grompp_result,
        ions_result,
    )


def test_graph_prefix_through_ions_grompp_matches_legacy_commands_and_outputs(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = tmp_path / "graph_project"
    project = GmxFlowProject.open(_write_project_config(project_root))
    (project_root / "inputs").mkdir()
    (project_root / "inputs" / "receptor.pdb").write_text("ATOM\n", encoding="utf-8")
    (project_root / "inputs" / "ligante.pdb").write_text("ATOM\n", encoding="utf-8")
    graph_ions_mdp = project_root / "work" / "box" / "ions.mdp"
    graph_ions_mdp.parent.mkdir(parents=True)
    graph_ions_mdp.write_text("MDP\n", encoding="utf-8")
    legacy_state = project_root / "work" / "state.json"
    legacy_state.parent.mkdir(parents=True, exist_ok=True)
    legacy_state.write_text(
        '{"version": 1, "steps": {"prepare": {"status": "success"}}}\n',
        encoding="utf-8",
    )
    legacy_state_before = legacy_state.read_bytes()

    legacy_root = tmp_path / "legacy_project"
    legacy_config = _write_project_config(legacy_root)
    (legacy_root / "inputs").mkdir()
    (legacy_root / "inputs" / "receptor.pdb").write_text("ATOM\n", encoding="utf-8")
    (legacy_root / "inputs" / "ligante.pdb").write_text("ATOM\n", encoding="utf-8")
    legacy_ions_mdp = legacy_root / "work" / "box" / "ions.mdp"
    legacy_ions_mdp.parent.mkdir(parents=True)
    legacy_ions_mdp.write_text("MDP\n", encoding="utf-8")

    subprocess_calls: list[tuple[str, ...]] = []

    def fake_subprocess_run(command, *, cwd, **kwargs):
        subprocess_calls.append(tuple(command))
        if "prepare-complex" in command:
            output_content = {
                "receptor_fixed.pdb": "RECEPTOR\n",
                "ligante_fixed.pdb": "LIGAND\n",
                "complexo.pdb": "COMPLEX\n",
            }
        elif "editconf" in command:
            output_content = {"box.gro": "BOX\n"}
        elif "solvate-system" in command:
            output_content = {"solv.gro": "SOLV\n"}
            output_topology = Path(
                command[command.index("--topology-output") + 1]
            )
            source_topology = output_topology.parent / "topol.top"
            output_topology.write_text(
                source_topology.read_text(encoding="utf-8") + "SOLVATED\n",
                encoding="utf-8",
            )
        elif "grompp" in command:
            output_content = {"ions.tpr": "IONS_TPR\n", "mdout.mdp": "MDTOUT\n"}
        else:
            output_content = {
                "complexo.gro": "GRO\n",
                "topol.top": "TOP\n",
                "topol_Protein_chain_A.itp": "CHAIN_A\n",
                "topol_Protein_chain_B.itp": "CHAIN_B\n",
                "posre_Protein_chain_A.itp": "POSRE_A\n",
                "posre_Protein_chain_B.itp": "POSRE_B\n",
            }
        for filename, content in output_content.items():
            (Path(cwd) / filename).write_text(content, encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("gmxflow.executor.subprocess.run", fake_subprocess_run)
    monkeypatch.setattr("gmxflow.api.GmxFlowProject.validate", lambda self: None)
    monkeypatch.setattr(
        "gmxflow.api.run_workspace_setup",
        lambda config, project_root: StepResult(
            step_name="workspace",
            command=["<internal>", "ensure-workspace"],
            workdir=project_root / "work",
            log_path=project_root / "work" / "logs" / "00_workspace.log",
            returncode=0,
            elapsed_seconds=0.0,
        ),
    )

    callback_events: list[tuple[str, int, str]] = []
    graph_report = project.run(
        until="ions-grompp",
        on_step_start=lambda index, step: callback_events.append(
            ("start", index, step.name)
        ),
        on_step_done=lambda index, result: callback_events.append(
            ("done", index, result.step_name)
        ),
    )
    resumed_report = project.run(until="ions-grompp")

    topology_only_root = tmp_path / "topology_only_project"
    topology_only_project = GmxFlowProject.open(
        _write_project_config(topology_only_root)
    )
    topology_only_inputs = topology_only_root / "inputs"
    topology_only_inputs.mkdir()
    (topology_only_inputs / "receptor.pdb").write_text("ATOM\n", encoding="utf-8")
    (topology_only_inputs / "ligante.pdb").write_text("ATOM\n", encoding="utf-8")
    prepared_structure = topology_only_root / "work" / "prep" / "complexo.pdb"
    prepared_structure.parent.mkdir(parents=True)
    prepared_structure.write_text("COMPLEX\n", encoding="utf-8")
    topology_only_report = topology_only_project.run(
        from_step="topology",
        until="topology",
    )

    box_only_root = tmp_path / "box_only_project"
    box_only_project = GmxFlowProject.open(_write_project_config(box_only_root))
    box_only_inputs = box_only_root / "inputs"
    box_only_inputs.mkdir()
    (box_only_inputs / "receptor.pdb").write_text("ATOM\n", encoding="utf-8")
    (box_only_inputs / "ligante.pdb").write_text("ATOM\n", encoding="utf-8")
    topology_dir = box_only_root / "work" / "topo"
    topology_dir.mkdir(parents=True)
    (topology_dir / "complexo.gro").write_text("GRO\n", encoding="utf-8")
    box_only_report = box_only_project.run(from_step="box", until="box")

    solvate_only_root = tmp_path / "solvate_only_project"
    solvate_only_project = GmxFlowProject.open(_write_project_config(solvate_only_root))
    solvate_only_inputs = solvate_only_root / "inputs"
    solvate_only_inputs.mkdir()
    (solvate_only_inputs / "receptor.pdb").write_text("ATOM\n", encoding="utf-8")
    (solvate_only_inputs / "ligante.pdb").write_text("ATOM\n", encoding="utf-8")
    solvate_only_topology = solvate_only_root / "work" / "topo" / "topol.top"
    solvate_only_topology.parent.mkdir(parents=True)
    solvate_only_topology.write_text("TOP\n", encoding="utf-8")
    solvate_only_box = solvate_only_root / "work" / "box" / "box.gro"
    solvate_only_box.parent.mkdir(parents=True)
    solvate_only_box.write_text("BOX\n", encoding="utf-8")
    solvate_only_report = solvate_only_project.run(
        from_step="solvate",
        until="solvate",
    )

    ions_grompp_only_root = tmp_path / "ions_grompp_only_project"
    ions_grompp_only_project = GmxFlowProject.open(
        _write_project_config(ions_grompp_only_root)
    )
    ions_grompp_only_inputs = ions_grompp_only_root / "inputs"
    ions_grompp_only_inputs.mkdir()
    (ions_grompp_only_inputs / "receptor.pdb").write_text(
        "ATOM\n", encoding="utf-8"
    )
    (ions_grompp_only_inputs / "ligante.pdb").write_text(
        "ATOM\n", encoding="utf-8"
    )
    ions_grompp_only_topology = (
        ions_grompp_only_root / "work" / "topo" / "topol_solvated.top"
    )
    ions_grompp_only_topology.parent.mkdir(parents=True)
    ions_grompp_only_topology.write_text("SOLVATED\n", encoding="utf-8")
    ions_grompp_only_box = ions_grompp_only_root / "work" / "box"
    ions_grompp_only_box.mkdir(parents=True)
    (ions_grompp_only_box / "ions.mdp").write_text("MDP\n", encoding="utf-8")
    (ions_grompp_only_box / "solv.gro").write_text("SOLV\n", encoding="utf-8")
    ions_grompp_only_report = ions_grompp_only_project.run(
        from_step="ions-grompp",
        until="ions-grompp",
    )

    legacy_steps = build_pipeline(
        project.config,
        config_dir=legacy_root,
        config_path=legacy_config,
    )[:5]
    legacy_results = run_steps(legacy_steps, project_root=legacy_root)

    assert len(graph_report.steps) == len(legacy_results) == 5
    for graph_result, legacy_result in zip(graph_report.steps, legacy_results):
        graph_command = [
            argument.replace(str(project_root), "<project-root>")
            for argument in graph_result.command
        ]
        legacy_command = [
            argument.replace(str(legacy_root), "<project-root>")
            for argument in legacy_result.command
        ]
        assert graph_command == legacy_command
        assert graph_result.returncode == legacy_result.returncode == 0
    assert all(result.skipped for result in resumed_report.steps)
    assert topology_only_report.steps[0].step_name == "topology"
    assert topology_only_report.steps[0].returncode == 0
    assert box_only_report.steps[0].step_name == "box"
    assert box_only_report.steps[0].returncode == 0
    assert solvate_only_report.steps[0].step_name == "solvate"
    assert solvate_only_report.steps[0].returncode == 0
    assert ions_grompp_only_report.steps[0].step_name == "ions-grompp"
    assert ions_grompp_only_report.steps[0].returncode == 0
    assert len(subprocess_calls) == 14  # graph twice, isolated steps, legacy prefix
    assert legacy_state.read_bytes() == legacy_state_before
    assert (project_root / "work" / "workflow_state.json").is_file()
    assert callback_events == [
        ("start", 1, "prepare"),
        ("done", 1, "prepare"),
        ("start", 2, "topology"),
        ("done", 2, "topology"),
        ("start", 3, "box"),
        ("done", 3, "box"),
        ("start", 4, "solvate"),
        ("done", 4, "solvate"),
        ("start", 5, "ions-grompp"),
        ("done", 5, "ions-grompp"),
    ]
    for relative_dir in (
        Path("work/prep"),
        Path("work/topo"),
        Path("work/box"),
    ):
        graph_outputs = sorted((project_root / relative_dir).glob("*"))
        legacy_outputs = sorted((legacy_root / relative_dir).glob("*"))
        assert [path.name for path in graph_outputs] == [
            path.name for path in legacy_outputs
        ]
        assert [path.read_bytes() for path in graph_outputs] == [
            path.read_bytes() for path in legacy_outputs
        ]


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
