from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence as SequenceABC
from dataclasses import dataclass, field
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


@dataclass
class PipelineCommandStep:
    """Workflow ``Step`` adapter that preserves a legacy command step."""

    id: str
    name: str
    command: tuple[str, ...]
    workdir: Path
    inputs: tuple[Artifact, ...]
    outputs: tuple[Artifact, ...]
    stdin: str | None
    env: Mapping[str, str]
    state: Mapping[str, object]
    parallel: bool = False
    version: str = "1"

    @classmethod
    def from_pipeline_step(cls, step: PipelineStep) -> PipelineCommandStep:
        """Adapt one existing pipeline step without changing its command."""
        return cls(
            id=step.name,
            name=step.description,
            command=tuple(step.command),
            workdir=step.workdir,
            inputs=tuple(_path_artifact(path) for path in step.inputs),
            outputs=tuple(_path_artifact(path) for path in step.outputs),
            stdin=step.stdin,
            env=MappingProxyType(dict(step.env)),
            state=MappingProxyType(dict(step.state)),
        )

    def run(self, context: RunContext) -> None:
        for artifact in self.inputs:
            context.input_path(artifact)
        for artifact in self.outputs:
            context.output_path(artifact)
        context.run_command(
            self.command,
            cwd=self.workdir,
            env=self.env,
            stdin=self.stdin,
        )


def _path_artifact(path: Path) -> Artifact:
    resolved_path = path.expanduser().resolve()
    return Artifact(key=str(resolved_path), kind=resolved_path.suffix.lstrip(".") or "file")


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
    version: str
    state: Mapping[str, object]

    def run(self, context: RunContext) -> None: ...


@dataclass(frozen=True)
class CommandResult:
    """Captured result of one command started through ``RunContext``."""

    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    elapsed_seconds: float


class RunContext(Protocol):
    """Capabilities available to a step while the executor runs it."""

    project_root: Path

    def input_path(self, artifact: Artifact) -> Path: ...

    def output_path(self, artifact: Artifact) -> Path: ...

    def run_command(
        self,
        argv: SequenceABC[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | None = None,
    ) -> CommandResult: ...


@dataclass
class GromacsCommandStep:
    """Shared command execution mechanics for concrete workflow steps."""

    id: str
    name: str
    command: tuple[str, ...]
    workdir: Path
    input_paths: tuple[Path, ...]
    output_paths: tuple[Path, ...]
    inputs: tuple[Artifact, ...] = field(init=False)
    outputs: tuple[Artifact, ...] = field(init=False)
    stdin: str | None = None
    env: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    state: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))
    parallel: bool = False
    version: str = "1"

    def __post_init__(self) -> None:
        self.inputs = tuple(_path_artifact(path) for path in self.input_paths)
        self.outputs = tuple(_path_artifact(path) for path in self.output_paths)

    def run(self, context: RunContext) -> None:
        for artifact in self.inputs:
            context.input_path(artifact)
        for artifact in self.outputs:
            context.output_path(artifact)
        context.run_command(
            self.command,
            cwd=self.workdir,
            env=self.env,
            stdin=self.stdin,
        )

    def to_pipeline_step(self) -> PipelineStep:
        """Project this typed step into the legacy CLI pipeline definition."""
        return PipelineStep(
            name=self.id,
            description=self.name,
            workdir=self.workdir,
            command=list(self.command),
            inputs=list(self.input_paths),
            outputs=list(self.output_paths),
            stdin=self.stdin,
            env=dict(self.env),
            state=dict(self.state),
        )


