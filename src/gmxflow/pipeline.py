from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from gmxflow.config import GmxFlowConfig


class PipelineStep(BaseModel):
    name: str
    description: str
    workdir: Path
    command: list[str]
    inputs: list[Path] = Field(default_factory=list)
    outputs: list[Path] = Field(default_factory=list)
    stdin: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    state: dict[str, object] = Field(default_factory=dict)


def build_pipeline(
    config: GmxFlowConfig,
    config_dir: Path,
    config_path: Path | None = None,
    strict_inputs: bool = False,
) -> list[PipelineStep]:
    project_root = config_dir.expanduser().resolve()
    work_dir = project_root / "work"
    receptor_pdb = _resolve_from_config(config.input.receptor_pdb, project_root)
    ligand_pdb = _resolve_from_config(config.input.ligand_pdb, project_root)
    ligand_mol2 = _resolve_from_config(config.input.ligand_mol2, project_root)
    ligand_str = _resolve_from_config(config.input.ligand_str, project_root)
    config_path = (config_path or (project_root / "config.toml")).expanduser().resolve()

    if strict_inputs:
        _require_file(receptor_pdb)
        _require_file(ligand_pdb)
        if config.input.ligand_kind == "small_molecule":
            _require_file(ligand_mol2)
            _require_file(ligand_str)

    gmx = _gmx_command(config)
    gromacs_env = _gromacs_env(config.force_field.name, project_root)

    prep = work_dir / "prep"
    topo = work_dir / "topo"
    box = work_dir / "box"
    em = work_dir / "em"
    nvt = work_dir / "nvt"
    npt = work_dir / "npt"
    prod = work_dir / "prod"
    analysis = work_dir / "analysis"
    outputs = project_root / "outputs"
    ligand = work_dir / "ligand"
    ligand_prefix = config.input.ligand_resname.lower()

    steps = [
        PipelineStep(
            name="prepare",
            description="Preparar complexo receptor-ligante.",
            workdir=prep,
            command=[
                "gmxflow",
                "prepare-complex",
                "--config",
                str(config_path),
                "--force",
            ],
            inputs=[receptor_pdb, ligand_pdb],
            outputs=[
                prep / "receptor_fixed.pdb",
                prep / "ligante_fixed.pdb",
                prep / "complexo.pdb",
            ],
            state={
                "input.ph": config.input.ph,
                "input.ligand_kind": config.input.ligand_kind,
                "input.ligand_resname": config.input.ligand_resname,
                "force_field.name": config.force_field.name,
            },
        ),
    ]

    if config.input.ligand_kind == "small_molecule":
        steps.extend(
            [
                PipelineStep(
                    name="ligand-topology",
                    description="Converter topologia CGenFF do ligante para GROMACS.",
                    workdir=ligand,
                    command=["gmxflow", "prepare-ligand", "--config", str(config_path)],
                    inputs=[ligand_mol2, ligand_str],
                    outputs=[
                        ligand / f"{ligand_prefix}.itp",
                        ligand / f"{ligand_prefix}.prm",
                        ligand / f"{ligand_prefix}.top",
                        ligand / f"{ligand_prefix}_ini.pdb",
                    ],
                    state={
                        "input.ligand_resname": config.input.ligand_resname,
                        "force_field.name": config.force_field.name,
                    },
                ),
                PipelineStep(
                    name="protein-topology",
                    description="Gerar topologia da proteína com pdb2gmx.",
                    workdir=topo,
                    command=[
                        gmx,
                        "pdb2gmx",
                        "-f",
                        str(prep / "receptor_fixed.pdb"),
                        "-o",
                        "protein.gro",
                        "-p",
                        "topol.top",
                        "-i",
                        "posre.itp",
                        "-ff",
                        config.force_field.name,
                        "-water",
                        config.force_field.water,
                        "-ignh",
                        "-ter",
                    ],
                    stdin=_terminal_selection_stdin(config, chains=1),
                    inputs=[prep / "receptor_fixed.pdb"],
                    outputs=[
                        topo / "protein.gro",
                        topo / "topol.top",
                    ],
                    env=gromacs_env,
                ),
                PipelineStep(
                    name="assemble-complex",
                    description="Montar complexo proteína-ligante pequeno.",
                    workdir=topo,
                    command=[
                        "gmxflow",
                        "assemble-complex",
                        "--config",
                        str(config_path),
                    ],
                    inputs=[
                        topo / "protein.gro",
                        topo / "topol.top",
                        ligand / f"{ligand_prefix}.itp",
                        ligand / f"{ligand_prefix}.prm",
                        ligand / f"{ligand_prefix}_ini.pdb",
                    ],
                    outputs=[
                        topo / "complexo.gro",
                        topo / "topol.top",
                        topo / ".small_molecule_complex.ok",
                    ],
                    state={
                        "input.ligand_resname": config.input.ligand_resname,
                        "solvent.positive_ion": config.solvent.positive_ion,
                        "solvent.negative_ion": config.solvent.negative_ion,
                    },
                ),
            ]
        )
    else:
        steps.append(
            PipelineStep(
                name="topology",
                description="Gerar topologia com pdb2gmx.",
                workdir=topo,
                command=[
                    gmx,
                    "pdb2gmx",
                    "-f",
                    str(prep / "complexo.pdb"),
                    "-o",
                    "complexo.gro",
                    "-p",
                    "topol.top",
                    "-i",
                    "posre.itp",
                    "-ff",
                    config.force_field.name,
                    "-water",
                    config.force_field.water,
                    "-ignh",
                    "-ter",
                    "-chainsep",
                    "ter",
                    "-merge",
                    "no",
                ],
                stdin=_terminal_selection_stdin(config, chains=2),
                inputs=[prep / "complexo.pdb"],
                outputs=[
                    topo / "complexo.gro",
                    topo / "topol.top",
                    topo / "topol_Protein_chain_A.itp",
                    topo / "topol_Protein_chain_B.itp",
                    topo / "posre_Protein_chain_A.itp",
                    topo / "posre_Protein_chain_B.itp",
                ],
                env=gromacs_env,
                state={
                    "input.ph": config.input.ph,
                    "force_field.name": config.force_field.name,
                },
            ),
        )

    final_analysis_inputs = [
        analysis / "rmsd_backbone.xvg",
        analysis / "rmsd_ligante.xvg",
        analysis / "rmsf_residuos.xvg",
        analysis / "gyrate.xvg",
        analysis / "mindist.xvg",
        analysis / "numcont.xvg",
        analysis / "hbond.xvg",
    ]
    analysis_outputs = [
        analysis / "lig.ndx",
        analysis / "rmsd_backbone.xvg",
        analysis / "rmsd_ligante.xvg",
        analysis / "rmsf_residuos.xvg",
        analysis / "gyrate.xvg",
        analysis / "mindist.xvg",
        analysis / "numcont.xvg",
        analysis / "hbond.xvg",
        analysis / "hbond.ndx",
    ]
    if config.analysis.catalytic_residues.strip():
        analysis_outputs.extend(
            [
                analysis / "catalytic_distance.xvg",
                analysis / "catalytic_occupancy.xvg",
            ]
        )
    steps.extend(
        [
            PipelineStep(
                name="box",
                description="Criar caixa de simulação.",
                workdir=box,
                command=[
                    gmx,
                    "editconf",
                    "-f",
                    str(topo / "complexo.gro"),
                    "-o",
                    "box.gro",
                    "-c",
                    "-d",
                    str(config.box.distance_nm),
                    "-bt",
                    config.box.type,
                ],
                inputs=[topo / "complexo.gro"],
                outputs=[box / "box.gro"],
                env=gromacs_env,
            ),
            PipelineStep(
                name="solvate",
                description="Adicionar solvente.",
                workdir=box,
                command=[
                    "gmxflow",
                    "solvate-system",
                    "--config",
                    str(config_path),
                ],
                inputs=[box / "box.gro", topo / "topol.top"],
                outputs=[box / "solv.gro", topo / "topol.top"],
                env=gromacs_env,
                state={
                    "solvent.water_structure": config.solvent.water_structure,
                    "solvent.positive_ion": config.solvent.positive_ion,
                    "solvent.negative_ion": config.solvent.negative_ion,
                    "solvent.salt_concentration_m": config.solvent.salt_concentration_m,
                    "solvent.neutralize": config.solvent.neutralize,
                },
            ),
            PipelineStep(
                name="ions-grompp",
                description="Preparar entrada binária para adição de íons.",
                workdir=box,
                command=[
                    gmx,
                    "grompp",
                    "-f",
                    "ions.mdp",
                    "-c",
                    "solv.gro",
                    "-p",
                    str(topo / "topol.top"),
                    "-o",
                    "ions.tpr",
                ],
                inputs=[box / "ions.mdp", box / "solv.gro", topo / "topol.top"],
                outputs=[box / "ions.tpr", box / "mdout.mdp"],
                env=gromacs_env,
            ),
            PipelineStep(
                name="ions",
                description="Adicionar íons e neutralizar o sistema.",
                workdir=box,
                command=[
                    gmx,
                    "genion",
                    "-s",
                    "ions.tpr",
                    "-o",
                    "ions.gro",
                    "-p",
                    str(topo / "topol.top"),
                    "-pname",
                    config.solvent.positive_ion,
                    "-nname",
                    config.solvent.negative_ion,
                    "-conc",
                    str(config.solvent.salt_concentration_m),
                    *(_neutralize_args(config)),
                ],
                stdin="SOL\n",
                inputs=[box / "ions.tpr", topo / "topol.top"],
                outputs=[box / "ions.gro", topo / "topol.top"],
                env=gromacs_env,
            ),
            PipelineStep(
                name="em-grompp",
                description="Preparar minimização de energia.",
                workdir=em,
                command=[
                    gmx,
                    "grompp",
                    "-f",
                    "em.mdp",
                    "-c",
                    str(box / "ions.gro"),
                    "-p",
                    str(topo / "topol.top"),
                    "-o",
                    "em.tpr",
                ],
                inputs=[em / "em.mdp", box / "ions.gro", topo / "topol.top"],
                outputs=[em / "em.tpr", em / "mdout.mdp"],
                env=gromacs_env,
            ),
            PipelineStep(
                name="em",
                description="Executar minimização de energia.",
                workdir=em,
                command=_mdrun_command(config, gmx, "em"),
                inputs=[em / "em.tpr"],
                outputs=[em / "em.gro", em / "em.edr", em / "em.log", em / "em.trr"],
                env=gromacs_env,
            ),
            PipelineStep(
                name="nvt-grompp",
                description="Preparar equilíbrio NVT.",
                workdir=nvt,
                command=[
                    gmx,
                    "grompp",
                    "-f",
                    "nvt.mdp",
                    "-c",
                    str(em / "em.gro"),
                    "-r",
                    str(em / "em.gro"),
                    "-p",
                    str(topo / "topol.top"),
                    "-o",
                    "nvt.tpr",
                ],
                inputs=[nvt / "nvt.mdp", em / "em.gro", topo / "topol.top"],
                outputs=[nvt / "nvt.tpr", nvt / "mdout.mdp"],
                env=gromacs_env,
            ),
            PipelineStep(
                name="nvt",
                description="Executar equilíbrio NVT.",
                workdir=nvt,
                command=_mdrun_command(config, gmx, "nvt"),
                inputs=[nvt / "nvt.tpr"],
                outputs=[
                    nvt / "nvt.gro",
                    nvt / "nvt.cpt",
                    nvt / "nvt.edr",
                    nvt / "nvt.log",
                    nvt / "nvt.trr",
                ],
                env=gromacs_env,
            ),
            PipelineStep(
                name="npt-grompp",
                description="Preparar equilíbrio NPT.",
                workdir=npt,
                command=[
                    gmx,
                    "grompp",
                    "-f",
                    "npt.mdp",
                    "-c",
                    str(nvt / "nvt.gro"),
                    "-t",
                    str(nvt / "nvt.cpt"),
                    "-r",
                    str(nvt / "nvt.gro"),
                    "-p",
                    str(topo / "topol.top"),
                    "-o",
                    "npt.tpr",
                ],
                inputs=[
                    npt / "npt.mdp",
                    nvt / "nvt.gro",
                    nvt / "nvt.cpt",
                    topo / "topol.top",
                ],
                outputs=[npt / "npt.tpr", npt / "mdout.mdp"],
                env=gromacs_env,
            ),
            PipelineStep(
                name="npt",
                description="Executar equilíbrio NPT.",
                workdir=npt,
                command=_mdrun_command(config, gmx, "npt"),
                inputs=[npt / "npt.tpr"],
                outputs=[
                    npt / "npt.gro",
                    npt / "npt.cpt",
                    npt / "npt.edr",
                    npt / "npt.log",
                    npt / "npt.trr",
                ],
                env=gromacs_env,
            ),
            PipelineStep(
                name="production-grompp",
                description="Preparar produção MD.",
                workdir=prod,
                command=[
                    gmx,
                    "grompp",
                    "-f",
                    "md.mdp",
                    "-c",
                    str(npt / "npt.gro"),
                    "-t",
                    str(npt / "npt.cpt"),
                    "-p",
                    str(topo / "topol.top"),
                    "-o",
                    "md.tpr",
                ],
                inputs=[
                    prod / "md.mdp",
                    npt / "npt.gro",
                    npt / "npt.cpt",
                    topo / "topol.top",
                ],
                outputs=[prod / "md.tpr", prod / "mdout.mdp"],
                env=gromacs_env,
            ),
            PipelineStep(
                name="production",
                description="Executar produção MD.",
                workdir=prod,
                command=_mdrun_command(config, gmx, "md"),
                inputs=[prod / "md.tpr"],
                outputs=[
                    prod / "md.xtc",
                    prod / "md.gro",
                    prod / "md.cpt",
                    prod / "md.edr",
                    prod / "md.log",
                ],
                env=gromacs_env,
            ),
            PipelineStep(
                name="pbc-nojump",
                description="Remover saltos por condições periódicas.",
                workdir=prod,
                command=[
                    gmx,
                    "trjconv",
                    "-s",
                    "md.tpr",
                    "-f",
                    "md.xtc",
                    "-o",
                    "md_nojump.xtc",
                    "-pbc",
                    "nojump",
                ],
                stdin="0\n",
                inputs=[prod / "md.tpr", prod / "md.xtc"],
                outputs=[prod / "md_nojump.xtc"],
                env=gromacs_env,
            ),
            PipelineStep(
                name="pbc-center",
                description="Centralizar sistema e manter moléculas compactas.",
                workdir=prod,
                command=[
                    gmx,
                    "trjconv",
                    "-s",
                    "md.tpr",
                    "-f",
                    "md_nojump.xtc",
                    "-o",
                    "md_nopbc.xtc",
                    "-pbc",
                    "mol",
                    "-center",
                    "-ur",
                    "compact",
                ],
                stdin=f"{config.analysis.center_group}\n{config.analysis.output_group}\n",
                inputs=[prod / "md.tpr", prod / "md_nojump.xtc"],
                outputs=[prod / "md_nopbc.xtc"],
                env=gromacs_env,
            ),
            PipelineStep(
                name="fit",
                description="Alinhar trajetória por rotação e translação.",
                workdir=prod,
                command=[
                    gmx,
                    "trjconv",
                    "-s",
                    "md.tpr",
                    "-f",
                    "md_nopbc.xtc",
                    "-o",
                    "md_fit.xtc",
                    "-fit",
                    "rot+trans",
                ],
                stdin=f"{config.analysis.fit_group}\n{config.analysis.output_group}\n",
                inputs=[prod / "md.tpr", prod / "md_nopbc.xtc"],
                outputs=[prod / "md_fit.xtc"],
                env=gromacs_env,
            ),
            PipelineStep(
                name="analysis",
                description="Executar análises principais.",
                workdir=analysis,
                command=["gmxflow", "analyze", "--config", str(config_path)],
                inputs=[prod / "md.tpr", prod / "md_fit.xtc"],
                outputs=analysis_outputs,
                state={
                    "input.ligand_kind": config.input.ligand_kind,
                    "input.ligand_resname": config.input.ligand_resname,
                    "analysis": config.analysis.model_dump(),
                },
            ),
        ]
    )
    if config.analysis.interaction_energy:
        steps.append(
            PipelineStep(
                name="interaction-energy",
                description="Calcular energia aproximada de interação receptor-ligante por rerun.",
                workdir=analysis,
                command=["gmxflow", "interaction-energy", "--config", str(config_path)],
                inputs=[
                    analysis / "rerun.mdp",
                    analysis / "lig.ndx",
                    prod / "md.gro",
                    prod / "md_fit.xtc",
                    topo / "topol.top",
                ],
                outputs=[
                    analysis / "interaction.tpr",
                    analysis / "interaction.edr",
                    analysis / "interaction.log",
                    analysis / "interaction_energy.xvg",
                ],
                env=gromacs_env,
                state={
                    "analysis.interaction_energy": config.analysis.interaction_energy,
                    "input.ligand_resname": config.input.ligand_resname,
                    "force_field.name": config.force_field.name,
                },
            )
        )
        final_analysis_inputs.append(analysis / "interaction_energy.xvg")
    if config.analysis.sasa:
        steps.append(
            PipelineStep(
                name="sasa",
                description="Calcular SASA e BSA aproximado receptor-ligante.",
                workdir=analysis,
                command=["gmxflow", "sasa", "--config", str(config_path)],
                inputs=[
                    analysis / "lig.ndx",
                    prod / "md.tpr",
                    prod / "md_fit.xtc",
                ],
                outputs=[
                    analysis / "sasa_receptor.xvg",
                    analysis / "sasa_ligante.xvg",
                    analysis / "sasa_complexo.xvg",
                    analysis / "bsa.xvg",
                ],
                env=gromacs_env,
                state={
                    "analysis.sasa": config.analysis.sasa,
                    "input.ligand_resname": config.input.ligand_resname,
                },
            )
        )
        final_analysis_inputs.extend(
            [
                analysis / "sasa_receptor.xvg",
                analysis / "sasa_ligante.xvg",
                analysis / "sasa_complexo.xvg",
                analysis / "bsa.xvg",
            ]
        )
    if config.analysis.catalytic_residues.strip():
        final_analysis_inputs.extend(
            [
                analysis / "catalytic_distance.xvg",
                analysis / "catalytic_occupancy.xvg",
            ]
        )
    plot_inputs = [
        analysis / "rmsd_backbone.xvg",
        analysis / "rmsd_ligante.xvg",
        analysis / "rmsf_residuos.xvg",
        analysis / "gyrate.xvg",
        analysis / "numcont.xvg",
        analysis / "hbond.xvg",
    ]
    plot_outputs = [
        analysis / "painel_completo.png",
        analysis / "rmsd_bb.png",
        analysis / "rmsd_lig.png",
        analysis / "rmsf.png",
        analysis / "rg.png",
        analysis / "ncont.png",
        analysis / "hbond.png",
    ]
    if config.analysis.sasa:
        plot_inputs.extend(
            [
                analysis / "sasa_complexo.xvg",
                analysis / "sasa_ligante.xvg",
                analysis / "bsa.xvg",
            ]
        )
        plot_outputs.extend(
            [
                analysis / "sasa_complexo.png",
                analysis / "sasa_ligante.png",
                analysis / "bsa.png",
            ]
        )
    if config.analysis.catalytic_residues.strip():
        plot_inputs.extend(
            [
                analysis / "catalytic_distance.xvg",
                analysis / "catalytic_occupancy.xvg",
            ]
        )
        plot_outputs.extend(
            [
                analysis / "catalytic_distance.png",
                analysis / "catalytic_occupancy.png",
            ]
        )
    steps.extend(
        [
            PipelineStep(
                name="plots",
                description="Gerar figuras das análises.",
                workdir=analysis,
                command=["gmxflow", "plot-analysis", "--config", str(config_path)],
                inputs=plot_inputs,
                outputs=plot_outputs,
                state={
                    "plots": config.plots.model_dump(),
                    "analysis.sasa": config.analysis.sasa,
                    "analysis.catalytic_residues": config.analysis.catalytic_residues,
                    "analysis.catalytic_distance_cutoff_nm": (
                        config.analysis.catalytic_distance_cutoff_nm
                    ),
                },
            ),
            PipelineStep(
                name="report",
                description="Gerar relatório consolidado das análises.",
                workdir=outputs,
                command=["gmxflow", "report", "--config", str(config_path)],
                inputs=[
                    *final_analysis_inputs,
                    *plot_outputs,
                ],
                outputs=[
                    outputs / "summary.json",
                    outputs / "summary.txt",
                    outputs / "report.html",
                ],
                state={
                    "project": config.project.model_dump(),
                    "input.ligand_kind": config.input.ligand_kind,
                    "input.ligand_resname": config.input.ligand_resname,
                    "simulation": config.simulation.model_dump(),
                    "analysis": config.analysis.model_dump(),
                    "plots": config.plots.model_dump(),
                },
            ),
        ]
    )
    return steps


