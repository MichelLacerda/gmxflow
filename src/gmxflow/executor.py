from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Callable

from pydantic import BaseModel

from gmxflow.config import GmxFlowConfig
from gmxflow.pipeline import PipelineStep
from gmxflow.runner import format_command
from gmxflow.workspace import ensure_workspace

STATE_VERSION = 1
HASH_SIZE_LIMIT = 64 * 1024 * 1024


class StepResult(BaseModel):
    step_name: str
    command: list[str]
    workdir: Path
    log_path: Path
    returncode: int
    elapsed_seconds: float
    skipped: bool = False

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0


def run_steps(
    steps: list[PipelineStep],
    project_root: Path,
    start_index: int = 1,
    on_step_start: Callable[[int, PipelineStep], None] | None = None,
    on_step_done: Callable[[int, StepResult], None] | None = None,
    global_inputs: list[Path] | None = None,
) -> list[StepResult]:
    logs_dir = project_root / "work" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    state_path = project_root / "work" / "state.json"
    produced_paths = {path for step in steps for path in step.outputs}

    results: list[StepResult] = []
    force_remaining = False
    for index, step in enumerate(steps, start=start_index):
        if on_step_start is not None:
            on_step_start(index, step)
        result = run_step(
            step,
            logs_dir=logs_dir,
            index=index,
            state_path=state_path,
            produced_paths=produced_paths,
            global_inputs=global_inputs or [],
            force=force_remaining,
        )
        if not result.skipped:
            force_remaining = True
        results.append(result)
        if on_step_done is not None:
            on_step_done(index, result)
        if not result.succeeded:
            raise RuntimeError(
                f"Etapa '{step.name}' falhou com codigo {result.returncode}. Log: {result.log_path}"
            )
    return results


def run_workspace_setup(
    config: GmxFlowConfig,
    project_root: Path,
    index: int = 0,
) -> StepResult:
    logs_dir = project_root / "work" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"{index:02d}_workspace.log"
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
    _write_state_entry(
        state_path=project_root / "work" / "state.json",
        step=PipelineStep(
            name="workspace",
            description="Preparar diretórios de trabalho e arquivos .mdp ausentes.",
            workdir=setup.work_root,
            command=command,
            outputs=[
                *[item.output_path for item in setup.rendered_templates],
                *setup.existing_templates,
            ],
        ),
        command=command,
        started=started,
        finished=finished,
        elapsed=elapsed,
        returncode=0,
        log_path=log_path,
        skipped=False,
    )

    return StepResult(
        step_name="workspace",
        command=command,
        workdir=setup.work_root,
        log_path=log_path,
        returncode=0,
        elapsed_seconds=elapsed,
    )


def run_step(
    step: PipelineStep,
    logs_dir: Path,
    index: int,
    state_path: Path | None = None,
    produced_paths: set[Path] | None = None,
    global_inputs: list[Path] | None = None,
    force: bool = False,
) -> StepResult:
    step.workdir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"{index:02d}_{step.name}.log"
    command = _runtime_command(step.command)
    state_path = state_path or logs_dir.parent / "state.json"
    produced_paths = produced_paths or set()
    global_inputs = global_inputs or []

    if not force and _can_skip_step(
        step=step,
        command=command,
        state_path=state_path,
        produced_paths=produced_paths,
        global_inputs=global_inputs,
    ):
        result = _skip_step(step=step, command=command, log_path=log_path)
        _write_state_entry(
            state_path=state_path,
            step=step,
            command=command,
            started=datetime.now(UTC),
            finished=datetime.now(UTC),
            elapsed=0.0,
            returncode=0,
            log_path=log_path,
            skipped=True,
            tracked_inputs=_tracked_inputs(step, produced_paths, global_inputs),
        )
        return result

    started = datetime.now(UTC)
    start_time = perf_counter()
    completed = subprocess.run(
        command,
        cwd=step.workdir,
        env=_step_env(step),
        input=step.stdin,
        text=True,
        capture_output=True,
        check=False,
    )
    elapsed = perf_counter() - start_time
    finished = datetime.now(UTC)

    _write_log(
        log_path=log_path,
        step=step,
        command=command,
        started=started,
        finished=finished,
        elapsed=elapsed,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        skipped=False,
    )
    _write_state_entry(
        state_path=state_path,
        step=step,
        command=command,
        started=started,
        finished=finished,
        elapsed=elapsed,
        returncode=completed.returncode,
        log_path=log_path,
        skipped=False,
        tracked_inputs=_tracked_inputs(step, produced_paths, global_inputs),
    )

    return StepResult(
        step_name=step.name,
        command=command,
        workdir=step.workdir,
        log_path=log_path,
        returncode=completed.returncode,
        elapsed_seconds=elapsed,
    )


def _outputs_complete(step: PipelineStep) -> bool:
    return bool(step.outputs) and all(path.exists() for path in step.outputs)


