from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest

from gmxflow.api import GmxFlowProject
from gmxflow.config import default_config, to_toml
from gmxflow.executor import (
    WorkflowExecutionReport,
    WorkflowStepResult,
    WorkflowStepStatus,
)
from gmxflow.pipeline import (
    Artifact,
    GromacsCommandStep,
    RunContext,
    Step,
)


def _write_project_config(project_dir: Path) -> Path:
    project_dir.mkdir(parents=True)
    config_path = project_dir / "project.toml"
    config_path.write_text(to_toml(default_config(project_dir.name)), encoding="utf-8")
    return config_path


def _command_steps(
    project: GmxFlowProject,
    *,
    from_step: str | None = None,
    until: str | None = None,
) -> list[GromacsCommandStep]:
    """Select GROMACS command steps from a project workflow."""
    workflow = project.workflow(from_step=from_step, until=until)
    return [
        step
        for step in workflow.items
        if isinstance(step, GromacsCommandStep)
    ]


@dataclass
class _CopyArtifactStep:
    id: str
    name: str
    inputs: tuple[Artifact, ...]
    outputs: tuple[Artifact, ...]
    parallel: bool = False
    version: str = "1"
    state: Mapping[str, object] = field(default_factory=dict)

    def run(self, context: RunContext) -> None:
        context.output_path(self.outputs[0]).write_bytes(
            context.input_path(self.inputs[0]).read_bytes()
        )


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


def test_project_runs_a_custom_protocol_step_and_resumes(tmp_path: Path) -> None:
    project = GmxFlowProject.open(_write_project_config(tmp_path / "custom_step"))
    source_path = project.root / "inputs" / "source.txt"
    source_path.parent.mkdir()
    source_path.write_text("custom step input", encoding="utf-8")
    target_path = project.root / "outputs" / "copy.txt"
    source = Artifact("source", "text")
    target = Artifact("copy", "text")
    step: Step = _CopyArtifactStep("copy", "Copy input", (source,), (target,))

    dry_run = project.run_workflow(
        step,
        project_inputs=(source,),
        artifact_paths={"source": source_path, "copy": target_path},
        state_name="custom-copy.json",
        dry_run=True,
    )

    assert dry_run.dry_run
    assert not target_path.exists()


def test_project_workflow_uses_shared_default_state_file(tmp_path: Path) -> None:
    project = GmxFlowProject.open(_write_project_config(tmp_path / "default_state"))
    source_path = project.root / "inputs" / "source.txt"
    source_path.parent.mkdir()
    source_path.write_text("input", encoding="utf-8")
    source = Artifact("source", "text")
    target = Artifact("copy", "text")
    step = _CopyArtifactStep("copy", "Copy input", (source,), (target,))

    report = project.run_workflow(
        step,
        project_inputs=(source,),
        artifact_paths={
            "source": source_path,
            "copy": project.root / "outputs" / "copy.txt",
        },
    )

    assert report.succeeded
    assert (project.root / "work" / "state.json").is_file()
    assert not (project.root / "work" / "project-workflow.json").exists()
    assert not (project.root / "work" / "workflow_state.json").exists()


def test_project_workflow_builds_concrete_steps_for_composition(
    tmp_path: Path,
) -> None:
    project = GmxFlowProject.open(_write_project_config(tmp_path / "workflow_api"))

    workflow = project.workflow(until="topology")
    steps = tuple(
        step for step in workflow.items if isinstance(step, GromacsCommandStep)
    )

    assert len(steps) == len(workflow.items)
    assert [step.id for step in steps] == ["prepare", "topology"]
    assert not (project.root / "work").exists()


