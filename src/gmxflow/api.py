"""Initial experimental Python API for working with gmxflow projects."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from gmxflow.config import GmxFlowConfig, load_config
from gmxflow.executor import (
    StepResult,
    run_steps,
    run_workspace_setup,
    select_steps,
)
from gmxflow.forcefields import resolve_forcefield
from gmxflow.pipeline import (
    REAL_EXECUTION_STEPS,
    PipelineStep,
    build_pipeline,
)
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


@dataclass(frozen=True)
class GmxFlowProject:
    """A project loaded from its configuration file.

    This experimental API supports loading, validating, planning, and running
    a project. Its public contract is not yet stable.
    """

    config_path: Path
    config: GmxFlowConfig

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
        results = run_steps(
            steps,
            project_root=self.root,
            start_index=1,
            on_step_start=on_step_start,
            on_step_done=on_step_done,
        )
        return ExecutionReport(
            workspace=workspace_result,
            steps=tuple(results),
        )