def _can_skip_step(
    step: PipelineStep,
    command: list[str],
    state_path: Path,
    produced_paths: set[Path],
    global_inputs: list[Path],
) -> bool:
    if not _outputs_complete(step):
        return False
    entry = _load_state(state_path).get("steps", {}).get(step.name)  # pyright: ignore[reportAttributeAccessIssue]
    if not isinstance(entry, dict):
        return False
    if entry.get("status") not in {"success", "skipped"}:
        return False
    return (
        entry.get("command") == command
        and entry.get("stdin") == step.stdin
        and entry.get("env") == step.env
        and entry.get("state") == step.state
        and entry.get("inputs")
        == _fingerprints(_tracked_inputs(step, produced_paths, global_inputs))
    )


def _tracked_inputs(
    step: PipelineStep,
    produced_paths: set[Path],
    global_inputs: list[Path],
) -> list[Path]:
    return _unique_paths([*_external_inputs(step, produced_paths), *global_inputs])


def _external_inputs(step: PipelineStep, produced_paths: set[Path]) -> list[Path]:
    return [path for path in step.inputs if path not in produced_paths]


def _unique_paths(paths: list[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def _skip_step(step: PipelineStep, command: list[str], log_path: Path) -> StepResult:
    started = datetime.now(UTC)
    finished = datetime.now(UTC)
    _write_log(
        log_path=log_path,
        step=step,
        command=command,
        started=started,
        finished=finished,
        elapsed=0.0,
        returncode=0,
        stdout=(
            "Etapa ignorada: estado persistente confirma que entradas, comando "
            "e saídas continuam válidos."
        ),
        stderr="",
        skipped=True,
    )
    return StepResult(
        step_name=step.name,
        command=command,
        workdir=step.workdir,
        log_path=log_path,
        returncode=0,
        elapsed_seconds=0.0,
        skipped=True,
    )


def select_steps(
    steps: list[PipelineStep],
    from_step: str | None = None,
    until: str | None = None,
) -> list[PipelineStep]:
    names = [step.name for step in steps]
    start = _step_index(names, from_step) if from_step else 0
    end = _step_index(names, until) + 1 if until else len(steps)
    if start >= end:
        raise ValueError(
            "--from-step deve apontar para uma etapa anterior ou igual a --until"
        )
    return steps[start:end]


def _step_index(names: list[str], name: str | None) -> int:
    if name is None:
        return 0
    try:
        return names.index(name)
    except ValueError as error:
        valid = ", ".join(names)
        raise ValueError(
            f"Etapa desconhecida: {name}. Etapas validas: {valid}"
        ) from error


def _runtime_command(command: list[str]) -> list[str]:
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


def _write_log(
    log_path: Path,
    step: PipelineStep,
    command: list[str],
    started: datetime,
    finished: datetime,
    elapsed: float,
    returncode: int,
    stdout: str,
    stderr: str,
    skipped: bool = False,
) -> None:
    content = [
        f"step: {step.name}",
        f"description: {step.description}",
        f"workdir: {step.workdir}",
        f"command: {format_command(command)}",
        f"started_at: {started.isoformat()}",
        f"finished_at: {finished.isoformat()}",
        f"elapsed_seconds: {elapsed:.3f}",
        f"returncode: {returncode}",
        f"skipped: {str(skipped).lower()}",
        "",
        "inputs:",
        *[f"- {path}" for path in step.inputs],
        "",
        "outputs:",
        *[f"- {path}" for path in step.outputs],
        "",
        "env:",
        *[f"- {key}={value}" for key, value in sorted(step.env.items())],
        "",
        "stdout:",
        stdout.rstrip(),
        "",
        "stderr:",
        stderr.rstrip(),
        "",
    ]
    log_path.write_text("\n".join(content), encoding="utf-8")


def _step_env(step: PipelineStep) -> dict[str, str] | None:
    if not step.env:
        return None
    return {**os.environ, **step.env}


def _write_state_entry(
    state_path: Path,
    step: PipelineStep,
    command: list[str],
    started: datetime,
    finished: datetime,
    elapsed: float,
    returncode: int,
    log_path: Path,
    skipped: bool,
    tracked_inputs: list[Path] | None = None,
) -> None:
    state = _load_state(state_path)
    state["version"] = STATE_VERSION
    state["updated_at"] = finished.isoformat()
    steps = state.setdefault("steps", {})
    steps[step.name] = {  # pyright: ignore[reportIndexIssue]
        "status": _step_status(returncode=returncode, skipped=skipped),
        "skipped": skipped,
        "description": step.description,
        "workdir": str(step.workdir),
        "command": command,
        "stdin": step.stdin,
        "env": step.env,
        "state": step.state,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "elapsed_seconds": round(elapsed, 3),
        "returncode": returncode,
        "log_path": str(log_path),
        "inputs": _fingerprints(
            tracked_inputs if tracked_inputs is not None else step.inputs
        ),
        "outputs": _fingerprints(step.outputs),
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _step_status(returncode: int, skipped: bool) -> str:
    if skipped:
        return "skipped"
    if returncode == 0:
        return "success"
    return "failed"


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
