"""Initial experimental Python API for working with gmxflow projects."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

from gmxflow.config import GmxFlowConfig, load_config
from gmxflow.executor import (
    StepResult,
    WorkflowExecutionError,
    WorkflowStepResult,
    WorkflowStepStatus,
    run_steps,
    run_workflow_graph,
    run_workspace_setup,
    runtime_command,
    select_steps,
)
from gmxflow.forcefields import resolve_forcefield
from gmxflow.pipeline import (
    REAL_EXECUTION_STEPS,
    PipelineCommandStep,
    PipelineStep,
    Step,
    Sequence as WorkflowSequence,
    WorkflowGraph,
    build_pipeline,
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

    This experimental API supports creating and loading projects, validating
    prerequisites, planning, running, and displaying results. Its public
    contract is not yet stable.
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

    def show_execution(self, report: ExecutionReport) -> None:
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

    def plan(
        self,
        *,
        strict_inputs: bool = False,
        from_step: str | None = None,
        until: str | None = None,
    ) -> list[PipelineStep]:
        """Build and optionally narrow the execution plan without running it."""
        steps = build_pipeline(
            self.config,
            config_dir=self.root,
            config_path=self.config_path,
            strict_inputs=strict_inputs,
        )
        return select_steps(steps, from_step=from_step, until=until)

    def validate(self) -> ValidationReport:
        """Check required input files, force field, and GROMACS executable.

        This method does not create project directories or execute commands.
        It raises ``FileNotFoundError`` with the missing prerequisite when a
        required input, force field, or executable cannot be found.
        """
        steps = self.plan(strict_inputs=True)
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

        input_files = list(steps[0].inputs)
        ligand_topology = next(
            (step for step in steps if step.name == "ligand-topology"), None
        )
        if ligand_topology is not None:
            input_files.extend(ligand_topology.inputs)

        return ValidationReport(
            config_path=self.config_path,
            project_root=self.root,
            input_files=tuple(input_files),
            force_field_path=force_field.path,
            gromacs_executable=Path(executable).resolve(),
            planned_steps=tuple(step.name for step in steps),
        )

    def run(
        self,
        *,
        from_step: str | None = None,
        until: str | None = None,
        on_step_start: Callable[[int, PipelineStep], None] | None = None,
        on_step_done: Callable[[int, StepResult], None] | None = None,
    ) -> ExecutionReport:
        """Validate prerequisites and execute the selected project steps.

        Workspace setup preserves existing templates. Execution uses the same
        logs, persistent state, and resume behavior as the CLI. A failed step
        raises ``RuntimeError`` containing its name and log path.
        """
        self.validate()
        steps = self.plan(strict_inputs=True, from_step=from_step, until=until)
        blocked_steps = [
            step.name for step in steps if step.name not in REAL_EXECUTION_STEPS
        ]
        if blocked_steps:
            raise ValueError(
                "Etapas ainda não liberadas para execução real: "
                + ", ".join(blocked_steps)
            )

        workspace_result = run_workspace_setup(
            self.config, project_root=self.root
        )
        results: list[StepResult] = []
        remaining_steps = steps
        start_index = 1
        graph_step_count = 0
        graph_step_names = {
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
        }
        if self.config.input.ligand_kind in {"peptide", "none"}:
            graph_step_names.update(
                {"analysis", "thermodynamics", "plots", "report"}
            )
        if (
            self.config.input.ligand_kind == "peptide"
            and self.config.analysis.interaction_energy
        ):
            graph_step_names.add("interaction-energy")
        if (
            self.config.input.ligand_kind == "peptide"
            and self.config.analysis.sasa
        ):
            graph_step_names.add("sasa")
        if steps and steps[0].name in graph_step_names:
            graph_step_count = next(
                (
                    index
                    for index, step in enumerate(steps)
                    if step.name not in graph_step_names
                ),
                len(steps),
            )
        if graph_step_count:
            results.extend(
                _run_graph_steps(
                    steps[:graph_step_count],
                    project_root=self.root,
                    on_step_start=on_step_start,
                    on_step_done=on_step_done,
                )
            )
            remaining_steps = steps[graph_step_count:]
            start_index = graph_step_count + 1
        if remaining_steps:
            results.extend(
                run_steps(
                    remaining_steps,
                    project_root=self.root,
                    start_index=start_index,
                    on_step_start=on_step_start,
                    on_step_done=on_step_done,
                )
            )
        return ExecutionReport(
            workspace=workspace_result,
            steps=tuple(results),
        )


def _run_graph_steps(
    steps: list[PipelineStep],
    *,
    project_root: Path,
    on_step_start: Callable[[int, PipelineStep], None] | None,
    on_step_done: Callable[[int, StepResult], None] | None,
) -> list[StepResult]:
    """Run a selected prefix of legacy command steps through the graph."""
    adapted_steps = [
        replace(
            PipelineCommandStep.from_pipeline_step(step),
            command=tuple(runtime_command(step.command)),
        )
        for step in steps
    ]
    workflow = (
        WorkflowSequence(*adapted_steps)
        if len(adapted_steps) > 1
        else adapted_steps[0]
    )
    produced_keys = {
        artifact.key for step in adapted_steps for artifact in step.outputs
    }
    project_inputs = {
        artifact.key: artifact
        for step in adapted_steps
        for artifact in step.inputs
        if artifact.key not in produced_keys
    }
    graph = WorkflowGraph.from_workflow(
        workflow,
        project_inputs=project_inputs.values(),
    )
    artifact_paths = {
        artifact.key: Path(artifact.key)
        for step in adapted_steps
        for artifact in (*step.inputs, *step.outputs)
    }
    step_indexes = {step.name: index for index, step in enumerate(steps, start=1)}
    legacy_steps = {step.name: step for step in steps}

    def notify_start(adapted_step: Step) -> None:
        if on_step_start is not None:
            step = legacy_steps[adapted_step.id]
            on_step_start(step_indexes[adapted_step.id], step)

    def to_api_result(workflow_result: WorkflowStepResult) -> StepResult:
        step = legacy_steps[workflow_result.step_id]
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
            step_name=step.name,
            command=list(runtime_command(step.command)),
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
    results = [to_api_result(graph_results[step.name]) for step in steps]
    failed_result = next(
        (
            result
            for result in results
            if graph_results[result.step_name].status is WorkflowStepStatus.FAILED
        ),
        None,
    )
    if failed_result is not None:
        raise RuntimeError(
            f"Etapa '{failed_result.step_name}' falhou com codigo "
            f"{failed_result.returncode}. Log: {failed_result.log_path}"
        )
    return results
