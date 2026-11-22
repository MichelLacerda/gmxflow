from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Protocol, TypeAlias

from pydantic import BaseModel, Field

from gmxflow.config import GmxFlowConfig
from gmxflow.forcefields import resolve_forcefield


REAL_EXECUTION_STEPS = frozenset(
    {
        "prepare",
        "ligand-topology",
        "protein-topology",
        "assemble-complex",
        "topology",
        "box",
        "solvate",
        "ions-grompp",
        "ions",
        "em-grompp",
        "em",
        "nvt-grompp",
        "nvt",
        "npt-grompp",
        "npt",
        "production-grompp",
        "production",
        "thermodynamics",
        "pbc-nojump",
        "pbc-center",
        "fit",
        "analysis",
        "interaction-energy",
        "sasa",
        "plots",
        "report",
    }
)


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


@dataclass(frozen=True)
class Artifact:
    """Logical artifact declaration; physical paths are resolved elsewhere."""

    key: str
    kind: str

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError("Artifact.key não pode ser vazio")
        if not self.kind.strip():
            raise ValueError("Artifact.kind não pode ser vazio")


class Step(Protocol):
    """Structural contract for a step in a declarative workflow."""

    id: str
    name: str
    inputs: tuple[Artifact, ...]
    outputs: tuple[Artifact, ...]
    parallel: bool

    def run(self, context: RunContext) -> None: ...


class RunContext(Protocol):
    """Execution context interface, completed with the executor migration."""


@dataclass(frozen=True)
class Sequence:
    """An ordered composition of workflow items."""

    items: tuple[WorkflowItem, ...]

    def __init__(self, *items: WorkflowItem) -> None:
        if not items:
            raise ValueError("Sequence precisa conter ao menos um item")
        object.__setattr__(self, "items", items)


@dataclass(frozen=True)
class Parallel:
    """Independent workflow branches followed by an implicit join."""

    branches: tuple[WorkflowItem, ...]

    def __init__(self, *branches: WorkflowItem) -> None:
        if not branches:
            raise ValueError("Parallel precisa conter ao menos um ramo")
        object.__setattr__(self, "branches", branches)


WorkflowItem: TypeAlias = Step | Sequence | Parallel


