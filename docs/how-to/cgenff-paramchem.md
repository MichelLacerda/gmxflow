# Como Preparar Ligante Pequeno Com CGenFF/ParamChem

O `gmxflow` não parametriza ligantes pequenos automaticamente. Para o fluxo CHARMM/CGenFF, ele consome arquivos já preparados externamente:

```text
ligand.mol2
ligand.str
```

## Fluxo Esperado

1. Prepare a estrutura 3D do ligante.
2. Gere um `.mol2` com nomes de átomos estáveis.
3. Envie esse `.mol2` para CGenFF/ParamChem/SilcsBio.
4. Baixe o `.str` gerado.
5. Baixe o force field CHARMM36/CGenFF para GROMACS.
6. Configure `input.ligand_mol2`, `input.ligand_str`, `input.ligand_resname` e `force_field.name`.
7. Rode `gmxflow prepare-ligand`.

Exemplo:

```toml
[input]
ligand_kind = "small_molecule"
ligand_pdb = "inputs/JZ4.pdb"
ligand_mol2 = "inputs/JZ4.mol2"
ligand_str = "inputs/JZ4.str"
ligand_resname = "JZ4"

[force_field]
name = "charmm36-feb2026_cgenff-5.0"
water = "tip3p"
```

## Como Obter O CHARMM36/CGenFF Para GROMACS

Baixe o port oficial para GROMACS no site do MacKerell Lab:

- <https://mackerell.umaryland.edu/charmm_ff.shtml#gromacs>

Na seção **CHARMM36 Files for GROMACS**, baixe:

```text
charmm36-feb2026_cgenff-5.0.ff.tgz
```

Esse é o pacote usado neste exemplo:

```toml
[force_field]
name = "charmm36-feb2026_cgenff-5.0"
water = "tip3p"
```

Para baixar por linha de comando a partir da raiz do exemplo:

```sh
cd examples/protein_ligand_complex
wget https://mackerell.umaryland.edu/download.php?filename=CHARMM_ff_params_files/charmm36-feb2026_cgenff-5.0.ff.tgz -O charmm36-feb2026_cgenff-5.0.ff.tgz
tar -xzf charmm36-feb2026_cgenff-5.0.ff.tgz
```

Depois da extração, a estrutura esperada é:

```text
examples/protein_ligand_complex/
  config.toml
  charmm36-feb2026_cgenff-5.0.ff/
    forcefield.itp
    aminoacids.rtp
    cgenff.rtp
    ...
```

O nome da pasta sem o sufixo `.ff` precisa bater com `force_field.name`. Se você usar outra versão, ajuste o `config.toml`. Exemplos:

```toml
name = "charmm36-feb2026_cgenff-5.0"
name = "charmm36-feb2026_cgenff-4.6"
name = "charmm36-feb2026_ljpme_cgenff-5.0"
```

Ponto crítico: a versão dos parâmetros CGenFF do force field precisa ser compatível com a versão usada para gerar o `.str` do ligante. Para este tutorial, mantenha CGenFF 5.0 no force field e gere o `.str` com CGenFF/ParamChem/SilcsBio compatível com CGenFF 5.0.

O diretório `.ff` é ignorado pelo `.gitignore` do exemplo. Para publicar ou compartilhar o projeto, prefira documentar o download em vez de versionar uma cópia completa do force field.

## Como Obter O `.mol2`

O `.mol2` normalmente é gerado com **Open Babel** a partir de uma estrutura do ligante. Ele é o arquivo que você envia para CGenFF/ParamChem/SilcsBio e também o arquivo que o `gmxflow` usa depois em `input.ligand_mol2`.

Regra prática:

- se você já tem a pose 3D do docking/cristalografia, preserve essas coordenadas;
- se você só tem SMILES/SDF 2D, gere coordenadas 3D antes de parametrizar;
- use o mesmo `.mol2` para gerar o `.str` e para rodar `gmxflow prepare-ligand`.

Instalação em Ubuntu/Debian:

```sh
sudo apt update
sudo apt install openbabel
```

Verifique:

```sh
obabel -V
```

### Caso 1: Preservar Uma Pose 3D Em PDB

Se você já tem uma pose 3D em PDB e quer preservar as coordenadas:

```sh
obabel inputs/JZ4.pdb -O inputs/JZ4.mol2
```

Esse é o caso mais comum quando o ligante veio de docking ou foi separado de uma estrutura cristalográfica. Não use `--gen3d` nesse caso, porque ele pode gerar uma nova conformação e perder a pose que você queria simular.

Se o CGenFF/SilcsBio recusar esse `.mol2`, tente incluir hidrogênios e cargas parciais:

```sh
obabel inputs/JZ4.pdb -O inputs/JZ4.mol2 -h --partialcharge gasteiger
```

Isso pode resolver arquivos PDB que vieram sem hidrogênios ou com informação química incompleta, mas não corrige todos os problemas de conectividade.

Depois, confira rapidamente:

```sh
head -40 inputs/JZ4.mol2
```

No bloco `@<TRIPOS>MOLECULE`, o nome da molécula deve ser coerente com o resname escolhido. Para este exemplo, usamos:

```toml
ligand_resname = "JZ4"
```

