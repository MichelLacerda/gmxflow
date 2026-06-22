from pathlib import Path
from types import SimpleNamespace

from gmxflow.analysis import run_analysis, run_interaction_energy, run_sasa_analysis
from gmxflow.config import default_config


def test_run_analysis_executes_rms_and_rmsf(tmp_path: Path, monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(command, cwd, input, text, capture_output, check):
        calls.append(
            {
                "command": command,
                "cwd": cwd,
                "input": input,
                "text": text,
                "capture_output": capture_output,
                "check": check,
            }
        )
        stdout = "  0 System\n  1 Protein\n" if input == "q\n" else "ok"
        return SimpleNamespace(stdout=stdout, stderr="", returncode=0)

    monkeypatch.setattr("gmxflow.analysis.subprocess.run", fake_run)

    prep = tmp_path / "work" / "prep"
    prep.mkdir(parents=True)
    (prep / "complexo.pdb").write_text(
        _atom(residue=10, chain="A") + "\n" + _atom(residue=11, chain="B") + "\n",
        encoding="utf-8",
    )
    config = default_config("analysis_test")
    results = run_analysis(config, project_root=tmp_path)

    analysis_dir = tmp_path.resolve() / "work" / "analysis"
    assert [result.name for result in results] == [
        "ligand_index",
        "rmsd_backbone",
        "rmsd_ligante",
        "rmsf_residuos",
        "gyrate",
        "mindist",
        "hbond",
    ]
    assert calls[0]["input"] == "q\n"
    assert calls[1]["input"] == "r 11-11\nname 2 Ligante\n1 & ! 2\nname 3 Receptor\nq\n"
    assert calls[2]["cwd"] == analysis_dir
    assert calls[2]["input"] == "Backbone\nBackbone\n"
    assert calls[2]["command"] == [
        "gmx",
        "rms",
        "-s",
        str(tmp_path.resolve() / "work" / "prod" / "md.tpr"),
        "-f",
        str(tmp_path.resolve() / "work" / "prod" / "md_fit.xtc"),
        "-n",
        str(analysis_dir / "lig.ndx"),
        "-o",
        str(analysis_dir / "rmsd_backbone.xvg"),
        "-tu",
        "ns",
    ]
    assert calls[3]["input"] == "Ligante\nLigante\n"
    assert calls[3]["command"][1] == "rms"  # pyright: ignore[reportIndexIssue]
    assert calls[3]["command"][calls[3]["command"].index("-o") + 1] == str(  # pyright: ignore[reportIndexIssue, reportAttributeAccessIssue]
        analysis_dir / "rmsd_ligante.xvg"
    )
    assert calls[4]["cwd"] == analysis_dir
    assert calls[4]["input"] == "Backbone\n"
    assert calls[4]["command"] == [
        "gmx",
        "rmsf",
        "-s",
        str(tmp_path.resolve() / "work" / "prod" / "md.tpr"),
        "-f",
        str(tmp_path.resolve() / "work" / "prod" / "md_fit.xtc"),
        "-n",
        str(analysis_dir / "lig.ndx"),
        "-res",
        "-fit",
        "-o",
        str(analysis_dir / "rmsf_residuos.xvg"),
    ]
    assert calls[5]["input"] == "Protein\n"
    assert calls[5]["command"][1] == "gyrate"  # pyright: ignore[reportIndexIssue]
    assert calls[6]["input"] == "Receptor\nLigante\n"
    assert calls[6]["command"][1] == "mindist"  # pyright: ignore[reportIndexIssue]
    assert calls[7]["input"] == "Receptor\nLigante\n"
    assert calls[7]["command"][1] == "hbond"  # pyright: ignore[reportIndexIssue]


def test_run_analysis_honors_gmx_mpi_engine(tmp_path: Path, monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, cwd, input, text, capture_output, check):
        calls.append(command)
        stdout = "  0 System\n  1 Protein\n" if input == "q\n" else ""
        return SimpleNamespace(stdout=stdout, stderr="", returncode=0)

    monkeypatch.setattr("gmxflow.analysis.subprocess.run", fake_run)

    config = default_config("analysis_mpi_test")
    config.mdrun.engine = "gmx_mpi"
    prep = tmp_path / "work" / "prep"
    prep.mkdir(parents=True)
    (prep / "complexo.pdb").write_text(
        _atom(residue=1, chain="B") + "\n", encoding="utf-8"
    )

    run_analysis(config, project_root=tmp_path)

    assert calls[0][:2] == ["gmx_mpi", "make_ndx"]
    assert calls[2][:2] == ["gmx_mpi", "rms"]
    assert calls[4][:2] == ["gmx_mpi", "rmsf"]


def test_run_analysis_selects_small_molecule_ligand_by_resname(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(command, cwd, input, text, capture_output, check):
        calls.append(
            {
                "command": command,
                "cwd": cwd,
                "input": input,
                "text": text,
                "capture_output": capture_output,
                "check": check,
            }
        )
        stdout = "  0 System\n  1 Protein\n" if input == "q\n" else ""
        return SimpleNamespace(stdout=stdout, stderr="", returncode=0)

    monkeypatch.setattr("gmxflow.analysis.subprocess.run", fake_run)

    config = default_config("analysis_small_molecule_test")
    config.input.ligand_kind = "small_molecule"
    config.input.ligand_resname = "JZ4"

    run_analysis(config, project_root=tmp_path)

    assert calls[1]["input"] == "r JZ4\nname 2 Ligante\n1 & ! 2\nname 3 Receptor\nq\n"


def test_run_analysis_adds_catalytic_triad_when_configured(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(command, cwd, input, text, capture_output, check):
        calls.append(
            {
                "command": command,
                "cwd": cwd,
                "input": input,
                "text": text,
                "capture_output": capture_output,
                "check": check,
            }
        )
        stdout = "  0 System\n  1 Protein\n" if input == "q\n" else "ok"
        return SimpleNamespace(stdout=stdout, stderr="", returncode=0)

    monkeypatch.setattr("gmxflow.analysis.subprocess.run", fake_run)

    prep = tmp_path / "work" / "prep"
    prep.mkdir(parents=True)
    (prep / "complexo.pdb").write_text(
        _atom(residue=11, chain="B") + "\n",
        encoding="utf-8",
    )
    config = default_config("analysis_catalytic_test")
    config.analysis.catalytic_residues = "HIS57, ASP102, SER195"

    results = run_analysis(config, project_root=tmp_path)

    analysis_dir = tmp_path.resolve() / "work" / "analysis"
    assert results[-1].name == "catalytic-triad"
    assert calls[1]["input"] == (
        "r 11-11\n"
        "name 2 Ligante\n"
        "r 57 | r 102 | r 195\n"
        "name 3 TriadeCatalitica\n"
        "1 & ! 2\n"
        "name 4 Receptor\n"
        "q\n"
    )
    assert calls[-1]["command"][1] == "mindist"  # pyright: ignore[reportIndexIssue]
    assert calls[-1]["input"] == "Ligante\nTriadeCatalitica\n"
    assert calls[-1]["command"][calls[-1]["command"].index("-od") + 1] == str(  # pyright: ignore[reportIndexIssue, reportAttributeAccessIssue]
        analysis_dir / "catalytic_distance.xvg"
    )
    assert calls[-1]["command"][calls[-1]["command"].index("-on") + 1] == str(  # pyright: ignore[reportIndexIssue, reportAttributeAccessIssue]
        analysis_dir / "catalytic_occupancy.xvg"
    )


def test_run_interaction_energy_executes_rerun_and_energy(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(command, cwd, input, text, capture_output, check):
        calls.append(
            {
                "command": command,
                "cwd": cwd,
                "input": input,
                "text": text,
                "capture_output": capture_output,
                "check": check,
            }
        )
        if command[1] == "energy" and input == "\n":
            stdout = (
                "  1  Bond\n"
                "  9  Coul-SR:Receptor-Ligante\n"
                " 10  LJ-SR:Receptor-Ligante\n"
            )
        else:
            stdout = "ok"
        return SimpleNamespace(stdout=stdout, stderr="", returncode=0)

    monkeypatch.setattr("gmxflow.analysis.subprocess.run", fake_run)

    results = run_interaction_energy(default_config("interaction_test"), tmp_path)

    analysis_dir = tmp_path.resolve() / "work" / "analysis"
    assert [result.name for result in results] == [
        "interaction-grompp",
        "interaction-rerun",
        "interaction-energy",
    ]
    assert calls[0]["command"][1] == "grompp"  # pyright: ignore[reportIndexIssue]
    assert calls[0]["command"][calls[0]["command"].index("-n") + 1] == str(  # pyright: ignore[reportIndexIssue, reportAttributeAccessIssue]
        analysis_dir / "lig.ndx"
    )
    assert calls[1]["command"][1] == "mdrun"  # pyright: ignore[reportIndexIssue]
    assert "-rerun" in calls[1]["command"]  # pyright: ignore[reportOperatorIssue]
    assert calls[1]["command"][calls[1]["command"].index("-nb") + 1] == "cpu"  # pyright: ignore[reportIndexIssue, reportAttributeAccessIssue]
    assert calls[1]["command"][calls[1]["command"].index("-ntomp") + 1] == "8"  # pyright: ignore[reportIndexIssue, reportAttributeAccessIssue]
    assert calls[3]["input"] == "9\n10\n\n"


def test_run_sasa_analysis_executes_sasa_and_writes_bsa(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(command, cwd, input, text, capture_output, check):
        calls.append(
            {
                "command": command,
                "cwd": cwd,
                "input": input,
                "text": text,
                "capture_output": capture_output,
                "check": check,
            }
        )
        output = Path(command[command.index("-o") + 1])
        if output.name == "sasa_receptor.xvg":
            _write_xvg(output, [10.0, 11.0])
        elif output.name == "sasa_ligante.xvg":
            _write_xvg(output, [3.0, 4.0])
        elif output.name == "sasa_complexo.xvg":
            _write_xvg(output, [11.0, 12.0])
        return SimpleNamespace(stdout="ok", stderr="", returncode=0)

    monkeypatch.setattr("gmxflow.analysis.subprocess.run", fake_run)

    results = run_sasa_analysis(default_config("sasa_test"), tmp_path)

    analysis_dir = tmp_path.resolve() / "work" / "analysis"
    assert [result.name for result in results] == [
        "sasa-receptor",
        "sasa-ligante",
        "sasa-complexo",
        "bsa",
    ]
    assert calls[0]["command"][1] == "sasa"  # pyright: ignore[reportIndexIssue]
    assert calls[0]["command"][calls[0]["command"].index("-surface") + 1] == (  # pyright: ignore[reportIndexIssue, reportAttributeAccessIssue]
        'group "Receptor"'
    )
    assert calls[1]["command"][calls[1]["command"].index("-surface") + 1] == (  # pyright: ignore[reportIndexIssue, reportAttributeAccessIssue]
        'group "Ligante"'
    )
    assert calls[2]["command"][calls[2]["command"].index("-surface") + 1] == (  # pyright: ignore[reportIndexIssue, reportAttributeAccessIssue]
        'group "Receptor" or group "Ligante"'
    )
    bsa = (analysis_dir / "bsa.xvg").read_text(encoding="utf-8")
    assert "0.000000 2.000000" in bsa
    assert "1.000000 3.000000" in bsa


def _atom(residue: int, chain: str) -> str:
    return (
        f"ATOM      1  CA  ALA {chain}{residue:4d}    "
        "   0.000   0.000   0.000  1.00  0.00           C"
    )


def _write_xvg(path: Path, values: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# synthetic XVG", '@ title "test"']
    lines.extend(f"{index:.1f} {value:.3f}" for index, value in enumerate(values))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