def test_project_workflow_composes_and_runs_custom_protocol_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = GmxFlowProject.open(_write_project_config(tmp_path / "mixed_workflow"))
    base_workflow = project.workflow(from_step="solvate", until="solvate")
    solvate_step = base_workflow.items[0]
    assert isinstance(solvate_step, GromacsCommandStep)
    source = next(
        artifact for artifact in solvate_step.outputs if artifact.kind == "gro"
    )
    target = Artifact("custom:solvate-copy", "gro")
    custom_step: Step = _CopyArtifactStep(
        "custom-copy", "Copy solvated coordinates", (source,), (target,)
    )
    workflow = base_workflow | custom_step
    for input_path in solvate_step.input_paths:
        input_path.parent.mkdir(parents=True, exist_ok=True)
        input_path.write_text("GROMACS INPUT\n", encoding="utf-8")
    target_path = project.root / "outputs" / "solvate-copy.gro"
    setup_events: list[str] = []
    callback_events: list[str] = []

    monkeypatch.setattr(
        GmxFlowProject,
        "validate",
        lambda self: setup_events.append("validate"),
    )
    monkeypatch.setattr(
        "gmxflow.api.run_workspace_setup",
        lambda config, project_root, **kwargs: setup_events.append("workspace"),
    )

    def fake_subprocess_run(argv, *, cwd, env, input, text, capture_output, check):
        assert tuple(argv[1:3]) == ("-c", "from gmxflow.cli import app; app()")
        assert cwd == solvate_step.workdir
        for path in solvate_step.output_paths:
            path.write_text("GROMACS OUTPUT\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("gmxflow.executor.subprocess.run", fake_subprocess_run)

    report = project.run_workflow(
        workflow,
        artifact_paths={target.key: target_path},
        state_name="mixed-workflow.json",
        on_step_start=lambda step: callback_events.append(f"start:{step.id}"),
        on_step_done=lambda result: callback_events.append(f"done:{result.step_id}"),
    )

    assert report.succeeded
    assert [result.step_id for result in report.results] == ["solvate", "custom-copy"]
    assert setup_events == ["validate", "workspace"]
    assert callback_events == [
        "start:solvate",
        "done:solvate",
        "start:custom-copy",
        "done:custom-copy",
    ]
    assert target_path.read_text(encoding="utf-8") == "GROMACS OUTPUT\n"


def test_composed_project_workflow_dry_run_does_not_prepare_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = GmxFlowProject.open(_write_project_config(tmp_path / "dry_workflow"))
    base_workflow = project.workflow(from_step="topology", until="topology")
    topology_step = base_workflow.items[0]
    assert isinstance(topology_step, GromacsCommandStep)
    target = Artifact("custom:dry-copy", "gro")
    workflow = base_workflow | _CopyArtifactStep(
        "custom-copy",
        "Copy topology coordinates",
        (next(item for item in topology_step.outputs if item.kind == "gro"),),
        (target,),
    )
    setup_events: list[str] = []
    monkeypatch.setattr(
        GmxFlowProject,
        "validate",
        lambda self: setup_events.append("validate"),
    )
    monkeypatch.setattr(
        "gmxflow.api.run_workspace_setup",
        lambda config, project_root, **kwargs: setup_events.append("workspace"),
    )

    report = project.run_workflow(
        workflow,
        artifact_paths={target.key: project.root / "outputs" / "dry-copy.gro"},
        state_name="dry-workflow.json",
        dry_run=True,
    )

    assert report.dry_run
    assert [result.step_id for result in report.results] == ["topology", "custom-copy"]
    assert setup_events == []
    assert not (project.root / "work").exists()


def test_project_custom_workflow_executes_protocol_steps_and_resumes(
    tmp_path: Path,
) -> None:
    project = GmxFlowProject.open(_write_project_config(tmp_path / "custom_step"))
    source_path = project.root / "inputs" / "source.txt"
    source_path.parent.mkdir()
    source_path.write_text("custom step input", encoding="utf-8")
    target_path = project.root / "outputs" / "copy.txt"
    source = Artifact("source", "text")
    target = Artifact("copy", "text")
    step: Step = _CopyArtifactStep("copy", "Copy input", (source,), (target,))

    first = project.run_workflow(
        step,
        project_inputs=(source,),
        artifact_paths={"source": source_path, "copy": target_path},
        state_name="custom-copy.json",
    )
    second = project.run_workflow(
        step,
        project_inputs=(source,),
        artifact_paths={"source": source_path, "copy": target_path},
        state_name="custom-copy.json",
    )

    assert first.succeeded
    assert first.results[0].status is WorkflowStepStatus.SUCCEEDED
    assert target_path.read_text(encoding="utf-8") == "custom step input"
    assert second.results[0].status is WorkflowStepStatus.SKIPPED
    assert (project.root / "work" / "custom-copy.json").is_file()


@pytest.mark.parametrize(
    "state_name",
    [
        "../state.json",
        "sub/state.json",
        "state.txt",
        "STATE.JSON",
    ],
)
def test_custom_workflow_rejects_invalid_state_names(
    tmp_path: Path, state_name: str
) -> None:
    project = GmxFlowProject.open(_write_project_config(tmp_path / "custom_step"))
    source = Artifact("source", "text")
    target = Artifact("copy", "text")
    step: Step = _CopyArtifactStep("copy", "Copy input", (source,), (target,))

    with pytest.raises(ValueError, match="state_name"):
        project.run_workflow(
            step,
            project_inputs=(source,),
            artifact_paths={"source": tmp_path / "source", "copy": tmp_path / "copy"},
            state_name=state_name,
            dry_run=True,
        )


def test_create_refuses_existing_project_without_force(tmp_path: Path) -> None:
    project_dir = tmp_path / "existing_project"
    project_dir.mkdir()
    marker = project_dir / "keep.txt"
    marker.write_text("user data", encoding="utf-8")

    with pytest.raises(FileExistsError):
        GmxFlowProject.create("existing_project", destination=tmp_path)

    assert marker.read_text(encoding="utf-8") == "user data"


def test_show_report_delegates_using_project_root(tmp_path: Path, monkeypatch) -> None:
    project = GmxFlowProject.open(_write_project_config(tmp_path / "api_project"))
    shown_projects: list[tuple[Path, object]] = []

    monkeypatch.setattr(
        "gmxflow.notebook.show_report",
        lambda root, config: shown_projects.append((root, config)),
    )

    project.show_report()

    assert shown_projects == [(project.root, project.config)]


def test_edit_config_delegates_to_notebook_form(tmp_path: Path, monkeypatch) -> None:
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
    shown_results: list[tuple[object, ...]] = []
    monkeypatch.setattr("gmxflow.notebook.show_execution", shown_results.append)

    workflow_result = WorkflowStepResult(
        step_id="custom-step",
        status=WorkflowStepStatus.SUCCEEDED,
        log_path=project.root / "work" / "logs" / "custom-step.log",
    )
    workflow_report = WorkflowExecutionReport(
        results=(workflow_result,),
        dependencies={},
        artifact_paths={},
    )
    project.show_execution(workflow_report)

    assert shown_results == [(workflow_result,)]


def test_clean_removes_work_artifacts_and_preserves_project_data(
    tmp_path: Path,
) -> None:
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
    monkeypatch.setattr(
        "gmxflow.api.shutil.which", lambda command: "/opt/gromacs/bin/gmx"
    )
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


def test_validate_reports_missing_configured_input_before_other_prerequisites(
    tmp_path: Path,
) -> None:
    project = GmxFlowProject.open(_write_project_config(tmp_path / "api_project"))

    with pytest.raises(FileNotFoundError, match="receptor.pdb"):
        project.validate()


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
    monkeypatch.setattr(
        "gmxflow.api.shutil.which", lambda command: "/opt/gromacs/bin/gmx"
    )
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
        .replace("remove_resnames = []", 'remove_resnames = ["HOH"]')
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

    monkeypatch.setattr(
        "gmxflow.preparation.structure.import_module", missing_dependency
    )
    project = GmxFlowProject.open(config_path)

    with pytest.raises(RuntimeError, match="Instale `mdanalysis`"):
        project.validate()


def test_full_project_workflow_executes_and_resumes(
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
    graph_em_mdp = project_root / "work" / "em" / "em.mdp"
    graph_em_mdp.parent.mkdir(parents=True)
    graph_em_mdp.write_text("MDP\n", encoding="utf-8")
    graph_nvt_mdp = project_root / "work" / "nvt" / "nvt.mdp"
    graph_nvt_mdp.parent.mkdir(parents=True)
    graph_nvt_mdp.write_text("MDP\n", encoding="utf-8")
    graph_npt_mdp = project_root / "work" / "npt" / "npt.mdp"
    graph_npt_mdp.parent.mkdir(parents=True)
    graph_npt_mdp.write_text("MDP\n", encoding="utf-8")
    graph_prod_mdp = project_root / "work" / "prod" / "md.mdp"
    graph_prod_mdp.parent.mkdir(parents=True)
    graph_prod_mdp.write_text("MDP\n", encoding="utf-8")
    subprocess_calls: list[tuple[str, ...]] = []
    subprocess_inputs: list[tuple[tuple[str, ...], str | None]] = []

    def fake_subprocess_run(command, *, cwd, **kwargs):
        subprocess_calls.append(tuple(command))
        subprocess_inputs.append((tuple(command), kwargs.get("input")))
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
            output_topology = Path(command[command.index("--topology-output") + 1])
            source_topology = output_topology.parent / "topol.top"
            output_topology.write_text(
                source_topology.read_text(encoding="utf-8") + "SOLVATED\n",
                encoding="utf-8",
            )
        elif "genion-system" in command:
            output_content = {"ions.gro": "IONS\n"}
            output_topology = Path(command[command.index("--topology-output") + 1])
            source_topology = Path(command[command.index("--topology-input") + 1])
            output_topology.write_text(
                source_topology.read_text(encoding="utf-8") + "IONS\n",
                encoding="utf-8",
            )
        elif "grompp" in command:
            output_file = command[command.index("-o") + 1]
            output_content = {
                output_file: f"{Path(output_file).stem.upper()}_TPR\n",
                "mdout.mdp": "MDTOUT\n",
            }
        elif "analyze" in command:
            output_content = {
                Path(output).name: "ANALYSIS\n"
                for output in _command_steps(project, until="analysis")[-1].output_paths
            }
        elif "thermodynamics" in command:
            output_content = {
                Path(output).name: "THERMODYNAMICS\n"
                for output in _command_steps(project, until="thermodynamics")[-1].output_paths
            }
        elif "plot-analysis" in command:
            output_content = {
                Path(output).name: "PLOT\n"
                for output in _command_steps(project, until="plots")[-1].output_paths
            }
        elif "report" in command:
            report_step = _command_steps(project, until="report")[-1]
            for output in report_step.output_paths:
                if not output.suffix:
                    (Path(cwd) / output.name).mkdir(exist_ok=True)
            output_content = {
                output.name: "REPORT\n"
                for output in report_step.output_paths
                if output.suffix
            }
        elif "trjconv" in command:
            output_file = command[command.index("-o") + 1]
            output_content = {output_file: "NOJUMP_XTC\n"}
        elif "mdrun" in command:
            output_prefix = command[command.index("-deffnm") + 1]
            output_content = {
                f"{output_prefix}.gro": f"{output_prefix.upper()}_GRO\n",
                f"{output_prefix}.edr": f"{output_prefix.upper()}_EDR\n",
                f"{output_prefix}.log": f"{output_prefix.upper()}_LOG\n",
                f"{output_prefix}.trr": f"{output_prefix.upper()}_TRR\n",
            }
            if output_prefix in {"nvt", "npt"}:
                output_content[f"{output_prefix}.cpt"] = (
                    f"{output_prefix.upper()}_CPT\n"
                )
            if output_prefix == "md":
                output_content = {
                    "md.xtc": "MD_XTC\n",
                    "md.gro": "MD_GRO\n",
                    "md.cpt": "MD_CPT\n",
                    "md.edr": "MD_EDR\n",
                    "md.log": "MD_LOG\n",
                }
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
        lambda config, project_root, **kwargs: None,
    )

    step_indexes = {
        step.id: index
        for index, step in enumerate(_command_steps(project, until="report"), start=1)
    }
    callback_events: list[tuple[str, int, str]] = []
    graph_report = project.run_workflow(
        project.workflow(until="report"),
        on_step_start=lambda step: callback_events.append(
            ("start", step_indexes[step.id], step.id)
        ),
        on_step_done=lambda result: callback_events.append(
            ("done", step_indexes[result.step_id], result.step_id)
        ),
    )
    resumed_report = project.run_workflow(project.workflow(until="report"))
    assert len(graph_report.results) == 21
    assert graph_report.succeeded
    assert all(
        result.status is WorkflowStepStatus.SKIPPED for result in resumed_report.results
    )
    assert len(subprocess_calls) == 21
    assert (
        sum(
            command[-1:] == ("nojump",) and stdin == "0\n"
            for command, stdin in subprocess_inputs
        )
        == 1
    )
    assert (
        sum(
            "-center" in command and stdin == "Protein\nSystem\n"
            for command, stdin in subprocess_inputs
        )
        == 1
    )
    assert (
        sum(
            "-fit" in command and stdin == "Backbone\nSystem\n"
            for command, stdin in subprocess_inputs
        )
        == 1
    )
    assert (project_root / "work" / "state.json").is_file()
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
        ("start", 6, "ions"),
        ("done", 6, "ions"),
        ("start", 7, "em-grompp"),
        ("done", 7, "em-grompp"),
        ("start", 8, "em"),
        ("done", 8, "em"),
        ("start", 9, "nvt-grompp"),
        ("done", 9, "nvt-grompp"),
        ("start", 10, "nvt"),
        ("done", 10, "nvt"),
        ("start", 11, "npt-grompp"),
        ("done", 11, "npt-grompp"),
        ("start", 12, "npt"),
        ("done", 12, "npt"),
        ("start", 13, "production-grompp"),
        ("done", 13, "production-grompp"),
        ("start", 14, "production"),
        ("done", 14, "production"),
        ("start", 15, "pbc-nojump"),
        ("done", 15, "pbc-nojump"),
        ("start", 16, "pbc-center"),
        ("done", 16, "pbc-center"),
        ("start", 17, "fit"),
        ("done", 17, "fit"),
        ("start", 18, "analysis"),
        ("done", 18, "analysis"),
        ("start", 19, "thermodynamics"),
        ("done", 19, "thermodynamics"),
        ("start", 20, "plots"),
        ("done", 20, "plots"),
        ("start", 21, "report"),
        ("done", 21, "report"),
    ]
    for relative_dir in (
        Path("work/prep"),
        Path("work/topo"),
        Path("work/box"),
        Path("work/em"),
        Path("work/nvt"),
        Path("work/npt"),
        Path("work/prod"),
        Path("work/analysis"),
    ):
        graph_outputs = sorted((project_root / relative_dir).glob("*"))
        assert any(path.is_file() for path in graph_outputs)
    graph_report_outputs = sorted((project_root / "outputs").rglob("*"))
    assert any(path.is_file() for path in graph_report_outputs)


