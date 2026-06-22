from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from gmxflow.config import GmxFlowConfig, default_config, to_toml

PROJECT_DIRS = (
    "inputs",
    "outputs",
    "work",
)

TEMPLATE_NAMES = (
    "ions.mdp.j2",
    "em.mdp.j2",
    "nvt.mdp.j2",
    "npt.mdp.j2",
    "md.mdp.j2",
)

INITIAL_TEMPLATE_OUTPUTS = {
    "ions.mdp.j2": Path("work/box/ions.mdp"),
    "em.mdp.j2": Path("work/em/em.mdp"),
    "nvt.mdp.j2": Path("work/nvt/nvt.mdp"),
    "npt.mdp.j2": Path("work/npt/npt.mdp"),
    "md.mdp.j2": Path("work/prod/md.mdp"),
}

WORK_DIRS = (
    "work/prep",
    "work/topo",
    "work/box",
    "work/em",
    "work/nvt",
    "work/npt",
    "work/prod",
    "work/analysis",
    "work/logs",
)


def create_project(
    name: str,
    destination: Path,
    force: bool = False,
    receptor: str | None = None,
    ligand: str | None = None,
    ligand_kind: str = "peptide",
    gpu: str = "auto",
    profile: str = "standard",
) -> Path:
    project_dir = destination / name
    if project_dir.exists() and not force:
        raise FileExistsError(f"O diretório já existe: {project_dir}")

    project_dir.mkdir(parents=True, exist_ok=True)
    for directory in PROJECT_DIRS:
        (project_dir / directory).mkdir(exist_ok=True)
    for directory in WORK_DIRS:
        (project_dir / directory).mkdir(parents=True, exist_ok=True)

    config = default_config(name)
    if receptor:
        config.input.receptor_pdb = receptor
    if ligand:
        config.input.ligand_pdb = ligand
    config.input.ligand_kind = _validate_choice(
        ligand_kind,
        allowed={"peptide", "small_molecule"},
        field_name="ligand_kind",
    )
    config.mdrun.gpu = _validate_choice(
        gpu,
        allowed={"auto", "off", "force"},
        field_name="gpu",
    )
    config.simulation.profile = _validate_choice(
        profile,
        allowed={"standard", "smoke"},
        field_name="profile",
    )

    _write_text(project_dir / "config.toml", to_toml(config), force)
    _write_text(project_dir / "README.md", _render_readme(config), force)
    _write_text(project_dir / ".gitignore", _render_gitignore(), force)

    env = _template_env()
    for template_name, relative_output in INITIAL_TEMPLATE_OUTPUTS.items():
        rendered = env.get_template(template_name).render(config=config)
        _write_text(project_dir / relative_output, rendered, force)

    _write_text(project_dir / "inputs" / ".gitkeep", "", force)

    return project_dir


def render_template(name: str, config: GmxFlowConfig) -> str:
    return _template_env().get_template(name).render(config=config)


def available_templates() -> list[str]:
    template_root = files("gmxflow").joinpath("templates")
    return sorted(path.name for path in template_root.iterdir() if path.name.endswith(".j2"))
    return sorted(
        path.name for path in template_root.iterdir() if path.name.endswith(".j2")
    )

def _validate_choice(value: str, allowed: set[str], field_name: str) -> str:
    normalized = value.strip()
    if normalized not in allowed:
        choices = ", ".join(sorted(allowed))
        raise ValueError(f"{field_name} inválido: {value}. Valores aceitos: {choices}")
    return normalized


