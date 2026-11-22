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
    em_grompp_result = StepResult(
        step_name="em-grompp",
        command=runtime_command(project.plan(until="em-grompp")[6].command),
        workdir=project.root / "work" / "em",
        log_path=project.root / "work" / "logs" / "07_em-grompp.log",
        returncode=0,
        elapsed_seconds=0.8,
    )
    em_result = StepResult(
        step_name="em",
        command=runtime_command(project.plan(until="em")[7].command),
        workdir=project.root / "work" / "em",
        log_path=project.root / "work" / "logs" / "08_em.log",
        returncode=0,
        elapsed_seconds=0.9,
    )
    nvt_grompp_result = StepResult(
        step_name="nvt-grompp",
        command=runtime_command(project.plan(until="nvt-grompp")[8].command),
        workdir=project.root / "work" / "nvt",
        log_path=project.root / "work" / "logs" / "09_nvt-grompp.log",
        returncode=0,
        elapsed_seconds=1.0,
    )
    nvt_result = StepResult(
        step_name="nvt",
        command=runtime_command(project.plan(until="nvt")[9].command),
        workdir=project.root / "work" / "nvt",
        log_path=project.root / "work" / "logs" / "10_nvt.log",
        returncode=0,
        elapsed_seconds=1.1,
    )
    npt_grompp_result = StepResult(
        step_name="npt-grompp",
        command=runtime_command(project.plan(until="npt-grompp")[10].command),
        workdir=project.root / "work" / "npt",
        log_path=project.root / "work" / "logs" / "11_npt-grompp.log",
        returncode=0,
        elapsed_seconds=1.2,
    )
    npt_result = StepResult(
        step_name="npt",
        command=runtime_command(project.plan(until="npt")[11].command),
        workdir=project.root / "work" / "npt",
        log_path=project.root / "work" / "logs" / "12_npt.log",
        returncode=0,
        elapsed_seconds=1.3,
    )
    production_grompp_result = StepResult(
        step_name="production-grompp",
        command=runtime_command(project.plan(until="production-grompp")[12].command),
        workdir=project.root / "work" / "prod",
        log_path=project.root / "work" / "logs" / "13_production-grompp.log",
        returncode=0,
        elapsed_seconds=1.4,
    )
    production_result = StepResult(
        step_name="production",
        command=runtime_command(project.plan(until="production")[13].command),
        workdir=project.root / "work" / "prod",
        log_path=project.root / "work" / "logs" / "14_production.log",
        returncode=0,
        elapsed_seconds=1.5,
    )
    pbc_nojump_result = StepResult(
        step_name="pbc-nojump",
        command=runtime_command(project.plan(until="pbc-nojump")[14].command),
        workdir=project.root / "work" / "prod",
        log_path=project.root / "work" / "logs" / "15_pbc-nojump.log",
        returncode=0,
        elapsed_seconds=1.6,
    )
    pbc_center_result = StepResult(
        step_name="pbc-center",
        command=runtime_command(project.plan(until="pbc-center")[15].command),
        workdir=project.root / "work" / "prod",
        log_path=project.root / "work" / "logs" / "16_pbc-center.log",
        returncode=0,
        elapsed_seconds=1.7,
    )
    fit_result = StepResult(
        step_name="fit",
        command=runtime_command(project.plan(until="fit")[16].command),
        workdir=project.root / "work" / "prod",
        log_path=project.root / "work" / "logs" / "17_fit.log",
        returncode=0,
        elapsed_seconds=1.8,
    )
    analysis_result = StepResult(
        step_name="analysis",
        command=runtime_command(project.plan(until="analysis")[17].command),
        workdir=project.root / "work" / "analysis",
        log_path=project.root / "work" / "logs" / "18_analysis.log",
        returncode=0,
        elapsed_seconds=1.9,
    )
    thermodynamics_result = StepResult(
        step_name="thermodynamics",
        command=runtime_command(project.plan(until="thermodynamics")[18].command),
        workdir=project.root / "work" / "analysis",
        log_path=project.root / "work" / "logs" / "19_thermodynamics.log",
        returncode=0,
        elapsed_seconds=2.0,
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
        )
        assert kwargs["project_root"] == project.root
        step_results = {
            "prepare": step_result,
            "topology": topology_result,
            "box": box_result,
            "solvate": solvate_result,
            "ions-grompp": ions_grompp_result,
            "ions": ions_result,
            "em-grompp": em_grompp_result,
            "em": em_result,
            "nvt-grompp": nvt_grompp_result,
            "nvt": nvt_result,
            "npt-grompp": npt_grompp_result,
            "npt": npt_result,
            "production-grompp": production_grompp_result,
            "production": production_result,
            "pbc-nojump": pbc_nojump_result,
            "pbc-center": pbc_center_result,
            "fit": fit_result,
            "analysis": analysis_result,
            "thermodynamics": thermodynamics_result,
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

    report = project.run(until="thermodynamics")

    assert events == ["validate", "workspace", "workflow_graph"]
    assert report.workspace is workspace
    assert report.steps == (
        step_result,
        topology_result,
        box_result,
        solvate_result,
        ions_grompp_result,
        ions_result,
        em_grompp_result,
        em_result,
        nvt_grompp_result,
        nvt_result,
        npt_grompp_result,
        npt_result,
        production_grompp_result,
        production_result,
        pbc_nojump_result,
        pbc_center_result,
        fit_result,
        analysis_result,
        thermodynamics_result,
    )
    assert report.results == (
        workspace,
        step_result,
        topology_result,
        box_result,
        solvate_result,
        ions_grompp_result,
        ions_result,
        em_grompp_result,
        em_result,
        nvt_grompp_result,
        nvt_result,
        npt_grompp_result,
        npt_result,
        production_grompp_result,
        production_result,
        pbc_nojump_result,
        pbc_center_result,
        fit_result,
        analysis_result,
        thermodynamics_result,
    )


def test_graph_prefix_through_plots_matches_legacy_commands_and_outputs(
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
    legacy_em_mdp = legacy_root / "work" / "em" / "em.mdp"
    legacy_em_mdp.parent.mkdir(parents=True)
    legacy_em_mdp.write_text("MDP\n", encoding="utf-8")
    legacy_nvt_mdp = legacy_root / "work" / "nvt" / "nvt.mdp"
    legacy_nvt_mdp.parent.mkdir(parents=True)
    legacy_nvt_mdp.write_text("MDP\n", encoding="utf-8")
    legacy_npt_mdp = legacy_root / "work" / "npt" / "npt.mdp"
    legacy_npt_mdp.parent.mkdir(parents=True)
    legacy_npt_mdp.write_text("MDP\n", encoding="utf-8")
    legacy_prod_mdp = legacy_root / "work" / "prod" / "md.mdp"
    legacy_prod_mdp.parent.mkdir(parents=True)
    legacy_prod_mdp.write_text("MDP\n", encoding="utf-8")

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
            output_topology = Path(
                command[command.index("--topology-output") + 1]
            )
            source_topology = output_topology.parent / "topol.top"
            output_topology.write_text(
                source_topology.read_text(encoding="utf-8") + "SOLVATED\n",
                encoding="utf-8",
            )
        elif "genion-system" in command:
            output_content = {"ions.gro": "IONS\n"}
            output_topology = Path(
                command[command.index("--topology-output") + 1]
            )
            source_topology = Path(
                command[command.index("--topology-input") + 1]
            )
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
                for output in project.plan(until="analysis")[-1].outputs
            }
        elif "thermodynamics" in command:
            output_content = {
                Path(output).name: "THERMODYNAMICS\n"
                for output in project.plan(until="thermodynamics")[-1].outputs
            }
        elif "plot-analysis" in command:
            output_content = {
                Path(output).name: "PLOT\n"
                for output in project.plan(until="plots")[-1].outputs
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
                output_content[f"{output_prefix}.cpt"] = f"{output_prefix.upper()}_CPT\n"
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
        until="plots",
        on_step_start=lambda index, step: callback_events.append(
            ("start", index, step.name)
        ),
        on_step_done=lambda index, result: callback_events.append(
            ("done", index, result.step_name)
        ),
    )
    resumed_report = project.run(until="plots")

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

    ions_only_root = tmp_path / "ions_only_project"
    ions_only_project = GmxFlowProject.open(_write_project_config(ions_only_root))
    ions_only_inputs = ions_only_root / "inputs"
    ions_only_inputs.mkdir()
    (ions_only_inputs / "receptor.pdb").write_text("ATOM\n", encoding="utf-8")
    (ions_only_inputs / "ligante.pdb").write_text("ATOM\n", encoding="utf-8")
    ions_only_box = ions_only_root / "work" / "box"
    ions_only_box.mkdir(parents=True)
    (ions_only_box / "ions.tpr").write_text("IONS_TPR\n", encoding="utf-8")
    ions_only_topology = ions_only_root / "work" / "topo" / "topol_solvated.top"
    ions_only_topology.parent.mkdir(parents=True)
    ions_only_topology.write_text("SOLVATED\n", encoding="utf-8")
    ions_only_report = ions_only_project.run(from_step="ions", until="ions")

    em_grompp_only_root = tmp_path / "em_grompp_only_project"
    em_grompp_only_project = GmxFlowProject.open(
        _write_project_config(em_grompp_only_root)
    )
    em_grompp_only_inputs = em_grompp_only_root / "inputs"
    em_grompp_only_inputs.mkdir()
    (em_grompp_only_inputs / "receptor.pdb").write_text(
        "ATOM\n", encoding="utf-8"
    )
    (em_grompp_only_inputs / "ligante.pdb").write_text(
        "ATOM\n", encoding="utf-8"
    )
    em_grompp_only_dir = em_grompp_only_root / "work" / "em"
    em_grompp_only_dir.mkdir(parents=True)
    (em_grompp_only_dir / "em.mdp").write_text("MDP\n", encoding="utf-8")
    em_grompp_only_box = em_grompp_only_root / "work" / "box"
    em_grompp_only_box.mkdir(parents=True)
    (em_grompp_only_box / "ions.gro").write_text("IONS\n", encoding="utf-8")
    em_grompp_only_topology = (
        em_grompp_only_root / "work" / "topo" / "topol_ions.top"
    )
    em_grompp_only_topology.parent.mkdir(parents=True)
    em_grompp_only_topology.write_text("IONIZED\n", encoding="utf-8")
    em_grompp_only_report = em_grompp_only_project.run(
        from_step="em-grompp", until="em-grompp"
    )

    em_only_root = tmp_path / "em_only_project"
    em_only_project = GmxFlowProject.open(_write_project_config(em_only_root))
    em_only_inputs = em_only_root / "inputs"
    em_only_inputs.mkdir()
    (em_only_inputs / "receptor.pdb").write_text("ATOM\n", encoding="utf-8")
    (em_only_inputs / "ligante.pdb").write_text("ATOM\n", encoding="utf-8")
    em_only_dir = em_only_root / "work" / "em"
    em_only_dir.mkdir(parents=True)
    (em_only_dir / "em.tpr").write_text("EM_TPR\n", encoding="utf-8")
    em_only_report = em_only_project.run(from_step="em", until="em")

    nvt_grompp_only_root = tmp_path / "nvt_grompp_only_project"
    nvt_grompp_only_project = GmxFlowProject.open(
        _write_project_config(nvt_grompp_only_root)
    )
    nvt_grompp_only_inputs = nvt_grompp_only_root / "inputs"
    nvt_grompp_only_inputs.mkdir()
    (nvt_grompp_only_inputs / "receptor.pdb").write_text(
        "ATOM\n", encoding="utf-8"
    )
    (nvt_grompp_only_inputs / "ligante.pdb").write_text(
        "ATOM\n", encoding="utf-8"
    )
    nvt_grompp_only_dir = nvt_grompp_only_root / "work" / "nvt"
    nvt_grompp_only_dir.mkdir(parents=True)
    (nvt_grompp_only_dir / "nvt.mdp").write_text("MDP\n", encoding="utf-8")
    nvt_grompp_only_em = nvt_grompp_only_root / "work" / "em"
    nvt_grompp_only_em.mkdir(parents=True)
    (nvt_grompp_only_em / "em.gro").write_text("EM_GRO\n", encoding="utf-8")
    nvt_grompp_only_topology = (
        nvt_grompp_only_root / "work" / "topo" / "topol_ions.top"
    )
    nvt_grompp_only_topology.parent.mkdir(parents=True)
    nvt_grompp_only_topology.write_text("IONIZED\n", encoding="utf-8")
    nvt_grompp_only_report = nvt_grompp_only_project.run(
        from_step="nvt-grompp", until="nvt-grompp"
    )

    nvt_only_root = tmp_path / "nvt_only_project"
    nvt_only_project = GmxFlowProject.open(_write_project_config(nvt_only_root))
    nvt_only_inputs = nvt_only_root / "inputs"
    nvt_only_inputs.mkdir()
    (nvt_only_inputs / "receptor.pdb").write_text("ATOM\n", encoding="utf-8")
    (nvt_only_inputs / "ligante.pdb").write_text("ATOM\n", encoding="utf-8")
    nvt_only_dir = nvt_only_root / "work" / "nvt"
    nvt_only_dir.mkdir(parents=True)
    (nvt_only_dir / "nvt.tpr").write_text("NVT_TPR\n", encoding="utf-8")
    nvt_only_report = nvt_only_project.run(from_step="nvt", until="nvt")

    npt_grompp_only_root = tmp_path / "npt_grompp_only_project"
    npt_grompp_only_project = GmxFlowProject.open(
        _write_project_config(npt_grompp_only_root)
    )
    npt_grompp_only_inputs = npt_grompp_only_root / "inputs"
    npt_grompp_only_inputs.mkdir()
    (npt_grompp_only_inputs / "receptor.pdb").write_text(
        "ATOM\n", encoding="utf-8"
    )
    (npt_grompp_only_inputs / "ligante.pdb").write_text(
        "ATOM\n", encoding="utf-8"
    )
    npt_grompp_only_dir = npt_grompp_only_root / "work" / "npt"
    npt_grompp_only_dir.mkdir(parents=True)
    (npt_grompp_only_dir / "npt.mdp").write_text("MDP\n", encoding="utf-8")
    npt_grompp_only_nvt = npt_grompp_only_root / "work" / "nvt"
    npt_grompp_only_nvt.mkdir(parents=True)
    (npt_grompp_only_nvt / "nvt.gro").write_text("NVT_GRO\n", encoding="utf-8")
    (npt_grompp_only_nvt / "nvt.cpt").write_text("NVT_CPT\n", encoding="utf-8")
    npt_grompp_only_topology = (
        npt_grompp_only_root / "work" / "topo" / "topol_ions.top"
    )
    npt_grompp_only_topology.parent.mkdir(parents=True)
    npt_grompp_only_topology.write_text("IONIZED\n", encoding="utf-8")
    npt_grompp_only_report = npt_grompp_only_project.run(
        from_step="npt-grompp", until="npt-grompp"
    )

    npt_only_root = tmp_path / "npt_only_project"
    npt_only_project = GmxFlowProject.open(_write_project_config(npt_only_root))
    npt_only_inputs = npt_only_root / "inputs"
    npt_only_inputs.mkdir()
    (npt_only_inputs / "receptor.pdb").write_text("ATOM\n", encoding="utf-8")
    (npt_only_inputs / "ligante.pdb").write_text("ATOM\n", encoding="utf-8")
    npt_only_dir = npt_only_root / "work" / "npt"
    npt_only_dir.mkdir(parents=True)
    (npt_only_dir / "npt.tpr").write_text("NPT_TPR\n", encoding="utf-8")
    npt_only_report = npt_only_project.run(from_step="npt", until="npt")

    production_grompp_only_root = tmp_path / "production_grompp_only_project"
    production_grompp_only_project = GmxFlowProject.open(
        _write_project_config(production_grompp_only_root)
    )
    production_grompp_only_inputs = production_grompp_only_root / "inputs"
    production_grompp_only_inputs.mkdir()
    (production_grompp_only_inputs / "receptor.pdb").write_text(
        "ATOM\n", encoding="utf-8"
    )
    (production_grompp_only_inputs / "ligante.pdb").write_text(
        "ATOM\n", encoding="utf-8"
    )
    production_grompp_only_dir = production_grompp_only_root / "work" / "prod"
    production_grompp_only_dir.mkdir(parents=True)
    (production_grompp_only_dir / "md.mdp").write_text("MDP\n", encoding="utf-8")
    production_grompp_only_npt = production_grompp_only_root / "work" / "npt"
    production_grompp_only_npt.mkdir(parents=True)
    (production_grompp_only_npt / "npt.gro").write_text("NPT_GRO\n", encoding="utf-8")
    (production_grompp_only_npt / "npt.cpt").write_text("NPT_CPT\n", encoding="utf-8")
    production_grompp_only_topology = (
        production_grompp_only_root / "work" / "topo" / "topol_ions.top"
    )
    production_grompp_only_topology.parent.mkdir(parents=True)
    production_grompp_only_topology.write_text("IONIZED\n", encoding="utf-8")
    production_grompp_only_report = production_grompp_only_project.run(
        from_step="production-grompp", until="production-grompp"
    )

    production_only_root = tmp_path / "production_only_project"
    production_only_project = GmxFlowProject.open(
        _write_project_config(production_only_root)
    )
    production_only_inputs = production_only_root / "inputs"
    production_only_inputs.mkdir()
    (production_only_inputs / "receptor.pdb").write_text(
        "ATOM\n", encoding="utf-8"
    )
    (production_only_inputs / "ligante.pdb").write_text(
        "ATOM\n", encoding="utf-8"
    )
    production_only_dir = production_only_root / "work" / "prod"
    production_only_dir.mkdir(parents=True)
    (production_only_dir / "md.tpr").write_text("MD_TPR\n", encoding="utf-8")
    production_only_report = production_only_project.run(
        from_step="production", until="production"
    )

    pbc_nojump_only_root = tmp_path / "pbc_nojump_only_project"
    pbc_nojump_only_project = GmxFlowProject.open(
        _write_project_config(pbc_nojump_only_root)
    )
    pbc_nojump_only_inputs = pbc_nojump_only_root / "inputs"
    pbc_nojump_only_inputs.mkdir()
    (pbc_nojump_only_inputs / "receptor.pdb").write_text(
        "ATOM\n", encoding="utf-8"
    )
    (pbc_nojump_only_inputs / "ligante.pdb").write_text(
        "ATOM\n", encoding="utf-8"
    )
    pbc_nojump_only_dir = pbc_nojump_only_root / "work" / "prod"
    pbc_nojump_only_dir.mkdir(parents=True)
    (pbc_nojump_only_dir / "md.tpr").write_text("MD_TPR\n", encoding="utf-8")
    (pbc_nojump_only_dir / "md.xtc").write_text("MD_XTC\n", encoding="utf-8")
    pbc_nojump_only_report = pbc_nojump_only_project.run(
        from_step="pbc-nojump", until="pbc-nojump"
    )

    pbc_center_only_root = tmp_path / "pbc_center_only_project"
    pbc_center_only_project = GmxFlowProject.open(
        _write_project_config(pbc_center_only_root)
    )
    pbc_center_only_inputs = pbc_center_only_root / "inputs"
    pbc_center_only_inputs.mkdir()
    (pbc_center_only_inputs / "receptor.pdb").write_text(
        "ATOM\n", encoding="utf-8"
    )
    (pbc_center_only_inputs / "ligante.pdb").write_text(
        "ATOM\n", encoding="utf-8"
    )
    pbc_center_only_dir = pbc_center_only_root / "work" / "prod"
    pbc_center_only_dir.mkdir(parents=True)
    (pbc_center_only_dir / "md.tpr").write_text("MD_TPR\n", encoding="utf-8")
    (pbc_center_only_dir / "md_nojump.xtc").write_text(
        "NOJUMP_XTC\n", encoding="utf-8"
    )
    pbc_center_only_report = pbc_center_only_project.run(
        from_step="pbc-center", until="pbc-center"
    )

    fit_only_root = tmp_path / "fit_only_project"
    fit_only_project = GmxFlowProject.open(_write_project_config(fit_only_root))
    fit_only_inputs = fit_only_root / "inputs"
    fit_only_inputs.mkdir()
    (fit_only_inputs / "receptor.pdb").write_text("ATOM\n", encoding="utf-8")
    (fit_only_inputs / "ligante.pdb").write_text("ATOM\n", encoding="utf-8")
    fit_only_dir = fit_only_root / "work" / "prod"
    fit_only_dir.mkdir(parents=True)
    (fit_only_dir / "md.tpr").write_text("MD_TPR\n", encoding="utf-8")
    (fit_only_dir / "md_nopbc.xtc").write_text("CENTERED_XTC\n", encoding="utf-8")
    fit_only_report = fit_only_project.run(from_step="fit", until="fit")

    analysis_only_root = tmp_path / "analysis_only_project"
    analysis_only_project = GmxFlowProject.open(
        _write_project_config(analysis_only_root)
    )
    analysis_only_inputs = analysis_only_root / "inputs"
    analysis_only_inputs.mkdir()
    (analysis_only_inputs / "receptor.pdb").write_text("ATOM\n", encoding="utf-8")
    (analysis_only_inputs / "ligante.pdb").write_text("ATOM\n", encoding="utf-8")
    analysis_only_dir = analysis_only_root / "work" / "prod"
    analysis_only_dir.mkdir(parents=True)
    (analysis_only_dir / "md.tpr").write_text("MD_TPR\n", encoding="utf-8")
    (analysis_only_dir / "md_fit.xtc").write_text("FIT_XTC\n", encoding="utf-8")
    analysis_only_report = analysis_only_project.run(
        from_step="analysis", until="analysis"
    )

    thermo_only_root = tmp_path / "thermo_only_project"
    thermo_only_project = GmxFlowProject.open(_write_project_config(thermo_only_root))
    thermo_only_inputs = thermo_only_root / "inputs"
    thermo_only_inputs.mkdir()
    (thermo_only_inputs / "receptor.pdb").write_text("ATOM\n", encoding="utf-8")
    (thermo_only_inputs / "ligante.pdb").write_text("ATOM\n", encoding="utf-8")
    for phase in ("em", "nvt", "npt"):
        phase_dir = thermo_only_root / "work" / phase
        phase_dir.mkdir(parents=True)
        (phase_dir / f"{phase}.edr").write_text("ENERGY\n", encoding="utf-8")
    thermo_only_report = thermo_only_project.run(
        from_step="thermodynamics", until="thermodynamics"
    )

    legacy_steps = build_pipeline(
        project.config,
        config_dir=legacy_root,
        config_path=legacy_config,
    )[:20]
    legacy_results = run_steps(legacy_steps, project_root=legacy_root)

    assert len(graph_report.steps) == len(legacy_results) == 20
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
    assert ions_only_report.steps[0].step_name == "ions"
    assert ions_only_report.steps[0].returncode == 0
    assert em_grompp_only_report.steps[0].step_name == "em-grompp"
    assert em_grompp_only_report.steps[0].returncode == 0
    assert em_only_report.steps[0].step_name == "em"
    assert em_only_report.steps[0].returncode == 0
    assert nvt_grompp_only_report.steps[0].step_name == "nvt-grompp"
    assert nvt_grompp_only_report.steps[0].returncode == 0
    assert nvt_only_report.steps[0].step_name == "nvt"
    assert nvt_only_report.steps[0].returncode == 0
    assert npt_grompp_only_report.steps[0].step_name == "npt-grompp"
    assert npt_grompp_only_report.steps[0].returncode == 0
    assert npt_only_report.steps[0].step_name == "npt"
    assert npt_only_report.steps[0].returncode == 0
    assert production_grompp_only_report.steps[0].step_name == "production-grompp"
    assert production_grompp_only_report.steps[0].returncode == 0
    assert production_only_report.steps[0].step_name == "production"
    assert production_only_report.steps[0].returncode == 0
    assert pbc_nojump_only_report.steps[0].step_name == "pbc-nojump"
    assert pbc_nojump_only_report.steps[0].returncode == 0
    assert pbc_center_only_report.steps[0].step_name == "pbc-center"
    assert pbc_center_only_report.steps[0].returncode == 0
    assert fit_only_report.steps[0].step_name == "fit"
    assert fit_only_report.steps[0].returncode == 0
    assert analysis_only_report.steps[0].step_name == "analysis"
    assert analysis_only_report.steps[0].returncode == 0
    assert thermo_only_report.steps[0].step_name == "thermodynamics"
    assert thermo_only_report.steps[0].returncode == 0
    assert len(subprocess_calls) == 58  # graph, isolated steps, and legacy prefix
    assert sum(
        command[-1:] == ("nojump",) and stdin == "0\n"
        for command, stdin in subprocess_inputs
    ) == 3  # graph run, isolated graph step, and legacy reference
    assert sum(
        "-center" in command and stdin == "Protein\nSystem\n"
        for command, stdin in subprocess_inputs
    ) == 3  # graph run, isolated graph step, and legacy reference
    assert sum(
        "-fit" in command and stdin == "Backbone\nSystem\n"
        for command, stdin in subprocess_inputs
    ) == 3  # graph run, isolated graph step, and legacy reference
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
        legacy_outputs = sorted((legacy_root / relative_dir).glob("*"))
        assert [path.name for path in graph_outputs] == [
            path.name for path in legacy_outputs
        ]
        assert [path.read_bytes() for path in graph_outputs] == [
            path.read_bytes() for path in legacy_outputs
        ]


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
        lambda config, project_root: StepResult(
            step_name="workspace",
            command=["<internal>", "ensure-workspace"],
            workdir=project_root / "work",
            log_path=project_root / "work" / "logs" / "00_workspace.log",
            returncode=0,
            elapsed_seconds=0.0,
        ),
    )

    calls: list[tuple[str, ...]] = []

    def fake_subprocess_run(command, *, cwd, **kwargs):
        calls.append(tuple(command))
        for output in project.plan(until="interaction-energy")[-1].outputs:
            (Path(cwd) / output.name).write_text("SIMULATED\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("gmxflow.executor.subprocess.run", fake_subprocess_run)

    report = project.run(
        from_step="interaction-energy", until="interaction-energy"
    )

    assert len(calls) == 1
    assert report.steps[0].step_name == "interaction-energy"
    assert report.steps[0].returncode == 0
    assert all(
        output.is_file()
        for output in project.plan(until="interaction-energy")[-1].outputs
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
        lambda config, project_root: StepResult(
            step_name="workspace",
            command=["<internal>", "ensure-workspace"],
            workdir=project_root / "work",
            log_path=project_root / "work" / "logs" / "00_workspace.log",
            returncode=0,
            elapsed_seconds=0.0,
        ),
    )

    calls: list[tuple[str, ...]] = []

    def fake_subprocess_run(command, *, cwd, **kwargs):
        calls.append(tuple(command))
        for output in project.plan(until="sasa")[-1].outputs:
            (Path(cwd) / output.name).write_text("SIMULATED\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("gmxflow.executor.subprocess.run", fake_subprocess_run)

    report = project.run(from_step="sasa", until="sasa")

    assert len(calls) == 1
    assert report.steps[0].step_name == "sasa"
    assert report.steps[0].returncode == 0
    assert all(output.is_file() for output in project.plan(until="sasa")[-1].outputs)


def test_plots_runs_through_graph_when_started_directly(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = tmp_path / "plot_project"
    project = GmxFlowProject.open(_write_project_config(project_root))
    inputs_dir = project_root / "inputs"
    inputs_dir.mkdir()
    (inputs_dir / "receptor.pdb").write_text("ATOM\n", encoding="utf-8")
    (inputs_dir / "ligante.pdb").write_text("ATOM\n", encoding="utf-8")

    plots_step = project.plan(until="plots")[-1]
    for input_path in plots_step.inputs:
        input_path.parent.mkdir(parents=True, exist_ok=True)
        input_path.write_text("PLOT_INPUT\n", encoding="utf-8")

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

    calls: list[tuple[str, ...]] = []

    def fake_subprocess_run(command, *, cwd, **kwargs):
        calls.append(tuple(command))
        for output in plots_step.outputs:
            (Path(cwd) / output.name).write_text("PLOT\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("gmxflow.executor.subprocess.run", fake_subprocess_run)

    report = project.run(from_step="plots", until="plots")

    assert len(calls) == 1
    assert report.steps[0].step_name == "plots"
    assert report.steps[0].returncode == 0
    assert all(output.is_file() for output in plots_step.outputs)


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
