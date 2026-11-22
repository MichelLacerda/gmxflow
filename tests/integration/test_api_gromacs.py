from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from gmxflow.api import GmxFlowProject


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

    first_run = project.run()
    second_run = project.run()

    assert first_run.results
    assert all(result.succeeded for result in first_run.results)
    assert all(result.log_path.is_file() for result in first_run.results)
    assert all(not result.skipped for result in first_run.steps)
    assert all(result.skipped for result in second_run.steps)
    assert all(
        "skipped: true" in result.log_path.read_text(encoding="utf-8")
        for result in second_run.steps
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
