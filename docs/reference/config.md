# Referência Do config.toml

Exemplo gerado pelo `startproject`:

```toml
[project]
name = "example"
description = "Simulação de dinâmica molecular com GROMACS"

# [paths]
# Uso avançado: por padrão, o gmxflow usa a pasta onde está o config.toml
# como raiz do projeto. Os arquivos intermediários ficam em ./work e os
# resultados finais ficam em ./outputs. Futuramente estes campos poderão
# redirecionar dados pesados para outro disco, SSD externo ou scratch de HPC.
# work_dir = "work"
# output_dir = "outputs"

[input]
receptor_pdb = "inputs/receptor.pdb"
ligand_pdb = "inputs/ligante.pdb"
ligand_kind = "peptide"
ligand_mol2 = ""
ligand_str = ""
ligand_resname = "LIG"
ph = 7.4

[force_field]
name = "amber99sb-ildn"
water = "tip3p"

[box]
type = "dodecahedron"
distance_nm = 1.2

[solvent]
water_structure = "spc216.gro"
salt_concentration_m = 0.15
positive_ion = "NA"
negative_ion = "CL"
neutralize = true

[simulation]
profile = "standard"
temperature_k = 300
pressure_bar = 1.0
dt_ps = 0.002
production_ns = 100
nvt_ps = 100
npt_ps = 100

[mdrun]
engine = "auto"
gpu = "auto"
gpu_id = "0"
ntomp = 8
pin = "auto"

[pdb2gmx]
terminal_selections = []

[analysis]
ligand_chain = "B"
fit_group = "Backbone"
center_group = "Protein"
output_group = "System"
contact_cutoff_nm = 0.4
interaction_energy = false
sasa = false
catalytic_residues = ""
catalytic_distance_cutoff_nm = 0.4

[plots]
receptor_color = "#1f77b4"
ligand_color = "#C2185B"
band_window = 25
band_std = 2.0
raw_alpha = 0.18
band_alpha = 0.22
```

## Significado das configurações

### `[project]`

- `name`: nome lógico do experimento.
- `description`: descrição curta do objetivo da simulação.

### `# [paths]`

Bloco comentado. Ele existe apenas como documentação de uso avançado futuro.

A ideia é permitir, mais adiante, redirecionar arquivos pesados para outro local, por exemplo:

- disco externo;
- SSD rápido;
- diretório scratch em HPC;
- partição com mais espaço.

Enquanto estiver comentado, não tem efeito.

### `[input]`

- `receptor_pdb`: caminho do PDB do receptor, relativo ao `config.toml` ou absoluto.
- `ligand_pdb`: caminho do PDB do ligante, relativo ao `config.toml` ou absoluto.
- `ligand_kind`: tipo do ligante. Use `peptide` para ligante peptídico ou `small_molecule` para molécula pequena com topologia externa CGenFF.
- `ligand_mol2`: arquivo `.mol2` enviado ao CGenFF/ParamChem/SilcsBio, usado por `prepare-ligand`.
- `ligand_str`: arquivo `.str` produzido externamente pelo CGenFF/ParamChem/SilcsBio, usado por `prepare-ligand`.
- `ligand_resname`: resname do ligante no `.str`, por exemplo `JZ4` ou `LIG`.
- `ph`: pH usado na preparação do complexo.

### `[force_field]`

- `name`: campo de força passado ao `gmx pdb2gmx`, por exemplo `amber99sb-ildn`.
- `water`: modelo de água passado ao `gmx pdb2gmx`, por exemplo `tip3p`.

Para `small_molecule` com CHARMM/CGenFF, o force field `.ff` pode ficar na raiz do projeto, por exemplo:

```text
example/
  charmm36-feb2026_cgenff-5.0.ff/
  config.toml
```

Nesse caso, configure:

```toml
[force_field]
name = "charmm36-feb2026_cgenff-5.0"
water = "tip3p"
```

### `[box]`

- `type`: tipo de caixa para `gmx editconf`, por exemplo `dodecahedron`.
- `distance_nm`: distância mínima entre o soluto e a borda da caixa, em nm.

### `[solvent]`

- `water_structure`: estrutura de água usada por `gmx solvate`, como `spc216.gro`.
- `salt_concentration_m`: concentração de sal em mol/L.
- `positive_ion`: nome do íon positivo para `gmx genion`.
- `negative_ion`: nome do íon negativo para `gmx genion`.
- `neutralize`: se `true`, adiciona `-neutral` ao `gmx genion`.