@dataclass(frozen=True)
class WorkflowGraph:
    """Validated dependency graph; this model does not execute its steps."""

    steps: Mapping[str, Step]
    dependencies: Mapping[str, frozenset[str]]
    producers: Mapping[str, str | None]
    parallel_groups: tuple[tuple[frozenset[str], ...], ...]

    @classmethod
    def from_workflow(
        cls,
        workflow: WorkflowItem,
        project_inputs: Iterable[Artifact] = (),
    ) -> WorkflowGraph:
        steps: dict[str, Step] = {}
        graph: dict[str, set[str]] = {}
        parallel_groups: list[tuple[frozenset[str], ...]] = []

        def visit(item: WorkflowItem) -> tuple[set[str], set[str]]:
            if isinstance(item, Sequence):
                entries: set[str] = set()
                previous_exits: set[str] = set()
                for child in item.items:
                    child_entries, child_exits = visit(child)
                    if not entries:
                        entries = child_entries
                    for predecessor in previous_exits:
                        for successor in child_entries:
                            graph[predecessor].add(successor)
                    previous_exits = child_exits
                return entries, previous_exits

            if isinstance(item, Parallel):
                branch_sets: list[frozenset[str]] = []
                all_entries: set[str] = set()
                all_exits: set[str] = set()
                for branch in item.branches:
                    branch_entries, branch_exits = visit(branch)
                    branch_nodes = _workflow_step_ids(branch)
                    if any(not steps[step_id].parallel for step_id in branch_nodes):
                        ineligible = sorted(
                            step_id for step_id in branch_nodes if not steps[step_id].parallel
                        )
                        raise ValueError(
                            "Etapas não elegíveis para Parallel: " + ", ".join(ineligible)
                        )
                    branch_sets.append(frozenset(branch_nodes))
                    all_entries.update(branch_entries)
                    all_exits.update(branch_exits)
                parallel_groups.append(tuple(branch_sets))
                return all_entries, all_exits

            step = item
            _validate_step(step)
            if step.id in steps:
                raise ValueError(f"ID de etapa duplicado no workflow: {step.id!r}")
            steps[step.id] = step
            graph[step.id] = set()
            return {step.id}, {step.id}

        visit(workflow)

        external_inputs: dict[str, Artifact] = {}
        for artifact in project_inputs:
            if artifact.key in external_inputs:
                raise ValueError(f"Entrada de projeto duplicada: {artifact.key!r}")
            external_inputs[artifact.key] = artifact

        producers: dict[str, str | None] = {
            key: None for key in external_inputs
        }
        for step in steps.values():
            for artifact in step.outputs:
                if artifact.key in producers:
                    raise ValueError(
                        f"Artefato {artifact.key!r} tem mais de uma origem "
                        "ou também foi declarado como entrada do projeto"
                    )
                producers[artifact.key] = step.id

        for step in steps.values():
            for artifact in step.inputs:
                producer_id = producers.get(artifact.key, "missing")
                if producer_id == "missing":
                    raise ValueError(
                        f"Etapa {step.id!r} requer artefato sem origem: {artifact.key!r}"
                    )
                producer_artifact = (
                    external_inputs[artifact.key]
                    if producer_id is None
                    else next(
                        output
                        for output in steps[producer_id].outputs
                        if output.key == artifact.key
                    )
                )
                if producer_artifact.kind != artifact.kind:
                    raise ValueError(
                        f"Tipo incompatível para artefato {artifact.key!r}: "
                        f"esperado {artifact.kind!r}, produzido como "
                        f"{producer_artifact.kind!r}"
                    )
                if producer_id is not None:
                    graph[producer_id].add(step.id)

        cycle = _find_cycle(graph)
        if cycle:
            raise ValueError(f"Workflow contém dependência cíclica: {cycle}")

        for branches in parallel_groups:
            for index, left in enumerate(branches):
                for right in branches[index + 1 :]:
                    if any(
                        _has_path(graph, left_step, right_step)
                        or _has_path(graph, right_step, left_step)
                        for left_step in left
                        for right_step in right
                    ):
                        raise ValueError(
                            "Ramos de Parallel possuem dependência entre si"
                        )

        return cls(
            steps=MappingProxyType(steps),
            dependencies=MappingProxyType(
                {
                    step_id: frozenset(
                        predecessor
                        for predecessor, successors in graph.items()
                        if step_id in successors
                    )
                    for step_id in graph
                }
            ),
            producers=MappingProxyType(producers),
            parallel_groups=tuple(parallel_groups),
        )

    @property
    def topological_order(self) -> tuple[str, ...]:
        """Return a deterministic order consistent with all dependencies."""
        successors: dict[str, set[str]] = {
            step_id: set() for step_id in self.steps
        }
        indegree = {step_id: len(predecessors) for step_id, predecessors in self.dependencies.items()}
        for step_id, predecessors in self.dependencies.items():
            for predecessor in predecessors:
                successors[predecessor].add(step_id)

        ready = sorted(step_id for step_id, count in indegree.items() if count == 0)
        ordered: list[str] = []
        while ready:
            step_id = ready.pop(0)
            ordered.append(step_id)
            for successor in sorted(successors[step_id]):
                indegree[successor] -= 1
                if indegree[successor] == 0:
                    ready.append(successor)
                    ready.sort()
        if len(ordered) != len(self.steps):
            raise ValueError("Workflow contém dependência cíclica")
        return tuple(ordered)


