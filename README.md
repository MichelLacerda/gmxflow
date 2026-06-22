# gmxflow

CLI para preparar, executar e analisar pipelines de dinâmica molecular com GROMACS.

O foco inicial é substituir scripts shell rígidos por uma ferramenta com configuração TOML, geração de projeto, validação, dry-run, execução real, logs e testes automatizados.

## Estado atual

Implementado:

- criação de projeto com `startproject`;
- presets iniciais no `startproject` para tipo de ligante, GPU e perfil de simulação;
- `.gitignore` gerado para evitar commit de `work/` e `outputs/`;
- configuração TOML validada com Pydantic;
- templates `.mdp` com Jinja2;
- setup de workspace com `setup-workspace`;
- `plan` resumido;
- `run --dry-run` detalhado;
- execução real da pipeline GROMACS;
- logs por etapa;
- retomada com `--from-step` e `--until`;
- estado persistente em `work/state.json`, com fingerprints de entradas para pular etapas já válidas;
- análises e figuras em `work/analysis/`;
- relatório consolidado em `outputs/summary.json`, `outputs/summary.txt` e `outputs/report.html`;
- publicação de figuras, séries `.xvg` e logs em `outputs/`;
- análises opcionais de energia de interação por rerun, SASA/BSA e distância/ocupação de resíduos catalíticos;
- comando `list-residues` para ajudar a configurar `analysis.catalytic_residues`;
- fluxo proteína + ligante pequeno com CGenFF externo, topologia do ligante, montagem do complexo, simulação e análises;
- validação opcional de arquivos de entrada com `--strict-inputs`;
- testes automatizados com `pytest`.

Ainda em evolução:

- parametrização automática CGenFF/ParamChem/SilcsBio;
- validação das métricas opcionais em simulações reais completas;
- documentação detalhada do fluxo CGenFF/ParamChem/CHARMM-GUI;
- CI remoto, licença e política de compatibilidade com versões do GROMACS.

## Instalação para desenvolvimento

Na raiz deste projeto:

```sh
uv sync
```

Para rodar a CLI local:

```sh
uv run gmxflow --help
```

## Comandos disponíveis

### Ajuda geral

```sh
uv run gmxflow --help
```

Mostra os comandos disponíveis.

### Criar projeto

```sh
uv run gmxflow startproject example
```

Cria:

```text
example/
  config.toml
  README.md
  .gitignore
  inputs/
    .gitkeep
  outputs/
  work/
    prep/
    topo/
    box/
      ions.mdp
    em/
      em.mdp
    nvt/
      nvt.mdp
    npt/
      npt.mdp
    prod/
      md.mdp
    analysis/
    logs/
```

Também é possível informar arquivos iniciais:

```sh
uv run gmxflow startproject example \
  --receptor inputs/receptor_ph82.pdb \
  --ligand inputs/ligante_ph82.pdb
```

Também é possível criar o projeto já com presets de fluxo:

```sh
uv run gmxflow startproject example \
  --ligand-kind small_molecule \
  --gpu off \
  --profile smoke
```

Valores aceitos:

- `--ligand-kind`: `peptide` ou `small_molecule`;
- `--gpu`: `auto`, `off` ou `force`;
- `--profile`: `standard` ou `smoke`.

Essas opções gravam o `config.toml` inicial. Quando `--profile smoke` é usado, os `.mdp` iniciais também já são renderizados com 10 passos para NVT, NPT e produção.

Para criar em outro diretório:

```sh
uv run gmxflow startproject example --destination ~/projects/examples/
```

Por segurança, arquivos existentes não são sobrescritos. Para permitir sobrescrita:

```sh
uv run gmxflow startproject example --force
```

### Validar configuração

```sh
uv run gmxflow validate --config example/config.toml
```

Valida o TOML e mostra informações derivadas, como número de passos de produção.

### Ver plano resumido

```sh
uv run gmxflow plan --config example/config.toml
```

Mostra uma tabela curta com as etapas principais da pipeline.

### Ver dry-run detalhado

```sh
uv run gmxflow run --config example/config.toml --dry-run
```

Mostra:

- etapa;
- descrição;
- diretório de trabalho;
- comando que seria executado;
- entradas esperadas;
- saídas esperadas;
- `stdin` usado em comandos interativos do GROMACS.

