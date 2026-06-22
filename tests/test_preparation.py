from pathlib import Path

import pytest
from typer.testing import CliRunner

from gmxflow.config import default_config, to_toml
from gmxflow.preparation import prepare_complex
from gmxflow.preparation.disulfide import detect_disulfides
from gmxflow.preparation.protonation import histidine_form_for_ph


def test_histidine_form_for_ph() -> None:
    assert histidine_form_for_ph(5.5) == "HIP"
    assert histidine_form_for_ph(7.4) == "HID"
    assert histidine_form_for_ph(8.2) == "HIE"


def test_histidine_form_uses_charmm_names() -> None:
    assert histidine_form_for_ph(5.5, force_field_name="charmm36-feb2026_cgenff-5.0") == "HSP"
    assert histidine_form_for_ph(7.4, force_field_name="charmm36-feb2026_cgenff-5.0") == "HSD"
    assert histidine_form_for_ph(8.2, force_field_name="charmm36-feb2026_cgenff-5.0") == "HSE"


def test_detect_disulfides_by_sg_distance() -> None:
    records = [
        _atom(1, "SG", "CYS", "A", 1, 0.0, 0.0, 0.0, "S"),
        _atom(2, "SG", "CYS", "A", 2, 2.0, 0.0, 0.0, "S"),
        _atom(3, "SG", "CYS", "A", 3, 8.0, 0.0, 0.0, "S"),
    ]

    assert detect_disulfides(records, cutoff_angstrom=2.5) == {1, 2}


def test_prepare_complex_writes_outputs_and_preserves_ligand_pose(tmp_path: Path) -> None:
    receptor = tmp_path / "receptor.pdb"
    ligand = tmp_path / "ligand.pdb"
    output_dir = tmp_path / "prep"

    receptor.write_text(
        "\n".join(
            [
                _atom(1, "N", "HIS", "A", 1, 1.0, 2.0, 3.0, "N"),
                _atom(2, "SG", "CYS", "A", 2, 0.0, 0.0, 0.0, "S"),
                _atom(3, "HG", "CYS", "A", 2, 0.1, 0.0, 0.0, "H"),
                _atom(4, "SG", "CYS", "A", 3, 2.0, 0.0, 0.0, "S"),
                "END",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    ligand.write_text(
        "\n".join(
            [
                _atom(1, "N", "ALA", "B", 1, 9.0, 8.0, 7.0, "N"),
                _atom(2, "CA", "ALA", "B", 1, 9.5, 8.5, 7.5, "C"),
                "END",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = prepare_complex(receptor, ligand, output_dir, ph=7.4)

    assert result.complex_pdb == output_dir / "complexo.pdb"
    assert result.receptor_atoms == 3
    assert result.ligand_atoms == 2
    assert result.disulfide_residues == [2, 3]
    assert result.histidine_form == "HID"

    complex_text = result.complex_pdb.read_text(encoding="utf-8")
    assert "HID A   1" in complex_text
    assert "CYX A   2" in complex_text
    assert "CYS A   2" not in complex_text
    assert "ALA B   4" in complex_text
    assert "   9.000   8.000   7.000" in complex_text


def test_prepare_complex_uses_charmm_histidine_names(tmp_path: Path) -> None:
    receptor = tmp_path / "receptor.pdb"
    ligand = tmp_path / "ligand.pdb"
    output_dir = tmp_path / "prep"
    receptor.write_text(_atom(1, "N", "HIS", "A", 1, 0, 0, 0, "N") + "\n", encoding="utf-8")
    ligand.write_text(_atom(1, "N", "ALA", "B", 1, 1, 1, 1, "N") + "\n", encoding="utf-8")

    result = prepare_complex(
        receptor,
        ligand,
        output_dir,
        ph=7.4,
        force_field_name="charmm36-feb2026_cgenff-5.0",
    )

    assert result.histidine_form == "HSD"
    assert "HSD A   1" in result.receptor_pdb.read_text(encoding="utf-8")


def test_prepare_complex_refuses_overwrite_without_force(tmp_path: Path) -> None:
    receptor = tmp_path / "receptor.pdb"
    ligand = tmp_path / "ligand.pdb"
    output_dir = tmp_path / "prep"
    receptor.write_text(_atom(1, "N", "ALA", "A", 1, 0, 0, 0, "N") + "\n", encoding="utf-8")
    ligand.write_text(_atom(1, "N", "ALA", "B", 1, 1, 1, 1, "N") + "\n", encoding="utf-8")

    prepare_complex(receptor, ligand, output_dir, ph=7.4)

    with pytest.raises(FileExistsError):
        prepare_complex(receptor, ligand, output_dir, ph=7.4)


def test_prepare_complex_cli(tmp_path: Path) -> None:
    runner = CliRunner()
    project = tmp_path / "project"
    inputs = project / "inputs"
    inputs.mkdir(parents=True)
    (project / "config.toml").write_text(to_toml(default_config("cli_prepare")), encoding="utf-8")
    (inputs / "receptor.pdb").write_text(
        _atom(1, "N", "HIS", "A", 1, 0, 0, 0, "N") + "\n",
        encoding="utf-8",
    )
    (inputs / "ligante.pdb").write_text(
        _atom(1, "N", "ALA", "B", 1, 1, 1, 1, "N") + "\n",
        encoding="utf-8",
    )

    from gmxflow.cli import app

    result = runner.invoke(app, ["prepare-complex", "--config", str(project / "config.toml")])

    assert result.exit_code == 0
    assert "Complexo preparado:" in result.output
    assert (project / "work" / "prep" / "complexo.pdb").is_file()


def _atom(
    serial: int,
    atom: str,
    residue: str,
    chain: str,
    resid: int,
    x: float,
    y: float,
    z: float,
    element: str,
) -> str:
    return (
        f"ATOM  {serial:5d} {atom:<4} {residue:<3} {chain}{resid:4d}"
        f"    {x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00           {element:>2}"
    )