def _validate_step(step: Step) -> None:
    if not isinstance(step.id, str) or not step.id.strip():
        raise ValueError("Step.id deve ser uma string não vazia")
    if not isinstance(step.name, str) or not step.name.strip():
        raise ValueError(f"Step {step.id!r} precisa de um name não vazio")
    if not isinstance(step.parallel, bool):
        raise ValueError(f"Step {step.id!r}: parallel deve ser bool")
    if not callable(getattr(step, "run", None)):
        raise ValueError(f"Step {step.id!r}: run(context) deve ser implementado")
    for field_name in ("inputs", "outputs"):
        artifacts = getattr(step, field_name)
        if not isinstance(artifacts, tuple) or any(
            not isinstance(artifact, Artifact) for artifact in artifacts
        ):
            raise ValueError(
                f"Step {step.id!r}: {field_name} deve ser uma tupla de Artifact"
            )
        keys = [artifact.key for artifact in artifacts]
        if len(keys) != len(set(keys)):
            raise ValueError(
                f"Step {step.id!r}: chaves duplicadas em {field_name}"
            )


def _workflow_step_ids(item: WorkflowItem) -> set[str]:
    if isinstance(item, Sequence):
        return set().union(*(_workflow_step_ids(child) for child in item.items))
    if isinstance(item, Parallel):
        return set().union(*(_workflow_step_ids(branch) for branch in item.branches))
    return {item.id}


def _has_path(graph: Mapping[str, set[str]], start: str, goal: str) -> bool:
    pending = [start]
    visited: set[str] = set()
    while pending:
        current = pending.pop()
        if current == goal:
            return True
        if current not in visited:
            visited.add(current)
            pending.extend(graph[current] - visited)
    return False


