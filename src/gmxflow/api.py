"""Initial experimental Python API for working with gmxflow projects."""

from __future__ import annotations

import shutil
from collections.abc import Iterable, Mapping
from copy import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from gmxflow.config import GmxFlowConfig, load_config
from gmxflow.executor import (
    StepResult,
    WorkflowExecutionError,
    WorkflowExecutionReport,
    WorkflowStepResult,
    WorkflowStepStatus,
    run_workflow_graph,
    run_workspace_setup,
    runtime_command,
)
from gmxflow.forcefields import resolve_forcefield
from gmxflow.pipeline import (
    Artifact,
    REAL_EXECUTION_STEPS,
    GromacsCommandStep,
    Parallel,
    Step,
    Sequence as WorkflowSequence,
    WorkflowGraph,
    WorkflowItem,
    build_workflow,
)
from gmxflow.preparation.structure import require_mdanalysis
from gmxflow.project import create_project as create_project_files
from gmxflow.workspace import CleanResult, clean_workspace


@dataclass(frozen=True)
class ValidationReport:
    """Summary of the project prerequisites checked without running GROMACS."""

    config_path: Path
    project_root: Path
    input_files: tuple[Path, ...]
    force_field_path: Path
    gromacs_executable: Path
    planned_steps: tuple[str, ...]


@dataclass(frozen=True)
class ExecutionReport:
    """Results from the workspace setup and executed pipeline steps."""

    workspace: StepResult
    steps: tuple[StepResult, ...]

    @property
    def results(self) -> tuple[StepResult, ...]:
        """Return workspace and pipeline results in execution order."""
        return (self.workspace, *self.steps)


