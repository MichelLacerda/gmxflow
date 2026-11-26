from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from gmxflow.api import GmxFlowProject
from gmxflow.executor import WorkflowStepStatus


@pytest.mark.gromacs
def test_smoke_project_runs_and_resumes_in_an_isolated_copy(
    tmp_path: Path,
) -> None:
    if shutil.which("gmx") is None:
        pytest.skip("GROMACS executable 'gmx' is not available on PATH")

    example = (
        Path(__file__).resolve().parents[2]
        / "examples"
        / "smoke_peptide_complex"
    )
    source_snapshot = {
        path.relative_to(example): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in example.rglob("*")
        if path.is_file()
    }
    project_dir = tmp_path / "smoke_peptide_complex"
    shutil.copytree(
        example,
        project_dir,
        ignore=shutil.ignore_patterns("work", "outputs"),
    )
    project = GmxFlowProject.open(project_dir / "project.toml")

    steps = project.steps()
    workflow = steps["prepare"]
    for step in tuple(steps.values())[1:]:
        workflow = workflow | step
    first_run = project.run_workflow(workflow)
    second_run = project.run_workflow(workflow)

    assert first_run.results
    assert first_run.succeeded
    assert all(result.log_path.is_file() for result in first_run.results)
    assert all(
        result.status is WorkflowStepStatus.SUCCEEDED for result in first_run.results
    )
    assert all(
        result.status is WorkflowStepStatus.SKIPPED for result in second_run.results
    )
    assert all(
        (project_dir / "work" / "analysis" / filename).is_file()
        for filename in (
            "em_potential.xvg",
            "nvt_temperature.xvg",
            "npt_pressure.xvg",
            "npt_density.xvg",
        )
    )
    assert source_snapshot == {
        path.relative_to(example): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in example.rglob("*")
        if path.is_file()
    }