@dataclass
class PrepareComplexStep(GromacsCommandStep):
    """Prepare receptor and optional ligand coordinates from project inputs."""

    @classmethod
    def from_config(
        cls, config: GmxFlowConfig, project_root: Path, config_path: Path
    ) -> PrepareComplexStep:
        root = project_root.expanduser().resolve()
        prep = root / "work" / "prep"
        inputs = [_resolve_from_config(config.input.receptor_pdb, root)]
        outputs = [prep / "receptor_fixed.pdb", prep / "complexo.pdb"]
        if config.input.remove_resnames:
            outputs.insert(0, prep / "receptor_filtered.pdb")
        if config.input.ligand_kind != "none":
            inputs.append(_resolve_from_config(config.input.ligand_pdb, root))
            outputs.insert(1, prep / "ligante_fixed.pdb")
        return cls(
            id="prepare",
            name=(
                "Preparar proteína sem ligante."
                if config.input.ligand_kind == "none"
                else "Preparar complexo receptor-ligante."
            ),
            command=(
                "gmxflow",
                "prepare-complex",
                "--project",
                str(config_path.expanduser().resolve()),
                "--force",
            ),
            workdir=prep,
            input_paths=tuple(inputs),
            output_paths=tuple(outputs),
            state={
                "input.ph": config.input.ph,
                "input.ligand_kind": config.input.ligand_kind,
                "input.ligand_resname": config.input.ligand_resname,
                "input.remove_resnames": config.input.remove_resnames,
                "force_field.name": config.force_field.name,
            },
        )


@dataclass
class LigandTopologyStep(GromacsCommandStep):
    """Convert CGenFF ligand inputs to GROMACS topology files."""

    @classmethod
    def from_config(
        cls, config: GmxFlowConfig, project_root: Path, config_path: Path
    ) -> LigandTopologyStep:
        root = project_root.expanduser().resolve()
        ligand_dir = root / "work" / "ligand"
        prefix = config.input.ligand_resname.lower()
        return cls(
            id="ligand-topology",
            name="Converter topologia CGenFF do ligante para GROMACS.",
            command=(
                "gmxflow",
                "prepare-ligand",
                "--project",
                str(config_path.expanduser().resolve()),
            ),
            workdir=ligand_dir,
            input_paths=(
                _resolve_from_config(config.input.ligand_mol2, root),
                _resolve_from_config(config.input.ligand_str, root),
            ),
            output_paths=(
                ligand_dir / f"{prefix}.itp",
                ligand_dir / f"{prefix}.prm",
                ligand_dir / f"{prefix}.top",
                ligand_dir / f"{prefix}_ini.pdb",
            ),
            state={
                "input.ligand_resname": config.input.ligand_resname,
                "force_field.name": config.force_field.name,
            },
        )


@dataclass
class ProteinTopologyStep(GromacsCommandStep):
    """Build the protein-only topology for a small-molecule workflow."""

    @classmethod
    def from_config(
        cls, config: GmxFlowConfig, project_root: Path
    ) -> ProteinTopologyStep:
        root = project_root.expanduser().resolve()
        topo = root / "work" / "topo"
        return cls(
            id="protein-topology",
            name="Gerar topologia da proteína com pdb2gmx.",
            command=(
                _gmx_command(config),
                "pdb2gmx",
                "-f",
                str(root / "work" / "prep" / "receptor_fixed.pdb"),
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
            ),
            workdir=topo,
            input_paths=(root / "work" / "prep" / "receptor_fixed.pdb",),
            output_paths=(topo / "protein.gro", topo / "topol.top"),
            stdin=_terminal_selection_stdin(config, chains=1),
            env=_gromacs_env(config.force_field.name, root),
        )


