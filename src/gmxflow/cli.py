from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from gmxflow.analysis import run_analysis, run_interaction_energy, run_sasa_analysis
from gmxflow.config import load_config
from gmxflow.executor import run_steps, run_workspace_setup, select_steps
from gmxflow.ligand import prepare_ligand as prepare_ligand_files
from gmxflow.pipeline import PipelineStep, build_pipeline
from gmxflow.preparation import prepare_complex as prepare_complex_files
from gmxflow.project import available_templates, create_project
from gmxflow.report import generate_report
from gmxflow.runner import print_dry_run
from gmxflow.small_molecule import assemble_small_molecule_complex
from gmxflow.topology import reset_molecules_section
from gmxflow.workspace import clean_workspace, ensure_workspace, render_templates

app = typer.Typer(
    help="CLI para preparar, executar e analisar pipelines de dinâmica molecular com GROMACS."
)
console = Console()
ALLOWED_REAL_STEPS = {
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
    "pbc-nojump",
    "pbc-center",
    "fit",
    "analysis",
    "interaction-energy",
    "sasa",
    "plots",
    "report",
}


@dataclass(frozen=True)
class ResidueInfo:
    chain: str
    number: int
    name: str
    atom_count: int


@app.command()
def startproject(
    name: Annotated[str, typer.Argument(help="Nome do projeto a ser criado.")],
    destination: Annotated[
        Path,
        typer.Option(
            "--destination",
            "-d",
            help="Diretório onde o projeto será criado.",
        ),
    ] = Path.cwd(),
    receptor: Annotated[
        str | None,
        typer.Option("--receptor", help="Caminho inicial do PDB do receptor."),
    ] = None,
    ligand: Annotated[
        str | None,
        typer.Option("--ligand", help="Caminho inicial do PDB do ligante."),
    ] = None,
    ligand_kind: Annotated[
        str,
        typer.Option(
            "--ligand-kind",
            help="Tipo de ligante inicial: peptide ou small_molecule.",
        ),
    ] = "peptide",
    gpu: Annotated[
        str,
        typer.Option(
            "--gpu",
            help="Uso de GPU no mdrun: auto, off ou force.",
        ),
    ] = "auto",
    profile: Annotated[
        str,
        typer.Option(
            "--profile",
            help="Perfil de simulação inicial: standard ou smoke.",
        ),
    ] = "standard",
    force: Annotated[
        bool,
        typer.Option("--force", help="Permite sobrescrever arquivos gerados."),
    ] = False,
) -> None:
    """Cria uma estrutura inicial de projeto, inspirado no startproject do Django."""
    try:
        project_dir = create_project(
            name=name,
            destination=destination,
            force=force,
            receptor=receptor,
            ligand=ligand,
            ligand_kind=ligand_kind,
            gpu=gpu,
            profile=profile,
        )
    except (FileExistsError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error

    console.print(f"Projeto criado em: [bold]{project_dir}[/bold]")


@app.command()
def validate(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Arquivo TOML da pipeline."),
    ] = Path("config.toml"),
) -> None:
    """Valida o arquivo de configuração TOML."""
    loaded = load_config(config)
    console.print(f"Configuração válida: [bold]{config.name}[/bold]")
    console.print(f"Caminho: {config}")
    console.print(f"Projeto: {loaded.project.name}")
    console.print(f"Passos de produção: {loaded.simulation.production_steps}")