def _resolve_from_config(value: str, config_dir: Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return config_dir / path


def _require_file(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Arquivo de entrada não encontrado: {path}")


def _gmx_command(config: GmxFlowConfig) -> str:
    if config.mdrun.engine in {"gmx", "gmx_mpi"}:
        return config.mdrun.engine
    return "gmx"


def _gromacs_env(force_field_name: str, project_root: Path) -> dict[str, str]:
    force_field_dir = _local_force_field_dir(force_field_name, project_root)
    if force_field_dir is None:
        return {}
    return {"GMXLIB": str(force_field_dir.parent)}


def _local_force_field_dir(force_field_name: str, project_root: Path) -> Path | None:
    names = [force_field_name]
    if force_field_name and not force_field_name.endswith(".ff"):
        names.append(f"{force_field_name}.ff")
    for name in names:
        path = Path(name).expanduser()
        if path.is_absolute() and path.is_dir():
            return path.resolve()
        candidate = project_root / path
        if candidate.is_dir():
            return candidate.resolve()
    return None


def _neutralize_args(config: GmxFlowConfig) -> list[str]:
    return ["-neutral"] if config.solvent.neutralize else []


def _terminal_selection_stdin(config: GmxFlowConfig, chains: int) -> str:
    if config.pdb2gmx.terminal_selections:
        return "\n".join(config.pdb2gmx.terminal_selections) + "\n"
    if config.force_field.name.lower().startswith("charmm"):
        selections = ["1", "0"] * chains
    else:
        selections = ["0", "0"] * chains
    return "\n".join(selections) + "\n"


def _mdrun_command(config: GmxFlowConfig, gmx: str, deffnm: str) -> list[str]:
    command = [gmx, "mdrun", "-v", "-deffnm", deffnm]
    if gmx != "gmx_mpi":
        command.extend(["-ntmpi", "1"])
    command.extend(["-ntomp", str(config.mdrun.ntomp)])
    if config.mdrun.gpu == "force":
        # command.extend(["-nb", "gpu", "-pme", "gpu", "-bonded", "gpu", "-gpu_id", config.mdrun.gpu_id])
        command.extend(["-nb", "gpu", "-gpu_id", config.mdrun.gpu_id])
    elif config.mdrun.gpu == "off":
        command.extend(["-nb", "cpu"])
    if config.mdrun.pin != "auto":
        command.extend(["-pin", config.mdrun.pin])
    return command
