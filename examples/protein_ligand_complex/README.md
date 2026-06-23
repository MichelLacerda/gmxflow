# Protein-Ligand Complex

Exemplo de complexo proteína-ligante pequeno para o `gmxflow`, estruturado para seguir a lógica do tutorial clássico **Protein-Ligand Complex** de Justin A. Lemkul para GROMACS.

Referência original:

- <http://www.mdtutorials.com/gmx/complex/>

Este exemplo não substitui o tutorial original e não copia suas instruções. A intenção é oferecer a mesma rota mental conhecida pela comunidade, mas usando a CLI `gmxflow` para automatizar preparação, execução, análises, figuras e relatório.

## Objetivo

Rodar um fluxo curto de validação para o complexo T4 lysozyme L99A com o ligante JZ4, usando CHARMM36/CGenFF e topologia do ligante gerada externamente.

O perfil padrão deste exemplo é `smoke`. Ele executa poucos passos e serve para validar instalação, arquivos de entrada, topologia, comandos e relatório. Não use resultados `smoke` para interpretação científica.

## Arquivos Esperados

Este diretório já aponta para:

```text
inputs/3HTB.pdb
inputs/JZ4.pdb
inputs/JZ4.mol2
inputs/JZ4.str
charmm36-feb2026_cgenff-5.0.ff/
```

Os arquivos `JZ4.mol2`, `JZ4.str` e o diretório `.ff` não devem ser tratados como artefatos universais do `gmxflow`. Eles dependem do fluxo CHARMM/CGenFF usado pelo usuário.

Antes de rodar a pipeline completa, confirme:

- `inputs/3HTB.pdb`: estrutura do receptor;
- `inputs/JZ4.pdb`: pose 3D do ligante;
- `inputs/JZ4.mol2`: ligante enviado/compatível com CGenFF;
- `inputs/JZ4.str`: stream file produzido por CGenFF/ParamChem/SilcsBio;
- `charmm36-feb2026_cgenff-5.0.ff/`: force field CHARMM/CGenFF local.

`inputs/3HTB.pdb` pode ser um PDB cristalográfico completo contendo o JZ4. Para `ligand_kind = "small_molecule"`, o `gmxflow` remove do receptor os registros com `resname = ligand_resname` antes de chamar `gmx pdb2gmx`, evitando que o GROMACS tente tratar o ligante como parte da cadeia proteica.

### Baixar O CHARMM36/CGenFF Para GROMACS

Baixe o force field no site do MacKerell Lab:

- <https://mackerell.umaryland.edu/charmm_ff.shtml#gromacs>

Na seção **CHARMM36 Files for GROMACS**, use o pacote:

```text
charmm36-feb2026_cgenff-5.0.ff.tgz
```

Por linha de comando:

```sh
cd examples/protein_ligand_complex
wget https://mackerell.umaryland.edu/download.php?filename=CHARMM_ff_params_files/charmm36-feb2026_cgenff-5.0.ff.tgz -O charmm36-feb2026_cgenff-5.0.ff.tgz
tar -xzf charmm36-feb2026_cgenff-5.0.ff.tgz
```

Depois da extração, a pasta esperada é:

```text
charmm36-feb2026_cgenff-5.0.ff/
```

Esse nome precisa bater com:

```toml
[force_field]
name = "charmm36-feb2026_cgenff-5.0"
```

Se você baixar outra variante, como LJPME ou CGenFF 4.6, ajuste `force_field.name` e garanta que o `.str` do ligante foi gerado com uma versão compatível de CGenFF.

Com CHARMM, a escolha de terminais no `pdb2gmx -ter` é crítica. Este exemplo define explicitamente:

```toml
[pdb2gmx]
terminal_selections = ["1", "0"]
```

Isso seleciona `NH3+` no N-terminal e `COO-` no C-terminal. Se o GROMACS escolher `MET1` no N-terminal, a etapa pode falhar com `atom C1 not found in buiding block 1MET`; isso indica seleção de terminal incorreta para este caso.

### Gerar O `.mol2`

Para gerar o `.mol2` a partir da pose 3D do ligante, use Open Babel:

```sh
obabel inputs/JZ4.pdb -O inputs/JZ4.mol2
```

Não use `--gen3d` se `JZ4.pdb` já representa a pose no sítio de ligação. `--gen3d` é útil quando a entrada é 2D, por exemplo:

```sh
obabel inputs/JZ4.sdf -O inputs/JZ4.mol2 --gen3d
```

Use o mesmo `inputs/JZ4.mol2` para gerar o `.str` em CGenFF/ParamChem/SilcsBio e para rodar `gmxflow prepare-ligand`.

Se o CGenFF By SilcsBio recusar o `.mol2` com a mensagem:

```text
The uploaded Mol2 file cannot be processed by the CGenFF engine. Please try a different molecule. See the log file for more information
```

o problema costuma ser conectividade ou química inferida incorretamente a partir do PDB. Primeiro tente:

```sh
obabel inputs/JZ4.pdb -O inputs/JZ4.mol2 -h --partialcharge gasteiger
```

Se ainda falhar, gere o `.mol2` a partir do SDF ideal do RCSB Chemical Component Dictionary:

```sh
wget https://files.rcsb.org/ligands/download/JZ4_ideal.sdf -O inputs/JZ4_ideal.sdf
obabel inputs/JZ4_ideal.sdf -O inputs/JZ4.mol2 -h --partialcharge gasteiger
```

Esse `.mol2` é usado para parametrização no CGenFF. A pose simulada continua vindo de `inputs/JZ4.pdb`, configurada em `ligand_pdb`.

## Configuração Principal

O `config.toml` usa:

```toml
[input]
receptor_pdb = "inputs/3HTB.pdb"
ligand_pdb = "inputs/JZ4.pdb"
ligand_kind = "small_molecule"
ligand_mol2 = "inputs/JZ4.mol2"
ligand_str = "inputs/JZ4.str"
ligand_resname = "JZ4"

[force_field]
name = "charmm36-feb2026_cgenff-5.0"
water = "tip3p"
```

Quando o force field `.ff` fica na raiz do projeto, o `gmxflow` define `GMXLIB` durante as etapas GROMACS para que `pdb2gmx` encontre esse force field local.

## Fluxo Rápido

Na raiz do repositório:

```sh
gmxflow validate --config examples/protein_ligand_complex/config.toml
gmxflow run --config examples/protein_ligand_complex/config.toml --dry-run --strict-inputs
gmxflow run --config examples/protein_ligand_complex/config.toml
```

Para rodar de dentro deste diretório:

```sh
gmxflow validate --config config.toml
gmxflow run --config config.toml --dry-run --strict-inputs
gmxflow run --config config.toml
```

O relatório final fica em:

```text
outputs/report.html
outputs/summary.txt
outputs/summary.json
outputs/figures/
outputs/data/
outputs/logs/
```

## Equivalência Com O Fluxo Lemkul

| Fluxo manual reconhecido | Etapa no `gmxflow` |
| --- | --- |
| Preparar PDBs de proteína e ligante | `prepare` |
| Converter topologia CGenFF do ligante | `ligand-topology` / `gmxflow prepare-ligand` |
| Gerar topologia da proteína com `pdb2gmx` | `protein-topology` |
| Montar complexo proteína-ligante | `assemble-complex` |
| Criar caixa | `box` |
| Solvatar | `solvate` |
| Adicionar íons | `ions-grompp` e `ions` |
| Minimização | `em-grompp` e `em` |
| Equilíbrio NVT | `nvt-grompp` e `nvt` |
| Equilíbrio NPT | `npt-grompp` e `npt` |
| Produção MD | `production-grompp` e `production` |
| Correções PBC e alinhamento | `pbc-nojump`, `pbc-center`, `fit` |
| Análises e gráficos | `analysis`, `plots`, `report` |

## Pontos Críticos

### 1. O `.mol2` e o `.str` precisam representar o mesmo ligante

O `prepare-ligand` compara `inputs/JZ4.mol2` com `inputs/JZ4.str`. Os nomes e a quantidade de átomos precisam bater.

Sintomas comuns:

- erro indicando diferença entre átomos do `.mol2` e do `.str`;
- `RESI` do `.str` diferente de `ligand_resname`;
- PDB gerado pelo conversor com contagem de átomos inesperada.

Correção:

- gere o `.mol2` a partir da mesma estrutura usada para CGenFF;
- mantenha o resname do ligante como `JZ4`;
- confirme que o `RESI` no `.str` é `JZ4`;
- não edite nomes de átomos manualmente sem repetir a parametrização.

### 2. Penalties CGenFF altos exigem revisão química

O `gmxflow` emite aviso quando encontra penalties altos no `.str`. Isso não impede a execução, mas indica que parâmetros podem ser pouco confiáveis.

Correção:

- revise o ligante no CGenFF/ParamChem/SilcsBio;
- confira protonação, tautômero e carga formal;
- para produção científica, valide parâmetros ou consulte literatura/parametrização especializada.

### 3. O force field precisa estar visível para o GROMACS

Este exemplo espera uma pasta:

```text
charmm36-feb2026_cgenff-5.0.ff/
```

e o `config.toml` usa:

```toml
name = "charmm36-feb2026_cgenff-5.0"
```

Correção:

- se sua pasta `.ff` tiver outro nome, ajuste `force_field.name`;
- mantenha a pasta `.ff` ao lado do `config.toml`;
- se usar uma instalação global do GROMACS, garanta que o force field também esteja em um caminho reconhecido pelo GROMACS.

### 4. `profile = "smoke"` não é simulação interpretável

O perfil `smoke` reduz NVT, NPT e produção para poucos passos. Ele existe para testar o fluxo.

Correção:

- use `smoke` para validar instalação e topologia;
- mude para `profile = "standard"` apenas depois que o fluxo curto funcionar;
- revise os `.mdp` e parâmetros científicos antes de uma simulação real.

### 5. Reexecuções usam `work/state.json`

O `gmxflow` registra estado e fingerprints em `work/state.json`. Se entradas, comando, ambiente ou estado declarado não mudarem, etapas já concluídas podem ser puladas.

Correção:

- após mudar arquivos de entrada, rode normalmente; o estado deve detectar mudanças rastreadas;
- se quiser forçar reexecução parcial, use `--from-step`;
- se estiver em dúvida, use `gmxflow clean --config config.toml` para remover artefatos regeneráveis preservando templates.

## Comandos Úteis

Validar:

```sh
gmxflow validate --config config.toml
```

Dry-run estrito:

```sh
gmxflow run --config config.toml --dry-run --strict-inputs
```

Preparar apenas ligante:

```sh
gmxflow prepare-ligand --config config.toml
```

Rodar até montagem do complexo:

```sh
gmxflow run --config config.toml --until assemble-complex
```

Rodar pipeline completa:

```sh
gmxflow run --config config.toml
```

Regenerar relatório a partir de análises existentes:

```sh
gmxflow report --config config.toml
```

Limpar artefatos regeneráveis:

```sh
gmxflow clean --config config.toml
```

## Próximo Passo

Depois que o perfil `smoke` funcionar, duplique este diretório para um novo projeto, substitua entradas e topologia do ligante, ajuste `ligand_resname`, revise o force field e só então aumente a duração da simulação.