@app.command("list-residues")
def list_residues(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Arquivo TOML da pipeline."),
    ] = Path("config.toml"),
    chain: Annotated[
        str | None,
        typer.Option("--chain", help="Filtra por cadeia, por exemplo A."),
    ] = None,
    resnames: Annotated[
        str | None,
        typer.Option(
            "--resnames",
            help="Filtra nomes de resíduos separados por vírgula, por exemplo HIS,ASP,SER.",
        ),
    ] = None,
) -> None:
    """Lista resíduos do complexo preparado e ajuda a preencher catalytic_residues."""
    config_path = config.expanduser().resolve()
    pdb_path = config_path.parent / "work" / "prep" / "complexo.pdb"
    if not pdb_path.is_file():
        raise typer.BadParameter(
            f"Complexo preparado não encontrado: {pdb_path}. "
            "Rode primeiro: gmxflow run --config config.toml --until prepare"
        )

    residues = _read_pdb_residues(pdb_path)
    if chain is not None:
        residues = [residue for residue in residues if residue.chain == chain.strip()]
    wanted_resnames = _parse_resnames_filter(resnames)
    if wanted_resnames:
        residues = [
            residue for residue in residues if residue.name.upper() in wanted_resnames
        ]
    if not residues:
        raise typer.BadParameter("Nenhum resíduo encontrado com os filtros informados.")

    table = Table(title=f"Resíduos em {pdb_path}")
    table.add_column("Cadeia")
    table.add_column("Número", justify="right")
    table.add_column("Nome")
    table.add_column("Átomos", justify="right")
    table.add_column("Valor para config")
    for residue in residues:
        table.add_row(
            residue.chain or "-",
            str(residue.number),
            residue.name,
            str(residue.atom_count),
            str(residue.number),
        )
    console.print(table)

    if chain or wanted_resnames:
        values = ",".join(str(residue.number) for residue in residues)
        console.print(f'catalytic_residues = "{values}"')
    if _has_duplicated_residue_numbers(residues):
        console.print(
            "[yellow]Aviso:[/yellow] há números de resíduos repetidos em cadeias diferentes. "
            "Use --chain para evitar seleção ambígua."
        )


@app.command()
def plan(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Arquivo TOML da pipeline."),
    ] = Path("config.toml"),
) -> None:
    """Mostra o plano de execução sem rodar GROMACS."""
    loaded = load_config(config)

    table = Table(title=f"Plano de execução: {loaded.project.name}")
    table.add_column("Etapa")
    table.add_column("Comando principal")
    table.add_column("Saída esperada")

    rows = [
        ("Preparação", "gmxflow prepare-complex", "work/prep/complexo.pdb"),
        ("Topologia", "gmx pdb2gmx", "topo/complexo.gro, topol.top"),
        ("Caixa", "gmx editconf", "box/box.gro"),
        ("Solvatação", "gmx solvate", "box/solv.gro"),
        ("Íons", "gmx genion", "box/ions.gro"),
        ("Minimização", "gmx grompp + gmx mdrun", "em/em.gro"),
        ("NVT", "gmx grompp + gmx mdrun", "nvt/nvt.gro"),
        ("NPT", "gmx grompp + gmx mdrun", "npt/npt.gro"),
        ("Produção", "gmx grompp + gmx mdrun", "prod/md.xtc"),
        ("Pós-processamento", "gmx trjconv", "prod/md_fit.xtc"),
        ("Análises", "gmx rms/rmsf/gyrate/mindist/hbond", "analysis/*.xvg"),
        ("Figuras", "gmxflow plot-analysis", "analysis/*.png"),
        ("Relatório", "gmxflow report", "outputs/report.html"),
    ]
    for row in rows:
        table.add_row(*row)

    console.print(table)


@app.command()
def templates() -> None:
    """Lista os templates Jinja2 distribuídos com a CLI."""
    for template in available_templates():
        console.print(template)


@app.command("render-templates")
def render_templates_command(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Arquivo TOML da pipeline."),
    ] = Path("config.toml"),
    force: Annotated[
        bool,
        typer.Option(
            "--force", help="Permite sobrescrever arquivos .mdp renderizados."
        ),
    ] = False,
) -> None:
    """Renderiza os templates .mdp para work/ sem executar GROMACS."""
    loaded = load_config(config)
    config_path = config.expanduser().resolve()

    try:
        rendered = render_templates(
            config=loaded,
            project_root=config_path.parent,
            force=force,
        )
    except FileExistsError as error:
        raise typer.BadParameter(str(error)) from error

    for item in rendered:
        console.print(f"Template renderizado: [bold]{item.output_path}[/bold]")


@app.command("setup-workspace")
def setup_workspace(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Arquivo TOML da pipeline."),
    ] = Path("config.toml"),
) -> None:
    """Garante work/ e renderiza apenas templates .mdp ausentes."""
    loaded = load_config(config)
    config_path = config.expanduser().resolve()
    setup = ensure_workspace(config=loaded, project_root=config_path.parent)

    console.print(f"Workspace preparado: [bold]{setup.work_root}[/bold]")
    for directory in setup.directories:
        console.print(f"Diretório garantido: {directory}")
    for item in setup.rendered_templates:
        console.print(f"Template renderizado: [bold]{item.output_path}[/bold]")
    for path in setup.existing_templates:
        console.print(f"Template existente: {path}")