### `[simulation]`

- `profile`: `standard` para uso normal ou `smoke` para testes muito curtos da ferramenta.
- `temperature_k`: temperatura em Kelvin.
- `pressure_bar`: pressão em bar.
- `dt_ps`: passo de integração em ps.
- `production_ns`: duração da produção em ns.
- `nvt_ps`: duração do equilíbrio NVT em ps.
- `npt_ps`: duração do equilíbrio NPT em ps.

Com `dt_ps = 0.002`, uma produção de `100 ns` gera:

```text
50.000.000 passos
```

Com `profile = "smoke"`, NVT, NPT e produção usam 10 passos. Esse perfil existe para validar executor, logs e integração, não para gerar uma simulação interpretável.

### `[mdrun]`

- `engine`: `auto`, `gmx` ou `gmx_mpi`.
- `gpu`: `auto`, `off` ou `force`.
- `gpu_id`: ID da GPU quando `gpu = "force"`.
- `ntomp`: número de threads OpenMP.
- `pin`: política de pinning. `auto` deixa o GROMACS decidir.

### `[pdb2gmx]`

- `terminal_selections`: respostas enviadas aos prompts do `gmx pdb2gmx -ter`.

Quando vazio, o `gmxflow` usa uma política automática simples: `1,0` por cadeia para force fields `charmm*`, e `0,0` por cadeia para os demais. Para sistemas fora do padrão, preencha explicitamente após conferir as opções mostradas pelo `pdb2gmx`.

Exemplo para uma cadeia CHARMM com N-terminal `NH3+` e C-terminal `COO-`:

```toml
[pdb2gmx]
terminal_selections = ["1", "0"]
```

### `[analysis]`

- `ligand_chain`: cadeia do ligante no PDB preparado.
- `fit_group`: grupo usado para alinhamento da trajetória.
- `center_group`: grupo usado para centralização.
- `output_group`: grupo exportado no `trjconv`.
- `contact_cutoff_nm`: cutoff para contatos receptor-ligante.
- `interaction_energy`: se `true`, calcula energia Coulomb/Lennard-Jones receptor-ligante por `gmx mdrun -rerun` e adiciona o resumo ao relatório. Depende dos grupos `Receptor` e `Ligante` criados em `work/analysis/lig.ndx`. O rerun força `-nb cpu`, porque múltiplos energy groups não são suportados em GPU pelo GROMACS.
- `sasa`: se `true`, calcula SASA/BSA aproximado receptor-ligante com `gmx sasa` e adiciona o resumo ao relatório.
- `catalytic_residues`: resíduos catalíticos para calcular distância mínima e ocupação contra o ligante. Aceita números ou rótulos com números, por exemplo `"57,102,195"` ou `"HIS57,ASP102,SER195"`. Quando preenchido, a pipeline gera `catalytic_distance.xvg`, `catalytic_occupancy.xvg` e os gráficos correspondentes.
- `catalytic_distance_cutoff_nm`: cutoff usado para contar ocupação/contatos da tríade catalítica.

Para descobrir os números dos resíduos no complexo preparado:

```sh
gmxflow run --config config.toml --until prepare
gmxflow list-residues --config config.toml --chain A --resnames HIS,ASP,SER
```

O comando imprime uma tabela e uma linha pronta para copiar para o `config.toml`, por exemplo:

```toml
catalytic_residues = "57,102,195"
```

### `[plots]`

- `receptor_color`: cor usada para séries do receptor. O padrão é azul.
- `ligand_color`: cor usada para séries do ligante. O padrão é vermelho cereja.
- `band_window`: janela da média móvel usada na banda tipo Bollinger dos gráficos de série temporal.
- `band_std`: multiplicador do desvio padrão na banda.
- `raw_alpha`: opacidade dos valores crus da série.
- `band_alpha`: opacidade da banda.

Com exceção de `rmsf.png` e `catalytic_occupancy.png`, os gráficos individuais usam valores crus em baixa opacidade, média móvel opaca e banda de desvio padrão. O gráfico `sasa_complexo.png` compara SASA do receptor e SASA do ligante no mesmo eixo. O gráfico `catalytic_occupancy.png` resume a ocupação média da tríade catalítica como barra com desvio padrão.