O dry-run não executa `gmx`, não chama `mdrun` e não gera arquivos pesados.

### Preparar complexo

```sh
uv run gmxflow prepare-complex --config example/config.toml
```

Gera em `work/prep/`:

- `receptor_fixed.pdb`;
- `ligante_fixed.pdb`;
- `complexo.pdb`.

Por padrão, não sobrescreve arquivos já existentes. Para permitir sobrescrita:

```sh
uv run gmxflow prepare-complex --config example/config.toml --force
```

### Preparar ligante pequeno com CGenFF

```sh
uv run gmxflow prepare-ligand --config example/config.toml --force-field-dir /caminho/para/charmm36.ff
```

Esse comando usa o conversor `cgenff_charmm2gmx.py` vendorizado em `src/gmxflow/vendor/` para converter arquivos já gerados externamente pelo CGenFF/ParamChem/SilcsBio.

Para obter o `.mol2` de uma molécula pequena a partir de um arquivo estrutural, instale o Open Babel no Ubuntu/Debian:

```sh
sudo apt update
sudo apt install openbabel
```

Verifique a instalação:

```sh
obabel -V
```

Se você já tem a pose 3D do ligante em PDB e quer preservá-la, converta sem gerar novas coordenadas:

```sh
obabel inputs/ligand.pdb -O inputs/ligand.mol2
```

Se a entrada for 2D ou precisar gerar coordenadas 3D, use `--gen3d`:

```sh
obabel inputs/ligand.sdf -O inputs/ligand.mol2 --gen3d
```

O `.mol2` e o `.str` devem representar o mesmo ligante e a mesma lista de átomos. O nome/resname usado no `.mol2` e o `RESI` do `.str` devem ser compatíveis com `input.ligand_resname`.

Antes de chamar o conversor CGenFF, o `prepare-ligand` valida:

- presença de `input.ligand_mol2` e `input.ligand_str`;
- compatibilidade entre `input.ligand_resname` e `RESI` do `.str`;
- lista de átomos do `.mol2` contra os comandos `ATOM` do `.str`;
- contagem de átomos do PDB gerado pelo conversor contra o `.mol2`;
- penalties CGenFF altos no `.str`, emitindo aviso quando encontrar valores a partir de `50`.

Entradas esperadas no `config.toml`:

```toml
[input]
ligand_kind = "small_molecule"
ligand_mol2 = "inputs/ligand.mol2"
ligand_str = "inputs/ligand.str"
ligand_resname = "LIG"
```

Saídas geradas em `work/ligand/`:

```text
<ligand_resname>.itp
<ligand_resname>.prm
<ligand_resname>.top
<ligand_resname>_ini.pdb
```

Observação: este comando não gera os parâmetros CGenFF. Ele consome o `.str` já produzido por ferramenta externa e apenas converte para arquivos utilizáveis pelo GROMACS. O `RESI` do `.str` deve corresponder ao `input.ligand_resname`.

Quando `ligand_kind = "small_molecule"`, o `gmxflow run` inclui as etapas `ligand-topology`, `protein-topology` e `assemble-complex` antes de seguir para caixa, solvatação, íons, minimização, equilíbrios, produção e análises. Se o force field `.ff` estiver na raiz do projeto, o executor define `GMXLIB` para que o GROMACS encontre esse force field local.

Nas análises, ligantes peptídicos ainda são detectados por cadeia (`analysis.ligand_chain`). Para `small_molecule`, o grupo `Ligante` é criado pelo `input.ligand_resname`.

### Preparar workspace

```sh
uv run gmxflow setup-workspace --config example/config.toml
```

Garante a estrutura de `work/` e renderiza somente os `.mdp` ausentes. Arquivos `.mdp` já existentes são preservados.

### Executar até a preparação

```sh
uv run gmxflow run --config example/config.toml --until prepare
```

Esse comando:

- garante a estrutura de `work/`;
- renderiza somente os `.mdp` ausentes;
- executa a preparação do complexo;
- registra logs em `work/logs/`.

Logs esperados:

```text
work/logs/00_workspace.log
work/logs/01_prepare.log
```

### Limpar workspace

```sh
uv run gmxflow clean --config mastoparan_dm/config.toml
```

