from __future__ import annotations

import math

from gmxflow.preparation.pdb import atom_name, coordinates, residue_name, residue_number


def detect_disulfides(records: list[str], cutoff_angstrom: float = 2.5) -> set[int]:
    sulfur_atoms: list[tuple[int, float, float, float]] = []
    for record in records:
        if atom_name(record) == "SG" and residue_name(record) in {"CYS", "CYX"}:
            x, y, z = coordinates(record)
            sulfur_atoms.append((residue_number(record), x, y, z))

    bonded: set[int] = set()
    for index, first in enumerate(sulfur_atoms):
        res1, x1, y1, z1 = first
        for res2, x2, y2, z2 in sulfur_atoms[index + 1 :]:
            distance = math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2 + (z1 - z2) ** 2)
            if distance < cutoff_angstrom:
                bonded.add(res1)
                bonded.add(res2)
    return bonded