@dataclass
class GmxFlowProject:
    """A project loaded from its configuration file.

    This experimental API supports creating and loading projects, composing
    workflows, validating prerequisites, running them, and displaying results.
    Its public contract is not yet stable.
    """

    config_path: Path
    config: GmxFlowConfig

    @classmethod
    def create(
        cls,
        name: str,
        destination: str | Path = ".",
        *,
        receptor: str | None = None,
        ligand: str | None = None,
        ligand_kind: str = "peptide",
        gpu: str = "auto",
        profile: str = "standard",
        force: bool = False,
    ) -> GmxFlowProject:
        """Create a project directory and return the newly opened project.

        ``destination`` is the parent directory; the project is created in a
        child directory named ``name``. Existing projects are not overwritten
        unless ``force=True`` is explicitly provided.
        """
        project_dir = create_project_files(
            name=name,
            destination=Path(destination).expanduser().resolve(),
            force=force,
            receptor=receptor,
            ligand=ligand,
            ligand_kind=ligand_kind,
            gpu=gpu,
            profile=profile,
        )
        return cls.open(project_dir / "project.toml")

    @classmethod
    def open(cls, config_path: str | Path = "project.toml") -> GmxFlowProject:
        """Load and validate a project configuration from a TOML file."""
        path = Path(config_path).expanduser().resolve()
        return cls(config_path=path, config=load_config(path))

    @property
    def root(self) -> Path:
        """Return the directory containing the project's configuration."""
        return self.config_path.parent

    def show_report(self) -> None:
        """Display the generated report inline in a Jupyter notebook."""
        from gmxflow.notebook import show_report

        show_report(self.root, self.config)

    def edit_config(self) -> Any:
        """Display an interactive notebook form for editing ``project.toml``."""
        from gmxflow.notebook_config import edit_project_config

        return edit_project_config(self)

    def show_execution(self, report: ExecutionReport | WorkflowExecutionReport) -> None:
        """Display an execution summary with statuses, durations, and log paths."""
        from gmxflow.notebook import show_execution

        show_execution(report.results)

    def clean(
        self,
        *,
        remove_templates: bool = False,
        all_work: bool = False,
    ) -> CleanResult:
        """Remove generated files from ``work/`` without touching inputs or outputs.

        By default, rendered ``.mdp`` templates are preserved. Set
        ``remove_templates=True`` to remove them, or ``all_work=True`` to remove
        and recreate the entire ``work/`` directory tree.
        """
        return clean_workspace(
            project_root=self.root,
            remove_templates=remove_templates,
            all_work=all_work,
        )

    def workflow(
        self,
        *,
        from_step: str | None = None,
        until: str | None = None,
    ) -> WorkflowSequence:
        """Return concrete project Steps, ready to compose with custom Steps.

        The returned workflow is newly built and can be split, reordered, or
        combined with ``Sequence``, ``Parallel``, and the ``|`` operator.
        Creating it does not validate files, initialize workspaces, or execute
        any commands.
        """
        return build_workflow(
            self.config,
            self.root,
            config_path=self.config_path,
            from_step=from_step,
            until=until,
        )

    def validate(self) -> ValidationReport:
        """Check required input files, force field, and GROMACS executable.

        This method does not create project directories or execute commands.
        It raises ``FileNotFoundError`` with the missing prerequisite when a
        required input, force field, or executable cannot be found.
        """
        workflow = self.workflow()
        graph, _ = _project_workflow_graph(workflow)
        input_paths = _configured_input_paths(self.config, self.root)
        for path in input_paths:
            if not path.is_file():
                raise FileNotFoundError(f"Arquivo de entrada não encontrado: {path}")

        if self.config.input.remove_resnames:
            try:
                require_mdanalysis()
            except RuntimeError as error:
                raise RuntimeError(
                    f"Pré-requisito ausente no projeto {self.config_path}: {error}"
                ) from error
        gromacs_command = (
            self.config.mdrun.engine
            if self.config.mdrun.engine in {"gmx", "gmx_mpi"}
            else "gmx"
        )
        executable = shutil.which(gromacs_command)
        if executable is None:
            raise FileNotFoundError(
                f"Executável GROMACS '{gromacs_command}' não encontrado no PATH. "
                "Ative o ambiente Conda/Micromamba que contém o GROMACS."
            )

        force_field = resolve_forcefield(
            self.config.force_field.name,
            project_root=self.root,
        )
        if force_field is None:
            raise FileNotFoundError(
                f"Force field '{self.config.force_field.name}' não encontrado. "
                "Verifique a instalação do GROMACS ou use "
                "'gmxflow forcefield locate'."
            )

        return ValidationReport(
            config_path=self.config_path,
            project_root=self.root,
            input_files=input_paths,
            force_field_path=force_field.path,
            gromacs_executable=Path(executable).resolve(),
            planned_steps=graph.topological_order,
        )

    def run(
        self,
        *,
        from_step: str | None = None,
        until: str | None = None,
        on_step_start: Callable[[int, GromacsCommandStep], None] | None = None,
        on_step_done: Callable[[int, StepResult], None] | None = None,
    ) -> ExecutionReport:
        """Validate prerequisites and execute the selected project steps.

        Workspace setup preserves existing templates. The API executes the
        selected workflow through the graph executor and persists its state in
        ``work/workflow_state.json``, independently from the CLI state file. A
        failed step raises ``RuntimeError`` containing its ID and log path.
        ``on_step_start`` receives the concrete Step; use ``step.id`` as its
        stable identifier and ``step.name`` as its human-readable label.
        """
        self.validate()
        workflow = self.workflow(from_step=from_step, until=until)
        steps = tuple(_iter_workflow_steps(workflow))
        blocked_steps = [
            step.id for step in steps if step.id not in REAL_EXECUTION_STEPS
        ]
        if blocked_steps:
            raise ValueError(
                "Etapas ainda não liberadas para execução real: "
                + ", ".join(blocked_steps)
            )

        workspace_result = run_workspace_setup(
            self.config,
            project_root=self.root,
            state_path=self.root / "work" / "workflow_state.json",
        )
        results = _run_graph_steps(
            workflow=workflow,
            project_root=self.root,
            on_step_start=on_step_start,
            on_step_done=on_step_done,
        )
        return ExecutionReport(
            workspace=workspace_result,
            steps=tuple(results),
        )

    def run_workflow(
        self,
        workflow: WorkflowItem,
        *,
        project_inputs: Iterable[Artifact] | None = None,
        artifact_paths: Mapping[str, Path] | None = None,
        state_name: str = "project-workflow.json",
        dry_run: bool = False,
        on_step_start: Callable[[Step], None] | None = None,
        on_step_done: Callable[[WorkflowStepResult], None] | None = None,
    ) -> WorkflowExecutionReport:
        """Run a custom or project-composed Step workflow.

        Custom-only workflows still require external artifact paths but infer
        project inputs from undeclared producers. Paths for built-in GROMACS
        Steps are inferred; ``artifact_paths`` supplies paths for custom
        logical artifacts. When the workflow contains a GromacsCommandStep,
        a real run validates project prerequisites and initializes the normal
        workspace. A dry run remains structural and creates no workspace.
        """
        filename = Path(state_name)
        reserved_state_names = {"state.json", "workflow_state.json"}
        if (
            not state_name.strip()
            or filename.name != state_name
            or filename.stem in {"", ".", ".."}
            or filename.suffix != ".json"
            or filename.name.casefold() in reserved_state_names
            or "/" in state_name
            or "\\" in state_name
        ):
            raise ValueError(
                "state_name deve ser um nome simples de arquivo terminado em .json; "
                "state.json e workflow_state.json são reservados"
            )

        runtime_workflow = _with_runtime_commands(workflow)
        workflow_steps = tuple(_iter_workflow_steps(runtime_workflow))
        if project_inputs is None:
            produced = {
                artifact.key for step in workflow_steps for artifact in step.outputs
            }
            inferred_inputs: dict[str, Artifact] = {}
            for step in workflow_steps:
                for artifact in step.inputs:
                    if artifact.key not in produced:
                        inferred_inputs.setdefault(artifact.key, artifact)
            project_inputs = inferred_inputs.values()

        graph = WorkflowGraph.from_workflow(
            runtime_workflow,
            project_inputs=project_inputs,
        )
        resolved_paths: dict[str, Path] = {}
        for step in workflow_steps:
            if isinstance(step, GromacsCommandStep):
                for artifact, path in zip(
                    (*step.inputs, *step.outputs),
                    (*step.input_paths, *step.output_paths),
                    strict=True,
                ):
                    resolved_paths[artifact.key] = path
        for key, path in (artifact_paths or {}).items():
            if key in resolved_paths:
                expected = _resolve_project_path(resolved_paths[key], self.root)
                provided = _resolve_project_path(path, self.root)
                if expected != provided:
                    raise ValueError(
                        f"O caminho do artefato interno {key!r} não pode ser "
                        "substituído por um workflow customizado."
                    )
            else:
                resolved_paths[key] = path

        state_path = self.root / "work" / filename
        preflight = run_workflow_graph(
            graph,
            project_root=self.root,
            artifact_paths=resolved_paths,
            state_path=state_path,
            dry_run=True,
        )
        if dry_run:
            return preflight

        if any(isinstance(step, GromacsCommandStep) for step in workflow_steps):
            self.validate()
            run_workspace_setup(
                self.config,
                project_root=self.root,
                state_path=state_path,
            )

        return run_workflow_graph(
            graph,
            project_root=self.root,
            artifact_paths=preflight.artifact_paths,
            state_path=state_path,
            on_step_start=on_step_start,
            on_step_done=on_step_done,
        )