Remove artefatos regeneráveis em `work/`, preservando os `.mdp` renderizados por padrão. Para remover também os `.mdp`:

```sh
uv run gmxflow clean --config mastoparan_dm/config.toml --templates
```

Para remover todo o `work/` e recriar apenas os diretórios vazios:

```sh
uv run gmxflow clean --config mastoparan_dm/config.toml --all-work
```

### Executar análises

```sh
uv run gmxflow run --config example/config.toml
```

Esse comando executa a pipeline completa: setup de workspace, preparação, solvatação, íons, minimização, equilíbrios NVT/NPT, produção, pós-processamento `gmx trjconv`, análises para gerar `work/analysis/*.xvg`, figuras `work/analysis/*.png` e relatório em `outputs/`. Se uma etapa já tiver todas as saídas esperadas, ela é registrada como ignorada e o fluxo continua.

Análises geradas:

```text
work/analysis/rmsd_backbone.xvg
work/analysis/rmsd_ligante.xvg
work/analysis/rmsf_residuos.xvg
work/analysis/gyrate.xvg
work/analysis/mindist.xvg
work/analysis/numcont.xvg
work/analysis/hbond.xvg
work/analysis/sasa_complexo.xvg
work/analysis/sasa_ligante.xvg
work/analysis/bsa.xvg
work/analysis/catalytic_distance.xvg
work/analysis/catalytic_occupancy.xvg
```

Figuras geradas:

```text
work/analysis/painel_completo.png
work/analysis/rmsd_bb.png
work/analysis/rmsd_lig.png
work/analysis/rmsf.png
work/analysis/rg.png
work/analysis/ncont.png
work/analysis/hbond.png
work/analysis/sasa_complexo.png
work/analysis/sasa_ligante.png
work/analysis/bsa.png
work/analysis/catalytic_distance.png
work/analysis/catalytic_occupancy.png
```

Relatório consolidado:

O comando `gmxflow report` publica um resumo em `outputs/summary.json`, `outputs/summary.txt` e `outputs/report.html`. Esse relatório reúne métricas importantes de dinâmica molecular, sem tentar reproduzir diretamente um score de docking como HADDOCK. A primeira versão usa os dados já gerados em `work/analysis/*.xvg`:

- estabilidade da simulação: RMSD do backbone, RMSD do ligante, RMSF, raio de giro e tempo analisado;
- interação receptor-ligante: distância mínima, número de contatos, pontes de hidrogênio e fração da trajetória com interação;
- resumo executivo com média e desvio padrão das séries principais;
- gráficos já gerados em `work/analysis/*.png`.

Se `analysis.interaction_energy = true`, a pipeline também executa `gmxflow interaction-energy` por `gmx mdrun -rerun`, extrai termos Coulomb/Lennard-Jones receptor-ligante quando disponíveis e adiciona a energia total aproximada ao relatório. Essa métrica é uma análise aproximada do `gmxflow`, não um `HADDOCK score`. Mesmo quando a produção usa GPU, esse rerun é executado com `-nb cpu`, porque o GROMACS não suporta múltiplos energy groups em GPU.

Se `analysis.sasa = true`, a pipeline também executa `gmxflow sasa`, calcula SASA do receptor, SASA do ligante, SASA do complexo e BSA aproximado pela relação:

```text
BSA = SASA receptor + SASA ligante - SASA complexo
```

Evoluções posteriores podem adicionar clustering e um score próprio do `gmxflow`. Esse score deve ser documentado como métrica aproximada da aplicação, não como `HADDOCK score`.

Saídas do relatório:

```text
outputs/summary.json
outputs/summary.txt
outputs/report.html
outputs/figures/*.png
outputs/data/*.xvg
outputs/logs/*.log
```

As figuras, séries numéricas e logs usados pelo relatório são publicados dentro de `outputs/`, permitindo abrir ou compartilhar `outputs/report.html` junto com as pastas `figures/`, `data/` e `logs/` sem depender diretamente de caminhos em `work/`.

Logs esperados:

