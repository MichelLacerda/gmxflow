from __future__ import annotations

from pathlib import Path


def reset_molecules_section(
    topol_top: Path,
    remove_molecules: set[str],
    append_molecules: list[tuple[str, int]] | None = None,
) -> None:
    lines = topol_top.read_text(encoding="utf-8").splitlines()
    lines = reset_molecules_lines(
        lines,
        remove_molecules=remove_molecules,
        append_molecules=append_molecules or [],
    )
    topol_top.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def reset_molecules_lines(
    lines: list[str],
    remove_molecules: set[str],
    append_molecules: list[tuple[str, int]],
) -> list[str]:
    molecule_index = next(
        (index for index, line in enumerate(lines) if line.strip() == "[ molecules ]"),
        None,
    )
    if molecule_index is None:
        appended = [f"{name:<20} {count}" for name, count in append_molecules]
        return [*lines, "", "[ molecules ]", *appended]

    output = lines[: molecule_index + 1]
    section_tail: list[str] = []
    for index, line in enumerate(lines[molecule_index + 1 :], start=molecule_index + 1):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section_tail = lines[index:]
            break
        if not stripped or stripped.startswith(";"):
            output.append(line)
            continue
        molecule_name = stripped.split()[0]
        if molecule_name in remove_molecules:
            continue
        output.append(line)

    output.extend(f"{name:<20} {count}" for name, count in append_molecules)
    if section_tail:
        output.extend(["", *section_tail])
    return output
