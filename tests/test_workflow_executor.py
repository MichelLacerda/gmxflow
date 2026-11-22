from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from gmxflow.executor import (
    WorkflowExecutionError,
    WorkflowStepStatus,
    run_workflow_graph,
)
from gmxflow.pipeline import Artifact, Parallel, RunContext, Sequence, WorkflowGraph


@dataclass
class _Step:
    id: str
    name: str
    action: Callable[[RunContext], None]
    inputs: tuple[Artifact, ...] = ()
    outputs: tuple[Artifact, ...] = ()
    parallel: bool = True
    version: str = "1"
    state: dict[str, object] = field(default_factory=dict)

    def run(self, context: RunContext) -> None:
        self.action(context)


def _artifact_paths(root: Path, *items: tuple[str, str]) -> dict[str, Path]:
    return {key: root / relative_path for key, relative_path in items}


def test_run_workflow_graph_executes_in_dependency_order_and_logs_commands(
    tmp_path: Path,
) -> None:
    source = Artifact("source", "txt")
    prepared = Artifact("prepared", "txt")
    analyzed = Artifact("analyzed", "txt")
    source_path = tmp_path / "inputs" / "source.txt"
    source_path.parent.mkdir()
    source_path.write_text("initial\n", encoding="utf-8")
    executed: list[str] = []

    def prepare(context: RunContext) -> None:
        executed.append("prepare")
        text = context.input_path(source).read_text(encoding="utf-8")
        context.output_path(prepared).write_text(text.upper(), encoding="utf-8")

    def analyze(context: RunContext) -> None:
        executed.append("analyze")
        command = context.run_command(
            [sys.executable, "-c", "print('analysis complete')"]
        )
        assert command.returncode == 0
        context.output_path(analyzed).write_text(
            context.input_path(prepared).read_text(encoding="utf-8") + "DONE\n",
            encoding="utf-8",
        )

    graph = WorkflowGraph.from_workflow(
        Sequence(
            _Step("prepare", "Prepare", prepare, (source,), (prepared,)),
            _Step("analyze", "Analyze", analyze, (prepared,), (analyzed,)),
        ),
        project_inputs=(source,),
    )

    report = run_workflow_graph(
        graph,
        project_root=tmp_path,
        artifact_paths=_artifact_paths(
            tmp_path,
            ("source", "inputs/source.txt"),
            ("prepared", "work/prepared.txt"),
            ("analyzed", "outputs/analyzed.txt"),
        ),
    )

    assert executed == ["prepare", "analyze"]
    assert [result.status for result in report.results] == [
        WorkflowStepStatus.SUCCEEDED,
        WorkflowStepStatus.SUCCEEDED,
    ]
    assert (tmp_path / "outputs/analyzed.txt").read_text(encoding="utf-8") == (
        "INITIAL\nDONE\n"
    )
    analysis_log = report.results[1].log_path.read_text(encoding="utf-8")
    assert "analysis complete" in analysis_log
    assert "argv:" in analysis_log


def test_run_workflow_graph_resumes_when_state_inputs_and_outputs_match(
    tmp_path: Path,
) -> None:
    output = Artifact("output", "txt")
    calls: list[str] = []

    def write_output(context: RunContext) -> None:
        calls.append("run")
        context.output_path(output).write_text("cached\n", encoding="utf-8")

    graph = WorkflowGraph.from_workflow(
        _Step("cache-step", "Cache step", write_output, outputs=(output,))
    )
    paths = _artifact_paths(tmp_path, ("output", "work/cache.txt"))

    first = run_workflow_graph(graph, project_root=tmp_path, artifact_paths=paths)
    second = run_workflow_graph(graph, project_root=tmp_path, artifact_paths=paths)

    assert first.results[0].status is WorkflowStepStatus.SUCCEEDED
    assert second.results[0].status is WorkflowStepStatus.SKIPPED
    assert calls == ["run"]
    state = json.loads((tmp_path / "work/state.json").read_text(encoding="utf-8"))
    assert state["steps"]["cache-step"]["step_version"] == "1"


def test_run_workflow_graph_can_use_an_isolated_state_file(
    tmp_path: Path,
) -> None:
    output = Artifact("output", "txt")
    calls: list[str] = []

    def write_output(context: RunContext) -> None:
        calls.append("run")
        context.output_path(output).write_text("cached\n", encoding="utf-8")

    graph = WorkflowGraph.from_workflow(
        _Step("isolated-cache", "Isolated cache", write_output, outputs=(output,))
    )
    workflow_state = tmp_path / "work" / "workflow_state.json"
    paths = _artifact_paths(tmp_path, ("output", "work/cache.txt"))

    first = run_workflow_graph(
        graph,
        project_root=tmp_path,
        artifact_paths=paths,
        state_path=workflow_state,
    )
    second = run_workflow_graph(
        graph,
        project_root=tmp_path,
        artifact_paths=paths,
        state_path=workflow_state,
    )

    assert first.results[0].status is WorkflowStepStatus.SUCCEEDED
    assert second.results[0].status is WorkflowStepStatus.SKIPPED
    assert workflow_state.is_file()
    assert not (tmp_path / "work" / "state.json").exists()
    assert calls == ["run"]


