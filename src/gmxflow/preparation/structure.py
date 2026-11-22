from __future__ import annotations

from importlib import import_module
from pathlib import Path
from types import ModuleType


def require_mdanalysis() -> ModuleType:
    """Raise a user-facing error when structural filtering lacks MDAnalysis."""
    try:
        return import_module("MDAnalysis")
    except ImportError as error:
        raise RuntimeError(
            "A remoção de resíduos requer MDAnalysis. Instale `mdanalysis` "
            "no ambiente Conda/Micromamba do kernel ou `gmxflow[notebook]` "
            "no ambiente Python ativo."
        ) from error


def remove_residues(
    input_path: Path,
    output_path: Path,
    residue_names: tuple[str, ...],
) -> int:
    """Write a PDB without selected residue names and return removed atom count."""
    mda = require_mdanalysis()

    names = tuple(name.strip().upper() for name in residue_names if name.strip())
    if not names:
        raise ValueError("Informe pelo menos um nome de resíduo para remover.")

    universe = mda.Universe(str(input_path))
    selection = universe.select_atoms(f"not resname {' '.join(names)}")
    if selection.n_atoms == 0:
        raise ValueError(
            f"A seleção removeu todos os átomos do arquivo: {input_path}"
        )

    removed_atoms = universe.atoms.n_atoms - selection.n_atoms
    output_path.parent.mkdir(parents=True, exist_ok=True)
    selection.write(str(output_path))
    return removed_atoms