def test_interaction_energy_runs_through_graph_when_enabled(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = tmp_path / "interaction_project"
    project = GmxFlowProject.open(_write_project_config(project_root))
    project.config.analysis.interaction_energy = True

    inputs_dir = project_root / "inputs"
    inputs_dir.mkdir()
    (inputs_dir / "receptor.pdb").write_text("ATOM\n", encoding="utf-8")
    (inputs_dir / "ligante.pdb").write_text("ATOM\n", encoding="utf-8")
    analysis_dir = project_root / "work" / "analysis"
    analysis_dir.mkdir(parents=True)
    (analysis_dir / "rerun.mdp").write_text("MDP\n", encoding="utf-8")
    (analysis_dir / "lig.ndx").write_text("INDEX\n", encoding="utf-8")
    production_dir = project_root / "work" / "prod"
    production_dir.mkdir(parents=True)
    (production_dir / "md.gro").write_text("GRO\n", encoding="utf-8")
    (production_dir / "md_fit.xtc").write_text("TRAJECTORY\n", encoding="utf-8")
    topology_dir = project_root / "work" / "topo"
    topology_dir.mkdir(parents=True)
    (topology_dir / "topol_ions.top").write_text("TOP\n", encoding="utf-8")

    monkeypatch.setattr("gmxflow.api.GmxFlowProject.validate", lambda self: None)
    monkeypatch.setattr(
        "gmxflow.api.run_workspace_setup",
        lambda config, project_root, **kwargs: None,
    )

    calls: list[tuple[str, ...]] = []

    def fake_subprocess_run(command, *, cwd, **kwargs):
        calls.append(tuple(command))
        for output in _command_steps(project, until="interaction-energy")[-1].output_paths:
            (Path(cwd) / output.name).write_text("SIMULATED\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("gmxflow.executor.subprocess.run", fake_subprocess_run)

    report = project.run_workflow(
        project.workflow(from_step="interaction-energy", until="interaction-energy")
    )

    assert len(calls) == 1
    assert report.results[0].step_id == "interaction-energy"
    assert report.results[0].status is WorkflowStepStatus.SUCCEEDED
    assert all(
        output.is_file()
        for output in _command_steps(project, until="interaction-energy")[-1].output_paths
    )


def test_sasa_runs_through_graph_when_enabled(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / "sasa_project"
    project = GmxFlowProject.open(_write_project_config(project_root))
    project.config.analysis.sasa = True

    inputs_dir = project_root / "inputs"
    inputs_dir.mkdir()
    (inputs_dir / "receptor.pdb").write_text("ATOM\n", encoding="utf-8")
    (inputs_dir / "ligante.pdb").write_text("ATOM\n", encoding="utf-8")
    analysis_dir = project_root / "work" / "analysis"
    analysis_dir.mkdir(parents=True)
    (analysis_dir / "lig.ndx").write_text("INDEX\n", encoding="utf-8")
    production_dir = project_root / "work" / "prod"
    production_dir.mkdir(parents=True)
    (production_dir / "md.tpr").write_text("TPR\n", encoding="utf-8")
    (production_dir / "md_fit.xtc").write_text("TRAJECTORY\n", encoding="utf-8")

    monkeypatch.setattr("gmxflow.api.GmxFlowProject.validate", lambda self: None)
    monkeypatch.setattr(
        "gmxflow.api.run_workspace_setup",
        lambda config, project_root, **kwargs: None,
    )

    calls: list[tuple[str, ...]] = []

    def fake_subprocess_run(command, *, cwd, **kwargs):
        calls.append(tuple(command))
        for output in _command_steps(project, until="sasa")[-1].output_paths:
            (Path(cwd) / output.name).write_text("SIMULATED\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("gmxflow.executor.subprocess.run", fake_subprocess_run)

    report = project.run_workflow(project.workflow(from_step="sasa", until="sasa"))

    assert len(calls) == 1
    assert report.results[0].step_id == "sasa"
    assert report.results[0].status is WorkflowStepStatus.SUCCEEDED
    assert all(
        output.is_file() for output in _command_steps(project, until="sasa")[-1].output_paths
    )


def test_plots_runs_through_graph_when_started_directly(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = tmp_path / "plot_project"
    project = GmxFlowProject.open(_write_project_config(project_root))
    inputs_dir = project_root / "inputs"
    inputs_dir.mkdir()
    (inputs_dir / "receptor.pdb").write_text("ATOM\n", encoding="utf-8")
    (inputs_dir / "ligante.pdb").write_text("ATOM\n", encoding="utf-8")

    plots_step = _command_steps(project, until="plots")[-1]
    for input_path in plots_step.input_paths:
        input_path.parent.mkdir(parents=True, exist_ok=True)
        input_path.write_text("PLOT_INPUT\n", encoding="utf-8")

    monkeypatch.setattr("gmxflow.api.GmxFlowProject.validate", lambda self: None)
    monkeypatch.setattr(
        "gmxflow.api.run_workspace_setup",
        lambda config, project_root, **kwargs: None,
    )

    calls: list[tuple[str, ...]] = []

    def fake_subprocess_run(command, *, cwd, **kwargs):
        calls.append(tuple(command))
        for output in plots_step.output_paths:
            (Path(cwd) / output.name).write_text("PLOT\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("gmxflow.executor.subprocess.run", fake_subprocess_run)

    report = project.run_workflow(project.workflow(from_step="plots", until="plots"))

    assert len(calls) == 1
    assert report.results[0].step_id == "plots"
    assert report.results[0].status is WorkflowStepStatus.SUCCEEDED
    assert all(output.is_file() for output in plots_step.output_paths)


def test_report_runs_through_graph_when_started_directly(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = tmp_path / "report_project"
    project = GmxFlowProject.open(_write_project_config(project_root))
    inputs_dir = project_root / "inputs"
    inputs_dir.mkdir()
    (inputs_dir / "receptor.pdb").write_text("ATOM\n", encoding="utf-8")
    (inputs_dir / "ligante.pdb").write_text("ATOM\n", encoding="utf-8")

    report_step = _command_steps(project, until="report")[-1]
    for input_path in report_step.input_paths:
        input_path.parent.mkdir(parents=True, exist_ok=True)
        input_path.write_text("REPORT_INPUT\n", encoding="utf-8")

    monkeypatch.setattr("gmxflow.api.GmxFlowProject.validate", lambda self: None)
    monkeypatch.setattr(
        "gmxflow.api.run_workspace_setup",
        lambda config, project_root, **kwargs: None,
    )

    calls: list[tuple[str, ...]] = []

    def fake_subprocess_run(command, *, cwd, **kwargs):
        calls.append(tuple(command))
        for output in report_step.output_paths:
            path = Path(cwd) / output.name
            if not output.suffix:
                path.mkdir(exist_ok=True)
            else:
                path.write_text("REPORT\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("gmxflow.executor.subprocess.run", fake_subprocess_run)

    report = project.run_workflow(project.workflow(from_step="report", until="report"))

    assert len(calls) == 1
    assert report.results[0].step_id == "report"
    assert report.results[0].status is WorkflowStepStatus.SUCCEEDED
    assert all(output.exists() for output in report_step.output_paths)


def test_small_molecule_assembly_prefix_runs_through_graph(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = tmp_path / "small_molecule_project"
    project_root.mkdir()
    config = default_config("small_molecule_project")
    config.input.ligand_kind = "small_molecule"
    config.input.ligand_mol2 = "inputs/ligand.mol2"
    config.input.ligand_str = "inputs/ligand.str"
    config.input.ligand_resname = "LIG"
    config_path = project_root / "project.toml"
    config_path.write_text(to_toml(config), encoding="utf-8")
    project = GmxFlowProject.open(config_path)

    inputs_dir = project_root / "inputs"
    inputs_dir.mkdir()
    for filename in ("receptor.pdb", "ligante.pdb", "ligand.mol2", "ligand.str"):
        (inputs_dir / filename).write_text("INPUT\n", encoding="utf-8")

    monkeypatch.setattr("gmxflow.api.GmxFlowProject.validate", lambda self: None)
    monkeypatch.setattr(
        "gmxflow.api.run_workspace_setup",
        lambda config, project_root, **kwargs: None,
    )

    calls: list[tuple[str, ...]] = []
    subprocess_inputs: list[str | None] = []

    def fake_subprocess_run(command, *, cwd, **kwargs):
        calls.append(tuple(command))
        subprocess_inputs.append(kwargs.get("input"))
        if "prepare-complex" in command:
            outputs = _command_steps(project, until="prepare")[0].output_paths
        elif "pdb2gmx" in command:
            outputs = _command_steps(project, until="protein-topology")[-1].output_paths
        elif "assemble-complex" in command:
            outputs = _command_steps(project, until="assemble-complex")[-1].output_paths
        else:
            outputs = _command_steps(project, until="ligand-topology")[-1].output_paths
        for output in outputs:
            (Path(cwd) / output.name).write_text("SIMULATED\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("gmxflow.executor.subprocess.run", fake_subprocess_run)

    report = project.run_workflow(project.workflow(until="assemble-complex"))

    assert len(calls) == 4
    assert [result.step_id for result in report.results] == [
        "prepare",
        "ligand-topology",
        "protein-topology",
        "assemble-complex",
    ]
    assert all(
        result.status is WorkflowStepStatus.SUCCEEDED for result in report.results
    )
    assert "pdb2gmx" in calls[-2]
    assert "assemble-complex" in calls[-1]
    assert subprocess_inputs[-2] == "0\n0\n"
    assert all(
        output.is_file()
        for output in _command_steps(project, until="assemble-complex")[-1].output_paths
    )


@pytest.mark.parametrize(
    ("step_name", "command_name"),
    [("analysis", "analyze"), ("thermodynamics", "thermodynamics")],
)
def test_small_molecule_analysis_steps_can_start_through_graph(
    tmp_path: Path, monkeypatch, step_name: str, command_name: str
) -> None:
    project_root = tmp_path / "small_molecule_analysis_project"
    project_root.mkdir()
    config = default_config(project_root.name)
    config.input.ligand_kind = "small_molecule"
    config.input.ligand_mol2 = "inputs/ligand.mol2"
    config.input.ligand_str = "inputs/ligand.str"
    config.input.ligand_resname = "LIG"
    config_path = project_root / "project.toml"
    config_path.write_text(to_toml(config), encoding="utf-8")
    project = GmxFlowProject.open(config_path)
    selected_step = _command_steps(project, from_step=step_name, until=step_name)[0]

    inputs_dir = project_root / "inputs"
    inputs_dir.mkdir()
    for filename in ("receptor.pdb", "ligante.pdb", "ligand.mol2", "ligand.str"):
        (inputs_dir / filename).write_text("INPUT\n", encoding="utf-8")
    for input_path in selected_step.input_paths:
        input_path.parent.mkdir(parents=True, exist_ok=True)
        input_path.write_text("INPUT\n", encoding="utf-8")

    monkeypatch.setattr("gmxflow.api.GmxFlowProject.validate", lambda self: None)
    monkeypatch.setattr(
        "gmxflow.api.run_workspace_setup",
        lambda config, project_root, **kwargs: None,
    )
    calls: list[tuple[str, ...]] = []

    def fake_subprocess_run(command, *, cwd, **kwargs):
        calls.append(tuple(command))
        for output in selected_step.output_paths:
            (Path(cwd) / output.name).write_text("SIMULATED\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("gmxflow.executor.subprocess.run", fake_subprocess_run)

    report = project.run_workflow(
        project.workflow(from_step=step_name, until=step_name)
    )

    assert len(calls) == 1
    assert command_name in calls[0]
    assert [result.step_id for result in report.results] == [step_name]
    assert report.results[0].status is WorkflowStepStatus.SUCCEEDED
    assert all(output.is_file() for output in selected_step.output_paths)