@app.command("clean")
def clean(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Arquivo TOML da pipeline."),
    ] = Path("config.toml"),
    templates: Annotated[
        bool,
        typer.Option("--templates", help="Remove também os .mdp renderizados."),
    ] = False,
    all_work: Annotated[
        bool,
        typer.Option(
            "--all-work", help="Remove todo work/ e recria diretórios vazios."
        ),
    ] = False,
) -> None:
    """Remove artefatos regeneráveis de work/."""
    load_config(config)
    config_path = config.expanduser().resolve()
    result = clean_workspace(
        project_root=config_path.parent,
        remove_templates=templates,
        all_work=all_work,
    )

    console.print(f"Workspace limpo: [bold]{result.work_root}[/bold]")
    for path in result.removed_paths:
        console.print(f"Removido: {path}")
    for path in result.preserved_paths:
        console.print(f"Preservado: {path}")
    if not result.removed_paths:
        console.print("Nenhum artefato para remover.")


@app.command("prepare-complex")
def prepare_complex(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Arquivo TOML da pipeline."),
    ] = Path("config.toml"),
    force: Annotated[
        bool,
        typer.Option("--force", help="Permite sobrescrever arquivos de preparação."),
    ] = False,
) -> None:
    """Prepara receptor, ligante e complexo dentro de work/prep."""
    loaded = load_config(config)
    config_path = config.expanduser().resolve()
    project_root = config_path.parent
    output_dir = project_root / "work" / "prep"
    receptor_pdb = _resolve_project_path(loaded.input.receptor_pdb, project_root)
    ligand_pdb = _resolve_project_path(loaded.input.ligand_pdb, project_root)

    try:
        result = prepare_complex_files(
            receptor_pdb=receptor_pdb,
            ligand_pdb=ligand_pdb,
            output_dir=output_dir,
            ph=loaded.input.ph,
            force_field_name=loaded.force_field.name,
            force=force,
        )
    except (FileExistsError, FileNotFoundError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error

    console.print(f"Complexo preparado: [bold]{result.complex_pdb}[/bold]")
    console.print(f"Átomos do receptor: {result.receptor_atoms}")
    console.print(f"Átomos do ligante: {result.ligand_atoms}")
    console.print(f"Histidina: {result.histidine_form}")
    console.print(f"Pontes S-S: {result.disulfide_residues or '-'}")


@app.command("prepare-ligand")
def prepare_ligand(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Arquivo TOML da pipeline."),
    ] = Path("config.toml"),
    force_field_dir: Annotated[
        Path | None,
        typer.Option(
            "--force-field-dir",
            help="Diretório .ff CHARMM usado pelo conversor CGenFF.",
        ),
    ] = None,
) -> None:
    """Converte .mol2 + .str CGenFF para topologia GROMACS do ligante."""
    loaded = load_config(config)
    config_path = config.expanduser().resolve()

    try:
        result = prepare_ligand_files(
            loaded,
            project_root=config_path.parent,
            force_field_dir=force_field_dir,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error

    console.print(f"Ligante preparado: [bold]{result.resname}[/bold]")
    console.print(f"ITP: [bold]{result.itp_path}[/bold]")
    console.print(f"PRM: [bold]{result.prm_path}[/bold]")
    console.print(f"TOP: [bold]{result.top_path}[/bold]")
    console.print(f"PDB: [bold]{result.pdb_path}[/bold]")
    for warning in result.warnings:
        console.print(f"[yellow]Aviso:[/yellow] {warning}")


@app.command("assemble-complex")
def assemble_complex(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Arquivo TOML da pipeline."),
    ] = Path("config.toml"),
) -> None:
    """Monta complexo .gro e topologia para ligante pequeno."""
    loaded = load_config(config)
    config_path = config.expanduser().resolve()

    try:
        result = assemble_small_molecule_complex(
            loaded,
            project_root=config_path.parent,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error

    console.print(f"Complexo montado: [bold]{result.complex_gro}[/bold]")
    console.print(f"Topologia atualizada: [bold]{result.topology}[/bold]")
    console.print(f"Átomos da proteína: {result.protein_atoms}")
    console.print(f"Átomos do ligante: {result.ligand_atoms}")


@app.command("solvate-system")
def solvate_system(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Arquivo TOML da pipeline."),
    ] = Path("config.toml"),
) -> None:
    """Normaliza a topologia e adiciona solvente."""
    loaded = load_config(config)
    config_path = config.expanduser().resolve()
    project_root = config_path.parent
    topol_top = project_root / "work" / "topo" / "topol.top"

    if not topol_top.is_file():
        raise typer.BadParameter(f"Topologia não encontrada: {topol_top}")

    reset_molecules_section(
        topol_top,
        remove_molecules={
            "SOL",
            loaded.solvent.positive_ion,
            loaded.solvent.negative_ion,
        },
    )
    command = [
        _gmx_command(loaded),
        "solvate",
        "-cp",
        "box.gro",
        "-cs",
        loaded.solvent.water_structure,
        "-p",
        str(topol_top),
        "-o",
        "solv.gro",
    ]
    completed = subprocess.run(command, text=True, check=False)
    if completed.returncode != 0:
        raise typer.Exit(code=completed.returncode)