```text
work/logs/00_workspace.log
work/logs/01_prepare.log
work/logs/02_topology.log
work/logs/03_box.log
work/logs/04_solvate.log
work/logs/05_ions-grompp.log
work/logs/06_ions.log
work/logs/07_em-grompp.log
work/logs/08_em.log
work/logs/09_nvt-grompp.log
work/logs/10_nvt.log
work/logs/11_npt-grompp.log
work/logs/12_npt.log
work/logs/13_production-grompp.log
work/logs/14_production.log
work/logs/15_pbc-nojump.log
work/logs/16_pbc-center.log
work/logs/17_fit.log
work/logs/18_analysis.log
work/logs/19_plots.log
work/logs/20_report.log
```

Quando `analysis.interaction_energy = true`, há uma etapa extra antes dos gráficos; os logs posteriores são deslocados em uma posição e também é gerado `work/logs/19_interaction-energy.log`.

Quando `analysis.sasa = true`, há uma etapa extra antes dos gráficos; os logs posteriores são deslocados em uma posição e também é gerado um log `sasa`.

### Renderizar Templates

```sh
uv run gmxflow render-templates --config example/config.toml
```

Renderiza os arquivos `.mdp` finais em `work/`:

```text
work/box/ions.mdp
work/em/em.mdp
work/nvt/nvt.mdp
work/npt/npt.mdp
work/prod/md.mdp
```

Por padrão, arquivos existentes não são sobrescritos. Para sobrescrever:

```sh
uv run gmxflow render-templates --config example/config.toml --force
```

Observação: projetos criados com `startproject` já nascem com esses `.mdp` em `work/`. Nesse caso, use `--force` quando quiser recriá-los a partir do `config.toml`.

### Dry-run com validação dos PDBs

```sh
uv run gmxflow run --config example/config.toml --dry-run --strict-inputs
```

Com `--strict-inputs`, a CLI falha se `receptor_pdb` ou `ligand_pdb` não existirem.

Sem `--strict-inputs`, o dry-run funciona mesmo que os PDBs ainda não tenham sido copiados para `inputs/`.

### Listar templates internos

```sh
uv run gmxflow templates
```

Lista os templates Jinja2 distribuídos com o pacote.

## Raiz do projeto e diretórios

O `gmxflow` usa como raiz do projeto a pasta onde está o `config.toml`.

Exemplo:

```sh
uv run gmxflow run --config /home/dev/simulacoes/example/config.toml --dry-run
```

Neste caso, a raiz do projeto é:

```text
/home/dev/simulacoes/example
```

Por padrão:

- entradas ficam em `inputs/`;
- templates internos ficam no pacote `gmxflow`, não no projeto criado;
- arquivos `.mdp` renderizados e intermediários ficam em `work/`;
- resultados finais devem ficar em `outputs/`.

A pipeline operacional usa subpastas dentro de `work/`:

```text
work/
  prep/
  topo/
  box/
  em/
  nvt/
  npt/
  prod/
  analysis/
```

Essa escolha evita um `base_dir` separado no TOML. Se você mover a pasta inteira do projeto, a configuração continua válida.

## Configuração TOML

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
uv run gmxflow run --config config.toml --until prepare
uv run gmxflow list-residues --config config.toml --chain A --resnames HIS,ASP,SER
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

## Testes

Rodar suíte:

```sh
uv run pytest
```

Rodar lint:

```sh
uv run ruff check
```

## Exemplo smoke

O projeto inclui um exemplo mínimo para validar a CLI, o dry-run e futuramente o executor com logs:

```text
examples/smoke_peptide_complex/
```

Ele usa dois peptídeos curtos de glicina e `simulation.profile = "smoke"`, que reduz NVT, NPT e produção para 10 passos. Esse exemplo serve para testar a ferramenta rapidamente; os resultados não são cientificamente interpretáveis.

Comandos:

```sh
uv run gmxflow validate --config examples/smoke_peptide_complex/config.toml
uv run gmxflow run --config examples/smoke_peptide_complex/config.toml --dry-run --strict-inputs
uv run gmxflow prepare-complex --config examples/smoke_peptide_complex/config.toml --force
uv run gmxflow render-templates --config examples/smoke_peptide_complex/config.toml --force
```

Para criar um projeto novo já em modo smoke:

```sh
uv run gmxflow startproject smoke_test --profile smoke
```

Para um fluxo de ligante pequeno com teste curto:

```sh
uv run gmxflow startproject ben_test \
  --ligand-kind small_molecule \
  --profile smoke \
  --gpu off
```