def _template_env() -> Environment:
    return Environment(
        loader=PackageLoader("gmxflow", "templates"),
        autoescape=select_autoescape(enabled_extensions=()),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _render_readme(config: GmxFlowConfig) -> str:
    return f"""# {config.project.name}

{config.project.description}

Este projeto contém a configuração e a estrutura de diretórios para uma pipeline de dinâmica molecular com GROMACS.

## Como usar

Coloque os arquivos PDB de entrada em `inputs/` e ajuste os caminhos em `config.toml`.

Valide a configuração:

```bash
gmxflow validate --config config.toml
```

Veja o plano resumido:

```bash
gmxflow plan --config config.toml
```

Veja o plano detalhado sem executar GROMACS:

```bash
gmxflow run --config config.toml --dry-run
```

Crie projetos novos com presets iniciais quando necessário:

```bash
gmxflow startproject novo_projeto --ligand-kind small_molecule --profile smoke --gpu off
```

Valores aceitos:

- `--ligand-kind`: `peptide` ou `small_molecule`;
- `--profile`: `standard` ou `smoke`;
- `--gpu`: `auto`, `off` ou `force`.

Prepare o complexo receptor-ligante:

```bash
gmxflow prepare-complex --config config.toml
```

Para ligante pequeno já parametrizado externamente com CGenFF:

```bash
gmxflow prepare-ligand --config config.toml
```

Esse comando gera `work/ligand/<ligand_resname>.itp`, `.prm`, `.top` e `_ini.pdb`. Ele não acessa CGenFF/ParamChem/SilcsBio; esses arquivos externos devem ser obtidos antes e configurados em `input.ligand_mol2` e `input.ligand_str`.

Para gerar `input.ligand_mol2` a partir de uma estrutura de molécula pequena, instale o Open Babel no Ubuntu/Debian:

```bash
sudo apt update
sudo apt install openbabel
```

Preservando uma pose 3D já existente em PDB:

```bash
obabel inputs/ligand.pdb -O inputs/ligand.mol2
```

Se a entrada for 2D ou precisar gerar coordenadas 3D:

```bash
obabel inputs/ligand.sdf -O inputs/ligand.mol2 --gen3d
```

O `.mol2` e o `.str` devem representar o mesmo ligante e a mesma lista de átomos. O nome/resname usado no `.mol2` e o `RESI` do `.str` devem ser compatíveis com `input.ligand_resname`. O `prepare-ligand` valida a lista de átomos entre `.mol2` e `.str`, confere a contagem do PDB gerado e emite aviso para penalties CGenFF altos no `.str`.

Execute a pipeline até a preparação, com logs:

```bash
gmxflow run --config config.toml --until prepare
```

Limpe artefatos regeneráveis preservando os `.mdp`:

```bash
gmxflow clean --config config.toml
```

Renderize novamente os arquivos `.mdp` finais:

```bash
gmxflow render-templates --config config.toml --force
```

Gere novamente o relatório consolidado em `outputs/`:

```bash
gmxflow report --config config.toml
```

Para também conferir se os PDBs configurados existem:

```bash
gmxflow run --config config.toml --dry-run --strict-inputs
```

## Estrutura do projeto

```text
.
├── config.toml
├── .gitignore
├── inputs/
├── outputs/
└── work/
    ├── prep/
    ├── topo/
    ├── box/
    │   └── ions.mdp
    ├── em/
    │   └── em.mdp
    ├── nvt/
    │   └── nvt.mdp
    ├── npt/
    │   └── npt.mdp
    ├── prod/
    │   └── md.mdp
    ├── analysis/
    └── logs/
```

- `config.toml`: configuração principal da simulação.
- `inputs/`: arquivos PDB de entrada.
- `work/`: arquivos intermediários da pipeline.
- `outputs/`: resultados finais e relatórios.
- `.gitignore`: ignora `work/`, `outputs/`, caches Python e ambientes locais.

O diretório raiz do projeto é a pasta onde está este `config.toml`. Por padrão, os arquivos intermediários e os `.mdp` renderizados ficam em `work/`.

Após `gmxflow prepare-complex`, a pasta `work/prep/` deve conter:

- `receptor_fixed.pdb`;
- `ligante_fixed.pdb`;
- `complexo.pdb`.

Após `gmxflow run --until prepare`, os logs devem ficar em:

- `work/logs/00_workspace.log`;
- `work/logs/01_prepare.log`.

`gmxflow clean --config config.toml` remove artefatos regeneráveis em `work/` e preserva os `.mdp`. Use `--templates` para remover também os `.mdp`, ou `--all-work` para recriar `work/` vazio.

Os arquivos `.mdp` finais já são criados pelo `startproject` e ficam em `work/`. Eles podem ser recriados com `gmxflow render-templates --force`:

- `work/box/ions.mdp`;
- `work/em/em.mdp`;
- `work/nvt/nvt.mdp`;
- `work/npt/npt.mdp`;
- `work/prod/md.mdp`.

Como `work/` e `outputs/` são artefatos regeneráveis, eles são ignorados pelo Git no `.gitignore` gerado. A pasta `inputs/` recebe um `.gitkeep` para permitir versionar a estrutura inicial sem obrigar arquivos de entrada reais.

## Configuração

### `[project]`

- `name`: nome lógico deste experimento.
- `description`: descrição curta do objetivo da simulação.

### `# [paths]`

Este bloco vem comentado por padrão e ainda não altera o comportamento da CLI.

Ele documenta um uso avançado futuro: redirecionar arquivos pesados para outro disco, SSD externo ou diretório scratch em HPC. Enquanto as linhas estiverem comentadas, a raiz do projeto continua sendo a pasta do `config.toml`.

### `[input]`

- `receptor_pdb`: caminho do PDB do receptor. Pode ser relativo ao `config.toml` ou absoluto.
- `ligand_pdb`: caminho do PDB do ligante. Pode ser relativo ao `config.toml` ou absoluto.
- `ligand_kind`: tipo do ligante. Use `peptide` para ligante peptídico ou `small_molecule` para molécula pequena com topologia externa CGenFF.
- `ligand_mol2`: arquivo `.mol2` do ligante pequeno, usado quando `ligand_kind = "small_molecule"`.
- `ligand_str`: arquivo `.str` gerado externamente por CGenFF/ParamChem/SilcsBio.
- `ligand_resname`: resname do ligante pequeno no `.str`, por exemplo `BEN` ou `LIG`.
- `ph`: pH usado na preparação do complexo.

Quando `ligand_kind = "small_molecule"`, o `gmxflow run` inclui as etapas `ligand-topology`, `protein-topology` e `assemble-complex`. A parametrização CGenFF ainda precisa ser feita fora do `gmxflow`; a CLI consome o `.mol2` e o `.str` já obtidos.

### `[force_field]`

- `name`: campo de força usado pelo `gmx pdb2gmx`, por exemplo `amber99sb-ildn`.
- `water`: modelo de água, por exemplo `tip3p`.

Para CHARMM/CGenFF com ligante pequeno, uma pasta `.ff` pode ficar na raiz do projeto. Exemplo:

```text
charmm36-feb2026_cgenff-5.0.ff/
config.toml
```

Nesse caso, use `name = "charmm36-feb2026_cgenff-5.0"`.

### `[box]`

- `type`: tipo de caixa usado no `gmx editconf`, por exemplo `dodecahedron`.
- `distance_nm`: distância mínima entre o complexo e a borda da caixa, em nanômetros.

### `[solvent]`

- `water_structure`: estrutura de água usada pelo `gmx solvate`, como `spc216.gro`.
- `salt_concentration_m`: concentração de sal em mol/L.
- `positive_ion`: nome do íon positivo usado pelo `gmx genion`.
- `negative_ion`: nome do íon negativo usado pelo `gmx genion`.
- `neutralize`: se `true`, adiciona `-neutral` ao `gmx genion`.

### `[simulation]`

- `profile`: `standard` para uso normal ou `smoke` para testes muito curtos da ferramenta.
- `temperature_k`: temperatura em Kelvin.
- `pressure_bar`: pressão em bar.
- `dt_ps`: passo de integração em ps.
- `production_ns`: duração da produção em ns.
- `nvt_ps`: duração do equilíbrio NVT em ps.
- `npt_ps`: duração do equilíbrio NPT em ps.

Com `dt_ps = 0.002`, uma produção de `100 ns` gera `50.000.000` passos.

Com `profile = "smoke"`, NVT, NPT e produção usam apenas 10 passos. Esse perfil serve para testar a ferramenta e os logs, não para produzir resultados científicos.

### `[mdrun]`

- `engine`: `auto`, `gmx` ou `gmx_mpi`.
- `gpu`: `auto`, `off` ou `force`.
- `gpu_id`: ID da GPU quando `gpu = "force"`.
- `ntomp`: número de threads OpenMP.
- `pin`: política de pinning. `auto` deixa o GROMACS decidir.

### `[analysis]`

- `ligand_chain`: cadeia do ligante no PDB preparado.
- `fit_group`: grupo usado para alinhamento da trajetória.
- `center_group`: grupo usado para centralização.
- `output_group`: grupo exportado no `trjconv`.
- `contact_cutoff_nm`: cutoff para contatos receptor-ligante, em nanômetros.
- `interaction_energy`: se `true`, calcula energia Coulomb/Lennard-Jones receptor-ligante por `gmx mdrun -rerun` e adiciona ao relatório. O rerun força `-nb cpu`, porque múltiplos energy groups não são suportados em GPU pelo GROMACS.
- `sasa`: se `true`, calcula SASA/BSA aproximado receptor-ligante com `gmx sasa` e adiciona ao relatório.
- `catalytic_residues`: resíduos catalíticos usados para calcular distância mínima e ocupação contra o ligante. Aceita valores como `"57,102,195"` ou `"HIS57,ASP102,SER195"`.
- `catalytic_distance_cutoff_nm`: cutoff usado para ocupação/contatos da tríade catalítica, em nanômetros.

Para descobrir os números dos resíduos no complexo preparado:

```sh
gmxflow run --config config.toml --until prepare
gmxflow list-residues --config config.toml --chain A --resnames HIS,ASP,SER
```

O comando imprime uma tabela e uma linha pronta para copiar para o `config.toml`.

### `[plots]`

- `receptor_color`: cor usada para séries do receptor. O padrão é azul.
- `ligand_color`: cor usada para séries do ligante. O padrão é vermelho cereja.
- `band_window`: janela da média móvel usada na banda tipo Bollinger.
- `band_std`: multiplicador do desvio padrão na banda.
- `raw_alpha`: opacidade dos valores crus da série.
- `band_alpha`: opacidade da banda.
"""


def _render_gitignore() -> str:
    return """# Artefatos regeneráveis da pipeline
work/
outputs/

# Caches Python
__pycache__/
*.py[cod]
.pytest_cache/
.ruff_cache/

# Ambientes locais
.venv/
venv/

# Arquivos temporários de sistema/editor
.DS_Store
Thumbs.db
*.swp
"""


def _write_text(path: Path, content: str, force: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"O arquivo já existe: {path}")
    path.write_text(content, encoding="utf-8")
