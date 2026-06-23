# Tutorial: Protein-Ligand Complex

Este tutorial mostra como usar o `gmxflow` em um fluxo proteína-ligante pequeno inspirado no tutorial **Protein-Ligand Complex** de Justin A. Lemkul para GROMACS.

Referência original:

- <http://www.mdtutorials.com/gmx/complex/>

O objetivo aqui não é copiar o tutorial original, mas oferecer uma ponte para usuários que já reconhecem esse fluxo manual como padrão: preparar proteína, parametrizar ligante com CGenFF, montar o complexo, solvatar, adicionar íons, minimizar, equilibrar, produzir trajetória e analisar.

## Público-Alvo

Este tutorial é para usuários que:

- já têm GROMACS instalado;
- querem simular uma proteína com molécula pequena;
- têm ou conseguem gerar `.mol2` e `.str` do ligante via CGenFF/ParamChem/SilcsBio;
- querem validar rapidamente a pipeline antes de fazer uma simulação longa.

## Pré-Requisitos

Ative o ambiente onde GROMACS, Open Babel e `gmxflow` estão instalados:

```sh
micromamba activate gmx_compile
gmxflow --help
```

Também são necessários:

- GROMACS acessível como `gmx`;
- Open Babel, se precisar converter o ligante para `.mol2`;
- force field CHARMM/CGenFF em uma pasta `.ff`;
- arquivos `.mol2` e `.str` compatíveis para o ligante.

Para instalar GROMACS com suporte a CUDA/NVIDIA, veja:

- [Como instalar GROMACS com CUDA usando Micromamba](../how-to/install-gromacs-cuda.md)

O force field usado no exemplo é baixado do site do MacKerell Lab:

- <https://mackerell.umaryland.edu/charmm_ff.shtml#gromacs>

Na seção **CHARMM36 Files for GROMACS**, baixe `charmm36-feb2026_cgenff-5.0.ff.tgz` e extraia na raiz do exemplo:

```sh
cd examples/protein_ligand_complex
wget https://mackerell.umaryland.edu/download.php?filename=CHARMM_ff_params_files/charmm36-feb2026_cgenff-5.0.ff.tgz -O charmm36-feb2026_cgenff-5.0.ff.tgz
tar -xzf charmm36-feb2026_cgenff-5.0.ff.tgz
```

O diretório extraído deve se chamar:

```text
charmm36-feb2026_cgenff-5.0.ff/
```

e o `config.toml` deve usar:

```toml
[force_field]
name = "charmm36-feb2026_cgenff-5.0"
```

## Exemplo Disponível

O exemplo fica em:

```text
examples/protein_ligand_complex/
```

Arquivos centrais:

```text
config.toml
README.md
inputs/3HTB.pdb
inputs/JZ4.pdb
inputs/JZ4.mol2
inputs/JZ4.str
charmm36-feb2026_cgenff-5.0.ff/
```

O diretório do force field local é ignorado pelo Git no exemplo. Para publicar ou compartilhar o projeto, prefira documentar como obtê-lo em vez de versionar uma cópia completa.

O PDB do receptor pode vir de uma estrutura cristalográfica que ainda contém o ligante. Quando `ligand_kind = "small_molecule"`, o `gmxflow` remove do receptor os átomos cujo resname corresponde a `input.ligand_resname` antes da etapa `protein-topology`. Isso evita o erro do `pdb2gmx` em que uma cadeia mistura resíduos de tipo `Protein` e `Other`.

## Rodar O Fluxo Curto

Valide a configuração:

```sh
gmxflow validate --config examples/protein_ligand_complex/config.toml
```

Inspecione o plano detalhado sem executar GROMACS:

```sh
gmxflow run --config examples/protein_ligand_complex/config.toml --dry-run --strict-inputs
```

Execute a pipeline:

```sh
gmxflow run --config examples/protein_ligand_complex/config.toml
```

Abra o relatório:

```text
examples/protein_ligand_complex/outputs/report.html
```

## Como O `gmxflow` Traduz O Fluxo Manual

| Conceito do tutorial manual | Implementação no `gmxflow` |
| --- | --- |
| Preparar coordenadas de proteína e ligante | `prepare` |
| Converter parâmetros CGenFF | `prepare-ligand` / `ligand-topology` |
| Gerar topologia da proteína | `protein-topology` |
| Combinar proteína e ligante | `assemble-complex` |
| Definir caixa | `box` |
| Solvatar | `solvate` |
| Adicionar íons | `ions-grompp` e `ions` |
| Minimizar energia | `em-grompp` e `em` |
| Equilibrar em NVT | `nvt-grompp` e `nvt` |
| Equilibrar em NPT | `npt-grompp` e `npt` |
| Rodar produção | `production-grompp` e `production` |
| Corrigir PBC e alinhar trajetória | `pbc-nojump`, `pbc-center`, `fit` |
| Calcular métricas e figuras | `analysis`, `plots`, `report` |

## Pontos Críticos E Soluções

### Compatibilidade entre `.mol2`, `.str` e `ligand_resname`

O `input.ligand_resname` precisa corresponder ao `RESI` do `.str`. A lista de átomos do `.mol2` precisa bater com os comandos `ATOM` do `.str`.

Se falhar:

```text
RESI incompatível
lista de átomos incompatível
contagem de átomos divergente
```

