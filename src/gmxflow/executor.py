from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from time import perf_counter
from typing import Callable

from gmxflow.config import GmxFlowConfig
from gmxflow.pipeline import (
    Artifact,
    CommandResult,
    Step,
    WorkflowGraph,
)
from gmxflow.runner import format_command
from gmxflow.workspace import ensure_workspace

STATE_VERSION = 1
HASH_SIZE_LIMIT = 64 * 1024 * 1024


class WorkflowStepStatus(StrEnum):
    PLANNED = "planned"
    SUCCEEDED = "success"
    SKIPPED = "skipped"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class WorkflowStepResult:
    step_id: str
    status: WorkflowStepStatus
    log_path: Path
    elapsed_seconds: float = 0.0
    commands: tuple[CommandResult, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class WorkflowExecutionReport:
    results: tuple[WorkflowStepResult, ...]
    dependencies: Mapping[str, frozenset[str]]
    artifact_paths: Mapping[str, Path]
    dry_run: bool = False

    @property
    def succeeded(self) -> bool:
        return all(
            result.status
            in {
                WorkflowStepStatus.PLANNED,
                WorkflowStepStatus.SUCCEEDED,
                WorkflowStepStatus.SKIPPED,
            }
            for result in self.results
        )


class WorkflowExecutionError(RuntimeError):
    def __init__(self, report: WorkflowExecutionReport) -> None:
        self.report = report
        failed_ids = [
            result.step_id
            for result in report.results
            if result.status is WorkflowStepStatus.FAILED
        ]
        super().__init__("Workflow falhou nas etapas: " + ", ".join(failed_ids))


class CommandExecutionError(RuntimeError):
    def __init__(self, result: CommandResult) -> None:
        self.result = result
        super().__init__(
            f"Comando {format_command(list(result.argv))} terminou com "
            f"código {result.returncode}"
        )


def run_workflow_graph(
    graph: WorkflowGraph,
    *,
    project_root: Path,
    artifact_paths: Mapping[str, Path],
    state_path: Path | None = None,
    dry_run: bool = False,
    global_inputs: Sequence[Path] = (),
    on_step_start: Callable[[Step], None] | None = None,
    on_step_done: Callable[[WorkflowStepResult], None] | None = None,
) -> WorkflowExecutionReport:
    """Execute a validated graph sequentially, or return its dry-run plan.

    Artifact paths are supplied by the caller because graph artifacts have
    logical identities independent of any project directory layout. This
    executor deliberately does not schedule parallel branches concurrently.
    """
    root = project_root.expanduser().resolve()
    resolved_artifact_paths = _resolve_artifact_paths(graph, root, artifact_paths)
    resolved_global_inputs = tuple(
        path.expanduser().resolve() for path in global_inputs
    )
    log_dir = root / "work" / "logs"
    state_path = state_path or Path("work/state.json")
    if not state_path.is_absolute():
        state_path = root / state_path
    state_path = state_path.expanduser().resolve()
    ordered_ids = graph.topological_order
    log_paths = {
        step_id: log_dir / f"{index:02d}_{_safe_step_id(step_id)}.log"
        for index, step_id in enumerate(ordered_ids, start=1)
    }

    states: dict[str, WorkflowStepStatus] = {}
    results: list[WorkflowStepResult] = []

    def record_result(result: WorkflowStepResult) -> None:
        results.append(result)
        if on_step_done is not None:
            on_step_done(result)

    normalized_states = {
        step_id: _normalized_step_state(graph.steps[step_id]) for step_id in ordered_ids
    }

    external_inputs = {
        artifact.key
        for step in graph.steps.values()
        for artifact in step.inputs
        if graph.producers[artifact.key] is None
    }
    unavailable_project_inputs = [
        resolved_artifact_paths[key]
        for key in sorted(external_inputs)
        if not resolved_artifact_paths[key].exists()
        or not os.access(resolved_artifact_paths[key], os.R_OK)
    ]
    if unavailable_project_inputs and not dry_run:
        raise FileNotFoundError(
            "Inputs do projeto ausentes ou sem leitura: "
            + ", ".join(str(path) for path in unavailable_project_inputs)
        )

    if dry_run:
        results = [
            WorkflowStepResult(
                step_id=step_id,
                status=WorkflowStepStatus.PLANNED,
                log_path=log_paths[step_id],
            )
            for step_id in ordered_ids
        ]
        return WorkflowExecutionReport(
            results=tuple(results),
            dependencies=graph.dependencies,
            artifact_paths=MappingProxyType(resolved_artifact_paths),
            dry_run=True,
        )

    log_dir.mkdir(parents=True, exist_ok=True)
    for step_id in ordered_ids:
        step = graph.steps[step_id]
        if on_step_start is not None:
            on_step_start(step)
        step_log = log_paths[step_id]
        blocked_by = sorted(
            predecessor
            for predecessor in graph.dependencies[step_id]
            if states.get(predecessor)
            in {WorkflowStepStatus.FAILED, WorkflowStepStatus.BLOCKED}
        )
        if blocked_by:
            message = "Bloqueada por falha em: " + ", ".join(blocked_by)
            _write_workflow_log(
                step_log,
                step,
                status=WorkflowStepStatus.BLOCKED,
                started=None,
                elapsed=0.0,
                commands=(),
                error=message,
                input_paths=[resolved_artifact_paths[item.key] for item in step.inputs],
                output_paths=[
                    resolved_artifact_paths[item.key] for item in step.outputs
                ],
            )
            _write_workflow_state(
                state_path,
                step,
                status=WorkflowStepStatus.BLOCKED,
                state=normalized_states[step_id],
                inputs={},
                outputs=_fingerprints(
                    [resolved_artifact_paths[item.key] for item in step.outputs]
                ),
                log_path=step_log,
                elapsed=0.0,
                started=None,
            )
            states[step_id] = WorkflowStepStatus.BLOCKED
            record_result(
                WorkflowStepResult(
                    step_id=step_id,
                    status=WorkflowStepStatus.BLOCKED,
                    log_path=step_log,
                    error=message,
                )
            )
            continue

        input_paths = [resolved_artifact_paths[item.key] for item in step.inputs]
        tracked_paths = _unique_paths([*input_paths, *resolved_global_inputs])
        missing_inputs = [
            path
            for path in input_paths
            if not path.exists() or not os.access(path, os.R_OK)
        ]
        if missing_inputs:
            missing_input_error = "Inputs ausentes ou sem leitura: " + ", ".join(
                str(path) for path in missing_inputs
            )
            result = _fail_workflow_step(
                state_path=state_path,
                step=step,
                state=normalized_states[step_id],
                inputs=_fingerprints(tracked_paths),
                output_paths_for_log=[
                    resolved_artifact_paths[item.key] for item in step.outputs
                ],
                log_path=step_log,
                started=datetime.now(UTC),
                elapsed=0.0,
                commands=(),
                error=missing_input_error,
                input_paths=input_paths,
                output_paths=[
                    resolved_artifact_paths[item.key] for item in step.outputs
                ],
            )
            states[step_id] = WorkflowStepStatus.FAILED
            record_result(result)
            continue

        input_fingerprints = _fingerprints(tracked_paths)
        output_paths = [resolved_artifact_paths[item.key] for item in step.outputs]
        output_fingerprints = _fingerprints(output_paths)
        if _can_skip_workflow_step(
            step=step,
            state_path=state_path,
            state=normalized_states[step_id],
            inputs=input_fingerprints,
            outputs=output_fingerprints,
        ):
            _write_workflow_log(
                step_log,
                step,
                status=WorkflowStepStatus.SKIPPED,
                started=None,
                elapsed=0.0,
                commands=(),
                error=None,
                input_paths=input_paths,
                output_paths=output_paths,
            )
            _write_workflow_state(
                state_path,
                step,
                status=WorkflowStepStatus.SKIPPED,
                state=normalized_states[step_id],
                inputs=input_fingerprints,
                outputs=output_fingerprints,
                log_path=step_log,
                elapsed=0.0,
                started=None,
            )
            states[step_id] = WorkflowStepStatus.SKIPPED
            record_result(
                WorkflowStepResult(
                    step_id=step_id,
                    status=WorkflowStepStatus.SKIPPED,
                    log_path=step_log,
                )
            )
            continue

        started = datetime.now(UTC)
        start_time = perf_counter()
        context = _WorkflowRunContext(
            project_root=root,
            step=step,
            artifact_paths=resolved_artifact_paths,
        )
        previous_outputs = {
            path: (
                _fingerprint(path),
                path.stat().st_mtime_ns if path.exists() else None,
            )
            for path in output_paths
        }
        step_error: str | None = None
        status = WorkflowStepStatus.SUCCEEDED
        try:
            for output_path in output_paths:
                output_path.parent.mkdir(parents=True, exist_ok=True)
            step.run(context)
            missing_outputs = [path for path in output_paths if not path.exists()]
            if missing_outputs:
                raise FileNotFoundError(
                    "Outputs declarados não foram produzidos: "
                    + ", ".join(str(path) for path in missing_outputs)
                )
            unchanged_outputs = [
                path
                for path in output_paths
                if previous_outputs[path]
                == (
                    _fingerprint(path),
                    path.stat().st_mtime_ns,
                )
            ]
            if unchanged_outputs:
                raise RuntimeError(
                    "Outputs declarados não foram atualizados: "
                    + ", ".join(str(path) for path in unchanged_outputs)
                )
        except Exception as exception:
            status = WorkflowStepStatus.FAILED
            step_error = f"{type(exception).__name__}: {exception}"
        elapsed = perf_counter() - start_time
        output_fingerprints = _fingerprints(output_paths)
        _write_workflow_log(
            step_log,
            step,
            status=status,
            started=started,
            elapsed=elapsed,
            commands=context.commands,
            error=step_error,
            input_paths=input_paths,
            output_paths=output_paths,
        )
        _write_workflow_state(
            state_path,
            step,
            status=status,
            state=normalized_states[step_id],
            inputs=input_fingerprints,
            outputs=output_fingerprints,
            log_path=step_log,
            elapsed=elapsed,
            started=started,
        )
        states[step_id] = status
        record_result(
            WorkflowStepResult(
                step_id=step_id,
                status=status,
                log_path=step_log,
                elapsed_seconds=elapsed,
                commands=tuple(context.commands),
                error=step_error,
            )
        )

    report = WorkflowExecutionReport(
        results=tuple(results),
        dependencies=graph.dependencies,
        artifact_paths=MappingProxyType(resolved_artifact_paths),
    )
    if any(result.status is WorkflowStepStatus.FAILED for result in results):
        raise WorkflowExecutionError(report)
    return report


class _WorkflowRunContext:
    def __init__(
        self,
        *,
        project_root: Path,
        step: Step,
        artifact_paths: Mapping[str, Path],
    ) -> None:
        self.project_root = project_root
        self._step = step
        self._artifact_paths = artifact_paths
        self.commands: list[CommandResult] = []

    def input_path(self, artifact: Artifact) -> Path:
        if artifact not in self._step.inputs:
            raise ValueError(
                f"Step {self._step.id!r} não declarou input {artifact.key!r}"
            )
        return self._artifact_paths[artifact.key]

    def output_path(self, artifact: Artifact) -> Path:
        if artifact not in self._step.outputs:
            raise ValueError(
                f"Step {self._step.id!r} não declarou output {artifact.key!r}"
            )
        return self._artifact_paths[artifact.key]

    def run_command(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | None = None,
    ) -> CommandResult:
        if isinstance(argv, (str, bytes)) or not argv:
            raise ValueError("run_command exige uma sequência argv não vazia")
        command = tuple(argv)
        if any(not isinstance(argument, str) for argument in command):
            raise TypeError("Todos os argumentos de run_command devem ser strings")
        working_directory = cwd or self.project_root
        if not working_directory.is_absolute():
            working_directory = self.project_root / working_directory
        command_env = {**os.environ, **(env or {})}
        started = perf_counter()
        try:
            completed = subprocess.run(
                command,
                cwd=working_directory,
                env=command_env,
                input=stdin,
                text=True,
                capture_output=True,
                check=False,
            )
        except OSError as error:
            result = CommandResult(
                argv=command,
                returncode=-1,
                stdout="",
                stderr=str(error),
                elapsed_seconds=perf_counter() - started,
            )
            self.commands.append(result)
            raise CommandExecutionError(result) from error
        result = CommandResult(
            argv=command,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            elapsed_seconds=perf_counter() - started,
        )
        self.commands.append(result)
        if result.returncode:
            raise CommandExecutionError(result)
        return result


def _resolve_artifact_paths(
    graph: WorkflowGraph,
    project_root: Path,
    artifact_paths: Mapping[str, Path],
) -> dict[str, Path]:
    expected = set(graph.artifacts)
    provided = set(artifact_paths)
    missing = sorted(expected - provided)
    extra = sorted(provided - expected)
    if missing or extra:
        details = []
        if missing:
            details.append("sem caminho: " + ", ".join(missing))
        if extra:
            details.append("não declarados: " + ", ".join(extra))
        raise ValueError("Mapa de artefatos inválido (" + "; ".join(details) + ")")

    resolved: dict[str, Path] = {}
    owners: dict[Path, str] = {}
    for key, path in artifact_paths.items():
        resolved_path = path.expanduser()
        if not resolved_path.is_absolute():
            resolved_path = project_root / resolved_path
        resolved_path = resolved_path.resolve()
        previous_key = owners.get(resolved_path)
        if previous_key is not None:
            raise ValueError(
                f"Artefatos {previous_key!r} e {key!r} apontam para o mesmo caminho: "
                f"{resolved_path}"
            )
        owners[resolved_path] = key
        resolved[key] = resolved_path
    return resolved


def _safe_step_id(step_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", step_id).strip("._") or "step"


def _normalized_step_state(step: Step) -> dict[str, object]:
    state_data = dict(step.state)
    if any(not isinstance(key, str) for key in state_data):
        raise ValueError(f"Step {step.id!r}: as chaves de state devem ser strings")
    try:
        encoded = json.dumps(
            state_data,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
        normalized = json.loads(encoded)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"Step {step.id!r}: state deve conter apenas valores serializáveis em JSON"
        ) from error
    if not isinstance(normalized, dict):
        raise ValueError(f"Step {step.id!r}: state deve ser um objeto JSON")
    return normalized


def _can_skip_workflow_step(
    *,
    step: Step,
    state_path: Path,
    state: dict[str, object],
    inputs: dict[str, dict[str, object]],
    outputs: dict[str, dict[str, object]],
) -> bool:
    if not outputs or not all(item.get("exists") is True for item in outputs.values()):
        return False
    entry = _load_state(state_path).get("steps", {})
    if not isinstance(entry, dict):
        return False
    previous = entry.get(step.id)
    if not isinstance(previous, dict):
        return False
    return (
        previous.get("workflow_step") is True
        and previous.get("status") in {"success", "skipped"}
        and previous.get("step_version") == step.version
        and previous.get("state") == state
        and previous.get("inputs") == inputs
        and previous.get("outputs") == outputs
    )


def _write_workflow_state(
    state_path: Path,
    step: Step,
    *,
    status: WorkflowStepStatus,
    state: dict[str, object],
    inputs: dict[str, dict[str, object]],
    outputs: dict[str, dict[str, object]],
    log_path: Path,
    elapsed: float,
    started: datetime | None,
) -> None:
    document = _load_state(state_path)
    entries = document.get("steps")
    if not isinstance(entries, dict):
        entries = {}
        document["steps"] = entries
    finished = datetime.now(UTC)
    entries[step.id] = {
        "workflow_step": True,
        "step_version": step.version,
        "status": status.value,
        "state": state,
        "started_at": started.isoformat() if started else None,
        "finished_at": finished.isoformat(),
        "elapsed_seconds": round(elapsed, 3),
        "log_path": str(log_path),
        "inputs": inputs,
        "outputs": outputs,
    }
    document["version"] = STATE_VERSION
    document["updated_at"] = finished.isoformat()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_workflow_log(
    log_path: Path,
    step: Step,
    *,
    status: WorkflowStepStatus,
    started: datetime | None,
    elapsed: float,
    commands: Sequence[CommandResult],
    error: str | None,
    input_paths: Sequence[Path] = (),
    output_paths: Sequence[Path] = (),
) -> None:
    finished = datetime.now(UTC)
    lines = [
        f"step_id: {step.id}",
        f"step: {step.name}",
        f"step_version: {step.version}",
        f"status: {status.value}",
        f"started_at: {started.isoformat() if started else '-'}",
        f"finished_at: {finished.isoformat()}",
        f"elapsed_seconds: {elapsed:.3f}",
        "",
        "inputs:",
        *[f"- {path}" for path in input_paths],
        "",
        "outputs:",
        *[f"- {path}" for path in output_paths],
        "",
        "commands:",
    ]
    for index, command in enumerate(commands, start=1):
        lines.extend(
            [
                f"- argv: {format_command(list(command.argv))}",
                f"  returncode: {command.returncode}",
                f"  elapsed_seconds: {command.elapsed_seconds:.3f}",
                "  stdout:",
                *[f"    {line}" for line in command.stdout.rstrip().splitlines()],
                "  stderr:",
                *[f"    {line}" for line in command.stderr.rstrip().splitlines()],
            ]
        )
    if not commands:
        lines.append("- none")
    if error:
        lines.extend(["", "error:", error])
    lines.append("")
    log_path.write_text("\n".join(lines), encoding="utf-8")


def _fail_workflow_step(
    *,
    state_path: Path,
    step: Step,
    state: dict[str, object],
    inputs: dict[str, dict[str, object]],
    output_paths: Sequence[Path],
    log_path: Path,
    started: datetime,
    elapsed: float,
    commands: Sequence[CommandResult],
    error: str,
    input_paths: Sequence[Path] = (),
    output_paths_for_log: Sequence[Path] = (),
) -> WorkflowStepResult:
    outputs = _fingerprints(list(output_paths))
    _write_workflow_log(
        log_path,
        step,
        status=WorkflowStepStatus.FAILED,
        started=started,
        elapsed=elapsed,
        commands=commands,
        error=error,
        input_paths=input_paths,
        output_paths=output_paths_for_log,
    )
    _write_workflow_state(
        state_path,
        step,
        status=WorkflowStepStatus.FAILED,
        state=state,
        inputs=inputs,
        outputs=outputs,
        log_path=log_path,
        elapsed=elapsed,
        started=started,
    )
    return WorkflowStepResult(
        step_id=step.id,
        status=WorkflowStepStatus.FAILED,
        log_path=log_path,
        elapsed_seconds=elapsed,
        commands=tuple(commands),
        error=error,
    )


def run_workspace_setup(
    config: GmxFlowConfig,
    project_root: Path,
) -> None:
    logs_dir = project_root / "work" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "00_workspace.log"
    command = ["<internal>", "ensure-workspace"]

    started = datetime.now(UTC)
    start_time = perf_counter()
    setup = ensure_workspace(config=config, project_root=project_root)
    elapsed = perf_counter() - start_time
    finished = datetime.now(UTC)

    content = [
        "step: workspace",
        "description: Preparar diretórios de trabalho e arquivos .mdp ausentes.",
        f"workdir: {setup.work_root}",
        f"command: {format_command(command)}",
        f"started_at: {started.isoformat()}",
        f"finished_at: {finished.isoformat()}",
        f"elapsed_seconds: {elapsed:.3f}",
        "returncode: 0",
        "",
        "directories:",
        *[f"- {path}" for path in setup.directories],
        "",
        "rendered_templates:",
        *[
            f"- {item.template_name} -> {item.output_path}"
            for item in setup.rendered_templates
        ],
        "",
        "existing_templates:",
        *[f"- {path}" for path in setup.existing_templates],
        "",
    ]
    log_path.write_text("\n".join(content), encoding="utf-8")


def runtime_command(command: list[str]) -> list[str]:
    """Resolve package-local commands the same way for every executor."""
    if command[:1] == ["gmxflow"]:
        return [
            sys.executable,
            "-c",
            "from gmxflow.cli import app; app()",
            *command[1:],
        ]
    if command[:1] == ["python"]:
        return [sys.executable, *command[1:]]
    return command


def _unique_paths(paths: Sequence[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def _load_state(state_path: Path) -> dict[str, object]:
    if not state_path.is_file():
        return {"version": STATE_VERSION, "steps": {}}
    try:
        loaded = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": STATE_VERSION, "steps": {}}
    if not isinstance(loaded, dict):
        return {"version": STATE_VERSION, "steps": {}}
    if not isinstance(loaded.get("steps"), dict):
        loaded["steps"] = {}
    return loaded


def _fingerprints(paths: list[Path]) -> dict[str, dict[str, object]]:
    return {str(path): _fingerprint(path) for path in paths}


def _fingerprint(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"exists": False}
    stat = path.stat()
    fingerprint: dict[str, object] = {
        "exists": True,
        "is_file": path.is_file(),
        "size": stat.st_size,
    }
    if path.is_file() and stat.st_size <= HASH_SIZE_LIMIT:
        fingerprint["sha256"] = _sha256(path)
    else:
        fingerprint["mtime_ns"] = stat.st_mtime_ns
    return fingerprint


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