@dataclass
class AssembleComplexStep(GromacsCommandStep):
    """Assemble protein and ligand while preserving the protein topology."""

    @classmethod
    def from_config(
        cls, config: GmxFlowConfig, project_root: Path, config_path: Path
    ) -> AssembleComplexStep:
        root = project_root.expanduser().resolve()
        topo = root / "work" / "topo"
        ligand_dir = root / "work" / "ligand"
        prefix = config.input.ligand_resname.lower()
        return cls(
            id="assemble-complex",
            name="Montar complexo proteína-ligante pequeno.",
            command=(
                "gmxflow",
                "assemble-complex",
                "--project",
                str(config_path.expanduser().resolve()),
                "--topology-output",
                str(topo / "topol_complex.top"),
            ),
            workdir=topo,
            input_paths=(
                topo / "protein.gro",
                topo / "topol.top",
                ligand_dir / f"{prefix}.itp",
                ligand_dir / f"{prefix}.prm",
                ligand_dir / f"{prefix}_ini.pdb",
            ),
            output_paths=(
                topo / "complexo.gro",
                topo / "topol_complex.top",
                topo / ".small_molecule_complex.ok",
            ),
            state={
                "input.ligand_resname": config.input.ligand_resname,
                "solvent.positive_ion": config.solvent.positive_ion,
                "solvent.negative_ion": config.solvent.negative_ion,
            },
        )


@dataclass
class CreateBoxStep(GromacsCommandStep):
    """Create the periodic simulation box around the prepared complex."""

    @classmethod
    def from_config(
        cls, config: GmxFlowConfig, project_root: Path
    ) -> CreateBoxStep:
        root = project_root.expanduser().resolve()
        topo = root / "work" / "topo"
        box = root / "work" / "box"
        return cls(
            id="box",
            name="Criar caixa de simulação.",
            command=(
                _gmx_command(config),
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
            ),
            workdir=box,
            input_paths=(topo / "complexo.gro",),
            output_paths=(box / "box.gro",),
            env=_gromacs_env(config.force_field.name, root),
        )


@dataclass
class SolvateSystemStep(GromacsCommandStep):
    """Add solvent while preserving the input topology as a separate file."""

    @classmethod
    def from_config(
        cls, config: GmxFlowConfig, project_root: Path, config_path: Path
    ) -> SolvateSystemStep:
        root = project_root.expanduser().resolve()
        resolved_config = config_path.expanduser().resolve()
        topo = root / "work" / "topo"
        box = root / "work" / "box"
        input_topology = (
            topo / "topol_complex.top"
            if config.input.ligand_kind == "small_molecule"
            else topo / "topol.top"
        )
        output_topology = topo / "topol_solvated.top"
        return cls(
            id="solvate",
            name="Adicionar solvente.",
            command=(
                "gmxflow",
                "solvate-system",
                "--project",
                str(resolved_config),
                "--topology-input",
                str(input_topology),
                "--topology-output",
                str(output_topology),
            ),
            workdir=box,
            input_paths=(box / "box.gro", input_topology),
            output_paths=(box / "solv.gro", output_topology),
            env=_gromacs_env(config.force_field.name, root),
            state={
                "solvent.water_structure": config.solvent.water_structure,
                "solvent.positive_ion": config.solvent.positive_ion,
                "solvent.negative_ion": config.solvent.negative_ion,
                "solvent.salt_concentration_m": config.solvent.salt_concentration_m,
                "solvent.neutralize": config.solvent.neutralize,
            },
        )


@dataclass
class PrepareIonsStep(GromacsCommandStep):
    """Generate the binary input required by GROMACS genion."""

    @classmethod
    def from_config(
        cls, config: GmxFlowConfig, project_root: Path
    ) -> PrepareIonsStep:
        root = project_root.expanduser().resolve()
        box = root / "work" / "box"
        topology = root / "work" / "topo" / "topol_solvated.top"
        gmx = _gmx_command(config)
        return cls(
            id="ions-grompp",
            name="Preparar entrada binária para adição de íons.",
            command=(
                gmx,
                "grompp",
                "-f",
                "ions.mdp",
                "-c",
                "solv.gro",
                "-p",
                str(topology),
                "-o",
                "ions.tpr",
            ),
            workdir=box,
            input_paths=(box / "ions.mdp", box / "solv.gro", topology),
            output_paths=(box / "ions.tpr", box / "mdout.mdp"),
            env=_gromacs_env(config.force_field.name, root),
        )


