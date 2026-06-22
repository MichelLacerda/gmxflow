from __future__ import annotations

from pathlib import Path


def read_atom_records(path: Path) -> list[str]:
    return [
        line.rstrip("\n")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith(("ATOM", "HETATM"))
    ]


def atom_name(record: str) -> str:
    return record[12:16].strip()


def residue_name(record: str) -> str:
    return record[17:20].strip()


def residue_number(record: str) -> int:
    return int(record[22:26])


def coordinates(record: str) -> tuple[float, float, float]:
    return (
        float(record[30:38]),
        float(record[38:46]),
        float(record[46:54]),
    )


def rewrite_atom_record(record: str, serial: int, chain: str, resseq: int) -> str:
    record_type = record[0:6]
    atom = record[12:16]
    alt_loc = record[16:17]
    resname = record[17:20]
    x = record[30:38]
    y = record[38:46]
    z = record[46:54]
    occupancy = record[54:60] if len(record) >= 60 else "  1.00"
    bfactor = record[60:66] if len(record) >= 66 else "  0.00"
    element = record[76:78] if len(record) >= 78 else "  "

    if not occupancy.strip() or occupancy.strip() == "0.00":
        occupancy = "  1.00"
    if not bfactor.strip():
        bfactor = "  0.00"

    return (
        "{:<6s}{:>5d} {:<4s}{:<1s}{:<3s} {:<1s}{:>4d}    "
        "{:>8s}{:>8s}{:>8s}{:>6s}{:>6s}          {:>2s}"
    ).format(
        record_type,
        serial,
        atom,
        alt_loc,
        resname,
        chain,
        resseq,
        x,
        y,
        z,
        occupancy,
        bfactor,
        element,
    )


def with_residue_name(record: str, name: str) -> str:
    return record[:17] + f"{name:<3}"[:3] + record[20:]


def write_pdb(path: Path, records: list[str], remarks: list[str] | None = None) -> None:
    lines = [f"REMARK   {remark}" for remark in remarks or []]
    lines.extend(records)
    lines.extend(["TER", "END"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
