from pathlib import Path

from gmxflow.config import default_config
from gmxflow.small_molecule import assemble_small_molecule_complex


def test_assemble_small_molecule_complex_writes_gro_and_updates_topology(
    tmp_path: Path,
) -> None:
    topo = tmp_path / "work" / "topo"
    ligand = tmp_path / "work" / "ligand"
    topo.mkdir(parents=True)
    ligand.mkdir(parents=True)
    (topo / "protein.gro").write_text(
        "Protein\n"
        "    2\n"
        "    1ALA      N    1   0.000   0.100   0.200\n"
        "    1ALA     CA    2   0.300   0.400   0.500\n"
        "   1.00000   1.00000   1.00000\n",
        encoding="utf-8",
    )
    (topo / "topol.top").write_text(
        '#include "charmm36.ff/forcefield.itp"\n'
        '#include "topol_Protein_chain_A.itp"\n'
        "\n"
        "[ system ]\n"
        "Protein\n"
        "\n"
        "[ molecules ]\n"
        "Protein_chain_A     1\n",
        encoding="utf-8",
    )
    (ligand / "jz4.itp").write_text("itp", encoding="utf-8")
    (ligand / "jz4.prm").write_text("prm", encoding="utf-8")
    (ligand / "jz4_ini.pdb").write_text(
        "HETATM    1  C1  JZ4 B   1      10.000  20.000  30.000  1.00  0.00           C\n"
        "HETATM    2  N1  JZ4 B   1      11.000  21.000  31.000  1.00  0.00           N\n",
        encoding="utf-8",
    )
    config = default_config("small_molecule_assembly_test")
    config.input.ligand_resname = "JZ4"

    result = assemble_small_molecule_complex(config, project_root=tmp_path)

    assert result.protein_atoms == 2
    assert result.ligand_atoms == 2
    assert result.marker.is_file()
    complex_lines = result.complex_gro.read_text(encoding="utf-8").splitlines()
    assert complex_lines[1].strip() == "4"
    assert "    2JZ4     C1    3   1.000   2.000   3.000" in complex_lines
    assert "    2JZ4     N1    4   1.100   2.100   3.100" in complex_lines
    topol = result.topology.read_text(encoding="utf-8")
    assert '#include "../ligand/jz4.prm"' in topol
    assert '#include "../ligand/jz4.itp"' in topol
    assert "JZ4                  1" in topol


def test_assemble_small_molecule_complex_resets_transient_molecules_section(
    tmp_path: Path,
) -> None:
    topo = tmp_path / "work" / "topo"
    ligand = tmp_path / "work" / "ligand"
    topo.mkdir(parents=True)
    ligand.mkdir(parents=True)
    (topo / "protein.gro").write_text(
        "Protein\n"
        "    1\n"
        "    1ALA      N    1   0.000   0.100   0.200\n"
        "   1.00000   1.00000   1.00000\n",
        encoding="utf-8",
    )
    (topo / "topol.top").write_text(
        '#include "charmm36.ff/forcefield.itp"\n'
        '#include "topol_Protein_chain_A.itp"\n'
        "\n"
        "[ system ]\n"
        "Protein\n"
        "\n"
        "[ molecules ]\n"
        "Protein_chain_A     1\n"
        "JZ4                 1\n"
        "SOL              8762\n"
        "NA                 28\n"
        "CL                 34\n",
        encoding="utf-8",
    )
    (ligand / "jz4.itp").write_text("itp", encoding="utf-8")
    (ligand / "jz4.prm").write_text("prm", encoding="utf-8")
    (ligand / "jz4_ini.pdb").write_text(
        "HETATM    1  C1  JZ4 B   1      10.000  20.000  30.000  1.00  0.00           C\n",
        encoding="utf-8",
    )
    config = default_config("small_molecule_reset_test")
    config.input.ligand_resname = "JZ4"

    result = assemble_small_molecule_complex(config, project_root=tmp_path)

    topol = result.topology.read_text(encoding="utf-8")
    assert "Protein_chain_A     1" in topol
    assert "JZ4                  1" in topol
    assert "SOL" not in topol
    assert "NA" not in topol
    assert "CL" not in topol
