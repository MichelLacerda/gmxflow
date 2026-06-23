from pathlib import Path
from types import SimpleNamespace

import pytest

from gmxflow.config import default_config
from gmxflow.ligand import prepare_ligand


def test_prepare_ligand_runs_vendored_converter(tmp_path: Path, monkeypatch) -> None:
    mol2 = tmp_path / "inputs" / "lig.mol2"
    stream = tmp_path / "inputs" / "lig.str"
    force_field = tmp_path / "charmm36.ff"
    mol2.parent.mkdir()
    _write_mol2(mol2)
    _write_stream(stream)
    force_field.mkdir()

    calls: list[dict[str, object]] = []

    def fake_run(command, cwd, text, capture_output, check):
        calls.append(
            {
                "command": command,
                "cwd": cwd,
                "text": text,
                "capture_output": capture_output,
                "check": check,
            }
        )
        cwd.joinpath("jz4.itp").write_text(
            "\n".join(
                [
                    "[ moleculetype ]",
                    "ligand.pdb 3",
                    "",
                    "[ atoms ]",
                    "1 C1 1 ligand.pdb C1 1 -0.1 12.011 ;",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        cwd.joinpath("jz4.prm").write_text("prm", encoding="utf-8")
        cwd.joinpath("jz4.top").write_text("top", encoding="utf-8")
        _write_pdb(cwd.joinpath("jz4_ini.pdb"))
        return SimpleNamespace(stdout="ok", stderr="", returncode=0)

    monkeypatch.setattr("gmxflow.ligand.subprocess.run", fake_run)

    config = default_config("ligand_test")
    config.input.ligand_mol2 = "inputs/lig.mol2"
    config.input.ligand_str = "inputs/lig.str"
    config.input.ligand_resname = "JZ4"

    result = prepare_ligand(config, project_root=tmp_path, force_field_dir=force_field)

    assert result.resname == "JZ4"
    assert result.itp_path == tmp_path / "work" / "ligand" / "jz4.itp"
    assert result.prm_path.is_file()
    assert result.top_path.is_file()
    assert result.pdb_path.is_file()
    assert result.warnings == []
    assert calls[0]["cwd"] == tmp_path / "work" / "ligand"
    command = calls[0]["command"]
    assert command[2:] == [  # pyright: ignore[reportIndexIssue]
        "JZ4",
        str(mol2),
        str(stream),
        str(force_field.resolve()),
    ]
    itp_text = result.itp_path.read_text(encoding="utf-8")
    assert "JZ4 3" in itp_text
    assert "1 C1 1 JZ4 C1 1 -0.1 12.011 ;" in itp_text


def test_prepare_ligand_requires_mol2_path(tmp_path: Path) -> None:
    config = default_config("ligand_missing_test")
    config.input.ligand_str = "inputs/lig.str"

    with pytest.raises(ValueError, match="input.ligand_mol2"):
        prepare_ligand(config, project_root=tmp_path)


def test_prepare_ligand_rejects_stream_resname_mismatch(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    _write_mol2(inputs / "lig.mol2")
    _write_stream(inputs / "lig.str")
    force_field = tmp_path / "charmm36.ff"
    force_field.mkdir()
    config = default_config("ligand_resname_mismatch_test")
    config.input.ligand_mol2 = "inputs/lig.mol2"
    config.input.ligand_str = "inputs/lig.str"
    config.input.ligand_resname = "BEN"

    with pytest.raises(ValueError, match="ligand.str: JZ4"):
        prepare_ligand(config, project_root=tmp_path, force_field_dir=force_field)


def test_prepare_ligand_finds_force_field_from_gmx_path(
    tmp_path: Path, monkeypatch
) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    _write_mol2(inputs / "lig.mol2")
    _write_stream(inputs / "lig.str")
    gmx_root = tmp_path / "gmx-env"
    ff_dir = gmx_root / "share" / "gromacs" / "top" / "charmm36-jul2022.ff"
    ff_dir.mkdir(parents=True)
    calls: list[dict[str, object]] = []

    def fake_run(command, cwd, text, capture_output, check):
        calls.append({"command": command, "cwd": cwd})
        cwd.joinpath("jz4.itp").write_text("itp", encoding="utf-8")
        cwd.joinpath("jz4.prm").write_text("prm", encoding="utf-8")
        cwd.joinpath("jz4.top").write_text("top", encoding="utf-8")
        _write_pdb(cwd.joinpath("jz4_ini.pdb"))
        return SimpleNamespace(stdout="ok", stderr="", returncode=0)

    monkeypatch.setattr("gmxflow.ligand.subprocess.run", fake_run)
    monkeypatch.setattr(
        "gmxflow.ligand.shutil.which",
        lambda name: str(gmx_root / "bin.AVX2_256" / name),
    )

    config = default_config("ligand_ff_lookup_test")
    config.force_field.name = "charmm36-jul2022"
    config.input.ligand_mol2 = "inputs/lig.mol2"
    config.input.ligand_str = "inputs/lig.str"
    config.input.ligand_resname = "JZ4"

    prepare_ligand(config, project_root=tmp_path)

    assert calls[0]["command"][-1] == str(ff_dir)  # pyright: ignore[reportIndexIssue]


def test_prepare_ligand_rejects_atom_mismatch_between_mol2_and_stream(
    tmp_path: Path,
) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    _write_mol2(inputs / "lig.mol2", atoms=("C1", "N1"))
    _write_stream(inputs / "lig.str", atoms=("C1", "O1"))
    force_field = tmp_path / "charmm36.ff"
    force_field.mkdir()
    config = default_config("ligand_atom_mismatch_test")
    config.input.ligand_mol2 = "inputs/lig.mol2"
    config.input.ligand_str = "inputs/lig.str"
    config.input.ligand_resname = "JZ4"

    with pytest.raises(ValueError, match="lista de átomos"):
        prepare_ligand(config, project_root=tmp_path, force_field_dir=force_field)


def test_prepare_ligand_allows_cgenff_hydrogen_renaming(
    tmp_path: Path, monkeypatch
) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    _write_mol2(inputs / "lig.mol2", atoms=("C1", "H", "H"))
    _write_stream(inputs / "lig.str", atoms=("C1", "H1", "H2"))
    force_field = tmp_path / "charmm36.ff"
    force_field.mkdir()

    def fake_run(command, cwd, text, capture_output, check):
        cwd.joinpath("jz4.itp").write_text("itp", encoding="utf-8")
        cwd.joinpath("jz4.prm").write_text("prm", encoding="utf-8")
        cwd.joinpath("jz4.top").write_text("top", encoding="utf-8")
        _write_pdb(cwd.joinpath("jz4_ini.pdb"), atoms=("C1", "H1", "H2"))
        return SimpleNamespace(stdout="ok", stderr="", returncode=0)

    monkeypatch.setattr("gmxflow.ligand.subprocess.run", fake_run)
    config = default_config("ligand_hydrogen_rename_test")
    config.input.ligand_mol2 = "inputs/lig.mol2"
    config.input.ligand_str = "inputs/lig.str"
    config.input.ligand_resname = "JZ4"

    result = prepare_ligand(config, project_root=tmp_path, force_field_dir=force_field)

    assert "Nomes de hidrogênios diferem" in result.warnings[0]


def test_prepare_ligand_warns_for_high_cgenff_penalty(
    tmp_path: Path, monkeypatch
) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    _write_mol2(inputs / "lig.mol2")
    _write_stream(inputs / "lig.str", penalty=60.0)
    force_field = tmp_path / "charmm36.ff"
    force_field.mkdir()

    def fake_run(command, cwd, text, capture_output, check):
        cwd.joinpath("jz4.itp").write_text("itp", encoding="utf-8")
        cwd.joinpath("jz4.prm").write_text("prm", encoding="utf-8")
        cwd.joinpath("jz4.top").write_text("top", encoding="utf-8")
        _write_pdb(cwd.joinpath("jz4_ini.pdb"))
        return SimpleNamespace(stdout="ok", stderr="", returncode=0)

    monkeypatch.setattr("gmxflow.ligand.subprocess.run", fake_run)
    config = default_config("ligand_penalty_test")
    config.input.ligand_mol2 = "inputs/lig.mol2"
    config.input.ligand_str = "inputs/lig.str"
    config.input.ligand_resname = "JZ4"

    result = prepare_ligand(config, project_root=tmp_path, force_field_dir=force_field)

    assert "Penalties CGenFF altos" in result.warnings[0]


def _write_mol2(path: Path, atoms: tuple[str, ...] = ("C1", "N1")) -> None:
    lines = [
        "@<TRIPOS>MOLECULE",
        "JZ4",
        f"{len(atoms)} 0 0 0 0",
        "SMALL",
        "USER_CHARGES",
        "@<TRIPOS>ATOM",
    ]
    for index, atom in enumerate(atoms, start=1):
        element = atom[0]
        lines.append(
            f"{index:7d} {atom:<4} {index:.4f} 0.0000 0.0000 {element}.3 1 JZ4 0.0000"
        )
    lines.append("@<TRIPOS>BOND")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_stream(
    path: Path,
    atoms: tuple[str, ...] = ("C1", "N1"),
    penalty: float | None = None,
) -> None:
    lines = ["RESI JZ4 0.000"]
    for atom in atoms:
        lines.append(f"ATOM {atom} CG2R61 0.000")
    if penalty is not None:
        lines.append(f"! penalty= {penalty:.3f}")
    lines.append("BOND C1 N1")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_pdb(path: Path, atoms: tuple[str, ...] = ("C1", "N1")) -> None:
    lines = []
    for index, atom in enumerate(atoms, start=1):
        lines.append(
            f"HETATM{index:5d} {atom:<4} JZ4 B   1      "
            f"{index:8.3f}{0.0:8.3f}{0.0:8.3f}  1.00  0.00           {atom[0]}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
