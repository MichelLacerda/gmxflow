from __future__ import annotations

import re
import subprocess
from pathlib import Path

from pydantic import BaseModel

from gmxflow.config import GmxFlowConfig
from gmxflow.runner import format_command


class AnalysisCommandResult(BaseModel):
    name: str
    command: list[str]
    stdout: str
    stderr: str
    returncode: int
    output_path: Path


def run_analysis(
    config: GmxFlowConfig, project_root: Path
) -> list[AnalysisCommandResult]:
    project_root = project_root.expanduser().resolve()
    work_dir = project_root / "work"
    prod = work_dir / "prod"
    prep = work_dir / "prep"
    analysis = work_dir / "analysis"
    analysis.mkdir(parents=True, exist_ok=True)

    gmx = _gmx_command(config)
    index_path = analysis / "lig.ndx"
    catalytic_selection = _catalytic_residue_selection(config)
    results = [
        _create_ligand_index(
            gmx=gmx,
            tpr_path=prod / "md.tpr",
            output_path=index_path,
            ligand_selection=_ligand_selection(config, prep / "complexo.pdb"),
            catalytic_selection=catalytic_selection,
            cwd=analysis,
        )
    ]

    commands = [
        (
            "rmsd_backbone",
            [
                gmx,
                "rms",
                "-s",
                str(prod / "md.tpr"),
                "-f",
                str(prod / "md_fit.xtc"),
                "-n",
                str(index_path),
                "-o",
                str(analysis / "rmsd_backbone.xvg"),
                "-tu",
                "ns",
            ],
            f"{config.analysis.fit_group}\n{config.analysis.fit_group}\n",
            analysis / "rmsd_backbone.xvg",
        ),
        (
            "rmsd_ligante",
            [
                gmx,
                "rms",
                "-s",
                str(prod / "md.tpr"),
                "-f",
                str(prod / "md_fit.xtc"),
                "-n",
                str(index_path),
                "-o",
                str(analysis / "rmsd_ligante.xvg"),
                "-tu",
                "ns",
            ],
            "Ligante\nLigante\n",
            analysis / "rmsd_ligante.xvg",
        ),
        (
            "rmsf_residuos",
            [
                gmx,
                "rmsf",
                "-s",
                str(prod / "md.tpr"),
                "-f",
                str(prod / "md_fit.xtc"),
                "-n",
                str(index_path),
                "-res",
                "-fit",
                "-o",
                str(analysis / "rmsf_residuos.xvg"),
            ],
            f"{config.analysis.fit_group}\n",
            analysis / "rmsf_residuos.xvg",
        ),
        (
            "gyrate",
            [
                gmx,
                "gyrate",
                "-s",
                str(prod / "md.tpr"),
                "-f",
                str(prod / "md_fit.xtc"),
                "-n",
                str(index_path),
                "-o",
                str(analysis / "gyrate.xvg"),
                "-tu",
                "ns",
            ],
            "Protein\n",
            analysis / "gyrate.xvg",
        ),
        (
            "mindist",
            [
                gmx,
                "mindist",
                "-s",
                str(prod / "md.tpr"),
                "-f",
                str(prod / "md_fit.xtc"),
                "-n",
                str(index_path),
                "-od",
                str(analysis / "mindist.xvg"),
                "-on",
                str(analysis / "numcont.xvg"),
                "-d",
                str(config.analysis.contact_cutoff_nm),
                "-tu",
                "ns",
            ],
            "Receptor\nLigante\n",
            analysis / "mindist.xvg",
        ),
        (
            "hbond",
            [
                gmx,
                "hbond",
                "-s",
                str(prod / "md.tpr"),
                "-f",
                str(prod / "md_fit.xtc"),
                "-n",
                str(index_path),
                "-num",
                str(analysis / "hbond.xvg"),
                "-tu",
                "ns",
            ],
            "Receptor\nLigante\n",
            analysis / "hbond.xvg",
        ),
    ]
    if catalytic_selection is not None:
        commands.append(
            (
                "catalytic-triad",
                [
                    gmx,
                    "mindist",
                    "-s",
                    str(prod / "md.tpr"),
                    "-f",
                    str(prod / "md_fit.xtc"),
                    "-n",
                    str(index_path),
                    "-od",
                    str(analysis / "catalytic_distance.xvg"),
                    "-on",
                    str(analysis / "catalytic_occupancy.xvg"),
                    "-d",
                    str(config.analysis.catalytic_distance_cutoff_nm),
                    "-tu",
                    "ns",
                ],
                "Ligante\nTriadeCatalitica\n",
                analysis / "catalytic_distance.xvg",
            )
        )

    for name, command, stdin, output_path in commands:
        results.append(
            _run_analysis_command(name, command, stdin, output_path, analysis)
        )
    return results


