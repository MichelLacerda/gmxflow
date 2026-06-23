from __future__ import annotations

import os
import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel, Field

from gmxflow.config import GmxFlowConfig
from gmxflow.runner import format_command


class LigandPreparationResult(BaseModel):
    resname: str
    command: list[str]
    workdir: Path
    stdout: str
    stderr: str
    returncode: int
    warnings: list[str] = Field(default_factory=list)
    itp_path: Path
    prm_path: Path
    top_path: Path
    pdb_path: Path


def prepare_ligand(
    config: GmxFlowConfig,
    project_root: Path,
    force_field_dir: Path | None = None,
) -> LigandPreparationResult:
    project_root = project_root.expanduser().resolve()
    workdir = project_root / "work" / "ligand"
    workdir.mkdir(parents=True, exist_ok=True)

    mol2_path = _required_project_file(
        config.input.ligand_mol2,
        project_root,
        "input.ligand_mol2",
    )
    str_path = _required_project_file(
        config.input.ligand_str,
        project_root,
        "input.ligand_str",
    )
    ff_dir = _resolve_force_field_dir(
        configured=config.force_field.name,
        project_root=project_root,
        explicit=force_field_dir,
    )
    resname = config.input.ligand_resname.strip()
    if not resname:
        raise ValueError("input.ligand_resname deve ser informado para ligante pequeno.")
    validation_warnings = _validate_ligand_inputs(
        mol2_path=mol2_path,
        str_path=str_path,
        expected_resname=resname,
    )

    script = resources.files("gmxflow.vendor.cgenff_charmm2gmx").joinpath(
        "cgenff_charmm2gmx.py"
    )
    command = [
        sys.executable,
        str(script),
        resname,
        str(mol2_path),
        str(str_path),
        str(ff_dir),
    ]
    completed = subprocess.run(
        command,
        cwd=workdir,
        text=True,
        capture_output=True,
        check=False,
    )

    prefix = resname.lower()
    result = LigandPreparationResult(
        resname=resname,
        command=command,
        workdir=workdir,
        stdout=completed.stdout,
        stderr=completed.stderr,
        returncode=completed.returncode,
        warnings=validation_warnings,
        itp_path=workdir / f"{prefix}.itp",
        prm_path=workdir / f"{prefix}.prm",
        top_path=workdir / f"{prefix}.top",
        pdb_path=workdir / f"{prefix}_ini.pdb",
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Preparação do ligante falhou com codigo {completed.returncode}: "
            f"{format_command(command)}\n{completed.stderr.strip()}"
        )
    _require_outputs(result)
    _validate_generated_ligand_pdb(
        pdb_path=result.pdb_path,
        expected_atoms=len(_mol2_atom_names(mol2_path)),
    )
    _normalize_ligand_itp(result.itp_path, resname=resname)
    return result


def _required_project_file(value: str, project_root: Path, field_name: str) -> Path:
    if not value.strip():
        raise ValueError(f"{field_name} deve ser informado para ligante pequeno.")
    path = _resolve_project_path(value, project_root)
    if not path.is_file():
        raise FileNotFoundError(f"Arquivo não encontrado em {field_name}: {path}")
    return path