@app.command("analyze")
def analyze(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Arquivo TOML da pipeline."),
    ] = Path("config.toml"),
) -> None:
    """Executa análises principais sobre a trajetória alinhada."""
    loaded = load_config(config)
    config_path = config.expanduser().resolve()

    try:
        results = run_analysis(loaded, project_root=config_path.parent)
    except RuntimeError as error:
        raise typer.BadParameter(str(error)) from error

    for result in results:
        console.print(
            f"Análise concluída: {result.name} -> [bold]{result.output_path}[/bold]"
        )


@app.command("interaction-energy")
def interaction_energy(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Arquivo TOML da pipeline."),
    ] = Path("config.toml"),
) -> None:
    """Calcula energia aproximada de interação receptor-ligante por rerun."""
    loaded = load_config(config)
    config_path = config.expanduser().resolve()

    try:
        results = run_interaction_energy(loaded, project_root=config_path.parent)
    except RuntimeError as error:
        raise typer.BadParameter(str(error)) from error

    for result in results:
        console.print(
            f"Energia de interação concluída: {result.name} -> [bold]{result.output_path}[/bold]"
        )


@app.command("sasa")
def sasa(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Arquivo TOML da pipeline."),
    ] = Path("config.toml"),
) -> None:
    """Calcula SASA e BSA aproximado para receptor-ligante."""
    loaded = load_config(config)
    config_path = config.expanduser().resolve()

    try:
        results = run_sasa_analysis(loaded, project_root=config_path.parent)
    except RuntimeError as error:
        raise typer.BadParameter(str(error)) from error

    for result in results:
        console.print(
            f"SASA concluído: {result.name} -> [bold]{result.output_path}[/bold]"
        )


@app.command("plot-analysis")
def plot_analysis(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Arquivo TOML da pipeline."),
    ] = Path("config.toml"),
) -> None:
    """Gera figuras PNG a partir dos arquivos .xvg de análise."""
    from gmxflow.plots import generate_analysis_plots

    loaded = load_config(config)
    config_path = config.expanduser().resolve()

    results = generate_analysis_plots(loaded, project_root=config_path.parent)
    for result in results:
        console.print(
            f"Figura gerada: {result.name} -> [bold]{result.output_path}[/bold]"
        )


@app.command("report")
def report(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Arquivo TOML da pipeline."),
    ] = Path("config.toml"),
) -> None:
    """Gera relatório consolidado em outputs/."""
    loaded = load_config(config)
    config_path = config.expanduser().resolve()

    result = generate_report(loaded, project_root=config_path.parent)
    console.print(f"Resumo JSON: [bold]{result.summary_json}[/bold]")
    console.print(f"Resumo texto: [bold]{result.summary_txt}[/bold]")
    console.print(f"Relatório HTML: [bold]{result.report_html}[/bold]")