def run_interaction_energy(
    config: GmxFlowConfig,
    project_root: Path,
) -> list[AnalysisCommandResult]:
    project_root = project_root.expanduser().resolve()
    work_dir = project_root / "work"
    prod = work_dir / "prod"
    topo = work_dir / "topo"
    analysis = work_dir / "analysis"
    analysis.mkdir(parents=True, exist_ok=True)

    gmx = _gmx_command(config)
    results: list[AnalysisCommandResult] = []
    results.append(
        _run_analysis_command(
            "interaction-grompp",
            [
                gmx,
                "grompp",
                "-f",
                str(analysis / "rerun.mdp"),
                "-c",
                str(prod / "md.gro"),
                "-p",
                str(topo / "topol.top"),
                "-n",
                str(analysis / "lig.ndx"),
                "-o",
                str(analysis / "interaction.tpr"),
            ],
            "",
            analysis / "interaction.tpr",
            analysis,
        )
    )
    results.append(
        _run_analysis_command(
            "interaction-rerun",
            _interaction_rerun_command(
                config=config,
                gmx=gmx,
                tpr_path=analysis / "interaction.tpr",
                trajectory_path=prod / "md_fit.xtc",
            ),
            "",
            analysis / "interaction.edr",
            analysis,
        )
    )
    selected_terms = _interaction_energy_terms(
        gmx=gmx,
        energy_path=analysis / "interaction.edr",
        cwd=analysis,
    )
    results.append(
        _run_analysis_command(
            "interaction-energy",
            [
                gmx,
                "energy",
                "-f",
                str(analysis / "interaction.edr"),
                "-o",
                str(analysis / "interaction_energy.xvg"),
            ],
            "".join(f"{term.number}\n" for term in selected_terms) + "\n",
            analysis / "interaction_energy.xvg",
            analysis,
        )
    )
    return results


def run_sasa_analysis(
    config: GmxFlowConfig,
    project_root: Path,
) -> list[AnalysisCommandResult]:
    project_root = project_root.expanduser().resolve()
    work_dir = project_root / "work"
    prod = work_dir / "prod"
    analysis = work_dir / "analysis"
    analysis.mkdir(parents=True, exist_ok=True)

    gmx = _gmx_command(config)
    commands = [
        (
            "sasa-receptor",
            analysis / "sasa_receptor.xvg",
            'group "Receptor"',
        ),
        (
            "sasa-ligante",
            analysis / "sasa_ligante.xvg",
            'group "Ligante"',
        ),
        (
            "sasa-complexo",
            analysis / "sasa_complexo.xvg",
            'group "Receptor" or group "Ligante"',
        ),
    ]
    results = [
        _run_analysis_command(
            name,
            [
                gmx,
                "sasa",
                "-s",
                str(prod / "md.tpr"),
                "-f",
                str(prod / "md_fit.xtc"),
                "-n",
                str(analysis / "lig.ndx"),
                "-o",
                str(output_path),
                "-surface",
                selection,
                "-output",
                selection,
                "-tu",
                "ns",
            ],
            "",
            output_path,
            analysis,
        )
        for name, output_path, selection in commands
    ]
    _write_bsa_xvg(
        receptor_path=analysis / "sasa_receptor.xvg",
        ligand_path=analysis / "sasa_ligante.xvg",
        complex_path=analysis / "sasa_complexo.xvg",
        output_path=analysis / "bsa.xvg",
    )
    results.append(
        AnalysisCommandResult(
            name="bsa",
            command=["<internal>", "calculate-bsa"],
            stdout="",
            stderr="",
            returncode=0,
            output_path=analysis / "bsa.xvg",
        )
    )
    return results