def _resolve_project_path(value: str, project_root: Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return project_root / path


def _resolve_force_field_dir(
    configured: str,
    project_root: Path,
    explicit: Path | None,
) -> Path:
    if explicit is not None:
        path = explicit.expanduser().resolve()
        if not path.is_dir():
            raise FileNotFoundError(f"Diretório de force field não encontrado: {path}")
        return path

    for candidate in _force_field_candidates(configured, project_root):
        if candidate.is_dir():
            return candidate.resolve()

    searched = "\n".join(f"- {path}" for path in _force_field_candidates(configured, project_root))
    raise FileNotFoundError(
        "Diretório de force field CHARMM não encontrado. Informe --force-field-dir.\n"
        f"Buscado em:\n{searched}"
    )


def _force_field_candidates(configured: str, project_root: Path) -> list[Path]:
    names = [configured]
    if configured and not configured.endswith(".ff"):
        names.append(f"{configured}.ff")

    roots = [
        project_root,
        project_root / "inputs",
        project_root / "work",
        Path(sys.prefix) / "share" / "gromacs" / "top",
    ]
    if gmxlib := os.environ.get("GMXLIB"):
        roots.insert(0, Path(gmxlib))
    if conda_prefix := os.environ.get("CONDA_PREFIX"):
        roots.insert(0, Path(conda_prefix) / "share" / "gromacs" / "top")
    roots.extend(_gromacs_roots_from_path())

    candidates: list[Path] = []
    for name in names:
        path = Path(name).expanduser()
        if path.is_absolute():
            candidates.append(path)
        candidates.extend(root / name for root in roots)
    return _unique_paths(candidates)


def _gromacs_roots_from_path() -> list[Path]:
    roots: list[Path] = []
    for command in ("gmx", "gmx_mpi"):
        executable = shutil.which(command)
        if executable is None:
            continue
        path = Path(executable).resolve()
        if path.parent.name.startswith("bin"):
            roots.append(path.parent.parent / "share" / "gromacs" / "top")
        else:
            roots.append(path.parent / "share" / "gromacs" / "top")
    return roots


def _unique_paths(paths: Iterable[Path]) -> list[Path]:
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        key = str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _require_outputs(result: LigandPreparationResult) -> None:
    missing = [
        path
        for path in (result.itp_path, result.prm_path, result.top_path, result.pdb_path)
        if not path.is_file()
    ]
    if missing:
        missing_text = "\n".join(f"- {path}" for path in missing)
        raise RuntimeError(
            "Conversor CGenFF finalizou, mas outputs esperados não foram encontrados:\n"
            f"{missing_text}"
        )


def _normalize_ligand_itp(path: Path, resname: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    normalized: list[str] = []
    section = ""
    replace_next_moleculetype = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped.lower()
            replace_next_moleculetype = section == "[ moleculetype ]"
            normalized.append(line)
            continue
        if replace_next_moleculetype and stripped and not stripped.startswith(";"):
            normalized.append(_replace_first_field(line, resname))
            replace_next_moleculetype = False
            continue
        if section == "[ atoms ]" and stripped and not stripped.startswith(";"):
            normalized.append(_replace_field(line, index=3, value=resname))
            continue
        normalized.append(line)
    path.write_text("\n".join(normalized).rstrip() + "\n", encoding="utf-8")


def _replace_first_field(line: str, value: str) -> str:
    return _replace_field(line, index=0, value=value)


def _replace_field(line: str, index: int, value: str) -> str:
    body, separator, comment = line.partition(";")
    fields = body.split()
    if len(fields) <= index:
        return line
    fields[index] = value
    rewritten = " ".join(fields)
    if separator:
        return f"{rewritten} {separator}{comment}"
    return rewritten


def _validate_ligand_inputs(
    mol2_path: Path,
    str_path: Path,
    expected_resname: str,
) -> list[str]:
    _validate_stream_resname(str_path, expected_resname=expected_resname)
    mol2_atoms = _mol2_atom_names(mol2_path)
    stream_atoms = _stream_atom_names(str_path)
    if not mol2_atoms:
        raise ValueError(f"Não foi possível detectar átomos no arquivo .mol2: {mol2_path}")
    if not stream_atoms:
        raise ValueError(f"Não foi possível detectar átomos ATOM no arquivo .str: {str_path}")
    warnings = _stream_penalty_warnings(str_path)
    if mol2_atoms != stream_atoms:
        if _atom_names_compatible(mol2_atoms, stream_atoms):
            warnings.append(
                "Nomes de hidrogênios diferem entre .mol2 e .str, mas a ordem "
                "e os átomos pesados são compatíveis. Isso é comum quando Open Babel "
                "gera hidrogênios genéricos como H e CGenFF renomeia para H1, H2, ..."
            )
            return warnings
        raise ValueError(
            "A lista de átomos do .mol2 não corresponde ao arquivo .str.\n"
            f"mol2 ({len(mol2_atoms)}): {', '.join(mol2_atoms)}\n"
            f"str ({len(stream_atoms)}): {', '.join(stream_atoms)}"
        )
    return warnings


def _validate_stream_resname(str_path: Path, expected_resname: str) -> None:
    actual_resname = _stream_resname(str_path)
    if actual_resname is None:
        raise ValueError(f"Não foi possível detectar RESI no arquivo .str: {str_path}")
    if actual_resname != expected_resname:
        raise ValueError(
            "input.ligand_resname não corresponde ao RESI do arquivo .str.\n"
            f"config.toml: {expected_resname}\n"
            f"ligand.str: {actual_resname}"
        )


def _stream_resname(str_path: Path) -> str | None:
    for line in str_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("RESI "):
            parts = stripped.split()
            if len(parts) >= 2:
                return parts[1]
    return None


def _mol2_atom_names(mol2_path: Path) -> list[str]:
    atoms: list[str] = []
    in_atoms = False
    for line in mol2_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped == "@<TRIPOS>ATOM":
            in_atoms = True
            continue
        if stripped.startswith("@<TRIPOS>") and in_atoms:
            break
        if not in_atoms or not stripped:
            continue
        parts = stripped.split()
        if len(parts) >= 2:
            atoms.append(parts[1])
    return atoms


def _stream_atom_names(str_path: Path) -> list[str]:
    atoms: list[str] = []
    in_residue = False
    for line in str_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("RESI "):
            in_residue = True
            continue
        if in_residue and stripped.startswith(("BOND", "DOUBLE", "IMPR", "END")):
            break
        if in_residue and stripped.startswith("ATOM "):
            parts = stripped.split()
            if len(parts) >= 2:
                atoms.append(parts[1])
    return atoms


def _atom_names_compatible(mol2_atoms: list[str], stream_atoms: list[str]) -> bool:
    if len(mol2_atoms) != len(stream_atoms):
        return False
    for mol2_atom, stream_atom in zip(mol2_atoms, stream_atoms, strict=True):
        if mol2_atom == stream_atom:
            continue
        if _atom_name_element(mol2_atom) != "H" or _atom_name_element(stream_atom) != "H":
            return False
    return True


def _atom_name_element(name: str) -> str:
    for char in name.strip():
        if char.isalpha():
            return char.upper()
    return ""


def _validate_generated_ligand_pdb(pdb_path: Path, expected_atoms: int) -> None:
    actual_atoms = sum(
        1
        for line in pdb_path.read_text(encoding="utf-8").splitlines()
        if line.startswith(("ATOM", "HETATM"))
    )
    if actual_atoms != expected_atoms:
        raise RuntimeError(
            "PDB gerado pelo conversor não corresponde ao .mol2 de entrada.\n"
            f"mol2: {expected_atoms} átomos\n"
            f"pdb: {actual_atoms} átomos\n"
            f"arquivo: {pdb_path}"
        )


def _stream_penalty_warnings(str_path: Path) -> list[str]:
    warnings: list[str] = []
    penalties: list[float] = []
    for line in str_path.read_text(encoding="utf-8").splitlines():
        lowered = line.lower()
        if "penalty" not in lowered:
            continue
        for raw in lowered.replace("=", " ").replace(":", " ").split():
            try:
                penalties.append(float(raw))
            except ValueError:
                continue
    high = [penalty for penalty in penalties if penalty >= 50]
    if high:
        warnings.append(
            "Penalties CGenFF altos detectados no .str "
            f"(máximo {max(high):.3f}). Revise a parametrização antes de interpretar resultados."
        )
    return warnings