def _find_cycle(graph: Mapping[str, set[str]]) -> str | None:
    active: list[str] = []
    active_set: set[str] = set()
    complete: set[str] = set()

    def visit(step_id: str) -> list[str] | None:
        if step_id in active_set:
            cycle_start = active.index(step_id)
            return [*active[cycle_start:], step_id]
        if step_id in complete:
            return None
        active.append(step_id)
        active_set.add(step_id)
        for successor in graph[step_id]:
            cycle = visit(successor)
            if cycle is not None:
                return cycle
        active.pop()
        active_set.remove(step_id)
        complete.add(step_id)
        return None

    for step_id in graph:
        cycle = visit(step_id)
        if cycle is not None:
            return " -> ".join(cycle)
    return None


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
    config_path = (config_path or (project_root / "project.toml")).expanduser().resolve()

    if strict_inputs:
        _require_file(receptor_pdb)
        if config.input.ligand_kind != "none":
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

    preparation_inputs = [receptor_pdb]
    preparation_outputs = [prep / "receptor_fixed.pdb", prep / "complexo.pdb"]
    if config.input.remove_resnames:
        preparation_outputs.insert(0, prep / "receptor_filtered.pdb")
    if config.input.ligand_kind != "none":
        preparation_inputs.append(ligand_pdb)
        preparation_outputs.insert(1, prep / "ligante_fixed.pdb")

    steps = [
        PipelineStep(
            name="prepare",
            description=(
                "Preparar proteína sem ligante."
                if config.input.ligand_kind == "none"
                else "Preparar complexo receptor-ligante."
            ),
            workdir=prep,
            command=[
                "gmxflow",
                "prepare-complex",
                "--project",
                str(config_path),
                "--force",
            ],
            inputs=preparation_inputs,
            outputs=preparation_outputs,
            state={
                "input.ph": config.input.ph,
                "input.ligand_kind": config.input.ligand_kind,
                "input.ligand_resname": config.input.ligand_resname,
                "input.remove_resnames": config.input.remove_resnames,
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
                    command=["gmxflow", "prepare-ligand", "--project", str(config_path)],
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
                        "--project",
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
        topology_chains = 1 if config.input.ligand_kind == "none" else 2
        topology_outputs = [topo / "complexo.gro", topo / "topol.top"]
        if config.input.ligand_kind == "none":
            topology_outputs.extend(
                [
                    topo / "topol_Protein_chain_A.itp",
                    topo / "posre_Protein_chain_A.itp",
                ]
            )
        else:
            topology_outputs.extend(
                [
                    topo / "topol_Protein_chain_A.itp",
                    topo / "topol_Protein_chain_B.itp",
                    topo / "posre_Protein_chain_A.itp",
                    topo / "posre_Protein_chain_B.itp",
                ]
            )
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
                stdin=_terminal_selection_stdin(config, chains=topology_chains),
                inputs=[prep / "complexo.pdb"],
                outputs=topology_outputs,
                env=gromacs_env,
                state={
                    "input.ph": config.input.ph,
                    "force_field.name": config.force_field.name,
                },
            ),
        )

    if config.input.ligand_kind == "none":
        final_analysis_inputs = [
            analysis / "rmsd_backbone.xvg",
            analysis / "rmsd_reference.xvg",
            analysis / "rmsf_residuos.xvg",
            analysis / "gyrate.xvg",
        ]
        analysis_outputs = list(final_analysis_inputs)
        plot_inputs = list(final_analysis_inputs)
        plot_outputs = [
            analysis / "rmsd_bb.png",
            analysis / "rmsd_reference.png",
            analysis / "rmsf.png",
            analysis / "rg.png",
        ]
    else:
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
    if config.analysis.catalytic_residues.strip():
        analysis_outputs.extend(
            [
                analysis / "catalytic_distance.xvg",
                analysis / "catalytic_occupancy.xvg",
            ]
        )
    analysis_step_inputs = [prod / "md.tpr", prod / "md_fit.xtc"]
    if config.input.ligand_kind == "none":
        analysis_step_inputs.append(em / "em.tpr")
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
                    "--project",
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
                command=["gmxflow", "analyze", "--project", str(config_path)],
                inputs=analysis_step_inputs,
                outputs=analysis_outputs,
                state={
                    "input.ligand_kind": config.input.ligand_kind,
                    "input.ligand_resname": config.input.ligand_resname,
                    "analysis": config.analysis.model_dump(),
                },
            ),
        ]
    )
    steps.append(
        PipelineStep(
            name="thermodynamics",
            description="Extrair propriedades termodinâmicas das etapas MD.",
            workdir=analysis,
            command=["gmxflow", "thermodynamics", "--project", str(config_path)],
            inputs=[em / "em.edr", nvt / "nvt.edr", npt / "npt.edr"],
            outputs=[
                analysis / "em_potential.xvg",
                analysis / "nvt_temperature.xvg",
                analysis / "npt_pressure.xvg",
                analysis / "npt_density.xvg",
            ],
            env=gromacs_env,
        )
    )
    if config.analysis.interaction_energy:
        steps.append(
            PipelineStep(
                name="interaction-energy",
                description="Calcular energia aproximada de interação receptor-ligante por rerun.",
                workdir=analysis,
                command=["gmxflow", "interaction-energy", "--project", str(config_path)],
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
                command=["gmxflow", "sasa", "--project", str(config_path)],
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
    thermodynamic_outputs = [
        analysis / "em_potential.xvg",
        analysis / "nvt_temperature.xvg",
        analysis / "npt_pressure.xvg",
        analysis / "npt_density.xvg",
    ]
    final_analysis_inputs.extend(thermodynamic_outputs)
    plot_inputs.extend(thermodynamic_outputs)
    plot_outputs.extend(
        [
            analysis / "em_potential.png",
            analysis / "nvt_temperature.png",
            analysis / "npt_pressure.png",
            analysis / "npt_density.png",
        ]
    )
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
                command=["gmxflow", "plot-analysis", "--project", str(config_path)],
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
                command=["gmxflow", "report", "--project", str(config_path)],
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
    location = resolve_forcefield(force_field_name, project_root)
    if location is None or location.gmxlib is None:
        return {}
    return {"GMXLIB": str(location.gmxlib)}


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