@dataclass
class AddIonsStep(GromacsCommandStep):
    """Add ions to the solvated system using the generated GROMACS input."""

    @classmethod
    def from_config(
        cls, config: GmxFlowConfig, project_root: Path, config_path: Path
    ) -> AddIonsStep:
        root = project_root.expanduser().resolve()
        resolved_config = config_path.expanduser().resolve()
        box = root / "work" / "box"
        input_topology = root / "work" / "topo" / "topol_solvated.top"
        output_topology = root / "work" / "topo" / "topol_ions.top"
        return cls(
            id="ions",
            name="Adicionar íons e neutralizar o sistema.",
            command=(
                "gmxflow",
                "genion-system",
                "--project",
                str(resolved_config),
                "--topology-input",
                str(input_topology),
                "--topology-output",
                str(output_topology),
            ),
            workdir=box,
            input_paths=(box / "ions.tpr", input_topology),
            output_paths=(box / "ions.gro", output_topology),
            env=_gromacs_env(config.force_field.name, root),
        )


@dataclass
class PrepareEnergyMinimizationStep(GromacsCommandStep):
    """Prepare the GROMACS run input for energy minimization."""

    @classmethod
    def from_config(
        cls, config: GmxFlowConfig, project_root: Path
    ) -> PrepareEnergyMinimizationStep:
        root = project_root.expanduser().resolve()
        em = root / "work" / "em"
        box = root / "work" / "box"
        topology = root / "work" / "topo" / "topol_ions.top"
        return cls(
            id="em-grompp",
            name="Preparar minimização de energia.",
            command=(
                _gmx_command(config),
                "grompp",
                "-f",
                "em.mdp",
                "-c",
                str(box / "ions.gro"),
                "-p",
                str(topology),
                "-o",
                "em.tpr",
            ),
            workdir=em,
            input_paths=(em / "em.mdp", box / "ions.gro", topology),
            output_paths=(em / "em.tpr", em / "mdout.mdp"),
            env=_gromacs_env(config.force_field.name, root),
        )


