from __future__ import annotations

import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


FORCEFIELD_ENV = "GMXFLOW_FORCEFIELD_DIR"


@dataclass(frozen=True)
class ForceFieldLocation:
    name: str
    path: Path
    source: str
    gmxlib: Path | None


def user_forcefield_root() -> Path:
    """Return the persistent per-user directory for externally managed force fields."""
    if override := os.environ.get(FORCEFIELD_ENV):
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return (base / "gmxflow" / "forcefields").expanduser().resolve()


def forcefield_names(name: str) -> tuple[str, ...]:
    value = name.strip()
    if not value:
        return ()
    if value.endswith(".ff"):
        return (value,)
    return (value, f"{value}.ff")


def validate_forcefield_directory(path: Path) -> Path:
    directory = path.expanduser().resolve()
    if not directory.is_dir():
        raise FileNotFoundError(f"Diretório de force field não encontrado: {directory}")
    missing = [
        filename
        for filename in ("forcefield.itp", "forcefield.doc")
        if not (directory / filename).is_file()
    ]
    if missing:
        raise ValueError(
            f"Diretório incompleto: {directory} não contém "
            f"{', '.join(missing)}. "
            "Informe a pasta <nome>.ff extraída, não o arquivo compactado nem sua pasta-pai."
        )
    return directory


def resolve_forcefield(
    name: str,
    project_root: Path,
    explicit: Path | None = None,
) -> ForceFieldLocation | None:
    """Resolve a force field with installed, user, then legacy-project precedence."""
    project_root = project_root.expanduser().resolve()
    if explicit is not None:
        directory = validate_forcefield_directory(explicit)
        return ForceFieldLocation(
            directory.name.removesuffix(".ff"), directory, "explicit", directory.parent
        )

    configured_path = Path(name).expanduser()
    if configured_path.is_absolute():
        for candidate in _named_candidates(configured_path):
            if _is_forcefield(candidate):
                directory = candidate.resolve()
                return ForceFieldLocation(
                    directory.name.removesuffix(".ff"),
                    directory,
                    "explicit",
                    directory.parent,
                )
        return None

    names = forcefield_names(name)
    for root in _installed_roots():
        for candidate_name in names:
            candidate = root / candidate_name
            if _is_forcefield(candidate):
                return ForceFieldLocation(name, candidate.resolve(), "gromacs", None)

    user_root = user_forcefield_root()
    for candidate_name in names:
        candidate = user_root / candidate_name
        if _is_forcefield(candidate):
            directory = candidate.resolve()
            return ForceFieldLocation(name, directory, "user", user_root)

    project_roots = (project_root, project_root / "inputs", project_root / "work")
    for root in project_roots:
        for candidate_name in names:
            candidate = root / candidate_name
            if _is_forcefield(candidate):
                directory = candidate.resolve()
                return ForceFieldLocation(name, directory, "project", root.resolve())
    return None


def forcefield_search_paths(name: str, project_root: Path) -> list[Path]:
    names = forcefield_names(name)
    paths: list[Path] = []
    configured = Path(name).expanduser()
    if configured.is_absolute():
        paths.append(configured)
    paths.extend(root / item for root in _installed_roots() for item in names)
    user_root = user_forcefield_root()
    paths.extend(user_root / item for item in names)
    resolved_project = project_root.expanduser().resolve()
    paths.extend(
        root / item
        for root in (resolved_project, resolved_project / "inputs", resolved_project / "work")
        for item in names
    )
    return _unique_paths(paths)


def install_forcefield(source: Path, name: str | None = None) -> Path:
    source_path = validate_forcefield_directory(source)
    target_name = name or source_path.name
    if not target_name.endswith(".ff"):
        target_name += ".ff"
    if Path(target_name).name != target_name or target_name in {".", ".."}:
        raise ValueError("O nome do force field deve ser um nome de pasta simples.")

    root = user_forcefield_root()
    target = root / target_name
    if source_path == target.resolve():
        return target
    if target.exists() or target.is_symlink():
        raise FileExistsError(
            f"Já existe um force field nesse destino: {target}. "
            "Nada foi sobrescrito; escolha outro nome ou faça backup/migração manual."
        )
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".gmxflow-install-", dir=root) as temp_dir:
        staged = Path(temp_dir) / target_name
        shutil.copytree(source_path, staged)
        staged.rename(target)
    validate_forcefield_directory(target)
    return target


def list_user_forcefields() -> list[ForceFieldLocation]:
    root = user_forcefield_root()
    if not root.is_dir():
        return []
    return [
        ForceFieldLocation(
            name=directory.name.removesuffix(".ff"),
            path=directory.resolve(),
            source="user",
            gmxlib=root,
        )
        for directory in sorted(root.glob("*.ff"))
        if _is_forcefield(directory)
    ]


def _installed_roots() -> list[Path]:
    roots: list[Path] = []
    if gmxlib := os.environ.get("GMXLIB"):
        roots.append(Path(gmxlib).expanduser())
    if conda_prefix := os.environ.get("CONDA_PREFIX"):
        roots.append(Path(conda_prefix) / "share" / "gromacs" / "top")
    roots.append(Path(sys.prefix) / "share" / "gromacs" / "top")
    for command in ("gmx", "gmx_mpi"):
        executable = shutil.which(command)
        if executable is None:
            continue
        binary = Path(executable).resolve()
        roots.append(binary.parent.parent / "share" / "gromacs" / "top")
    return _unique_paths(roots)


def _is_forcefield(path: Path) -> bool:
    return path.is_dir() and all(
        (path / filename).is_file()
        for filename in ("forcefield.itp", "forcefield.doc")
    )


def _named_candidates(path: Path) -> tuple[Path, ...]:
    if path.name.endswith(".ff"):
        return (path,)
    return (path, path.with_name(f"{path.name}.ff"))


def _unique_paths(paths: Iterable[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        normalized = str(path.expanduser().resolve())
        if normalized not in seen:
            seen.add(normalized)
            unique.append(Path(normalized))
    return unique