def _run_analysis_command(
    name: str,
    command: list[str],
    stdin: str,
    output_path: Path,
    cwd: Path,
) -> AnalysisCommandResult:
    completed = subprocess.run(
        command,
        cwd=cwd,
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
    )
    result = AnalysisCommandResult(
        name=name,
        command=command,
        stdout=completed.stdout,
        stderr=completed.stderr,
        returncode=completed.returncode,
        output_path=output_path,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Análise '{name}' falhou com codigo {completed.returncode}: {format_command(command)}\n"
            f"{completed.stderr.strip()}"
        )
    return result


def _write_bsa_xvg(
    receptor_path: Path,
    ligand_path: Path,
    complex_path: Path,
    output_path: Path,
) -> None:
    receptor = _load_xvg_rows(receptor_path)
    ligand = _load_xvg_rows(ligand_path)
    complex_sasa = _load_xvg_rows(complex_path)
    if not receptor or not ligand or not complex_sasa:
        raise RuntimeError("Arquivos SASA ausentes para calcular BSA.")
    if len(receptor) != len(ligand) or len(receptor) != len(complex_sasa):
        raise RuntimeError("Arquivos SASA incompatíveis para calcular BSA.")

    lines = [
        "# BSA aproximado calculado por gmxflow",
        "# BSA = SASA receptor + SASA ligante - SASA complexo",
        '@ title "Buried Surface Area"',
        '@ xaxis label "Time (ns)"',
        '@ yaxis label "Area (nm^2)"',
        "@TYPE xy",
    ]
    for receptor_row, ligand_row, complex_row in zip(
        receptor,
        ligand,
        complex_sasa,
        strict=True,
    ):
        if len(receptor_row) < 2 or len(ligand_row) < 2 or len(complex_row) < 2:
            raise RuntimeError(
                "Arquivos SASA sem colunas suficientes para calcular BSA."
            )
        if receptor_row[0] != ligand_row[0] or receptor_row[0] != complex_row[0]:
            raise RuntimeError("Tempos SASA incompatíveis para calcular BSA.")
        bsa = receptor_row[1] + ligand_row[1] - complex_row[1]
        lines.append(f"{receptor_row[0]:.6f} {bsa:.6f}")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _load_xvg_rows(path: Path) -> list[list[float]]:
    rows: list[list[float]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(("#", "@")):
            continue
        try:
            rows.append([float(value) for value in line.split()])
        except ValueError:
            continue
    return rows


class EnergyTerm(BaseModel):
    number: int
    name: str


def _interaction_energy_terms(
    gmx: str, energy_path: Path, cwd: Path
) -> list[EnergyTerm]:
    probe = cwd / "_interaction_energy_probe.xvg"
    completed = subprocess.run(
        [gmx, "energy", "-f", str(energy_path), "-o", str(probe)],
        cwd=cwd,
        input="\n",
        text=True,
        capture_output=True,
        check=False,
    )
    probe.unlink(missing_ok=True)
    output = completed.stdout + "\n" + completed.stderr
    terms = _parse_energy_terms(output)
    selected = [term for term in terms if _is_receptor_ligand_energy_term(term.name)]
    if not selected:
        raise RuntimeError(
            "Não foi possível detectar termos Coul-SR/LJ-SR entre Receptor e Ligante "
            "em interaction.edr."
        )
    return selected


def _parse_energy_terms(output: str) -> list[EnergyTerm]:
    terms: list[EnergyTerm] = []
    for line in output.splitlines():
        match = re.match(r"^\s*(\d+)\s+(.+?)\s*$", line)
        if match is None:
            continue
        terms.append(EnergyTerm(number=int(match.group(1)), name=match.group(2)))
    return terms


def _is_receptor_ligand_energy_term(name: str) -> bool:
    normalized = name.replace("_", "-")
    if not normalized.startswith(("Coul-SR:", "LJ-SR:")):
        return False
    return "Receptor-Ligante" in normalized or "Ligante-Receptor" in normalized


def _create_ligand_index(
    gmx: str,
    tpr_path: Path,
    output_path: Path,
    ligand_selection: str,
    catalytic_selection: str | None,
    cwd: Path,
) -> AnalysisCommandResult:
    default = subprocess.run(
        [gmx, "make_ndx", "-f", str(tpr_path), "-o", str(cwd / "_default.ndx")],
        cwd=cwd,
        input="q\n",
        text=True,
        capture_output=True,
        check=False,
    )
    if default.returncode != 0:
        raise RuntimeError(
            f"Análise 'make_index_default' falhou com codigo {default.returncode}\n"
            f"{default.stderr.strip()}"
        )

    default_group_count = _count_index_groups(default.stdout + "\n" + default.stderr)
    (cwd / "_default.ndx").unlink(missing_ok=True)
    ligand_index = default_group_count
    next_index = ligand_index + 1
    stdin_parts = [
        f"{ligand_selection}\n",
        f"name {ligand_index} Ligante\n",
    ]
    if catalytic_selection is not None:
        catalytic_index = next_index
        next_index += 1
        stdin_parts.extend(
            [
                f"{catalytic_selection}\n",
                f"name {catalytic_index} TriadeCatalitica\n",
            ]
        )
    receptor_index = next_index
    stdin_parts.extend(
        [
            f"1 & ! {ligand_index}\n",
            f"name {receptor_index} Receptor\n",
            "q\n",
        ]
    )
    stdin = "".join(stdin_parts)
    command = [gmx, "make_ndx", "-f", str(tpr_path), "-o", str(output_path)]
    return _run_analysis_command(
        "ligand_index",
        command,
        stdin,
        output_path,
        cwd,
    )


def _count_index_groups(output: str) -> int:
    group_numbers = {
        int(match.group(1))
        for line in output.splitlines()
        if (match := re.match(r"^\s*(\d+)\s+\S+", line))
    }
    if not group_numbers:
        raise RuntimeError("Não foi possível detectar grupos padrão do GROMACS.")
    return max(group_numbers) + 1


def _ligand_selection(config: GmxFlowConfig, complex_pdb: Path) -> str:
    if config.input.ligand_kind == "small_molecule":
        resname = config.input.ligand_resname.strip()
        if not resname:
            raise RuntimeError("input.ligand_resname deve ser informado para análise.")
        return f"r {resname}"

    first_residue, last_residue = _ligand_residue_range(
        complex_pdb, chain=config.analysis.ligand_chain
    )
    return f"r {first_residue}-{last_residue}"


def _catalytic_residue_selection(config: GmxFlowConfig) -> str | None:
    raw = config.analysis.catalytic_residues.strip()
    if not raw:
        return None

    residues: list[str] = []
    for token in re.split(r"[,;\s]+", raw):
        if not token:
            continue
        match = re.search(r"\d+", token)
        if match is None:
            raise RuntimeError(
                "analysis.catalytic_residues deve conter números de resíduos, "
                f"mas recebeu: {token}"
            )
        residues.append(match.group(0))

    if not residues:
        return None
    return " | ".join(f"r {residue}" for residue in residues)


def _ligand_residue_range(complex_pdb: Path, chain: str) -> tuple[int, int]:
    residues: list[int] = []
    for line in complex_pdb.read_text(encoding="utf-8").splitlines():
        if line.startswith(("ATOM", "HETATM")) and line[21:22] == chain:
            residues.append(int(line[22:26]))
    if not residues:
        raise RuntimeError(
            f"Não foi possível detectar resíduos do ligante na cadeia {chain}: {complex_pdb}"
        )
    return min(residues), max(residues)


def _gmx_command(config: GmxFlowConfig) -> str:
    if config.mdrun.engine in {"gmx", "gmx_mpi"}:
        return config.mdrun.engine
    return "gmx"


def _interaction_rerun_command(
    config: GmxFlowConfig,
    gmx: str,
    tpr_path: Path,
    trajectory_path: Path,
) -> list[str]:
    command = [
        gmx,
        "mdrun",
        "-s",
        str(tpr_path),
        "-rerun",
        str(trajectory_path),
        "-deffnm",
        "interaction",
    ]
    if gmx != "gmx_mpi":
        command.extend(["-ntmpi", "1"])
    command.extend(["-ntomp", str(config.mdrun.ntomp), "-nb", "cpu"])
    if config.mdrun.pin != "auto":
        command.extend(["-pin", config.mdrun.pin])
    return command