@app.command()
def run(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Arquivo TOML da pipeline."),
    ] = Path("config.toml"),
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run", help="Mostra o plano detalhado sem executar comandos."
        ),
    ] = False,
    strict_inputs: Annotated[
        bool,
        typer.Option(
            "--strict-inputs", help="Falha se os arquivos PDB de entrada não existirem."
        ),
    ] = False,
    from_step: Annotated[
        str | None,
        typer.Option("--from-step", help="Executa a partir de uma etapa específica."),
    ] = None,
    until: Annotated[
        str | None,
        typer.Option("--until", help="Executa até uma etapa específica, inclusive."),
    ] = None,
) -> None:
    """Executa a pipeline ou mostra o plano detalhado em modo dry-run."""
    loaded = load_config(config)

    try:
        config_path = config.expanduser().resolve()
        all_steps = build_pipeline(
            loaded,
            config_dir=config_path.parent,
            config_path=config_path,
            strict_inputs=strict_inputs,
        )
        steps = select_steps(all_steps, from_step=from_step, until=until)
    except (FileNotFoundError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error

    if not dry_run and any(step.name not in ALLOWED_REAL_STEPS for step in steps):
        console.print(
            "Há etapas ainda não liberadas para execução real. Use --dry-run para inspecionar o plano."
        )
        raise typer.Exit(code=2)

    if not dry_run:
        total_steps = len(steps) + 1

        def print_step_start(index: int, step: PipelineStep) -> None:
            console.print(
                f"[{index + 1}/{total_steps} {(index / total_steps) * 100:5.1f}%] "
                f"Iniciando: [bold]{step.name}[/bold]"
            )

        def print_step_done(index: int, result) -> None:
            status = "ignorada" if result.skipped else "concluída"
            console.print(
                f"[{index + 1}/{total_steps} {((index + 1) / total_steps) * 100:5.1f}%] "
                f"Etapa {status}: [bold]{result.step_name}[/bold] "
                f"({result.elapsed_seconds:.2f}s) log={result.log_path}"
            )

        try:
            console.print(
                f"[1/{total_steps} {0.0:5.1f}%] Iniciando: [bold]workspace[/bold]"
            )
            workspace_result = run_workspace_setup(
                loaded, project_root=config_path.parent
            )
            console.print(
                f"[1/{total_steps} {(1 / total_steps) * 100:5.1f}%] "
                f"Etapa concluída: [bold]{workspace_result.step_name}[/bold] "
                f"({workspace_result.elapsed_seconds:.2f}s) log={workspace_result.log_path}"
            )
            results = [workspace_result]
            results.extend(
                run_steps(
                    steps,
                    project_root=config_path.parent,
                    start_index=1,
                    on_step_start=print_step_start,
                    on_step_done=print_step_done,
                )
            )
        except RuntimeError as error:
            raise typer.BadParameter(str(error)) from error
        return

    print_dry_run(steps, console)


def _resolve_project_path(value: str, project_root: Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return project_root / path


def _gmx_command(config) -> str:
    if config.mdrun.engine in {"gmx", "gmx_mpi"}:
        return config.mdrun.engine
    return "gmx"


def _read_pdb_residues(path: Path) -> list[ResidueInfo]:
    atom_counts: dict[tuple[str, int, str], int] = {}
    order: list[tuple[str, int, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith(("ATOM", "HETATM")):
            continue
        chain = line[21:22].strip()
        number = int(line[22:26])
        name = line[17:20].strip()
        key = (chain, number, name)
        if key not in atom_counts:
            atom_counts[key] = 0
            order.append(key)
        atom_counts[key] += 1
    return [
        ResidueInfo(
            chain=chain,
            number=number,
            name=name,
            atom_count=atom_counts[(chain, number, name)],
        )
        for chain, number, name in order
    ]


def _parse_resnames_filter(resnames: str | None) -> set[str]:
    if resnames is None:
        return set()
    return {
        value.strip().upper()
        for value in resnames.replace(";", ",").split(",")
        if value.strip()
    }


def _has_duplicated_residue_numbers(residues: list[ResidueInfo]) -> bool:
    chains_by_number: dict[int, set[str]] = {}
    for residue in residues:
        chains_by_number.setdefault(residue.number, set()).add(residue.chain)
    return any(len(chains) > 1 for chains in chains_by_number.values())
