from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from gmxflow.preparation.disulfide import detect_disulfides
from gmxflow.preparation.pdb import (
    atom_name,
    read_atom_records,
    residue_name,
    residue_number,
    rewrite_atom_record,
    with_residue_name,
    write_pdb,
)
from gmxflow.preparation.protonation import histidine_form_for_ph


class PreparedComplex(BaseModel):
    receptor_pdb: Path
    ligand_pdb: Path
    complex_pdb: Path
    receptor_atoms: int
    ligand_atoms: int
    disulfide_residues: list[int]
    histidine_form: str


def prepare_complex(
    receptor_pdb: Path,
    ligand_pdb: Path,
    output_dir: Path,
    ph: float,
    force_field_name: str = "",
    ligand_kind: str = "peptide",
    ligand_resname: str = "",
    disulfide_cutoff_angstrom: float = 2.5,
    force: bool = False,
) -> PreparedComplex:
    receptor_records = read_atom_records(receptor_pdb)
    ligand_records = read_atom_records(ligand_pdb)
    if not receptor_records:
        raise ValueError(f"Receptor sem registros ATOM/HETATM: {receptor_pdb}")
    if not ligand_records:
        raise ValueError(f"Ligante sem registros ATOM/HETATM: {ligand_pdb}")

    output_dir.mkdir(parents=True, exist_ok=True)
    receptor_out_path = output_dir / "receptor_fixed.pdb"
    ligand_out_path = output_dir / "ligante_fixed.pdb"
    complex_out_path = output_dir / "complexo.pdb"
    _check_overwrite([receptor_out_path, ligand_out_path, complex_out_path], force)

    receptor_records = _filter_receptor_records(
        receptor_records,
        ligand_kind=ligand_kind,
        ligand_resname=ligand_resname,
    )
    if not receptor_records:
        raise ValueError(
            f"Receptor sem registros ATOM/HETATM após remover ligante {ligand_resname}: "
            f"{receptor_pdb}"
        )

    disulfides = detect_disulfides(receptor_records, disulfide_cutoff_angstrom)
    histidine_form = histidine_form_for_ph(ph, force_field_name=force_field_name)
    receptor_prepared = _prepare_receptor(receptor_records, disulfides, histidine_form)

    receptor_out, next_serial = _renumber_records(receptor_prepared, chain="A", start_serial=1)
    ligand_offset = residue_number(receptor_prepared[-1]) + 1 - residue_number(ligand_records[0])
    ligand_out, _ = _renumber_records(
        ligand_records,
        chain="B",
        start_serial=next_serial,
        residue_offset=ligand_offset,
    )

    write_pdb(
        receptor_out_path,
        receptor_out,
        [
            f"Receptor preparado para pH {ph}",
            f"{histidine_form} para HIS; CYX em pontes S-S: {sorted(disulfides)}",
        ],
    )
    write_pdb(
        ligand_out_path,
        ligand_out,
        ["Ligante peptídico com pose original preservada"],
    )
    _write_complex(
        complex_out_path,
        receptor_out,
        ligand_out,
        ph=ph,
        receptor_range=(residue_number(receptor_records[0]), residue_number(receptor_records[-1])),
        ligand_range=(
            residue_number(ligand_records[0]) + ligand_offset,
            residue_number(ligand_records[-1]) + ligand_offset,
        ),
    )

    return PreparedComplex(
        receptor_pdb=receptor_out_path,
        ligand_pdb=ligand_out_path,
        complex_pdb=complex_out_path,
        receptor_atoms=len(receptor_out),
        ligand_atoms=len(ligand_out),
        disulfide_residues=sorted(disulfides),
        histidine_form=histidine_form,
    )


def _filter_receptor_records(
    records: list[str],
    ligand_kind: str,
    ligand_resname: str,
) -> list[str]:
    if ligand_kind != "small_molecule" or not ligand_resname.strip():
        return records
    wanted = ligand_resname.strip()
    return [record for record in records if residue_name(record) != wanted]


def _prepare_receptor(records: list[str], disulfides: set[int], histidine_form: str) -> list[str]:
    prepared: list[str] = []
    for record in records:
        resnum = residue_number(record)
        resname = residue_name(record)
        atom = atom_name(record)
        if resnum in disulfides and resname == "CYS" and atom == "HG":
            continue
        if resnum in disulfides and resname == "CYS":
            record = with_residue_name(record, "CYX")
        if resname == "HIS":
            record = with_residue_name(record, histidine_form)
        prepared.append(record)
    return prepared


def _renumber_records(
    records: list[str],
    chain: str,
    start_serial: int,
    residue_offset: int = 0,
) -> tuple[list[str], int]:
    output: list[str] = []
    serial = start_serial
    for record in records:
        output.append(
            rewrite_atom_record(
                record,
                serial=serial,
                chain=chain,
                resseq=residue_number(record) + residue_offset,
            )
        )
        serial += 1
    return output, serial


def _write_complex(
    path: Path,
    receptor_records: list[str],
    ligand_records: list[str],
    ph: float,
    receptor_range: tuple[int, int],
    ligand_range: tuple[int, int],
) -> None:
    lines = [
        f"REMARK   Complexo proteína-peptídeo - pH {ph}",
        f"REMARK   Cadeia A: receptor {receptor_range[0]}-{receptor_range[1]}",
        f"REMARK   Cadeia B: ligante {ligand_range[0]}-{ligand_range[1]}",
        *receptor_records,
        "TER",
        *ligand_records,
        "TER",
        "END",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _check_overwrite(paths: list[Path], force: bool) -> None:
    if force:
        return
    for path in paths:
        if path.exists():
            raise FileExistsError(f"O arquivo já existe: {path}")