def _with_runtime_commands(workflow: WorkflowItem) -> WorkflowItem:
    if isinstance(workflow, WorkflowSequence):
        return WorkflowSequence(
            *(_with_runtime_commands(item) for item in workflow.items)
        )
    if isinstance(workflow, Parallel):
        return Parallel(
            *(_with_runtime_commands(branch) for branch in workflow.branches)
        )
    if isinstance(workflow, GromacsCommandStep):
        step = copy(workflow)
        step.command = tuple(runtime_command(list(step.command)))
        return step
    return workflow


def _iter_workflow_steps(workflow: WorkflowItem) -> Iterable[Step]:
    if isinstance(workflow, WorkflowSequence):
        for item in workflow.items:
            yield from _iter_workflow_steps(item)
    elif isinstance(workflow, Parallel):
        for branch in workflow.branches:
            yield from _iter_workflow_steps(branch)
    else:
        yield workflow


def _resolve_project_path(path: Path, project_root: Path) -> Path:
    resolved = path.expanduser()
    if not resolved.is_absolute():
        resolved = project_root / resolved
    return resolved.resolve()


def _project_workflow_graph(
    workflow: WorkflowItem,
) -> tuple[WorkflowGraph, dict[str, Path]]:
    """Resolve project paths and external inputs for built-in GROMACS Steps."""
    steps = tuple(_iter_workflow_steps(workflow))
    concrete_steps = tuple(
        step for step in steps if isinstance(step, GromacsCommandStep)
    )
    if len(concrete_steps) != len(steps):
        raise TypeError("A validação de projeto requer GromacsCommandStep.")

    produced_keys = {
        artifact.key for step in concrete_steps for artifact in step.outputs
    }
    input_artifacts: dict[str, Artifact] = {}
    artifact_paths: dict[str, Path] = {}
    for step in concrete_steps:
        for artifact, path in zip(
            (*step.inputs, *step.outputs),
            (*step.input_paths, *step.output_paths),
            strict=True,
        ):
            existing_path = artifact_paths.get(artifact.key)
            if existing_path is not None and existing_path != path:
                raise ValueError(
                    f"Artefato {artifact.key!r} aponta para caminhos distintos: "
                    f"{existing_path} e {path}."
                )
            artifact_paths[artifact.key] = path
        for artifact in step.inputs:
            if artifact.key not in produced_keys:
                input_artifacts.setdefault(artifact.key, artifact)

    graph = WorkflowGraph.from_workflow(
        workflow,
        project_inputs=input_artifacts.values(),
    )
    return graph, artifact_paths