@dataclass
class EnergyMinimizationStep(GromacsCommandStep):
    """Run the configured GROMACS energy-minimization job."""

    @classmethod
    def from_config(
        cls, config: GmxFlowConfig, project_root: Path
    ) -> EnergyMinimizationStep:
        root = project_root.expanduser().resolve()
        em = root / "work" / "em"
        return cls(
            id="em",
            name="Executar minimização de energia.",
            command=tuple(
                _mdrun_command(config, _gmx_command(config), "em")
            ),
            workdir=em,
            input_paths=(em / "em.tpr",),
            output_paths=(
                em / "em.gro",
                em / "em.edr",
                em / "em.log",
                em / "em.trr",
            ),
            env=_gromacs_env(config.force_field.name, root),
        )


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
    """Validated dependency graph consumed by the workflow executor."""

    steps: Mapping[str, Step]
    dependencies: Mapping[str, frozenset[str]]
    producers: Mapping[str, str | None]
    artifacts: Mapping[str, Artifact]
    project_inputs: frozenset[str]
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
        artifacts = dict(external_inputs)
        for step in steps.values():
            for artifact in step.outputs:
                if artifact.key in producers:
                    raise ValueError(
                        f"Artefato {artifact.key!r} tem mais de uma origem "
                        "ou também foi declarado como entrada do projeto"
                    )
                producers[artifact.key] = step.id
                artifacts[artifact.key] = artifact

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
            artifacts=MappingProxyType(artifacts),
            project_inputs=frozenset(external_inputs),
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
    if not isinstance(step.version, str) or not step.version.strip():
        raise ValueError(f"Step {step.id!r}: version deve ser uma string não vazia")
    if not isinstance(step.state, Mapping):
        raise ValueError(f"Step {step.id!r}: state deve ser um mapeamento")
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
    ionized_topology = topo / "topol_ions.top"
    em = work_dir / "em"
    nvt = work_dir / "nvt"
    npt = work_dir / "npt"
    prod = work_dir / "prod"
    analysis = work_dir / "analysis"
    outputs = project_root / "outputs"
    prepare_step = PrepareComplexStep.from_config(config, project_root, config_path)
    steps = [prepare_step.to_pipeline_step()]

    if config.input.ligand_kind == "small_molecule":
        typed_steps: tuple[GromacsCommandStep, ...] = (
            LigandTopologyStep.from_config(config, project_root, config_path),
            ProteinTopologyStep.from_config(config, project_root),
            AssembleComplexStep.from_config(config, project_root, config_path),
        )
        steps.extend(step.to_pipeline_step() for step in typed_steps)
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
            CreateBoxStep.from_config(config, project_root).to_pipeline_step(),
            SolvateSystemStep.from_config(
                config, project_root, config_path
            ).to_pipeline_step(),
            PrepareIonsStep.from_config(config, project_root).to_pipeline_step(),
            AddIonsStep.from_config(
                config, project_root, config_path
            ).to_pipeline_step(),
            PrepareEnergyMinimizationStep.from_config(
                config, project_root
            ).to_pipeline_step(),
            EnergyMinimizationStep.from_config(
                config, project_root
            ).to_pipeline_step(),
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
                    str(ionized_topology),
                    "-o",
                    "nvt.tpr",
                ],
                inputs=[nvt / "nvt.mdp", em / "em.gro", ionized_topology],
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
                    str(ionized_topology),
                    "-o",
                    "npt.tpr",
                ],
                inputs=[
                    npt / "npt.mdp",
                    nvt / "nvt.gro",
                    nvt / "nvt.cpt",
                    ionized_topology,
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
                    str(ionized_topology),
                    "-o",
                    "md.tpr",
                ],
                inputs=[
                    prod / "md.mdp",
                    npt / "npt.gro",
                    npt / "npt.cpt",
                    ionized_topology,
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
                    ionized_topology,
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
                    outputs / "figures",
                    outputs / "data",
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


def build_workflow(
    config: GmxFlowConfig,
    config_dir: Path,
    *,
    config_path: Path | None = None,
    selected_steps: list[PipelineStep] | None = None,
) -> Sequence:
    """Compose an API workflow from concrete steps and temporary legacy adapters.

    The CLI continues to consume ``build_pipeline()``. The API reuses concrete
    step implementations where available and adapts only steps not migrated yet.
    """
    root = config_dir.expanduser().resolve()
    resolved_config = (config_path or root / "project.toml").expanduser().resolve()
    plan = (
        build_pipeline(config, root, config_path=resolved_config)
        if selected_steps is None
        else selected_steps
    )

    concrete_steps: list[GromacsCommandStep] = [
        PrepareComplexStep.from_config(config, root, resolved_config)
    ]
    if config.input.ligand_kind == "small_molecule":
        concrete_steps.extend(
            [
                LigandTopologyStep.from_config(config, root, resolved_config),
                ProteinTopologyStep.from_config(config, root),
                AssembleComplexStep.from_config(config, root, resolved_config),
            ]
        )
    concrete_steps.extend(
        [
            CreateBoxStep.from_config(config, root),
            SolvateSystemStep.from_config(config, root, resolved_config),
            PrepareIonsStep.from_config(config, root),
            AddIonsStep.from_config(config, root, resolved_config),
            PrepareEnergyMinimizationStep.from_config(config, root),
            EnergyMinimizationStep.from_config(config, root),
        ]
    )
    by_id = {step.id: step for step in concrete_steps}
    workflow_steps: list[Step] = []
    for pipeline_step in plan:
        concrete = by_id.get(pipeline_step.name)
        if concrete is None:
            workflow_steps.append(
                PipelineCommandStep.from_pipeline_step(pipeline_step)
            )
            continue
        if concrete.to_pipeline_step() != pipeline_step:
            raise ValueError(
                f"A definição tipada da etapa {pipeline_step.name!r} "
                "diverge do plano legado."
            )
        workflow_steps.append(concrete)
    return Sequence(*workflow_steps)


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