def test_run_workflow_graph_invalidates_resume_when_state_or_version_changes(
    tmp_path: Path,
) -> None:
    output = Artifact("output", "txt")
    calls: list[str] = []

    def write_versioned(context: RunContext) -> None:
        calls.append("run")
        context.output_path(output).write_text("result", encoding="utf-8")

    step = _Step(
        "versioned",
        "Versioned",
        write_versioned,
        outputs=(output,),
        state={"parameter": 1},
    )
    graph = WorkflowGraph.from_workflow(step)
    paths = _artifact_paths(tmp_path, ("output", "work/result.txt"))

    run_workflow_graph(graph, project_root=tmp_path, artifact_paths=paths)
    step.state["parameter"] = 2
    run_workflow_graph(graph, project_root=tmp_path, artifact_paths=paths)
    step.version = "2"
    run_workflow_graph(graph, project_root=tmp_path, artifact_paths=paths)

    assert calls == ["run", "run", "run"]


def test_run_workflow_graph_invalidates_resume_when_input_changes(
    tmp_path: Path,
) -> None:
    source = Artifact("source", "txt")
    output = Artifact("output", "txt")
    source_path = tmp_path / "inputs/source.txt"
    source_path.parent.mkdir()
    source_path.write_text("first", encoding="utf-8")
    calls: list[str] = []

    def copy_input(context: RunContext) -> None:
        calls.append("run")
        context.output_path(output).write_text(
            context.input_path(source).read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    graph = WorkflowGraph.from_workflow(
        _Step("copy", "Copy", copy_input, (source,), (output,)),
        project_inputs=(source,),
    )
    paths = _artifact_paths(
        tmp_path,
        ("source", "inputs/source.txt"),
        ("output", "work/copy.txt"),
    )

    run_workflow_graph(graph, project_root=tmp_path, artifact_paths=paths)
    source_path.write_text("second", encoding="utf-8")
    report = run_workflow_graph(graph, project_root=tmp_path, artifact_paths=paths)

    assert report.results[0].status is WorkflowStepStatus.SUCCEEDED
    assert calls == ["run", "run"]
    assert (tmp_path / "work/copy.txt").read_text(encoding="utf-8") == "second"


def test_run_workflow_graph_blocks_dependents_but_runs_independent_branch(
    tmp_path: Path,
) -> None:
    failed_output = Artifact("failed-output", "txt")
    independent_output = Artifact("independent-output", "txt")
    final_output = Artifact("final-output", "txt")
    calls: list[str] = []

    def fail(_: RunContext) -> None:
        calls.append("fail")
        raise RuntimeError("expected test failure")

    def independent(context: RunContext) -> None:
        calls.append("independent")
        context.output_path(independent_output).write_text("ok", encoding="utf-8")

    def final(context: RunContext) -> None:
        calls.append("final")
        context.output_path(final_output).write_text("unexpected", encoding="utf-8")

    graph = WorkflowGraph.from_workflow(
        Sequence(
            Parallel(
                _Step("fail", "Fail", fail, outputs=(failed_output,)),
                _Step(
                    "independent",
                    "Independent",
                    independent,
                    outputs=(independent_output,),
                ),
            ),
            _Step(
                "final",
                "Final",
                final,
                inputs=(failed_output, independent_output),
                outputs=(final_output,),
                parallel=False,
            ),
        )
    )
    paths = _artifact_paths(
        tmp_path,
        ("failed-output", "work/failed.txt"),
        ("independent-output", "work/independent.txt"),
        ("final-output", "outputs/final.txt"),
    )

    with pytest.raises(WorkflowExecutionError) as raised:
        run_workflow_graph(graph, project_root=tmp_path, artifact_paths=paths)

    results = {result.step_id: result for result in raised.value.report.results}
    assert calls == ["fail", "independent"]
    assert results["fail"].status is WorkflowStepStatus.FAILED
    assert results["independent"].status is WorkflowStepStatus.SUCCEEDED
    assert results["final"].status is WorkflowStepStatus.BLOCKED
    assert not (tmp_path / "outputs/final.txt").exists()


def test_run_workflow_graph_dry_run_does_not_call_steps_or_create_work(
    tmp_path: Path,
) -> None:
    output = Artifact("output", "txt")
    calls: list[str] = []
    graph = WorkflowGraph.from_workflow(
        _Step(
            "dry-step",
            "Dry step",
            lambda _: calls.append("run"),
            outputs=(output,),
        )
    )

    report = run_workflow_graph(
        graph,
        project_root=tmp_path,
        artifact_paths=_artifact_paths(tmp_path, ("output", "work/dry.txt")),
        dry_run=True,
    )

    assert report.dry_run
    assert report.results[0].status is WorkflowStepStatus.PLANNED
    assert calls == []
    assert not (tmp_path / "work").exists()


def test_run_workflow_graph_preflights_missing_project_inputs(
    tmp_path: Path,
) -> None:
    source = Artifact("source", "txt")
    output = Artifact("output", "txt")
    calls: list[str] = []
    graph = WorkflowGraph.from_workflow(
        _Step(
            "requires-input",
            "Requires input",
            lambda _: calls.append("run"),
            inputs=(source,),
            outputs=(output,),
        ),
        project_inputs=(source,),
    )

    with pytest.raises(FileNotFoundError, match="Inputs do projeto"):
        run_workflow_graph(
            graph,
            project_root=tmp_path,
            artifact_paths={
                "source": Path("inputs/missing.txt"),
                "output": Path("work/out.txt"),
            },
        )

    assert calls == []
    assert not (tmp_path / "work").exists()


def test_run_workflow_graph_rejects_artifact_path_collisions(tmp_path: Path) -> None:
    first = Artifact("first", "txt")
    second = Artifact("second", "txt")
    graph = WorkflowGraph.from_workflow(
        _Step("step", "Step", lambda _: None, outputs=(first, second))
    )

    with pytest.raises(ValueError, match="mesmo caminho"):
        run_workflow_graph(
            graph,
            project_root=tmp_path,
            artifact_paths={"first": Path("work/out.txt"), "second": Path("work/out.txt")},
            dry_run=True,
        )


def test_run_workflow_graph_rejects_non_json_state(tmp_path: Path) -> None:
    output = Artifact("output", "txt")
    graph = WorkflowGraph.from_workflow(
        _Step("step", "Step", lambda _: None, outputs=(output,), state={"bad": object()})
    )

    with pytest.raises(ValueError, match="serializáveis em JSON"):
        run_workflow_graph(
            graph,
            project_root=tmp_path,
            artifact_paths={"output": Path("work/out.txt")},
            dry_run=True,
        )


def test_run_workflow_graph_records_failed_command_output(tmp_path: Path) -> None:
    graph = WorkflowGraph.from_workflow(
        _Step(
            "command-fails",
            "Command fails",
            lambda context: context.run_command(
                [
                    sys.executable,
                    "-c",
                    "import sys; print('stdout detail'); "
                    "print('stderr detail', file=sys.stderr); sys.exit(7)",
                ]
            ),
        )
    )

    with pytest.raises(WorkflowExecutionError) as raised:
        run_workflow_graph(graph, project_root=tmp_path, artifact_paths={})

    result = raised.value.report.results[0]
    assert result.status is WorkflowStepStatus.FAILED
    assert result.commands[0].returncode == 7
    log = result.log_path.read_text(encoding="utf-8")
    assert "stdout detail" in log
    assert "stderr detail" in log


def test_run_workflow_graph_fails_when_step_omits_declared_output(
    tmp_path: Path,
) -> None:
    output = Artifact("output", "txt")
    graph = WorkflowGraph.from_workflow(
        _Step("missing-output", "Missing output", lambda _: None, outputs=(output,))
    )

    with pytest.raises(WorkflowExecutionError) as raised:
        run_workflow_graph(
            graph,
            project_root=tmp_path,
            artifact_paths={"output": Path("work/expected.txt")},
        )

    assert raised.value.report.results[0].status is WorkflowStepStatus.FAILED
    error = raised.value.report.results[0].error
    assert error is not None
    assert "não foram produzidos" in error


def test_run_workflow_graph_does_not_accept_an_unchanged_stale_output(
    tmp_path: Path,
) -> None:
    output = Artifact("output", "txt")
    output_path = tmp_path / "work/expected.txt"
    output_path.parent.mkdir()
    output_path.write_text("stale", encoding="utf-8")
    graph = WorkflowGraph.from_workflow(
        _Step("no-op", "No-op", lambda _: None, outputs=(output,))
    )

    with pytest.raises(WorkflowExecutionError) as raised:
        run_workflow_graph(
            graph,
            project_root=tmp_path,
            artifact_paths={"output": Path("work/expected.txt")},
        )

    error = raised.value.report.results[0].error
    assert error is not None
    assert "não foram atualizados" in error