Resolva gerando novamente o `.mol2` e o `.str` a partir da mesma estrutura e mantendo nomes de átomos/resíduo consistentes.

Se o CGenFF By SilcsBio recusar o upload com:

```text
The uploaded Mol2 file cannot be processed by the CGenFF engine. Please try a different molecule. See the log file for more information
```

o `.mol2` provavelmente foi gerado a partir de um PDB sem informação química suficiente. Primeiro tente:

```sh
obabel inputs/JZ4.pdb -O inputs/JZ4.mol2 -h --partialcharge gasteiger
```

Se continuar falhando, use o SDF ideal do RCSB para gerar o `.mol2` de parametrização:

```sh
wget https://files.rcsb.org/ligands/download/JZ4_ideal.sdf -O inputs/JZ4_ideal.sdf
obabel inputs/JZ4_ideal.sdf -O inputs/JZ4.mol2 -h --partialcharge gasteiger
```

Mantenha `ligand_pdb = "inputs/JZ4.pdb"` para preservar a pose simulada, e use o `.mol2` gerado do SDF para CGenFF e para `ligand_mol2`.

### Penalties CGenFF

Penalties altos indicam parâmetros menos confiáveis. O `gmxflow` avisa, mas não impede a execução.

Para produção científica:

- revise protonação, tautômero e carga do ligante;
- confira se a pose 3D é a desejada;
- valide ou refine parâmetros críticos;
- documente penalties e decisões no relatório do projeto.

### Force Field Local

Para este exemplo:

```toml
[force_field]
name = "charmm36-feb2026_cgenff-5.0"
water = "tip3p"
```

A pasta esperada é:

```text
examples/protein_ligand_complex/charmm36-feb2026_cgenff-5.0.ff/
```

Se a pasta tiver outro nome, ajuste `force_field.name`. Se o GROMACS não encontrar o force field, confira o nome da pasta e se ela está ao lado do `config.toml`.

Também confira a compatibilidade entre a versão CGenFF do force field e a versão usada para gerar o `.str` do ligante. O exemplo usa CGenFF 5.0.

### Seleção De Terminais No `pdb2gmx`

Com CHARMM, o `pdb2gmx -ter` pode listar opções como:

```text
Select start terminus type for MET-1
 0: MET1
 1: NH3+
...
Select end terminus type for ASN-163
 0: COO-
```

Para este exemplo, a escolha correta é `NH3+` no N-terminal e `COO-` no C-terminal. Se a opção `MET1` for escolhida por engano, o GROMACS pode falhar com:

```text
Fatal error:
atom C1 not found in buiding block 1MET while combining tdb and rtp
```

O exemplo deixa essa escolha explícita no `config.toml`:

```toml
[pdb2gmx]
terminal_selections = ["1", "0"]
```

Esses valores são enviados em ordem para os prompts do `pdb2gmx -ter`. Para uma proteína com uma cadeia, são dois valores: N-terminal e C-terminal. Para duas cadeias, informe quatro valores, por exemplo:

```toml
terminal_selections = ["1", "0", "1", "0"]
```

Se a lista estiver vazia, o `gmxflow` usa uma política automática: para force fields `charmm*`, seleciona `1, 0` por cadeia; para os demais, seleciona `0, 0` por cadeia. Em sistemas fora do padrão, prefira preencher `terminal_selections` explicitamente depois de conferir as opções mostradas pelo `pdb2gmx`.

### Perfil `smoke`

O exemplo usa:

```toml
[simulation]
profile = "smoke"
```

Esse perfil é para testar rapidamente a pipeline. Para uma simulação real, altere para:

```toml
profile = "standard"
```

Depois revise os `.mdp`, duração de produção, equilíbrios e parâmetros físicos antes de interpretar resultados.

### Reexecução E Estado

O `gmxflow` usa `work/state.json` para registrar comandos, entradas e fingerprints. Se uma etapa continua válida, ela pode ser pulada.

Use:

```sh
gmxflow run --config examples/protein_ligand_complex/config.toml --from-step ligand-topology
```

quando quiser refazer a partir de uma etapa específica.

Use:

```sh
gmxflow clean --config examples/protein_ligand_complex/config.toml
```

quando quiser limpar artefatos regeneráveis preservando templates `.mdp`.

## Saídas

Depois da execução completa:

```text
work/analysis/*.xvg
work/analysis/*.png
outputs/summary.json
outputs/summary.txt
outputs/report.html
outputs/figures/
outputs/data/
outputs/logs/
```

Compartilhe preferencialmente `outputs/report.html` junto com `outputs/figures/`, `outputs/data/` e `outputs/logs/`.

## Próximos Passos

Depois que este exemplo rodar em `smoke`:

1. Troque para `profile = "standard"`.
2. Revise a preparação química do ligante.
3. Revise protonação e estados de histidina da proteína.
4. Aumente o tempo de produção.
5. Ative análises opcionais se fizerem sentido:

```toml
[analysis]
interaction_energy = true
sasa = true
catalytic_residues = ""
```

Para resíduos catalíticos:

```sh
gmxflow run --config examples/protein_ligand_complex/config.toml --until prepare
gmxflow list-residues --config examples/protein_ligand_complex/config.toml --chain A --resnames HIS,ASP,SER
```