### Caso 2: Gerar 3D A Partir De SDF/SMILES

Se a entrada for 2D ou não tiver coordenadas 3D:

```sh
obabel inputs/JZ4.sdf -O inputs/JZ4.mol2 --gen3d
```

Também é possível partir de SMILES:

```sh
obabel -:"CCO" -O inputs/ligand.mol2 --gen3d
```

Use esse caminho apenas quando você ainda não tem uma pose 3D relevante. Para simulação de complexo proteína-ligante, normalmente você precisa posicionar esse ligante no sítio de ligação antes de rodar MD.

### Caso 3: Ajustar Protonação Ou Carga

Open Babel pode atribuir hidrogênios, mas protonação/carga precisam ser decididas quimicamente. Para adicionar hidrogênios em pH aproximado:

```sh
obabel inputs/JZ4.sdf -O inputs/JZ4.mol2 --gen3d -p 7.4
```

Use isso com cuidado. Para produção científica, confira protonação, tautômero e carga formal antes de enviar o `.mol2` ao CGenFF/ParamChem/SilcsBio.

### Checagens Antes De Enviar Ao CGenFF

Antes de gerar o `.str`, confira:

- se o `.mol2` tem todos os átomos esperados;
- se hidrogênios foram tratados como você queria;
- se a carga formal está correta;
- se a pose 3D é a pose que você pretende simular;
- se você guardou esse mesmo `.mol2` para usar depois no `gmxflow`.

Depois que o `.str` for gerado, não renomeie átomos no `.mol2` manualmente. Se precisar mudar nomes, protonação ou carga, gere novamente o `.mol2` e repita a parametrização.

## Erro No CGenFF/SilcsBio Ao Enviar `.mol2`

Uma falha comum no CGenFF By SilcsBio é:

```text
The uploaded Mol2 file cannot be processed by the CGenFF engine. Please try a different molecule. See the log file for more information
```

Isso geralmente significa que o `.mol2` gerado pelo Open Babel a partir do PDB não tem conectividade, ordem de ligação, aromaticidade, hidrogênios ou carga formal em um formato que o CGenFF consiga processar.

O motivo principal é que PDB não descreve química de ligação de forma confiável para ligantes pequenos. Ao converter PDB para MOL2, o Open Babel precisa inferir ligações e tipos atômicos. Às vezes essa inferência falha.

Primeira tentativa:

```sh
obabel inputs/JZ4.pdb -O inputs/JZ4.mol2 -h --partialcharge gasteiger
```

Depois confira:

```sh
head -80 inputs/JZ4.mol2
```

Procure sinais suspeitos:

- tipos atômicos `Du`;
- átomos duplicados;
- moléculas/resíduos extras;
- hidrogênios ausentes quando deveriam existir;
- cargas muito improváveis;
- metais, água, íons ou pedaços da proteína no arquivo do ligante.

Se ainda falhar, use uma fonte química mais adequada que o PDB. Para ligantes presentes no PDB, a RCSB fornece arquivos SDF do Chemical Component Dictionary. Para JZ4:

```sh
wget https://files.rcsb.org/ligands/download/JZ4_ideal.sdf -O inputs/JZ4_ideal.sdf
obabel inputs/JZ4_ideal.sdf -O inputs/JZ4.mol2 -h --partialcharge gasteiger
```

Esse caminho costuma resolver falhas do tipo "cannot be processed" porque o SDF ideal contém conectividade química melhor que o PDB extraído.

Ponto importante: o `JZ4_ideal.sdf` é bom para parametrização, mas pode não preservar a pose cristalográfica ou de docking. Para o `gmxflow`, mantenha a pose no PDB e use o MOL2/SDF para parametrização:

```toml
[input]
ligand_pdb = "inputs/JZ4.pdb"
ligand_mol2 = "inputs/JZ4.mol2"
ligand_str = "inputs/JZ4.str"
ligand_resname = "JZ4"
```

O `.mol2` usado para gerar o `.str` deve ser o mesmo configurado em `ligand_mol2`.

## Validações Feitas Pelo `gmxflow`

`gmxflow prepare-ligand` verifica:

- se `ligand_mol2` existe;
- se `ligand_str` existe;
- se `input.ligand_resname` bate com o `RESI` do `.str`;
- se a lista de átomos do `.mol2` bate com o `.str`;
- se o PDB gerado pelo conversor tem a contagem esperada de átomos;
- se há penalties CGenFF altos no `.str`.

## Problemas Comuns

### `RESI` diferente do `ligand_resname`

Corrija o `config.toml` ou gere novamente os arquivos com o resname correto.

### Átomos diferentes entre `.mol2` e `.str`

Use o mesmo `.mol2` para parametrização e para o `gmxflow`. Não renomeie átomos manualmente depois de gerar o `.str`.

### Penalties altos

Penalties altos não são apenas problema técnico. Eles indicam incerteza nos parâmetros.

Para produção científica:

- revise protonação e carga formal;
- confira tautômero;
- revise geometria;
- valide parâmetros críticos;
- documente os penalties.

## Referência

O fluxo é compatível com a lógica do tutorial Protein-Ligand Complex de Justin A. Lemkul:

- <http://www.mdtutorials.com/gmx/complex/>
