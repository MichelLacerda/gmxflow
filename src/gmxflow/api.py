"""Initial experimental Python API for working with gmxflow projects."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gmxflow.config import GmxFlowConfig, load_config
from gmxflow.executor import select_steps
from gmxflow.pipeline import PipelineStep, build_pipeline


@dataclass(frozen=True)
class GmxFlowProject:
    """A project loaded from its configuration file.

    This initial API supports loading a project and inspecting its execution
    plan. Running simulations through the Python API is not implemented yet.
    """

    config_path: Path
    config: GmxFlowConfig

    @classmethod
    def open(cls, config_path: str | Path = "config.toml") -> GmxFlowProject:
        """Load and validate a project configuration from a TOML file."""
        path = Path(config_path).expanduser().resolve()
        return cls(config_path=path, config=load_config(path))

    @property
    def root(self) -> Path:
        """Return the directory containing the project's configuration."""
        return self.config_path.parent

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
