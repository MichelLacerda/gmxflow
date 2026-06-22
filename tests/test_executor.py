import json
from pathlib import Path

from gmxflow.config import default_config
from gmxflow.executor import run_step, run_steps, run_workspace_setup
from gmxflow.pipeline import PipelineStep


def test_run_step_writes_log_for_successful_command(tmp_path: Path) -> None:
    step = PipelineStep(
        name="fake",
        description="Fake command",
        workdir=tmp_path / "work",
        command=["python", "-c", "print('ok')"],
    )

    result = run_step(step, logs_dir=tmp_path / "logs", index=1)

    assert result.succeeded
    assert result.log_path.is_file()
    log = result.log_path.read_text(encoding="utf-8")
    assert "step: fake" in log
    assert "returncode: 0" in log
    assert "ok" in log
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["steps"]["fake"]["status"] == "success"


def test_run_step_skips_when_outputs_and_state_match(tmp_path: Path) -> None:
    output = tmp_path / "work" / "done.txt"
    step = PipelineStep(
        name="done",
        description="Already done",
        workdir=tmp_path / "work",
        command=["python", "-c", "from pathlib import Path; Path('done.txt').write_text('done')"],
        outputs=[output],
    )

    first = run_step(step, logs_dir=tmp_path / "logs", index=1)
    second = run_step(step, logs_dir=tmp_path / "logs", index=2)

    assert first.succeeded
    assert not first.skipped
    assert second.succeeded
    assert second.skipped
    log = second.log_path.read_text(encoding="utf-8")
    assert "skipped: true" in log
    assert "estado persistente confirma" in log


def test_run_step_does_not_skip_when_input_changes(tmp_path: Path) -> None:
    input_path = tmp_path / "input.txt"
    output = tmp_path / "work" / "done.txt"
    input_path.write_text("first", encoding="utf-8")
    step = PipelineStep(
        name="stale",
        description="Stale input",
        workdir=tmp_path / "work",
        command=[
            "python",
            "-c",
            "from pathlib import Path; Path('done.txt').write_text(Path('../input.txt').read_text())",
        ],
        inputs=[input_path],
        outputs=[output],
    )

    first = run_step(step, logs_dir=tmp_path / "logs", index=1)
    input_path.write_text("second", encoding="utf-8")
    second = run_step(step, logs_dir=tmp_path / "logs", index=2)

    assert first.succeeded
    assert not second.skipped
    assert output.read_text(encoding="utf-8") == "second"


def test_run_step_skips_when_input_mtime_changes_without_content_change(tmp_path: Path) -> None:
    input_path = tmp_path / "input.txt"
    output = tmp_path / "work" / "done.txt"
    input_path.write_text("same", encoding="utf-8")
    step = PipelineStep(
        name="stable",
        description="Stable input",
        workdir=tmp_path / "work",
        command=[
            "python",
            "-c",
            "from pathlib import Path; Path('done.txt').write_text(Path('../input.txt').read_text())",
        ],
        inputs=[input_path],
        outputs=[output],
    )

    first = run_step(step, logs_dir=tmp_path / "logs", index=1)
    input_path.touch()
    second = run_step(step, logs_dir=tmp_path / "logs", index=2)

    assert first.succeeded
    assert second.skipped


def test_run_step_skips_when_output_was_mutated_downstream(tmp_path: Path) -> None:
    output = tmp_path / "work" / "shared.txt"
    step = PipelineStep(
        name="shared",
        description="Shared output",
        workdir=tmp_path / "work",
        command=["python", "-c", "from pathlib import Path; Path('shared.txt').write_text('base')"],
        outputs=[output],
    )

    first = run_step(step, logs_dir=tmp_path / "logs", index=1)
    output.write_text("mutated downstream", encoding="utf-8")
    second = run_step(step, logs_dir=tmp_path / "logs", index=2)

    assert first.succeeded
    assert second.skipped


def test_run_steps_skip_ignores_intermediate_inputs_produced_by_selected_steps(
    tmp_path: Path,
) -> None:
    shared = tmp_path / "work" / "shared.txt"
    final = tmp_path / "work" / "final.txt"
    steps = [
        PipelineStep(
            name="producer",
            description="Producer",
            workdir=tmp_path / "work",
            command=["python", "-c", "from pathlib import Path; Path('shared.txt').write_text('base')"],
            outputs=[shared],
        ),
        PipelineStep(
            name="consumer",
            description="Consumer",
            workdir=tmp_path / "work",
            command=["python", "-c", "from pathlib import Path; Path('final.txt').write_text('done')"],
            inputs=[shared],
            outputs=[final],
        ),
    ]

    first = run_steps(steps, project_root=tmp_path)
    shared.write_text("mutated by downstream step", encoding="utf-8")
    second = run_steps(steps, project_root=tmp_path)

    assert [result.skipped for result in first] == [False, False]
    assert [result.skipped for result in second] == [True, True]


def test_run_steps_state_change_invalidates_step_and_downstream(tmp_path: Path) -> None:
    first_output = tmp_path / "work" / "first.txt"
    output = tmp_path / "work" / "done.txt"
    steps = [
        PipelineStep(
            name="config-sensitive",
            description="Config sensitive",
            workdir=tmp_path / "work",
            command=["python", "-c", "from pathlib import Path; Path('first.txt').write_text('done')"],
            outputs=[first_output],
            state={"box.distance_nm": 1.2},
        ),
        PipelineStep(
            name="downstream",
            description="Downstream",
            workdir=tmp_path / "work",
            command=["python", "-c", "from pathlib import Path; Path('done.txt').write_text('done')"],
            inputs=[first_output],
            outputs=[output],
        ),
    ]

    first = run_steps(steps, project_root=tmp_path)
    steps[0].state = {"box.distance_nm": 2.0}
    second = run_steps(steps, project_root=tmp_path)

    assert [result.skipped for result in first] == [False, False]
    assert [result.skipped for result in second] == [False, False]


def test_run_step_writes_log_for_failed_command(tmp_path: Path) -> None:
    step = PipelineStep(
        name="fail",
        description="Fail command",
        workdir=tmp_path / "work",
        command=["python", "-c", "import sys; print('bad'); sys.exit(7)"],
    )

    result = run_step(step, logs_dir=tmp_path / "logs", index=1)

    assert not result.succeeded
    assert result.returncode == 7
    log = result.log_path.read_text(encoding="utf-8")
    assert "returncode: 7" in log
    assert "bad" in log


def test_run_step_passes_step_environment(tmp_path: Path) -> None:
    step = PipelineStep(
        name="env",
        description="Env command",
        workdir=tmp_path / "work",
        command=["python", "-c", "import os; print(os.environ['GMXLIB'])"],
        env={"GMXLIB": str(tmp_path / "ff")},
    )

    result = run_step(step, logs_dir=tmp_path / "logs", index=1)

    assert result.succeeded
    log = result.log_path.read_text(encoding="utf-8")
    assert f"GMXLIB={tmp_path / 'ff'}" in log


def test_run_workspace_setup_writes_log_and_mdp_files(tmp_path: Path) -> None:
    result = run_workspace_setup(default_config("workspace_log_test"), project_root=tmp_path)

    assert result.succeeded
    assert result.step_name == "workspace"
    assert result.log_path == tmp_path / "work" / "logs" / "00_workspace.log"
    assert (tmp_path / "work" / "prod" / "md.mdp").is_file()

    log = result.log_path.read_text(encoding="utf-8")
    assert "step: workspace" in log
    assert "rendered_templates:" in log
    assert "md.mdp.j2" in log