def _run_graph_steps(
    *,
    workflow: WorkflowSequence,
    project_root: Path,
    on_step_start: Callable[[int, GromacsCommandStep], None] | None,
    on_step_done: Callable[[int, StepResult], None] | None,
) -> list[StepResult]:
    """Execute a composed workflow of concrete GROMACS command steps."""
    runtime_workflow = _with_runtime_commands(workflow)
    if not isinstance(runtime_workflow, WorkflowSequence):
        raise TypeError("A execução do projeto requer uma Sequence de Steps.")
    graph, artifact_paths = _project_workflow_graph(runtime_workflow)
    steps = tuple(_iter_workflow_steps(runtime_workflow))
    concrete_steps = tuple(
        step for step in steps if isinstance(step, GromacsCommandStep)
    )
    if len(concrete_steps) != len(steps):
        raise TypeError("A execução do projeto requer GromacsCommandStep.")
    steps_by_id = {step.id: step for step in concrete_steps}
    step_indexes = {
        step.id: index for index, step in enumerate(concrete_steps, start=1)
    }

    def notify_start(step: Step) -> None:
        if on_step_start is not None:
            on_step_start(step_indexes[step.id], steps_by_id[step.id])

    def to_api_result(workflow_result: WorkflowStepResult) -> StepResult:
        step = steps_by_id[workflow_result.step_id]
        returncode = next(
            (
                command.returncode
                for command in workflow_result.commands
                if command.returncode != 0
            ),
            1
            if workflow_result.status
            in {WorkflowStepStatus.FAILED, WorkflowStepStatus.BLOCKED}
            else 0,
        )
        return StepResult(
            step_name=step.id,
            command=runtime_command(list(step.command)),
            workdir=step.workdir,
            log_path=workflow_result.log_path,
            returncode=returncode,
            elapsed_seconds=workflow_result.elapsed_seconds,
            skipped=workflow_result.status is WorkflowStepStatus.SKIPPED,
        )

    def notify_done(workflow_result: WorkflowStepResult) -> None:
        if on_step_done is not None:
            on_step_done(
                step_indexes[workflow_result.step_id],
                to_api_result(workflow_result),
            )

    try:
        report = run_workflow_graph(
            graph,
            project_root=project_root,
            artifact_paths=artifact_paths,
            state_path=project_root / "work" / "workflow_state.json",
            on_step_start=notify_start,
            on_step_done=notify_done,
        )
    except WorkflowExecutionError as error:
        report = error.report

    graph_results = {result.step_id: result for result in report.results}
    results = [to_api_result(graph_results[step.id]) for step in concrete_steps]
    failed_result = next(
        (
            to_api_result(graph_results[step.id])
            for step in concrete_steps
            if graph_results[step.id].status is WorkflowStepStatus.FAILED
        ),
        None,
    )
    if failed_result is not None:
        raise RuntimeError(
            f"Etapa '{failed_result.step_name}' falhou com codigo "
            f"{failed_result.returncode}. Log: {failed_result.log_path}"
        )
    return results


def _configured_input_paths(
    config: GmxFlowConfig, project_root: Path
) -> tuple[Path, ...]:
    """Resolve only user-supplied input paths, excluding generated work files."""
    values = [config.input.receptor_pdb]
    if config.input.ligand_kind != "none":
        values.append(config.input.ligand_pdb)
    if config.input.ligand_kind == "small_molecule":
        values.extend((config.input.ligand_mol2, config.input.ligand_str))

    paths: list[Path] = []
    for value in values:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = project_root / path
        paths.append(path.resolve())
    return tuple(paths)
